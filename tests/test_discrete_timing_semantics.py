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


class TestSampledDataExactSolution:
    """サンプル値閉ループの厳密解 (ZOH 等価離散化 + 離散漸化式を numpy で直接計算) との一致。

    連続プラント 1/((s+1)(s+2)) + Tustin 離散 PI (直達あり) + 演算遅れ UnitDelay。
    サンプル点での y は厳密に離散時間系なので、solve_ivp の許容誤差の範囲で一致するはず。
    """

    TS = 0.05
    BC = None
    AC = None

    @classmethod
    def _controller(cls):
        import control

        if cls.BC is None:
            cz = control.c2d(control.tf([4.0, 6.0], [1.0, 0.0]), cls.TS, "tustin")
            cls.BC = np.asarray(cz.num[0][0], float).ravel()
            cls.AC = np.asarray(cz.den[0][0], float).ravel()
        return cls.BC, cls.AC

    @classmethod
    def _exact(cls, n_steps: int, ctrl_ratio: int = 1) -> np.ndarray:
        import control

        pd = control.c2d(control.tf2ss(control.tf([1.0], [1.0, 3.0, 2.0])), cls.TS, "zoh")
        Ad, Bd, Cd = np.asarray(pd.A), np.asarray(pd.B), np.asarray(pd.C)
        bc, ac = cls._controller()
        xp = np.zeros((Ad.shape[0], 1))
        u_prev = e_prev = u = v = 0.0
        ys = []
        for k in range(n_steps + 1):
            y = float((Cd @ xp).item())
            ys.append(y)
            e = 1.0 - y
            if k % ctrl_ratio == 0:
                u_new = -ac[1] * u_prev + bc[0] * e + bc[1] * e_prev
                u_prev, e_prev, u = u_new, e, u_new
            v_k, v = v, u  # UnitDelay: 出力は前サンプルの u
            xp = Ad @ xp + Bd * v_k
        return np.array(ys)

    def _flode(self, ctrl_ts: float, use_block: bool = False) -> np.ndarray:
        bc, ac = self._controller()
        sim = Simulator(t_end=2.0, dt=self.TS, rtol=1e-11, atol=1e-13)
        r = sim.add(Step(step_time=0.0, id="r"))
        e = sim.add(Sum(signs="+-", id="e"))
        if use_block:

            @block(states=1, sample_time=ctrl_ts, direct_feedthrough=True)
            def pi_block(
                t: float, x: np.ndarray, u: float, *, x0: float = 0.0
            ) -> tuple[float, np.ndarray]:
                uk = bc[0] * u + x[0]
                return float(uk), np.array([-ac[1] * uk + bc[1] * u])

            c = sim.add(pi_block(id="pi"))
        else:
            c = sim.add(
                DiscreteTransferFunction(
                    numerator=list(bc), denominator=list(ac), sample_time=ctrl_ts, id="pi"
                )
            )
        d = sim.add(UnitDelay(sample_time=self.TS, id="d"))
        g = sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 3.0, 2.0], id="G"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(r, e, dst_idx=0)
        sim.connect(g, e, dst_idx=1)
        sim.connect(e, c)
        sim.connect(c, d)
        sim.connect(d, g)
        sim.connect(g, sc)
        sim.run()
        return sc.values[:, 0]

    def test_single_rate_matches_exact(self):
        np.testing.assert_allclose(self._flode(self.TS), self._exact(40), atol=1e-9)

    def test_multirate_controller_matches_exact(self):
        np.testing.assert_allclose(
            self._flode(2 * self.TS), self._exact(40, ctrl_ratio=2), atol=1e-9
        )

    def test_block_form_matches_builtin(self):
        np.testing.assert_allclose(
            self._flode(self.TS, use_block=True), self._flode(self.TS), atol=1e-12
        )


class TestImmediateBlocksSameInstant:
    """直達の離散非線形ブロック (Relay / RateLimiter) の t_k の出力が、同時刻に発火する
    下流 UnitDelay の update に届く (ADR-0078 Amendment: output() が u_k から決定値を計算)。"""

    @staticmethod
    def _run(mid) -> np.ndarray:
        sim = Simulator(t_end=0.6, dt=TS)
        src = sim.add(Step(step_time=0.25, final_value=1.0, id="src"))
        m = sim.add(mid)
        d = sim.add(UnitDelay(sample_time=TS, id="d"))
        sc = sim.add(Scope(n_inputs=2, id="sc"))
        sim.connect(src, m)
        sim.connect(m, d)
        sim.connect(m, sc, dst_idx=0)
        sim.connect(d, sc, dst_idx=1)
        sim.run()
        return sc.values

    def test_relay_then_unit_delay(self):
        from flode.blocks import Relay

        v = self._run(Relay(sample_time=TS, switch_on_point=0.5, switch_off_point=-0.5, id="relay"))
        np.testing.assert_allclose(v[:, 0], [0, 0, 0, 1, 1, 1, 1])
        np.testing.assert_allclose(v[1:, 1], v[:-1, 0])

    def test_rate_limiter_then_unit_delay(self):
        from flode.blocks import RateLimiter

        v = self._run(
            RateLimiter(sample_time=TS, rising_slew_rate=2.0, falling_slew_rate=-2.0, id="rl")
        )
        np.testing.assert_allclose(v[:, 0], [0, 0, 0, 0.2, 0.4, 0.6, 0.8])
        np.testing.assert_allclose(v[1:, 1], v[:-1, 0])


