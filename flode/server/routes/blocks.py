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
    rewrite_python_source,
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


@router.get("/python-function/rewrite")
def rewrite_python_function_get_method_not_allowed() -> None:
    """``POST /api/v1/blocks/python-function/rewrite`` の GET 方向の 405 stub。"""
    raise HTTPException(
        status_code=405,
        detail=(
            "Use POST /api/v1/blocks/python-function/rewrite with body "
            '{"code": ..., "edits": {"inputs"?, "outputs"?, "input_names"?, '
            '"output_names"?, "params"?}} to rewrite a PythonFunction source.'
        ),
    )


def _validated_rewrite_count(edits: dict[str, Any], key: str) -> None:
    from ...blocks.pythonfunc_rewrite import MAX_PYTHON_FUNCTION_PORTS

    v = edits.get(key)
    if v is None:
        return
    if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= MAX_PYTHON_FUNCTION_PORTS:
        raise HTTPException(
            status_code=400,
            detail=f"edits.{key} must be an integer in 1..{MAX_PYTHON_FUNCTION_PORTS}",
        )


def _validated_rewrite_names(edits: dict[str, Any], key: str) -> None:
    from ...blocks.pythonfunc_rewrite import MAX_PYTHON_FUNCTION_PORTS

    v = edits.get(key)
    if v is None:
        return
    if not isinstance(v, list) or not all(isinstance(n, str) for n in v):
        raise HTTPException(status_code=400, detail=f"edits.{key} must be a list of strings")
    # security-reviewer SHOULD-2: 要素数もポート上限で揃える (32 超は常に長さ不一致)
    if len(v) > MAX_PYTHON_FUNCTION_PORTS:
        raise HTTPException(
            status_code=400,
            detail=f"edits.{key} must have at most {MAX_PYTHON_FUNCTION_PORTS} elements",
        )
    for i, n in enumerate(v):
        if len(n) > 32:
            raise HTTPException(status_code=400, detail=f"edits.{key}[{i}] exceeds 32 code points")


def _validated_rewrite_params(edits: dict[str, Any]) -> list[Any] | None:
    """``edits.params`` (SPEC-0025 §機能要件 5) を検証して ``ParamEdit`` 列に変換する。

    ここで弾くのは **body だけで判定できる静的規則** (P1〜P4 / 型語彙 / default の
    JSON 型・サイズ / 1 request 1 op / rename × ポート編集の併用) = クライアントの
    バグなので 400。ソースの中身に依存する P5〜P9 / U1〜U8 は engine 側が
    ``applied:false`` で返す。wire の ``from`` / ``to`` は Python の予約語のため、
    ここで ``old`` / ``new`` に変換する (ADR-0075 §論点 5: 変換は REST 層の 1 箇所だけ)。
    """
    import keyword
    import math
    import unicodedata

    from ...blocks.pythonfunc_rewrite import (
        FORBIDDEN_DEFAULT_CATEGORIES,
        MAX_PARAM_NAME_LENGTH,
        MAX_PARAM_STR_DEFAULT_LENGTH,
        PARAM_NAME_RE,
        PARAM_TYPE_NAMES,
        AddParam,
        RemoveParam,
        RenameParam,
    )

    v = edits.get("params")
    if v is None:
        return None
    if not isinstance(v, list) or len(v) != 1:
        raise HTTPException(
            status_code=400,
            detail="edits.params must be a list with exactly one edit (1 request = 1 op)",
        )
    raw = v[0]
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="edits.params[0] must be an object")

    def _checked_name(field: str) -> str:
        value = raw.get(field)
        if (
            not isinstance(value, str)
            or not PARAM_NAME_RE.match(value)
            or keyword.iskeyword(value)
            or len(value) > MAX_PARAM_NAME_LENGTH
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"edits.params[0].{field} must be an ASCII identifier "
                    f"(non-keyword, at most {MAX_PARAM_NAME_LENGTH} characters)"
                ),
            )
        return value

    op = raw.get("op")
    if op == "add":
        if set(raw) != {"op", "name", "type", "default"}:
            raise HTTPException(
                status_code=400,
                detail='edits.params[0] for "add" must have exactly op/name/type/default',
            )
        name = _checked_name("name")
        ptype = raw.get("type")
        if ptype not in PARAM_TYPE_NAMES:
            raise HTTPException(
                status_code=400,
                detail=f"edits.params[0].type must be one of {list(PARAM_TYPE_NAMES)}",
            )
        default = raw.get("default")
        bad_default = HTTPException(
            status_code=400,
            detail=f"edits.params[0].default does not match type {ptype!r}",
        )
        if ptype == "bool":
            if not isinstance(default, bool):
                raise bad_default
        elif ptype == "int":
            if isinstance(default, bool) or not isinstance(default, int):
                raise bad_default
        elif ptype == "float":
            if isinstance(default, bool) or not isinstance(default, int | float):
                raise bad_default
            if not math.isfinite(float(default)):
                raise HTTPException(
                    status_code=400, detail="edits.params[0].default must be finite"
                )
        else:  # str
            if not isinstance(default, str):
                raise bad_default
            if len(default) > MAX_PARAM_STR_DEFAULT_LENGTH:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"edits.params[0].default exceeds {MAX_PARAM_STR_DEFAULT_LENGTH} characters"
                    ),
                )
            if any(unicodedata.category(ch) in FORBIDDEN_DEFAULT_CATEGORIES for ch in default):
                raise HTTPException(
                    status_code=400,
                    detail="edits.params[0].default must not contain control characters",
                )
        return [AddParam(name=name, type=ptype, default=default)]
    if op == "remove":
        if set(raw) != {"op", "name"}:
            raise HTTPException(
                status_code=400,
                detail='edits.params[0] for "remove" must have exactly op/name',
            )
        return [RemoveParam(name=_checked_name("name"))]
    if op == "rename":
        if set(raw) != {"op", "from", "to"}:
            raise HTTPException(
                status_code=400,
                detail='edits.params[0] for "rename" must have exactly op/from/to',
            )
        # ADR-0075 §論点 2-D: rename × ポート編集の併用は 400 (E4a の証明を単純に保つ)
        if any(
            edits.get(k) is not None for k in ("inputs", "outputs", "input_names", "output_names")
        ):
            raise HTTPException(
                status_code=400,
                detail="edits.params rename cannot be combined with port edits",
            )
        return [RenameParam(old=_checked_name("from"), new=_checked_name("to"))]
    raise HTTPException(status_code=400, detail=f"Unknown edits.params op: {op!r}")


