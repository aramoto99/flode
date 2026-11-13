"""シミュレーション制御 + WebSocket エンドポイント (ADR-0011 §(1)(2)、ADR-0041 §5)。

v0.21.0: legacy ``model_id`` 受付を削除。``model_path`` (= workspace 相対 path)
または ``model`` (= インライン dict) のいずれかを必須に。

ADR-0056: シミュレーション開始エラーは構造化 detail で返す
(``{detail: {category, template_key, ...}}``)。WS の ``error`` メッセージは廃止し、
``failed`` 1 件に構造化フィールドをマージして送る (= runtime 側で実施)。
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from ...blocks.pythonfunc import (
    compute_python_digest,
    get_python_block_policy,
    iter_python_functions,
)
from ...core.persistence import migrate_to_current, resolve_block_class
from ...core.simulator import Simulator
from ...exceptions import (
    FlodeError,
    ModelLoadError,
    PathTraversalError,
    PythonBlocksDisabledError,
    SimulationStillRunningError,
    UnknownBlockTypeError,
)
from ..errors import (
    CATEGORY_PYTHON_FUNCTION_UNCONFIRMED,
    MissingBlockType,
    build_failure_payload,
    build_unknown_block_type_payload,
)
from ..runtime import SimulationManager
from ..security import resolve_workspace_path

_logger = logging.getLogger("flode.server.routes.simulations")

router = APIRouter(prefix="/simulations", tags=["simulations"])

#: ``unknown_block_type`` で列挙する一意な型の上限 (超えたら ``truncated``)。
MAX_LISTED_UNKNOWN_TYPES = 64
#: ``unknown_block_type`` で列挙するブロックの上限 (超えたら ``truncated``)。
MAX_LISTED_UNKNOWN_BLOCKS = 256
#: 列挙のために解決を試みる一意な型名の上限 (解決できる型も含む)。
MAX_RESOLVED_TYPE_NAMES = 1024
#: ログに出す型名の件数。
_LOGGED_UNKNOWN_TYPES = 5

_INLINE_DISPLAY_ID = "<inline>"
"""インライン model 経由のシミュレーションの ``model_id`` 表示値 (ADR-0041 §5)。

