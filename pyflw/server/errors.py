"""ドメイン例外 (``PyflwError`` 系) を HTTP エラーへ変換するハンドラ (ADR-0011 §(5))。"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..exceptions import (
    AlgebraicLoopError,
    BlockSpecError,
    ModelLoadError,
    ModelSerializationError,
    PyflwError,
    SchedulingError,
    SchemaVersionError,
    SolverError,
    UnknownBlockIdError,
    UnknownBlockTypeError,
)

_logger = logging.getLogger("pyflw.server")


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


def _resolve_status(exc: PyflwError) -> int:
    """``exc`` の MRO を走査して最も具体的な ``_STATUS_MAP`` エントリを返す。

    継承関係を考慮した完全一致優先のロジックなので、``_STATUS_MAP`` の dict 挿入順
    に依存しない (例: ``SchemaVersionError(ModelLoadError)`` も 400 に解決される)。
    """
    for cls in type(exc).__mro__:
        if cls in _STATUS_MAP:
            return _STATUS_MAP[cls]
    return 500


def register_error_handlers(app: FastAPI) -> None:
    """``PyflwError`` 系を JSON レスポンスに変換するハンドラを app に登録する。"""

    @app.exception_handler(PyflwError)
    async def _pyflw_error_handler(_request: Request, exc: PyflwError) -> JSONResponse:
        status_code = _resolve_status(exc)
        trace_id = str(uuid.uuid4())
        _logger.error(
            "PyflwError [%s] (trace_id=%s): %s",
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
