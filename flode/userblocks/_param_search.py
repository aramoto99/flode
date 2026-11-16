"""ユーザーブロックが提供する引数の値の検索 (ADR-0085、試験的)。

ブロックが ``block_param_search`` で宣言した検索関数 (classmethod / staticmethod) を呼び、
戻り値を検証・変換して ``limit`` 件に切り詰める。検索関数の呼び出しと戻り値の読み出し
(generator の進行・Mapping の参照) はユーザーコードの境界として扱い、中断
(``KeyboardInterrupt`` / ``GeneratorExit``) 以外のどんな例外も ``BlockSpecError`` にする
(``resolve_user_block_ports`` と同じ扱い。``SystemExit`` も捕捉する)。インスタンスは作らない。
"""

from __future__ import annotations

import itertools
import logging
import math
import numbers
import time
import types
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..exceptions import BlockSpecError, ParamSearchFunctionError
from ._docmeta import read_params, resolve_param_search
from ._loader import _exception_text, _reraise_if_interrupt, _safe_text, _truncate

_logger = logging.getLogger("flode.userblocks.param_search")

#: 表の列数の上限 (超えたら不正な応答)。
MAX_PARAM_SEARCH_COLUMNS = 16
#: 列見出しの最大長 (超えた分は切り詰める。表示だけの事柄)。
MAX_PARAM_SEARCH_COLUMN_CHARS = 200
#: 文字列のセルの最大長 (超えた分は切り詰める。表示だけの事柄)。
MAX_PARAM_SEARCH_CELL_CHARS = 200
#: ``value`` (引数に入れる 1 行) の最大長 (超えたら不正な応答)。
MAX_PARAM_SEARCH_VALUE_CHARS = 1000
#: これより大きい整数は ``float`` で返す (JSON の数値として JavaScript が正確に読める範囲)。
_MAX_EXACT_INT_BITS = 53
_INVALID_RESULT_PREFIX = "the search function returned an invalid result: "
#: ``value`` に許さない Unicode の一般カテゴリ: 制御文字 (C0 / C1) と行区切り・段落区切り
#: (末尾の U+2028 / U+2029 は ``splitlines()`` の行数では検出できない)。
_FORBIDDEN_VALUE_CATEGORIES = frozenset({"Cc", "Zl", "Zp"})

#: 表のセル 1 つ (JSON の文字列・数値・``null``)。
Cell = str | int | float | None


@dataclass(frozen=True)
class ParamSearchRow:
    """検索結果の 1 行。

    Attributes:
        cells: 表示するセル (列と同じ数)。
        value: 選んだときに引数の末尾に足す 1 行。
    """

    cells: tuple[Cell, ...]
    value: str


@dataclass(frozen=True)
class ParamSearchResult:
    """検証・変換・切り詰め済みの検索結果。

    Attributes:
        columns: 列見出し。
        rows: 行 (最大 ``limit`` 件、ブロックが返した順)。
        truncated: ブロックが ``limit`` 件より多く返した (切り詰めた)。
    """

    columns: tuple[str, ...]
    rows: tuple[ParamSearchRow, ...]
    truncated: bool


class _InvalidResultError(BlockSpecError):
    """検索関数の戻り値の形が不正 (flode 自身の検証。ユーザーコードの例外と区別する)。"""


def _plain_str(value: str) -> str:
    """``str`` の派生型も素の ``str`` にする (派生型の ``__str__`` は呼ばない)。"""
    return str.__str__(value)


def _is_utf8_encodable(text: str) -> bool:
    """孤立サロゲートを含まないか (含むと応答の JSON を UTF-8 にできず 500 になる)。"""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _utf8_safe(text: str) -> str:
    """UTF-8 にできない文字 (孤立サロゲート) を ``?`` に置き換える (表示だけの文字列用)。"""
    return text.encode("utf-8", errors="replace").decode("utf-8")


