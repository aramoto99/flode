"""シミュレーション制御 + WebSocket エンドポイント (ADR-0011 §(1)(2))。"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from ...exceptions import PyflwError, SimulationStillRunningError
from ..runtime import SimulationManager
from .models import _model_dir, _model_path

router = APIRouter(prefix="/simulations", tags=["simulations"])


def _manager(request: Request) -> SimulationManager:
    return request.app.state.simulation_manager  # type: ignore[no-any-return]


def _scope_batch_size(request: Request) -> int:
    return int(request.app.state.settings.scope_batch_size)


@router.post("")
async def start_simulation(request: Request) -> dict[str, str]:
    payload = await request.json()
    if not isinstance(payload, dict) or "model_id" not in payload:
        raise HTTPException(status_code=400, detail="Body must be {'model_id': '<id>'}")
    model_id = payload["model_id"]
    path = _model_path(_model_dir(request), model_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Model {model_id!r} not found")
    manager = _manager(request)
    loop = asyncio.get_running_loop()
    sim_id = manager.start(
        model_id=model_id,
        model_path=path,
        loop=loop,
        scope_batch_size=_scope_batch_size(request),
    )
    return {"simulation_id": sim_id, "model_id": model_id}


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
