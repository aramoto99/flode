"""SPEC-0028 §2.2: ``cast_value`` (変換規則の SSOT) のテスト。

期待値は SPEC の表の具体値をハードコードする (numpy に問い合わせて生成しない —
numpy 側の挙動変化を検出するため)。
"""

from __future__ import annotations

import numpy as np
import pytest

from flode.core.dtypes import cast_value


class TestFloatToInt:
    """float → 整数: ゼロ方向切り捨て + 決定的飽和 (Q3)。"""

    @pytest.mark.parametrize(
        ("value", "target", "expected"),
        [
            (2.7, "int32", 2),  # 切り捨て (3 ではない)
            (-2.7, "int32", -2),  # ゼロ方向
            (2.5, "int64", 2),  # 偶数丸め (→2) と同値だが規則は切り捨て
            (3.5, "int64", 3),  # 偶数丸めなら 4 — 切り捨てなので 3
            (float("nan"), "int64", 0),
            (float("inf"), "int32", 2147483647),
            (float("-inf"), "int32", -2147483648),
            (float("inf"), "uint8", 255),
            (float("-inf"), "uint8", 0),
            (-1.0, "uint8", 255),  # 域外はモジュラ wrap
            (256.0, "uint8", 0),
            (2147483648.0, "int32", -2147483648),  # int32 域外 wrap
        ],
    )
    def test_hardcoded_table(self, value: float, target: str, expected: int) -> None:
        out = cast_value(np.array([value]), target)
        assert out.dtype == np.dtype(target)
        assert int(out[0]) == expected


class TestToBool:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (0.0, False),
            (1.0, True),
            (-0.5, True),
            (float("nan"), True),  # SPEC-0026 §確定事項 3 と同一規則
            (float("inf"), True),
        ],
    )
    def test_u_ne_zero(self, value: float, expected: bool) -> None:
        out = cast_value(np.array([value]), "bool")
        assert out.dtype == np.dtype("bool")
        assert bool(out[0]) is expected


class TestToFloat64:
    def test_int_widens_exactly(self) -> None:
        out = cast_value(np.array([3], dtype=np.int64), "float64")
        assert out.dtype == np.dtype("float64")
        assert out[0] == 3.0

    def test_float_passthrough(self) -> None:
        out = cast_value(np.array([2.7]), "float64")
        assert out[0] == 2.7


class TestIntToInt:
    def test_narrowing_wraps_modularly(self) -> None:
        # int64(300) → uint8 = 300 mod 256 = 44 (numpy astype と一致)
        out = cast_value(np.array([300], dtype=np.int64), "uint8")
        assert int(out[0]) == 44

    def test_bool_to_int(self) -> None:
        out = cast_value(np.array([True]), "int32")
        assert out.dtype == np.dtype("int32")
        assert int(out[0]) == 1


class TestShapeAndIdentity:
    def test_same_dtype_is_identity(self) -> None:
        arr = np.array([1, 2], dtype=np.int32)
        out = cast_value(arr, "int32")
        assert out.dtype == np.dtype("int32")
        assert np.array_equal(out, arr)

    def test_shape_is_preserved(self) -> None:
        arr = np.array([[1.7, -2.7], [0.0, 5.9]])
        out = cast_value(arr, "int64")
        assert out.shape == (2, 2)
        assert out.tolist() == [[1, -2], [0, 5]]

    def test_rank0_input(self) -> None:
        out = cast_value(np.float64(2.7), "int32")
        assert out.shape == ()
        assert int(out) == 2
