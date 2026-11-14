"""ADR-0083 §(2): 実行の終わりに ``Block.close()`` が必ず呼ばれることのテスト。"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from flode import Block
from flode.blocks import Constant, Scope
from flode.core.simulator import Simulator
from flode.subsystems import Inport, Outport, Subsystem


class _Tracked(Block):
    """reset / close の呼び出しを記録する 1 入出力ブロック。"""

    def __init__(
        self,
        *,
        id: str | None = None,
        fail_output: bool = False,
        fail_close: bool = False,
    ) -> None:
        super().__init__(id=id, n_inputs=1, n_outputs=1)
        self._params = {}
        self.events: list[str] = []
        self._fail_output = fail_output
        self._fail_close = fail_close

    def reset(self) -> None:
        self.events.append("reset")

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        if self._fail_output:
            raise RuntimeError("boom")
        return np.asarray(u, dtype=float)

    def close(self) -> None:
        self.events.append("close")
        if self._fail_close:
            raise RuntimeError("close failed")


def _chain(*tracked: _Tracked, t_end: float = 0.3) -> Simulator:
    sim = Simulator(t_end=t_end, dt=0.1)
    sim.add(Constant(value=1.0, id="c"))
    prev = "c"
    for b in tracked:
        sim.add(b)
        sim.connect(prev, b.id)
        prev = b.id
    sim.add(Scope(id="scope"))
    sim.connect(prev, "scope")
    return sim


def test_close_called_after_completed_run() -> None:
    a = _Tracked(id="a")
    _chain(a).run()
    assert a.events == ["reset", "close"]


def test_close_called_when_run_fails() -> None:
    a = _Tracked(id="a", fail_output=True)
    with pytest.raises(RuntimeError, match="boom"):
        _chain(a).run()
    assert a.events == ["reset", "close"]


def test_close_called_when_stopped() -> None:
    a = _Tracked(id="a")
    sim = _chain(a, t_end=float("inf"))
    sim.on_step_callback = lambda t, t_end: t < 0.2  # False で停止
    sim.run()
    assert a.events == ["reset", "close"]


def test_failing_close_does_not_skip_others(caplog: pytest.LogCaptureFixture) -> None:
    a = _Tracked(id="a", fail_close=True)
    b = _Tracked(id="b")
    with caplog.at_level(logging.ERROR, logger="flode.core.block"):
        _chain(a, b).run()  # 後片付けの失敗は実行の失敗にしない
    assert a.events[-1] == "close"
    assert b.events[-1] == "close"
    assert "close() of block 'a'" in caplog.text


def test_close_reaches_blocks_inside_subsystem() -> None:
    inner = _Tracked(id="inner")
    sub = Subsystem(id="sub")
    sub.add(Inport(port_idx=0, id="in1"))
    sub.add(inner)
    sub.add(Outport(port_idx=0, id="out1"))
    sub.connect("in1", "inner")
    sub.connect("inner", "out1")
    sim = Simulator(t_end=0.2, dt=0.1)
    sim.add(Constant(value=1.0, id="c"))
    sim.add(sub)
    sim.add(Scope(id="scope"))
    sim.connect("c", "sub")
    sim.connect("sub", "scope")
    sim.run()
    assert inner.events == ["reset", "close"]


class _FailingReset(_Tracked):
    def reset(self) -> None:
        self.events.append("reset")
        raise RuntimeError("reset failed")


def test_reset_failure_closes_only_started_blocks() -> None:
    a = _Tracked(id="a")
    b = _FailingReset(id="b")
    c = _Tracked(id="third")
    with pytest.raises(RuntimeError, match="reset failed"):
        _chain(a, b, c).run()
    assert a.events == ["reset", "close"]
    assert b.events == ["reset", "close"]  # 途中まで開いたかもしれないので閉じる
    assert c.events == []  # reset していないブロックは閉じない


def test_default_close_is_noop() -> None:
    Constant(value=1.0).close()
