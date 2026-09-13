"""``Divide`` の 0 除算が nan / inf を伝播する (例外にしない) ことの回帰テスト。

2026-09-13 発見: ``Divide.output`` が Python の ``float`` 演算で除算していたため、
除数 0 で ``ZeroDivisionError`` になり run 全体が落ちていた。docstring と
ADR-0053 §論点 6 (定義域外は nan / inf 伝播で統一、``MathFunction("reciprocal")``
は ``np.divide`` 経由で +inf) に反する。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from flode import Simulator
from flode.blocks import Constant, Divide, Scope


def _divide(signs: str, *values: float) -> float:
    blk = Divide(signs=signs)
    return float(blk.output(0.0, np.zeros(0), np.array(values, dtype=float))[0])


@pytest.mark.parametrize(
    ("signs", "values", "check"),
    [
        ("*/", (1.0, 0.0), lambda y: math.isinf(y) and y > 0),
        ("*/", (-1.0, 0.0), lambda y: math.isinf(y) and y < 0),
        ("*/", (0.0, 0.0), math.isnan),
        ("/", (0.0,), lambda y: math.isinf(y) and y > 0),
        ("**/", (2.0, 3.0, 0.0), lambda y: math.isinf(y) and y > 0),
        ("*/", (6.0, 3.0), lambda y: y == 2.0),
    ],
)
def test_divide_by_zero_propagates_inf_or_nan(signs: str, values: tuple[float, ...], check) -> None:
    assert check(_divide(signs, *values))


def test_divide_by_zero_inside_simulator_does_not_abort_run() -> None:
    sim = Simulator(t_end=0.02, dt=0.01)
    sim.add(Constant(value=1.0, id="a"))
    sim.add(Constant(value=0.0, id="b"))
    sim.add(Divide(signs="*/", id="d"))
    sim.add(Scope(n_inputs=1, id="sc"))
    sim.connect("a", "d", dst_idx=0)
    sim.connect("b", "d", dst_idx=1)
    sim.connect("d", "sc")
    sim.run()
    assert np.all(np.isposinf(sim.get_block("sc").values[:, 0]))


def test_divide_with_int_dtype_inputs_is_float64_division() -> None:
    """Divide は float_out (SPEC-0028 分類) なので int 入力でも float64 の真の除算。"""
    sim = Simulator(t_end=0.01, dt=0.01)
    sim.add(Constant(value=7, dtype="int32", id="a"))
    sim.add(Constant(value=2, dtype="int32", id="b"))
    sim.add(Constant(value=0, dtype="int64", id="z"))
    sim.add(Divide(signs="*/", id="d"))
    sim.add(Divide(signs="*/", id="dz"))
    sim.add(Scope(n_inputs=2, id="sc"))
    sim.connect("a", "d", dst_idx=0)
    sim.connect("b", "d", dst_idx=1)
    sim.connect("a", "dz", dst_idx=0)
    sim.connect("z", "dz", dst_idx=1)
    sim.connect("d", "sc", dst_idx=0)
    sim.connect("dz", "sc", dst_idx=1)
    sim.run()
    y = sim.get_block("sc").values[0]
    assert y[0] == 3.5
    assert np.isposinf(y[1])
