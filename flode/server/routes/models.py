"""モデル静的解析ルート (SPEC-0027: SM-D Stage 0、v0.54.0 新設)。

``POST /api/v1/models/resolve-dtypes`` — 影の型解決 (shadow dtype propagation)。

セキュリティ上の要点 (security-reviewer 向け):

- **静的解析のみでユーザーコード (PythonFunction) を一切実行しない**。
  エンジン (``flode.core.dtypes``) は PythonFunction を含むモデルでは
  ``_build()`` を呼ばない static mode に縮退する (二経路設計)。
  そのため ``/simulations`` の python_ack (409) ゲートは不要
- モデルの構築・path 検証は既存 ``_resolve_simulator`` を再利用
  (``resolve_workspace_path`` による path traversal 防御込み、400/403/404)
- 型解決自体の失敗は **HTTP 200 + diagnostics** (Stage 0 は「解析できなかった」
  ことも測定対象のため、SPEC-0027 Q4)

Note: v0.21.0 で削除された legacy models router とは無関係の新設。
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .simulations import _resolve_simulator, _start_validation_detail

router = APIRouter(prefix="/models", tags=["models"])


@router.get("/resolve-dtypes")
async def resolve_dtypes_get_stub() -> dict[str, Any]:
    """GET は不可 (blocks router の 405 stub と同じ流儀)。"""
    raise HTTPException(
        status_code=405,
        detail="Use POST /api/v1/models/resolve-dtypes with a JSON body "
        "({'model': {...}} or {'model_path': '...'}).",
    )


@router.post("/resolve-dtypes")
async def resolve_dtypes_endpoint(request: Request) -> dict[str, Any]:
    """影の型解決を行い ``dtypes.v1`` payload を返す (SPEC-0027 §5.2)。

    Request body は ``model_path`` または ``model`` のうち正確に 1 つを含む
    JSON object (``POST /simulations`` と同じ 2 形式)。実行は一切行わず、
    シミュレーション結果にも保存ファイルにも影響しない (Stage 0 = 表示・測定のみ)。

    モデル構築と型解決は threadpool で行い、大きいモデルでも event loop
    (= 実行中シミュレーションの WS 配信) を止めない (security-reviewer SHOULD-2)。
    """
    try:
        payload = await request.json()
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=_start_validation_detail("Body must be valid JSON"),
        ) from e
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail=_start_validation_detail("Body must be a JSON object"),
        )

    def _resolve() -> dict[str, Any]:
        simulator, _display_id = _resolve_simulator(request, payload)
        return simulator.resolve_dtypes().to_payload()

    return await run_in_threadpool(_resolve)
