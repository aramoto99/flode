"""ADR-0006 LTI ブロック (連続 + 離散) のテスト。

- 連続: ``StateSpace`` / ``TransferFunction`` / ``Derivative``
- 離散: ``DiscreteStateSpace`` / ``DiscreteTransferFunction``

数値検証は scipy.signal の参照実装または解析解と比較する。
"""

from __future__ import annotations

import numpy as np
import pytest

from pyflw import AlgebraicLoopError, BlockSpecError, Simulator
from pyflw.blocks import (
    Constant,
    Derivative,
    DiscreteStateSpace,
    DiscreteTransferFunction,
    Integrator,
    Scope,
    StateSpace,
    Step,
    Sum,
    TransferFunction,
)

# ---------------------------------------------------------------
# StateSpace (連続)
# ---------------------------------------------------------------


class TestStateSpace:
    def test_first_order_lag_step_response(self):
        """1 次遅れ系 ``y = 1/(s+1) * u`` のステップ応答が解析解と一致する。

        State Space: A=-1, B=1, C=1, D=0、x0=0、u=1 (Step) で
        ``y(t) = 1 - exp(-t)``。
        """
        sim = Simulator(t_end=2.0, dt=0.01, rtol=1e-9, atol=1e-12)
        src = sim.add(Step(step_time=0.0, final_value=1.0, id="src"))
        ss = sim.add(
            StateSpace(
                A=np.array([[-1.0]]),
                B=np.array([[1.0]]),
                C=np.array([[1.0]]),
                id="ss",
            )
        )
        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(src, ss)
        sim.connect(ss, scope)
        sim.run()

        t = np.array(scope.times)
        y = scope.values[:, 0]
        expected = 1.0 - np.exp(-t)
        np.testing.assert_allclose(y, expected, rtol=1e-3, atol=1e-4)

    def test_direct_feedthrough_inferred_from_d(self):
        """``D != 0`` で direct_feedthrough=True が自動推論される (ADR-0006 §DF-A)。"""
        ss = StateSpace(
            A=np.array([[-1.0]]),
            B=np.array([[1.0]]),
            C=np.array([[1.0]]),
            D=np.array([[2.0]]),
        )
        assert ss.direct_feedthrough is True
        # y = C*x + D*u = 1*x + 2*u
        np.testing.assert_allclose(ss.output(0.0, np.array([3.0]), np.array([5.0])), [13.0])

    def test_d_below_tolerance_treats_as_zero(self):
        """``D`` の最大絶対値が ``1e-12`` 未満なら direct_feedthrough=False。"""
        ss = StateSpace(
            A=np.array([[-1.0]]),
            B=np.array([[1.0]]),
            C=np.array([[1.0]]),
            D=np.array([[1e-15]]),
        )
        assert ss.direct_feedthrough is False

    def test_invalid_a_raises(self):
        with pytest.raises(BlockSpecError, match="A must be square"):
            StateSpace(
                A=np.array([[1.0, 2.0]]),
                B=np.array([[1.0]]),
                C=np.array([[1.0]]),
            )

    def test_b_shape_mismatch_raises(self):
        with pytest.raises(BlockSpecError, match="B must have shape"):
            StateSpace(
                A=np.array([[-1.0]]),
                B=np.array([[1.0], [2.0]]),  # n=1 のはずが 2 行
                C=np.array([[1.0]]),
            )

    def test_x0_shape_mismatch_raises(self):
        with pytest.raises(BlockSpecError, match="x0 must have shape"):
            StateSpace(
                A=np.eye(2),
                B=np.array([[1.0], [0.0]]),
                C=np.array([[1.0, 0.0]]),
                x0=np.array([1.0]),  # n=2 のはずが 1
            )

    def test_n_states_zero_rejected(self):
        """``A`` が 0x0 (純ゲイン) は拒否する (Phase 1 スコープ外)。"""
        with pytest.raises(BlockSpecError, match="n_states=0"):
            StateSpace(
                A=np.zeros((0, 0)),
                B=np.zeros((0, 1)),
                C=np.zeros((1, 0)),
                D=np.array([[2.0]]),
            )

    def test_mimo_2x2_state_space_runs(self):
        """``n_states=2`` の MIMO SS が Simulator で動く。``.ravel()`` 対応の回帰。

        2 次系 ``x_dot = [[-1, 0], [0, -2]] x + [[1], [1]] u``、``y = [1, 1] x``
        のステップ応答 ``y(t) = (1 - exp(-t)) + 0.5 * (1 - exp(-2t))``。
        """
        sim = Simulator(t_end=2.0, dt=0.01, rtol=1e-9, atol=1e-12)
        src = sim.add(Step(step_time=0.0, final_value=1.0, id="src"))
        ss = sim.add(
            StateSpace(
                A=np.array([[-1.0, 0.0], [0.0, -2.0]]),
                B=np.array([[1.0], [1.0]]),
                C=np.array([[1.0, 1.0]]),
                id="ss",
            )
        )
        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(src, ss)
        sim.connect(ss, scope)
        sim.run()
        t = np.array(scope.times)
        expected = (1.0 - np.exp(-t)) + 0.5 * (1.0 - np.exp(-2.0 * t))
        np.testing.assert_allclose(scope.values[:, 0], expected, rtol=1e-3, atol=1e-4)


