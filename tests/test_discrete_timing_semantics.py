"""離散ブロックのサンプル時刻セマンティクス回帰テスト (ADR-0078 / bug-fix 2026-09-14)。

3 件のバグの再現テスト:

* BUG-001: 離散→(直達)→離散の直列で 1 サンプル余分に遅れる / 離散フィードバックが半速
* BUG-002: ``@block`` の離散ステートフルブロックが t_k で x_{k+1} を出力する (1 サンプル先行)
* BUG-003: 直達項を持つ離散ブロック (DTF / DSS の D≠0) がサンプル間で入力をホールドしない

期待値は独立した参照 (``scipy.signal.dlsim``、サンプル値制御の解析解、UnitDelay 単体の
docstring 契約 ``y[k+1] = u[k]`` の合成) から与える。
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import signal

from flode import Simulator, Subsystem, block
from flode.blocks import (
    Clock,
    Constant,
    DiscreteIntegrator,
    DiscreteStateSpace,
    DiscreteTransferFunction,
    Gain,
    PythonFunction,
    Ramp,
    Scope,
    Step,
    Sum,
    TransferFunction,
    TransportDelay,
    UnitDelay,
    ZeroOrderHoldDirect,
)
from flode.subsystems import Inport, Outport

TS = 0.1


def _chain(blocks: list, *, source=None, t_end: float = 0.6, dt: float = TS) -> np.ndarray:
    sim = Simulator(t_end=t_end, dt=dt)
    prev = sim.add(source if source is not None else Clock(id="clk"))
    for b in blocks:
        sim.add(b)
        sim.connect(prev, b)
        prev = b
    sc = sim.add(Scope(id="sc"))
    sim.connect(prev, sc)
    sim.run()
    return sc.values[:, 0]


def _lagged_ramp(n_lag: int, n: int = 7) -> np.ndarray:
    t = np.arange(n) * TS
    return np.concatenate([np.zeros(n_lag), t[: n - n_lag]])


# ---------------------------------------------------------------------------
# BUG-001: 直列 / フィードバック
# ---------------------------------------------------------------------------


class TestDiscreteChainDelay:
    def test_two_unit_delays_are_two_samples(self):
        y = _chain([UnitDelay(sample_time=TS), UnitDelay(sample_time=TS)])
        np.testing.assert_allclose(y, _lagged_ramp(2))

    def test_unit_delay_gain_unit_delay(self):
        y = _chain([UnitDelay(sample_time=TS), Gain(k=1.0), UnitDelay(sample_time=TS)])
        np.testing.assert_allclose(y, _lagged_ramp(2))

    def test_dtf_delay_then_unit_delay(self):
        y = _chain(
            [
                DiscreteTransferFunction(
                    numerator=[0.0, 1.0], denominator=[1.0, 0.0], sample_time=TS
                ),
                UnitDelay(sample_time=TS),
            ]
        )
        np.testing.assert_allclose(y, _lagged_ramp(2))

    def test_dss_delay_then_unit_delay(self):
        dss = DiscreteStateSpace(
            A=np.zeros((1, 1)), B=np.ones((1, 1)), C=np.ones((1, 1)), sample_time=TS
        )
        y = _chain([dss, UnitDelay(sample_time=TS)])
        np.testing.assert_allclose(y, _lagged_ramp(2))

    def test_unit_delay_then_discrete_integrator(self):
        y = _chain([UnitDelay(sample_time=TS), DiscreteIntegrator(sample_time=TS)])
        u = _lagged_ramp(1)
        expected = np.concatenate([[0.0], np.cumsum(u[:-1]) * TS])
        np.testing.assert_allclose(y, expected)

    def test_unit_delay_then_transport_delay(self):
        y = _chain([UnitDelay(sample_time=TS), TransportDelay(delay_time=2 * TS, sample_time=TS)])
        np.testing.assert_allclose(y, _lagged_ramp(3))

    def test_transport_delay_then_unit_delay(self):
        y = _chain([TransportDelay(delay_time=2 * TS, sample_time=TS), UnitDelay(sample_time=TS)])
        np.testing.assert_allclose(y, _lagged_ramp(3))

    def test_zoh_then_unit_delay_unchanged(self):
        y = _chain([ZeroOrderHoldDirect(sample_time=TS), UnitDelay(sample_time=TS)])
        np.testing.assert_allclose(y, _lagged_ramp(1))

    def test_random_source_then_unit_delay_same_instant(self):
        """RandomSource (描画は advance 相) の新値が同時刻の下流 UnitDelay に届く。"""
        from flode.blocks import RandomSource

        sim = Simulator(t_end=0.6, dt=TS)
        rs = sim.add(RandomSource(sample_time=TS, seed=7, id="rs"))
        ud = sim.add(UnitDelay(sample_time=TS, id="ud"))
        sc = sim.add(Scope(n_inputs=2, id="sc"))
        sim.connect(rs, ud)
        sim.connect(rs, sc, dst_idx=0)
        sim.connect(ud, sc, dst_idx=1)
        sim.run()
        v = sc.values
        np.testing.assert_allclose(v[1:, 1], v[:-1, 0])  # y_ud[k] = y_rs[k-1]
        assert v[0, 1] == 0.0


class TestDiscreteFeedback:
    @staticmethod
    def _unit_delay_loop() -> np.ndarray:
        """x[k+1] = 0.5 x[k] + 1 を Sum / UnitDelay / Gain で構成。"""
        sim = Simulator(t_end=0.6, dt=TS)
        c = sim.add(Constant(value=1.0, id="c"))
        s = sim.add(Sum(signs="++", id="s"))
        d = sim.add(UnitDelay(sample_time=TS, id="d"))
        g = sim.add(Gain(k=0.5, id="g"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(c, s, dst_idx=0)
        sim.connect(g, s, dst_idx=1)
        sim.connect(s, d)
        sim.connect(d, g)
        sim.connect(d, sc)
        sim.run()
        return sc.values[:, 0]

    def test_loop_matches_dlsim(self):
        _, y_ref = signal.dlsim((np.array([0.0, 1.0]), np.array([1.0, -0.5]), TS), np.ones(7))
        np.testing.assert_allclose(self._unit_delay_loop(), y_ref.ravel())

    def test_loop_matches_single_dtf(self):
        y_dtf = _chain(
            [
                DiscreteTransferFunction(
                    numerator=[0.0, 1.0], denominator=[1.0, -0.5], sample_time=TS
                )
            ],
            source=Constant(value=1.0, id="c"),
        )
        np.testing.assert_allclose(self._unit_delay_loop(), y_dtf)

    def test_cross_coupled_unit_delays_period_two(self):
        """a[k+1] = b[k], b[k+1] = a[k] → 10, 20, 10, 20, ... (period 2)。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        a = sim.add(UnitDelay(sample_time=0.01, x0=10.0, id="a"))
        b = sim.add(UnitDelay(sample_time=0.01, x0=20.0, id="b"))
        sa = sim.add(Scope(id="sa"))
        sb = sim.add(Scope(id="sb"))
        sim.connect(a, b)
        sim.connect(b, a)
        sim.connect(a, sa)
        sim.connect(b, sb)
        sim.run()
        np.testing.assert_allclose(sa.values[:, 0], [10, 20, 10, 20, 10, 20])
        np.testing.assert_allclose(sb.values[:, 0], [20, 10, 20, 10, 20, 10])

    def test_chain_inside_subsystem_matches_root(self):
        sub = Subsystem(id="sub")
        sub.add(Inport(0, id="in"))
        sub.add(UnitDelay(sample_time=TS, id="d1"))
        sub.add(UnitDelay(sample_time=TS, id="d2"))
        sub.add(Outport(0, id="out"))
        sub.connect("in", "d1")
        sub.connect("d1", "d2")
        sub.connect("d2", "out")
        y = _chain([sub])
        np.testing.assert_allclose(y, _lagged_ramp(2))


