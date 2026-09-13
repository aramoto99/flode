"""永続化できないユーザーブロック (``@block`` を __main__ で定義した等) を Subsystem に
入れても **実行はできる** ことの回帰テスト。

2026-09-13 発見: ``Subsystem._build`` が save/load 用に内部ブロックの ``to_dict()`` を
先読みしていたため、``__main__`` 定義の ``@block`` ブロックを Subsystem に入れると
``run()`` の構造解析時点で ``ModelSerializationError`` になっていた (ルート直下なら
run はでき、save だけが落ちる)。永続化の失敗は save 時に報告されるべき。
"""

from __future__ import annotations

import numpy as np
import pytest

from flode import Inport, Outport, Simulator, Subsystem, block
from flode.blocks import Constant, Scope
from flode.exceptions import ModelSerializationError


def _main_defined_gain(k: float):
    @block
    def local_gain(t: float, u: float) -> float:
        return k * u

    # __main__ で定義されたユーザーブロックを模す (to_dict が拒否する条件)
    local_gain.__module__ = "__main__"
    return local_gain


def _build_sim() -> Simulator:
    cls = _main_defined_gain(3.0)
    sub = Subsystem(id="sub")
    sub.add(Inport(port_idx=0, id="i"))
    sub.add(cls(id="g"))
    sub.add(Outport(port_idx=0, id="o"))
    sub.connect("i", "g")
    sub.connect("g", "o")
    sim = Simulator(t_end=0.05, dt=0.01)
    sim.add(Constant(value=2.0, id="c"))
    sim.add(sub)
    sim.add(Scope(n_inputs=1, id="sc"))
    sim.connect("c", "sub")
    sim.connect("sub", "sc")
    return sim


def test_unpersistable_inner_block_can_run() -> None:
    sim = _build_sim()
    sim.run()
    np.testing.assert_allclose(sim.get_block("sc").values[:, 0], 6.0)


def test_unpersistable_inner_block_still_fails_at_save(tmp_path) -> None:
    sim = _build_sim()
    sim.run()
    with pytest.raises(ModelSerializationError, match="__main__"):
        sim.save(tmp_path / "m.flw.json")
