"""シミュレーション実行マネージャ (ADR-0011 §(4))。

``ThreadPoolExecutor`` で ``Simulator.run()`` を背景実行し、Scope データを
``asyncio.Queue`` に push して WebSocket クライアントへ配信する。
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import threading
import time
import uuid
from collections.abc import AsyncIterator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

import numpy as np

from ..core.persistence import serialize_t_end
from ..core.simulator import Simulator
from ..exceptions import PyflwError, SimulationStillRunningError

_logger = logging.getLogger("pyflw.server.runtime")


@dataclasses.dataclass
class SimulationState:
    """シミュレーションの公開状態 (REST ``GET /simulations/{id}`` 用)。

    ADR-0042 §論点 3-A: ``t_end`` は ``float`` (有限値) または ``"inf"`` 文字列
    リテラル (= unbounded、``Stop Time = inf``) を取る Union。
    """

    simulation_id: str
    model_id: str
    status: str  # "running" / "completed" / "failed" / "stopped"
    current_t: float
    t_end: float | str
    started_at: float
    finished_at: float | None = None
    error: str | None = None


class _SimulationRecord:
    """内部追跡: Simulator インスタンス + 背景タスク + asyncio キュー。"""

    def __init__(
        self,
        *,
        simulation_id: str,
        model_id: str,
        simulator: Simulator,
        loop: asyncio.AbstractEventLoop,
        scope_batch_size: int,
    ) -> None:
        self.simulation_id = simulation_id
        self.model_id = model_id
        self.simulator = simulator
        self.loop = loop
        self.scope_batch_size = scope_batch_size
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1024)
        self.state = SimulationState(
            simulation_id=simulation_id,
            model_id=model_id,
            status="running",
            current_t=0.0,
            # ADR-0042 §論点 3-A: ``math.inf`` は wire 上 ``"inf"`` 文字列で
            # 配信する (= JS 側 JSON.stringify(Infinity)==="null" の罠回避)。
            t_end=serialize_t_end(simulator.t_end),
            started_at=time.time(),
        )
        self.future: Future[None] | None = None
        # 各 Scope の前回送信済みインデックス (バッチ送信用)
        self._scope_cursors: dict[str, int] = {}


class SimulationManager:
    """背景タスクで ``Simulator.run`` を回し WS にイベントを配信するマネージャ。

    ``FastAPI`` の lifespan 内で 1 つだけ生成し、リクエストハンドラから利用する。
    """

    def __init__(self, max_concurrent: int = 4) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self._records: dict[str, _SimulationRecord] = {}
        self._lock = threading.Lock()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def list_simulations(self) -> list[SimulationState]:
        with self._lock:
            return [dataclasses.replace(r.state) for r in self._records.values()]

    def get_state(self, sim_id: str) -> SimulationState:
        with self._lock:
            if sim_id not in self._records:
                raise PyflwError(f"Unknown simulation_id: {sim_id!r}")
            return dataclasses.replace(self._records[sim_id].state)

    def stop(self, sim_id: str) -> None:
        with self._lock:
            if sim_id not in self._records:
                raise PyflwError(f"Unknown simulation_id: {sim_id!r}")
            rec = self._records[sim_id]
        rec.simulator.request_stop()

    def start(
        self,
        *,
        model_id: str,
        simulator: Simulator,
        loop: asyncio.AbstractEventLoop,
        scope_batch_size: int,
    ) -> str:
        """既に構築済の ``Simulator`` インスタンスからシミュレーションを開始する。

        ADR-0041 §論点 5-A 以前は ``model_path`` を受け取って ``Simulator.load``
        を内部で呼んでいたが、ファイル ロード / インラインモデル / 旧 ``model_id``
        の 3 形式が混在するようになったため **ロード責務を呼び出し側に委譲**
        した。route handler が文字列引数を Simulator に解決してから start を
        呼ぶ形に統一。

        Args:
            model_id: 表示用モデル識別子 (= ファイル path / 旧 model_id /
                ``"<inline>"`` のいずれか)。トラッキング表示用で fs にアクセス
                しない。
            simulator: 構築済の ``Simulator`` インスタンス (= ``Simulator.load`` /
                ``Simulator.from_dict`` のどちらかで生成済)。
            loop: WS dispatch 用の asyncio loop。
            scope_batch_size: Scope バッチ送信のサイズ。
        """
        sim_id = uuid.uuid4().hex[:12]
        record = _SimulationRecord(
            simulation_id=sim_id,
            model_id=model_id,
            simulator=simulator,
            loop=loop,
            scope_batch_size=scope_batch_size,
        )

        # on_step_callback を設定 (バッチ送信トリガー)
        simulator.on_step_callback = lambda t, t_end: self._on_step(record, t, t_end)

        with self._lock:
            self._records[sim_id] = record
        record.future = self._executor.submit(self._run_in_thread, record)
        return sim_id

    # ---------- 内部実装 ----------

    def _on_step(self, rec: _SimulationRecord, t: float, t_end: float) -> bool:
        rec.state.current_t = t
        # 各 Scope について新規サンプル数が batch_size に達したら送信
        for b in rec.simulator.blocks:
            scope = _as_scope(b)
            if scope is None:
                continue
            assert scope.id is not None
            cursor = rec._scope_cursors.get(scope.id, 0)
            n_total = len(scope.times)
            if n_total - cursor >= rec.scope_batch_size:
                self._dispatch_scope_batch(rec, scope, cursor, n_total)
                rec._scope_cursors[scope.id] = n_total
        # progress イベント (バッチサイズに関わらず毎ステップ送る)。
        # ADR-0042 §論点 3-A: ``t_end`` は ``serialize_t_end`` 経由で
        # ``math.inf → "inf"`` 文字列にする (= wire 形式統一)。
        self._dispatch(
            rec,
            {
                "type": "progress",
                "current_t": t,
                "t_end": serialize_t_end(t_end),
            },
        )
        return True

    def _flush_remaining_scopes(self, rec: _SimulationRecord) -> None:
        """終了時に残った scope サンプルを送る。"""
        for b in rec.simulator.blocks:
            scope = _as_scope(b)
            if scope is None:
                continue
            assert scope.id is not None
            cursor = rec._scope_cursors.get(scope.id, 0)
            n_total = len(scope.times)
            if n_total > cursor:
                self._dispatch_scope_batch(rec, scope, cursor, n_total)
                rec._scope_cursors[scope.id] = n_total

    def _dispatch_scope_batch(
        self, rec: _SimulationRecord, scope: Any, start: int, end: int
    ) -> None:
        # ADR-0042 §論点 2-A: ``Scope.buffer_mode='ring'`` で ``scope.times`` が
        # ``deque`` の場合、slice 直接適用は非対応。一度 list / np.asarray に
        # 変換してから slice することで両モード対応する。
        # NOTE: ring wrap 後に最古サンプルが drop されると ``cursor`` が
        # stale になる edge case があるが、Step 5 (WS scope_overflow message
        # 配信) で本格対応する。本ステップでは finite t_end 既存挙動の
        # 完全互換のみを保証する。
        times = list(scope.times)[start:end]
        values_arr = np.asarray(scope.values)[start:end]
        msg = {
            "type": "scope_batch",
            "scope_id": scope.id,
            "times": times,
            "values": values_arr.tolist(),
        }
        self._dispatch(rec, msg)

    def _dispatch(self, rec: _SimulationRecord, msg: dict[str, Any]) -> None:
        """thread から asyncio.Queue へ thread-safe に push (ADR-0011 Risk #1)。

        Queue が満杯 (= 1024 件) の場合は **古いメッセージを drop** して新しい
        メッセージを優先する (back-pressure ではなく fail-fast)。これにより thread
        側が put で永続的に block するのを防ぐ (code-reviewer MUST #4 修正)。
        """

        async def _put_or_drop() -> None:
            try:
                rec.queue.put_nowait(msg)
            except asyncio.QueueFull:
                # 古いものを 1 件 drop して空きを作って入れ直す
                try:
                    _ = rec.queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    rec.queue.put_nowait(msg)
                except asyncio.QueueFull:
                    _logger.warning(
                        "WS queue still full after eviction; dropping message type=%r "
                        "(simulation_id=%s)",
                        msg.get("type"),
                        rec.simulation_id,
                    )

        try:
            asyncio.run_coroutine_threadsafe(_put_or_drop(), rec.loop)
        except RuntimeError:
            # loop が閉じている場合は drop (シャットダウン途中)
            _logger.debug("event loop closed; dropping message %r", msg.get("type"))

    def _run_in_thread(self, rec: _SimulationRecord) -> None:
        try:
            rec.simulator.run()
            self._flush_remaining_scopes(rec)
            if rec.simulator.is_stopped:
                rec.state.status = "stopped"
            else:
                rec.state.status = "completed"
        except Exception as e:  # noqa: BLE001 - server境界でドメイン例外もシステム例外も補足
            _logger.exception("simulation %s failed", rec.simulation_id)
            rec.state.status = "failed"
            rec.state.error = f"{type(e).__name__}: {e}"
            self._dispatch(rec, {"type": "error", "message": rec.state.error})
        finally:
            rec.state.finished_at = time.time()
            duration = rec.state.finished_at - rec.state.started_at
            self._dispatch(
                rec,
                {
                    "type": rec.state.status,  # completed / stopped / failed
                    "duration_sec": duration,
                },
            )

    async def stream(self, sim_id: str) -> AsyncIterator[dict[str, Any]]:
        with self._lock:
            if sim_id not in self._records:
                raise PyflwError(f"Unknown simulation_id: {sim_id!r}")
            rec = self._records[sim_id]
        terminal_types = {"completed", "stopped", "failed"}
        while True:
            msg = await rec.queue.get()
            yield msg
            if msg.get("type") in terminal_types:
                break

    def get_results(self, sim_id: str) -> dict[str, Any]:
        """完了後に Scope データを一括取得 (ADR-0011 §(1) GET /results)。"""
        with self._lock:
            if sim_id not in self._records:
                raise PyflwError(f"Unknown simulation_id: {sim_id!r}")
            rec = self._records[sim_id]
        if rec.state.status == "running":
            raise SimulationStillRunningError(
                f"Simulation {sim_id!r} is still running; results not yet available"
            )
        scopes: dict[str, Any] = {}
        for b in rec.simulator.blocks:
            scope = _as_scope(b)
            if scope is None:
                continue
            assert scope.id is not None
            scopes[scope.id] = {
                "labels": list(scope.labels),
                "times": list(scope.times),
                "values": np.asarray(scope.values).tolist(),
            }
        return {
            "simulation_id": sim_id,
            "status": rec.state.status,
            "scopes": scopes,
        }


def _as_scope(b: Any) -> Any:
    """``Scope`` 互換のブロックなら ``b`` を返し、そうでなければ ``None``。

    duck-typing で ``record`` / ``times`` / ``values`` / ``labels`` を持つかを確認
    する。``Block`` 基底に直接の attr 宣言がないため、mypy は ``Any`` 経由で呼び
    出す形にする。
    """
    if (
        hasattr(b, "record")
        and hasattr(b, "times")
        and hasattr(b, "values")
        and hasattr(b, "labels")
    ):
        return b
    return None
