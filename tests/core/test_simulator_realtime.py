"""SPEC-0034 R-1〜R-3 / ADR-0082 §(2): Simulator の実時間同期のテスト。"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from flode import Block
from flode.blocks import Constant, Scope
from flode.core.simulator import Simulator
from flode.exceptions import ModelLoadError


def _model(*, realtime: bool, t_end: float = 0.3, dt: float = 0.1) -> Simulator:
    sim = Simulator(t_end=t_end, dt=dt, realtime=realtime)
    sim.add(Constant(value=1.0, id="c"))
    sim.add(Scope(id="scope"))
    sim.connect("c", "scope")
    return sim


class _Slow(Block):
    """最初の 1 回だけ ``delay`` 秒かかる出力ブロック (遅れの再現用)。"""

    def __init__(self, delay: float) -> None:
        super().__init__(n_inputs=0, n_outputs=1)
        self._delay = delay
        self._slept = False
        self._params = {}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        if not self._slept:
            self._slept = True
            time.sleep(self._delay)
        return np.array([0.0])


class TestPacing:
    def test_realtime_takes_at_least_t_end(self) -> None:
        sim = _model(realtime=True, t_end=0.3)
        t0 = time.monotonic()
        sim.run()
        assert time.monotonic() - t0 >= 0.3 - 0.02
        assert len(sim.get_block("scope").times) == 4

    def test_default_is_as_fast_as_possible(self) -> None:
        sim = _model(realtime=False, t_end=5.0)
        t0 = time.monotonic()
        sim.run()
        assert time.monotonic() - t0 < 2.0

    def test_no_fast_forward_after_falling_behind(self) -> None:
        """遅れたら基準を付け替える (= 遅れた分を早送りで取り戻さない)。"""
        sim = Simulator(t_end=0.4, dt=0.1, realtime=True)
        sim.add(_Slow(delay=0.3))
        t0 = time.monotonic()
        sim.run()
        elapsed = time.monotonic() - t0
        # t=0 の出力で 0.3 s 遅れ → t=0.1 で基準を付け替え、残り t=0.1→0.4 (0.3 s) を
        # 実時間で進める (計 ~0.6 s)。早送りで取り戻すなら壁時計 0.4 s 付近で終わる
        assert elapsed >= 0.3 + 0.3 - 0.05

    def test_stop_interrupts_waiting(self) -> None:
        sim = _model(realtime=True, t_end=60.0, dt=10.0)
        timer = threading.Timer(0.2, sim.request_stop)
        timer.start()
        t0 = time.monotonic()
        sim.run()
        timer.join()
        assert time.monotonic() - t0 < 2.0
        assert sim.is_stopped

    def test_huge_wait_does_not_overflow(self) -> None:
        """巨大な dt でも待ちが TIMEOUT_MAX で丸められ、停止要求で抜ける。"""
        sim = _model(realtime=True, t_end=1e12, dt=1e11)
        timer = threading.Timer(0.2, sim.request_stop)
        timer.start()
        sim.run()
        timer.join()
        assert sim.is_stopped

    def test_origin_excludes_setup_time(self) -> None:
        """基準は最初のステップで決まる (run() 前の経過時間を遅れとして数えない)。"""
        sim = _model(realtime=True, t_end=0.2)
        sim._realtime_origin = time.monotonic() - 100.0  # 前回の値が残っていても
        t0 = time.monotonic()
        sim.run()
        assert time.monotonic() - t0 >= 0.2 - 0.02


class TestPersistence:
    def test_true_is_saved_and_loaded(self, tmp_path: Path) -> None:
        path = tmp_path / "m.flw.json"
        _model(realtime=True).save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["simulator"]["realtime"] is True
        assert Simulator.load(path).realtime is True

    def test_false_is_not_written(self, tmp_path: Path) -> None:
        path = tmp_path / "m.flw.json"
        _model(realtime=False).save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "realtime" not in data["simulator"]
        assert Simulator.load(path).realtime is False

    @pytest.mark.parametrize("bad", ["yes", 1, None])
    def test_non_bool_is_rejected(self, tmp_path: Path, bad: object) -> None:
        path = tmp_path / "m.flw.json"
        _model(realtime=False).save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["simulator"]["realtime"] = bad
        with pytest.raises(ModelLoadError, match="realtime"):
            Simulator.from_dict(data)