@router.post("/python-function/rewrite")
async def rewrite_python_function(request: Request) -> dict[str, Any]:
    """``PythonFunction`` ソースのポート構造を書き換える (SPEC-0024 §3.1)。

    Body: ``{"code": "<source>", "edits": {"inputs"?, "outputs"?, "input_names"?,
    "output_names"?}}`` (patch セマンティクス: 省略した key は書き換えない)。

    Returns:
        200 ``{"applied": true, "code", "spec"}`` — 書き換え成功。``spec`` は
        introspect と同一形なので、frontend は 1 往復で cache 投入 → commit できる。
        200 ``{"applied": false, "error": {...}}`` — ソース側の事情で書き換え不能
        (受理契約外・編集不可の形・自己検証失敗)。**元コードは返さない**。
        400 — body 自体の不正 (型・範囲・サイズ)。クライアントのバグ。

    Note:
        **この endpoint はユーザーコードを exec しない** (introspect と同じ不変条件)。
        静的 AST 解析 + テキスト splice + 再解析のみ。
    """
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")
    code = body.get("code")
    edits = body.get("edits")
    if not isinstance(code, str):
        raise HTTPException(status_code=400, detail="`code` (string) is required in body")
    if len(code) > MAX_INTROSPECT_CODE_CHARS:
        raise HTTPException(
            status_code=400, detail=f"`code` exceeds {MAX_INTROSPECT_CODE_CHARS} characters"
        )
    if not isinstance(edits, dict):
        raise HTTPException(status_code=400, detail="`edits` (object) is required in body")
    unknown = set(edits) - {"inputs", "outputs", "input_names", "output_names", "params"}
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown edits keys: {sorted(unknown)}")
    _validated_rewrite_count(edits, "inputs")
    _validated_rewrite_count(edits, "outputs")
    _validated_rewrite_names(edits, "input_names")
    _validated_rewrite_names(edits, "output_names")
    param_edits = _validated_rewrite_params(edits)

    return await run_in_threadpool(
        rewrite_python_source, code, edits, key="rewrite", params=param_edits
    )


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