複数のインライン実行が共存しても ``simulation_id`` で区別できるため、
``model_id`` 表示は固定値で OK。frontend は ``"<inline>"`` をトラッキング
タブで「未保存」表示等に使う想定。
"""


def _manager(request: Request) -> SimulationManager:
    return request.app.state.simulation_manager  # type: ignore[no-any-return]


def _start_validation_detail(message: str) -> dict[str, Any]:
    """ADR-0056 §B-2: start API のシンプルな validation error 用の構造化 detail。

    例外が無いケース (= body の形式違反等) で使う。``ModelLoadError`` や
    ``BlockSpecError`` 等の例外がある場合は ``build_failure_payload`` を直接使う。
    """
    return {
        "category": "start_validation",
        "template_key": "error.start_validation",
        "template_args": {"message": message},
        "block_id": None,
        "block_ids": [],
        "block_type": None,
        "block_label": None,
        "t": None,
        "raw_message": message,
        "raw_traceback": None,
    }


def _exception_detail(exc: BaseException) -> dict[str, Any]:
    """例外から start API 用の構造化 detail を組み立てる (ADR-0056 §B-2)。"""
    return build_failure_payload(exc, simulator=None, t=None)


def _python_unconfirmed_detail(simulator: Simulator, digest: str) -> dict[str, Any]:
    """SPEC-0023 soft gate (ADR-0073 §論点 4 (S)): 409 用の構造化 detail。

    ``template_args.digest`` をクライアントが echo して再送する。この機構は
    「このモデルは Python を実行する」の告知と同意のための **UX 機構** であり、
    セキュリティ機構ではない (REST を直接叩けば ack を自分で付けられる)。
    """
    entries = list(iter_python_functions(simulator.blocks))
    labels = [qid for qid, _ in entries]
    ids = [pf.id for _, pf in entries if isinstance(pf.id, str)]
    return {
        "category": CATEGORY_PYTHON_FUNCTION_UNCONFIRMED,
        "template_key": "error.python_function_unconfirmed",
        "template_args": {"block_labels": labels, "digest": digest},
        "block_id": ids[0] if ids else None,
        "block_ids": ids,
        "block_type": "flode.blocks.pythonfunc.PythonFunction",
        "block_label": labels[0] if labels else None,
        "t": None,
        "raw_message": (
            "This model contains PythonFunction blocks. Running it executes their Python "
            "code with your privileges. Re-send with python_ack=<digest> to confirm."
        ),
        "raw_traceback": None,
    }


def _enforce_python_gates(simulator: Simulator, payload: dict[str, Any]) -> None:
    """``PythonFunction`` を含むモデルの start 前チェック (SPEC-0023 / ADR-0073 §論点 4)。

    * hard gate: プロセス policy が禁止なら **403** (構造化 detail
      ``python_function_disabled``)。``_build()`` でも同じ判定が走るので、ここでの
      早期拒否は「ワーカーを起動せずに即答する」ための重複であり bypass 点ではない
    * soft gate: ``python_ack`` が digest と一致しなければ **409**

    ``PythonFunction`` を含まないモデルでは何もしない (= ``python_ack`` は無視、
    既存クライアント完全互換)。
    """
    digest = compute_python_digest(simulator)
    if digest is None:
        return
    policy = get_python_block_policy()
    if not policy.allowed:
        first = next(iter_python_functions(simulator.blocks), None)
        block_id = first[1].id if first is not None else None
        reason = f" ({policy.reason})" if policy.reason else ""
        exc = PythonBlocksDisabledError(
            f"PythonFunction: execution of Python blocks is disabled in this server{reason}. "
            f"Start the server with --allow-python-blocks or set [server] "
            f"allow_python_blocks = true to enable it.",
            block_id=block_id,
        )
        raise HTTPException(status_code=403, detail=_exception_detail(exc))
    ack = payload.get("python_ack")
    if not isinstance(ack, str) or ack != digest:
        raise HTTPException(status_code=409, detail=_python_unconfirmed_detail(simulator, digest))


def _scope_batch_size(request: Request) -> int:
    return int(request.app.state.settings.scope_batch_size)


def _resolve_simulator(request: Request, payload: dict[str, Any]) -> tuple[Simulator, str]:
    """request body から ``Simulator`` を構築する (ADR-0041 §論点 5-A)。

    v0.21.0: 2 形式のみ。相互排他で 1 つだけ指定:

    * ``{"model_path": str}`` — workspace 相対 path。``resolve_workspace_path``
      で path traversal 防御を通してから ``Simulator.load``。
    * ``{"model": dict}`` — インライン (= 未保存 editingModel の試行実行)。
      ``Simulator.from_dict`` で構築、fs アクセスなし。

    Returns:
        ``(simulator, display_id)``。``display_id`` はトラッキング表示用 (=
        path では path 文字列、inline では ``"<inline>"``)。
    """
    # `key in payload` ベース検出 (= falsy 値も「指定あり」として拾う)
    specified_keys = [k for k in ("model_path", "model") if k in payload]
    model_path = payload.get("model_path")
    model_inline = payload.get("model")
    if len(specified_keys) == 0:
        raise HTTPException(
            status_code=400,
            detail=_start_validation_detail(
                "Body must specify exactly one of: 'model_path' "
                "(workspace-relative) or 'model' (inline)."
            ),
        )
    if len(specified_keys) > 1:
        raise HTTPException(
            status_code=400,
            detail=_start_validation_detail(
                "Body must specify exactly one of 'model_path' / 'model' "
                f"(mutually exclusive). Got: {specified_keys}."
            ),
        )

    if model_path is not None:
        if not isinstance(model_path, str):
            raise HTTPException(
                status_code=400,
                detail=_start_validation_detail("'model_path' must be a string"),
            )
        settings = request.app.state.settings
        workspace_root = settings.workspace_root
        try:
            resolved = resolve_workspace_path(workspace_root, model_path)
        except PathTraversalError as e:
            # _resolve_simulator は models route とも共有のため、監査ログには
            # 実際の endpoint パスを記録する (security-reviewer SHOULD-3)
            _logger.warning("Path traversal rejected in %s: %s", request.url.path, e)
            raise HTTPException(
                status_code=403,
                detail=_start_validation_detail(
                    "Path traversal rejected (see server log for details)."
                ),
            ) from e
        if not resolved.exists():
            raise HTTPException(
                status_code=404,
                detail=_start_validation_detail(f"Model file not found: {model_path}"),
            )
        if resolved.is_dir():
            raise HTTPException(
                status_code=400,
                detail=_start_validation_detail(
                    f"'model_path' is a directory, not a file: {model_path}"
                ),
            )
        try:
            simulator = Simulator.load(resolved)
        except UnknownBlockTypeError as e:
            raise _unknown_block_type_error(_read_model_file(resolved), e) from e
        except ModelLoadError as e:
            raise HTTPException(status_code=400, detail=_exception_detail(e)) from e
        return simulator, model_path

    # model_inline (= dict)
    if not isinstance(model_inline, dict):
        raise HTTPException(
            status_code=400,
            detail=_start_validation_detail("'model' must be a JSON object"),
        )
    try:
        simulator = Simulator.from_dict(model_inline)
    except UnknownBlockTypeError as e:
        raise _unknown_block_type_error(model_inline, e) from e
    except ModelLoadError as e:
        raise HTTPException(status_code=400, detail=_exception_detail(e)) from e
    return simulator, _INLINE_DISPLAY_ID


def _read_model_file(path: Path) -> Any:
    """``unknown_block_type`` の全列挙用にモデルファイルを読み直す (読めなければ ``None``)。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _missing_block_types(model: Any) -> tuple[list[MissingBlockType], bool]:
    """モデル (Subsystem 内部を含む) で解決できない型のブロックを集める (ADR-0081 §4-B)。

    ``Simulator.from_dict`` は最初の 1 件で止まるので、``UnknownBlockTypeError`` が出たときだけ
    呼んで列挙する。型の解決は ``from_dict`` と同じ ``resolve_block_class`` (管理型表 →
    予約ルートは import しない → allowlist) なので、新たな import の経路は作らない。
    Subsystem 内部 (``params.blocks``) は、型が解決できないか ``_from_dict`` を持つ (= コンテナ)
    ブロックの中だけを見る。走査は明示的なスタックで行い (深い入れ子でも再帰しない)、
    文書順 (行きがけ順) で並べる。

    列挙数には上限がある: 一意な型 ``MAX_LISTED_UNKNOWN_TYPES``、ブロック
    ``MAX_LISTED_UNKNOWN_BLOCKS``、解決を試みる一意な型名 ``MAX_RESOLVED_TYPE_NAMES``
    (無認証のクライアントが大量の型名で import の試行を誘発するのを防ぐ)。

    Returns:
        ``(欠けているブロック, 上限で打ち切ったか)``。
    """
    if not isinstance(model, dict):
        return [], False
    # from_dict が同じ dict で既に通しているので、ここでの migration は読むだけの再実行
    data = migrate_to_current(model)
    resolved: dict[str, type | None] = {}
    missing: list[MissingBlockType] = []
    types: set[str] = set()
    truncated = False
    root_blocks = data.get("blocks")
    stack: list[tuple[Any, tuple[str, ...]]] = [
        (entry, ()) for entry in reversed(root_blocks if isinstance(root_blocks, list) else [])
    ]
    while stack:
        entry, prefix = stack.pop()
        if not isinstance(entry, dict):
            continue
        raw_id = entry.get("id")
        block_id = raw_id if isinstance(raw_id, str) else str(raw_id)
        type_path = entry.get("type")
        cls: type | None = None
        if isinstance(type_path, str):
            if type_path not in resolved:
                if len(resolved) >= MAX_RESOLVED_TYPE_NAMES:
                    truncated = True
                    break
                try:
                    resolved[type_path] = resolve_block_class(type_path)
                except ModelLoadError:
                    resolved[type_path] = None
            cls = resolved[type_path]
        if cls is None:
            shown_type = type_path if isinstance(type_path, str) else repr(type_path)
            if len(missing) >= MAX_LISTED_UNKNOWN_BLOCKS or (
                shown_type not in types and len(types) >= MAX_LISTED_UNKNOWN_TYPES
            ):
                truncated = True
                break
            types.add(shown_type)
            missing.append(
                MissingBlockType(
                    block_id=block_id,
                    qualified_id="/".join((*prefix, block_id)),
                    type_path=shown_type,
                )
            )
        params = entry.get("params")
        if isinstance(params, dict) and (cls is None or callable(getattr(cls, "_from_dict", None))):
            inner = params.get("blocks")
            if isinstance(inner, list):
                stack.extend((child, (*prefix, block_id)) for child in reversed(inner))
    return missing, truncated


