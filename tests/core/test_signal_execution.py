"""ADR-0079 Stage 1: 信号面 plan での実行テスト (AC-1 / AC-2)。

- AC-1: 全ポート `()` のモデルは v0.61.0 と bit-identical かつ `_step` 経路
  (基準 npz + 経路スパイ。基準モデルは `_dtype_baseline_models.py` を共有)
- AC-2: 予測 shape == 実行 shape (全ステップ突合、`_dtype_instrumented_run.py`)
- Goto / From のベクトル透過 run、Merge / Switch のベクトル run、
  ホールド値 (初回 fire 前) の shape
"""

from __future__ import annotations

from unittest import mock

import numpy as np
import pytest

from flode import Simulator
from flode.blocks import (
    Cast,
    Constant,
    Demux,
    From,
    Gain,
    Goto,
    Integrator,
    Merge,
    Mux,
    Scope,
    Sum,
    Switch,
    Terminator,
    UnitDelay,
)
from flode.core import signals
from tests.core import _dtype_baseline_models as baseline
from tests.core._dtype_instrumented_run import assert_signal_prediction_matches_execution


def _sim() -> Simulator:
    return Simulator(t_end=0.05, dt=0.01)


def _mux3(sim: Simulator, prefix: str = "m") -> Mux:
    m = sim.add(Mux(n=3, id=prefix))
    for i in range(3):
        c = sim.add(Constant(value=float(i + 1), id=f"{prefix}_c{i}"))
        sim.connect(c, m, dst_idx=i)
    return m


# ---------------------------------------------------------------------------
# AC-1: 全ポート () のモデルは不変
# ---------------------------------------------------------------------------


class TestScalarModelsUnchanged:
    @pytest.mark.parametrize("name_builder", baseline.builders(), ids=lambda nb: nb[0])
    def test_scalar_model_takes_step_path_and_never_resolves(
        self, name_builder: tuple[str, baseline.Builder]
    ) -> None:
        _name, builder = name_builder
        sim, scope = builder()
        called = {"step": 0, "step_vector": 0}
        orig_step = Simulator._step
        orig_step_v = Simulator._step_vector

        def spy_step(self, *a, **k):  # type: ignore[no-untyped-def]
            called["step"] += 1
            return orig_step(self, *a, **k)

        def spy_step_v(self, *a, **k):  # type: ignore[no-untyped-def]
            called["step_vector"] += 1
            return orig_step_v(self, *a, **k)

        with (
            mock.patch.object(Simulator, "_step", spy_step),
            mock.patch.object(Simulator, "_step_vector", spy_step_v),
            mock.patch.object(
                signals, "resolve_for_execution", side_effect=AssertionError("must not resolve")
            ),
        ):
            sim.run()
        assert called["step"] > 0
        assert called["step_vector"] == 0
        assert sim._signal_plan is None
        assert len(scope.times) > 0

    def test_baseline_values_match_v0_61(self) -> None:
        """基準 npz (v0.61.0 で採取) と times は厳密一致、values は build 差ノイズ以下。"""
        with np.load(baseline.BASELINE_NPZ) as npz:
            for name, builder in baseline.builders():
                sim, scope = builder()
                sim.run()
                times = np.asarray(list(scope.times), dtype=np.float64)
                values = np.asarray(scope.values, dtype=np.float64)
                assert np.array_equal(times, npz[f"{name}_times"])
                if name == "continuous":
                    np.testing.assert_allclose(values, npz[f"{name}_values"], rtol=1e-9, atol=1e-12)
                else:
                    assert np.array_equal(values, npz[f"{name}_values"])


# ---------------------------------------------------------------------------
# AC-2: 予測 == 実行 (shape)
# ---------------------------------------------------------------------------


