"""SPEC-0028 §1 / §2.1: ``dtype`` param (Cast / Constant) のテスト。

語彙検証 / Q1 ("auto" は _params に出さない — Constant のみ。Cast は v0.56.0
から常に宣言) / Cast(dtype="float64") の実変換 (恒等ではない) /
has_declared_dtype pre-filter。旧 Q2 排他 (output_type × dtype) は v0.56.0 の
output_type 撤去で概念ごと消滅した。
"""

from __future__ import annotations

import numpy as np
import pytest

from flode import Simulator
from flode.blocks.cast import Cast
from flode.blocks.mathops import Gain
from flode.blocks.sources import Constant
from flode.core.signals import DTYPE_PARAM_VALUES, DTYPE_VOCABULARY, has_declared_dtype
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

    def test_param_enums_expose_dtype_vocabulary(self) -> None:
        # registry の inspect 自動走査 (registry.py) が Inspector の <select> に流す。
        # Cast は auto なし (常に変換)、Constant は auto あり (未宣言が既定)。
        assert Cast._param_enums == {"dtype": DTYPE_VOCABULARY}
        assert Constant._param_enums == {"dtype": DTYPE_PARAM_VALUES}


class TestParamsSerialization:
    """Q1: Constant の "auto" は _params に dtype キーを入れない (保存 JSON に出ない)。

    Cast は v0.56.0 から常に宣言ブロックのため dtype が必ず _params に出る。
    """

    def test_constant_auto_is_not_in_params(self) -> None:
        assert "dtype" not in Constant()._params

    def test_cast_always_has_dtype_in_params(self) -> None:
        assert Cast()._params["dtype"] == "float64"

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
        assert y[0] == 2  # 3 ではない (Rounding(round) の偶数丸めとは別物)

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


class TestHasDeclaredDtype:
    """§3.1 pre-filter (AC-1 の構造的保証の入口)。"""

    def test_false_for_plain_model(self) -> None:
        sim = Simulator(t_end=0.1, dt=0.01)
        c = sim.add(Constant(value=1.0, id="c"))
        g = sim.add(Gain(k=2.0, id="g"))
        sim.connect(c, g)
        assert has_declared_dtype(sim) is False

    def test_true_when_any_block_declares_dtype(self) -> None:
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(Constant(value=1.0, id="c"))
        sim.add(Cast(dtype="int32", id="k"))
        assert has_declared_dtype(sim) is True

    def test_cast_always_declares(self) -> None:
        """v0.56.0: Cast は auto を持たないため、Cast を含むモデルは常に SM-B。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(Cast(id="k"))  # 既定 float64 でも宣言
        assert has_declared_dtype(sim) is True
