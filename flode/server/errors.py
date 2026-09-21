"""ドメイン例外 (``FlodeError`` 系) を HTTP エラーへ変換するハンドラ (ADR-0011 §(5))。

ADR-0056 追加: シミュレーション失敗時の構造化エラー payload (``FailurePayload``)
を組み立てる ``classify_exception`` / ``build_failure_payload`` も本モジュールに集約
(= サーバ専用ロジックで core 不汚染、ADR-0001 §横断方針)。
"""

from __future__ import annotations

import dataclasses
import logging
import traceback
import uuid
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..exceptions import (
    AlgebraicLoopError,
    BlockSpecError,
    FlodeError,
    ModelLoadError,
    ModelSerializationError,
    PythonBlocksDisabledError,
    PythonFunctionEvalError,
    SchedulingError,
    SchemaVersionError,
    SignalShapeError,
    SolverError,
    UnknownBlockIdError,
    UnknownBlockTypeError,
)

if TYPE_CHECKING:
    from ..core.simulator import Simulator

_logger = logging.getLogger("flode.server")


_STATUS_MAP: dict[type[Exception], int] = {
    BlockSpecError: 400,
    UnknownBlockTypeError: 400,
    ModelLoadError: 400,
    SchemaVersionError: 400,
    UnknownBlockIdError: 404,
    AlgebraicLoopError: 422,
    ModelSerializationError: 500,
    SchedulingError: 500,
    SolverError: 500,
}


def _resolve_status(exc: FlodeError) -> int:
    """``exc`` の MRO を走査して最も具体的な ``_STATUS_MAP`` エントリを返す。

    継承関係を考慮した完全一致優先のロジックなので、``_STATUS_MAP`` の dict 挿入順
    に依存しない (例: ``SchemaVersionError(ModelLoadError)`` も 400 に解決される)。
    """
    for cls in type(exc).__mro__:
        if cls in _STATUS_MAP:
            return _STATUS_MAP[cls]
    return 500


# ============================================================================
# ADR-0056: 構造化エラー protocol (シミュレーション失敗時 UI 用)
# ============================================================================

# Phase 1 カテゴリ taxonomy (ADR-0056 §C-2 / SPEC-0005 §F5)。
# 新カテゴリ追加時はここに 1 行 + locale.json に template 追加で済む設計。
_CATEGORY_ALGEBRAIC_LOOP = "algebraic_loop"
_CATEGORY_SHAPE_MISMATCH = "shape_mismatch"
_CATEGORY_DIVIDE_BY_ZERO = "divide_by_zero"
_CATEGORY_SOLVER_FAILURE = "solver_failure"
_CATEGORY_START_VALIDATION = "start_validation"
_CATEGORY_UNKNOWN = "unknown"
# SPEC-0023 / ADR-0073 §論点 6: PythonFunction 専用カテゴリ 3 件。
#   - python_function_error: ユーザーコードの実行時例外 (行番号 + 該当行付き)
#   - python_function_disabled: hard gate (非 loopback bind でフラグ無し) による拒否
#   - python_function_unconfirmed: start API の soft gate (409、route が生成)
CATEGORY_PYTHON_FUNCTION_ERROR = "python_function_error"
CATEGORY_PYTHON_FUNCTION_DISABLED = "python_function_disabled"
CATEGORY_PYTHON_FUNCTION_UNCONFIRMED = "python_function_unconfirmed"

# Phase 1 で fall through する例外 (= unknown 扱い、Phase 2 で新カテゴリ追加候補):
#   - ``TypeError`` / 素の ``IndexError`` (= simulator.py の add 引数 validation 等。
#     ``connect`` のポート範囲外は 2026-09-14 に ``PortIndexError`` (= ``BlockSpecError``
#     継承) 化済みで、``start_validation`` / 400 に分類される)
#   - ``RuntimeWarning`` (= numpy overflow、Phase 2 で overflow カテゴリ)
#   - ``Fcn`` (式ブロック) の任意 Python 例外 (Phase 2)。``PythonFunction`` は
#     専用カテゴリ ``python_function_error`` で扱う (ADR-0073 §論点 6)


@dataclasses.dataclass(frozen=True)
class ErrorClassification:
    """例外 → カテゴリ + i18n テンプレートキーへの分類結果 (ADR-0056 §B-1)。"""

    category: str
    template_key: str


