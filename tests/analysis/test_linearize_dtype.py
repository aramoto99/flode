"""SPEC-0028 AC-8 / Q10: 非 float64 モデルの解析 API 明示拒否。"""

from __future__ import annotations

import pytest

from flode import Simulator, linearize
from flode.blocks.cast import Cast
from flode.blocks.continuous import Integrator
from flode.blocks.mathops import Gain, Sum
from flode.blocks.sources import Constant
from flode.exceptions import BlockSpecError


def _feedback_model(*, declare_int: bool, declare_float: bool = False) -> Simulator:
    """1 次系 x' = -x + u の閉ループ (linearize 可能な連続状態つき)。"""
    sim = Simulator(t_end=1.0, dt=0.01)
    c = sim.add(
        Constant(value=1.0, dtype="int32", id="c") if declare_int else Constant(value=1.0, id="c")
    )
    s = sim.add(Sum(signs="+-", id="s"))
    integ = sim.add(Integrator(x0=0.0, id="integ"))
    g = sim.add(Gain(k=1.0, id="g"))
    sim.connect(c, s, dst_idx=0)
    sim.connect(g, s, dst_idx=1)
    sim.connect(s, integ)
    sim.connect(integ, g)
    if declare_float:
        sim.add(Cast(dtype="float64", id="marker"))
    return sim


class TestLinearizeDtypeRejection:
    def test_non_float64_model_is_rejected(self) -> None:
        sim = _feedback_model(declare_int=True)
        with pytest.raises(BlockSpecError, match="non-float64"):
            linearize(sim)

    def test_error_message_suggests_cast(self) -> None:
        sim = _feedback_model(declare_int=True)
        with pytest.raises(BlockSpecError, match="Cast\\(dtype='float64'\\)"):
            linearize(sim)

    def test_undeclared_model_still_linearizes(self) -> None:
        sim = _feedback_model(declare_int=False)
        ls = linearize(sim)
        assert ls.A.shape == (1, 1)

    def test_all_float64_declared_model_passes(self) -> None:
        # エッジケース表: 全 float64 宣言なら non_float_ports == 0 で通る
        sim = _feedback_model(declare_int=False, declare_float=True)
        ls = linearize(sim)
        assert ls.A.shape == (1, 1)

    def test_simulator_wrapper_also_rejects(self) -> None:
        sim = _feedback_model(declare_int=True)
        with pytest.raises(BlockSpecError, match="non-float64"):
            sim.linearize()
