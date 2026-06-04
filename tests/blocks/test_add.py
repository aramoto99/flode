"""v0.35.0: Add ブロックの単体テスト (= Sum の矩形版、機能同等)。"""

from __future__ import annotations

import numpy as np
import pytest

from pyflw.blocks.mathops import Add
from pyflw.exceptions import BlockSpecError


class TestAddConstruction:
    def test_default_signs(self) -> None:
        blk = Add()
        assert blk.n_inputs == 2
        assert blk.n_outputs == 1
        assert blk._params == {"signs": "++"}

    def test_three_inputs(self) -> None:
        blk = Add(signs="+++")
        assert blk.n_inputs == 3

    def test_subtraction(self) -> None:
        blk = Add(signs="+-")
        assert blk.n_inputs == 2
        # signs 内部は ±1 配列
        np.testing.assert_array_equal(blk.signs, np.array([1.0, -1.0]))

    def test_empty_signs_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="non-empty"):
            Add(signs="")

    def test_invalid_char_raises(self) -> None:
        with pytest.raises(BlockSpecError, match=r"\+'/'-"):
            Add(signs="++*")


class TestAddOutput:
    def test_simple_sum(self) -> None:
        blk = Add(signs="++")
        u = np.array([3.0, 4.0])
        y = blk.output(0.0, np.array([]), u)
        assert y[0] == 7.0

    def test_subtract(self) -> None:
        blk = Add(signs="+-")
        u = np.array([10.0, 3.0])
        y = blk.output(0.0, np.array([]), u)
        assert y[0] == 7.0

    def test_mixed(self) -> None:
        blk = Add(signs="+-+")
        u = np.array([5.0, 2.0, 1.0])
        y = blk.output(0.0, np.array([]), u)
        assert y[0] == 4.0  # 5 - 2 + 1

    def test_all_negative(self) -> None:
        blk = Add(signs="--")
        u = np.array([3.0, 4.0])
        y = blk.output(0.0, np.array([]), u)
        assert y[0] == -7.0

    def test_zero_inputs_result(self) -> None:
        blk = Add(signs="+-")
        u = np.array([5.0, 5.0])
        y = blk.output(0.0, np.array([]), u)
        assert y[0] == 0.0


class TestAddVsSum:
    """Add と Sum が同じ機能であることを確認 (= 形状だけ違う)。"""

    def test_same_output_as_sum(self) -> None:
        from pyflw.blocks.mathops import Sum

        signs = "++--+"
        u = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        add_y = Add(signs=signs).output(0.0, np.array([]), u)
        sum_y = Sum(signs=signs).output(0.0, np.array([]), u)
        assert add_y[0] == sum_y[0]