def _unknown_block_type_error(model: Any, exc: UnknownBlockTypeError) -> HTTPException:
    """解決できない型を並べた 400 ``unknown_block_type`` (列挙できなければ従来の detail)。

    列挙はベストエフォート: 想定外の失敗 (``RecursionError`` を含む) は「列挙できない」とみなして
    従来の ``start_validation`` の detail に戻す (400 を 500 にしない)。
    """
    try:
        missing, truncated = _missing_block_types(model)
    except Exception:  # noqa: BLE001 - 列挙は付加情報。どんな失敗でも従来の 400 に戻す
        _logger.warning("Could not enumerate unloaded block types", exc_info=True)
        missing, truncated = [], False
    if not missing:
        return HTTPException(status_code=400, detail=_exception_detail(exc))
    types = list(dict.fromkeys(m.type_path for m in missing))
    _logger.info(
        "Rejected a model with unloaded block types: %d type(s), %d block(s)%s, e.g. %r",
        len(types),
        len(missing),
        " (truncated)" if truncated else "",
        types[:_LOGGED_UNKNOWN_TYPES],
    )
    return HTTPException(
        status_code=400, detail=build_unknown_block_type_payload(missing, truncated=truncated)
    )


@router.post("")
async def start_simulation(request: Request) -> dict[str, str]:
    """シミュレーションを開始する (ADR-0041 §論点 5-A、2 形式対応)。

    Request body は ``model_path`` または ``model`` のうち **正確に 1 つ** を
    含む JSON object。詳細は ``_resolve_simulator`` docstring 参照。
    """
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail=_start_validation_detail("Body must be a JSON object"),
        )

    # モデルの構築 (と型が欠けているときの列挙) は event loop を止めないよう threadpool で行う
    simulator, display_id = await run_in_threadpool(_resolve_simulator, request, payload)
    _enforce_python_gates(simulator, payload)

    manager = _manager(request)
    loop = asyncio.get_running_loop()
    sim_id = manager.start(
        model_id=display_id,
        simulator=simulator,
        loop=loop,
        scope_batch_size=_scope_batch_size(request),
    )
    return {"simulation_id": sim_id, "model_id": display_id}


