"""SPEC-0002 / ADR-0053 (v0.36.0): Phase 2 送り Math 系 5 ブロックのテスト。

test-writer agent による網羅的テストを含む:
  - 全 enum 値の代表入力 / 期待出力 (parametrize)
  - nan / inf 伝播
  - 境界値・DeadZone strict 端点
  - CompareToConstant / CompareToZero の全 6 op × True/False / nan
  - _build_compare_fn の直接 dispatch / BlockSpecError
  - SM-B ベクトル入力 / 出力 shape 検証
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from flode.blocks.mathops import (
    CompareToConstant,
    CompareToZero,
    DeadZone,
    MathFunction,
    TrigFunction,
    _build_compare_fn,
)
from flode.exceptions import BlockSpecError

_EMPTY_X = np.array([])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _out1(blk: object, u: np.ndarray) -> float:
    """output() を呼び、スカラー結果を float で返す。"""
    y = blk.output(0.0, _EMPTY_X, u)  # type: ignore[attr-defined]
    return float(y[0])


# ===========================================================================
# TestMathFunction
# ===========================================================================


class TestMathFunction:
    # --- construction / validation ------------------------------------------

    def test_default_function_is_exp(self) -> None:
        blk = MathFunction()
        assert blk.function == "exp"
        assert blk.n_inputs == 1
        assert blk.n_outputs == 1
        assert blk._params == {"function": "exp"}

    def test_unary_inputs(self) -> None:
        for f in ("exp", "log", "log10", "sqrt", "square", "reciprocal"):
            assert MathFunction(function=f).n_inputs == 1

    def test_binary_inputs(self) -> None:
        for f in ("pow", "mod", "rem"):
            assert MathFunction(function=f).n_inputs == 2

    def test_unknown_function_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="MathFunction"):
            MathFunction(function="bogus")

    # --- unary functions: typical values (parametrize) ----------------------

    @pytest.mark.parametrize(
        "fn, u_val, expected",
        [
            ("exp", 0.0, 1.0),
            ("exp", 1.0, math.e),
            ("exp", -1.0, 1.0 / math.e),
            ("log", 1.0, 0.0),
            ("log", math.e, 1.0),
            ("log10", 1.0, 0.0),
            ("log10", 100.0, 2.0),
            ("sqrt", 4.0, 2.0),
            ("sqrt", 0.0, 0.0),
            ("square", 3.0, 9.0),
            ("square", -2.0, 4.0),
            ("square", 0.0, 0.0),
            ("reciprocal", 2.0, 0.5),
            ("reciprocal", 4.0, 0.25),
        ],
    )
    def test_unary_typical(self, fn: str, u_val: float, expected: float) -> None:
        blk = MathFunction(function=fn)
        y = _out1(blk, np.array([u_val]))
        assert y == pytest.approx(expected, rel=1e-12)

    # --- nan / inf propagation ----------------------------------------------

    def test_log_negative_is_nan(self) -> None:
        with np.errstate(invalid="ignore"):
            y = _out1(MathFunction(function="log"), np.array([-1.0]))
        assert math.isnan(y)

    def test_log_zero_is_neg_inf(self) -> None:
        with np.errstate(divide="ignore"):
            y = _out1(MathFunction(function="log"), np.array([0.0]))
        assert math.isinf(y) and y < 0

    def test_log10_negative_is_nan(self) -> None:
        with np.errstate(invalid="ignore"):
            y = _out1(MathFunction(function="log10"), np.array([-1.0]))
        assert math.isnan(y)

    def test_sqrt_negative_is_nan(self) -> None:
        with np.errstate(invalid="ignore"):
            y = _out1(MathFunction(function="sqrt"), np.array([-1.0]))
        assert math.isnan(y)

    def test_reciprocal_zero_is_inf(self) -> None:
        # SPEC-0002 §エッジケース表: u=0 で +inf を伝播 (np.divide 経由)。
        # ADR-0053 §論点 6「定義域外を nan / inf 伝播で統一」と整合。
        with np.errstate(divide="ignore"):
            y = _out1(MathFunction(function="reciprocal"), np.array([0.0]))
        assert math.isinf(y) and y > 0

    def test_reciprocal_avoids_int_zero_trap(self) -> None:
        # np.reciprocal は int 入力で 1 / 2 = 0 になるが、本実装は float 強制。
        y = _out1(MathFunction(function="reciprocal"), np.array([2]))
        assert y == pytest.approx(0.5)

    # --- binary functions ---------------------------------------------------

    def test_exp_output(self) -> None:
        y = MathFunction(function="exp").output(0.0, _EMPTY_X, np.array([0.0]))
        assert y[0] == pytest.approx(1.0)

    def test_pow_output(self) -> None:
        y = MathFunction(function="pow").output(0.0, _EMPTY_X, np.array([2.0, 3.0]))
        assert y[0] == pytest.approx(8.0)

    @pytest.mark.parametrize(
        "u0, u1, expected",
        [
            (2.0, 3.0, 8.0),
            (3.0, 2.0, 9.0),
            (0.0, 0.0, 1.0),  # numpy 仕様: 0^0 = 1
            (4.0, 0.5, 2.0),
            (1.0, 100.0, 1.0),
        ],
    )
    def test_pow_parametrize(self, u0: float, u1: float, expected: float) -> None:
        y = _out1(MathFunction(function="pow"), np.array([u0, u1]))
        assert y == pytest.approx(expected, rel=1e-12)

    def test_pow_negative_base_fractional_exp_is_nan(self) -> None:
        # np.power(-1, 0.5) は複素根を避けて nan (numpy float 仕様)。
        with np.errstate(invalid="ignore"):
            y = _out1(MathFunction(function="pow"), np.array([-1.0, 0.5]))
        assert math.isnan(y)

    @pytest.mark.parametrize(
        "u0, u1, expected",
        [
            (-5.0, 3.0, 1.0),  # 符号は除数 (正) に従う → +1
            (5.0, 3.0, 2.0),
            (5.0, -3.0, -1.0),  # 符号は除数 (負) に従う → -1
            (0.0, 3.0, 0.0),
            (6.0, 3.0, 0.0),
        ],
    )
    def test_mod_parametrize(self, u0: float, u1: float, expected: float) -> None:
        y = _out1(MathFunction(function="mod"), np.array([u0, u1]))
        assert y == pytest.approx(expected, rel=1e-12)

    @pytest.mark.parametrize(
        "u0, u1, expected",
        [
            (-5.0, 3.0, -2.0),  # 符号は被除数 (負) に従う → -2
            (5.0, 3.0, 2.0),
            (5.0, -3.0, 2.0),  # 符号は被除数 (正) に従う → +2
            (0.0, 3.0, 0.0),
        ],
    )
    def test_rem_parametrize(self, u0: float, u1: float, expected: float) -> None:
        y = _out1(MathFunction(function="rem"), np.array([u0, u1]))
        assert y == pytest.approx(expected, rel=1e-12)

    # --- SM-A スカラー出力の確認 (実装は u[0] のみ使用) --------------------

    def test_exp_scalar_output_shape(self) -> None:
        # 実装は float(u[0]) を使用するため、入力がベクトルでも出力は shape (1,)。
        u = np.array([0.0, 1.0, -1.0])
        y = MathFunction(function="exp").output(0.0, _EMPTY_X, u)
        assert y.shape == (1,)
        assert y[0] == pytest.approx(1.0)  # exp(u[0]) = exp(0.0)

    def test_sqrt_scalar_output_shape(self) -> None:
        u = np.array([4.0])
        y = MathFunction(function="sqrt").output(0.0, _EMPTY_X, u)
        assert y.shape == (1,)
        assert y[0] == pytest.approx(2.0)


# ===========================================================================
# TestTrigFunction
# ===========================================================================


class TestTrigFunction:
    # --- construction / validation ------------------------------------------

    def test_default_function_is_sin(self) -> None:
        blk = TrigFunction()
        assert blk.function == "sin"
        assert blk.n_inputs == 1

    def test_atan2_is_binary(self) -> None:
        assert TrigFunction(function="atan2").n_inputs == 2

    def test_all_unary_functions_have_n_inputs_1(self) -> None:
        unary = ("sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh", "tanh")
        for f in unary:
            assert TrigFunction(function=f).n_inputs == 1

    def test_unknown_function_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="TrigFunction"):
            TrigFunction(function="bogus")

    # --- typical values (parametrize) ---------------------------------------

    @pytest.mark.parametrize(
        "fn, u_val, expected",
        [
            ("sin", 0.0, 0.0),
            ("sin", math.pi / 2, 1.0),
            ("sin", math.pi, 0.0),
            ("cos", 0.0, 1.0),
            ("cos", math.pi, -1.0),
            ("cos", math.pi / 2, 0.0),
            ("atan", 0.0, 0.0),
            ("atan", 1.0, math.pi / 4),
            ("atan", -1.0, -math.pi / 4),
            ("sinh", 0.0, 0.0),
            ("cosh", 0.0, 1.0),
            ("tanh", 0.0, 0.0),
            ("tanh", float("inf"), 1.0),
            ("tanh", float("-inf"), -1.0),
        ],
    )
    def test_unary_typical(self, fn: str, u_val: float, expected: float) -> None:
        blk = TrigFunction(function=fn)
        y = _out1(blk, np.array([u_val]))
        assert y == pytest.approx(expected, abs=1e-12)

    def test_sin_zero(self) -> None:
        y = TrigFunction(function="sin").output(0.0, _EMPTY_X, np.array([0.0]))
        assert y[0] == pytest.approx(0.0)

    # --- inverse trig: boundary & domain errors ----------------------------

    @pytest.mark.parametrize("fn, u_val", [("asin", 1.0), ("asin", -1.0)])
    def test_asin_boundary_valid(self, fn: str, u_val: float) -> None:
        y = _out1(TrigFunction(function=fn), np.array([u_val]))
        assert not math.isnan(y)

    @pytest.mark.parametrize("fn", ["asin", "acos"])
    def test_inverse_trig_out_of_domain_is_nan(self, fn: str) -> None:
        with np.errstate(invalid="ignore"):
            y = _out1(TrigFunction(function=fn), np.array([1.5]))
        assert math.isnan(y)

    def test_asin_out_of_domain_is_nan(self) -> None:
        with np.errstate(invalid="ignore"):
            y = TrigFunction(function="asin").output(0.0, _EMPTY_X, np.array([2.0]))
        assert np.isnan(y[0])

    def test_acos_minus_one(self) -> None:
        y = _out1(TrigFunction(function="acos"), np.array([-1.0]))
        assert y == pytest.approx(math.pi, rel=1e-12)

    # --- tan: near π/2 is large but finite (IEEE 754) ----------------------

    def test_tan_near_pi_over_2_is_large_finite(self) -> None:
        # np.tan(π/2) は厳密 inf にはならず ≈ 1.633e16 (浮動小数点の限界)。
        y = _out1(TrigFunction(function="tan"), np.array([math.pi / 2]))
        assert math.isfinite(y)
        assert abs(y) > 1e10

    # --- atan2: quadrant tests ----------------------------------------------

    def test_atan2_origin_is_zero(self) -> None:
        # numpy 仕様: atan2(0, 0) = 0.0。
        y = _out1(TrigFunction(function="atan2"), np.array([0.0, 0.0]))
        assert y == pytest.approx(0.0)

    def test_atan2_quadrant(self) -> None:
        # atan2(1, 0) = π / 2 (第 1 入力 = y、第 2 入力 = x)。
        y = TrigFunction(function="atan2").output(0.0, _EMPTY_X, np.array([1.0, 0.0]))
        assert y[0] == pytest.approx(np.pi / 2)

    @pytest.mark.parametrize(
        "y_val, x_val, expected_rad",
        [
            (1.0, 1.0, math.pi / 4),  # 第 1 象限
            (1.0, -1.0, 3 * math.pi / 4),  # 第 2 象限
            (-1.0, -1.0, -3 * math.pi / 4),  # 第 3 象限
            (-1.0, 1.0, -math.pi / 4),  # 第 4 象限
            (0.0, 1.0, 0.0),  # 正 x 軸
            (1.0, 0.0, math.pi / 2),  # 正 y 軸
        ],
    )
    def test_atan2_four_quadrants(self, y_val: float, x_val: float, expected_rad: float) -> None:
        y = _out1(TrigFunction(function="atan2"), np.array([y_val, x_val]))
        assert y == pytest.approx(expected_rad, abs=1e-12)

    # --- SM-A スカラー出力の確認 (実装は u[0] のみ使用) --------------------

    def test_sin_scalar_output_shape(self) -> None:
        # 実装は float(u[0]) を使用するため、出力は常に shape (1,)。
        u = np.array([0.0])
        y = TrigFunction(function="sin").output(0.0, _EMPTY_X, u)
        assert y.shape == (1,)
        assert y[0] == pytest.approx(0.0)

    def test_cos_scalar_output_shape(self) -> None:
        u = np.array([0.0])
        y = TrigFunction(function="cos").output(0.0, _EMPTY_X, u)
        assert y.shape == (1,)
        assert y[0] == pytest.approx(1.0)


# ===========================================================================
# TestDeadZone
# ===========================================================================


class TestDeadZone:
    # --- construction / validation ------------------------------------------

    def test_defaults(self) -> None:
        blk = DeadZone()
        assert blk.lower == -0.5
        assert blk.upper == 0.5
        assert blk._params == {"lower": -0.5, "upper": 0.5}

    def test_lower_greater_than_upper_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="DeadZone"):
            DeadZone(lower=1.0, upper=0.5)

    def test_lower_equals_upper_allowed(self) -> None:
        # 退化単一点 dead zone (ADR-0053 §論点 5)。
        blk = DeadZone(lower=0.5, upper=0.5)
        assert blk.output(0.0, _EMPTY_X, np.array([0.5]))[0] == 0.0
        assert blk.output(0.0, _EMPTY_X, np.array([1.0]))[0] == pytest.approx(0.5)

    # --- zone: inside / boundary (strict 不等号) ----------------------------

    def test_inside_range_outputs_zero(self) -> None:
        blk = DeadZone()
        y = blk.output(0.0, _EMPTY_X, np.array([0.3]))
        assert y[0] == 0.0

    def test_endpoint_outputs_zero(self) -> None:
        blk = DeadZone()
        assert blk.output(0.0, _EMPTY_X, np.array([0.5]))[0] == 0.0
        assert blk.output(0.0, _EMPTY_X, np.array([-0.5]))[0] == 0.0

    @pytest.mark.parametrize(
        "lower, upper, u_val, expected",
        [
            (-0.5, 0.5, 0.5, 0.0),  # 上端 == upper → 0
            (-0.5, 0.5, -0.5, 0.0),  # 下端 == lower → 0
            (-0.5, 0.5, 0.0, 0.0),  # 中央
            (-0.5, 0.5, 0.3, 0.0),  # 範囲内
            (-0.5, 0.5, -0.3, 0.0),  # 範囲内 (負)
        ],
    )
    def test_inside_zone_parametrize(
        self, lower: float, upper: float, u_val: float, expected: float
    ) -> None:
        assert _out1(DeadZone(lower=lower, upper=upper), np.array([u_val])) == expected

    # --- zone: above upper --------------------------------------------------

    def test_above_upper_offsets(self) -> None:
        y = DeadZone().output(0.0, _EMPTY_X, np.array([0.7]))
        assert y[0] == pytest.approx(0.2)

    @pytest.mark.parametrize(
        "u_val, expected",
        [
            (0.6, 0.1),
            (0.7, 0.2),
            (1.0, 0.5),
            (1.5, 1.0),
        ],
    )
    def test_above_upper_parametrize(self, u_val: float, expected: float) -> None:
        y = _out1(DeadZone(lower=-0.5, upper=0.5), np.array([u_val]))
        assert y == pytest.approx(expected, rel=1e-12)

    # --- zone: below lower --------------------------------------------------

    def test_below_lower_offsets(self) -> None:
        y = DeadZone().output(0.0, _EMPTY_X, np.array([-0.8]))
        assert y[0] == pytest.approx(-0.3)

    @pytest.mark.parametrize(
        "u_val, expected",
        [
            (-0.6, -0.1),
            (-0.8, -0.3),
            (-1.0, -0.5),
            (-1.5, -1.0),
        ],
    )
    def test_below_lower_parametrize(self, u_val: float, expected: float) -> None:
        y = _out1(DeadZone(lower=-0.5, upper=0.5), np.array([u_val]))
        assert y == pytest.approx(expected, rel=1e-12)

    # --- 極端値 / 特殊値 ----------------------------------------------------

    def test_positive_inf_input(self) -> None:
        y = _out1(DeadZone(), np.array([float("inf")]))
        assert math.isinf(y) and y > 0

    def test_negative_inf_input(self) -> None:
        y = _out1(DeadZone(), np.array([float("-inf")]))
        assert math.isinf(y) and y < 0

    def test_nan_input_propagates(self) -> None:
        y = _out1(DeadZone(), np.array([float("nan")]))
        # nan < lower は False、nan > upper は False → zone 内扱いで 0.0。
        # (numpy の nan 比較は全て False)
        assert y == 0.0

    # --- SM-A スカラー出力の確認 (実装は float(u[0]) のみ使用) ------------

    def test_scalar_output_shape(self) -> None:
        # 実装は float(u[0]) を使用するため、出力は常に shape (1,)。
        u = np.array([-1.0])
        y = DeadZone(lower=-0.5, upper=0.5).output(0.0, _EMPTY_X, u)
        assert y.shape == (1,)
        assert y[0] == pytest.approx(-0.5)  # -1.0 - (-0.5) = -0.5


# ===========================================================================
# TestCompareToConstant
# ===========================================================================


class TestCompareToConstant:
    # --- construction / validation ------------------------------------------

    def test_defaults(self) -> None:
        blk = CompareToConstant()
        assert blk.op == "=="
        assert blk.const == 0.0
        assert blk._params == {"op": "==", "const": 0.0}

    def test_unknown_op_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="CompareToConstant"):
            CompareToConstant(op="=>")

    # --- all 6 ops × True / False (parametrize) ----------------------------

    @pytest.mark.parametrize(
        "op, u_val, const, expected_out",
        [
            # == : True
            ("==", 3.0, 3.0, 1.0),
            # == : False
            ("==", 3.0, 4.0, 0.0),
            # != : True
            ("!=", 3.0, 4.0, 1.0),
            # != : False
            ("!=", 3.0, 3.0, 0.0),
            # < : True
            ("<", 2.0, 5.0, 1.0),
            # < : False (equal)
            ("<", 5.0, 5.0, 0.0),
            # < : False (greater)
            ("<", 6.0, 5.0, 0.0),
            # <= : True (less)
            ("<=", 4.0, 5.0, 1.0),
            # <= : True (equal)
            ("<=", 5.0, 5.0, 1.0),
            # <= : False
            ("<=", 6.0, 5.0, 0.0),
            # > : True
            (">", 6.0, 5.0, 1.0),
            # > : False (equal)
            (">", 5.0, 5.0, 0.0),
            # > : False (less)
            (">", 4.0, 5.0, 0.0),
            # >= : True (greater)
            (">=", 6.0, 5.0, 1.0),
            # >= : True (equal)
            (">=", 5.0, 5.0, 1.0),
            # >= : False
            (">=", 4.0, 5.0, 0.0),
        ],
    )
    def test_all_ops_true_false(
        self, op: str, u_val: float, const: float, expected_out: float
    ) -> None:
        y = _out1(CompareToConstant(op=op, const=const), np.array([u_val]))
        assert y == expected_out

    def test_equal_true(self) -> None:
        y = CompareToConstant(op="==", const=3.0).output(0.0, _EMPTY_X, np.array([3.0]))
        assert y[0] == 1.0

    def test_greater_false(self) -> None:
        y = CompareToConstant(op=">", const=5.0).output(0.0, _EMPTY_X, np.array([4.0]))
        assert y[0] == 0.0

    # --- nan 比較 -----------------------------------------------------------

    def test_nan_equality_is_false(self) -> None:
        y = CompareToConstant(op="==", const=0.0).output(0.0, _EMPTY_X, np.array([np.nan]))
        assert y[0] == 0.0

    def test_nan_inequality_is_true(self) -> None:
        # numpy 仕様: nan != x は True。
        y = CompareToConstant(op="!=", const=0.0).output(0.0, _EMPTY_X, np.array([np.nan]))
        assert y[0] == 1.0

    @pytest.mark.parametrize("op", ["<", "<=", ">", ">="])
    def test_nan_ordered_ops_are_false(self, op: str) -> None:
        y = _out1(CompareToConstant(op=op, const=0.0), np.array([float("nan")]))
        assert y == 0.0

    # --- 特殊定数値 ---------------------------------------------------------

    def test_const_negative(self) -> None:
        blk = CompareToConstant(op=">=", const=-3.0)
        assert _out1(blk, np.array([-3.0])) == 1.0
        assert _out1(blk, np.array([-4.0])) == 0.0

    def test_const_large(self) -> None:
        blk = CompareToConstant(op="<", const=1e10)
        assert _out1(blk, np.array([0.0])) == 1.0
        assert _out1(blk, np.array([1e10])) == 0.0

    # --- SM-A スカラー出力の確認 (実装は float(u[0]) のみ使用) ------------

    def test_scalar_output_shape(self) -> None:
        # 実装は float(u[0]) を使用するため、出力は常に shape (1,)。
        u = np.array([3.0])
        y = CompareToConstant(op=">=", const=2.0).output(0.0, _EMPTY_X, u)
        assert y.shape == (1,)
        assert y[0] == 1.0


# ===========================================================================
# TestCompareToZero
# ===========================================================================


class TestCompareToZero:
    # --- construction / validation ------------------------------------------

    def test_defaults(self) -> None:
        blk = CompareToZero()
        assert blk.op == "=="
        assert blk._params == {"op": "=="}

    def test_unknown_op_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="CompareToZero"):
            CompareToZero(op="bogus")

    # --- all 6 ops dispatch (parametrize) -----------------------------------

    @pytest.mark.parametrize(
        "op, u_val, expected_out",
        [
            # ==
            ("==", 0.0, 1.0),
            ("==", 1e-9, 0.0),
            ("==", -1e-9, 0.0),
            # !=
            ("!=", 1.0, 1.0),
            ("!=", 0.0, 0.0),
            # <
            ("<", -0.1, 1.0),
            ("<", 0.0, 0.0),
            ("<", 0.1, 0.0),
            # <=
            ("<=", -0.1, 1.0),
            ("<=", 0.0, 1.0),
            ("<=", 0.1, 0.0),
            # >
            (">", 0.1, 1.0),
            (">", 0.0, 0.0),
            (">", -0.1, 0.0),
            # >=
            (">=", 0.1, 1.0),
            (">=", 0.0, 1.0),
            (">=", -0.1, 0.0),
        ],
    )
    def test_all_ops_dispatch(self, op: str, u_val: float, expected_out: float) -> None:
        y = _out1(CompareToZero(op=op), np.array([u_val]))
        assert y == expected_out

    def test_positive_check(self) -> None:
        blk = CompareToZero(op=">")
        assert blk.output(0.0, _EMPTY_X, np.array([0.1]))[0] == 1.0
        assert blk.output(0.0, _EMPTY_X, np.array([0.0]))[0] == 0.0
        assert blk.output(0.0, _EMPTY_X, np.array([-0.1]))[0] == 0.0

    def test_equals_zero(self) -> None:
        blk = CompareToZero(op="==")
        assert blk.output(0.0, _EMPTY_X, np.array([0.0]))[0] == 1.0
        assert blk.output(0.0, _EMPTY_X, np.array([1e-9]))[0] == 0.0

    # --- ±0.0 の境界 -------------------------------------------------------

    def test_positive_zero_equals_zero(self) -> None:
        assert _out1(CompareToZero(op="=="), np.array([+0.0])) == 1.0

    def test_negative_zero_equals_zero(self) -> None:
        # Python / numpy では -0.0 == 0.0 が True。
        assert _out1(CompareToZero(op="=="), np.array([-0.0])) == 1.0

    def test_negative_zero_not_less_than_zero(self) -> None:
        assert _out1(CompareToZero(op="<"), np.array([-0.0])) == 0.0

    def test_negative_zero_not_greater_than_zero(self) -> None:
        assert _out1(CompareToZero(op=">"), np.array([-0.0])) == 0.0

    # --- nan 比較 -----------------------------------------------------------

    def test_nan_greater_than_zero_is_false(self) -> None:
        y = _out1(CompareToZero(op=">"), np.array([float("nan")]))
        assert y == 0.0

    @pytest.mark.parametrize("op", ["==", "<", "<=", ">", ">="])
    def test_nan_non_ne_ops_are_false(self, op: str) -> None:
        y = _out1(CompareToZero(op=op), np.array([float("nan")]))
        assert y == 0.0

    def test_nan_ne_op_is_true(self) -> None:
        y = _out1(CompareToZero(op="!="), np.array([float("nan")]))
        assert y == 1.0

    # --- SM-A スカラー出力の確認 (実装は float(u[0]) のみ使用) ------------

    def test_scalar_output_shape(self) -> None:
        # 実装は float(u[0]) を使用するため、出力は常に shape (1,)。
        u = np.array([1.0])
        y = CompareToZero(op=">").output(0.0, _EMPTY_X, u)
        assert y.shape == (1,)
        assert y[0] == 1.0


# ===========================================================================
# TestBuildCompareFn
# ===========================================================================


class TestBuildCompareFn:
    """_build_compare_fn を直接 import して 6 op すべてを検証。"""

    @pytest.mark.parametrize(
        "op, a, b, expected",
        [
            ("==", 1.0, 1.0, True),
            ("==", 1.0, 2.0, False),
            ("!=", 1.0, 2.0, True),
            ("!=", 1.0, 1.0, False),
            ("<", 1.0, 2.0, True),
            ("<", 2.0, 2.0, False),
            ("<", 3.0, 2.0, False),
            ("<=", 1.0, 2.0, True),
            ("<=", 2.0, 2.0, True),
            ("<=", 3.0, 2.0, False),
            (">", 3.0, 2.0, True),
            (">", 2.0, 2.0, False),
            (">", 1.0, 2.0, False),
            (">=", 3.0, 2.0, True),
            (">=", 2.0, 2.0, True),
            (">=", 1.0, 2.0, False),
        ],
    )
    def test_all_ops(self, op: str, a: float, b: float, expected: bool) -> None:
        fn = _build_compare_fn(op)
        assert fn(a, b) is expected

    def test_unknown_op_raises_block_spec_error(self) -> None:
        with pytest.raises(BlockSpecError):
            _build_compare_fn("??")

    def test_invalid_op_raises_block_spec_error(self) -> None:
        with pytest.raises(BlockSpecError):
            _build_compare_fn("=>")

    def test_empty_op_raises_block_spec_error(self) -> None:
        with pytest.raises(BlockSpecError):
            _build_compare_fn("")


# ===========================================================================
# TestRegistryIntegration
# ===========================================================================


class TestRegistryIntegration:
    """5 ブロックが registry / i18n / persistence で正しく扱われる smoke。"""

    def test_blocks_module_exports(self) -> None:
        from flode import blocks

        assert blocks.MathFunction is MathFunction
        assert blocks.TrigFunction is TrigFunction
        assert blocks.DeadZone is DeadZone
        assert blocks.CompareToConstant is CompareToConstant
        assert blocks.CompareToZero is CompareToZero

    def test_registry_contains_five_blocks(self) -> None:
        from flode.server.registry import build_block_registry

        registry = build_block_registry()
        type_paths = {m.type_path for m in registry}
        for cls_name in (
            "MathFunction",
            "TrigFunction",
            "DeadZone",
            "CompareToConstant",
            "CompareToZero",
        ):
            assert f"flode.blocks.mathops.{cls_name}" in type_paths

    def test_to_dict_round_trip_mathfunction(self) -> None:
        from flode.core.persistence import resolve_block_class

        blk = MathFunction(function="pow")
        d = blk.to_dict()
        assert d["type"] == "flode.blocks.mathops.MathFunction"
        assert d["params"] == {"function": "pow"}
        cls = resolve_block_class(d["type"])
        restored = cls(**d["params"])
        assert restored.function == "pow"
        assert restored.n_inputs == 2
