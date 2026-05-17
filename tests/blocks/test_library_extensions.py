"""Phase 1 ブロックライブラリ拡張のテスト (SPEC-0001 §機能要件 Phase 1 #1)。

選抜実装したブロック: Ramp / Clock / PulseGenerator / Terminator /
DiscreteIntegrator / Saturation / Abs / Sign / MinMax / Divide /
RelationalOperator / LogicalOperator / Switch。

Note: legacy ``ZeroOrderHold`` (= 2-state state-based ホールド) は v0.13.0
(ADR-0033) で削除済。リファレンスツールの ZOH 互換版は ``ZeroOrderHoldDirect`` (ADR-0014
§(3)、tests/test_discrete_block_semantics.py)。1 サンプル遅延は ``UnitDelay``。
"""

from __future__ import annotations

import numpy as np
import pytest

from pyflw import BlockSpecError, Simulator
from pyflw.blocks import (
    Abs,
    Clock,
    Constant,
    DiscreteIntegrator,
    Divide,
    LogicalOperator,
    MinMax,
    PulseGenerator,
    Ramp,
    RelationalOperator,
    Saturation,
    Scope,
    Sign,
    Step,
    Switch,
    Terminator,
)

# ---------------------------------------------------------------
# Sources
# ---------------------------------------------------------------


class TestRamp:
    def test_before_start_returns_initial(self):
        b = Ramp(slope=2.0, start_time=1.0, initial_output=5.0)
        np.testing.assert_allclose(b.output(0.5, np.zeros(0), np.zeros(0)), [5.0])

    def test_after_start_increases_linearly(self):
        b = Ramp(slope=2.0, start_time=1.0, initial_output=5.0)
        np.testing.assert_allclose(b.output(3.0, np.zeros(0), np.zeros(0)), [5.0 + 2.0 * 2.0])

    def test_at_start_equals_initial(self):
        b = Ramp(slope=1.0, start_time=2.0, initial_output=0.0)
        np.testing.assert_allclose(b.output(2.0, np.zeros(0), np.zeros(0)), [0.0])


class TestClock:
    def test_outputs_t(self):
        b = Clock()
        np.testing.assert_allclose(b.output(3.5, np.zeros(0), np.zeros(0)), [3.5])
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.zeros(0)), [0.0])


class TestPulseGenerator:
    def test_full_period_with_50pct_duty(self):
        b = PulseGenerator(amplitude=2.0, period=1.0, pulse_width=50.0, phase_delay=0.0)
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.zeros(0)), [2.0])
        np.testing.assert_allclose(b.output(0.4, np.zeros(0), np.zeros(0)), [2.0])
        # 0.5 で off (phi=0.5, threshold=0.5 で phi < threshold = False)
        np.testing.assert_allclose(b.output(0.5, np.zeros(0), np.zeros(0)), [0.0])
        np.testing.assert_allclose(b.output(0.9, np.zeros(0), np.zeros(0)), [0.0])
        # 次の周期
        np.testing.assert_allclose(b.output(1.1, np.zeros(0), np.zeros(0)), [2.0])

    def test_invalid_period_raises(self):
        with pytest.raises(BlockSpecError, match="period"):
            PulseGenerator(period=0.0)

    def test_invalid_pulse_width_raises(self):
        with pytest.raises(BlockSpecError, match="pulse_width"):
            PulseGenerator(pulse_width=150.0)


# ---------------------------------------------------------------
# Sinks
# ---------------------------------------------------------------


class TestTerminator:
    def test_runs_in_simulator_without_error(self):
        sim = Simulator(t_end=0.05, dt=0.01)
        src = sim.add(Constant(value=1.0, id="src"))
        term = sim.add(Terminator(n_inputs=1, id="term"))
        sim.connect(src, term)
        sim.run()
        # 例外なく完走すれば OK
        assert term.n_outputs == 0


# ---------------------------------------------------------------
# Discrete (DiscreteIntegrator)
# ---------------------------------------------------------------


