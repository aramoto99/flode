"""SPEC-0028 §1 / §2.1: ``dtype`` param (Cast / Constant) のテスト。

語彙検証 / Q2 排他 (output_type × dtype) / Q1 ("auto" は _params に出さない) /
Cast(dtype="float64") の実変換 (恒等ではない) / has_declared_dtype pre-filter。
"""

from __future__ import annotations

import numpy as np
import pytest

from flode import Simulator
from flode.blocks.cast import OUTPUT_TYPES, Cast
from flode.blocks.mathops import Gain
from flode.blocks.sources import Constant
from flode.core.dtypes import DTYPE_PARAM_VALUES, has_declared_dtype
from flode.exceptions import BlockSpecError


class TestDtypeVocabulary:
    def test_param_vocabulary_is_auto_plus_five(self) -> None:
        assert DTYPE_PARAM_VALUES == (
            "auto",
            "float64",
            "bool",
            "int32",
            "int64",
            "uint8",
        )

    @pytest.mark.parametrize("cls", [Cast, Constant])
    def test_invalid_dtype_is_rejected(self, cls: type) -> None:
        with pytest.raises(BlockSpecError, match="dtype must be one of"):
            cls(dtype="float32")

    @pytest.mark.parametrize("cls", [Cast, Constant])
    def test_param_enums_exposes_both_vocabularies(self, cls: type) -> None:
        # registry の inspect 自動走査 (registry.py) が Inspector の <select> に流す
        enums = cls._param_enums
        assert enums["output_type"] == OUTPUT_TYPES
        assert enums["dtype"] == DTYPE_PARAM_VALUES


class TestExclusivity:
    """Q2: output_type と dtype の併用は BlockSpecError (output_type="float" は許可)。"""

    @pytest.mark.parametrize("output_type", ["int", "bool"])
    @pytest.mark.parametrize("dtype", ["float64", "bool", "int32", "int64", "uint8"])
    def test_combining_both_is_rejected(self, output_type: str, dtype: str) -> None:
        with pytest.raises(BlockSpecError, match="cannot be combined"):
            Cast(output_type=output_type, dtype=dtype)
        with pytest.raises(BlockSpecError, match="cannot be combined"):
            Constant(output_type=output_type, dtype=dtype)

    @pytest.mark.parametrize("dtype", ["float64", "bool", "int32", "int64", "uint8"])
    def test_default_output_type_float_is_treated_as_unset(self, dtype: str) -> None:
        # output_type="float" は既定値 = 未指定と同義なので dtype と共存できる
        assert Cast(output_type="float", dtype=dtype).dtype == dtype
        assert Constant(dtype=dtype).dtype == dtype

    @pytest.mark.parametrize("output_type", ["float", "int", "bool"])
    def test_auto_dtype_allows_any_output_type(self, output_type: str) -> None:
        assert Cast(output_type=output_type, dtype="auto").output_type == output_type


class TestAutoOmission:
    """Q1: "auto" は _params に dtype キーを入れない (保存 JSON に出ない)。"""

    def test_auto_is_not_in_params(self) -> None:
        assert "dtype" not in Cast()._params
        assert "dtype" not in Constant()._params

    def test_declared_dtype_is_in_params(self) -> None:
        assert Cast(dtype="int32")._params["dtype"] == "int32"
        assert Constant(value=1.0, dtype="bool")._params["dtype"] == "bool"


class TestRealConversion:
    """Cast(dtype=...) は恒等ではなく実変換 (SPEC-0028 §背景)。"""

    def test_cast_float64_actually_converts_int_input(self) -> None:
        cast = Cast(dtype="float64", id="c")
        y = cast.output(0.0, np.zeros(0), np.array([3], dtype=np.int64))
        assert y.dtype == np.dtype("float64")
        assert y[0] == 3.0

    def test_cast_int32_truncates_toward_zero(self) -> None:
        cast = Cast(dtype="int32", id="c")
        y = cast.output(0.0, np.zeros(0), np.array([2.7]))
        assert y.dtype == np.dtype("int32")
        assert y[0] == 2  # 3 ではない (output_type="int" の偶数丸めとは別物)

    def test_cast_preserves_large_int64_precision(self) -> None:
        big = 2**60 + 1
        cast = Cast(dtype="int64", id="c")
        y = cast.output(0.0, np.zeros(0), np.array([big], dtype=np.int64))
        assert int(y[0]) == big  # float() 経由なら 2^53 で壊れる

    def test_constant_dtype_output(self) -> None:
        c = Constant(value=2.7, dtype="int32", id="c")
        y = c.output(0.0, np.zeros(0), np.zeros(0))
        assert y.dtype == np.dtype("int32")
        assert y[0] == 2

    def test_output_type_path_is_unchanged(self) -> None:
        # AC-5: output_type 経路は従来どおり (float64 の値の意味論)
        c = Constant(value=2.7, output_type="int", id="c")
        y = c.output(0.0, np.zeros(0), np.zeros(0))
        assert y.dtype == np.dtype("float64")
        assert y[0] == 3.0  # 最近接偶数丸め


class TestHasDeclaredDtype:
    """§3.1 pre-filter (AC-1 の構造的保証の入口)。"""

    def test_false_for_plain_model(self) -> None:
        sim = Simulator(t_end=0.1, dt=0.01)
        c = sim.add(Constant(value=1.0, id="c"))
        g = sim.add(Gain(k=2.0, id="g"))
        sim.connect(c, g)
        assert has_declared_dtype(sim) is False

    def test_false_for_output_type_only_model(self) -> None:
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(Constant(value=1.0, output_type="int", id="c"))
        assert has_declared_dtype(sim) is False  # 値の意味論は SM-D を起動しない

    def test_true_when_any_block_declares_dtype(self) -> None:
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(Constant(value=1.0, id="c"))
        sim.add(Cast(dtype="int32", id="k"))
        assert has_declared_dtype(sim) is True