class TestImmediateBlocksInsideSubsystem:
    """RateLimiter (直達の即時型ブロック) を非制御 Subsystem に入れてもルート直下と同じ値になる。"""

    def test_rate_limiter_inside_subsystem(self):
        from flode.blocks import RateLimiter

        def make_rl(id_: str):
            return RateLimiter(sample_time=TS, rising_slew_rate=2.0, falling_slew_rate=-2.0, id=id_)

        sub = Subsystem(
            blocks=[Inport(port_idx=0, id="in"), make_rl("rl"), Outport(port_idx=0, id="out")],
            connections=[{"src": "in", "dst": "rl"}, {"src": "rl", "dst": "out"}],
            id="sub",
        )
        src = Step(step_time=0.25, final_value=1.0, id="src")
        y_root = _chain([make_rl("rl")], source=Step(step_time=0.25, final_value=1.0, id="src"))
        y_sub = _chain([sub], source=src)
        np.testing.assert_allclose(y_root, [0, 0, 0, 0.2, 0.4, 0.6, 0.8])
        np.testing.assert_allclose(y_sub, y_root)


class TestTriggeredSubsystemFeedthrough:
    """ADR-0078: Trigger 付き Subsystem の direct_feedthrough は内部経路から推論する
    (fire 時刻の出力はその時刻のデータ入力に依存 = 数学的に直達)。"""

    @staticmethod
    def _triggered_gain() -> Subsystem:
        from flode.subsystems import Trigger

        return Subsystem(
            blocks=[
                Inport(port_idx=0, id="in_data"),
                Gain(k=2.0, id="g"),
                Outport(port_idx=0, id="out"),
                Trigger(trigger_type="rising", id="trig"),
            ],
            connections=[{"src": "in_data", "dst": "g"}, {"src": "g", "dst": "out"}],
            id="trig_gain",
        )

    def test_feedthrough_inner_path_is_inferred(self):
        sub = self._triggered_gain()
        sub._build()
        assert sub.direct_feedthrough is True

    def test_self_feedback_through_feedthrough_is_algebraic_loop(self):
        from flode import AlgebraicLoopError
        from flode.blocks import PulseGenerator

        sub = self._triggered_gain()
        sim = Simulator(t_end=0.3, dt=TS)
        sim.add(PulseGenerator(period=0.2, id="pulse"))
        sim.add(Sum(signs="++", id="s"))
        sim.add(sub)
        sim.connect("pulse", "s", dst_idx=0)
        sim.connect("trig_gain", "s", dst_idx=1)  # 自身の出力 → Sum → データ入力 (直達ループ)
        sim.connect("s", "trig_gain", dst_idx=0)
        sim.connect("pulse", "trig_gain", dst_idx=1)
        with pytest.raises(AlgebraicLoopError):
            sim.run()

    def test_non_feedthrough_inner_path_breaks_loop(self):
        from flode.blocks import PulseGenerator
        from flode.subsystems import Trigger

        sub = Subsystem(
            blocks=[
                Inport(port_idx=0, id="in_data"),
                UnitDelay(sample_time=TS, id="d"),
                Outport(port_idx=0, id="out"),
                Trigger(trigger_type="rising", id="trig"),
            ],
            connections=[{"src": "in_data", "dst": "d"}, {"src": "d", "dst": "out"}],
            id="trig_delay",
        )
        sub._build()
        assert sub.direct_feedthrough is False
        sim = Simulator(t_end=0.6, dt=TS)
        sim.add(PulseGenerator(period=0.2, id="pulse"))
        sim.add(Sum(signs="++", id="s"))
        sim.add(sub)
        sc = sim.add(Scope(id="sc"))
        sim.connect("pulse", "s", dst_idx=0)
        sim.connect("trig_delay", "s", dst_idx=1)
        sim.connect("s", "trig_delay", dst_idx=0)
        sim.connect("pulse", "trig_delay", dst_idx=1)
        sim.connect("trig_delay", sc)
        sim.run()  # 例外なし (UnitDelay がループを切る)
        assert np.isfinite(sc.values).all()

    def test_plain_subsystem_nested_inside_triggered_matches_flat(self):
        """plain-in-triggered: 自身の離散状態を持つ非制御 Subsystem を Trigger 付き
        Subsystem の内部に置いても、フラットな構成と一致する。"""
        from flode.blocks import PulseGenerator

        def inner_chain() -> Subsystem:
            return Subsystem(
                blocks=[
                    Inport(port_idx=0, id="i"),
                    UnitDelay(sample_time=TS, id="d1"),
                    UnitDelay(sample_time=TS, id="d2"),
                    Outport(port_idx=0, id="o"),
                ],
                connections=[
                    {"src": "i", "dst": "d1"},
                    {"src": "d1", "dst": "d2"},
                    {"src": "d2", "dst": "o"},
                ],
                id="chain",
            )

        def triggered(inner_blocks, inner_conns) -> Subsystem:
            from flode.subsystems import Trigger as _T

            return Subsystem(
                blocks=[
                    Inport(port_idx=0, id="in_data"),
                    *inner_blocks,
                    Outport(port_idx=0, id="out"),
                    _T(id="trig"),
                ],
                connections=inner_conns,
                id="trig_sub",
            )

        def run(target: Subsystem) -> np.ndarray:
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

        flat = triggered(
            [UnitDelay(sample_time=TS, id="d1"), UnitDelay(sample_time=TS, id="d2")],
            [
                {"src": "in_data", "dst": "d1"},
                {"src": "d1", "dst": "d2"},
                {"src": "d2", "dst": "out"},
            ],
        )
        nested = triggered(
            [inner_chain()],
            [{"src": "in_data", "dst": "chain"}, {"src": "chain", "dst": "out"}],
        )
        y_flat = run(flat)
        y_nested = run(nested)
        np.testing.assert_allclose(y_nested, y_flat)
        assert np.any(y_flat != 0.0)