def find_param_search_method(cls: type, param: str) -> str | None:
    """クラスがその引数に宣言した検索関数の名前を返す (宣言が無効・無ければ ``None``)。

    要求のたびにクラスそのものから宣言を引き直す (registry の写しとは世代がずれうるため、
    ADR-0085 §2-B)。判定は読み込み時と同じ ``resolve_param_search``。

    Args:
        cls: 管理型表にあるユーザーブロックのクラス。
        param: 引数名。

    Returns:
        classmethod / staticmethod の名前、または ``None``。

    Raises:
        ParamSearchFunctionError: 引数一覧や宣言の読み出しでユーザーコードが例外を出した
            (メッセージはユーザーコード由来)。
    """
    try:
        methods, _ = resolve_param_search(cls, read_params(cls))
    except BaseException as e:  # noqa: BLE001 - ユーザーのクラス属性 / メタクラスの境界
        _reraise_if_interrupt(e)
        # 非 loopback では利用者に「サーバログを見よ」とだけ返すので、原因はここで必ず残す
        _logger.warning(
            "cannot read the search declaration of %s.%s (param %r)",
            cls.__module__, cls.__qualname__, param, exc_info=True,
        )  # fmt: skip
        message = _safe_text(e) if isinstance(e, BlockSpecError) else _exception_text(e)
        raise ParamSearchFunctionError(
            _utf8_safe(_truncate(f"cannot read the search declaration of the block: {message}"))
        ) from e
    return methods.get(param)


def _convert_cell(value: Any, where: str) -> Cell:
    """セル 1 つを JSON に載せられる値にする (表示だけの事柄は寛容に直す、ADR-0085 §3-B)。"""
    if value is None:
        return None
    if isinstance(value, bool | np.bool_):
        # bool は int の派生。数値として右寄せにすると紛らわしいので文字列にする
        return "True" if bool(value) else "False"
    if isinstance(value, str):
        return _utf8_safe(_truncate(_plain_str(value), MAX_PARAM_SEARCH_CELL_CHARS))
    if isinstance(value, numbers.Integral):
        as_int = int(value)
        if as_int.bit_length() <= _MAX_EXACT_INT_BITS:
            return as_int
        try:
            return float(as_int)
        except OverflowError:
            return None
    if isinstance(value, numbers.Real):
        as_float = float(value)
        # 欠損値 (NaN) 等は空欄。素のまま返すと JSON 化 (allow_nan=False) で 500 になる
        return as_float if math.isfinite(as_float) else None
    raise _InvalidResultError(
        f"{where} is {type(value).__name__}; a cell must be a string, a number or None"
    )


def _validated_columns(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list | tuple) or not all(isinstance(c, str) for c in raw):
        raise _InvalidResultError("'columns' must be a list of strings")
    if not raw:
        raise _InvalidResultError("'columns' must not be empty")
    if len(raw) > MAX_PARAM_SEARCH_COLUMNS:
        raise _InvalidResultError(
            f"'columns' has {len(raw)} entries; at most {MAX_PARAM_SEARCH_COLUMNS} are allowed"
        )
    for i, column in enumerate(raw):
        if not _is_utf8_encodable(column):
            raise _InvalidResultError(f"columns[{i}] contains a lone surrogate character")
    return tuple(_truncate(_plain_str(c), MAX_PARAM_SEARCH_COLUMN_CHARS) for c in raw)


def _validated_value(raw: Any, where: str) -> str:
    if not isinstance(raw, str):
        raise _InvalidResultError(f"{where} is {type(raw).__name__}; it must be a string")
    value = _plain_str(raw)
    if not value.strip():
        raise _InvalidResultError(f"{where} is empty")
    # str.splitlines() の区切り (\n / \r / \x85 / U+2028 等) も 1 行の約束を壊す
    if len(value.splitlines()) != 1:
        raise _InvalidResultError(f"{where} contains a line break; it must be a single line")
    if any(unicodedata.category(ch) in _FORBIDDEN_VALUE_CATEGORIES for ch in value):
        raise _InvalidResultError(f"{where} contains a control character")  # 行区切りを含む
    if not _is_utf8_encodable(value):
        raise _InvalidResultError(f"{where} contains a lone surrogate character")
    if len(value) > MAX_PARAM_SEARCH_VALUE_CHARS:
        raise _InvalidResultError(
            f"{where} has {len(value)} characters; at most {MAX_PARAM_SEARCH_VALUE_CHARS} "
            f"are allowed"
        )
    return value


def _validated_row(raw: Any, index: int, n_columns: int) -> ParamSearchRow:
    if not isinstance(raw, Mapping):
        raise _InvalidResultError(f"rows[{index}] must be a dict with 'cells' and 'value'")
    cells = raw.get("cells")
    if not isinstance(cells, list | tuple):
        raise _InvalidResultError(f"rows[{index}].cells must be a list")
    if len(cells) != n_columns:
        raise _InvalidResultError(
            f"rows[{index}].cells has {len(cells)} cells but there are {n_columns} columns"
        )
    converted = tuple(
        _convert_cell(cell, f"rows[{index}].cells[{i}]") for i, cell in enumerate(cells)
    )
    value = _validated_value(raw.get("value"), f"rows[{index}].value")
    return ParamSearchRow(cells=converted, value=value)


