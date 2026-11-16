"""docstring 解析とメタデータ解決 (ADR-0081 §論点 7)。"""

from __future__ import annotations

import pytest

from flode import Block, block
from flode.exceptions import BlockSpecError
from flode.userblocks._docmeta import (
    is_string_list_type_label,
    parse_docstring,
    read_params,
    resolve_metadata,
    resolve_param_search,
)


class TestParseDocstring:
    def test_summary_and_args(self):
        doc = """Moving average filter.

        Longer explanation that is not the summary.

        Args:
            window (int): Number of samples
                averaged together.
            gain: Output scale.

        Returns:
            The filtered value.
        """
        info = parse_docstring(doc)
        assert info.summary == "Moving average filter."
        assert dict(info.args) == {
            "window": "Number of samples averaged together.",
            "gain": "Output scale.",
        }

    @pytest.mark.parametrize("doc", [None, ""])
    def test_empty(self, doc):
        info = parse_docstring(doc)
        assert info.summary == ""
        assert dict(info.args) == {}

    def test_no_args_section(self):
        assert dict(parse_docstring("Just a line.\n\nMore text: here.").args) == {}

    def test_arguments_header_is_accepted(self):
        info = parse_docstring("S.\n\nArguments:\n    k: Gain.\n")
        assert dict(info.args) == {"k": "Gain."}


class _Plain(Block):
    """Plain block.

    Args:
        k: The gain.
    """

    def __init__(self, k: float = 1.0, mode: str = "a", **kwargs):
        super().__init__(n_inputs=1, n_outputs=1, **kwargs)
        self.k = k
        self.mode = mode


class TestReadParams:
    def test_block_subclass_signature(self):
        params = read_params(_Plain)
        assert [(p.name, p.type_label, p.has_default, p.default) for p in params] == [
            ("k", "float", True, 1.0),
            ("mode", "str", True, "a"),
        ]

    def test_decorated_function_params(self):
        @block
        def scaled(t: float, u: float, *, k: float = 2.0, label: str = "x") -> float:
            return k * u

        params = read_params(scaled)
        assert [(p.name, p.type_label, p.default) for p in params] == [
            ("k", "float", 2.0),
            ("label", "str", "x"),
        ]

    def test_required_param_has_no_default(self):
        @block
        def needs(t: float, u: float, *, k: float) -> float:
            return k * u

        assert [(p.name, p.has_default) for p in read_params(needs)] == [("k", False)]


