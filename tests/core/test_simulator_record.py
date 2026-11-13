"""Simulator の記録経路のテスト (ADR-0081 §論点 5-B)。

* ``record_v`` を持つブロックにはポートごとの値を平坦化せずに渡す (信号面 plan のある経路)
* ``record_on_sample_hits`` が真のブロックは自分のサンプル時刻でだけ記録する
* 既存の sink (Scope 等、``record_on_sample_hits`` 既定 False) は毎ステップのまま
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np
import numpy.typing as npt
import pytest

from flode import Block, Simulator
from flode.blocks import Constant, Ramp, Scope


class _FlatRecorder(Block):
    """``record`` だけを持つ sink (既存の Scope と同じ形)。

    スカラ (``output``) とベクトル (``output_v``) の両経路で動くよう両方を持つ。
    """

    _skip_dual_api_check: ClassVar[bool] = True

    def __init__(self, *, id: str, sample_time: float | None = None) -> None:
        super().__init__(id=id, n_inputs=1, n_outputs=0, sample_time=sample_time)
        self.got: list[tuple[float, npt.NDArray[Any]]] = []

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.zeros(0)

    def output_v(
        self, t: float, x: npt.NDArray[Any], u: tuple[npt.NDArray[Any], ...]
    ) -> tuple[npt.NDArray[Any], ...]:
        return ()

    def record(self, t: float, u: npt.NDArray[Any]) -> None:
        self.got.append((t, np.array(u, copy=True)))


class _HitRecorder(_FlatRecorder):
    record_on_sample_hits: ClassVar[bool] = True


class _PortRecorder(_FlatRecorder):
    """``record_v`` と ``record`` の両方を持つ sink。"""

    def __init__(self, *, id: str) -> None:
        super().__init__(id=id)
        self.got_v: list[tuple[float, tuple[npt.NDArray[Any], ...]]] = []

    def record_v(self, t: float, u: tuple[npt.NDArray[Any], ...]) -> None:
        self.got_v.append((t, tuple(np.array(p, copy=True) for p in u)))


def _run(sink: Block, *, source: Block, t_end: float = 0.04, dt: float = 0.01) -> None:
    sim = Simulator(t_end=t_end, dt=dt)
    sim.add(source)
    sim.add(sink)
    sim.connect(source.id, sink.id)
    sim.run()


class TestRecordOnSampleHits:
    def test_default_false_records_every_base_step(self) -> None:
        """既存の sink の挙動は不変 (離散 sample_time を持っていても毎ステップ)。"""
        rec = _FlatRecorder(id="rec", sample_time=0.02)
        _run(rec, source=Ramp(slope=1.0, id="r"))
        assert [t for t, _ in rec.got] == pytest.approx([0.0, 0.01, 0.02, 0.03, 0.04])

    def test_true_records_on_own_period(self) -> None:
        rec = _HitRecorder(id="rec", sample_time=0.02)
        _run(rec, source=Ramp(slope=1.0, id="r"))
        assert [t for t, _ in rec.got] == pytest.approx([0.0, 0.02, 0.04])

    def test_true_and_continuous_records_every_step(self) -> None:
        rec = _HitRecorder(id="rec")
        _run(rec, source=Ramp(slope=1.0, id="r"))
        assert len(rec.got) == 5

    def test_scope_is_unchanged(self) -> None:
        scope = Scope(n_inputs=1, id="sc")
        _run(scope, source=Ramp(slope=1.0, id="r"))
        assert scope.values.shape == (5, 1)


class TestRecordV:
    def test_record_v_receives_port_tuple_on_plan_path(self) -> None:
        rec = _PortRecorder(id="rec")
        rec.port_shapes_in = ((3,),)
        _run(rec, source=Constant(value=[1.0, 2.0, 3.0], id="c"), t_end=0.01)
        assert rec.got == []
        assert len(rec.got_v) == 2
        for _, ports in rec.got_v:
            assert len(ports) == 1
            np.testing.assert_allclose(ports[0], [1.0, 2.0, 3.0])

    def test_record_only_block_still_gets_flattened_values(self) -> None:
        rec = _FlatRecorder(id="rec")
        rec.port_shapes_in = ((2,),)
        _run(rec, source=Constant(value=[1.0, 2.0], id="c"), t_end=0.01)
        assert len(rec.got) == 2
        np.testing.assert_allclose(rec.got[0][1], [1.0, 2.0])