def _validated_result(result: Any, limit: int) -> ParamSearchResult:
    """戻り値を検証・変換し、先頭から ``limit + 1`` 件だけ取り出して切り詰める。"""
    if not isinstance(result, Mapping):
        raise _InvalidResultError(
            f"expected a dict with 'columns' and 'rows', got {type(result).__name__}"
        )
    if "columns" not in result or "rows" not in result:
        raise _InvalidResultError("the dict must have 'columns' and 'rows'")
    columns = _validated_columns(result["columns"])
    raw_rows = result["rows"]
    if isinstance(raw_rows, str | bytes | Mapping):
        raise _InvalidResultError("'rows' must be a list (or an iterable) of rows")
    try:
        rows_iter: Iterator[Any] = iter(raw_rows)
    except TypeError as e:
        raise _InvalidResultError("'rows' must be a list (or an iterable) of rows") from e
    try:
        # limit + 1 件目があれば「もっとある」。generator なら残りは計算しない
        taken = list(itertools.islice(rows_iter, limit + 1))
    finally:
        if isinstance(rows_iter, types.GeneratorType):
            rows_iter.close()
    truncated = len(taken) > limit
    rows: list[ParamSearchRow] = []
    seen: set[str] = set()
    for index, raw in enumerate(taken[:limit]):
        row = _validated_row(raw, index, len(columns))
        if row.value in seen:
            # フロントは value を選択のキーに使うので、重複は通さない (ADR-0085 §3-B)
            raise _InvalidResultError(
                f"rows[{index}].value {_truncate(row.value, MAX_PARAM_SEARCH_CELL_CHARS)!r} "
                f"appears more than once; each value must be unique in one result"
            )
        seen.add(row.value)
        rows.append(row)
    return ParamSearchResult(columns=columns, rows=tuple(rows), truncated=truncated)


def search_user_block_param(
    cls: type, method_name: str, *, query: str, limit: int, current: Sequence[str]
) -> ParamSearchResult:
    """ユーザーブロックの検索関数を呼び、検証・変換・切り詰め済みの結果を返す。

    検索関数はキーワード引数で呼ぶ (``fn(query=..., limit=..., current=...)``)。
    ``current`` はコピーを渡す (ブロックが書き換えても呼び出し側に影響しない)。

    Args:
        cls: 管理型表にあるユーザーブロックのクラス。
        method_name: ``find_param_search_method`` が返した classmethod / staticmethod の名前。
        query: 検索語 (前後の空白は除いて渡す。空でないこと)。
        limit: 表示する最大件数 (1 以上)。
        current: その引数の現在の値。

    Returns:
        検索結果。

    Raises:
        ParamSearchFunctionError: 検索関数の例外 (メッセージは ``"<型名>: <メッセージ>"``)。
        BlockSpecError: 戻り値の形が不正 (位置付きのメッセージ)。

    メッセージの UTF-8 にできない文字 (孤立サロゲート) は ``?`` に置き換える。
    """
    started = time.perf_counter()
    try:
        fn = getattr(cls, method_name)
        raw = fn(query=query.strip(), limit=limit, current=list(current))
        result = _validated_result(raw, limit)
    except _InvalidResultError as e:
        message = _utf8_safe(_truncate(f"{_INVALID_RESULT_PREFIX}{_safe_text(e)}"))
        _logger.info("param search %s.%s: %s", cls.__name__, method_name, message)
        raise BlockSpecError(message) from e
    except BaseException as e:  # noqa: BLE001 - ユーザーコードの境界 (読み込み時と同じ扱い)
        _reraise_if_interrupt(e)
        # 作者が手元のコンソールで原因を追えるようにトレースバックを残す (ADR-0085 §3-D)
        _logger.warning(
            "param search %s.%s raised an exception",
            cls.__name__,
            method_name,
            exc_info=True,
        )
        message = _safe_text(e) if isinstance(e, BlockSpecError) else _exception_text(e)
        raise ParamSearchFunctionError(_utf8_safe(_truncate(message))) from e
    _logger.debug(
        "param search %s.%s: query of %d chars, %d row(s), truncated=%s, %.3f s",
        cls.__name__,
        method_name,
        len(query),
        len(result.rows),
        result.truncated,
        time.perf_counter() - started,
    )
    return result