class TestDiscreteIntegrator:
    def test_forward_euler_constant_input(self):
        """u=1 の前進 Euler 積分: x[k] = k * sample_time。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        src = sim.add(Constant(value=1.0, id="src"))
        di = sim.add(DiscreteIntegrator(sample_time=0.01, gain=1.0, x0=0.0, id="di"))
        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(src, di)
        sim.connect(di, scope)
        sim.run()

        values = scope.values[:, 0]
        # k=0 で出力 0.0 (x0)、以降 0.01, 0.02, ... と増える
        np.testing.assert_allclose(values[0], 0.0)
        np.testing.assert_allclose(values[1], 0.01, rtol=1e-9)
        np.testing.assert_allclose(values[5], 0.05, rtol=1e-9)

    def test_gain_scales_input(self):
        sim = Simulator(t_end=0.03, dt=0.01)
        src = sim.add(Constant(value=2.0, id="src"))
        di = sim.add(DiscreteIntegrator(sample_time=0.01, gain=3.0, x0=0.0, id="di"))
        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(src, di)
        sim.connect(di, scope)
        sim.run()
        # 1 ステップで 0.01 * 3.0 * 2.0 = 0.06 増える
        assert scope.values[2, 0] == pytest.approx(0.12, rel=1e-9)


class TestDiscreteIntegratorErrors:
    def test_update_without_resolution_raises(self):
        """Simulator 経由せず ``update`` を直接呼ぶと ``BlockSpecError``。

        無音バグ (sample_time=0 で積分が止まる) を防ぐためのガード
        (code-reviewer MUST 修正)。
        """
        di = DiscreteIntegrator(sample_time=0.01, gain=1.0, x0=0.0)
        with pytest.raises(BlockSpecError, match="sample_time has not been resolved"):
            di.update(0.0, np.array([1.0]), np.array([2.0]))


# ---------------------------------------------------------------
# Math
# ---------------------------------------------------------------


class TestSaturation:
    def test_clips_above_upper(self):
        b = Saturation(lower=-1.0, upper=1.0)
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([5.0])), [1.0])

    def test_clips_below_lower(self):
        b = Saturation(lower=-1.0, upper=1.0)
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([-5.0])), [-1.0])

    def test_passes_through_when_inside(self):
        b = Saturation(lower=-1.0, upper=1.0)
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([0.5])), [0.5])

    def test_invalid_bounds_raises(self):
        with pytest.raises(BlockSpecError, match="lower < upper"):
            Saturation(lower=1.0, upper=1.0)


class TestAbs:
    def test_negative_to_positive(self):
        b = Abs()
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([-3.5])), [3.5])

    def test_zero(self):
        b = Abs()
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([0.0])), [0.0])


class TestSign:
    @pytest.mark.parametrize(
        "u, expected",
        [(2.5, 1.0), (-3.0, -1.0), (0.0, 0.0)],
    )
    def test_three_cases(self, u, expected):
        b = Sign()
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([u])), [expected])


class TestMinMax:
    def test_min(self):
        b = MinMax(operator="min", n_inputs=3)
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([5.0, 1.0, 3.0])), [1.0])

    def test_max(self):
        b = MinMax(operator="max", n_inputs=3)
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([5.0, 1.0, 3.0])), [5.0])

    def test_invalid_operator_raises(self):
        with pytest.raises(BlockSpecError, match="operator"):
            MinMax(operator="median")

    def test_invalid_n_inputs_raises(self):
        with pytest.raises(BlockSpecError, match="n_inputs"):
            MinMax(n_inputs=0)


class TestDivide:
    def test_basic_div(self):
        b = Divide(signs="*/")
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([6.0, 3.0])), [2.0])

    def test_mul_then_div(self):
        b = Divide(signs="**/")
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([2.0, 3.0, 4.0])), [1.5])

    def test_starts_with_div(self):
        """signs='/' は ``y = 1.0 / u[0]``。"""
        b = Divide(signs="/")
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([4.0])), [0.25])

    def test_invalid_sign_raises(self):
        with pytest.raises(BlockSpecError, match="signs"):
            Divide(signs="*x")


# ---------------------------------------------------------------
# Logic
# ---------------------------------------------------------------


class TestRelationalOperator:
    @pytest.mark.parametrize(
        "op, a, b, expected",
        [
            ("<", 1.0, 2.0, 1.0),
            ("<", 2.0, 2.0, 0.0),
            ("<=", 2.0, 2.0, 1.0),
            ("==", 2.0, 2.0, 1.0),
            ("!=", 1.0, 2.0, 1.0),
            (">=", 3.0, 2.0, 1.0),
            (">", 3.0, 2.0, 1.0),
        ],
    )
    def test_operators(self, op, a, b, expected):
        block = RelationalOperator(operator=op)
        np.testing.assert_allclose(block.output(0.0, np.zeros(0), np.array([a, b])), [expected])

    def test_invalid_operator_raises(self):
        with pytest.raises(BlockSpecError, match="operator"):
            RelationalOperator(operator="===")


class TestLogicalOperator:
    def test_and(self):
        b = LogicalOperator(operator="AND", n_inputs=3)
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([1.0, 1.0, 1.0])), [1.0])
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([1.0, 0.0, 1.0])), [0.0])

    def test_or(self):
        b = LogicalOperator(operator="OR", n_inputs=2)
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([0.0, 1.0])), [1.0])
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([0.0, 0.0])), [0.0])

    def test_not(self):
        b = LogicalOperator(operator="NOT", n_inputs=1)
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([0.0])), [1.0])
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([1.0])), [0.0])

    def test_xor(self):
        b = LogicalOperator(operator="XOR", n_inputs=2)
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([1.0, 0.0])), [1.0])
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([1.0, 1.0])), [0.0])

    def test_nand(self):
        b = LogicalOperator(operator="NAND", n_inputs=2)
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([1.0, 1.0])), [0.0])
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([1.0, 0.0])), [1.0])

    def test_nor(self):
        b = LogicalOperator(operator="NOR", n_inputs=2)
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([0.0, 0.0])), [1.0])
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([0.0, 1.0])), [0.0])

    def test_not_requires_one_input(self):
        with pytest.raises(BlockSpecError, match="NOT"):
            LogicalOperator(operator="NOT", n_inputs=2)

    def test_and_requires_at_least_2_inputs(self):
        with pytest.raises(BlockSpecError, match="AND"):
            LogicalOperator(operator="AND", n_inputs=1)

    def test_unknown_operator_raises(self):
        with pytest.raises(BlockSpecError, match="unknown operator"):
            LogicalOperator(operator="IMPLIES")


# ---------------------------------------------------------------
# Routing
# ---------------------------------------------------------------


class TestSwitch:
    def test_selects_true_input_when_control_meets_threshold(self):
        b = Switch(threshold=0.5, criterion=">=")
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([10.0, 0.6, 20.0])), [10.0])

    def test_selects_false_input_otherwise(self):
        b = Switch(threshold=0.5, criterion=">=")
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([10.0, 0.4, 20.0])), [20.0])

    def test_strict_greater(self):
        b = Switch(threshold=0.5, criterion=">")
        # control == threshold は false 側
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([10.0, 0.5, 20.0])), [20.0])

    def test_not_equal_criterion(self):
        b = Switch(threshold=0.0, criterion="!=")
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([10.0, 1.0, 20.0])), [10.0])
        np.testing.assert_allclose(b.output(0.0, np.zeros(0), np.array([10.0, 0.0, 20.0])), [20.0])

    def test_invalid_criterion_raises(self):
        with pytest.raises(BlockSpecError, match="criterion"):
            Switch(criterion="<")


# ---------------------------------------------------------------
# Simulator 統合: Step → Saturation → Scope (combinational chain)
# ---------------------------------------------------------------


def test_saturation_integration_in_simulator():
    sim = Simulator(t_end=0.05, dt=0.01)
    src = sim.add(Step(step_time=0.0, final_value=10.0, id="src"))
    sat = sim.add(Saturation(lower=-1.0, upper=1.0, id="sat"))
    scope = sim.add(Scope(n_inputs=1, id="scope"))
    sim.connect(src, sat)
    sim.connect(sat, scope)
    sim.run()
    np.testing.assert_allclose(scope.values[:, 0], 1.0)
