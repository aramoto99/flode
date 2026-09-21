"""ADR-0079 Stage 1: 要素ごと演算ブロック (17 クラス) のテンソル対応テスト。

- AC-11: スカラ入力で `output` と `output_v` (= `_kernel`) が bit-identical
- AC-4': `Demux → 演算 × n → Mux` 版とベクトル版が bit-identical (要素ごと 3 モデル)
- AC-8 / AC-9: `Gain` 既定 (elementwise、スカラ k) の `_params` は不変、
  非既定 `multiplication` のみ書き出す。行列モードの数値 (allclose) と build 時の
  次元エラー
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from flode import Simulator
from flode.blocks import (
    Abs,
    Add,
    Cast,
    CompareToConstant,
    CompareToZero,
    Constant,
    DeadZone,
    Demux,
    Divide,
    Gain,
    LogicalOperator,
    MathFunction,
    MinMax,
    Mux,
    Product,
    RelationalOperator,
    Rounding,
    Saturation,
    Scope,
    Sign,
    Sum,
    TrigFunction,
)
from flode.blocks._elementwise import ElementwiseMixin
from flode.core.block import Block
from flode.exceptions import BlockSpecError

_X = np.zeros(0)

# (factory, 入力ポートごとの代表値の列)。値は演算ごとに定義域内 (nan/inf は別テスト)。
_CASES: list[tuple[str, Any, list[float]]] = [
    ("Gain", lambda: Gain(k=2.5), [1.25]),
    ("Sum", lambda: Sum(signs="+-+"), [1.5, 2.25, -0.75]),
    ("Add", lambda: Add(signs="++"), [0.1, 0.2]),
    ("Product", lambda: Product(n_inputs=3), [1.5, -2.0, 0.3]),
    ("Divide", lambda: Divide(signs="*/"), [1.0, 3.0]),
    ("Divide_recip", lambda: Divide(signs="/"), [7.0]),
    ("Saturation", lambda: Saturation(lower=-1.0, upper=1.0), [1.7]),
    ("DeadZone", lambda: DeadZone(lower=-0.5, upper=0.5), [0.9]),
    ("Abs", lambda: Abs(), [-3.3]),
    ("Sign", lambda: Sign(), [-0.0001]),
    ("MinMax", lambda: MinMax(operator="max", n_inputs=3), [1.0, 5.0, 2.0]),
    ("MathFunction_exp", lambda: MathFunction(function="exp"), [0.7]),
    ("MathFunction_pow", lambda: MathFunction(function="pow"), [1.3, 2.7]),
    ("TrigFunction_sin", lambda: TrigFunction(function="sin"), [0.4]),
    ("TrigFunction_atan2", lambda: TrigFunction(function="atan2"), [1.0, -2.0]),
    ("Rounding", lambda: Rounding(mode="floor"), [2.7]),
    ("Cast", lambda: Cast(dtype="int32"), [2.7]),
    ("RelationalOperator", lambda: RelationalOperator(operator="<"), [1.0, 2.0]),
    ("LogicalOperator", lambda: LogicalOperator(operator="XOR", n_inputs=3), [1.0, 0.0, 1.0]),
    ("CompareToConstant", lambda: CompareToConstant(op=">", const=0.5), [0.7]),
    ("CompareToZero", lambda: CompareToZero(op="!="), [0.0]),
]


class TestScalarParity:
    """AC-11: 17 クラスの output と output_v がスカラ入力で bit-identical。"""

    @pytest.mark.parametrize("case", _CASES, ids=[c[0] for c in _CASES])
    def test_output_v_equals_output_bitwise(self, case: tuple[str, Any, list[float]]) -> None:
        _name, factory, values = case
        blk = factory()
        assert isinstance(blk, ElementwiseMixin)
        u_1d = np.array(values, dtype=float)
        y_a = blk.output(0.0, _X, u_1d)
        y_v = blk.output_v(0.0, _X, tuple(np.asarray(v) for v in values))
        assert len(y_v) == 1
        assert np.asarray(y_v[0]).shape == ()
        assert np.asarray(y_v[0]).dtype == np.asarray(y_a[0]).dtype
        assert np.array_equal(np.asarray(y_v[0]), np.asarray(y_a[0]))

    def test_mixin_subclass_has_only_output_in_leaf_dict(self) -> None:
        # Block.__init__ の dual-override 検査に掛からない設計 (U1)
        for _name, factory, _values in _CASES:
            cls = type(factory())
            assert "output" in cls.__dict__
            assert "output_v" not in cls.__dict__
            assert "_kernel" in cls.__dict__

    def test_all_seventeen_classes_are_covered(self) -> None:
        covered = {type(f()).__name__ for _n, f, _v in _CASES}
        expected = {
            "Gain", "Sum", "Add", "Product", "Divide", "Saturation", "DeadZone", "Abs", "Sign",
            "MinMax", "MathFunction", "TrigFunction", "Rounding", "Cast", "RelationalOperator",
            "LogicalOperator", "CompareToConstant", "CompareToZero",
        }  # fmt: skip
        assert covered == expected


# ---------------------------------------------------------------------------
# AC-4': Demux 展開版とベクトル版の bit-identical
# ---------------------------------------------------------------------------


def _sources(sim: Simulator, values: list[float], prefix: str) -> Mux:
    m = sim.add(Mux(n=len(values), id=f"{prefix}_mux"))
    for i, v in enumerate(values):
        c = sim.add(Constant(value=v, id=f"{prefix}_c{i}"))
        sim.connect(c, m, dst_idx=i)
    return m


def _run_scalar_expanded(
    build_chain: Any, values_a: list[float], values_b: list[float]
) -> np.ndarray:
    """Demux → 演算 × n → Mux → Scope で各要素をスカラとして計算する。"""
    sim = Simulator(t_end=0.02, dt=0.01)
    n = len(values_a)
    ma = _sources(sim, values_a, "a")
    mb = _sources(sim, values_b, "b")
    da = sim.add(Demux(n=n, id="da"))
    db = sim.add(Demux(n=n, id="db"))
    out = sim.add(Mux(n=n, id="out"))
    sc = sim.add(Scope(id="sc"))
    sim.connect(ma, da)
    sim.connect(mb, db)
    for i in range(n):
        last = build_chain(sim, f"e{i}", (da, i), (db, i))
        sim.connect(last, out, dst_idx=i)
    sim.connect(out, sc)
    sim.run()
    return np.asarray(sc.values)


def _run_vector(build_chain: Any, values_a: list[float], values_b: list[float]) -> np.ndarray:
    sim = Simulator(t_end=0.02, dt=0.01)
    ma = _sources(sim, values_a, "a")
    mb = _sources(sim, values_b, "b")
    sc = sim.add(Scope(id="sc"))
    last = build_chain(sim, "v", (ma, 0), (mb, 0))
    sim.connect(last, sc)
    sim.run()
    return np.asarray(sc.values)


def _chain_gain_sum_sat(
    sim: Simulator, p: str, a: tuple[Block, int], b: tuple[Block, int]
) -> Block:
    g = sim.add(Gain(k=1.5, id=f"{p}_g"))
    s = sim.add(Sum(signs="+-", id=f"{p}_s"))
    sat = sim.add(Saturation(lower=-2.0, upper=2.0, id=f"{p}_sat"))
    sim.connect(a[0], g, src_idx=a[1])
    sim.connect(g, s, dst_idx=0)
    sim.connect(b[0], s, src_idx=b[1], dst_idx=1)
    sim.connect(s, sat)
    return sat


def _chain_product_trig_deadzone(
    sim: Simulator, p: str, a: tuple[Block, int], b: tuple[Block, int]
) -> Block:
    pr = sim.add(Product(n_inputs=2, id=f"{p}_pr"))
    tr = sim.add(TrigFunction(function="sin", id=f"{p}_tr"))
    dz = sim.add(DeadZone(lower=-0.1, upper=0.1, id=f"{p}_dz"))
    sim.connect(a[0], pr, src_idx=a[1], dst_idx=0)
    sim.connect(b[0], pr, src_idx=b[1], dst_idx=1)
    sim.connect(pr, tr)
    sim.connect(tr, dz)
    return dz


def _chain_compare_logic_round(
    sim: Simulator, p: str, a: tuple[Block, int], b: tuple[Block, int]
) -> Block:
    rel = sim.add(RelationalOperator(operator=">", id=f"{p}_rel"))
    cz = sim.add(CompareToZero(op="!=", id=f"{p}_cz"))
    lo = sim.add(LogicalOperator(operator="OR", n_inputs=2, id=f"{p}_lo"))
    rd = sim.add(Rounding(mode="round", id=f"{p}_rd"))
    sim.connect(a[0], rel, src_idx=a[1], dst_idx=0)
    sim.connect(b[0], rel, src_idx=b[1], dst_idx=1)
    sim.connect(b[0], cz, src_idx=b[1])
    sim.connect(rel, lo, dst_idx=0)
    sim.connect(cz, lo, dst_idx=1)
    sim.connect(lo, rd)
    return rd


_A = [0.125, -1.5, 2.75, 0.0]
_B = [1.0, 0.5, -0.25, 3.0]


class TestVectorEqualsExpanded:
    @pytest.mark.parametrize(
        "chain",
        [_chain_gain_sum_sat, _chain_product_trig_deadzone, _chain_compare_logic_round],
        ids=["gain_sum_sat", "product_trig_deadzone", "compare_logic_round"],
    )
    def test_bit_identical(self, chain: Any) -> None:
        expanded = _run_scalar_expanded(chain, _A, _B)
        vector = _run_vector(chain, _A, _B)
        assert expanded.shape == vector.shape == (3, 4)
        assert np.array_equal(expanded, vector)


# ---------------------------------------------------------------------------
# Gain: 行列モード / パラメータ永続化 (AC-8 / AC-9)
# ---------------------------------------------------------------------------


class TestGainMatrix:
    def test_default_params_unchanged(self) -> None:
        g = Gain(k=2.0)
        assert g._params == {"k": 2.0}
        assert isinstance(g.k, float)
        assert g.multiplication == "elementwise"

    def test_matrix_mode_is_written_only_when_non_default(self) -> None:
        g = Gain(k=[[1.0, 2.0]], multiplication="matrix-Ku")
        assert g._params["multiplication"] == "matrix-Ku"
        assert np.asarray(g._params["k"]).shape == (1, 2)
        assert "multiplication" not in Gain(k=[1.0, 2.0])._params

    def test_invalid_multiplication(self) -> None:
        with pytest.raises(BlockSpecError, match="multiplication"):
            Gain(k=[[1.0]], multiplication="outer")

    def test_matrix_mode_requires_array_k(self) -> None:
        with pytest.raises(BlockSpecError, match="requires a 1-D or 2-D k"):
            Gain(k=2.0, multiplication="matrix-Ku")

    def test_rank3_k_rejected(self) -> None:
        with pytest.raises(BlockSpecError, match="rank 3"):
            Gain(k=np.zeros((2, 2, 2)))

    def test_elementwise_vector_k(self) -> None:
        g = Gain(k=[1.0, 2.0, 3.0])
        (y,) = g.output_v(0.0, _X, (np.array([1.0, 1.0, 1.0]),))
        np.testing.assert_array_equal(y, [1.0, 2.0, 3.0])

    def test_matrix_ku_and_uk(self) -> None:
        k = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        u = np.array([1.0, 0.0, -1.0])
        (y,) = Gain(k=k, multiplication="matrix-Ku").output_v(0.0, _X, (u,))
        np.testing.assert_allclose(y, k @ u)
        u2 = np.array([1.0, 1.0])
        (y2,) = Gain(k=k, multiplication="matrix-uK").output_v(0.0, _X, (u2,))
        np.testing.assert_allclose(y2, u2 @ k)

    def test_dimension_mismatch_is_build_error(self) -> None:
        sim = Simulator(t_end=0.02, dt=0.01)
        m = _sources(sim, [1.0, 2.0, 3.0], "a")
        g = sim.add(Gain(k=[[1.0, 2.0]], multiplication="matrix-Ku", id="g"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(m, g)
        sim.connect(g, sc)
        with pytest.raises(BlockSpecError, match="inner dimensions"):
            sim.run()

    def test_unconnected_matrix_gain_input_is_build_error(self) -> None:
        """code-reviewer MUST (2026-09-21): 未接続入力 (= () に materialize) は行列積
        できないので build 時に拒否し、実行時の numpy ValueError にしない。"""
        from flode.blocks import Terminator

        for mode in ("matrix-Ku", "matrix-uK"):
            sim = Simulator(t_end=0.02, dt=0.01)
            g = sim.add(Gain(k=[[1.0, 2.0], [3.0, 4.0]], multiplication=mode, id="g"))
            term = sim.add(Terminator(id="term"))
            sim.connect(g, term)
            with pytest.raises(BlockSpecError, match="inner dimensions"):
                sim.run()

    def test_matrix_kernel_rejects_scalar_directly(self) -> None:
        g = Gain(k=[[1.0, 2.0]], multiplication="matrix-Ku", id="g")
        with pytest.raises(BlockSpecError, match="needs a vector"):
            g.output_v(0.0, _X, (np.asarray(1.0),))

    def test_elementwise_k_shape_mismatch_is_build_error(self) -> None:
        sim = Simulator(t_end=0.02, dt=0.01)
        m = _sources(sim, [1.0, 2.0, 3.0], "a")
        g = sim.add(Gain(k=[1.0, 2.0], id="g"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(m, g)
        sim.connect(g, sc)
        with pytest.raises(BlockSpecError, match="match the input shape"):
            sim.run()

    def test_matrix_gain_round_trip(self, tmp_path: Any) -> None:
        sim = Simulator(t_end=0.02, dt=0.01)
        m = _sources(sim, [1.0, 2.0, 3.0], "a")
        g = sim.add(Gain(k=[[1.0, 0.0, 0.0], [0.0, 0.0, 1.0]], multiplication="matrix-Ku", id="g"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(m, g)
        sim.connect(g, sc)
        path = tmp_path / "gain.flw.json"
        sim.save(path)
        loaded = Simulator.load(path)
        g2 = loaded.get_block("g")
        assert g2.multiplication == "matrix-Ku"
        np.testing.assert_array_equal(np.asarray(g2.k), np.asarray(g.k))
        loaded.run()
        np.testing.assert_allclose(np.asarray(loaded.get_block("sc").values)[0], [1.0, 3.0])

    def test_scalar_gain_still_takes_step_path(self) -> None:
        """AC-8: スカラ k の Gain は shape 起点にならない。"""
        sim = Simulator(t_end=0.02, dt=0.01)
        c = sim.add(Constant(value=1.0))
        g = sim.add(Gain(k=2.0))
        sim.connect(c, g)
        assert sim._is_sm_a_mode() is True


# ---------------------------------------------------------------------------
# nan / dtype 伝播の要素ごと版
# ---------------------------------------------------------------------------


class TestKernelSemantics:
    def test_sign_and_deadzone_treat_nan_like_scalar_path(self) -> None:
        u = (np.array([np.nan, 2.0, -2.0]),)
        (y,) = Sign().output_v(0.0, _X, u)
        np.testing.assert_array_equal(y, [0.0, 1.0, -1.0])
        (y2,) = DeadZone(lower=-1.0, upper=1.0).output_v(0.0, _X, u)
        np.testing.assert_array_equal(y2, [0.0, 1.0, -1.0])

    def test_divide_propagates_inf_without_raising(self) -> None:
        (y,) = Divide(signs="*/").output_v(0.0, _X, (np.array([1.0, 2.0]), np.array([0.0, 4.0])))
        assert np.isinf(y[0]) and y[1] == 0.5

    def test_integer_dtype_is_preserved_in_sum_and_product(self) -> None:
        a = np.array([1, 2], dtype=np.int64)
        b = np.array([3, 4], dtype=np.int64)
        (s,) = Sum(signs="++").output_v(0.0, _X, (a, b))
        (p,) = Product(n_inputs=2).output_v(0.0, _X, (a, b))
        assert s.dtype == np.int64 and p.dtype == np.int64
        np.testing.assert_array_equal(s, [4, 6])
        np.testing.assert_array_equal(p, [3, 8])

    def test_minmax_over_vectors(self) -> None:
        (y,) = MinMax(operator="min", n_inputs=2).output_v(
            0.0, _X, (np.array([1.0, 5.0]), np.array([3.0, 2.0]))
        )
        np.testing.assert_array_equal(y, [1.0, 2.0])

    def test_scalar_extension_in_kernel(self) -> None:
        (y,) = Add(signs="++").output_v(0.0, _X, (np.array([1.0, 2.0]), np.array(10.0)))
        np.testing.assert_array_equal(y, [11.0, 12.0])

    def test_cast_preserves_shape(self) -> None:
        (y,) = Cast(dtype="int32").output_v(0.0, _X, (np.array([[1.9, -2.9]]),))
        assert y.shape == (1, 2) and y.dtype == np.int32
        np.testing.assert_array_equal(y, [[1, -2]])
