"""ユーザーブロックの検索関数の呼び出し・応答の検証・切り詰め (ADR-0085 §2-B / §3)。"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import numpy as np
import pytest
from pytest_mock import MockerFixture

from flode import Block
from flode.exceptions import BlockSpecError, ParamSearchFunctionError
from flode.userblocks import (
    ParamSearchResult,
    ParamSearchRow,
    find_param_search_method,
    search_user_block_param,
)
from flode.userblocks._param_search import (
    MAX_PARAM_SEARCH_CELL_CHARS,
    MAX_PARAM_SEARCH_COLUMN_CHARS,
    MAX_PARAM_SEARCH_COLUMNS,
    MAX_PARAM_SEARCH_VALUE_CHARS,
)

INVALID = "the search function returned an invalid result: "


def _row(value: str, *cells: Any) -> dict[str, Any]:
    return {"cells": list(cells) if cells else [value], "value": value}


class _Returning:
    """``search`` が ``result`` を返すだけの検索提供クラス (インスタンスは作らない)。"""

    result: Any = None
    calls: list[dict[str, Any]]

    @classmethod
    def search(cls, **kwargs: Any) -> Any:
        cls.calls.append(kwargs)
        return cls.result


def _provider(result: Any) -> type[_Returning]:
    return type("Provider", (_Returning,), {"result": result, "calls": []})


def _search(cls: type, *, limit: int = 10, query: str = "q", current: Any = ()) -> Any:
    return search_user_block_param(cls, "search", query=query, limit=limit, current=list(current))


class TestCall:
    def test_keyword_call_and_result(self):
        cls = _provider({"columns": ["name", "n"], "rows": [_row("a: x", "x", 3)]})

        result = _search(cls, query="  x  ", limit=5, current=["b: y"])

        assert result == ParamSearchResult(
            columns=("name", "n"),
            rows=(ParamSearchRow(cells=("x", 3), value="a: x"),),
            truncated=False,
        )
        assert cls.calls == [{"query": "x", "limit": 5, "current": ["b: y"]}]

    def test_current_is_a_copy(self):
        class Mutating:
            @staticmethod
            def search(query, limit, current):
                current.append("changed")
                return {"columns": ["c"], "rows": []}

        current = ["a"]
        search_user_block_param(Mutating, "search", query="q", limit=1, current=current)
        assert current == ["a"]

    def test_extra_keys_are_ignored(self):
        cls = _provider(
            {"columns": ["c"], "rows": [{"cells": ["x"], "value": "x", "id": 1}], "meta": {}}
        )
        assert _search(cls).rows == (ParamSearchRow(cells=("x",), value="x"),)


class TestUserExceptions:
    @pytest.mark.parametrize(
        ("exc", "fragment"),
        [
            (ValueError("bad query"), "ValueError: bad query"),
            (SystemExit(3), "SystemExit: 3"),
        ],
    )
    def test_exception_becomes_block_spec_error(self, exc, fragment, caplog):
        class Raising:
            @classmethod
            def search(cls, **_):
                raise exc

        with caplog.at_level(logging.WARNING, logger="flode.userblocks.param_search"):
            with pytest.raises(BlockSpecError) as info:
                search_user_block_param(Raising, "search", query="q", limit=1, current=[])
        assert str(info.value) == fragment
        # 作者が原因を追えるようにトレースバックを残す
        assert any(r.exc_info for r in caplog.records)

    def test_keyboard_interrupt_passes_through(self):
        class Interrupted:
            @classmethod
            def search(cls, **_):
                raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            search_user_block_param(Interrupted, "search", query="q", limit=1, current=[])

    def test_unprintable_exception(self):
        class Ugly(Exception):
            def __str__(self):
                raise RuntimeError("no")

        class Raising:
            @classmethod
            def search(cls, **_):
                raise Ugly

        with pytest.raises(BlockSpecError, match="Ugly: <unprintable>"):
            search_user_block_param(Raising, "search", query="q", limit=1, current=[])

    def test_exception_while_iterating_rows(self):
        def rows() -> Iterator[dict[str, Any]]:
            yield _row("a")
            raise LookupError("broken table")

        with pytest.raises(BlockSpecError, match="LookupError: broken table"):
            _search(_provider({"columns": ["c"], "rows": rows()}))

    def test_long_message_is_truncated(self):
        class Raising:
            @classmethod
            def search(cls, **_):
                raise ValueError("x" * 5000)

        with pytest.raises(BlockSpecError) as info:
            search_user_block_param(Raising, "search", query="q", limit=1, current=[])
        assert len(str(info.value)) <= 500


class TestInvalidResult:
    @pytest.mark.parametrize(
        ("result", "fragment"),
        [
            (None, "expected a dict with 'columns' and 'rows', got NoneType"),
            ([], "expected a dict"),
            ({"columns": ["c"]}, "must have 'columns' and 'rows'"),
            ({"rows": []}, "must have 'columns' and 'rows'"),
            ({"columns": "c", "rows": []}, "'columns' must be a list of strings"),
            ({"columns": ["c", 1], "rows": []}, "'columns' must be a list of strings"),
            ({"columns": [], "rows": []}, "'columns' must not be empty"),
            (
                {"columns": ["c"] * (MAX_PARAM_SEARCH_COLUMNS + 1), "rows": []},
                f"at most {MAX_PARAM_SEARCH_COLUMNS} are allowed",
            ),
            ({"columns": ["c"], "rows": 3}, "'rows' must be a list"),
            ({"columns": ["c"], "rows": "abc"}, "'rows' must be a list"),
            ({"columns": ["c"], "rows": [["x"]]}, "rows[0] must be a dict"),
            ({"columns": ["c"], "rows": [{"cells": "x", "value": "x"}]}, "rows[0].cells must be"),
            (
                {"columns": ["c", "d"], "rows": [_row("a", 1, 2), _row("b", 1)]},
                "rows[1].cells has 1 cells but there are 2 columns",
            ),
            ({"columns": ["c"], "rows": [_row("a", object())]}, "rows[0].cells[0] is object"),
            ({"columns": ["c"], "rows": [_row("a", b"x")]}, "rows[0].cells[0] is bytes"),
            ({"columns": ["c"], "rows": [{"cells": [1], "value": 1}]}, "rows[0].value is int"),
            ({"columns": ["c"], "rows": [{"cells": [1]}]}, "rows[0].value is NoneType"),
            ({"columns": ["c"], "rows": [_row("", 1)]}, "rows[0].value is empty"),
            ({"columns": ["c"], "rows": [_row("   ", 1)]}, "rows[0].value is empty"),
            ({"columns": ["c"], "rows": [_row("a\nb", 1)]}, "contains a line break"),
            ({"columns": ["c"], "rows": [_row("a\rb", 1)]}, "contains a line break"),
            (
                {"columns": ["c"], "rows": [_row("v" * (MAX_PARAM_SEARCH_VALUE_CHARS + 1), 1)]},
                f"at most {MAX_PARAM_SEARCH_VALUE_CHARS} are allowed",
            ),
            (
                {"columns": ["c"], "rows": [_row("a", 1), _row("b", 2), _row("a", 3)]},
                "rows[2].value 'a' appears more than once",
            ),
        ],
    )
    def test_rejected(self, result, fragment):
        with pytest.raises(BlockSpecError) as info:
            _search(_provider(result))
        message = str(info.value)
        assert message.startswith(INVALID)
        assert fragment in message

    def test_invalid_result_is_logged_without_traceback(self, caplog):
        with caplog.at_level(logging.INFO, logger="flode.userblocks.param_search"):
            with pytest.raises(BlockSpecError):
                _search(_provider({"columns": [], "rows": []}))
        assert any("must not be empty" in r.getMessage() for r in caplog.records)
        assert not any(r.exc_info for r in caplog.records)


class TestCells:
    def test_conversions(self):
        cells = [
            "text",
            None,
            True,
            np.bool_(False),
            np.int64(7),
            np.float32(1.5),
            float("nan"),
            float("inf"),
            np.float64("nan"),
            2**60,
            10**400,
        ]
        result = _search(_provider({"columns": ["c"] * len(cells), "rows": [_row("v", *cells)]}))
        [row] = result.rows
        assert row.cells == (
            "text",
            None,
            "True",
            "False",
            7,
            1.5,
            None,
            None,
            None,
            float(2**60),
            None,
        )
        assert type(row.cells[4]) is int
        assert type(row.cells[5]) is float

    def test_long_strings_are_clipped(self):
        long_cell = "c" * (MAX_PARAM_SEARCH_CELL_CHARS + 50)
        long_column = "h" * (MAX_PARAM_SEARCH_COLUMN_CHARS + 50)
        result = _search(_provider({"columns": [long_column], "rows": [_row("v", long_cell)]}))
        assert len(result.columns[0]) == MAX_PARAM_SEARCH_COLUMN_CHARS
        assert result.columns[0].endswith("…")
        assert len(result.rows[0].cells[0]) == MAX_PARAM_SEARCH_CELL_CHARS

    def test_str_subclass_is_plain_str(self):
        class Loud(str):
            def __str__(self):
                raise AssertionError("must not be called")

        result = _search(_provider({"columns": [Loud("c")], "rows": [_row(Loud("v"), Loud("x"))]}))
        assert type(result.columns[0]) is str
        assert type(result.rows[0].value) is str
        assert type(result.rows[0].cells[0]) is str


class TestTruncation:
    @pytest.mark.parametrize(
        ("n_rows", "limit", "expected_rows", "truncated"),
        [(3, 5, 3, False), (5, 5, 5, False), (6, 5, 5, True), (100, 5, 5, True)],
    )
    def test_list_rows(self, n_rows, limit, expected_rows, truncated):
        rows = [_row(f"v{i}") for i in range(n_rows)]
        result = _search(_provider({"columns": ["c"], "rows": rows}), limit=limit)
        assert len(result.rows) == expected_rows
        assert result.truncated is truncated
        assert [r.value for r in result.rows] == [f"v{i}" for i in range(expected_rows)]

    def test_generator_is_read_only_up_to_limit_plus_one(self):
        produced: list[int] = []
        closed: list[bool] = []

        def rows() -> Iterator[dict[str, Any]]:
            try:
                for i in range(1000):
                    produced.append(i)
                    yield _row(f"v{i}")
            finally:
                closed.append(True)

        result = _search(_provider({"columns": ["c"], "rows": rows()}), limit=3)

        assert result.truncated is True
        assert len(result.rows) == 3
        assert produced == [0, 1, 2, 3]
        assert closed == [True]

    def test_row_beyond_limit_is_not_validated(self):
        rows = [_row("a"), {"broken": True}]
        result = _search(_provider({"columns": ["c"], "rows": rows}), limit=1)
        assert result.truncated is True
        assert [r.value for r in result.rows] == ["a"]


class _Declared(Block):
    """Searchable block."""

    block_param_search = {"names": "search"}

    def __init__(self, names: list[str] = [], **kwargs: Any):  # noqa: B006
        super().__init__(n_inputs=1, n_outputs=1, **kwargs)

    @classmethod
    def search(cls, query, limit, current):
        return {"columns": ["c"], "rows": []}


class TestFindMethod:
    def test_declared_param(self):
        assert find_param_search_method(_Declared, "names") == "search"

    def test_undeclared_param(self):
        assert find_param_search_method(_Declared, "other") is None

    def test_failure_reading_the_declaration_becomes_block_spec_error(self, mocker: MockerFixture):
        mocker.patch("flode.userblocks._param_search.read_params", side_effect=RuntimeError("meta"))
        with pytest.raises(BlockSpecError, match="RuntimeError: meta"):
            find_param_search_method(_Declared, "names")

    def test_failure_reading_the_declaration_is_logged(
        self, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
    ):
        # 非 loopback では利用者に「サーバログを見よ」と返すので、原因はログに残っていなければならない
        mocker.patch("flode.userblocks._param_search.read_params", side_effect=RuntimeError("meta"))
        with caplog.at_level("WARNING", logger="flode.userblocks.param_search"):
            with pytest.raises(BlockSpecError):
                find_param_search_method(_Declared, "names")
        record = next(r for r in caplog.records if "search declaration" in r.getMessage())
        assert record.exc_info is not None and "meta" in str(record.exc_info[1])


class TestUnsafeText:
    """孤立サロゲート・改行の仲間・制御文字 (応答の JSON 化を壊さない、1 行の約束を守る)。"""

    @pytest.mark.parametrize(
        ("value", "fragment"),
        [
            ("a\x85b", "contains a line break"),
            ("a b", "contains a line break"),
            ("a\x0bb", "contains a line break"),
            ("a\tb", "contains a control character"),
            ("a\x00b", "contains a control character"),
            ("a\x9bb", "contains a control character"),
            ("ab ", "contains a control character"),
            ("ab ", "contains a control character"),
            ("a\ud800b", "contains a lone surrogate character"),
        ],
    )
    def test_bad_value_is_rejected(self, value, fragment):
        with pytest.raises(BlockSpecError) as info:
            _search(_provider({"columns": ["c"], "rows": [_row(value, "x")]}))
        message = str(info.value)
        assert message.startswith(INVALID)
        assert fragment in message
        message.encode("utf-8")

    def test_column_with_lone_surrogate_is_rejected(self):
        with pytest.raises(BlockSpecError, match=r"columns\[1\] contains a lone surrogate"):
            _search(_provider({"columns": ["ok", "bad\udc80"], "rows": []}))

    def test_cell_with_lone_surrogate_is_replaced(self):
        result = _search(_provider({"columns": ["c"], "rows": [_row("v", "x\ud800y")]}))
        assert result.rows[0].cells == ("x?y",)

    def test_value_with_unicode_text_is_kept(self):
        result = _search(_provider({"columns": ["c"], "rows": [_row("部品: 抵抗 Ω", "x")]}))
        assert result.rows[0].value == "部品: 抵抗 Ω"

    def test_exception_text_with_lone_surrogate_is_replaced(self):
        class Raising:
            @classmethod
            def search(cls, **_):
                raise ValueError("bad\ud800text")

        with pytest.raises(ParamSearchFunctionError) as info:
            search_user_block_param(Raising, "search", query="q", limit=1, current=[])
        assert str(info.value) == "ValueError: bad?text"

    def test_invalid_result_is_not_a_function_error(self):
        with pytest.raises(BlockSpecError) as info:
            _search(_provider(None))
        assert not isinstance(info.value, ParamSearchFunctionError)
