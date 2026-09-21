"""ADR-0079 Stage 2 (v0.63.0): Subsystem 境界のベクトル透過 (D-8) のテスト。

- ``Mux → Subsystem(Gain / Sum / Integrator) → Demux`` がスカラ展開版と bit-identical
- 明示 ``port_shape`` の一致 / 不一致、ネスト 2 段、Goto/From の内部透過
- Enabled (held / reset) / Triggered の held output が plan shape のゼロ / 直前値
- ``port_shape`` の JSON 互換 (キーなし = 継承、明示 ``()`` は書き出す)
- 内部だけにベクトル起点があるモデルも plan 経路で走る (has_shape_source の再帰)
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest

from flode import Simulator
from flode.blocks import (
    Constant,
    Demux,
    From,
    Gain,
    Goto,
    Integrator,
    Mux,
    PulseGenerator,
    Scope,
    Sine,
    Sum,
)
from flode.core.signals import has_shape_source
from flode.exceptions import SignalShapeError
from flode.subsystems import Enable, Inport, Outport, Subsystem, Trigger

TS = 0.01


def _sources(sim: Simulator, values: list[float], prefix: str) -> Mux:
    m = sim.add(Mux(n=len(values), id=f"{prefix}_mux"))
    for i, v in enumerate(values):
        s = sim.add(Sine(amplitude=v, frequency=0.4 + 0.1 * i, id=f"{prefix}_s{i}"))
        sim.connect(s, m, dst_idx=i)
    return m


def _make_sub(sub_id: str = "sub") -> Subsystem:
    """in0 → Gain(2) → Sum(+ in1) → Integrator → out0、Sum → out1。"""
    return Subsystem(
        blocks=[
            Inport(port_idx=0, id="in0"),
            Inport(port_idx=1, id="in1"),
            Gain(k=2.0, id="g"),
            Sum(signs="++", id="s"),
            Integrator(x0=0.0, id="integ"),
            Outport(port_idx=0, id="out0"),
            Outport(port_idx=1, id="out1"),
        ],
        connections=[
            {"src": "in0", "dst": "g"},
            {"src": "g", "dst": "s", "dst_idx": 0},
            {"src": "in1", "dst": "s", "dst_idx": 1},
            {"src": "s", "dst": "integ"},
            {"src": "integ", "dst": "out0"},
            {"src": "s", "dst": "out1"},
        ],
        id=sub_id,
    )


class TestVectorThroughSubsystem:
    def test_matches_scalar_expansion_bitwise(self) -> None:
        a = [1.0, -0.5, 0.25]
        b = [0.3, 0.6, -0.9]
        # 展開版: 各要素にスカラ Subsystem
        sim_e = Simulator(t_end=0.1, dt=TS, rtol=1e-9, atol=1e-12)
        ma = _sources(sim_e, a, "a")
        mb = _sources(sim_e, b, "b")
        da = sim_e.add(Demux(n=3, id="da"))
        db = sim_e.add(Demux(n=3, id="db"))
        out0 = sim_e.add(Mux(n=3, id="out0"))
        out1 = sim_e.add(Mux(n=3, id="out1"))
        sc_e = sim_e.add(Scope(n_inputs=2, id="sc"))
        sim_e.connect(ma, da)
        sim_e.connect(mb, db)
        for i in range(3):
            sub = sim_e.add(_make_sub(f"sub{i}"))
            sim_e.connect(da, sub, src_idx=i, dst_idx=0)
            sim_e.connect(db, sub, src_idx=i, dst_idx=1)
            sim_e.connect(sub, out0, src_idx=0, dst_idx=i)
            sim_e.connect(sub, out1, src_idx=1, dst_idx=i)
        sim_e.connect(out0, sc_e, dst_idx=0)
        sim_e.connect(out1, sc_e, dst_idx=1)
        sim_e.run()
        # ベクトル版
        sim_v = Simulator(t_end=0.1, dt=TS, rtol=1e-9, atol=1e-12)
        ma2 = _sources(sim_v, a, "a")
        mb2 = _sources(sim_v, b, "b")
        sub_v = sim_v.add(_make_sub("sub"))
        sc_v = sim_v.add(Scope(n_inputs=2, id="sc"))
        sim_v.connect(ma2, sub_v, dst_idx=0)
        sim_v.connect(mb2, sub_v, dst_idx=1)
        sim_v.connect(sub_v, sc_v, src_idx=0, dst_idx=0)
        sim_v.connect(sub_v, sc_v, src_idx=1, dst_idx=1)
        sim_v.run()
        assert sub_v.n_states == 3
        assert sc_v.n_columns == 6
        assert np.array_equal(np.asarray(sc_e.values), np.asarray(sc_v.values))

    def test_inner_resolution_and_plan(self) -> None:
        sim = Simulator(t_end=0.05, dt=TS)
        ma = _sources(sim, [1.0, 2.0], "a")
        c = sim.add(Constant(value=1.0, id="c"))
        sub = sim.add(_make_sub())
        sim.connect(ma, sub, dst_idx=0)
        sim.connect(c, sub, dst_idx=1)  # スカラ拡張
        res = sim.resolve_signals()
        inner = res.inner["sub"]
        assert inner.out_shape("in0", 0) == (2,)
        assert inner.out_shape("in1", 0) == ()
        assert inner.out_shape("s", 0) == (2,)
        assert inner.out_shape("integ", 0) == (2,)
        assert res.out_shape("sub", 0) == (2,) and res.out_shape("sub", 1) == (2,)
        payload = res.to_payload()
        assert payload["inner"]["sub"]["ports"]
        sim.run()
        assert sub._inner_signal_plan is not None
        assert sub.get_block("integ").n_states == 2

    def test_nested_two_levels(self) -> None:
        inner = Subsystem(
            blocks=[Inport(port_idx=0, id="i"), Gain(k=3.0, id="g"), Outport(port_idx=0, id="o")],
            connections=[{"src": "i", "dst": "g"}, {"src": "g", "dst": "o"}],
            id="inner",
        )
        outer = Subsystem(
            blocks=[Inport(port_idx=0, id="i"), inner, Outport(port_idx=0, id="o")],
            connections=[{"src": "i", "dst": "inner"}, {"src": "inner", "dst": "o"}],
            id="outer",
        )
        sim = Simulator(t_end=0.02, dt=TS)
        m = _sources(sim, [1.0, 2.0], "a")
        sim.add(outer)
        sc = sim.add(Scope(id="sc"))
        sim.connect(m, outer)
        sim.connect(outer, sc)
        res = sim.resolve_signals()
        assert res.inner["outer"].inner["inner"].out_shape("g", 0) == (2,)
        sim.run()
        v = np.asarray(sc.values)
        assert v.shape == (3, 2)
        np.testing.assert_allclose(v[0], [0.0, 0.0])

    def test_goto_from_inside_subsystem(self) -> None:
        sub = Subsystem(
            blocks=[
                Inport(port_idx=0, id="i"),
                Goto(tag="bus", id="gt"),
                From(tag="bus", id="fr"),
                Gain(k=2.0, id="g"),
                Outport(port_idx=0, id="o"),
            ],
            connections=[
                {"src": "i", "dst": "gt"},
                {"src": "fr", "dst": "g"},
                {"src": "g", "dst": "o"},
            ],
            id="sub",
        )
        sim = Simulator(t_end=0.02, dt=TS)
        c1 = sim.add(Constant(value=1.0, id="c1"))
        c2 = sim.add(Constant(value=2.0, id="c2"))
        m = sim.add(Mux(n=2, id="m"))
        sim.add(sub)
        sc = sim.add(Scope(id="sc"))
        sim.connect(c1, m, dst_idx=0)
        sim.connect(c2, m, dst_idx=1)
        sim.connect(m, sub)
        sim.connect(sub, sc)
        sim.run()
        np.testing.assert_array_equal(np.asarray(sc.values)[0], [2.0, 4.0])

    def test_inner_only_shape_source_takes_plan_path(self) -> None:
        """外側は全スカラでも、内部に Mux があれば plan 経路 (has_shape_source の再帰)。"""
        sub = Subsystem(
            blocks=[
                Inport(port_idx=0, id="i"),
                Mux(n=2, id="m"),
                Gain(k=[1.0, 2.0], id="g"),
                Demux(n=2, id="d"),
                Outport(port_idx=0, id="o"),
            ],
            connections=[
                {"src": "i", "dst": "m", "dst_idx": 0},
                {"src": "i", "dst": "m", "dst_idx": 1},
                {"src": "m", "dst": "g"},
                {"src": "g", "dst": "d"},
                {"src": "d", "src_idx": 1, "dst": "o"},
            ],
            id="sub",
        )
        sim = Simulator(t_end=0.02, dt=TS)
        c = sim.add(Constant(value=3.0, id="c"))
        sim.add(sub)
        sc = sim.add(Scope(id="sc"))
        sim.connect(c, sub)
        sim.connect(sub, sc)
        assert has_shape_source(sim) is True
        sim.run()
        assert sim._signal_plan is not None
        np.testing.assert_array_equal(np.asarray(sc.values)[:, 0], 6.0)


class TestDeclaredPortShapes:
    def test_explicit_matching_declaration_passes(self) -> None:
        sim = Simulator(t_end=0.02, dt=TS)
        m = _sources(sim, [1.0, 2.0], "a")
        sub = Subsystem(
            blocks=[
                Inport(port_idx=0, port_shape=(2,), id="i"),
                Outport(port_idx=0, port_shape=(2,), id="o"),
            ],
            connections=[{"src": "i", "dst": "o"}],
            id="sub",
        )
        sim.add(sub)
        sc = sim.add(Scope(id="sc"))
        sim.connect(m, sub)
        sim.connect(sub, sc)
        sim.run()
        assert sc.n_columns == 2

    def test_explicit_outport_mismatch_is_rejected(self) -> None:
        sim = Simulator(t_end=0.02, dt=TS)
        m = _sources(sim, [1.0, 2.0], "a")
        sub = Subsystem(
            blocks=[Inport(port_idx=0, id="i"), Outport(port_idx=0, port_shape=(3,), id="o")],
            connections=[{"src": "i", "dst": "o"}],
            id="sub",
        )
        sim.add(sub)
        sim.connect(m, sub)
        with pytest.raises(SignalShapeError, match="Outport 'o'"):
            sim.run()

    def test_explicit_scalar_declaration_rejects_vector(self) -> None:
        sim = Simulator(t_end=0.02, dt=TS)
        m = _sources(sim, [1.0, 2.0], "a")
        sub = Subsystem(
            blocks=[Inport(port_idx=0, port_shape=(), id="i"), Outport(port_idx=0, id="o")],
            connections=[{"src": "i", "dst": "o"}],
            id="sub",
        )
        sim.add(sub)
        sim.connect(m, sub)
        with pytest.raises(SignalShapeError, match="shape.mismatch"):
            sim.run()

    def test_port_shape_json_compat(self, tmp_path: Any) -> None:
        """キーなし = 継承 (None)、明示 () は書き出す。既存 (n,) 宣言も従来どおり。"""
        sub = Subsystem(
            blocks=[
                Inport(port_idx=0, id="inherit"),
                Inport(port_idx=1, port_shape=(), id="scalar"),
                Inport(port_idx=2, port_shape=(2,), id="vec"),
                Outport(port_idx=0, id="o"),
            ],
            connections=[{"src": "vec", "dst": "o"}],
            id="sub",
        )
        sim = Simulator(t_end=0.02, dt=TS)
        sim.add(sub)
        path = tmp_path / "sub.flw.json"
        sim.save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        by_id = {b["id"]: b for b in data["blocks"][0]["params"]["blocks"]}
        assert "port_shape" not in by_id["inherit"]["params"]
        assert by_id["scalar"]["params"]["port_shape"] == []
        assert by_id["vec"]["params"]["port_shape"] == [2]
        loaded = Simulator.load(path)
        lsub = loaded.get_block("sub")
        assert lsub.get_block("inherit").port_shape is None
        assert lsub.get_block("scalar").port_shape == ()
        assert lsub.get_block("vec").port_shape == (2,)


class TestControlBlocksWithVectors:
    @staticmethod
    def _enabled_sub(outputs_when_disabled: str) -> Subsystem:
        return Subsystem(
            blocks=[
                Inport(port_idx=0, id="i"),
                Gain(k=2.0, id="g"),
                Outport(port_idx=0, id="o"),
                Enable(outputs_when_disabled=outputs_when_disabled, id="en"),
            ],
            connections=[{"src": "i", "dst": "g"}, {"src": "g", "dst": "o"}],
            id="sub",
        )

    @pytest.mark.parametrize("policy", ["held", "reset"])
    def test_enabled_subsystem_vector_output(self, policy: str) -> None:
        sim = Simulator(t_end=0.05, dt=TS)
        c1 = sim.add(Constant(value=1.0, id="c1"))
        c2 = sim.add(Constant(value=2.0, id="c2"))
        m = sim.add(Mux(n=2, id="m"))
        en = sim.add(PulseGenerator(period=0.04, id="en"))  # 前半 ON、後半 OFF
        sub = sim.add(self._enabled_sub(policy))
        sc = sim.add(Scope(id="sc"))
        sim.connect(c1, m, dst_idx=0)
        sim.connect(c2, m, dst_idx=1)
        sim.connect(m, sub, dst_idx=0)
        sim.connect(en, sub, dst_idx=1)
        sim.connect(sub, sc)
        sim.run()
        v = np.asarray(sc.values)
        assert v.shape[1] == 2
        np.testing.assert_array_equal(v[0], [2.0, 4.0])  # enabled
        # OFF 区間 (t=0.02, 0.03、PulseGenerator の後半) の出力ポリシー:
        # reset → plan shape のゼロ、held → 直前の出力 (ベクトルのまま)
        assert float(en.output(0.03, np.zeros(0), np.zeros(0))[0]) <= 0.0
        expected = [0.0, 0.0] if policy == "reset" else [2.0, 4.0]
        np.testing.assert_array_equal(v[2], expected)
        np.testing.assert_array_equal(v[3], expected)

    def test_enable_port_must_be_scalar(self) -> None:
        sim = Simulator(t_end=0.05, dt=TS)
        m = _sources(sim, [1.0, 2.0], "a")
        c = sim.add(Constant(value=1.0, id="c"))
        sub = sim.add(self._enabled_sub("held"))
        sim.connect(c, sub, dst_idx=0)
        sim.connect(m, sub, dst_idx=1)  # enable にベクトル
        with pytest.raises(SignalShapeError, match="shape.control_port_not_scalar"):
            sim.run()

    def test_triggered_subsystem_holds_vector_output(self) -> None:
        sub = Subsystem(
            blocks=[
                Inport(port_idx=0, id="i"),
                Gain(k=1.0, id="g"),
                Outport(port_idx=0, id="o"),
                Trigger(trigger_type="rising", id="trig"),
            ],
            connections=[{"src": "i", "dst": "g"}, {"src": "g", "dst": "o"}],
            id="sub",
        )
        sim = Simulator(t_end=0.06, dt=TS)
        m = _vector_ramp(sim)
        pulse = sim.add(PulseGenerator(period=0.04, id="pulse"))
        sim.add(sub)
        sc = sim.add(Scope(id="sc"))
        sim.connect(m, sub, dst_idx=0)
        sim.connect(pulse, sub, dst_idx=1)
        sim.connect(sub, sc)
        sim.run()
        v = np.asarray(sc.values)
        assert v.shape == (7, 2)
        # 立ち上がり (t=0, 0.04) でサンプルし、それ以外はホールド
        np.testing.assert_allclose(v[0], [0.0, 0.0])
        np.testing.assert_allclose(v[1], v[0])
        np.testing.assert_allclose(v[4], [0.04, 0.08], atol=1e-12)
        np.testing.assert_allclose(v[5], v[4])


def _vector_ramp(sim: Simulator) -> Mux:
    from flode.blocks import Clock

    clk = sim.add(Clock(id="clk"))
    g = sim.add(Gain(k=2.0, id="g2"))
    m = sim.add(Mux(n=2, id="ramp"))
    sim.connect(clk, g)
    sim.connect(clk, m, dst_idx=0)
    sim.connect(g, m, dst_idx=1)
    return m
