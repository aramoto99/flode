"""ADR-0009 Atomic Subsystem のテスト。

* Inport / Outport の境界動作
* 内部結線・出力一致
* direct_feedthrough 自動推論 (内部 Inport→Outport 経路解析)
* 連続状態 / 離散状態管理
* sample_time 継承
* 内部代数ループ検出
* save / load round-trip
* schema 0.1 → 0.2 migration
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from pyflw import (
    AlgebraicLoopError,
    BlockSpecError,
    Inport,
    Outport,
    Simulator,
    Subsystem,
)
from pyflw.blocks import (
    Constant,
    Gain,
    Integrator,
    Scope,
    Step,
    Sum,
    UnitDelay,
)
from pyflw.core import persistence as _persistence
from pyflw.core.persistence import register_block_module, reset_block_module_allowlist


@pytest.fixture(autouse=True)
def _reset_persistence_state():
    register_block_module("tests.")
    saved = dict(_persistence._MIGRATIONS)
    try:
        yield
    finally:
        reset_block_module_allowlist()
        _persistence._MIGRATIONS.clear()
        _persistence._MIGRATIONS.update(saved)
        _persistence._register_builtin_migrations()


def _build_gain_subsystem(k: float, id: str = "sub") -> Subsystem:
    """``y = k * u`` を内部で実装する Subsystem。"""
    sub = Subsystem(n_inputs=1, n_outputs=1, id=id)
    sub.add(Inport(port_idx=0, id=f"{id}_in"))
    sub.add(Gain(k=k, id=f"{id}_g"))
    sub.add(Outport(port_idx=0, id=f"{id}_out"))
    sub.connect(f"{id}_in", f"{id}_g")
    sub.connect(f"{id}_g", f"{id}_out")
    return sub


# ---------------------------------------------------------------
# 基本動作
# ---------------------------------------------------------------


class TestSubsystemBasic:
    def test_combinational_gain_subsystem(self):
        """``y = k * u`` Subsystem が外部から見て Gain と同等の振る舞い。"""
        sub = _build_gain_subsystem(k=2.0)
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(Constant(value=3.0, id="src"))
        sim.add(sub)
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "sub")
        sim.connect("sub", "scope")
        sim.run()
        np.testing.assert_allclose(sim.get_block("scope").values[:, 0], 6.0)

    def test_direct_feedthrough_inferred_true(self):
        """combinational 経路のみの Subsystem は direct_feedthrough=True。"""
        sub = _build_gain_subsystem(k=2.0)
        sim = Simulator(t_end=0.01, dt=0.01)
        sim.add(sub)
        # _build を発火させるため _execution_order を呼ぶ
        sim._execution_order()
        assert sub.direct_feedthrough is True

    def test_direct_feedthrough_inferred_false_with_integrator(self):
        """内部に Integrator (df=False) がある経路は Subsystem.df=False。"""
        sub = Subsystem(n_inputs=1, n_outputs=1, id="sub")
        sub.add(Inport(port_idx=0, id="sub_in"))
        sub.add(Integrator(x0=0.0, id="sub_int"))
        sub.add(Outport(port_idx=0, id="sub_out"))
        sub.connect("sub_in", "sub_int")
        sub.connect("sub_int", "sub_out")
        sim = Simulator(t_end=0.01, dt=0.01)
        sim.add(sub)
        sim._execution_order()
        assert sub.direct_feedthrough is False

    def test_continuous_state_integration(self):
        """Integrator を内蔵した Subsystem の連続状態が正しく統合される。"""
        sub = Subsystem(n_inputs=1, n_outputs=1, id="sub")
        sub.add(Inport(port_idx=0, id="sub_in"))
        sub.add(Integrator(x0=0.0, id="sub_int"))
        sub.add(Outport(port_idx=0, id="sub_out"))
        sub.connect("sub_in", "sub_int")
        sub.connect("sub_int", "sub_out")

        sim = Simulator(t_end=1.0, dt=0.01, rtol=1e-9, atol=1e-12)
        sim.add(Constant(value=1.0, id="src"))
        sim.add(sub)
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "sub")
        sim.connect("sub", "scope")
        sim.run()

        # ∫ 1 dt from 0 to 1 = 1.0
        assert sim.get_block("scope").values[-1, 0] == pytest.approx(1.0, rel=1e-3)

    def test_discrete_state_through_subsystem(self):
        """UnitDelay を内蔵した Subsystem が離散更新を正しく繰り返す。"""
        sub = Subsystem(n_inputs=1, n_outputs=1, id="sub")
        sub.add(Inport(port_idx=0, id="sub_in"))
        sub.add(UnitDelay(sample_time=0.01, x0=0.0, id="sub_delay"))
        sub.add(Outport(port_idx=0, id="sub_out"))
        sub.connect("sub_in", "sub_delay")
        sub.connect("sub_delay", "sub_out")

        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(Constant(value=2.0, id="src"))
        sim.add(sub)
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "sub")
        sim.connect("sub", "scope")
        sim.run()

        values = sim.get_block("scope").values[:, 0]
        assert values[0] == pytest.approx(0.0)  # x0
        for v in values[1:]:
            assert v == pytest.approx(2.0)


# ---------------------------------------------------------------
# 多入力多出力 Subsystem
# ---------------------------------------------------------------


class TestSubsystemMultiPort:
    def test_2_in_1_out_sum(self):
        """2 入力を内部 Sum で合算し 1 出力に出す Subsystem。"""
        sub = Subsystem(n_inputs=2, n_outputs=1, id="sub")
        sub.add(Inport(port_idx=0, id="sub_in0"))
        sub.add(Inport(port_idx=1, id="sub_in1"))
        sub.add(Sum(signs="++", id="sub_sum"))
        sub.add(Outport(port_idx=0, id="sub_out"))
        sub.connect("sub_in0", "sub_sum", dst_idx=0)
        sub.connect("sub_in1", "sub_sum", dst_idx=1)
        sub.connect("sub_sum", "sub_out")

        sim = Simulator(t_end=0.01, dt=0.01)
        sim.add(Constant(value=1.5, id="a"))
        sim.add(Constant(value=2.5, id="b"))
        sim.add(sub)
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("a", "sub", dst_idx=0)
        sim.connect("b", "sub", dst_idx=1)
        sim.connect("sub", "scope")
        sim.run()
        np.testing.assert_allclose(sim.get_block("scope").values[:, 0], 4.0)


# ---------------------------------------------------------------
# 例外パス
# ---------------------------------------------------------------


class TestSubsystemErrors:
    def test_inport_count_mismatch(self):
        """``n_inputs`` と Inport 数が一致しないとエラー。"""
        sub = Subsystem(n_inputs=2, n_outputs=1, id="sub")
        sub.add(Inport(port_idx=0, id="in0"))
        sub.add(Outport(port_idx=0, id="out0"))
        sim = Simulator()
        sim.add(sub)
        with pytest.raises(BlockSpecError, match="found 1 Inport"):
            sim._execution_order()

    def test_outport_count_mismatch(self):
        sub = Subsystem(n_inputs=1, n_outputs=2, id="sub")
        sub.add(Inport(port_idx=0, id="in0"))
        sub.add(Outport(port_idx=0, id="out0"))
        sim = Simulator()
        sim.add(sub)
        with pytest.raises(BlockSpecError, match="found 1 Outport"):
            sim._execution_order()

    def test_inport_idx_gap(self):
        """Inport port_idx が連番でないとエラー。"""
        sub = Subsystem(n_inputs=2, n_outputs=1, id="sub")
        sub.add(Inport(port_idx=0, id="in0"))
        sub.add(Inport(port_idx=2, id="in2"))  # gap (1 が無い)
        sub.add(Outport(port_idx=0, id="out0"))
        sim = Simulator()
        sim.add(sub)
        with pytest.raises(BlockSpecError, match=r"do not cover \[0, 2\)"):
            sim._execution_order()

    def test_inner_algebraic_loop_detected(self):
        """Subsystem 内部の代数ループが ``AlgebraicLoopError`` で検出される。"""
        sub = Subsystem(n_inputs=1, n_outputs=1, id="sub")
        sub.add(Inport(port_idx=0, id="in0"))
        sub.add(Gain(k=2.0, id="g1"))
        sub.add(Gain(k=3.0, id="g2"))
        sub.add(Outport(port_idx=0, id="out0"))
        # g1 → g2 → g1 のループ (in0 は使わない)
        sub.connect("g1", "g2")
        sub.connect("g2", "g1")
        sub.connect("g2", "out0")

        sim = Simulator()
        sim.add(sub)
        with pytest.raises(AlgebraicLoopError, match="inside Subsystem"):
            sim._execution_order()

    def test_duplicate_inner_id_raises(self):
        sub = Subsystem(n_inputs=1, n_outputs=1, id="sub")
        sub.add(Inport(port_idx=0, id="dup"))
        with pytest.raises(BlockSpecError, match="already exists"):
            sub.add(Gain(k=1.0, id="dup"))

    def test_inport_negative_idx_raises(self):
        with pytest.raises(BlockSpecError, match="non-negative"):
            Inport(port_idx=-1)

    def test_continuous_discrete_mixed_subsystem_rejected(self):
        """Phase 2 では Subsystem 内部の連続+離散混在を拒否する
        (code-reviewer MUST #1 修正)。"""
        sub = Subsystem(n_inputs=1, n_outputs=1, id="sub")
        sub.add(Inport(port_idx=0, id="sub_in"))
        sub.add(Integrator(x0=0.0, id="sub_int"))  # 連続
        sub.add(UnitDelay(sample_time=0.01, x0=0.0, id="sub_d"))  # 離散
        sub.add(Outport(port_idx=0, id="sub_out"))
        sub.connect("sub_in", "sub_int")
        sub.connect("sub_int", "sub_d")
        sub.connect("sub_d", "sub_out")
        sim = Simulator()
        sim.add(sub)
        with pytest.raises(BlockSpecError, match="mixing continuous-state and discrete-state"):
            sim._execution_order()


class TestSubsystemNested:
    """ネスト Subsystem (深さ 2) のカバレッジ (code-reviewer MUST #2 修正)。"""

    def test_nested_subsystem_runs(self):
        """``Subsystem(Gain) `` を内側に持つ ``Subsystem`` が外側から正しく動く。"""
        # 内側 Subsystem: u → Gain(k=2) → y
        inner = Subsystem(n_inputs=1, n_outputs=1, id="inner")
        inner.add(Inport(port_idx=0, id="inner_in"))
        inner.add(Gain(k=2.0, id="inner_g"))
        inner.add(Outport(port_idx=0, id="inner_out"))
        inner.connect("inner_in", "inner_g")
        inner.connect("inner_g", "inner_out")

        # 外側 Subsystem: u → inner → Gain(k=3) → y
        outer = Subsystem(n_inputs=1, n_outputs=1, id="outer")
        outer.add(Inport(port_idx=0, id="outer_in"))
        outer.add(inner)
        outer.add(Gain(k=3.0, id="outer_g"))
        outer.add(Outport(port_idx=0, id="outer_out"))
        outer.connect("outer_in", "inner")
        outer.connect("inner", "outer_g")
        outer.connect("outer_g", "outer_out")

        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(Constant(value=1.0, id="src"))
        sim.add(outer)
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "outer")
        sim.connect("outer", "scope")
        sim.run()
        # 1 * 2 * 3 = 6
        np.testing.assert_allclose(sim.get_block("scope").values[:, 0], 6.0)

    def test_nested_subsystem_direct_feedthrough_inferred_recursively(self):
        """ネスト内側に Integrator がある場合、外側の direct_feedthrough も False。"""
        inner = Subsystem(n_inputs=1, n_outputs=1, id="inner")
        inner.add(Inport(port_idx=0, id="inner_in"))
        inner.add(Integrator(x0=0.0, id="inner_int"))
        inner.add(Outport(port_idx=0, id="inner_out"))
        inner.connect("inner_in", "inner_int")
        inner.connect("inner_int", "inner_out")

        outer = Subsystem(n_inputs=1, n_outputs=1, id="outer")
        outer.add(Inport(port_idx=0, id="outer_in"))
        outer.add(inner)
        outer.add(Outport(port_idx=0, id="outer_out"))
        outer.connect("outer_in", "inner")
        outer.connect("inner", "outer_out")

        sim = Simulator()
        sim.add(outer)
        sim._execution_order()
        # 内側 Subsystem の df=False → 外側の Inport→Outport 経路に df=False が
        # 含まれるため、外側 Subsystem も df=False
        assert inner.direct_feedthrough is False
        assert outer.direct_feedthrough is False


