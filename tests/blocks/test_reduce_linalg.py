"""ADR-0079 Stage 3 (SPEC-0031 #19): ``Reduce`` / ``DotProduct`` / ``MatrixMultiply``。"""

from __future__ import annotations

import numpy as np
import pytest

from flode import Simulator
from flode.blocks import Constant, DotProduct, Gain, MatrixMultiply, Reduce, Scope
from flode.core.signals import resolve_for_execution
from flode.exceptions import BlockSpecError, SignalShapeError
from flode.server.registry import _BUILTIN_METADATA


def _run_last(sim: Simulator, sc: Scope) -> np.ndarray:
    sim.run()
    return np.asarray(sc.values)[-1]


class TestReduce:
    @pytest.mark.parametrize(
        "operation,expected",
        [("sum", 6.0), ("product", -30.0), ("min", -2.0), ("max", 5.0), ("mean", 2.0)],
    )
    def test_operations_on_vector(self, operation: str, expected: float) -> None:
        sim = Simulator(t_end=0.01, dt=0.01)
        c = sim.add(Constant(value=[3.0, -2.0, 5.0]))
        r = sim.add(Reduce(operation=operation))
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(c, r)
        sim.connect(r, sc)
        assert _run_last(sim, sc).tolist() == [expected]

    def test_matrix_input_reduces_all_elements(self) -> None:
        sim = Simulator(t_end=0.01, dt=0.01)
        c = sim.add(Constant(value=[[1.0, 2.0], [3.0, 4.0]]))
        r = sim.add(Reduce())
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(c, r)
        sim.connect(r, sc)
        assert _run_last(sim, sc).tolist() == [10.0]

    def test_scalar_input_is_identity_and_sm_a(self) -> None:
        sim = Simulator(t_end=0.01, dt=0.01)
        c = sim.add(Constant(value=4.5))
        r = sim.add(Reduce(operation="product"))
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(c, r)
        sim.connect(r, sc)
        assert sim._is_sm_a_mode()
        assert _run_last(sim, sc).tolist() == [4.5]
        assert r.output(0.0, np.zeros(0), np.array([4.5])).tolist() == [4.5]

    def test_output_shape_resolved_scalar(self) -> None:
        sim = Simulator(t_end=0.01, dt=0.01)
        c = sim.add(Constant(value=[1.0, 2.0], id="c"))
        r = sim.add(Reduce(id="r"))
        sim.connect(c, r)
        res = resolve_for_execution(sim)
        assert res.in_shape("r", 0) == (2,)
        assert res.out_shape("r", 0) == ()

    def test_invalid_operation(self) -> None:
        with pytest.raises(BlockSpecError, match="operation"):
            Reduce(operation="median")

    def test_params_and_registry(self) -> None:
        assert Reduce(operation="max")._params == {"operation": "max"}
        cat, name, icon = _BUILTIN_METADATA["flode.blocks.mathops.Reduce"]
        assert (cat, name, icon) == ("mathops", "Reduce", "math.reduce")


class TestDotProduct:
    def test_vector_inner_product(self) -> None:
        sim = Simulator(t_end=0.01, dt=0.01)
        a = sim.add(Constant(value=[1.0, 2.0, 3.0]))
        b = sim.add(Constant(value=[4.0, -5.0, 6.0]))
        d = sim.add(DotProduct())
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(a, d, dst_idx=0)
        sim.connect(b, d, dst_idx=1)
        sim.connect(d, sc)
        assert _run_last(sim, sc).tolist() == [4.0 - 10.0 + 18.0]

    def test_quadratic_form_with_matrix_gain(self) -> None:
        """xᵀ P x = Gain(P, matrix-Ku) → DotProduct(x, Px)。"""
        P = np.array([[2.0, 0.5], [0.5, 1.0]])
        x = np.array([1.0, -3.0])
        sim = Simulator(t_end=0.01, dt=0.01)
        cx = sim.add(Constant(value=x.tolist()))
        g = sim.add(Gain(k=P, multiplication="matrix-Ku"))
        d = sim.add(DotProduct())
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(cx, g)
        sim.connect(cx, d, dst_idx=0)
        sim.connect(g, d, dst_idx=1)
        sim.connect(d, sc)
        np.testing.assert_allclose(_run_last(sim, sc), [float(x @ P @ x)])

    def test_scalar_expansion_and_scalar_pair(self) -> None:
        sim = Simulator(t_end=0.01, dt=0.01)
        a = sim.add(Constant(value=[1.0, 2.0]))
        b = sim.add(Constant(value=3.0))
        d = sim.add(DotProduct())
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(a, d, dst_idx=0)
        sim.connect(b, d, dst_idx=1)
        sim.connect(d, sc)
        assert _run_last(sim, sc).tolist() == [9.0]
        assert DotProduct().output(0.0, np.zeros(0), np.array([2.0, 3.5])).tolist() == [7.0]

    def test_shape_mismatch_rejected(self) -> None:
        sim = Simulator(t_end=0.01, dt=0.01)
        a = sim.add(Constant(value=[1.0, 2.0]))
        b = sim.add(Constant(value=[1.0, 2.0, 3.0]))
        d = sim.add(DotProduct())
        sim.connect(a, d, dst_idx=0)
        sim.connect(b, d, dst_idx=1)
        sim.connect(d, sim.add(Scope()))
        with pytest.raises(SignalShapeError):
            sim.run()


