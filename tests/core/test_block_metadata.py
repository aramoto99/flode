"""メタデータ検証の公開関数のテスト (ADR-0081 §論点 7-A)。

``@block`` と素の ``Block`` サブクラス (``flode.userblocks``) が共有する規則そのものを、
デコレータを通さずに確かめる。``@block`` 経由の挙動は ``test_decorator_metadata.py``。
"""

from __future__ import annotations

import pytest

from flode.core.block_metadata import (
    HIDDEN_ATTRIBUTE,
    METADATA_ATTRIBUTES,
    NO_DEFAULT,
    validate_category,
    validate_choices,
    validate_param_descriptions,
    validate_text,
)
from flode.exceptions import BlockSpecError


def test_attribute_names() -> None:
    assert METADATA_ATTRIBUTES == {
        "block_category",
        "block_display_name",
        "block_description",
        "block_choices",
        "block_param_descriptions",
        "block_input_names",
        "block_output_names",
    }
    assert HIDDEN_ATTRIBUTE == "block_hidden"
    assert HIDDEN_ATTRIBUTE not in METADATA_ATTRIBUTES


class TestCategory:
    def test_valid(self) -> None:
        assert validate_category("Filters", owner="B") == "Filters"

    @pytest.mark.parametrize("bad", ["", " ", None, 1])
    def test_invalid(self, bad) -> None:
        with pytest.raises(BlockSpecError, match="category of 'B'"):
            validate_category(bad, owner="B")


class TestText:
    def test_str_and_mapping(self) -> None:
        assert validate_text("Gain", field="display_name", owner="B") == "Gain"
        src = {"ja": "ゲイン", "en": "Gain"}
        out = validate_text(src, field="display_name", owner="B")
        assert out == src
        assert out is not src

    @pytest.mark.parametrize("bad", ["", "  ", {}, {"ja": ""}, {"": "x"}, {"ja": 1}, ["x"], None])
    def test_invalid(self, bad) -> None:
        with pytest.raises(BlockSpecError, match="description of 'B'"):
            validate_text(bad, field="description", owner="B")


class TestChoices:
    PARAMS = {"mode": "fast", "level": NO_DEFAULT, "k": 1.0}

    def test_valid_returns_tuples(self) -> None:
        out = validate_choices(
            {"mode": ["fast", "slow"], "level": ("a", "b")}, self.PARAMS, owner="B"
        )
        assert out == {"mode": ("fast", "slow"), "level": ("a", "b")}

    def test_required_parameter_skips_default_check(self) -> None:
        assert validate_choices({"level": ["x"]}, self.PARAMS, owner="B") == {"level": ("x",)}

    @pytest.mark.parametrize(
        ("bad", "match"),
        [
            ({"speed": ["a"]}, "'speed', which is not a parameter"),
            ({"mode": []}, "non-empty sequence"),
            ({"mode": "fast"}, "non-empty sequence"),
            ({"mode": ["fast", 1]}, "non-empty sequence"),
            ({"mode": ["fast", "fast"]}, "duplicate"),
            ({"mode": ["slow"]}, "default value 'fast'"),
            ([("mode", ["fast"])], "must be a mapping"),
        ],
    )
    def test_invalid(self, bad, match: str) -> None:
        with pytest.raises(BlockSpecError, match=match):
            validate_choices(bad, self.PARAMS, owner="B")


class TestParamDescriptions:
    def test_valid(self) -> None:
        assert validate_param_descriptions({"k": "Gain"}, ["k", "mode"], owner="B") == {"k": "Gain"}

    def test_language_map_is_copied(self) -> None:
        source = {"ja": "ゲイン", "en": "Gain"}
        result = validate_param_descriptions({"k": source}, ["k"], owner="B")
        assert result == {"k": {"ja": "ゲイン", "en": "Gain"}}
        assert result["k"] is not source

    @pytest.mark.parametrize(
        ("bad", "match"),
        [
            ({"gain": "x"}, "'gain', which is not a parameter"),
            ({"k": 1}, r"param_descriptions\['k'\]"),
            ({"k": {}}, r"param_descriptions\['k'\]"),
            ({"k": {"ja": " "}}, r"param_descriptions\['k'\]"),
            ({"k": {"ja": 1}}, r"param_descriptions\['k'\]"),
            (["k"], "must be a mapping"),
        ],
    )
    def test_invalid(self, bad, match: str) -> None:
        with pytest.raises(BlockSpecError, match=match):
            validate_param_descriptions(bad, ["k", "mode"], owner="B")