# 例外クラス → 分類のマッピング。``classify_exception`` が MRO で解決する。
_CATEGORY_BY_EXC: tuple[tuple[type[BaseException], ErrorClassification], ...] = (
    (AlgebraicLoopError, ErrorClassification(_CATEGORY_ALGEBRAIC_LOOP, "error.algebraic_loop")),
    # ADR-0073 §論点 6: tuple 順の isinstance 走査なので、``BlockSpecError`` の
    # サブクラスである ``PythonBlocksDisabledError`` は BlockSpecError より前に置く。
    (
        PythonBlocksDisabledError,
        ErrorClassification(CATEGORY_PYTHON_FUNCTION_DISABLED, "error.python_function_disabled"),
    ),
    (
        PythonFunctionEvalError,
        ErrorClassification(CATEGORY_PYTHON_FUNCTION_ERROR, "error.python_function_error"),
    ),
    (ZeroDivisionError, ErrorClassification(_CATEGORY_DIVIDE_BY_ZERO, "error.divide_by_zero")),
    (SolverError, ErrorClassification(_CATEGORY_SOLVER_FAILURE, "error.solver_failure")),
    # ADR-0079 §(8): build 時の信号 shape 診断 (BlockSpecError のサブクラス) は
    # start_validation に埋もれさせず shape_mismatch カテゴリに振る。
    (SignalShapeError, ErrorClassification(_CATEGORY_SHAPE_MISMATCH, "error.shape_mismatch")),
    (BlockSpecError, ErrorClassification(_CATEGORY_START_VALIDATION, "error.start_validation")),
    (ModelLoadError, ErrorClassification(_CATEGORY_START_VALIDATION, "error.start_validation")),
    (
        UnknownBlockIdError,
        ErrorClassification(_CATEGORY_START_VALIDATION, "error.start_validation"),
    ),
    (
        UnknownBlockTypeError,
        ErrorClassification(_CATEGORY_START_VALIDATION, "error.start_validation"),
    ),
    (SchemaVersionError, ErrorClassification(_CATEGORY_START_VALIDATION, "error.start_validation")),
    # code-reviewer SHOULD-1: SchedulingError / ModelSerializationError は「モデル
    # 検証」ではなく内部構成エラー / 保存失敗。Phase 1 では専用カテゴリが無いため
    # ``unknown`` に落として raw_message で実情を伝える (= 「モデル検証エラー」と
    # 誤読される問題を回避)。Phase 2 で "start_configuration" / "internal_error"
    # 等の追加カテゴリ化を検討。
    (SchedulingError, ErrorClassification(_CATEGORY_UNKNOWN, "error.unknown")),
    (ModelSerializationError, ErrorClassification(_CATEGORY_UNKNOWN, "error.unknown")),
)


def classify_exception(exc: BaseException) -> ErrorClassification:
    """例外をカテゴリ + i18n テンプレートキーに分類する (ADR-0056 §C)。

    分類順:
      1. ``_CATEGORY_BY_EXC`` の MRO 完全一致 (= AlgebraicLoopError, SolverError 等)
      2. ``ValueError`` で message に ``"broadcast"`` / ``"shape"`` を含む
         → ``shape_mismatch`` (numpy 2.x の wording を狙い撃ち、ADR-0056 §Risks U5)
      3. 上記いずれにも該当しない → ``unknown``
    """
    for exc_type, classification in _CATEGORY_BY_EXC:
        if isinstance(exc, exc_type):
            return classification
    if isinstance(exc, ValueError):
        msg = str(exc).lower()
        if "broadcast" in msg or "shape" in msg:
            return ErrorClassification(_CATEGORY_SHAPE_MISMATCH, "error.shape_mismatch")
    return ErrorClassification(_CATEGORY_UNKNOWN, "error.unknown")


_MAX_TRACEBACK_LINES = 50
"""traceback を frontend に送る前に truncate する行数 (ADR-0056 §B-1 巨大 traceback 対応)。

サーバログには ``_logger.exception`` で全文が残るため、UI 側は要点表示のみで十分。
"""


def _truncate_traceback(tb_str: str, max_lines: int = _MAX_TRACEBACK_LINES) -> str:
    """traceback 文字列を ``max_lines`` 以下に truncate する。

    末尾を残す方が「最終的にどこで raise したか」が見える。
    """
    lines = tb_str.splitlines()
    if len(lines) <= max_lines:
        return tb_str
    truncated = lines[-max_lines:]
    omitted = len(lines) - max_lines
    return f"... ({omitted} earlier lines truncated)\n" + "\n".join(truncated)


def _block_label(block: Any) -> str | None:
    """``Block.name`` (ユーザー命名) があればそれ、無ければ ``id``、両方無ければ ``None``。"""
    name = getattr(block, "name", None)
    if isinstance(name, str) and name:
        return name
    block_id = getattr(block, "id", None)
    if isinstance(block_id, str) and block_id:
        return block_id
    return None


