"""ユーザーブロックの行エディタの呼び出しと応答の検証 (ADR-0086 §1 / §2)。"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from pytest_mock import MockerFixture

from flode import Block
from flode.exceptions import BlockSpecError, ParamSearchFunctionError
from flode.userblocks import (
    ParamRowsComposeResult,
    ParamRowsDescribeResult,
    ParamRowsDescribeRow,
    ParamRowsField,
    ParamRowsFormResult,
    ParamRowsOption,
    ParamRowsVariant,
    ParamSearchResult,
    ParamSearchRow,
    call_param_rows,
    find_param_rows_method,
)
from flode.userblocks._param_rows import (
    MAX_PARAM_ROWS_ERROR_CHARS,
    MAX_PARAM_ROWS_FIELDS,
    MAX_PARAM_ROWS_ID_CHARS,
    MAX_PARAM_ROWS_LABEL_CHARS,
    MAX_PARAM_ROWS_OPTIONS,
    MAX_PARAM_ROWS_PICK_VALUES,
    MAX_PARAM_ROWS_VALUE_CHARS,
    MAX_PARAM_ROWS_VARIANTS,
)


def _invalid(action: str) -> str:
    return f"the row editor returned an invalid result for action '{action}': "


class _Editor(Block):
    """行エディタを持つブロック。``edit`` は ``result`` を返し、受けた引数を ``calls`` に残す。"""

    block_dynamic_ports = True
    block_param_rows = {"names": "edit"}  # noqa: RUF012 - class の宣言として読む

    result: Any = None
    calls: list[dict[str, Any]]

    def __init__(
        self,
        names: list[str] = [],  # noqa: B006
        other: list[str] = [],  # noqa: B006
        k: float = 1.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(n_inputs=len(names), n_outputs=1, **kwargs)

    @classmethod
    def edit(cls, **kwargs: Any) -> Any:
        cls.calls.append(kwargs)
        return cls.result


def _editor(result: Any, *, dynamic: bool = True) -> type[_Editor]:
    attrs: dict[str, Any] = {"result": result, "calls": []}
    if not dynamic:
        attrs["block_dynamic_ports"] = False
    return type("Editor", (_Editor,), attrs)


def _describe(cls: type, rows: list[str], params: dict[str, Any] | None = None) -> Any:
    return call_param_rows(
        cls, "edit", action="describe", param="names", params=params or {}, rows=rows
    )


def _form(cls: type, row: str | None = None) -> Any:
    return call_param_rows(cls, "edit", action="form", param="names", params={}, row=row)


def _compose(cls: type, **kw: Any) -> Any:
    args: dict[str, Any] = {"variant": "v", "values": {}, "rows": [], "index": None}
    args.update(kw)
    return call_param_rows(cls, "edit", action="compose", param="names", params={}, **args)


def _search(cls: type, *, limit: int = 10) -> Any:
    return call_param_rows(
        cls, "edit", action="search", param="names", params={}, field="f", query=" q ", limit=limit
    )


def _rejected(call: Any, action: str, fragment: str) -> None:
    with pytest.raises(BlockSpecError) as info:
        call()
    message = str(info.value)
    assert not isinstance(info.value, ParamSearchFunctionError)
    assert message.startswith(_invalid(action)), message
    assert fragment in message, message


# ---------------------------------------------------------------------------
# 呼び方 (§1-B)
# ---------------------------------------------------------------------------


class TestCall:
    def test_keyword_call_with_common_and_action_arguments(self):
        cls = _editor({"columns": ["c"], "rows": [{"cells": ["x"]}], "ports": None})

        _describe(cls, ["a"], params={"other": ["z"], "k": 2.0})

        assert cls.calls == [
            {"action": "describe", "param": "names", "params": {"other": ["z"], "k": 2.0},
             "rows": ["a"]}
        ]  # fmt: skip

    def test_params_are_filtered_to_declared_params_without_the_edited_one(self):
        cls = _editor({"columns": ["c"], "rows": [], "ports": None})

        _describe(cls, [], params={"names": ["x"], "other": ["y"], "k": 1, "evil": "/etc/passwd"})

        assert cls.calls[0]["params"] == {"other": ["y"], "k": 1}

    def test_rows_are_a_copy(self):
        class Mutating(_Editor):
            @classmethod
            def edit(cls, rows, **_):
                rows.append("changed")
                return {"columns": ["c"], "rows": [{"cells": [1]}]}

        rows = ["a"]
        call_param_rows(Mutating, "edit", action="describe", param="names", params={}, rows=rows)
        assert rows == ["a"]

    def test_search_query_is_stripped(self):
        cls = _editor({"columns": ["c"], "rows": []})

        _search(cls, limit=3)

        assert cls.calls == [
            {"action": "search", "param": "names", "params": {}, "field": "f", "query": "q",
             "limit": 3}
        ]  # fmt: skip

    def test_unknown_action_is_rejected_before_calling(self):
        cls = _editor(None)
        with pytest.raises(BlockSpecError, match="unknown action"):
            call_param_rows(cls, "edit", action="delete", param="names", params={})
        assert cls.calls == []

    def test_method_without_kwargs_fails_on_the_first_call(self):
        class Strict(_Editor):
            @classmethod
            def edit(cls, action, params, rows):
                return {"columns": ["c"], "rows": []}

        with pytest.raises(ParamSearchFunctionError, match="TypeError"):
            call_param_rows(Strict, "edit", action="describe", param="names", params={}, rows=[])


# ---------------------------------------------------------------------------
# NotImplemented と例外 (§1-C / §3-C)
# ---------------------------------------------------------------------------


class TestNotImplemented:
    @pytest.mark.parametrize("action", ["describe", "form", "compose", "search"])
    def test_not_implemented_is_a_flode_message(self, action: str):
        cls = _editor(NotImplemented)
        kw: dict[str, Any] = {
            "describe": {"rows": []},
            "form": {"row": None},
            "compose": {"variant": "v", "values": {}, "rows": [], "index": None},
            "search": {"field": "f", "query": "q", "limit": 5},
        }[action]

        with pytest.raises(BlockSpecError) as info:
            call_param_rows(cls, "edit", action=action, param="names", params={}, **kw)

        assert not isinstance(info.value, ParamSearchFunctionError)
        assert str(info.value) == (
            f"the block does not support action {action!r} for parameter 'names'"
        )


class TestUserExceptions:
    @pytest.mark.parametrize(
        ("exc", "expected"),
        [(ValueError("bad row"), "ValueError: bad row"), (SystemExit(3), "SystemExit: 3")],
    )
    def test_exception_becomes_function_error(self, exc, expected, caplog):
        class Raising(_Editor):
            @classmethod
            def edit(cls, **_):
                raise exc

        with caplog.at_level(logging.WARNING, logger="flode.userblocks.param_rows"):
            with pytest.raises(ParamSearchFunctionError) as info:
                _compose(Raising)
        assert str(info.value) == expected
        assert any(r.exc_info for r in caplog.records)

    def test_keyboard_interrupt_passes_through(self):
        class Interrupted(_Editor):
            @classmethod
            def edit(cls, **_):
                raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            _compose(Interrupted)

    def test_exception_while_iterating_describe_rows(self):
        def rows() -> Iterator[dict[str, Any]]:
            yield {"cells": ["a"]}
            raise LookupError("broken table")

        with pytest.raises(ParamSearchFunctionError, match="LookupError: broken table"):
            _describe(_editor({"columns": ["c"], "rows": rows()}), ["a", "b"])

    def test_lone_surrogate_in_message_is_replaced(self):
        class Raising(_Editor):
            @classmethod
            def edit(cls, **_):
                raise ValueError("bad\ud800text")

        with pytest.raises(ParamSearchFunctionError) as info:
            _compose(Raising)
        assert str(info.value) == "ValueError: bad?text"

    def test_block_spec_error_is_logged_as_one_line(self, caplog):
        # 入力の誤りを知らせる BlockSpecError はプレビューで頻繁に起きるので、トレースバックを残さない
        class Rejecting(_Editor):
            @classmethod
            def edit(cls, **_):
                raise BlockSpecError("pick at least one part")

        with caplog.at_level(logging.INFO, logger="flode.userblocks.param_rows"):
            with pytest.raises(ParamSearchFunctionError, match="pick at least one part"):
                _compose(Rejecting)
        assert any("pick at least one part" in r.getMessage() for r in caplog.records)
        assert not any(r.exc_info for r in caplog.records)
        assert all(r.levelno < logging.WARNING for r in caplog.records)

    def test_invalid_result_is_logged_without_traceback(self, caplog):
        with caplog.at_level(logging.INFO, logger="flode.userblocks.param_rows"):
            with pytest.raises(BlockSpecError):
                _compose(_editor({}))
        assert any("'row'" in r.getMessage() for r in caplog.records)
        assert not any(r.exc_info for r in caplog.records)


# ---------------------------------------------------------------------------
# describe (§2-C)
# ---------------------------------------------------------------------------


class TestDescribe:
    def test_result(self):
        cls = _editor(
            {
                "columns": ["name", "n"],
                "rows": [
                    {"cells": ["a", 3], "error": None},
                    {"cells": ["b", None], "error": "unknown part"},
                    {"cells": ["c", 1.5], "error": "   "},
                    {"cells": ["d", True]},
                ],
                "ports": "input",
                "extra": 1,
            }
        )

        result = _describe(cls, ["a", "b", "c", "d"])

        assert result == ParamRowsDescribeResult(
            columns=("name", "n"),
            rows=(
                ParamRowsDescribeRow(cells=("a", 3), error=None),
                ParamRowsDescribeRow(cells=("b", None), error="unknown part"),
                ParamRowsDescribeRow(cells=("c", 1.5), error=None),
                ParamRowsDescribeRow(cells=("d", "True"), error=None),
            ),
            ports="input",
        )

    @pytest.mark.parametrize("ports", ["input", "output", None])
    def test_ports_values(self, ports):
        cls = _editor({"columns": ["c"], "rows": [], "ports": ports})
        assert _describe(cls, []).ports == ports

    def test_missing_ports_is_none(self):
        assert _describe(_editor({"columns": ["c"], "rows": []}), []).ports is None

    def test_ports_need_dynamic_ports(self):
        cls = _editor({"columns": ["c"], "rows": [], "ports": "input"}, dynamic=False)
        _rejected(
            lambda: _describe(cls, []),
            "describe",
            "ports can be declared only by a block with block_dynamic_ports = True",
        )

    def test_null_ports_without_dynamic_ports_is_fine(self):
        cls = _editor({"columns": ["c"], "rows": [], "ports": None}, dynamic=False)
        assert _describe(cls, []).ports is None

    def test_long_error_is_clipped(self):
        cls = _editor({"columns": ["c"], "rows": [{"cells": [1], "error": "e" * 2000}]})
        error = _describe(cls, ["a"]).rows[0].error
        assert len(error) == MAX_PARAM_ROWS_ERROR_CHARS

    def test_error_with_lone_surrogate_is_replaced(self):
        cls = _editor({"columns": ["c"], "rows": [{"cells": [1], "error": "x\ud800"}]})
        assert _describe(cls, ["a"]).rows[0].error == "x?"

    def test_generator_rows_are_read_up_to_count_plus_one_and_closed(self):
        produced: list[int] = []
        closed: list[bool] = []

        def rows() -> Iterator[dict[str, Any]]:
            try:
                for i in range(100):
                    produced.append(i)
                    yield {"cells": [i]}
            finally:
                closed.append(True)

        _rejected(
            lambda: _describe(_editor({"columns": ["c"], "rows": rows()}), ["a", "b"]),
            "describe",
            "describe returned more than 2 rows for 2 input rows",
        )
        assert produced == [0, 1, 2]
        assert closed == [True]

    def test_generator_with_the_right_count(self):
        def rows() -> Iterator[dict[str, Any]]:
            yield {"cells": ["x"]}

        result = _describe(_editor({"columns": ["c"], "rows": rows()}), ["a"])
        assert result.rows == (ParamRowsDescribeRow(cells=("x",), error=None),)

    @pytest.mark.parametrize(
        ("result", "fragment"),
        [
            (None, "expected a dict with 'columns' and 'rows', got NoneType"),
            ({"columns": ["c"]}, "must have 'columns' and 'rows'"),
            ({"columns": [], "rows": []}, "'columns' must not be empty"),
            ({"columns": ["c"] * 17, "rows": []}, "at most 16 are allowed"),
            ({"columns": ["c"], "rows": 3}, "'rows' must be a list"),
            ({"columns": ["c"], "rows": "ab"}, "'rows' must be a list"),
            ({"columns": ["c"], "rows": []}, "describe returned 0 rows for 1 input rows"),
            (
                {"columns": ["c"], "rows": [{"cells": [1]}, {"cells": [2]}]},
                "describe returned more than 1 rows for 1 input rows",
            ),
            ({"columns": ["c"], "rows": [["x"]]}, "rows[0] must be a dict with 'cells'"),
            ({"columns": ["c"], "rows": [{"cells": "x"}]}, "rows[0].cells must be a list"),
            (
                {"columns": ["c", "d"], "rows": [{"cells": [1]}]},
                "rows[0].cells has 1 cells but there are 2 columns",
            ),
            ({"columns": ["c"], "rows": [{"cells": [object()]}]}, "rows[0].cells[0] is object"),
            ({"columns": ["c"], "rows": [{"cells": [1], "error": 3}]}, "rows[0].error is int"),
            ({"columns": ["c"], "rows": [{"cells": [1]}], "ports": "both"}, "'ports' must be"),
            ({"columns": ["c"], "rows": [{"cells": [1]}], "ports": 1}, "'ports' must be"),
        ],
    )
    def test_rejected(self, result, fragment):
        _rejected(lambda: _describe(_editor(result), ["a"]), "describe", fragment)


# ---------------------------------------------------------------------------
# form (§2-C)
# ---------------------------------------------------------------------------


def _text(key: str, label: str | None = None) -> dict[str, Any]:
    field: dict[str, Any] = {"key": key, "kind": "text"}
    if label is not None:
        field["label"] = label
    return field


def _choice(key: str, *values: str) -> dict[str, Any]:
    return {"key": key, "kind": "choice", "options": [{"value": v} for v in values]}


def _pick(key: str) -> dict[str, Any]:
    return {"key": key, "kind": "pick", "label": "Parts"}


def _variant(vid: str, *fields: dict[str, Any], label: str | None = None) -> dict[str, Any]:
    variant: dict[str, Any] = {"id": vid, "fields": list(fields)}
    if label is not None:
        variant["label"] = label
    return variant


def _form_result(variants: list[dict[str, Any]], variant: Any = "a", values: Any = None) -> Any:
    out: dict[str, Any] = {"variants": variants, "variant": variant}
    if values is not None:
        out["values"] = values
    return out


class TestForm:
    def test_result_and_defaults(self):
        cls = _editor(
            _form_result(
                [
                    _variant(
                        "a",
                        _text("name", "Name"),
                        _choice("mode", "x", "y"),
                        _pick("parts"),
                        _text("note"),
                        label="Group",
                    ),
                    _variant("b", _text("line"), label=""),
                ],
                values={"name": "n1", "parts": ["p", "q"], "unknown": 3, "line": 5},
            )
        )

        result = _form(cls, "n1: p, q")

        assert result == ParamRowsFormResult(
            variants=(
                ParamRowsVariant(
                    id="a",
                    label="Group",
                    fields=(
                        ParamRowsField(key="name", label="Name", kind="text", options=()),
                        ParamRowsField(
                            key="mode",
                            label="mode",
                            kind="choice",
                            options=(ParamRowsOption("x", "x"), ParamRowsOption("y", "y")),
                        ),
                        ParamRowsField(key="parts", label="Parts", kind="pick", options=()),
                        ParamRowsField(key="note", label="note", kind="text", options=()),
                    ),
                ),
                ParamRowsVariant(
                    id="b",
                    label="b",
                    fields=(ParamRowsField(key="line", label="line", kind="text", options=()),),
                ),
            ),
            variant="a",
            # 選ばれた種類のフィールドだけを正規化し、無いものは既定で埋める
            values={"name": "n1", "mode": "x", "parts": ("p", "q"), "note": ""},
        )
        assert cls.calls[0]["row"] == "n1: p, q"

    def test_values_may_be_omitted(self):
        result = _form(_editor(_form_result([_variant("a", _text("t"))])))
        assert result.values == {"t": ""}

    def test_variant_without_fields(self):
        result = _form(_editor(_form_result([{"id": "a"}])))
        assert result.variants[0].fields == ()

    def test_long_labels_are_clipped(self):
        long = "L" * 500
        result = _form(
            _editor(
                _form_result(
                    [
                        _variant(
                            "a",
                            {"key": "c", "kind": "choice", "label": long,
                             "options": [{"value": "v", "label": long}]},
                            label=long,
                        )
                    ]
                )
            )
        )  # fmt: skip
        variant = result.variants[0]
        assert len(variant.label) == MAX_PARAM_ROWS_LABEL_CHARS
        assert len(variant.fields[0].label) == MAX_PARAM_ROWS_LABEL_CHARS
        assert len(variant.fields[0].options[0].label) == MAX_PARAM_ROWS_LABEL_CHARS

    def test_limits_are_accepted_at_the_boundary(self):
        fields = [_text(f"f{i}") for i in range(MAX_PARAM_ROWS_FIELDS)]
        variants = [_variant("a", *fields)] + [
            _variant(f"v{i}") for i in range(MAX_PARAM_ROWS_VARIANTS - 1)
        ]
        result = _form(_editor(_form_result(variants)))
        assert len(result.variants) == MAX_PARAM_ROWS_VARIANTS
        assert len(result.variants[0].fields) == MAX_PARAM_ROWS_FIELDS

    @pytest.mark.parametrize(
        ("result", "fragment"),
        [
            (None, "expected a dict with 'variants'"),
            ({"variant": "a"}, "'variants' must be a list"),
            (_form_result("a"), "'variants' must be a list"),
            (_form_result([]), "'variants' must not be empty"),
            (
                _form_result([_variant(f"v{i}") for i in range(MAX_PARAM_ROWS_VARIANTS + 1)]),
                f"at most {MAX_PARAM_ROWS_VARIANTS} are allowed",
            ),
            (_form_result(["a"]), "variants[0] must be a dict"),
            (_form_result([{"fields": []}]), "variants[0].id is NoneType"),
            (_form_result([_variant("")]), "variants[0].id is empty"),
            (
                _form_result([_variant("x" * (MAX_PARAM_ROWS_ID_CHARS + 1))]),
                f"at most {MAX_PARAM_ROWS_ID_CHARS} are allowed",
            ),
            (_form_result([_variant("a"), _variant("a")]), "variants[1].id 'a' appears more"),
            (_form_result([_variant("a", label=3)]), "variants[0].label is int"),
            (_form_result([{"id": "a", "fields": "x"}]), "variants[0].fields must be a list"),
            (
                _form_result(
                    [_variant("a", *[_text(f"f{i}") for i in range(MAX_PARAM_ROWS_FIELDS + 1)])]
                ),
                f"at most {MAX_PARAM_ROWS_FIELDS} are allowed",
            ),
            (_form_result([_variant("a", "f")]), "variants[0].fields[0] must be a dict"),
            (_form_result([_variant("a", {"kind": "text"})]), "fields[0].key is NoneType"),
            (
                _form_result([_variant("a", _text("k"), _text("k"))]),
                "variants[0].fields[1].key 'k' appears more",
            ),
            (
                _form_result([_variant("a", {"key": "k", "kind": "date"})]),
                "variants[0].fields[0].kind must be one of",
            ),
            (_form_result([_variant("a", {"key": "k"})]), "fields[0].kind must be one of"),
            (
                _form_result([_variant("a", {"key": "k", "kind": "choice"})]),
                "variants[0].fields[0].options must be a list",
            ),
            (
                _form_result([_variant("a", {"key": "k", "kind": "choice", "options": []})]),
                "variants[0].fields[0].options must not be empty",
            ),
            (
                _form_result(
                    [
                        _variant(
                            "a", _choice("k", *[f"o{i}" for i in range(MAX_PARAM_ROWS_OPTIONS + 1)])
                        )
                    ]
                ),
                f"at most {MAX_PARAM_ROWS_OPTIONS} are allowed",
            ),
            (
                _form_result([_variant("a", {"key": "k", "kind": "choice", "options": ["x"]})]),
                "options[0] must be a dict",
            ),
            (
                _form_result([_variant("a", _choice("k", "x", "x"))]),
                "options[1].value 'x' appears more",
            ),
            (_form_result([_variant("a", _choice("k", "a\nb"))]), "contains a line break"),
            (_form_result([_variant("a")], variant="b"), "'variant' must be one of"),
            (_form_result([_variant("a")], variant=None), "'variant' must be one of"),
            (_form_result([_variant("a")], values=[1]), "'values' must be a dict"),
            (_form_result([_variant("a", _text("t"))], values={"t": 1}), "values['t'] is int"),
            (
                _form_result([_variant("a", _text("t"))], values={"t": "a\nb"}),
                "values['t'] contains a control character",
            ),
            (
                _form_result(
                    [_variant("a", _text("t"))],
                    values={"t": "x" * (MAX_PARAM_ROWS_VALUE_CHARS + 1)},
                ),
                f"at most {MAX_PARAM_ROWS_VALUE_CHARS} are allowed",
            ),
            (
                _form_result([_variant("a", _choice("c", "x"))], values={"c": "y"}),
                "values['c'] must be one of the options",
            ),
            (
                _form_result([_variant("a", _pick("p"))], values={"p": "x"}),
                "values['p'] must be a list of strings",
            ),
            (
                _form_result([_variant("a", _pick("p"))], values={"p": ["x", "x"]}),
                "values['p'][1] 'x' appears more",
            ),
            (
                _form_result([_variant("a", _pick("p"))], values={"p": [""]}),
                "values['p'][0] is empty",
            ),
            (
                _form_result(
                    [_variant("a", _pick("p"))],
                    values={"p": [f"v{i}" for i in range(MAX_PARAM_ROWS_PICK_VALUES + 1)]},
                ),
                f"at most {MAX_PARAM_ROWS_PICK_VALUES} are allowed",
            ),
        ],
    )
    def test_rejected(self, result, fragment):
        _rejected(lambda: _form(_editor(result)), "form", fragment)

    def test_empty_text_value_is_allowed(self):
        result = _form(_editor(_form_result([_variant("a", _text("t"))], values={"t": ""})))
        assert result.values == {"t": ""}

    def test_values_of_other_variants_are_not_validated(self):
        result = _form(
            _editor(
                _form_result(
                    [_variant("a", _text("t")), _variant("b", _choice("c", "x"))],
                    values={"t": "ok", "c": object()},
                )
            )
        )
        assert result.values == {"t": "ok"}


# ---------------------------------------------------------------------------
# compose / search (§2-C)
# ---------------------------------------------------------------------------


class TestCompose:
    def test_result_and_arguments(self):
        cls = _editor({"row": "a: x", "extra": 1})

        result = _compose(
            cls, variant="g", values={"name": "a", "parts": ["x"]}, rows=["b: y"], index=0
        )

        assert result == ParamRowsComposeResult(row="a: x")
        assert cls.calls == [
            {"action": "compose", "param": "names", "params": {}, "variant": "g",
             "values": {"name": "a", "parts": ["x"]}, "rows": ["b: y"], "index": 0}
        ]  # fmt: skip

    @pytest.mark.parametrize(
        ("result", "fragment"),
        [
            ("a: x", "expected a dict with 'row'"),
            ({}, "'row' is NoneType"),
            ({"row": ""}, "'row' is empty"),
            ({"row": "a\nb"}, "contains a line break"),
            ({"row": "a\tb"}, "contains a control character"),
            ({"row": "r" * (MAX_PARAM_ROWS_VALUE_CHARS + 1)}, "at most"),
        ],
    )
    def test_rejected(self, result, fragment):
        _rejected(lambda: _compose(_editor(result)), "compose", fragment)


class TestSearch:
    def test_result_is_the_search_result(self):
        cls = _editor({"columns": ["c"], "rows": [{"cells": [1], "value": "a"}] * 1})

        assert _search(cls) == ParamSearchResult(
            columns=("c",), rows=(ParamSearchRow(cells=(1,), value="a"),), truncated=False
        )

    def test_truncated(self):
        rows = [{"cells": [i], "value": f"v{i}"} for i in range(5)]
        result = _search(_editor({"columns": ["c"], "rows": rows}), limit=2)
        assert result.truncated is True
        assert len(result.rows) == 2

    def test_duplicate_value_is_rejected(self):
        rows = [{"cells": [1], "value": "a"}, {"cells": [2], "value": "a"}]
        _rejected(
            lambda: _search(_editor({"columns": ["c"], "rows": rows})),
            "search",
            "appears more than once",
        )


# ---------------------------------------------------------------------------
# 宣言の引き直し (§3-A)
# ---------------------------------------------------------------------------


class TestFindMethod:
    def test_declared_param(self):
        assert find_param_rows_method(_Editor, "names") == "edit"

    def test_undeclared_param(self):
        assert find_param_rows_method(_Editor, "other") is None

    def test_failure_reading_the_declaration_becomes_function_error(
        self, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
    ):
        mocker.patch("flode.userblocks._param_rows.read_params", side_effect=RuntimeError("meta"))
        with caplog.at_level("WARNING", logger="flode.userblocks.param_rows"):
            with pytest.raises(ParamSearchFunctionError, match="RuntimeError: meta"):
                find_param_rows_method(_Editor, "names")
        assert any(r.exc_info for r in caplog.records)
