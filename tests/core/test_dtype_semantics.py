"""SPEC-0028 AC-4: numpy ネイティブ意味論の固定 (§2.3)。

期待値は SPEC に書かれた具体値を**ハードコード** (numpy に問い合わせて生成しない
— numpy 側の意味論変化を検出するため)。原則モデル経由 (run()) で固定する。
"""

from __future__ import annotations

import numpy as np

from flode import Simulator
from flode.blocks.cast import Cast
from flode.blocks.mathops import Product, Sum
from flode.blocks.sinks import Scope
from flode.blocks.sources import Constant


def _run_sum(
    a_value: float, a_dtype: str, b_value: float, b_dtype: str
) -> tuple[str, float]:
    """2 定数を Sum した (予測 dtype, 記録値) を返すヘルパ。"""
    sim = Simulator(t_end=0.05, dt=0.01)
    a = sim.add(Constant(value=a_value, dtype=a_dtype, id="a"))
    b = sim.add(Constant(value=b_value, dtype=b_dtype, id="b"))
    s = sim.add(Sum(signs="++", id="s"))
    sc = sim.add(Scope(id="sc"))
    sim.connect(a, s, dst_idx=0)
    sim.connect(b, s, dst_idx=1)
    sim.connect(s, sc)
    res = sim.resolve_dtypes()
    sim.run()
    return res.out_dtype("s", 0), float(np.asarray(sc.values)[0, 0])


class TestNativeSemantics:
    def test_bool_plus_bool_is_logical_or(self) -> None:
        # (F3): bool + bool == True (記録は float64 なので 1.0)。
        sim = Simulator(t_end=0.05, dt=0.01)
        c1 = sim.add(Constant(value=1.0, id="c1"))
        k1 = sim.add(Cast(dtype="bool", id="k1"))
        c2 = sim.add(Constant(value=1.0, id="c2"))
        k2 = sim.add(Cast(dtype="bool", id="k2"))
        s = sim.add(Sum(signs="++", id="s"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(c1, k1)
        sim.connect(c2, k2)
        sim.connect(k1, s, dst_idx=0)
        sim.connect(k2, s, dst_idx=1)
        sim.connect(s, sc)
        res = sim.resolve_dtypes()
        assert res.out_dtype("s", 0) == "bool"
        sim.run()
        assert float(np.asarray(sc.values)[0, 0]) == 1.0  # 2.0 ではない

    def test_int32_wrap_around(self) -> None:
        dtype, val = _run_sum(2**31 - 1, "int32", 1, "int32")
        assert dtype == "int32"
        assert val == -2147483648.0  # wrap (D-3)

    def test_uint8_wrap_around(self) -> None:
        dtype, val = _run_sum(255, "uint8", 1, "uint8")
        assert dtype == "uint8"
        assert val == 0.0

    def test_int32_plus_int64_promotes_to_int64(self) -> None:
        dtype, val = _run_sum(1, "int32", 2, "int64")
        assert dtype == "int64"
        assert val == 3.0

    def test_bool_plus_uint8_promotes_to_uint8(self) -> None:
        sim = Simulator(t_end=0.05, dt=0.01)
        c1 = sim.add(Constant(value=1.0, id="c1"))
        k1 = sim.add(Cast(dtype="bool", id="k1"))
        c2 = sim.add(Constant(value=254, dtype="uint8", id="c2"))
        s = sim.add(Sum(signs="++", id="s"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(c1, k1)
        sim.connect(k1, s, dst_idx=0)
        sim.connect(c2, s, dst_idx=1)
        sim.connect(s, sc)
        res = sim.resolve_dtypes()
        assert res.out_dtype("s", 0) == "uint8"
        sim.run()
        assert float(np.asarray(sc.values)[0, 0]) == 255.0

    def test_int_product_wraps_in_declared_dtype(self) -> None:
        # int32 の乗算オーバーフロー: 65536 * 65536 = 2^32 → int32 wrap で 0
        sim = Simulator(t_end=0.05, dt=0.01)
        a = sim.add(Constant(value=65536, dtype="int32", id="a"))
        b = sim.add(Constant(value=65536, dtype="int32", id="b"))
        p = sim.add(Product(n_inputs=2, id="p"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(a, p, dst_idx=0)
        sim.connect(b, p, dst_idx=1)
        sim.connect(p, sc)
        sim.run()
        assert float(np.asarray(sc.values)[0, 0]) == 0.0

    def test_integer_zero_division_semantics_documented(self) -> None:
        # §2.3: 整数の floor 除算 0 割りは 0 (+ RuntimeWarning)。flode の builtin
        # には整数除算ブロックが無いため (Divide は float_out)、意味論そのものを
        # numpy レベルで固定する (SPEC の表の値のハードコード)
        with np.errstate(divide="ignore"):
            out = np.int64(1) // np.int64(0)
        assert int(out) == 0