def _block_type_path(block: Any) -> str | None:
    """``"flode.blocks.mathops.Divide"`` 形式の type path。"""
    cls = type(block)
    module = cls.__module__
    return f"{module}.{cls.__name__}" if module else cls.__name__


def _shape_mismatch_args(exc: BaseException) -> dict[str, Any]:
    """``shape_mismatch`` カテゴリの ``template_args`` を抽出する。

    - ``SignalShapeError`` (ADR-0079 §(8)、build 時の信号面診断) は構造化属性から
      ``shapes`` (``expected vs actual``) / ``port`` / ``code`` / ``diagnostics``
      (error 級全件の ``{code, message, block_id, direction, port_index}``) を埋める
    - それ以外 (numpy 2.x の ``ValueError``) は message 中の ``(a,) (b,)`` 形式の
      shape タプルを正規表現で拾う best-effort。失敗してもエラー全体は壊さない
    """
    import re

    if isinstance(exc, SignalShapeError):
        args: dict[str, Any] = {}
        expected = exc.expected_shape
        actual = exc.actual_shape
        if expected is not None or actual is not None:
            args["shapes"] = f"expected {expected} vs actual {actual}"
        if exc.port is not None:
            args["port"] = exc.port
        if exc.block_id is not None:
            args.setdefault("block_label", exc.block_id)
        diags = [
            {
                "code": getattr(d, "code", None),
                "message": getattr(d, "message", None),
                "block_id": getattr(d, "block_id", None),
                "direction": getattr(d, "direction", None),
                "port_index": getattr(d, "port_index", None),
            }
            for d in exc.diagnostics
        ]
        if diags:
            args["code"] = diags[0]["code"]
            args["diagnostics"] = diags
        return args

    msg = str(exc)
    shapes = re.findall(r"\([\d,\s]*\)", msg)
    if shapes:
        return {"shapes": " vs ".join(shapes[:2])}
    return {}


def _solver_failure_args(exc: BaseException) -> dict[str, Any]:
    """``solver_failure`` の ``template_args.reason`` を抽出する。

    ``SolverError`` の message は ``"Solver failed at t=[t, t_next]: <reason>"`` 形式
    (simulator.py:1082)。コロン以降を reason とする。
    """
    msg = str(exc)
    if ":" in msg:
        reason = msg.rsplit(":", 1)[1].strip()
        if reason:
            return {"reason": reason}
    return {}


def _template_args_for(
    classification: ErrorClassification,
    exc: BaseException,
    *,
    block: Any | None,
    t: float | None,
) -> dict[str, Any]:
    """カテゴリに応じた ``template_args`` を組み立てる。

    全カテゴリ共通: ``block_label`` (in scope なら) と ``t`` (有値なら)。
    カテゴリ固有: shape_mismatch の ``shapes``、solver_failure の ``reason`` 等。
    """
    args: dict[str, Any] = {}
    label = _block_label(block) if block is not None else None
    if label is not None:
        args["block_label"] = label
    if t is not None:
        args["t"] = t

    if classification.category == _CATEGORY_ALGEBRAIC_LOOP and isinstance(exc, AlgebraicLoopError):
        args["block_labels"] = list(exc.block_ids)
    elif classification.category == _CATEGORY_SHAPE_MISMATCH:
        args.update(_shape_mismatch_args(exc))
        # ``error.shape_mismatch`` は {{block_label}} を参照するため、scope 外
        # (= block None) のとき literal 表示を防ぐフォールバックを入れる。
        args.setdefault("block_label", "?")
        args.setdefault("shapes", "?")
    elif classification.category == _CATEGORY_SOLVER_FAILURE:
        args.update(_solver_failure_args(exc))
        args.setdefault("reason", str(exc))
    elif classification.category == _CATEGORY_DIVIDE_BY_ZERO:
        args.setdefault("block_label", "?")
    elif classification.category == _CATEGORY_START_VALIDATION:
        # ``error.start_validation`` テンプレートが参照する {{message}} を必ず埋める
        # (= 例外由来経路で抜けると UI に "{{message}}" が literal 表示される)。
        args["message"] = str(exc)
    elif classification.category == CATEGORY_PYTHON_FUNCTION_ERROR:
        # ADR-0073 §論点 6: ユーザーコードの行番号 + 該当行テキスト。
        args["message"] = str(exc)
        args.setdefault("block_label", getattr(exc, "block_id", None) or "?")
        lineno = getattr(exc, "lineno", None)
        args["lineno"] = lineno if lineno is not None else "?"
        args["source_line"] = (getattr(exc, "source_line", None) or "").strip()
    elif classification.category == CATEGORY_PYTHON_FUNCTION_DISABLED:
        args["message"] = str(exc)
        args.setdefault("block_label", getattr(exc, "block_id", None) or "?")
    elif classification.category == _CATEGORY_UNKNOWN:
        args["raw_message"] = f"{type(exc).__name__}: {exc}"

    return args