class TestResolveMetadata:
    def test_defaults(self):
        meta = resolve_metadata(_Plain, {"k": 1.0, "mode": "a"}, n_inputs=1, n_outputs=1)
        assert meta.display_name == "_Plain"
        assert meta.description == "Plain block."
        assert meta.category is None
        assert dict(meta.param_descriptions) == {"k": "The gain."}
        assert dict(meta.choices) == {}

    def test_public_attributes_and_explicit_wins_over_docstring(self):
        class Tuned(_Plain):
            """Tuned block.

            Args:
                k: From docstring.
                mode: Mode from docstring.
            """

            block_category = "filters"
            block_display_name = {"ja": "調整", "en": "Tuned"}
            block_description = "Explicit description."
            block_choices = {"mode": ("a", "b")}
            block_param_descriptions = {"k": "Explicit gain."}
            block_input_names = ("in",)
            block_output_names = ("out",)

        meta = resolve_metadata(Tuned, {"k": 1.0, "mode": "a"}, n_inputs=1, n_outputs=1)
        assert meta.category == "filters"
        assert meta.display_name == "Tuned"
        assert dict(meta.display_name_i18n) == {"ja": "調整", "en": "Tuned"}
        assert meta.description == "Explicit description."
        assert dict(meta.choices) == {"mode": ("a", "b")}
        assert dict(meta.param_descriptions) == {
            "k": "Explicit gain.",
            "mode": "Mode from docstring.",
        }
        assert meta.input_names == ("in",)
        assert meta.output_names == ("out",)

    def test_param_description_language_map(self):
        """引数の説明も言語別に書ける (en が既定の文字列、無ければ最初の値)。"""

        class Bilingual(_Plain):
            """Bilingual.

            Args:
                k: From docstring.
                mode: Mode from docstring.
            """

            block_param_descriptions = {
                "k": {"ja": "ゲイン", "en": "Gain"},
                "mode": {"ja": "動作"},
            }

        meta = resolve_metadata(Bilingual, {"k": 1.0, "mode": "a"}, n_inputs=1, n_outputs=1)
        assert dict(meta.param_descriptions) == {"k": "Gain", "mode": "動作"}
        assert {k: dict(v) for k, v in meta.param_descriptions_i18n.items()} == {
            "k": {"ja": "ゲイン", "en": "Gain"},
            "mode": {"ja": "動作"},
        }

    def test_plain_param_description_has_no_language_map(self):
        class Plain(_Plain):
            block_param_descriptions = {"k": "Gain"}

        meta = resolve_metadata(Plain, {"k": 1.0, "mode": "a"}, n_inputs=1, n_outputs=1)
        assert dict(meta.param_descriptions_i18n) == {}

    def test_mapping_without_en_uses_first_value(self):
        class Ja(_Plain):
            block_display_name = {"ja": "日本語名"}

        meta = resolve_metadata(Ja, {"k": 1.0, "mode": "a"}, n_inputs=1, n_outputs=1)
        assert meta.display_name == "日本語名"

    def test_inheritance_rules(self):
        class Base(_Plain):
            """Base doc."""

            block_category = "cat"
            block_display_name = "Base name"
            block_description = "Base description"

        class Derived(Base):
            pass

        meta = resolve_metadata(Derived, {"k": 1.0, "mode": "a"}, n_inputs=1, n_outputs=1)
        assert meta.category == "cat"  # 継承する
        assert meta.display_name == "Derived"  # 自身の __dict__ だけ
        assert meta.description == ""  # docstring も自身のものだけ

    def test_private_attributes_are_read_for_compatibility(self):
        class Legacy(_Plain):
            _block_category = "legacy"
            _block_display_name = "Legacy name"
            _param_enums = {"mode": ("a", "z")}

        meta = resolve_metadata(Legacy, {"k": 1.0, "mode": "a"}, n_inputs=1, n_outputs=1)
        assert meta.category == "legacy"
        assert meta.display_name == "Legacy name"
        assert dict(meta.choices) == {"mode": ("a", "z")}

    def test_init_docstring_args_are_used_when_class_has_none(self):
        class InitDoc(Block):
            """Summary only."""

            def __init__(self, k: float = 1.0, **kwargs):
                """Build it.

                Args:
                    k: Gain from __init__.
                """
                super().__init__(n_inputs=1, n_outputs=1, **kwargs)

        meta = resolve_metadata(InitDoc, {"k": 1.0}, n_inputs=1, n_outputs=1)
        assert dict(meta.param_descriptions) == {"k": "Gain from __init__."}

    @pytest.mark.parametrize(
        ("attrs", "match"),
        [
            ({"block_category": ""}, "category of"),
            ({"block_choices": {"nope": ("a",)}}, "not a parameter"),
            ({"block_choices": {"mode": "ab"}}, "non-empty sequence"),
            ({"block_choices": {"mode": ()}}, "non-empty sequence"),
            ({"block_choices": {"mode": ("b", "c")}}, "default"),
            ({"block_display_name": 3}, "display_name of"),
            ({"block_param_descriptions": {"nope": "x"}}, "not a parameter"),
            ({"block_input_names": ("a", "b")}, "ports"),
        ],
    )
    def test_invalid_declarations(self, attrs, match):
        cls = type("Bad", (_Plain,), dict(attrs))
        with pytest.raises(BlockSpecError, match=match):
            resolve_metadata(cls, {"k": 1.0, "mode": "a"}, n_inputs=1, n_outputs=1)


class TestParseDocstringComplexity:
    def test_long_lines_are_linear(self):
        """空白の多い長い行が並んでもバックトラックで時間が爆発しない (L-3)。"""
        import time

        line = "    x" + " " * 900 + "!"
        doc = "Summary.\n\nArgs:\n" + "\n".join([line] * 2000)
        start = time.perf_counter()
        parse_docstring(doc)
        assert time.perf_counter() - start < 2.0

    def test_overlong_line_is_not_an_entry(self):
        doc = "S.\n\nArgs:\n    k: Gain.\n    " + "a" * 2000 + ": not an entry\n"
        assert set(parse_docstring(doc).args) == {"k"}

    def test_continuations_are_joined(self):
        doc = "S.\n\nArgs:\n    k: first\n        second\n        third\n"
        assert dict(parse_docstring(doc).args) == {"k": "first second third"}


# ---------------------------------------------------------------------------
# 引数の値の検索の宣言 (ADR-0085 §1-D)
# ---------------------------------------------------------------------------


