"""ADR-0083 §(5): 実行ログ (ブロックが出したログを WS ``log`` / results ``logs`` で届ける)。"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from flode import Block
from flode.blocks import Constant, Scope
from flode.core.simulator import Simulator
from flode.server.run_log import (
    RUN_LOG_MAX_ENTRIES,
    RUN_LOG_MAX_MESSAGE_CHARS,
    RunLogHandler,
)
from flode.server.runtime import SimulationManager

_user_logger = logging.getLogger("flode_ws.demo")
#: 実行スレッドの終わりを待つ上限 (超えたら future.result が TimeoutError で失敗する)
_RUN_TIMEOUT_SEC = 10.0


class _Talker(Block):
    """t = 0.1 で INFO、t = 0.2 で WARNING を出す素通しブロック。"""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id, n_inputs=1, n_outputs=1)
        self._params = {}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        if abs(t - 0.1) < 1e-9:
            _user_logger.info("picked up %s", "armor")
        if abs(t - 0.2) < 1e-9:
            _user_logger.warning("low health")
        return np.asarray(u, dtype=float)


def _model() -> Simulator:
    sim = Simulator(t_end=0.3, dt=0.1)
    sim.add(Constant(value=1.0, id="c"))
    sim.add(_Talker(id="talk"))
    sim.add(Scope(id="scope"))
    sim.connect("c", "talk")
    sim.connect("talk", "scope")
    return sim


async def _run(manager: SimulationManager) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sim_id = manager.start(
        model_id="<inline>",
        simulator=_model(),
        loop=asyncio.get_running_loop(),
        scope_batch_size=10,
    )
    messages = [m async for m in manager.stream(sim_id)]
    return messages, manager.get_results(sim_id)


def test_block_logs_are_streamed_and_returned() -> None:
    manager = SimulationManager()
    try:
        messages, results = asyncio.run(_run(manager))
    finally:
        manager.shutdown()
    logs = [m for m in messages if m["type"] == "log"]
    assert [(m["level"], m["message"]) for m in logs] == [
        ("INFO", "picked up armor"),
        ("WARNING", "low health"),
    ]
    assert logs[0]["logger"] == "flode_ws.demo"
    assert logs[0]["t"] == pytest.approx(0.1, abs=0.11)
    # ログは terminal より前に届く
    assert messages[-1]["type"] == "completed"
    assert [e["message"] for e in results["logs"]] == ["picked up armor", "low health"]
    assert results["logs_dropped"] == 0


def test_stream_started_after_the_run_finished_still_gets_every_message() -> None:
    """実行がイベントループより先に終わっても、最初の接続ではキューの中身を全部受け取る。

    送信は ``run_coroutine_threadsafe`` で予約されるだけなので、ループが回るまでキューは
    空のまま。そこで「終端済み + キューが空」を再接続とみなすと完了だけを返して終わり、
    ログや Scope のデータを取りこぼしていた (速い実行で CI だけ失敗)。
    """
    manager = SimulationManager()

    async def go() -> list[dict[str, Any]]:
        sim_id = manager.start(
            model_id="<inline>",
            simulator=_model(),
            loop=asyncio.get_running_loop(),
            scope_batch_size=10,
        )
        # ループを止めたまま (= 予約された送信を処理させずに) 実行スレッドの終わりを待つ。
        # Future の完了 = 完了メッセージの予約 (finally) まで済んだ状態
        future = manager._records[sim_id].future
        assert future is not None
        future.result(timeout=_RUN_TIMEOUT_SEC)
        return [m async for m in manager.stream(sim_id)]

    try:
        messages = asyncio.run(go())
    finally:
        manager.shutdown()
    types = [m["type"] for m in messages]
    assert types.count("log") == 2
    assert "scope_batch" in types
    assert types[-1] == "completed"


def _handler(sink: list[dict[str, Any]] | None = None) -> RunLogHandler:
    out = sink if sink is not None else []
    return RunLogHandler(thread_id=threading.get_ident(), current_t=lambda: 1.5, sink=out.append)


def _record(
    name: str, level: int, msg: str = "m", *, thread: int | None = None
) -> logging.LogRecord:
    rec = logging.LogRecord(name, level, __file__, 1, msg, None, None)
    rec.thread = threading.get_ident() if thread is None else thread
    return rec


class TestFilter:
    @pytest.mark.parametrize(
        ("name", "level", "accepted"),
        [
            ("flode_ws.demo", logging.INFO, True),
            ("flode_ws", logging.INFO, True),
            ("flode_ws.demo", logging.DEBUG, False),
            ("flode.core.block", logging.WARNING, True),
            ("flode.core.block", logging.INFO, False),
            ("uvicorn.error", logging.ERROR, False),
            ("flode_wsx", logging.ERROR, False),
        ],
    )
    def test_logger_and_level(self, name: str, level: int, accepted: bool) -> None:
        assert _handler().filter(_record(name, level)) is accepted

    def test_other_threads_are_ignored(self) -> None:
        other = threading.get_ident() + 1
        assert _handler().filter(_record("flode_ws.demo", logging.ERROR, thread=other)) is False


class TestEmit:
    def test_entry_shape(self) -> None:
        out: list[dict[str, Any]] = []
        _handler(out).emit(_record("flode_ws.demo", logging.INFO, "hello"))
        assert out == [{"t": 1.5, "level": "INFO", "logger": "flode_ws.demo", "message": "hello"}]

    def test_entries_are_capped(self) -> None:
        out: list[dict[str, Any]] = []
        handler = _handler(out)
        for _ in range(RUN_LOG_MAX_ENTRIES + 5):
            handler.emit(_record("flode_ws.demo", logging.INFO))
        assert len(out) == RUN_LOG_MAX_ENTRIES
        assert len(handler.entries) == RUN_LOG_MAX_ENTRIES
        assert handler.dropped == 5

    def test_long_message_is_truncated(self) -> None:
        out: list[dict[str, Any]] = []
        _handler(out).emit(
            _record("flode_ws.demo", logging.INFO, "x" * (RUN_LOG_MAX_MESSAGE_CHARS + 10))
        )
        assert len(out[0]["message"]) == RUN_LOG_MAX_MESSAGE_CHARS

    def test_exception_is_summarized(self) -> None:
        out: list[dict[str, Any]] = []
        try:
            raise ValueError("bad")
        except ValueError:
            import sys

            rec = _record("flode.core.block", logging.ERROR, "close failed")
            rec.exc_info = sys.exc_info()
        _handler(out).emit(rec)
        assert out[0]["message"] == "close failed: ValueError: bad"