def build_failure_payload(
    exc: BaseException,
    *,
    simulator: Simulator | None = None,
    t: float | None = None,
    duration_sec: float | None = None,
    include_traceback: bool = True,
) -> dict[str, Any]:
    """例外を WS ``failed`` メッセージ / REST start エラーの構造化 payload に変換する。

    ADR-0056 §B-1 の field schema に準拠。``type`` / ``duration_sec`` は呼び出し側
    (runtime / route) で merge する責務。

    Args:
        exc: 失敗の原因例外。
        simulator: 関連 Simulator (``_current_block`` から関与ブロック情報を引く)。
            ``None`` のときは ``block_*`` が全 None / 空。
        t: 失敗発生時のシミュレーション時刻 (秒)。runtime 層が ``rec.state.current_t``
            を渡す。起動失敗時は ``None``。
        duration_sec: 起動から失敗までの所要時間 (= ``failed`` のみ)。REST start
            エラー時は ``None`` (route 層で field 自体を含めない)。
        include_traceback: ``False`` のとき ``raw_traceback`` を ``None`` にする
            (= test 用、本番では常に ``True``)。

    Returns:
        ``failed`` / ``start error detail`` の field を満たす dict。``type`` /
        ``duration_sec`` を含まないので、呼び出し側で merge する。
    """
    classification = classify_exception(exc)

    block: Any | None = None
    if simulator is not None:
        block = getattr(simulator, "_current_block", None)

    block_id: str | None = None
    block_type: str | None = None
    block_label: str | None = None
    block_ids: list[str] = []

    if block is not None:
        block_id_attr = getattr(block, "id", None)
        if isinstance(block_id_attr, str):
            block_id = block_id_attr
            block_ids = [block_id_attr]
        block_type = _block_type_path(block)
        block_label = _block_label(block)

    # AlgebraicLoopError は run() 前 (= scheduling) で raise されるため ``_current_block``
    # は None、ただし ``block_ids`` 属性に複数 ID 持っている。
    if isinstance(exc, AlgebraicLoopError) and exc.block_ids:
        block_ids = list(exc.block_ids)
        if not block_id and exc.block_ids:
            block_id = exc.block_ids[0]
        if not block_label:
            block_label = exc.block_ids[0]

    # ADR-0056: ブロック単位の raise 箇所 (= From/Goto 解決、scheduling 前の
    # validation) は ``_current_block`` が未設定でも例外に ``block_id`` を載せている。
    # それを拾って UI のジャンプ対象にする (label は id にフォールバック)。
    exc_block_id = getattr(exc, "block_id", None)
    if not block_id and isinstance(exc_block_id, str):
        block_id = exc_block_id
        if not block_ids:
            block_ids = [exc_block_id]
        if not block_label:
            block_label = exc_block_id

    template_args = _template_args_for(
        classification,
        exc,
        block=block,
        t=t,
    )

    raw_message = f"{type(exc).__name__}: {exc}"
    raw_traceback: str | None = None
    if include_traceback:
        # ADR-0073 §論点 6: PythonFunction のユーザー例外は、flode 内部フレームを
        # 除いた ``user_traceback`` を優先する (完全な traceback はサーバログに残す)。
        user_tb = getattr(exc, "user_traceback", None)
        if isinstance(user_tb, str) and user_tb:
            tb_str = user_tb
        else:
            tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        raw_traceback = _truncate_traceback(tb_str)

    payload: dict[str, Any] = {
        "category": classification.category,
        "template_key": classification.template_key,
        "template_args": template_args,
        "block_id": block_id,
        "block_ids": block_ids,
        "block_type": block_type,
        "block_label": block_label,
        "t": t,
        "raw_message": raw_message,
        "raw_traceback": raw_traceback,
    }
    if duration_sec is not None:
        payload["duration_sec"] = duration_sec
    return payload


def register_error_handlers(app: FastAPI) -> None:
    """``FlodeError`` 系を JSON レスポンスに変換するハンドラを app に登録する。"""

    @app.exception_handler(FlodeError)
    async def _flode_error_handler(_request: Request, exc: FlodeError) -> JSONResponse:
        status_code = _resolve_status(exc)
        trace_id = str(uuid.uuid4())
        _logger.error(
            "FlodeError [%s] (trace_id=%s): %s",
            type(exc).__name__,
            trace_id,
            exc,
        )
        body: dict[str, Any] = {
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
                "trace_id": trace_id,
            }
        }
        return JSONResponse(status_code=status_code, content=body)
