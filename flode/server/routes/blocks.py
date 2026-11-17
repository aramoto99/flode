"""Block class registry エンドポイント (ADR-0019 §(1) / ADR-0081 §論点 8)。

ブロックパレット UI が利用する。サーバ起動時に build される
``app.state.block_registry`` (= ``BlockCatalog``、組み込み + ユーザーブロック) を返却 / 検索する。
``POST /blocks/reload`` はユーザーブロックを読み込み直し、新しい ``BlockCatalog`` を
1 回の代入で差し替える。
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from ...exceptions import (
    BlockReloadInProgressError,
    BlockSpecError,
    ParamSearchFunctionError,
    ParamSearchUnavailableError,
    UnknownBlockTypeError,
)
from ...userblocks import (
    PARAM_ROWS_ACTIONS,
    ParamRowsComposeResult,
    ParamRowsDescribeResult,
    ParamRowsField,
    ParamRowsFormResult,
    ParamRowsResult,
    ParamSearchResult,
    reload_sources,
)
from ...userblocks._param_rows import (
    MAX_PARAM_ROWS_FIELDS,
    MAX_PARAM_ROWS_ID_CHARS,
    MAX_PARAM_ROWS_PICK_VALUES,
    MAX_PARAM_ROWS_VALUE_CHARS,
    is_single_line_text,
)
from ..block_catalog import (
    BlockCatalog,
    compose_catalog,
    initial_catalog,
    registry_payload,
    reload_allowed,
    reload_payload,
    reload_rejection_reason,
)
from ..errors import build_user_blocks_error
from ..registry import (
    BlockMetadata,
    introspect_python_source,
    metadata_to_dict,
    param_rows,
    resolve_port_shapes,
    rewrite_python_source,
    search_param_values,
)
from ..settings import Settings

_logger = logging.getLogger("flode.server.routes.blocks")

router = APIRouter(prefix="/blocks", tags=["blocks"])

# SPEC-0023 introspect の入力上限 (security-reviewer: 無認証の CPU 消費点になるため)。
# 1 モデルに 64 個超の PythonFunction、256 KiB 超のソースは実用上あり得ない。
MAX_INTROSPECT_ITEMS = 64
MAX_INTROSPECT_CODE_CHARS = 256 * 1024

# ADR-0085 §2-E / §3-A: 引数の値の検索 (search-param-values) の入力上限と件数
MAX_PARAM_SEARCH_QUERY_CHARS = 256
MAX_PARAM_SEARCH_TYPE_PATH_CHARS = 512
MAX_PARAM_SEARCH_PARAM_CHARS = 256
#: ``current`` は引数の行 (= ポート)。ポート数の上限 256 の 4 倍の余裕
MAX_PARAM_SEARCH_CURRENT_ITEMS = 1024
MAX_PARAM_SEARCH_CURRENT_ITEM_CHARS = 1000
PARAM_SEARCH_DEFAULT_LIMIT = 200
PARAM_SEARCH_MAX_LIMIT = 1000
#: サーバ全体で同時に走らせるユーザーブロックの補助呼び出し (検索 ``search-param-values`` と
#: 行エディタ ``param-rows`` の合計) の数 (ADR-0085 §2-D / ADR-0086 §3-D、超えたら 409)。
#: スレッドプールは他の API と共有するので、重い初回の読み込みが要求の数だけ並行しないようにする
MAX_CONCURRENT_PARAM_SEARCHES = 2
PARAM_SEARCH_BUSY_DETAIL = "another parameter search is running; try again when it finishes"
#: 非 loopback bind で、検索関数の例外 (ユーザーコード由来の文字列) の代わりに返す固定文
PARAM_SEARCH_REMOTE_ERROR_DETAIL = "the search function raised an exception; see the server log"
PARAM_SEARCH_DISABLED_DETAIL = "user blocks are not enabled in this server configuration"

# ADR-0086 §3-B: 行エディタ (param-rows) の入力上限 (違反はすべて 400、ユーザーコードは走らない)
#: 本文の大きさ (``Content-Length`` と実際に読んだ長さの両方で見る)。search-param-values も共有
MAX_PARAM_ROWS_BODY_BYTES = 4 * 1024 * 1024
#: ``params`` の入れ子の深さ (``params`` 自身が 1)
MAX_PARAM_ROWS_PARAMS_DEPTH = 16
#: ``params`` に含まれる値 (入れ物を含む) の総数
MAX_PARAM_ROWS_PARAMS_NODES = 50_000
#: ``params`` の中の文字列 (キーを含む) 1 つの最大長
MAX_PARAM_ROWS_PARAMS_STRING_CHARS = 64 * 1024
#: ``rows`` の件数と 1 行の最大長 (検索の ``current`` と同じ)
MAX_PARAM_ROWS_ITEMS = MAX_PARAM_SEARCH_CURRENT_ITEMS
MAX_PARAM_ROWS_ITEM_CHARS = MAX_PARAM_SEARCH_CURRENT_ITEM_CHARS
PARAM_ROWS_BUSY_DETAIL = "another parameter helper is running; try again when it finishes"
#: 非 loopback bind で、行エディタの例外 (ユーザーコード由来の文字列) の代わりに返す固定文
PARAM_ROWS_REMOTE_ERROR_DETAIL = "the row editor raised an exception; see the server log"


def _catalog(request: Request) -> BlockCatalog:
    """app.state から registry (``BlockCatalog``) を取り出す型安全 helper。

    lifespan を通らない (test fixture 等) 場合は lifespan と同じ手順で作る。
    """
    catalog = getattr(request.app.state, "block_registry", None)
    if catalog is None:  # lifespan 起動前の test fixture 等
        catalog = initial_catalog(request.app.state.settings)
        request.app.state.block_registry = catalog
    # ``-O`` モード対策で assert を使わない実行時 check (ADR-0019 code-reviewer MUST)。
    if not isinstance(catalog, BlockCatalog):
        raise HTTPException(status_code=500, detail="block_registry state is corrupted")
    return catalog


def _registry(request: Request) -> tuple[BlockMetadata, ...]:
    """現在の registry のブロック一覧 (読み取りは 1 回の参照取得で完結する)。"""
    return _catalog(request).blocks


@router.get("")
def list_blocks(request: Request) -> dict[str, Any]:
    """全 Block class metadata を返す (パレット表示用、ADR-0019、ADR-0028、ADR-0081)。

    完全な docstring はサイズが大きくなるため省略 (``docstring_summary`` のみ)。
    詳細は ``GET /api/v1/blocks/{type_path}`` で個別取得する。

    ADR-0081 (blocks.v3、追加のみ): 各ブロックに ``source`` / ``input_names`` /
    ``output_names``、トップレベルに ``sources`` / ``load_errors`` / ``user_blocks``。
    形は ``flode.server.block_catalog.registry_payload`` を参照。
    """
    return registry_payload(_catalog(request), request.app.state.settings)


@router.get("/reload")
def reload_blocks_get_method_not_allowed() -> None:
    """``POST /api/v1/blocks/reload`` の GET 方向の 405 stub (catch-all への誤マッチ防止)。"""
    raise HTTPException(
        status_code=405,
        detail="Use POST /api/v1/blocks/reload with the JSON body {} to reload user blocks.",
    )


@router.post("/reload")
async def reload_blocks(request: Request) -> dict[str, Any]:
    """ワークスペース ``blocks/`` と config ``dirs`` のユーザーブロックを読み込み直す (ADR-0081 §2)。

    本文は ``{}`` 固定 (``application/json`` 必須にして CSRF guard の content-type 検査を必ず
    通す。パス・モジュール名は受け取らない)。config ``modules`` は読み直さない (Q5a)。
    実行中のシミュレーションは旧クラスのまま走り切る (SPEC-0033 P8) ので拒否しない。

    Returns:
        ``GET /blocks`` と同じ形 + ``added`` / ``removed`` / ``changed`` /
        ``restart_required_sources`` / ``errors`` (``load_errors`` と同じ)。

    Raises:
        HTTPException: 403 (``user_blocks_disabled`` / ``reload_not_allowed``)、
            400 (``invalid_reload_body``)、409 (``reload_in_progress``)。detail は
            ADR-0056 の構造化形式 + ``code``。読み込み後の registry 組み立てが想定外に失敗した
            場合は 500 (管理型表は新しい世代、registry は旧世代のまま。ログに記録する)。
    """
    settings: Settings = request.app.state.settings
    if not reload_allowed(settings):
        code = "user_blocks_disabled" if not settings.user_blocks_enabled else "reload_not_allowed"
        raise HTTPException(
            status_code=403,
            detail=build_user_blocks_error(
                code,
                reload_rejection_reason(settings),
                non_loopback=not settings.loopback_bind,
            ),
        )
    bad_body = HTTPException(
        status_code=400,
        detail=build_user_blocks_error(
            "invalid_reload_body", "the request body must be the JSON object {}"
        ),
    )
    try:
        body = await request.json()
    except ValueError as e:
        raise bad_body from e
    if not isinstance(body, dict) or body:
        raise bad_body

    lock: threading.Lock = request.app.state.block_reload_lock

    def _reload() -> BlockCatalog:
        # server ロックの取得・解放はワーカースレッドの中で完結させる。
        # 事実確認 (anyio 4 の asyncio backend、``run_sync_in_worker_thread``): Starlette の
        # ``run_in_threadpool`` は ``anyio.to_thread.run_sync(func)`` を
        # ``abandon_on_cancel=False`` で呼び、待機は ``CancelScope(shield=True)`` の中で行う。
        # anyio のキャンセルスコープ経由のキャンセルではスレッドの完了を待つが、
        # ``asyncio.Task.cancel()`` による素のキャンセル (サーバ終了時等) は shield を通り抜けて
        # ``await future`` が即座に ``CancelledError`` になり、スレッドは走り続ける。
        # 解放をイベントループ側の ``finally`` に置くと、その隙に次の再読み込みが割り込み、
        # 遅れて終わった古い方の差し替えが新しい方を上書きしうる。スレッド内で取って放せば、
        # 差し替えまで終わるまで次の再読み込みは必ず 409 になる。
        if not lock.acquire(blocking=False):
            raise BlockReloadInProgressError("the server is already reloading user blocks")
        try:
            current = _catalog(request)
            report = reload_sources()
            try:
                catalog = compose_catalog(current.builtin, report, settings)
            except Exception:
                # U2 の管理型表 (実行時の型解決) は既に新しい世代に替わっているが、registry
                # (パレット) は旧世代のまま残る。U2 側を戻す手段は無いので記録して 500 にする。
                # 次の再読み込みが成功すれば両者は一致する。
                _logger.exception(
                    "user blocks were reloaded but building the registry failed; the block "
                    "registry was not replaced (the palette may be out of date until the "
                    "next successful reload)"
                )
                raise
            # コミット点 (ADR-0081 §2-A 手順 6): 新しい registry を 1 回の代入で差し替える
            request.app.state.block_registry = catalog
            return catalog
        finally:
            lock.release()

    try:
        catalog = await run_in_threadpool(_reload)
    except BlockReloadInProgressError as e:
        _logger.info("user blocks reload rejected: %s", e)
        raise HTTPException(
            status_code=409,
            detail=build_user_blocks_error(
                "reload_in_progress",
                "user blocks are already being reloaded; try again when it finishes",
            ),
        ) from e
    return reload_payload(catalog, settings)


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
        ユーザーブロックはさらに ``"input_names"`` / ``"output_names"`` (空 = 無名)。

    Raises:
        HTTPException: type_path 解決失敗 → 404、``__init__`` 失敗 → 400
            (ユーザーブロックはユーザーコードのどんな例外も 400)。
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
        # ユーザーブロックの __init__ が重くても event loop (WS 配信・他の API) を止めない
        resolved = await run_in_threadpool(resolve_port_shapes, type_path, params)
    except UnknownBlockTypeError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except BlockSpecError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    out: dict[str, Any] = {
        "n_inputs": resolved.n_inputs,
        "n_outputs": resolved.n_outputs,
        "port_shapes_in": resolved.port_shapes_in,
        "port_shapes_out": resolved.port_shapes_out,
    }
    if resolved.input_names is not None:
        out["input_names"] = resolved.input_names
    if resolved.output_names is not None:
        out["output_names"] = resolved.output_names
    return out


@router.get("/search-param-values")
def search_param_values_get_method_not_allowed() -> None:
    """``POST /api/v1/blocks/search-param-values`` の GET 方向の 405 stub。

    ``resolve-port-shapes`` と同じ理由 (catch-all ``GET /{type_path:path}`` への誤マッチ防止)。
    """
    raise HTTPException(
        status_code=405,
        detail=(
            "Use POST /api/v1/blocks/search-param-values with body "
            "{type_path, param, query, limit?, current} to search parameter values."
        ),
    )


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


def _validated_target(body: dict[str, Any]) -> tuple[str, str]:
    """本文の ``type_path`` / ``param`` を検証する (search-param-values と param-rows で共通)。"""
    type_path = body.get("type_path")
    param = body.get("param")
    if not isinstance(type_path, str) or not type_path:
        raise _bad_request("`type_path` (string) is required in body")
    if len(type_path) > MAX_PARAM_SEARCH_TYPE_PATH_CHARS:
        raise _bad_request(f"`type_path` exceeds {MAX_PARAM_SEARCH_TYPE_PATH_CHARS} characters")
    if not isinstance(param, str) or not param:
        raise _bad_request("`param` (string) is required in body")
    if len(param) > MAX_PARAM_SEARCH_PARAM_CHARS:
        raise _bad_request(f"`param` exceeds {MAX_PARAM_SEARCH_PARAM_CHARS} characters")
    return type_path, param


def _validated_query_and_limit(body: dict[str, Any]) -> tuple[str, int]:
    """本文の ``query`` / ``limit`` を検証する (search-param-values と param-rows の search で共通)。

    Returns:
        ``(前後の空白を除いた query, 1〜上限に丸めた limit)``。
    """
    query = body.get("query")
    if not isinstance(query, str):
        raise _bad_request("`query` (string) is required in body")
    if len(query) > MAX_PARAM_SEARCH_QUERY_CHARS:
        raise _bad_request(f"`query` exceeds {MAX_PARAM_SEARCH_QUERY_CHARS} characters")
    query = query.strip()
    if not query:
        raise _bad_request("`query` must not be empty")
    raw_limit = body.get("limit")
    if raw_limit is None:
        limit = PARAM_SEARCH_DEFAULT_LIMIT
    elif isinstance(raw_limit, bool) or not isinstance(raw_limit, int):
        raise _bad_request("`limit` must be an integer")
    else:
        # 表示件数の希望なので範囲外は丸める (型の誤りだけ 400)
        limit = min(max(raw_limit, 1), PARAM_SEARCH_MAX_LIMIT)
    return query, limit


def _validated_param_search_body(body: Any) -> tuple[str, str, str, int, list[str]]:
    """search-param-values の本文を検証する (ADR-0085 §2-E / §3-A、違反はすべて 400)。

    Returns:
        ``(type_path, param, 前後の空白を除いた query, 1〜上限に丸めた limit, current)``。
    """
    if not isinstance(body, dict):
        raise _bad_request("Body must be a JSON object")
    type_path, param = _validated_target(body)
    query, limit = _validated_query_and_limit(body)
    current = body.get("current")
    if not isinstance(current, list):
        raise _bad_request("`current` (array of strings) is required in body")
    if len(current) > MAX_PARAM_SEARCH_CURRENT_ITEMS:
        raise _bad_request(f"`current` must have at most {MAX_PARAM_SEARCH_CURRENT_ITEMS} entries")
    for i, item in enumerate(current):
        if not isinstance(item, str):
            raise _bad_request(f"current[{i}] must be a string")
        if len(item) > MAX_PARAM_SEARCH_CURRENT_ITEM_CHARS:
            raise _bad_request(
                f"current[{i}] exceeds {MAX_PARAM_SEARCH_CURRENT_ITEM_CHARS} characters"
            )
    return type_path, param, query, limit, current


@router.post("/search-param-values")
async def search_param_values_endpoint(request: Request) -> dict[str, Any]:
    """ユーザーブロックが提供する引数の値の検索を実行する (ADR-0085、試験的)。

    Body: ``{"type_path": str, "param": str, "query": str, "limit"?: int, "current": [str]}``。
    ``limit`` は省略時 200、1〜1000 に丸める。

    Returns:
        ``{"columns": [str], "rows": [{"cells": [str | number | null], "value": str}],
        "truncated": bool}``。

    Raises:
        HTTPException: 404 (型がユーザーブロックとして読み込まれていない / その引数に検索の
            宣言が無い。ユーザーコードは走らない)、400 (本文の型違反・上限超過 (本文は
            ``MAX_PARAM_ROWS_BODY_BYTES`` まで)・不正な JSON (深い入れ子・NaN を含む)・空の検索語・
            検索関数の例外・不正な応答)、409 (同時に走る検索の数が上限)。detail は文字列。
            ユーザーブロックが無効な構成では本文も読まずに 404。非 loopback bind では
            検索関数の例外の detail を固定文にする (メッセージはサーバのログにある)。
    """
    settings: Settings = request.app.state.settings
    if not settings.user_blocks_enabled:
        # 管理型表の中身に関係なく、ユーザーコードを走らせない (security-reviewer SHOULD-1)
        raise HTTPException(status_code=404, detail=PARAM_SEARCH_DISABLED_DETAIL)
    # 本文の上限・深い入れ子・NaN は param-rows と同じ扱い (security SHOULD-2)
    body = await _read_limited_json(request)
    type_path, param, query, limit, current = _validated_param_search_body(body)
    semaphore: threading.BoundedSemaphore = request.app.state.param_search_semaphore

    def _search() -> ParamSearchResult | None:
        # 取得・解放はワーカースレッドの中で完結させる (再読み込みのロックと同じ理由)。
        # 取れなければ待たずに None (= 409)。待つとスレッドプールを握り続けるため
        if not semaphore.acquire(blocking=False):
            return None
        try:
            return search_param_values(type_path, param, query, limit, current)
        finally:
            semaphore.release()

    try:
        result = await run_in_threadpool(_search)
    except ParamSearchUnavailableError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ParamSearchFunctionError as e:
        detail = str(e) if settings.loopback_bind else PARAM_SEARCH_REMOTE_ERROR_DETAIL
        raise HTTPException(status_code=400, detail=detail) from e
    except BlockSpecError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if result is None:
        _logger.info(
            "parameter search for %r / %r rejected: %d search(es) are already running",
            type_path,
            param,
            MAX_CONCURRENT_PARAM_SEARCHES,
        )
        raise HTTPException(status_code=409, detail=PARAM_SEARCH_BUSY_DETAIL)
    return {
        "columns": list(result.columns),
        "rows": [{"cells": list(row.cells), "value": row.value} for row in result.rows],
        "truncated": result.truncated,
    }


@router.get("/param-rows")
def param_rows_get_method_not_allowed() -> None:
    """``POST /api/v1/blocks/param-rows`` の GET 方向の 405 stub (catch-all への誤マッチ防止)。"""
    raise HTTPException(
        status_code=405,
        detail=(
            "Use POST /api/v1/blocks/param-rows with body "
            "{type_path, param, action, params, ...} to call a block's row editor."
        ),
    )


@dataclass(frozen=True)
class _ParamRowsRequest:
    """検証済みの param-rows の要求。"""

    type_path: str
    param: str
    action: str
    params: dict[str, Any]
    action_args: dict[str, Any]


def _reject_json_constant(name: str) -> Any:
    """``json.loads`` の ``parse_constant``: ``NaN`` / ``Infinity`` / ``-Infinity`` は 400。"""
    raise _bad_request(f"Body must not contain {name} (not valid JSON)")


def _loads_json(raw: bytes) -> Any:
    """本文を JSON として解析する (不正・深い入れ子・NaN / Infinity は 400)。

    巨大な本文の解析はイベントループを止めるため、``run_in_threadpool`` で呼ぶ。
    """
    try:
        return json.loads(raw, parse_constant=_reject_json_constant)
    except (ValueError, RecursionError) as e:
        # 深い入れ子は ValueError ではなく RecursionError になる (ADR-0086 G-5)
        raise _bad_request("Body must be valid JSON") from e


async def _read_limited_json(request: Request) -> Any:
    """本文を ``MAX_PARAM_ROWS_BODY_BYTES`` まで読んで JSON として解析する (超過・不正は 400)。

    ``Content-Length`` で先に断り、chunked 等で長さの宣言が無い・偽る場合に備えて
    実際に読んだ長さでも見る。解析はスレッドプールで行い、深い入れ子の ``RecursionError`` と
    ``NaN`` / ``Infinity`` も 400 にする (ADR-0086 G-5)。読んでいる途中の切断も 400
    (応答は届かないが、500 のトレースバックを残さない)。
    """
    too_large = _bad_request(f"the request body exceeds {MAX_PARAM_ROWS_BODY_BYTES} bytes")
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_bytes = int(declared)
        except ValueError as e:
            raise _bad_request("invalid Content-Length header") from e
        if declared_bytes > MAX_PARAM_ROWS_BODY_BYTES:
            raise too_large
    chunks: list[bytes] = []
    total = 0
    try:
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_PARAM_ROWS_BODY_BYTES:
                raise too_large
            chunks.append(chunk)
    except ClientDisconnect as e:
        raise _bad_request("the client disconnected while sending the body") from e
    return await run_in_threadpool(_loads_json, b"".join(chunks))


def _check_param_rows_params(params: dict[str, Any]) -> None:
    """``params`` の深さ・値の総数・文字列の長さを反復で検査する (再帰しない)。

    値の総数は入れ物の中身を積む前に数える (積んでから数えると、平らな巨大配列 1 つで
    要素数ぶんの tuple を作ってしまう。security SHOULD-1)。dict はキーと値で 2 つずつ。
    """
    too_many = _bad_request(f"`params` has more than {MAX_PARAM_ROWS_PARAMS_NODES} values")
    stack: list[tuple[Any, int]] = [(params, 1)]
    nodes = 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if isinstance(value, str):
            if len(value) > MAX_PARAM_ROWS_PARAMS_STRING_CHARS:
                raise _bad_request(
                    f"`params` has a string longer than {MAX_PARAM_ROWS_PARAMS_STRING_CHARS} "
                    f"characters"
                )
        elif isinstance(value, dict | list):
            if depth > MAX_PARAM_ROWS_PARAMS_DEPTH:
                raise _bad_request(
                    f"`params` is nested deeper than {MAX_PARAM_ROWS_PARAMS_DEPTH} levels"
                )
            width = 2 * len(value) if isinstance(value, dict) else len(value)
            if nodes + len(stack) + width > MAX_PARAM_ROWS_PARAMS_NODES:
                raise too_many
            if isinstance(value, dict):
                for key, item in value.items():
                    # JSON のキーは常に文字列 (念のため)。キーの長さも文字列の上限で見る
                    if not isinstance(key, str):
                        raise _bad_request("`params` keys must be strings")
                    stack.append((key, depth + 1))
                    stack.append((item, depth + 1))
            else:
                stack.extend((item, depth + 1) for item in value)


def _require_single_line(value: str, where: str) -> None:
    """ユーザーコードに渡す要求の文字列に改行・制御文字があれば 400 (空は許す)。

    応答の ``value`` / 組み立てた行と同じ規則 (``is_single_line_text``)。
    """
    if not is_single_line_text(value):
        raise _bad_request(f"{where} contains a line break or a control character")


def _validated_rows_field(body: dict[str, Any]) -> list[str]:
    rows = body.get("rows")
    if not isinstance(rows, list):
        raise _bad_request("`rows` (array of strings) is required in body")
    if len(rows) > MAX_PARAM_ROWS_ITEMS:
        raise _bad_request(f"`rows` must have at most {MAX_PARAM_ROWS_ITEMS} entries")
    for i, item in enumerate(rows):
        if not isinstance(item, str):
            raise _bad_request(f"rows[{i}] must be a string")
        if len(item) > MAX_PARAM_ROWS_ITEM_CHARS:
            raise _bad_request(f"rows[{i}] exceeds {MAX_PARAM_ROWS_ITEM_CHARS} characters")
        _require_single_line(item, f"rows[{i}]")
    return rows


def _validated_short_id(body: dict[str, Any], name: str) -> str:
    value = body.get(name)
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_PARAM_ROWS_ID_CHARS:
        raise _bad_request(
            f"`{name}` must be a string of 1 to {MAX_PARAM_ROWS_ID_CHARS} characters"
        )
    _require_single_line(value, f"`{name}`")
    return value


def _validated_compose_values(raw: Any) -> dict[str, str | list[str]]:
    if not isinstance(raw, dict):
        raise _bad_request("`values` (object) is required in body")
    if len(raw) > MAX_PARAM_ROWS_FIELDS:
        raise _bad_request(f"`values` must have at most {MAX_PARAM_ROWS_FIELDS} keys")
    values: dict[str, str | list[str]] = {}
    for key, value in raw.items():
        if not 1 <= len(key) <= MAX_PARAM_ROWS_ID_CHARS:
            raise _bad_request(f"`values` keys must be 1 to {MAX_PARAM_ROWS_ID_CHARS} characters")
        _require_single_line(key, "a `values` key")
        where = f"values[{key!r}]"
        if isinstance(value, str):
            if len(value) > MAX_PARAM_ROWS_VALUE_CHARS:
                raise _bad_request(f"{where} exceeds {MAX_PARAM_ROWS_VALUE_CHARS} characters")
            _require_single_line(value, where)
        elif isinstance(value, list):
            if len(value) > MAX_PARAM_ROWS_PICK_VALUES:
                raise _bad_request(
                    f"{where} must have at most {MAX_PARAM_ROWS_PICK_VALUES} entries"
                )
            for i, item in enumerate(value):
                if not isinstance(item, str):
                    raise _bad_request(f"{where}[{i}] must be a string")
                if len(item) > MAX_PARAM_ROWS_VALUE_CHARS:
                    raise _bad_request(
                        f"{where}[{i}] exceeds {MAX_PARAM_ROWS_VALUE_CHARS} characters"
                    )
                _require_single_line(item, f"{where}[{i}]")
        else:
            raise _bad_request(f"{where} must be a string or an array of strings")
        values[key] = value
    return values


def _validated_search_args(body: dict[str, Any]) -> dict[str, Any]:
    field = _validated_short_id(body, "field")
    query, limit = _validated_query_and_limit(body)
    _require_single_line(query, "`query`")
    return {"field": field, "query": query, "limit": limit}


def _validated_action_args(action: str, body: dict[str, Any]) -> dict[str, Any]:
    """action ごとの引数を検証する (ADR-0086 §3-B)。"""
    if action == "describe":
        return {"rows": _validated_rows_field(body)}
    if action == "form":
        row = body.get("row")
        if row is not None and not isinstance(row, str):
            raise _bad_request("`row` must be a string or null")
        if row is not None:
            if len(row) > MAX_PARAM_ROWS_ITEM_CHARS:
                raise _bad_request(f"`row` exceeds {MAX_PARAM_ROWS_ITEM_CHARS} characters")
            _require_single_line(row, "`row`")
        return {"row": row}
    if action == "compose":
        variant = _validated_short_id(body, "variant")
        values = _validated_compose_values(body.get("values"))
        rows = _validated_rows_field(body)
        index = body.get("index")
        if index is not None:
            if isinstance(index, bool) or not isinstance(index, int):
                raise _bad_request("`index` must be null or an integer")
            if not 0 <= index < len(rows):
                raise _bad_request(f"`index` must be in 0..{len(rows) - 1} (the edited row)")
        return {"variant": variant, "values": values, "rows": rows, "index": index}
    return _validated_search_args(body)


def _validated_param_rows_body(body: Any) -> _ParamRowsRequest:
    """param-rows の本文を検証する (ADR-0086 §3-B、違反はすべて 400)。"""
    if not isinstance(body, dict):
        raise _bad_request("Body must be a JSON object")
    type_path, param = _validated_target(body)
    action = body.get("action")
    params = body.get("params")
    if not isinstance(action, str) or action not in PARAM_ROWS_ACTIONS:
        raise _bad_request(f"`action` must be one of {list(PARAM_ROWS_ACTIONS)}")
    if not isinstance(params, dict):
        raise _bad_request("`params` (object) is required in body")
    _check_param_rows_params(params)
    action_args = _validated_action_args(action, body)
    return _ParamRowsRequest(
        type_path=type_path, param=param, action=action, params=params, action_args=action_args
    )


def _field_payload(field: ParamRowsField) -> dict[str, Any]:
    out: dict[str, Any] = {"key": field.key, "label": field.label, "kind": field.kind}
    if field.kind == "choice":
        out["options"] = [{"value": o.value, "label": o.label} for o in field.options]
    return out


def _param_rows_payload(result: ParamRowsResult) -> dict[str, Any]:
    """検証済みの結果を応答の JSON にする (ADR-0086 §2-C / §3-A)。"""
    if isinstance(result, ParamRowsDescribeResult):
        return {
            "columns": list(result.columns),
            "rows": [{"cells": list(row.cells), "error": row.error} for row in result.rows],
            "ports": result.ports,
        }
    if isinstance(result, ParamRowsFormResult):
        return {
            "variants": [
                {
                    "id": v.id,
                    "label": v.label,
                    "fields": [_field_payload(f) for f in v.fields],
                }
                for v in result.variants
            ],
            "variant": result.variant,
            "values": {k: list(v) if isinstance(v, tuple) else v for k, v in result.values.items()},
        }
    if isinstance(result, ParamRowsComposeResult):
        return {"row": result.row}
    return {
        "columns": list(result.columns),
        "rows": [{"cells": list(row.cells), "value": row.value} for row in result.rows],
        "truncated": result.truncated,
    }


@router.post("/param-rows")
async def param_rows_endpoint(request: Request) -> dict[str, Any]:
    """ユーザーブロックが提供する行リスト引数の行エディタを呼ぶ (ADR-0086、試験的)。

    Body: ``{"type_path": str, "param": str, "action": str, "params": {...}, ...}``。
    action ごとの追加: describe ``rows: [str]`` / form ``row: str | null`` /
    compose ``variant: str, values: {key: str | [str]}, rows: [str], index: int | null`` /
    search ``field: str, query: str, limit?: int``。

    Returns:
        describe ``{"columns", "rows": [{"cells", "error"}], "ports"}`` /
        form ``{"variants": [{"id", "label", "fields": [{"key", "label", "kind",
        "options"?}]}], "variant", "values"}`` / compose ``{"row"}`` /
        search ``{"columns", "rows": [{"cells", "value"}], "truncated"}``。

    Raises:
        HTTPException: 404 (ユーザーブロック無効 / 型が無い / 宣言が無い。ユーザーコードは
            走らない)、400 (本文の型違反・上限超過・未知の action・行エディタの例外・未対応の
            action・不正な応答)、409 (検索と共有する同時実行の上限)。detail は文字列。
            非 loopback bind では行エディタの例外の detail を固定文にする。
    """
    settings: Settings = request.app.state.settings
    if not settings.user_blocks_enabled:
        # 管理型表の中身に関係なく、本文も読まずにユーザーコードを走らせない
        raise HTTPException(status_code=404, detail=PARAM_SEARCH_DISABLED_DETAIL)
    body = await _read_limited_json(request)
    # 4 MiB までの本文の走査はイベントループを止めうるのでスレッドプールで行う (security SHOULD-1)
    req = await run_in_threadpool(_validated_param_rows_body, body)
    semaphore: threading.BoundedSemaphore = request.app.state.param_search_semaphore

    def _call() -> ParamRowsResult | None:
        # 取得・解放はワーカースレッドの中で完結させる (search-param-values と同じ理由)
        if not semaphore.acquire(blocking=False):
            return None
        try:
            return param_rows(
                req.type_path,
                req.param,
                action=req.action,
                params=req.params,
                action_args=req.action_args,
            )
        finally:
            semaphore.release()

    try:
        result = await run_in_threadpool(_call)
    except ParamSearchUnavailableError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ParamSearchFunctionError as e:
        detail = str(e) if settings.loopback_bind else PARAM_ROWS_REMOTE_ERROR_DETAIL
        raise HTTPException(status_code=400, detail=detail) from e
    except BlockSpecError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if result is None:
        _logger.info(
            "row editor %r for %r / %r rejected: %d helper call(s) are already running",
            req.action,
            req.type_path,
            req.param,
            MAX_CONCURRENT_PARAM_SEARCHES,
        )
        raise HTTPException(status_code=409, detail=PARAM_ROWS_BUSY_DETAIL)
    return _param_rows_payload(result)


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
        MAX_PARAM_INT_DEFAULT_DIGITS,
        MAX_PARAM_NAME_LENGTH,
        MAX_PARAM_STR_DEFAULT_LENGTH,
        PARAM_NAME_RE,
        PARAM_TYPE_NAMES,
        AddParam,
        RemoveParam,
        RenameParam,
        RetypeParam,
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
            if default.bit_length() > 4 * MAX_PARAM_INT_DEFAULT_DIGITS or (
                len(str(abs(default))) > MAX_PARAM_INT_DEFAULT_DIGITS
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"edits.params[0].default must have at most "
                        f"{MAX_PARAM_INT_DEFAULT_DIGITS} digits"
                    ),
                )
        elif ptype == "float":
            if isinstance(default, bool) or not isinstance(default, int | float):
                raise bad_default
            try:
                as_float = float(default)
            except (OverflowError, ValueError) as e:
                # security-reviewer MUST: 巨大 int の float 変換は OverflowError
                raise HTTPException(
                    status_code=400,
                    detail="edits.params[0].default is out of float range",
                ) from e
            if not math.isfinite(as_float):
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
    if op == "retype":
        if set(raw) != {"op", "name", "type"}:
            raise HTTPException(
                status_code=400,
                detail='edits.params[0] for "retype" must have exactly op/name/type',
            )
        name = _checked_name("name")
        ptype = raw.get("type")
        if ptype not in PARAM_TYPE_NAMES:
            raise HTTPException(
                status_code=400,
                detail=f"edits.params[0].type must be one of {list(PARAM_TYPE_NAMES)}",
            )
        return [RetypeParam(name=name, type=ptype)]
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
