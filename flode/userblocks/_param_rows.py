"""ユーザーブロックが提供する行リスト引数の行エディタ (ADR-0086、試験的)。

ブロックが ``block_param_rows`` で宣言したメソッド (classmethod / staticmethod) を
``action`` (``describe`` / ``form`` / ``compose`` / ``search``) で呼び分け、戻り値を検証・変換する。
呼び出しと戻り値の読み出し (generator の進行・Mapping の参照) はユーザーコードの境界として扱い、
中断 (``KeyboardInterrupt`` / ``GeneratorExit``) 以外のどんな例外も ``ParamSearchFunctionError``
にする (ADR-0085 の検索と同じ扱い)。インスタンスは作らない。

検証部品は ``_param_search.py`` のものを流用する (ADR-0086 §2-A、S1)。
"""

from __future__ import annotations

import itertools
import logging
import time
import types
import unicodedata
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from ..exceptions import BlockSpecError, ParamSearchFunctionError
from ._docmeta import has_dynamic_ports, read_params, resolve_param_rows
from ._loader import (
    MAX_MESSAGE_CHARS,
    _exception_text,
    _reraise_if_interrupt,
    _safe_text,
    _truncate,
)
from ._param_search import (
    _FORBIDDEN_VALUE_CATEGORIES,
    MAX_PARAM_SEARCH_VALUE_CHARS,
    Cell,
    ParamSearchResult,
    _convert_cell,
    _InvalidResultError,
    _is_utf8_encodable,
    _plain_str,
    _utf8_safe,
    _validated_columns,
    _validated_result,
    _validated_value,
)

_logger = logging.getLogger("flode.userblocks.param_rows")

#: flode が送る action (これ以外はユーザーコードを呼ぶ前に拒否する、ADR-0086 §1-C)。
PARAM_ROWS_ACTIONS: tuple[str, ...] = ("describe", "form", "compose", "search")
#: form の種類の数の上限 (1 以上)。
MAX_PARAM_ROWS_VARIANTS = 16
#: 1 種類あたりのフィールド数の上限 (0 可)。
MAX_PARAM_ROWS_FIELDS = 16
#: choice フィールド 1 つあたりの選択肢の数の上限 (1 以上)。
MAX_PARAM_ROWS_OPTIONS = 256
#: pick フィールドの選択数の上限。
MAX_PARAM_ROWS_PICK_VALUES = 128
#: 要求で送り返す識別子 (種類の ``id`` / フィールドの ``key``) の最大長 (超えたら不正な応答)。
MAX_PARAM_ROWS_ID_CHARS = 64
#: 種類・フィールド・選択肢の ``label`` の最大長 (超えた分は切り詰める。表示だけの事柄)。
MAX_PARAM_ROWS_LABEL_CHARS = 100
#: describe の行の ``error`` の最大長 (超えた分は切り詰める)。
MAX_PARAM_ROWS_ERROR_CHARS = MAX_MESSAGE_CHARS
#: 組み立てた行・choice / pick / text の値の最大長 (要求の行の上限と揃える)。
MAX_PARAM_ROWS_VALUE_CHARS = MAX_PARAM_SEARCH_VALUE_CHARS

#: フィールドの種類。
FieldKind = Literal["text", "choice", "pick"]
_FIELD_KINDS: tuple[str, ...] = ("text", "choice", "pick")
#: describe の ``ports`` (行 i = 入力 / 出力ポート i)。
PortsSide = Literal["input", "output"]
_PORTS_SIDES: tuple[str, ...] = ("input", "output")
#: action ごとの追加の引数 (呼び出し側の誤りを早く知らせる)。
_ACTION_ARGUMENTS: dict[str, frozenset[str]] = {
    "describe": frozenset({"rows"}),
    "form": frozenset({"row"}),
    "compose": frozenset({"variant", "values", "rows", "index"}),
    "search": frozenset({"field", "query", "limit"}),
}


@dataclass(frozen=True)
class ParamRowsDescribeRow:
    """describe の 1 行 (要求の同じ位置の行の説明)。

    Attributes:
        cells: 表示するセル (列と同じ数)。
        error: その行の誤り (無ければ ``None``)。
    """

    cells: tuple[Cell, ...]
    error: str | None