class TestPredictionMatchesExecution:
    def test_elementwise_vector_chain(self) -> None:
        sim = _sim()
        m = _mux3(sim)
        g = sim.add(Gain(k=2.0, id="g"))
        s = sim.add(Sum(signs="++", id="s"))
        c = sim.add(Constant(value=0.5, id="c"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(m, g)
        sim.connect(g, s, dst_idx=0)
        sim.connect(c, s, dst_idx=1)
        sim.connect(s, sc)
        assert_signal_prediction_matches_execution(sim)
        np.testing.assert_allclose(np.asarray(sc.values)[0], [2.5, 4.5, 6.5])

    def test_matrix_gain_and_demux(self) -> None:
        sim = _sim()
        m = _mux3(sim)
        k = [[1.0, 0.0, 0.0], [0.0, 2.0, 0.0]]
        g = sim.add(Gain(k=k, multiplication="matrix-Ku", id="g"))
        d = sim.add(Demux(n=2, id="d"))
        sc0 = sim.add(Scope(id="sc0"))
        sc1 = sim.add(Scope(id="sc1"))
        sim.connect(m, g)
        sim.connect(g, d)
        sim.connect(d, sc0, src_idx=0)
        sim.connect(d, sc1, src_idx=1)
        assert_signal_prediction_matches_execution(sim)
        assert float(np.asarray(sc0.values)[0, 0]) == 1.0
        assert float(np.asarray(sc1.values)[0, 0]) == 4.0

    def test_switch_and_merge_with_vectors(self) -> None:
        sim = _sim()
        a = _mux3(sim, "a")
        b = _mux3(sim, "b")
        ctl = sim.add(Constant(value=0.0, id="ctl"))
        sw = sim.add(Switch(id="sw"))
        mg = sim.add(Merge(n_inputs=2, id="mg"))
        zero = sim.add(Gain(k=0.0, id="zero"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(a, sw, dst_idx=0)
        sim.connect(ctl, sw, dst_idx=1)
        sim.connect(b, sw, dst_idx=2)
        sim.connect(a, zero)  # 全要素 0 = initial_value → 非デフォルトの sw 側が選ばれる
        sim.connect(zero, mg, dst_idx=0)
        sim.connect(sw, mg, dst_idx=1)
        sim.connect(mg, sc)
        assert_signal_prediction_matches_execution(sim)
        np.testing.assert_allclose(np.asarray(sc.values)[0], [1.0, 2.0, 3.0])

    def test_goto_from_vector_and_dtype(self) -> None:
        sim = _sim()
        m = _mux3(sim)
        cast = sim.add(Cast(dtype="int32", id="cast"))
        gt = sim.add(Goto(tag="bus", id="gt"))
        fr = sim.add(From(tag="bus", id="fr"))
        g = sim.add(Gain(k=3.0, id="g"))
        term = sim.add(Terminator(id="term"))
        sim.connect(m, cast)
        sim.connect(cast, gt)
        sim.connect(fr, g)
        sim.connect(g, term)
        assert_signal_prediction_matches_execution(sim)

    def test_discrete_scalar_block_inside_vector_model(self) -> None:
        """状態ブロックは () 固定のまま、ベクトル経路と同居できる (advance の u は 1D)。"""
        sim = _sim()
        m = _mux3(sim)
        d = sim.add(Demux(n=3, id="d"))
        ud = sim.add(UnitDelay(sample_time=0.01, x0=0.0, id="ud"))
        integ = sim.add(Integrator(x0=0.0, id="integ"))
        sc = sim.add(Scope(n_inputs=2, id="sc"))
        sim.connect(m, d)
        sim.connect(d, ud, src_idx=0)
        sim.connect(d, integ, src_idx=1)
        sim.connect(ud, sc, dst_idx=0)
        sim.connect(integ, sc, dst_idx=1)
        assert_signal_prediction_matches_execution(sim)
        vals = np.asarray(sc.values)
        assert vals[0, 0] == 0.0 and vals[-1, 0] == 1.0


# ---------------------------------------------------------------------------
# ホールド値 / 記録
# ---------------------------------------------------------------------------


class TestHoldAndRecord:
    def test_from_hold_value_uses_plan_shape(self) -> None:
        """初回 fire 前の From のホールド値は plan の shape でゼロになる。"""
        sim = _sim()
        m = _mux3(sim)
        gt = sim.add(Goto(tag="bus", id="gt"))
        fr = sim.add(From(tag="bus", id="fr"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(m, gt)
        sim.connect(fr, sc)
        sim.run()
        assert fr._plan_out_shape == (3,)
        # Triggered / Enabled 内の Goto が未 fire の状態を模す
        gt._last_input = None
        gt._hold_before_first_run = True
        assert fr._held_value().shape == (3,)

    def test_scope_records_matrix_in_c_order(self) -> None:
        from flode.core.block import Block

        class _MatrixSrc(Block):
            def __init__(self, *, id: str | None = None) -> None:
                super().__init__(id=id, n_inputs=0, n_outputs=1, port_shapes_out=[(2, 2)])

            def output_v(self, t, x, u):  # type: ignore[no-untyped-def]
                return (np.array([[1.0, 2.0], [3.0, 4.0]]),)

        sim = _sim()
        src = sim.add(_MatrixSrc(id="src"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(src, sc)
        sim.run()
        assert sc.n_columns == 4
        assert sc.column_labels == ["in0[0,0]", "in0[0,1]", "in0[1,0]", "in0[1,1]"]
        np.testing.assert_array_equal(np.asarray(sc.values)[0], [1.0, 2.0, 3.0, 4.0])

    def test_scope_mixed_scalar_and_vector_ports(self) -> None:
        sim = _sim()
        m = _mux3(sim)
        c = sim.add(Constant(value=9.0, id="c"))
        sc = sim.add(Scope(n_inputs=2, labels=["v", "s"], id="sc"))
        sim.connect(m, sc, dst_idx=0)
        sim.connect(c, sc, dst_idx=1)
        sim.run()
        assert sc.column_labels == ["v[0]", "v[1]", "v[2]", "s"]
        np.testing.assert_array_equal(np.asarray(sc.values)[0], [1.0, 2.0, 3.0, 9.0])
        # WebSocket / results API の形式は不変 (list of rows)
        assert np.asarray(sc.values).tolist()[0] == [1.0, 2.0, 3.0, 9.0]