@router.get("")
def list_simulations(request: Request) -> dict[str, Any]:
    manager = _manager(request)
    return {"simulations": [dataclasses.asdict(s) for s in manager.list_simulations()]}


@router.get("/{sim_id}")
def get_simulation(request: Request, sim_id: str) -> dict[str, Any]:
    manager = _manager(request)
    try:
        state = manager.get_state(sim_id)
    except FlodeError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return dataclasses.asdict(state)


@router.post("/{sim_id}/stop")
def stop_simulation(request: Request, sim_id: str) -> dict[str, str]:
    manager = _manager(request)
    try:
        manager.stop(sim_id)
    except FlodeError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"simulation_id": sim_id, "status": "stop_requested"}


@router.get("/{sim_id}/results")
def get_results(request: Request, sim_id: str) -> dict[str, Any]:
    manager = _manager(request)
    try:
        return manager.get_results(sim_id)
    except SimulationStillRunningError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except FlodeError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.websocket("/{sim_id}/stream")
async def stream(websocket: WebSocket, sim_id: str) -> None:
    """シミュレーション進捗 + Scope データを WebSocket で配信。

    クライアントは接続後、サーバから JSON メッセージを順次受信する:
    ``progress`` / ``scope_batch`` / ``completed`` / ``stopped`` / ``failed``。

    ADR-0056: 旧 ``error`` メッセージは廃止 (= 失敗時の構造化フィールドは
    ``failed`` メッセージにマージされる)。

    クライアントが ``{"type": "stop"}`` を送るとサーバ側で
    ``SimulationManager.stop`` を呼ぶ。

    Note:
        WS は live 接続向け。途中参加した場合は接続前の ``progress`` /
        ``scope_batch`` 取り損ない、内部 ``asyncio.Queue`` (max 1024) が満杯時は
        古いメッセージから drop される (ADR-0011 §(2) / Risk #2)。完全な結果は
        ``GET /api/v1/simulations/{id}/results`` で取得すること。
    """
    await websocket.accept()
    manager: SimulationManager = websocket.app.state.simulation_manager
    try:
        # クライアント受信タスク (停止コマンド用) を並走
        async def _receiver() -> None:
            try:
                while True:
                    text = await websocket.receive_text()
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(data, dict) and data.get("type") == "stop":
                        try:
                            manager.stop(sim_id)
                        except FlodeError:
                            pass
            except WebSocketDisconnect:
                return

        recv_task = asyncio.create_task(_receiver())
        try:
            async for msg in manager.stream(sim_id):
                await websocket.send_json(msg)
        finally:
            recv_task.cancel()
    except FlodeError as e:
        # ADR-0056: 旧 ``error`` メッセージは廃止。WS 確立中のドメイン例外
        # (例: 未知の simulation_id) は構造化 ``failed`` で 1 件返してから閉じる。
        terminal = {"type": "failed", "duration_sec": 0.0}
        terminal.update(build_failure_payload(e, simulator=None, t=None))
        try:
            await websocket.send_json(terminal)
        except RuntimeError:
            pass
    except WebSocketDisconnect:
        pass
    finally:
        # WebSocket がまだ閉じていなければ閉じる (クライアント側の disconnect で
        # すでに閉じている可能性もある)
        try:
            await websocket.close()
        except RuntimeError:
            pass
