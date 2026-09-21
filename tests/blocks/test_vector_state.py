"""ADR-0079 Stage 2 (v0.63.0): ベクトル状態ブロック (`VectorStateMixin`) のテスト。

- スカラ入力で kernel (`*_v`) と SM-A (`output` / `derivative` / `update` / `advance`) が
  bit-identical (7 クラス parametrize)
- ``Mux → 状態ブロック → Demux`` がスカラ n 本と bit-identical (7a' のスカラ拡張)
- 配列 ``x0`` の round-trip と、``x0`` shape と入力 shape の不一致 = build エラー
- ``linearize`` のベクトル状態 (state_names は flat index)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from flode import Simulator
from flode.blocks import (
    Constant,
    Demux,
    Derivative,
    DiscreteIntegrator,
    Gain,
    Integrator,
    Mux,
    RateLimiter,
    RateTransition,
    Scope,
    Sine,
    UnitDelay,
    ZeroOrderHoldDirect,
)
from flode.blocks._vector_state import VectorStateMixin
from flode.core.signals import has_shape_source
from flode.exceptions import BlockSpecError, SignalShapeError

TS = 0.01


def _resolved(blk: Any, ts: float | None = TS) -> Any:
    blk._resolved_sample_time = ts
    return blk


_CASES: list[tuple[str, Any]] = [
    ("Integrator", lambda: Integrator(x0=0.25)),
    ("Derivative", lambda: Derivative(N=100.0, x0=0.5)),
    ("UnitDelay", lambda: _resolved(UnitDelay(sample_time=TS, x0=0.75))),
    ("DiscreteIntegrator", lambda: _resolved(DiscreteIntegrator(sample_time=TS, gain=2.0, x0=0.5))),
    (
        "RateTransition",
        lambda: _resolved(
            RateTransition(input_sample_time=TS, output_sample_time=2 * TS, x0=0.5), 2 * TS
        ),
    ),
    ("ZeroOrderHoldDirect", lambda: _resolved(ZeroOrderHoldDirect(sample_time=TS, x0=0.5))),
    (
        "RateLimiter",
        lambda: _resolved(RateLimiter(sample_time=TS, rising_slew_rate=10.0, x0=0.5)),
    ),
]


class TestScalarParity:
    @pytest.mark.parametrize("case", _CASES, ids=[c[0] for c in _CASES])
    def test_kernels_match_scalar_api_bitwise(self, case: tuple[str, Any]) -> None:
        _name, factory = case
        blk = factory()
        assert isinstance(blk, VectorStateMixin)
        assert blk.state_shape == ()
        x = np.linspace(0.3, 0.9, blk.n_states)
        u_1d = np.array([1.7])
        u_v = (np.asarray(1.7),)
        t = 0.03
        (y_v,) = blk.output_v(t, x, u_v)
        assert np.asarray(y_v).shape == ()
        assert np.array_equal(np.asarray(y_v), blk.output(t, x, u_1d)[0])
        assert np.array_equal(blk.derivative_v(t, x, u_v), blk.derivative(t, x, u_1d))
        assert np.array_equal(blk.update_v(t, x, u_v), blk.update(t, x, u_1d))
        assert np.array_equal(blk.advance_v(t, x, u_v), blk.advance(t, x, u_1d))

    def test_leaf_classes_keep_scalar_api_in_dict(self) -> None:
        for _name, factory in _CASES:
            cls = type(factory())
            assert "output" in cls.__dict__
            assert "output_v" not in cls.__dict__


class TestStateShape:
    def test_scalar_x0_extends_to_input_shape(self) -> None:
        integ = Integrator(x0=1.0)
        assert integ.n_states == 1 and integ._params["x0"] == 1.0
        integ._apply_state_shape((3,))
        assert integ.n_states == 3
        assert integ.state_shape == (3,)
        np.testing.assert_array_equal(integ.x0, [1.0, 1.0, 1.0])
        assert integ._params["x0"] == 1.0  # ユーザー指定値は不変 (D-2)

    def test_two_state_block_doubles_flat_layout(self) -> None:
        ud = UnitDelay(sample_time=TS, x0=[1.0, 2.0])
        assert ud.n_states == 4
        np.testing.assert_array_equal(ud.x0, [1.0, 2.0, 1.0, 2.0])
        assert ud._x0_shape == (2,)
        np.testing.assert_array_equal(np.asarray(ud._params["x0"]), [1.0, 2.0])

    def test_array_x0_is_a_shape_source(self) -> None:
        sim = Simulator(t_end=0.05, dt=TS)
        sim.add(Integrator(x0=np.zeros(3)))
        assert has_shape_source(sim) is True
        sim2 = Simulator(t_end=0.05, dt=TS)
        sim2.add(Integrator(x0=0.0))
        assert has_shape_source(sim2) is False

    def test_array_x0_rejects_conflicting_state_shape(self) -> None:
        integ = Integrator(x0=[1.0, 2.0])
        with pytest.raises(BlockSpecError, match="does not match"):
            integ._apply_state_shape((3,))

    def test_non_numeric_x0_rejected(self) -> None:
        with pytest.raises(BlockSpecError, match="numeric"):
            Integrator(x0="abc")  # type: ignore[arg-type]

    def test_matrix_state(self) -> None:
        integ = Integrator(x0=np.ones((2, 2)))
        assert integ.n_states == 4 and integ.state_shape == (2, 2)
        u = (np.array([[1.0, 2.0], [3.0, 4.0]]),)
        np.testing.assert_array_equal(integ.derivative_v(0.0, integ.x0, u), [1.0, 2.0, 3.0, 4.0])
        (y,) = integ.output_v(0.0, integ.x0, u)
        assert y.shape == (2, 2)


def _mux(sim: Simulator, values: list[float], prefix: str) -> Mux:
    m = sim.add(Mux(n=len(values), id=f"{prefix}_mux"))
    for i, v in enumerate(values):
        s = sim.add(Sine(amplitude=v, frequency=0.5 + 0.2 * i, id=f"{prefix}_s{i}"))
        sim.connect(s, m, dst_idx=i)
    return m


_STATE_FACTORIES: list[tuple[str, Any]] = [
    ("Integrator", lambda: Integrator(x0=0.1)),
    ("Derivative", lambda: Derivative(N=50.0)),
    ("UnitDelay", lambda: UnitDelay(sample_time=TS, x0=0.2)),
    ("DiscreteIntegrator", lambda: DiscreteIntegrator(sample_time=TS, gain=1.5, x0=0.1)),
    (
        "RateTransition",
        lambda: RateTransition(input_sample_time=TS, output_sample_time=2 * TS, x0=0.3),
    ),
    ("ZeroOrderHoldDirect", lambda: ZeroOrderHoldDirect(sample_time=TS, x0=0.0)),
    ("RateLimiter", lambda: RateLimiter(sample_time=TS, rising_slew_rate=5.0, x0=0.0)),
]


class TestVectorEqualsExpanded:
    """Mux → 状態ブロック (ベクトル状態) → Demux が、スカラ n 本と bit-identical。"""

    @pytest.mark.parametrize("case", _STATE_FACTORIES, ids=[c[0] for c in _STATE_FACTORIES])
    def test_bit_identical(self, case: tuple[str, Any]) -> None:
        _name, factory = case
        values = [1.0, 0.5, -0.75]
        # 展開版: Demux → 3 個の状態ブロック → Mux
        sim_e = Simulator(t_end=0.1, dt=TS, rtol=1e-9, atol=1e-12)
        m = _mux(sim_e, values, "a")
        d = sim_e.add(Demux(n=3, id="d"))
        out = sim_e.add(Mux(n=3, id="out"))
        sc_e = sim_e.add(Scope(id="sc"))
        sim_e.connect(m, d)
        for i in range(3):
            b = sim_e.add(factory())
            b.id = None
            sim_e.blocks.remove(b)
            b = sim_e.add(factory())
            sim_e.connect(d, b, src_idx=i)
            sim_e.connect(b, out, dst_idx=i)
        sim_e.connect(out, sc_e)
        sim_e.run()
        # ベクトル版
        sim_v = Simulator(t_end=0.1, dt=TS, rtol=1e-9, atol=1e-12)
        m2 = _mux(sim_v, values, "a")
        b2 = sim_v.add(factory())
        sc_v = sim_v.add(Scope(id="sc"))
        sim_v.connect(m2, b2)
        sim_v.connect(b2, sc_v)
        sim_v.run()
        assert b2.n_states == 3 * b2._state_slots
        assert sc_v.n_columns == 3
        assert np.array_equal(np.asarray(sc_e.values), np.asarray(sc_v.values))


class TestRoundTripAndErrors:
    def test_array_x0_round_trip(self, tmp_path: Any) -> None:
        sim = Simulator(t_end=0.05, dt=TS)
        c = sim.add(Constant(value=1.0, id="c"))
        m = sim.add(Mux(n=2, id="m"))
        integ = sim.add(Integrator(x0=[1.0, 2.0], id="integ"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(c, m, dst_idx=0)
        sim.connect(c, m, dst_idx=1)
        sim.connect(m, integ)
        sim.connect(integ, sc)
        path = tmp_path / "vec.flw.json"
        sim.save(path)
        loaded = Simulator.load(path)
        loaded.run()
        v = np.asarray(loaded.get_block("sc").values)
        np.testing.assert_allclose(v[0], [1.0, 2.0])
        np.testing.assert_allclose(v[-1], [1.05, 2.05], atol=1e-9)

    def test_array_x0_input_shape_mismatch_is_build_error(self) -> None:
        sim = Simulator(t_end=0.05, dt=TS)
        c = sim.add(Constant(value=1.0, id="c"))
        m = sim.add(Mux(n=3, id="m"))
        integ = sim.add(Integrator(x0=[1.0, 2.0], id="integ"))
        for i in range(3):
            sim.connect(c, m, dst_idx=i)
        sim.connect(m, integ)
        with pytest.raises(SignalShapeError, match="x0 has shape") as ei:
            sim.run()
        assert ei.value.expected_shape == (2,)
        assert ei.value.actual_shape == (3,)

    def test_array_x0_with_scalar_input_broadcasts(self) -> None:
        """x0 が (2,) で入力がスカラ: 入力は state shape に拡張される。"""
        sim = Simulator(t_end=0.05, dt=TS)
        c = sim.add(Constant(value=1.0, id="c"))
        integ = sim.add(Integrator(x0=[1.0, 2.0], id="integ"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(c, integ)
        sim.connect(integ, sc)
        res = sim.resolve_signals()
        assert res.in_shape("integ", 0) == ()
        assert res.out_shape("integ", 0) == (2,)
        sim.run()
        np.testing.assert_allclose(np.asarray(sc.values)[-1], [1.05, 2.05], atol=1e-9)

    def test_scalar_state_api_default_wrapper_rejects_vector(self) -> None:
        from flode.blocks import TransferFunction

        tf = TransferFunction(numerator=[1.0], denominator=[1.0, 1.0])
        with pytest.raises(BlockSpecError, match="scalar state API"):
            tf.derivative_v(0.0, np.zeros(1), (np.array([1.0, 2.0]),))


class TestLinearizeVectorState:
    def test_state_names_are_flat_indices(self) -> None:
        from flode.analysis import linearize

        sim = Simulator(t_end=1.0, dt=TS)
        m = sim.add(Mux(n=2, id="m"))
        g = sim.add(Gain(k=-2.0, id="g"))
        integ = sim.add(Integrator(x0=0.0, id="integ"))
        d = sim.add(Demux(n=2, id="d"))
        sc = sim.add(Scope(n_inputs=2, id="sc"))
        sim.connect(g, integ)
        sim.connect(integ, d)
        sim.connect(d, m, src_idx=0, dst_idx=0)
        sim.connect(d, m, src_idx=1, dst_idx=1)
        sim.connect(m, g)
        sim.connect(d, sc, src_idx=0, dst_idx=0)
        sim.connect(d, sc, src_idx=1, dst_idx=1)
        lin = linearize(sim)
        assert lin.state_names == ["integ.x[0]", "integ.x[1]"]
        np.testing.assert_allclose(lin.A, -2.0 * np.eye(2), atol=1e-6)