class TestIsStringListTypeLabel:
    """フロントの ``isStringListTypeLabel`` (tests/paramEdit.test.ts) と同じ例の表。"""

    @pytest.mark.parametrize(
        "label",
        [
            "list[str]",
            "List[str]",
            "tuple[str, ...]",
            "Sequence[str]",
            "collections.abc.Sequence[str]",
            " list[ str ] ",
        ],
    )
    def test_string_lists(self, label):
        assert is_string_list_type_label(label) is True

    @pytest.mark.parametrize(
        "label", ["list[float]", "list", "str", "dict[str, str]", "tuple[str, int]"]
    )
    def test_not_string_lists(self, label):
        assert is_string_list_type_label(label) is False


class _Searchable(Block):
    """Block with string-list parameters."""

    block_param_search = {"names": "search", "tags": "search_static"}

    def __init__(
        self,
        names: list[str] = ["a"],  # noqa: B006 - 既定値の検査に使う
        tags: tuple[str, ...] = (),
        k: float = 1.0,
        numbers: list[float] = [],  # noqa: B006
        **kwargs,
    ):
        super().__init__(n_inputs=1, n_outputs=1, **kwargs)

    @classmethod
    def search(cls, query, limit, current, **_):
        return {"columns": ["c"], "rows": []}

    @staticmethod
    def search_static(query, limit, current, **_):
        return {"columns": ["c"], "rows": []}

    def instance_search(self, query, limit, current):
        return {}

    @property
    def prop_search(self):
        return None

    not_callable = 3


def _resolve(cls):
    return resolve_param_search(cls, read_params(cls))


class TestResolveParamSearch:
    def test_valid_declaration(self):
        methods, warnings = _resolve(_Searchable)
        assert methods == {"names": "search", "tags": "search_static"}
        assert warnings == []

    def test_no_declaration(self):
        assert _resolve(_Plain) == ({}, [])

    def test_is_inherited(self):
        class Child(_Searchable):
            pass

        assert _resolve(Child)[0] == {"names": "search", "tags": "search_static"}

    def test_private_method_name_is_allowed(self):
        class Private(_Searchable):
            block_param_search = {"names": "_hidden"}

            @classmethod
            def _hidden(cls, query, limit, current):
                return {}

        assert _resolve(Private) == ({"names": "_hidden"}, [])

    @pytest.mark.parametrize("raw", [["names"], "names", 3])
    def test_not_a_mapping_ignores_everything(self, raw):
        Bad = type("Bad", (_Searchable,), {"block_param_search": raw})
        methods, warnings = _resolve(Bad)
        assert methods == {}
        assert len(warnings) == 1
        assert "must be a dict" in warnings[0]

    def test_property_declaration_is_not_evaluated(self):
        calls = []

        class Bad(_Searchable):
            @property
            def block_param_search(self):
                calls.append(1)
                return {"names": "search"}

        methods, warnings = _resolve(Bad)
        assert (methods, calls) == ({}, [])
        assert "property" in warnings[0]

    @pytest.mark.parametrize(
        ("declaration", "fragment"),
        [
            ({"missing": "search"}, "no parameter with this name"),
            ({1: "search"}, "no parameter with this name"),
            ({"k": "search"}, "only a parameter annotated as list[str]"),
            ({"numbers": "search"}, "only a parameter annotated as list[str]"),
            ({"names": 5}, "must be the name of a classmethod or staticmethod"),
            ({"names": "nope"}, "has no attribute 'nope'"),
            ({"names": "instance_search"}, "must be a classmethod or staticmethod"),
            ({"names": "prop_search"}, "must be a classmethod or staticmethod"),
            ({"names": "not_callable"}, "must be a classmethod or staticmethod"),
        ],
    )
    def test_bad_item_is_ignored_with_a_warning(self, declaration, fragment):
        Bad = type("Bad", (_Searchable,), {"block_param_search": {**declaration, "tags": "search"}})
        methods, warnings = _resolve(Bad)
        assert methods == {"tags": "search"}
        assert len(warnings) == 1
        assert fragment in warnings[0]

    def test_default_must_be_a_list_of_strings(self):
        class BadDefault(Block):
            block_param_search = {"names": "search"}

            def __init__(self, names: list[str] = [1, 2], **kwargs):  # noqa: B006
                super().__init__(n_inputs=1, n_outputs=1, **kwargs)

            @classmethod
            def search(cls, query, limit, current):
                return {}

        methods, warnings = _resolve(BadDefault)
        assert methods == {}
        assert "default value is a list of strings" in warnings[0]