@dataclass(frozen=True)
class ParamRowsDescribeResult:
    """検証済みの describe の結果。

    Attributes:
        columns: 列見出し。
        rows: 要求の行と同じ数・同じ順の説明。
        ports: 行 i が入力 / 出力ポート i に対応するなら ``"input"`` / ``"output"``。
    """

    columns: tuple[str, ...]
    rows: tuple[ParamRowsDescribeRow, ...]
    ports: PortsSide | None


@dataclass(frozen=True)
class ParamRowsOption:
    """choice フィールドの選択肢 1 つ。"""

    value: str
    label: str


@dataclass(frozen=True)
class ParamRowsField:
    """編集ダイアログのフィールド 1 つ (``options`` は choice のときだけ空でない)。"""

    key: str
    label: str
    kind: FieldKind
    options: tuple[ParamRowsOption, ...]


@dataclass(frozen=True)
class ParamRowsVariant:
    """行の種類 1 つ (種類ごとにフィールドが違う)。"""

    id: str
    label: str
    fields: tuple[ParamRowsField, ...]


@dataclass(frozen=True)
class ParamRowsFormResult:
    """検証済みの form の結果。

    Attributes:
        variants: すべての種類。
        variant: 選ばれた種類の ``id``。
        values: 選ばれた種類のフィールドの値 (無いものは既定で補完済み。text / choice は
            ``str``、pick は ``tuple[str, ...]``)。
    """

    variants: tuple[ParamRowsVariant, ...]
    variant: str
    values: Mapping[str, str | tuple[str, ...]]


@dataclass(frozen=True)
class ParamRowsComposeResult:
    """検証済みの compose の結果 (引数に入れる 1 行)。"""

    row: str


#: ``call_param_rows`` の戻り値 (search は ADR-0085 の検索結果と同じ形)。
ParamRowsResult = (
    ParamRowsDescribeResult | ParamRowsFormResult | ParamRowsComposeResult | ParamSearchResult
)