# ---------------------------------------------------------------
# TransferFunction (連続)
# ---------------------------------------------------------------


class TestTransferFunction:
    def test_first_order_step_response(self):
        """``H(s) = 1/(s+1)`` のステップ応答 ``y(t) = 1 - exp(-t)``。"""
        sim = Simulator(t_end=2.0, dt=0.01, rtol=1e-9, atol=1e-12)
        src = sim.add(Step(step_time=0.0, final_value=1.0, id="src"))
        tf = sim.add(TransferFunction([1.0], [1.0, 1.0], id="tf"))
        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(src, tf)
        sim.connect(tf, scope)
        sim.run()

        t = np.array(scope.times)
        y = scope.values[:, 0]
        expected = 1.0 - np.exp(-t)
        np.testing.assert_allclose(y, expected, rtol=1e-3, atol=1e-4)

    def test_second_order_underdamped(self):
        """``H(s) = 1/(s² + 0.4 s + 1)`` の振動応答が scipy 参照と一致する。"""
        import scipy.signal

        num, den = [1.0], [1.0, 0.4, 1.0]
        sim = Simulator(t_end=10.0, dt=0.01, rtol=1e-9, atol=1e-12)
        src = sim.add(Step(step_time=0.0, final_value=1.0, id="src"))
        tf = sim.add(TransferFunction(num, den, id="tf"))
        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(src, tf)
        sim.connect(tf, scope)
        sim.run()

        ts = np.array(scope.times)
        ref_t, ref_y = scipy.signal.step((num, den), T=ts)
        np.testing.assert_allclose(scope.values[:, 0], ref_y, rtol=1e-2, atol=1e-3)

    def test_biproper_with_d_nonzero(self):
        """``deg(num) == deg(den)`` で ``D != 0`` のケース。

        ``H(s) = (s + 2) / (s + 1)``: 直接通すと D = 1、極は -1 で安定。
        """
        tf = TransferFunction([1.0, 2.0], [1.0, 1.0])
        assert tf.direct_feedthrough is True
        assert tf.n_states == 1

    def test_improper_raises(self):
        with pytest.raises(BlockSpecError, match="improper"):
            TransferFunction([1.0, 0.0, 0.0], [1.0, 1.0])

    def test_zero_numerator_raises(self):
        with pytest.raises(BlockSpecError, match="all zeros"):
            TransferFunction([0.0, 0.0], [1.0, 1.0])

    def test_zero_leading_denominator_raises(self):
        with pytest.raises(BlockSpecError, match="leading coefficient"):
            TransferFunction([1.0], [0.0, 1.0])


# ---------------------------------------------------------------
# Derivative (連続、フィルタ近似)
# ---------------------------------------------------------------