# ---------------------------------------------------------------
# 永続化 (save / load round-trip)
# ---------------------------------------------------------------


class TestSubsystemPersistence:
    def test_round_trip_simple_gain_subsystem(self, tmp_path):
        sub = _build_gain_subsystem(k=2.5)
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(Constant(value=4.0, id="src"))
        sim.add(sub)
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "sub")
        sim.connect("sub", "scope")

        path = tmp_path / "sub.flw.json"
        sim.save(path)
        sim2 = Simulator.load(path)
        sim.run()
        sim2.run()
        np.testing.assert_allclose(
            sim.get_block("scope").values,
            sim2.get_block("scope").values,
            rtol=1e-9,
            atol=1e-12,
        )

    def test_round_trip_with_integrator(self, tmp_path):
        sub = Subsystem(n_inputs=1, n_outputs=1, id="sub")
        sub.add(Inport(port_idx=0, id="sub_in"))
        sub.add(Integrator(x0=0.5, id="sub_int"))
        sub.add(Outport(port_idx=0, id="sub_out"))
        sub.connect("sub_in", "sub_int")
        sub.connect("sub_int", "sub_out")

        sim = Simulator(t_end=1.0, dt=0.01, rtol=1e-9, atol=1e-12)
        sim.add(Step(step_time=0.0, final_value=1.0, id="src"))
        sim.add(sub)
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "sub")
        sim.connect("sub", "scope")

        path = tmp_path / "sub_int.flw.json"
        sim.save(path)
        sim2 = Simulator.load(path)
        sim.run()
        sim2.run()
        np.testing.assert_allclose(
            sim.get_block("scope").values,
            sim2.get_block("scope").values,
            rtol=1e-9,
            atol=1e-12,
        )

    def test_schema_version_is_current_when_subsystem_present(self, tmp_path):
        sim = Simulator(t_end=0.01, dt=0.01)
        sim.add(_build_gain_subsystem(k=1.0))
        path = tmp_path / "v.flw.json"
        sim.save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        # save は CURRENT_SCHEMA_VERSION を使う (ADR-0021 で 0.6 に bump)
        assert data["schema_version"] == "0.6"

    def test_loads_old_schema_0_1_via_migration(self, tmp_path):
        """``schema_version="0.1"`` の旧ファイルが migration 経由で読める。"""
        payload = {
            "schema_version": "0.1",
            "metadata": {"created_at": "2026-05-05T00:00:00Z", "tool": "pyflw 0.1.0"},
            "simulator": {
                "t_end": 0.05,
                "dt": 0.01,
                "solver": "RK45",
                "rtol": 1e-6,
                "atol": 1e-9,
                "dt_base": None,
            },
            "blocks": [
                {
                    "id": "src",
                    "type": "pyflw.blocks.sources.Constant",
                    "params": {"value": 1.0},
                },
                {
                    "id": "g",
                    "type": "pyflw.blocks.mathops.Gain",
                    "params": {"k": 2.0},
                },
            ],
            "connections": [{"src": "src", "src_idx": 0, "dst": "g", "dst_idx": 0}],
        }
        path = tmp_path / "old.flw.json"
        path.write_text(json.dumps(payload), encoding="utf-8")

        sim = Simulator.load(path)
        assert sim.t_end == 0.05
        assert [b.id for b in sim.blocks] == ["src", "g"]


# ---------------------------------------------------------------
# sample_time 継承 (ST-A)
# ---------------------------------------------------------------


class TestSubsystemSampleTimeInheritance:
    def test_sample_time_inherits_internal_min(self):
        """内部に sample_time=0.01 の UnitDelay があれば Subsystem の
        sample_time も 0.01 (内部最小値継承)。"""
        sub = Subsystem(n_inputs=1, n_outputs=1, id="sub")
        sub.add(Inport(port_idx=0, id="in0"))
        sub.add(UnitDelay(sample_time=0.01, x0=0.0, id="ud"))
        sub.add(Outport(port_idx=0, id="out0"))
        sub.connect("in0", "ud")
        sub.connect("ud", "out0")
        sim = Simulator()
        sim.add(sub)
        sim._execution_order()
        assert sub.sample_time == pytest.approx(0.01)

    def test_sample_time_none_when_continuous_only(self):
        """内部が連続のみなら Subsystem.sample_time も None。"""
        sub = _build_gain_subsystem(k=1.0)
        sim = Simulator()
        sim.add(sub)
        sim._execution_order()
        assert sub.sample_time is None
