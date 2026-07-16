"""``parse_t_end`` / ``serialize_t_end`` テスト (ADR-0042 §論点 4)。

JSON 永続化の ``simulator.t_end`` 値の正規化を検証する。
"""

from __future__ import annotations

import math

import pytest

from flode.core.persistence import parse_t_end, serialize_t_end
from flode.exceptions import ModelLoadError


class TestParseTEndAcceptsFiniteValues:
    """有限な正値は float に変換されてそのまま返る。"""

    def test_int_positive(self) -> None:
        assert parse_t_end(10) == 10.0
        assert isinstance(parse_t_end(10), float)

    def test_float_positive(self) -> None:
        assert parse_t_end(0.5) == 0.5

    def test_very_small_positive(self) -> None:
        assert parse_t_end(1e-9) == 1e-9

    def test_very_large_positive(self) -> None:
        assert parse_t_end(1e18) == 1e18


class TestParseTEndAcceptsInfString:
    """``"inf"`` (case-insensitive) は ``math.inf`` に変換される。"""

    def test_lowercase(self) -> None:
        assert parse_t_end("inf") == math.inf

    def test_uppercase(self) -> None:
        assert parse_t_end("INF") == math.inf

    def test_mixed_case(self) -> None:
        assert parse_t_end("Inf") == math.inf

    def test_with_whitespace(self) -> None:
        assert parse_t_end(" inf ") == math.inf
        assert parse_t_end("\tinf\n") == math.inf


class TestParseTEndRejectsBadStrings:
    """``"inf"`` 以外の文字列は ``ModelLoadError``。"""

    def test_plus_inf(self) -> None:
        with pytest.raises(ModelLoadError, match="Invalid t_end"):
            parse_t_end("+inf")

    def test_minus_inf_string(self) -> None:
        with pytest.raises(ModelLoadError, match="Invalid t_end"):
            parse_t_end("-inf")

    def test_infinity(self) -> None:
        with pytest.raises(ModelLoadError, match="Invalid t_end"):
            parse_t_end("infinity")

    def test_unicode_infinity(self) -> None:
        with pytest.raises(ModelLoadError, match="Invalid t_end"):
            parse_t_end("∞")

    def test_nan_string(self) -> None:
        with pytest.raises(ModelLoadError, match="Invalid t_end"):
            parse_t_end("nan")

    def test_empty_string(self) -> None:
        with pytest.raises(ModelLoadError, match="Invalid t_end"):
            parse_t_end("")

    def test_arbitrary(self) -> None:
        with pytest.raises(ModelLoadError, match="Invalid t_end"):
            parse_t_end("forever")


class TestParseTEndRejectsBadNumbers:
    """負値・ゼロ・NaN・``-inf`` は ``ModelLoadError``。"""

    def test_zero(self) -> None:
        with pytest.raises(ModelLoadError, match="must be positive"):
            parse_t_end(0)

    def test_zero_float(self) -> None:
        with pytest.raises(ModelLoadError, match="must be positive"):
            parse_t_end(0.0)

    def test_negative(self) -> None:
        with pytest.raises(ModelLoadError, match="must be positive"):
            parse_t_end(-1.0)

    def test_negative_inf(self) -> None:
        with pytest.raises(ModelLoadError, match="-inf is rejected"):
            parse_t_end(-math.inf)

    def test_nan(self) -> None:
        with pytest.raises(ModelLoadError, match="NaN"):
            parse_t_end(math.nan)


class TestParseTEndRejectsBadTypes:
    """``bool`` / ``None`` / 任意 object は ``ModelLoadError``。"""

    def test_bool_true(self) -> None:
        # bool は Python では int のサブクラスだが、t_end として渡されたら
        # 明確な間違いなので拒否する (= ADR-0042 §論点 4-A)
        with pytest.raises(ModelLoadError, match="bool"):
            parse_t_end(True)

    def test_bool_false(self) -> None:
        with pytest.raises(ModelLoadError, match="bool"):
            parse_t_end(False)

    def test_none(self) -> None:
        with pytest.raises(ModelLoadError, match="Invalid t_end type"):
            parse_t_end(None)

    def test_list(self) -> None:
        with pytest.raises(ModelLoadError, match="Invalid t_end type"):
            parse_t_end([1.0])


class TestSerializeTEnd:
    """``serialize_t_end`` は ``math.inf`` を ``"inf"`` 文字列に変換する。"""

    def test_finite(self) -> None:
        assert serialize_t_end(10.0) == 10.0
        assert isinstance(serialize_t_end(10.0), float)

    def test_inf(self) -> None:
        assert serialize_t_end(math.inf) == "inf"

    def test_roundtrip(self) -> None:
        # parse → serialize → parse でもとに戻る
        assert parse_t_end(serialize_t_end(parse_t_end("inf"))) == math.inf
        assert parse_t_end(serialize_t_end(parse_t_end(5.0))) == 5.0
