"""``Fcn`` が整数 dtype の入力でも float64 で式を評価することの回帰テスト。

2026-09-13 発見: SM-D (SPEC-0028) で ``Fcn`` は ``float_out`` (出力 float64) に
分類されているが、入力 ``u`` を dtype のまま名前空間に注入していたため、
``uint8`` 入力の ``u[0]+u[1]`` が numpy の uint8 演算で wrap し (250+10 → 4)、
出力 dtype は float64 なのに値だけが「整数演算の結果」になっていた。
"""

from __future__ import annotations

import numpy as np

from flode import Simulator
from flode.blocks import Constant, Fcn, Scope


def _run(expr: str, a, b, *, dtype: str) -> float:
    sim = Simulator(t_end=0.01, dt=0.01)
    sim.add(Constant(value=a, dtype=dtype, id="a"))
    sim.add(Constant(value=b, dtype=dtype, id="b"))
    sim.add(Fcn(expression=expr, n_inputs=2, id="f"))
    sim.add(Scope(n_inputs=1, id="sc"))
    sim.connect("a", "f", dst_idx=0)
    sim.connect("b", "f", dst_idx=1)
    sim.connect("f", "sc")
    sim.run()
    return float(sim.get_block("sc").values[0, 0])


def test_fcn_uint8_addition_does_not_wrap() -> None:
    assert _run("u[0]+u[1]", 250, 10, dtype="uint8") == 260.0


def test_fcn_int32_division_is_true_division() -> None:
    assert _run("u[0]/u[1]", 7, 2, dtype="int32") == 3.5


def test_fcn_int32_overflow_does_not_wrap() -> None:
    assert _run("u[0]*u[1]", 2**30, 4, dtype="int32") == float(2**32)


def test_fcn_float_inputs_unchanged() -> None:
    assert _run("u[0]*u[1] + 1", 1.5, 2.0, dtype="auto") == 4.0


def test_fcn_u_is_float64_array_inside_expression() -> None:
    """u は float64 配列として見える (整数 dtype の伝搬は Fcn の境界で止まる)。"""
    sim = Simulator(t_end=0.01, dt=0.01)
    sim.add(Constant(value=3, dtype="int64", id="a"))
    sim.add(Fcn(expression="u[0] / 2", n_inputs=1, id="f"))
    sim.add(Scope(n_inputs=1, id="sc"))
    sim.connect("a", "f")
    sim.connect("f", "sc")
    res = sim.resolve_dtypes()
    assert str(res.ports[("f", "out", 0)]) == "float64"
    sim.run()
    assert sim.get_block("sc").values[0, 0] == 1.5
    assert isinstance(np.float64(1.5), float)