# ---------------------------------------------------------------------------
# BUG-002: @block / PythonFunction 離散ブロックの出力タイミング
# ---------------------------------------------------------------------------


@block(states=1, sample_time=TS, direct_feedthrough=False)
def func_delay(t: float, x: np.ndarray, u: float, *, x0: float = 0.0) -> tuple[float, np.ndarray]:
    return float(x[0]), np.array([u])


@block(states=1, sample_time=TS, direct_feedthrough=False)
class ClassDelay:
    x0: float = 0.0

    def output(self, t: float, x: np.ndarray, u: float) -> float:
        return float(x[0])

    def update(self, t: float, x: np.ndarray, u: float) -> np.ndarray:
        return np.array([u])


@block(states=1, sample_time=-1.0, direct_feedthrough=False)
def inherited_delay(
    t: float, x: np.ndarray, u: float, *, x0: float = 0.0
) -> tuple[float, np.ndarray]:
    return float(x[0]), np.array([u])


PY_DELAY = """
import numpy as np
from flode import block

@block(states=1, sample_time=0.1, direct_feedthrough=False)
def py_delay(t: float, x: np.ndarray, u: float, *, x0: float = 0.0) -> tuple[float, np.ndarray]:
    return float(x[0]), np.array([u])
"""


class TestDecoratorDiscreteTiming:
    @pytest.mark.parametrize(
        "factory",
        [
            lambda: func_delay(x0=0.0, id="d"),
            lambda: ClassDelay(id="d"),
            lambda: PythonFunction(code=PY_DELAY, id="d"),
        ],
        ids=["function", "class", "python_function"],
    )
    def test_matches_builtin_unit_delay(self, factory):
        y_ref = _chain([UnitDelay(sample_time=TS, x0=0.0)], source=Constant(value=2.0, id="c"))
        y = _chain([factory()], source=Constant(value=2.0, id="c"))
        np.testing.assert_allclose(y, y_ref)
        np.testing.assert_allclose(y, [0, 2, 2, 2, 2, 2, 2])

    def test_two_decorator_delays_are_two_samples(self):
        y = _chain([func_delay(id="d1"), func_delay(id="d2")])
        np.testing.assert_allclose(y, _lagged_ramp(2))

    def test_builtin_then_decorator_delay(self):
        y = _chain([UnitDelay(sample_time=TS), func_delay(id="d2")])
        np.testing.assert_allclose(y, _lagged_ramp(2))

    def test_inherited_rate_delay(self):
        y = _chain([UnitDelay(sample_time=TS), inherited_delay(id="inh")])
        np.testing.assert_allclose(y, _lagged_ramp(2))

    def test_decorator_feedback_loop(self):
        sim = Simulator(t_end=0.6, dt=TS)
        c = sim.add(Constant(value=1.0, id="c"))
        s = sim.add(Sum(signs="++", id="s"))
        d = sim.add(func_delay(id="d"))
        g = sim.add(Gain(k=0.5, id="g"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(c, s, dst_idx=0)
        sim.connect(g, s, dst_idx=1)
        sim.connect(s, d)
        sim.connect(d, g)
        sim.connect(d, sc)
        sim.run()
        np.testing.assert_allclose(sc.values[:, 0], [0, 1, 1.5, 1.75, 1.875, 1.9375, 1.96875])


# ---------------------------------------------------------------------------
# BUG-003: 直達項のサンプル間ホールド
# ---------------------------------------------------------------------------


class TestFeedthroughHold:
    @staticmethod
    def _staircase(ts: float, n: int, dt: float) -> np.ndarray:
        t = np.arange(n) * dt
        return np.floor(np.round(t / ts, 9)) * ts

    @pytest.mark.parametrize(
        "blk",
        [
            DiscreteTransferFunction(numerator=[1.0], denominator=[1.0], sample_time=0.5),
            DiscreteStateSpace(
                A=np.zeros((1, 1)),
                B=np.zeros((1, 1)),
                C=np.zeros((1, 1)),
                D=np.ones((1, 1)),
                sample_time=0.5,
            ),
            ZeroOrderHoldDirect(sample_time=0.5),
        ],
        ids=["dtf_gain", "dss_D", "zoh"],
    )
    def test_ramp_is_held_between_samples(self, blk):
        y = _chain([blk], source=Ramp(slope=1.0, id="r"), t_end=1.0, dt=0.1)
        np.testing.assert_allclose(y, self._staircase(0.5, 11, 0.1))

    def test_single_rate_p_loop_is_sampled_data(self):
        """dt = Ts でも DTF ゲイン (直達) はサンプル&ホールド: u_k = 2 e_k をホールドし
        y(t_{k+1}) = a y_k + (1-a) u_k (a = e^{-Ts}) に一致する (連続 P 制御ではない)。"""
        sim = Simulator(t_end=2.0, dt=TS)
        r = sim.add(Step(step_time=0.0, id="r"))
        e = sim.add(Sum(signs="+-", id="e"))
        cd = sim.add(
            DiscreteTransferFunction(numerator=[2.0], denominator=[1.0], sample_time=TS, id="C")
        )
        g = sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0], id="G"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(r, e, dst_idx=0)
        sim.connect(g, e, dst_idx=1)
        sim.connect(e, cd)
        sim.connect(cd, g)
        sim.connect(g, sc)
        sim.run()
        a = np.exp(-TS)
        yk = [0.0]
        for _ in range(20):
            yk.append(a * yk[-1] + (1 - a) * 2.0 * (1.0 - yk[-1]))
        np.testing.assert_allclose(sc.values[:, 0], yk, atol=1e-7)

    def test_deadbeat_settles_in_one_sample(self):
        ts = 0.5
        a = np.exp(-ts)
        sim = Simulator(t_end=2.0, dt=0.01)
        r = sim.add(Step(step_time=0.0, id="r"))
        e = sim.add(Sum(signs="+-", id="e"))
        cd = sim.add(
            DiscreteTransferFunction(
                numerator=[1.0, -a], denominator=[1 - a, -(1 - a)], sample_time=ts, id="C"
            )
        )
        g = sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0], id="G"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(r, e, dst_idx=0)
        sim.connect(g, e, dst_idx=1)
        sim.connect(e, cd)
        sim.connect(cd, g)
        sim.connect(g, sc)
        sim.run()
        t = np.asarray(sc.times)
        hits = np.where(np.abs(t / ts - np.round(t / ts)) < 1e-9)[0]
        np.testing.assert_allclose(sc.values[hits[1:], 0], 1.0, atol=1e-6)