class TestMatrixMultiply:
    def test_matrix_times_vector(self) -> None:
        A = [[1.0, 2.0], [3.0, 4.0]]
        sim = Simulator(t_end=0.01, dt=0.01)
        ca = sim.add(Constant(value=A, id="A"))
        cv = sim.add(Constant(value=[1.0, -1.0], id="v"))
        m = sim.add(MatrixMultiply(id="m"))
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(ca, m, dst_idx=0)
        sim.connect(cv, m, dst_idx=1)
        sim.connect(m, sc)
        res = resolve_for_execution(sim)
        assert res.out_shape("m", 0) == (2,)
        np.testing.assert_array_equal(_run_last(sim, sc), [-1.0, -1.0])

    def test_matrix_times_matrix_shape(self) -> None:
        sim = Simulator(t_end=0.01, dt=0.01)
        ca = sim.add(Constant(value=np.ones((2, 3)).tolist()))
        cb = sim.add(Constant(value=np.ones((3, 4)).tolist()))
        m = sim.add(MatrixMultiply(id="m"))
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(ca, m, dst_idx=0)
        sim.connect(cb, m, dst_idx=1)
        sim.connect(m, sc)
        assert resolve_for_execution(sim).out_shape("m", 0) == (2, 4)
        assert _run_last(sim, sc).shape == (8,)
        assert np.all(_run_last(sim, sc) == 3.0)

    def test_scalar_pair_is_product(self) -> None:
        sim = Simulator(t_end=0.01, dt=0.01)
        a = sim.add(Constant(value=2.0))
        b = sim.add(Constant(value=3.0))
        m = sim.add(MatrixMultiply())
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(a, m, dst_idx=0)
        sim.connect(b, m, dst_idx=1)
        sim.connect(m, sc)
        assert sim._is_sm_a_mode()
        assert _run_last(sim, sc).tolist() == [6.0]

    @pytest.mark.parametrize(
        "shape_a,shape_b",
        [((2,), ()), ((2, 3), (2,)), ((2, 3), (4, 5))],
    )
    def test_incompatible_shapes_rejected_at_build(
        self, shape_a: tuple[int, ...], shape_b: tuple[int, ...]
    ) -> None:
        sim = Simulator(t_end=0.01, dt=0.01)
        a = sim.add(Constant(value=np.ones(shape_a).tolist() if shape_a else 1.0))
        b = sim.add(Constant(value=np.ones(shape_b).tolist() if shape_b else 1.0))
        m = sim.add(MatrixMultiply())
        sim.connect(a, m, dst_idx=0)
        sim.connect(b, m, dst_idx=1)
        sim.connect(m, sim.add(Scope()))
        with pytest.raises(SignalShapeError, match="MatrixMultiply"):
            sim.run()

    def test_direct_call_with_mixed_rank_is_fail_closed(self) -> None:
        m = MatrixMultiply(id="m")
        with pytest.raises(BlockSpecError, match="both inputs"):
            m.output_v(0.0, np.zeros(0), (np.ones(2), np.asarray(2.0)))
