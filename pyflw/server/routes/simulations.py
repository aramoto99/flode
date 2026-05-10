"""シミュレーション制御 + WebSocket エンドポイント (ADR-0011 §(1)(2)、ADR-0041 §5)。"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import warnings
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from ...core.simulator import Simulator
from ...exceptions import (
    ModelLoadError,
    PathTraversalError,
    PyflwError,
    SimulationStillRunningError,
)
from ..runtime import SimulationManager
from ..security import resolve_workspace_path
from .models import _model_dir, _model_path

_logger = logging.getLogger("pyflw.server.routes.simulations")

router = APIRouter(prefix="/simulations", tags=["simulations"])

_DEPRECATION_MODEL_ID_MSG = (
    "POST /api/v1/simulations with 'model_id' is deprecated; use 'model_path' "
    "(workspace-relative) or 'model' (inline) instead. 'model_id' will be removed "
    "in v3.0 (see ADR-0041 §5 for migration guide)."
)

_INLINE_DISPLAY_ID = "<inline>"
"""インライン model 経由のシミュレーションの ``model_id`` 表示値 (ADR-0041 §5)。

複数のインライン実行が共存しても ``simulation_id`` で区別できるため、
``model_id`` 表示は固定値で OK。frontend は ``"<inline>"`` をトラッキング
タブで「未保存」表示等に使う想定。
"""


def _manager(request: Request) -> SimulationManager:
    return request.app.state.simulation_manager  # type: ignore[no-any-return]


def _scope_batch_size(request: Request) -> int:
    return int(request.app.state.settings.scope_batch_size)


def _resolve_simulator(
    request: Request, payload: dict[str, Any]
) -> tuple[Simulator, str]:
    """request body から ``Simulator`` を構築する (ADR-0041 §論点 5-A)。

    3 形式を受け付け、相互排他で 1 つだけ指定されることを要求:

    * ``{"model_id": str}`` — legacy、deprecated。``model_dir / "{id}.flw.json"``
      から load。
    * ``{"model_path": str}`` — workspace 相対 path。``resolve_workspace_path``
      で path traversal 防御を通してから ``Simulator.load``。``workspace_root``
      未設定なら 503。
    * ``{"model": dict}`` — インライン (= 未保存 editingModel の試行実行)。
      ``Simulator.from_dict`` で構築、fs アクセスなし。

    Returns:
        ``(simulator, display_id)``。``display_id`` はトラッキング表示用 (=
        legacy では model_id、path では path 文字列、inline では ``"<inline>"``)。
    """
    # `key in payload` ベースの検出 — `{"model": false}` や `{"model": 0}` 等の
    # falsy 値も「指定あり」として拾い、後続の type validation で 400 にする
    # (= "指定なし" との誤誘導メッセージを避ける、code-reviewer SHOULD 修正)。
    specified_keys = [k for k in ("model_id", "model_path", "model") if k in payload]
    model_id = payload.get("model_id")
    model_path = payload.get("model_path")
    model_inline = payload.get("model")
    if len(specified_keys) == 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "Body must specify exactly one of: 'model_id' (deprecated), "
                "'model_path' (workspace-relative), or 'model' (inline)."
            ),
        )
    if len(specified_keys) > 1:
        raise HTTPException(
            status_code=400,
            detail=(
                "Body must specify exactly one of 'model_id' / 'model_path' / "
                f"'model' (mutually exclusive). Got: {specified_keys}."
            ),
        )

    if model_id is not None:
        if not isinstance(model_id, str):
            raise HTTPException(status_code=400, detail="'model_id' must be a string")
        # ``stacklevel=2`` は ``_resolve_simulator → start_simulation`` の
        # 1 階層分を skip して route handler の行を指す。利用者は HTTP client
        # 経由なので Python スタックは server プロセス内で完結するが、運用者が
        # ``-W default::DeprecationWarning`` 起動時に warning 元を辿りやすくする
        # 用途。pytest ``recwarn`` fixture との互換性も維持。
        warnings.warn(_DEPRECATION_MODEL_ID_MSG, DeprecationWarning, stacklevel=2)
        path = _model_path(_model_dir(request), model_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Model {model_id!r} not found")
        try:
            simulator = Simulator.load(path)
        except ModelLoadError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return simulator, model_id

    if model_path is not None:
        if not isinstance(model_path, str):
            raise HTTPException(status_code=400, detail="'model_path' must be a string")
        settings = request.app.state.settings
        workspace_root = settings.workspace_root
        if workspace_root is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "'model_path' requires --workspace=PATH; "
                    "currently in legacy --model-dir mode (see ADR-0041 §3)."
                ),
            )
        try:
            resolved = resolve_workspace_path(workspace_root, model_path)
        except PathTraversalError as e:
            _logger.warning("Path traversal rejected in /simulations: %s", e)
            raise HTTPException(
                status_code=403,
                detail="Path traversal rejected (see server log for details).",
            ) from e
        if not resolved.exists():
            raise HTTPException(
                status_code=404, detail=f"Model file not found: {model_path}"
            )
        if resolved.is_dir():
            raise HTTPException(
                status_code=400,
                detail=f"'model_path' is a directory, not a file: {model_path}",
            )
        try:
            simulator = Simulator.load(resolved)
        except ModelLoadError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return simulator, model_path

    # model_inline (= dict)
    if not isinstance(model_inline, dict):
        raise HTTPException(
            status_code=400, detail="'model' must be a JSON object"
        )
    try:
        simulator = Simulator.from_dict(model_inline)
    except ModelLoadError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return simulator, _INLINE_DISPLAY_ID


@router.post("")
async def start_simulation(request: Request) -> dict[str, str]:
    """シミュレーションを開始する (ADR-0041 §論点 5-A、3 形式対応)。

    Request body は ``model_id`` (= legacy、deprecated) / ``model_path`` /
    ``model`` のうち **正確に 1 つ** を含む JSON object。詳細は
    ``_resolve_simulator`` docstring 参照。
    """
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")

    simulator, display_id = _resolve_simulator(request, payload)

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
    except PyflwError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return dataclasses.asdict(state)


@router.post("/{sim_id}/stop")
def stop_simulation(request: Request, sim_id: str) -> dict[str, str]:
    manager = _manager(request)
    try:
        manager.stop(sim_id)
    except PyflwError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"simulation_id": sim_id, "status": "stop_requested"}


@router.get("/{sim_id}/results")
def get_results(request: Request, sim_id: str) -> dict[str, Any]:
    manager = _manager(request)
    try:
        return manager.get_results(sim_id)
    except SimulationStillRunningError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except PyflwError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.websocket("/{sim_id}/stream")
async def stream(websocket: WebSocket, sim_id: str) -> None:
    """シミュレーション進捗 + Scope データを WebSocket で配信。

    クライアントは接続後、サーバから JSON メッセージを順次受信する:
    ``progress`` / ``scope_batch`` / ``completed`` / ``stopped`` / ``failed`` / ``error``。

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
                        except PyflwError:
                            pass
            except WebSocketDisconnect:
                return

        recv_task = asyncio.create_task(_receiver())
        try:
            async for msg in manager.stream(sim_id):
                await websocket.send_json(msg)
        finally:
            recv_task.cancel()
    except PyflwError as e:
        await websocket.send_json({"type": "error", "message": f"{type(e).__name__}: {e}"})
    except WebSocketDisconnect:
        pass
    finally:
        # WebSocket がまだ閉じていなければ閉じる (クライアント側の disconnect で
        # すでに閉じている可能性もある)
        try:
            await websocket.close()
        except RuntimeError:
            pass