class TestDerivative:
    def test_step_input_response_decays(self):
        """ステップ入力の微分は filter 効果でインパルス的に立ち上がり指数減衰。

        N=10 で ``y(t) = N * exp(-N*t)`` (t > 0、x0=0 の場合)。
        """
        N = 10.0
        sim = Simulator(t_end=1.0, dt=0.001, rtol=1e-9, atol=1e-12)
        src = sim.add(Step(step_time=0.0, final_value=1.0, id="src"))
        d = sim.add(Derivative(N=N, x0=0.0, id="d"))
        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(src, d)
        sim.connect(d, scope)
        sim.run()

        t = np.array(scope.times)
        y = scope.values[:, 0]
        # t=0 では output = N*(u-x) = N*1 = N (direct feedthrough)
        assert y[0] == pytest.approx(N, rel=1e-3)
        # 後半は指数減衰 (積分定数を含むが N が大きいので近似で十分)
        # t=0.5 で y ≈ N * exp(-N*0.5) ≈ 10 * 0.0067
        late_idx = np.argmin(np.abs(t - 0.5))
        expected_late = N * np.exp(-N * 0.5)
        np.testing.assert_allclose(y[late_idx], expected_late, rtol=1e-2, atol=1e-3)

    def test_invalid_n_raises(self):
        with pytest.raises(BlockSpecError, match="N must be"):
            Derivative(N=0.0)
        with pytest.raises(BlockSpecError, match="N must be"):
            Derivative(N=-1.0)

    def test_self_loop_raises_algebraic_loop(self):
        """``Derivative`` は ``direct_feedthrough=True`` なので自己フィードバックで
        代数ループが検出される (code-reviewer SHOULD 修正)。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        d = sim.add(Derivative(N=10.0, id="d"))
        sim.connect(d, d)
        with pytest.raises(AlgebraicLoopError):
            sim.run()


# ---------------------------------------------------------------
# DiscreteStateSpace
# ---------------------------------------------------------------


class TestDiscreteStateSpace:
    def test_pure_delay_via_a0(self):
        """A=0、B=1、C=1、D=0、初期 x0=0 の離散 SS は UnitDelay と同等。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        src = sim.add(Constant(value=2.0, id="src"))
        dss = sim.add(
            DiscreteStateSpace(
                A=np.array([[0.0]]),
                B=np.array([[1.0]]),
                C=np.array([[1.0]]),
                sample_time=0.01,
                id="dss",
            )
        )
        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(src, dss)
        sim.connect(dss, scope)
        sim.run()
        # 1 サンプル遅延後に 2.0 が観測される
        values = scope.values[:, 0]
        assert values[0] == pytest.approx(0.0)
        assert values[-1] == pytest.approx(2.0)

    def test_d_nonzero_direct_feedthrough(self):
        dss = DiscreteStateSpace(
            A=np.array([[0.5]]),
            B=np.array([[1.0]]),
            C=np.array([[1.0]]),
            D=np.array([[0.5]]),
            sample_time=0.01,
        )
        assert dss.direct_feedthrough is True
        # output = C*x + D*u = 1*0 + 0.5*2 = 1.0
        np.testing.assert_allclose(dss.output(0.0, np.array([0.0]), np.array([2.0])), [1.0])

    def test_invalid_a_raises(self):
        with pytest.raises(BlockSpecError, match="A must be square"):
            DiscreteStateSpace(
                A=np.array([[1.0, 2.0]]),
                B=np.array([[1.0]]),
                C=np.array([[1.0]]),
                sample_time=0.01,
            )

    def test_n_states_zero_rejected(self):
        with pytest.raises(BlockSpecError, match="n_states=0"):
            DiscreteStateSpace(
                A=np.zeros((0, 0)),
                B=np.zeros((0, 1)),
                C=np.zeros((1, 0)),
                D=np.array([[2.0]]),
                sample_time=0.01,
            )


# ---------------------------------------------------------------
# DiscreteTransferFunction
# ---------------------------------------------------------------


class TestDiscreteTransferFunction:
    def test_unit_delay_via_z_inverse(self):
        """``H(z) = 1/z = z^{-1}``: UnitDelay と等価。

        scipy convention: ``num=[1]``, ``den=[1, 0]`` で ``H(z) = 1 / z``。
        """
        sim = Simulator(t_end=0.05, dt=0.01)
        src = sim.add(Constant(value=3.0, id="src"))
        dtf = sim.add(DiscreteTransferFunction([1.0], [1.0, 0.0], sample_time=0.01, id="dtf"))
        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(src, dtf)
        sim.connect(dtf, scope)
        sim.run()
        values = scope.values[:, 0]
        assert values[0] == pytest.approx(0.0)
        assert values[-1] == pytest.approx(3.0)

    def test_improper_raises(self):
        with pytest.raises(BlockSpecError, match="improper"):
            DiscreteTransferFunction([1.0, 0.0, 0.0], [1.0, 1.0], sample_time=0.01)

    def test_biproper_d_nonzero(self):
        """biproper でも D が推論される。"""
        dtf = DiscreteTransferFunction([1.0, 0.5], [1.0, -0.5], sample_time=0.01)
        # D = num[0]/den[0] = 1.0
        assert dtf.direct_feedthrough is True


# ---------------------------------------------------------------
# 統合: TransferFunction + Integrator のセルフテスト
# ---------------------------------------------------------------


def test_integrator_equivalent_to_tf_1_over_s():
    """Phase 0 の Integrator と TF(``1/s``) が同じ応答を返す。"""
    sim_a = Simulator(t_end=1.0, dt=0.01, rtol=1e-9, atol=1e-12)
    src_a = sim_a.add(Constant(value=1.0, id="src"))
    integ = sim_a.add(Integrator(x0=0.0, id="integ"))
    scope_a = sim_a.add(Scope(n_inputs=1, id="scope"))
    sim_a.connect(src_a, integ)
    sim_a.connect(integ, scope_a)
    sim_a.run()

    sim_b = Simulator(t_end=1.0, dt=0.01, rtol=1e-9, atol=1e-12)
    src_b = sim_b.add(Constant(value=1.0, id="src"))
    tf = sim_b.add(TransferFunction([1.0], [1.0, 0.0], id="tf"))
    scope_b = sim_b.add(Scope(n_inputs=1, id="scope"))
    sim_b.connect(src_b, tf)
    sim_b.connect(tf, scope_b)
    sim_b.run()

    np.testing.assert_allclose(scope_a.values[:, 0], scope_b.values[:, 0], rtol=1e-6, atol=1e-8)
    # Sum も使えることを軽くカバー (noqa: F401 のため)
    _ = Sum