def find_param_rows_method(cls: type, param: str) -> str | None:
    """クラスがその引数に宣言した行エディタのメソッド名を返す (宣言が無効・無ければ ``None``)。

    要求のたびにクラスそのものから宣言を引き直す (registry の写しとは世代がずれうるため)。
    判定は読み込み時と同じ ``resolve_param_rows``。

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
        methods, _ = resolve_param_rows(cls, read_params(cls))
    except BaseException as e:  # noqa: BLE001 - ユーザーのクラス属性 / メタクラスの境界
        _reraise_if_interrupt(e)
        _logger.warning(
            "cannot read the row editor declaration of %s.%s (param %r)",
            cls.__module__, cls.__qualname__, param, exc_info=True,
        )  # fmt: skip
        message = _safe_text(e) if isinstance(e, BlockSpecError) else _exception_text(e)
        raise ParamSearchFunctionError(
            _utf8_safe(_truncate(f"cannot read the row editor declaration of the block: {message}"))
        ) from e
    return methods.get(param)


# ---------------------------------------------------------------------------
# 応答の検証部品 (ADR-0086 §2-A)
# ---------------------------------------------------------------------------


def is_single_line_text(value: str) -> bool:
    """制御文字・行区切りを含まないか (空文字列は真)。

    ``str.splitlines()`` の区切り (\\n / \\r / \\v / \\f / \\x1c〜\\x1e / \\x85 / U+2028 /
    U+2029) はすべて ``_FORBIDDEN_VALUE_CATEGORIES`` に入るので、このカテゴリだけ見れば足りる。
    要求の文字列 (routes の param-rows) の検査にも使う。
    """
    return not any(unicodedata.category(ch) in _FORBIDDEN_VALUE_CATEGORIES for ch in value)


def _validated_text(raw: Any, where: str, max_chars: int = MAX_PARAM_ROWS_VALUE_CHARS) -> str:
    """空を許す 1 行テキスト (制御文字・行区切り・孤立サロゲートなし、``max_chars`` 字以内)。"""
    if not isinstance(raw, str):
        raise _InvalidResultError(f"{where} is {type(raw).__name__}; it must be a string")
    value = _plain_str(raw)
    if not is_single_line_text(value):
        raise _InvalidResultError(f"{where} contains a control character")
    if not _is_utf8_encodable(value):
        raise _InvalidResultError(f"{where} contains a lone surrogate character")
    if len(value) > max_chars:
        raise _InvalidResultError(
            f"{where} has {len(value)} characters; at most {max_chars} are allowed"
        )
    return value


def _validated_id(raw: Any, where: str) -> str:
    """要求で送り返す短い識別子 (``_validated_value`` + ``MAX_PARAM_ROWS_ID_CHARS`` 字以内)。"""
    value = _validated_value(raw, where)
    if len(value) > MAX_PARAM_ROWS_ID_CHARS:
        raise _InvalidResultError(
            f"{where} has {len(value)} characters; at most {MAX_PARAM_ROWS_ID_CHARS} are allowed"
        )
    return value


def _validated_label(raw: Any, where: str, fallback: str) -> str:
    """表示用の ``label`` (無い・空なら ``fallback``、長ければ切る。``str`` 以外は不正)。"""
    if raw is None:
        return fallback
    if not isinstance(raw, str):
        raise _InvalidResultError(f"{where} is {type(raw).__name__}; it must be a string")
    label = _plain_str(raw)
    if not label.strip():
        return fallback
    return _utf8_safe(_truncate(label, MAX_PARAM_ROWS_LABEL_CHARS))


def _validated_list(raw: Any, where: str, *, min_items: int, max_items: int) -> Sequence[Any]:
    if not isinstance(raw, list | tuple):
        raise _InvalidResultError(f"{where} must be a list")
    if len(raw) < min_items:
        raise _InvalidResultError(f"{where} must not be empty")
    if len(raw) > max_items:
        raise _InvalidResultError(
            f"{where} has {len(raw)} entries; at most {max_items} are allowed"
        )
    return raw


def _check_unique(value: str, seen: set[str], where: str) -> None:
    if value in seen:
        # フロントはこれらの値をキーに使うので重複は通さない
        raise _InvalidResultError(
            f"{where} {_truncate(value, MAX_PARAM_ROWS_LABEL_CHARS)!r} appears more than once"
        )
    seen.add(value)


# ---------------------------------------------------------------------------
# describe
# ---------------------------------------------------------------------------


def _validated_describe_row(raw: Any, index: int, n_columns: int) -> ParamRowsDescribeRow:
    if not isinstance(raw, Mapping):
        raise _InvalidResultError(f"rows[{index}] must be a dict with 'cells' and 'error'")
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
    raw_error = raw.get("error")
    error: str | None = None
    if raw_error is not None:
        if not isinstance(raw_error, str):
            raise _InvalidResultError(
                f"rows[{index}].error is {type(raw_error).__name__}; it must be a string or None"
            )
        text = _plain_str(raw_error)
        if text.strip():
            error = _utf8_safe(_truncate(text, MAX_PARAM_ROWS_ERROR_CHARS))
    return ParamRowsDescribeRow(cells=converted, error=error)


def _validated_describe(raw: Any, n_rows: int, dynamic_ports: bool) -> ParamRowsDescribeResult:
    if not isinstance(raw, Mapping):
        raise _InvalidResultError(
            f"expected a dict with 'columns' and 'rows', got {type(raw).__name__}"
        )
    if "columns" not in raw or "rows" not in raw:
        raise _InvalidResultError("the dict must have 'columns' and 'rows'")
    columns = _validated_columns(raw["columns"])
    raw_rows = raw["rows"]
    if isinstance(raw_rows, str | bytes | Mapping):
        raise _InvalidResultError("'rows' must be a list (or an iterable) of rows")
    try:
        rows_iter: Iterator[Any] = iter(raw_rows)
    except TypeError as e:
        raise _InvalidResultError("'rows' must be a list (or an iterable) of rows") from e
    try:
        # 1 件多く読めば「要求より多い」と分かる。generator なら残りは計算しない
        taken = list(itertools.islice(rows_iter, n_rows + 1))
    finally:
        if isinstance(rows_iter, types.GeneratorType):
            rows_iter.close()
    if len(taken) > n_rows:
        raise _InvalidResultError(
            f"describe returned more than {n_rows} rows for {n_rows} input rows"
        )
    if len(taken) < n_rows:
        raise _InvalidResultError(f"describe returned {len(taken)} rows for {n_rows} input rows")
    rows = tuple(
        _validated_describe_row(row, index, len(columns)) for index, row in enumerate(taken)
    )
    raw_ports = raw.get("ports")
    if raw_ports is not None and (not isinstance(raw_ports, str) or raw_ports not in _PORTS_SIDES):
        raise _InvalidResultError("'ports' must be 'input', 'output' or None")
    ports: PortsSide | None = None
    if raw_ports == "input":
        ports = "input"
    elif raw_ports == "output":
        ports = "output"
    if ports is not None and not dynamic_ports:
        # ポート数が引数に追従しないブロックで配線を付け替えると嘘になる (ADR-0086 §1-D)
        raise _InvalidResultError(
            "ports can be declared only by a block with block_dynamic_ports = True"
        )
    return ParamRowsDescribeResult(columns=columns, rows=rows, ports=ports)


# ---------------------------------------------------------------------------
# form
# ---------------------------------------------------------------------------


def _validated_options(raw: Any, where: str) -> tuple[ParamRowsOption, ...]:
    items = _validated_list(raw, where, min_items=1, max_items=MAX_PARAM_ROWS_OPTIONS)
    options: list[ParamRowsOption] = []
    seen: set[str] = set()
    for i, item in enumerate(items):
        at = f"{where}[{i}]"
        if not isinstance(item, Mapping):
            raise _InvalidResultError(f"{at} must be a dict with 'value' and 'label'")
        value = _validated_value(item.get("value"), f"{at}.value")
        _check_unique(value, seen, f"{at}.value")
        label = _validated_label(item.get("label"), f"{at}.label", value)
        options.append(ParamRowsOption(value=value, label=label))
    return tuple(options)


def _validated_field(raw: Any, where: str) -> ParamRowsField:
    if not isinstance(raw, Mapping):
        raise _InvalidResultError(f"{where} must be a dict with 'key', 'label' and 'kind'")
    key = _validated_id(raw.get("key"), f"{where}.key")
    label = _validated_label(raw.get("label"), f"{where}.label", key)
    kind = raw.get("kind")
    if kind == "text":
        return ParamRowsField(key=key, label=label, kind="text", options=())
    if kind == "pick":
        return ParamRowsField(key=key, label=label, kind="pick", options=())
    if kind == "choice":
        options = _validated_options(raw.get("options"), f"{where}.options")
        return ParamRowsField(key=key, label=label, kind="choice", options=options)
    raise _InvalidResultError(f"{where}.kind must be one of {list(_FIELD_KINDS)}")


def _validated_variant(raw: Any, where: str) -> ParamRowsVariant:
    if not isinstance(raw, Mapping):
        raise _InvalidResultError(f"{where} must be a dict with 'id', 'label' and 'fields'")
    vid = _validated_id(raw.get("id"), f"{where}.id")
    label = _validated_label(raw.get("label"), f"{where}.label", vid)
    raw_fields = raw.get("fields")
    items = (
        ()
        if raw_fields is None
        else _validated_list(
            raw_fields, f"{where}.fields", min_items=0, max_items=MAX_PARAM_ROWS_FIELDS
        )
    )
    fields: list[ParamRowsField] = []
    seen: set[str] = set()
    for i, item in enumerate(items):
        field = _validated_field(item, f"{where}.fields[{i}]")
        _check_unique(field.key, seen, f"{where}.fields[{i}].key")
        fields.append(field)
    return ParamRowsVariant(id=vid, label=label, fields=tuple(fields))


def _default_field_value(field: ParamRowsField) -> str | tuple[str, ...]:
    """フィールドの既定値 (text ``""`` / choice 先頭の選択肢 / pick ``()``)。"""
    if field.kind == "choice":
        return field.options[0].value
    if field.kind == "pick":
        return ()
    return ""


def _validated_field_value(field: ParamRowsField, raw: Any, where: str) -> str | tuple[str, ...]:
    if field.kind == "text":
        return _validated_text(raw, where)
    if field.kind == "choice":
        if not isinstance(raw, str) or raw not in {o.value for o in field.options}:
            raise _InvalidResultError(f"{where} must be one of the options of the field")
        return _plain_str(raw)
    if not isinstance(raw, list | tuple):
        raise _InvalidResultError(f"{where} must be a list of strings")
    if len(raw) > MAX_PARAM_ROWS_PICK_VALUES:
        raise _InvalidResultError(
            f"{where} has {len(raw)} entries; at most {MAX_PARAM_ROWS_PICK_VALUES} are allowed"
        )
    picked: list[str] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        value = _validated_value(item, f"{where}[{i}]")
        _check_unique(value, seen, f"{where}[{i}]")
        picked.append(value)
    return tuple(picked)


def _validated_form(raw: Any) -> ParamRowsFormResult:
    if not isinstance(raw, Mapping):
        raise _InvalidResultError(
            f"expected a dict with 'variants', 'variant' and 'values', got {type(raw).__name__}"
        )
    items = _validated_list(
        raw.get("variants"), "'variants'", min_items=1, max_items=MAX_PARAM_ROWS_VARIANTS
    )
    variants: list[ParamRowsVariant] = []
    seen: set[str] = set()
    for i, item in enumerate(items):
        variant = _validated_variant(item, f"variants[{i}]")
        _check_unique(variant.id, seen, f"variants[{i}].id")
        variants.append(variant)
    selected_id = raw.get("variant")
    selected = next((v for v in variants if v.id == selected_id), None)
    if selected is None:
        raise _InvalidResultError("'variant' must be one of the ids in 'variants'")
    raw_values = raw.get("values")
    if raw_values is None:
        raw_values = {}
    if not isinstance(raw_values, Mapping):
        raise _InvalidResultError("'values' must be a dict of field key -> value")
    # 選ばれた種類のフィールドだけを読む (他の種類のキー・未知のキーは無視する)
    values: dict[str, str | tuple[str, ...]] = {}
    for field in selected.fields:
        if field.key in raw_values:
            values[field.key] = _validated_field_value(
                field, raw_values[field.key], f"values[{field.key!r}]"
            )
        else:
            values[field.key] = _default_field_value(field)
    return ParamRowsFormResult(variants=tuple(variants), variant=selected.id, values=values)


# ---------------------------------------------------------------------------
# compose
# ---------------------------------------------------------------------------


def _validated_compose(raw: Any) -> ParamRowsComposeResult:
    if not isinstance(raw, Mapping):
        raise _InvalidResultError(f"expected a dict with 'row', got {type(raw).__name__}")
    return ParamRowsComposeResult(row=_validated_value(raw.get("row"), "'row'"))


# ---------------------------------------------------------------------------
# 呼び出し (ユーザーコードの境界)
# ---------------------------------------------------------------------------


def _copied_arguments(action: str, action_kw: Mapping[str, Any]) -> dict[str, Any]:
    """ユーザーコードに渡す action ごとの引数 (呼び出し側に影響しないようコピーする)。"""
    kw = dict(action_kw)
    if "rows" in kw:
        kw["rows"] = list(kw["rows"])
    if action == "compose":
        kw["values"] = {
            k: list(v) if isinstance(v, list | tuple) else v for k, v in kw["values"].items()
        }
    if action == "search":
        kw["query"] = kw["query"].strip()
    return kw


def _validator(cls: type, action: str, kw: Mapping[str, Any]) -> Callable[[Any], ParamRowsResult]:
    if action == "describe":
        n_rows = len(kw["rows"])
        dynamic = has_dynamic_ports(cls)
        return lambda raw: _validated_describe(raw, n_rows, dynamic)
    if action == "form":
        return _validated_form
    if action == "compose":
        return _validated_compose
    limit = int(kw["limit"])
    return lambda raw: _validated_result(raw, limit)


def _result_size(result: ParamRowsResult) -> int:
    if isinstance(result, ParamRowsFormResult):
        return len(result.variants)
    if isinstance(result, ParamRowsComposeResult):
        return 1
    return len(result.rows)


def call_param_rows(
    cls: type,
    method_name: str,
    *,
    action: str,
    param: str,
    params: Mapping[str, Any],
    **action_kw: Any,
) -> ParamRowsResult:
    """ユーザーブロックの行エディタを呼び、検証・変換済みの結果を返す (ADR-0086 §1-B / §2)。

    メソッドはすべてキーワード引数で呼ぶ: ``fn(action=, param=, params=, <action ごとの引数>)``。
    ``params`` はクラスが宣言した引数だけに絞り、編集中の引数 ``param`` 自身は除く。

    Args:
        cls: 管理型表にあるユーザーブロックのクラス。
        method_name: ``find_param_rows_method`` が返した classmethod / staticmethod の名前。
        action: ``"describe"`` / ``"form"`` / ``"compose"`` / ``"search"``。
        param: 編集中の引数名。
        params: 他の引数の現在の値 (JSON 値)。
        **action_kw: action ごとの引数 (describe: ``rows`` / form: ``row`` /
            compose: ``variant`` ``values`` ``rows`` ``index`` / search: ``field`` ``query``
            ``limit``)。

    Returns:
        action ごとの結果 (search は ``ParamSearchResult``)。

    Raises:
        ParamSearchFunctionError: メソッドの例外 (メッセージは ``"<型名>: <メッセージ>"``)。
        BlockSpecError: 未知の action、ブロックがその action に対応していない
            (``NotImplemented``)、または戻り値の形が不正 (位置付きのメッセージ)。
        TypeError: ``action_kw`` が action の引数と合わない (呼び出し側の誤り)。

    メッセージの UTF-8 にできない文字 (孤立サロゲート) は ``?`` に置き換える。
    """
    if action not in PARAM_ROWS_ACTIONS:
        raise BlockSpecError(
            f"unknown action {action!r}; it must be one of {list(PARAM_ROWS_ACTIONS)}"
        )
    expected = _ACTION_ARGUMENTS[action]
    if set(action_kw) != expected:
        raise TypeError(
            f"action {action!r} takes the arguments {sorted(expected)}, got {sorted(action_kw)}"
        )
    kw = _copied_arguments(action, action_kw)
    validate = _validator(cls, action, kw)
    started = time.perf_counter()
    result: ParamRowsResult | None = None
    try:
        declared = {p.name for p in read_params(cls)}
        call_params = {k: v for k, v in params.items() if k in declared and k != param}
        fn = getattr(cls, method_name)
        raw = fn(action=action, param=param, params=call_params, **kw)
        if raw is not NotImplemented:
            result = validate(raw)
    except _InvalidResultError as e:
        message = _utf8_safe(
            _truncate(
                f"the row editor returned an invalid result for action {action!r}: {_safe_text(e)}"
            )
        )
        _logger.info("param rows %s.%s: %s", cls.__name__, method_name, message)
        raise BlockSpecError(message) from e
    except BaseException as e:  # noqa: BLE001 - ユーザーコードの境界 (読み込み時と同じ扱い)
        _reraise_if_interrupt(e)
        if isinstance(e, BlockSpecError):
            # ブロックが意図して出す「入力が正しくない」(プレビューで入力のたびに起きうる)。
            # トレースバックは要らないので 1 行だけ残す
            _logger.info(
                "param rows %s.%s (action %r, param %r): %r",
                cls.__name__, method_name, action, param, _safe_text(e),
            )  # fmt: skip
        else:
            _logger.warning(
                "param rows %s.%s (action %r, param %r) raised an exception",
                cls.__name__, method_name, action, param, exc_info=True,
            )  # fmt: skip
        message = _safe_text(e) if isinstance(e, BlockSpecError) else _exception_text(e)
        raise ParamSearchFunctionError(_utf8_safe(_truncate(message))) from e
    if result is None:
        # NotImplemented = その action に対応していない。flode 自身の文言 (非 loopback でもそのまま返す、ADR-0086 §1-C)
        raise BlockSpecError(
            _utf8_safe(
                _truncate(f"the block does not support action {action!r} for parameter {param!r}")
            )
        )
    _logger.debug(
        "param rows %s.%s: action %r, param %r, %d item(s), %.3f s",
        cls.__name__, method_name, action, param, _result_size(result),
        time.perf_counter() - started,
    )  # fmt: skip
    return result
