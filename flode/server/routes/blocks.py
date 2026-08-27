"""Block class registry エンドポイント (ADR-0019 §(1))。

ブロックパレット UI が利用する。サーバ起動時に build される
``app.state.block_registry`` (= ``list[BlockMetadata]``) を返却 / 検索する。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from ...exceptions import BlockSpecError, UnknownBlockTypeError
from ..registry import (
    BlockMetadata,
    introspect_python_source,
    metadata_to_dict,
    resolve_port_shapes,
)

router = APIRouter(prefix="/blocks", tags=["blocks"])

# SPEC-0023 introspect の入力上限 (security-reviewer: 無認証の CPU 消費点になるため)。
# 1 モデルに 64 個超の PythonFunction、256 KiB 超のソースは実用上あり得ない。
MAX_INTROSPECT_ITEMS = 64
MAX_INTROSPECT_CODE_CHARS = 256 * 1024


def _registry(request: Request) -> list[BlockMetadata]:
    """app.state から registry を取り出す型安全 helper。"""
    reg = getattr(request.app.state, "block_registry", None)
    if reg is None:  # lifespan 起動前の test fixture 等
        from ..registry import build_block_registry

        reg = build_block_registry()
        request.app.state.block_registry = reg
    # ``-O`` モード対策で assert を使わない実行時 check (ADR-0019 code-reviewer MUST)。
    if not isinstance(reg, list):
        raise HTTPException(status_code=500, detail="block_registry state is corrupted")
    return reg


@router.get("")
def list_blocks(request: Request) -> dict[str, Any]:
    """全 Block class metadata を返す (パレット表示用、ADR-0019、ADR-0028)。

    完全な docstring はサイズが大きくなるため省略 (``docstring_summary`` のみ)。
    詳細は ``GET /api/v1/blocks/{type_path}`` で個別取得する。

    ADR-0028 (v0.11.0): ``schema_version = "blocks.v2"`` に bump、
    ``supported_locales`` フィールドを追加。各 block metadata に
    ``display_name_i18n`` / ``docstring_summary_i18n`` を同梱する (= 旧 frontend が
    読まない optional フィールドなので後方互換)。
    """
    # 遅延 import で循環回避
    from ..registry_translations import SUPPORTED_LOCALES

    return {
        "blocks": [metadata_to_dict(m, include_full_docstring=False) for m in _registry(request)],
        "schema_version": "blocks.v2",
        "supported_locales": list(SUPPORTED_LOCALES),
    }


@router.get("/resolve-port-shapes")
def resolve_port_shapes_get_method_not_allowed() -> None:
    """``POST /api/v1/blocks/resolve-port-shapes`` の GET 方向の Empty stub。

    GET で 405 にすると path conflict 検出が早く、開発者が POST を使い忘れた際の
    エラーが明確になる。FastAPI 既定では ``GET /api/v1/blocks/resolve-port-shapes`` が
    ``GET /api/v1/blocks/{type_path:path}`` にマッチしてしまうため、ここで明示的に
    優先順位の高い 405 ハンドラを置く。
    """
    raise HTTPException(
        status_code=405,
        detail=(
            "Use POST /api/v1/blocks/resolve-port-shapes with body "
            "{type_path, params} to resolve port shapes for a parametrized block."
        ),
    )


@router.post("/resolve-port-shapes")
async def resolve_port_shapes_endpoint(request: Request) -> dict[str, Any]:
    """指定 ``type_path`` + ``params`` で構築したインスタンスの port shapes を返す。

    Body schema (ADR-0019 §1.4):
        ``{"type_path": "flode.blocks.Sum", "params": {"signs": "+++"}}``

    Returns:
        ``{"n_inputs", "n_outputs", "port_shapes_in", "port_shapes_out"}``。

    Raises:
        HTTPException: type_path 解決失敗 → 404、``__init__`` 失敗 → 400。
    """
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")
    type_path = body.get("type_path")
    params = body.get("params", {})
    if not isinstance(type_path, str) or not type_path:
        raise HTTPException(status_code=400, detail="`type_path` (string) is required in body")
    if not isinstance(params, dict):
        raise HTTPException(status_code=400, detail="`params` must be a JSON object")
    try:
        resolved = resolve_port_shapes(type_path, params)
    except UnknownBlockTypeError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except BlockSpecError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "n_inputs": resolved.n_inputs,
        "n_outputs": resolved.n_outputs,
        "port_shapes_in": resolved.port_shapes_in,
        "port_shapes_out": resolved.port_shapes_out,
    }


@router.get("/python-function/introspect")
def introspect_python_function_get_method_not_allowed() -> None:
    """``POST /api/v1/blocks/python-function/introspect`` の GET 方向の 405 stub。

    ``resolve-port-shapes`` と同じ理由 (catch-all ``GET /{type_path:path}`` への
    誤マッチ防止)。
    """
    raise HTTPException(
        status_code=405,
        detail=(
            "Use POST /api/v1/blocks/python-function/introspect with body "
            '{"items": [{"key": ..., "code": ...}]} to analyse PythonFunction sources.'
        ),
    )


@router.post("/python-function/introspect")
async def introspect_python_function(request: Request) -> dict[str, Any]:
    """``PythonFunction`` ソースを静的解析して構造 + パラメータ宣言を返す (SPEC-0023 / ADR-0073 §論点 1)。

    Body: ``{"items": [{"key": "<client key>", "code": "<python source>"}, ...]}``。
    ``key`` はクライアントが突合に使う任意文字列 (index ではなく key で返す)。

    Returns:
        ``{"results": {key: {"resolved": true, ...} | {"resolved": false, "error": {...}}}}``。
        個々の解析失敗は 200 の中で表現する (1 件の失敗で他を巻き添えにしない)。
        body 自体が不正なときだけ 400。

    Note:
        **この endpoint はユーザーコードを exec しない** (RCE の観点では静的解析のみ)。
        DoS 耐性は別で、``MAX_INTROSPECT_ITEMS`` / ``MAX_INTROSPECT_CODE_CHARS`` で
        入力量を制限し、解析は threadpool で行って event loop を塞がない。
    """
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")
    items = body.get("items")
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="`items` (array) is required in body")
    if len(items) > MAX_INTROSPECT_ITEMS:
        raise HTTPException(
            status_code=400, detail=f"`items` must have at most {MAX_INTROSPECT_ITEMS} entries"
        )
    validated: list[tuple[str, str]] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail=f"items[{i}] must be a JSON object")
        key = item.get("key")
        code = item.get("code")
        if not isinstance(key, str) or not key:
            raise HTTPException(status_code=400, detail=f"items[{i}].key (string) is required")
        if not isinstance(code, str):
            raise HTTPException(status_code=400, detail=f"items[{i}].code (string) is required")
        if len(code) > MAX_INTROSPECT_CODE_CHARS:
            raise HTTPException(
                status_code=400,
                detail=f"items[{i}].code exceeds {MAX_INTROSPECT_CODE_CHARS} characters",
            )
        validated.append((key, code))

    def _analyse_all() -> dict[str, Any]:
        return {key: introspect_python_source(code, key=key) for key, code in validated}

    results = await run_in_threadpool(_analyse_all)
    return {"results": results}


@router.get("/{type_path:path}")
def get_block_metadata(request: Request, type_path: str) -> dict[str, Any]:
    """1 つの Block class の完全なメタデータを返す (full docstring 含む)。"""
    for m in _registry(request):
        if m.type_path == type_path:
            return metadata_to_dict(m, include_full_docstring=True)
    raise HTTPException(
        status_code=404,
        detail=f"Block type {type_path!r} not found in registry",
    )