class TestUnchangedSemantics:
    """修正で変わってはいけない挙動 (単体 UnitDelay / multi-rate / ZOH)。"""

    def test_single_unit_delay(self):
        np.testing.assert_allclose(_chain([UnitDelay(sample_time=TS)]), _lagged_ramp(1))

    def test_multirate_unit_delay_holds(self):
        y = _chain([UnitDelay(sample_time=0.2)], t_end=0.6, dt=0.1)
        np.testing.assert_allclose(y, [0, 0, 0, 0, 0.2, 0.2, 0.4])

    def test_discrete_integrator_alone(self):
        y = _chain([DiscreteIntegrator(sample_time=TS)])
        t = np.arange(7) * TS
        np.testing.assert_allclose(y, np.concatenate([[0.0], np.cumsum(t[:-1]) * TS]))


class TestNestedControlSubsystem:
    """Trigger 付き Subsystem (内部に UnitDelay 直列) を非制御 Subsystem に入れ子にしても
    ルート直下と同じ数値になる (ADR-0078 Risks #1: advance の分岐が階層で一貫する)。"""

    @staticmethod
    def _triggered() -> Subsystem:
        from flode.subsystems import Trigger

        return Subsystem(
            blocks=[
                Inport(port_idx=0, id="in_data"),
                UnitDelay(sample_time=TS, id="d1"),
                UnitDelay(sample_time=TS, id="d2"),
                Outport(port_idx=0, id="out"),
                Trigger(trigger_type="rising", id="trig"),
            ],
            connections=[
                {"src": "in_data", "dst": "d1"},
                {"src": "d1", "dst": "d2"},
                {"src": "d2", "dst": "out"},
            ],
            id="trig_sub",
        )

    @staticmethod
    def _run(target: Subsystem) -> np.ndarray:
        from flode.blocks import PulseGenerator

        sim = Simulator(t_end=1.0, dt=TS)
        clk = sim.add(Clock(id="clk"))
        pulse = sim.add(PulseGenerator(amplitude=1.0, period=0.3, pulse_width=50.0, id="pulse"))
        sim.add(target)
        sc = sim.add(Scope(id="sc"))
        sim.connect(clk, target, dst_idx=0)
        sim.connect(pulse, target, dst_idx=1)
        sim.connect(target, sc)
        sim.run()
        return sc.values[:, 0]

    def test_nested_matches_root(self):
        y_root = self._run(self._triggered())
        outer = Subsystem(
            blocks=[
                Inport(port_idx=0, id="o_in"),
                Inport(port_idx=1, id="o_trig"),
                self._triggered(),
                Outport(port_idx=0, id="o_out"),
            ],
            connections=[
                {"src": "o_in", "dst": "trig_sub", "dst_idx": 0},
                {"src": "o_trig", "dst": "trig_sub", "dst_idx": 1},
                {"src": "trig_sub", "dst": "o_out"},
            ],
            id="outer",
        )
        y_nested = self._run(outer)
        np.testing.assert_allclose(y_nested, y_root)
        assert np.any(y_root != 0.0), "trigger が一度も fire していない"
