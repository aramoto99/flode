"""``MultiportSwitch`` の selector が NaN のときにドメイン例外で止まることの回帰テスト。

2026-09-14 発見: ``int(round(nan))`` が builtin ``ValueError: cannot convert float NaN
to integer`` を投げ、run 全体が flode の例外体系外のエラーで落ちていた
(``Switch`` は NaN の扱いを docstring で定義している)。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from flode import Simulator
from flode.blocks import Constant, Divide, MultiportSwitch, Scope
from flode.exceptions import BlockEvalError


@pytest.mark.parametrize("mode", ["clip", "error"])
def test_nan_selector_raises_block_eval_error(mode: str) -> None:
    blk = MultiportSwitch(n_choices=2, out_of_range_mode=mode, id="mps")  # type: ignore[arg-type]
    with pytest.raises(BlockEvalError, match="NaN"):
        blk.output(0.0, np.zeros(0), np.array([math.nan, 1.0, 2.0]))


def test_nan_selector_in_simulator_reports_block_id() -> None:
    sim = Simulator(t_end=0.02, dt=0.01)
    sim.add(Constant(value=0.0, id="zero"))
    sim.add(Divide(signs="*/", id="nan_src"))  # 0/0 = nan
    sim.add(Constant(value=1.0, id="one"))
    sim.add(Constant(value=2.0, id="two"))
    sim.add(MultiportSwitch(n_choices=2, id="mps"))
    sim.add(Scope(n_inputs=1, id="sc"))
    sim.connect("zero", "nan_src", dst_idx=0)
    sim.connect("zero", "nan_src", dst_idx=1)
    sim.connect("nan_src", "mps", dst_idx=0)
    sim.connect("one", "mps", dst_idx=1)
    sim.connect("two", "mps", dst_idx=2)
    sim.connect("mps", "sc")
    with pytest.raises(BlockEvalError) as info:
        sim.run()
    assert info.value.block_id == "mps"


def test_finite_selector_still_rounds_half_to_even() -> None:
    blk = MultiportSwitch(n_choices=3, id="mps")
    out = [
        blk.output(0.0, np.zeros(0), np.array([s, 10.0, 20.0, 30.0]))[0] for s in (0.5, 1.5, 2.5)
    ]
    assert out == [10.0, 30.0, 30.0]
