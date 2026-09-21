"""ADR-0079 Stage 2 §(3) 6c: ``@block(port_shapes_in / port_shapes_out)`` と
``infer_output_shapes`` hook (ユーザーコード境界の宣言 API) のテスト。"""

from __future__ import annotations

import textwrap
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from flode import Simulator, block
from flode.blocks import Constant, Demux, Mux, PythonFunction, Scope
from flode.core import signals
from flode.exceptions import BlockSpecError, SignalShapeError


def _mux3(sim: Simulator, prefix: str = "m") -> Mux:
    m = sim.add(Mux(n=3, id=prefix))
    for i in range(3):
        c = sim.add(Constant(value=float(i + 1), id=f"{prefix}_c{i}"))
        sim.connect(c, m, dst_idx=i)
    return m


class TestFunctionForm:
    def test_structure_exposes_declared_shapes(self) -> None:
        @block(port_shapes_in=((3,),), port_shapes_out=((3,),))
        def double(t: float, u: float) -> float:
            return 2.0 * u

        s = double._flode_structure
        assert s.port_shapes_in == ((3,),)
        assert s.port_shapes_out == ((3,),)
        inst = double(id="d")
        assert inst.port_shapes_in == ((3,),)
        assert inst.port_shapes_out == ((3,),)
        assert signals._classify_shape(inst) == "declared"

    def test_undeclared_structure_is_empty_and_opaque(self) -> None:
        @block
        def ident(t: float, u: float) -> float:
            return u

        assert ident._flode_structure.port_shapes_in == ()
        assert ident._flode_structure.port_shapes_out == ()
        assert signals._classify_shape(ident()) == "opaque"

    def test_length_mismatch_rejected_at_decoration(self) -> None:
        with pytest.raises(BlockSpecError, match="length 2 does not match"):

            @block(port_shapes_in=((3,), ()))
            def f(t: float, u: float) -> float:
                return u

    def test_vector_runs_end_to_end(self) -> None:
        @block(port_shapes_in=((3,),), port_shapes_out=((3,),))
        def double(t: float, u: float) -> float:
            # ベクトル宣言ポートには ndarray が渡る
            assert isinstance(u, np.ndarray) and u.shape == (3,)
            return 2.0 * u

        sim = Simulator(t_end=0.02, dt=0.01)
        m = _mux3(sim)
        d = sim.add(double(id="d"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(m, d)
        sim.connect(d, sc)
        sim.run()
        np.testing.assert_array_equal(np.asarray(sc.values)[0], [2.0, 4.0, 6.0])

    def test_tuple_inputs_mixed_scalar_and_vector(self) -> None:
        @block(port_shapes_in=((3,), ()), port_shapes_out=((3,),))
        def scale(t: float, u: tuple[float, float]) -> float:
            v, k = u
            assert isinstance(v, np.ndarray) and isinstance(k, float)
            return k * v

        sim = Simulator(t_end=0.02, dt=0.01)
        m = _mux3(sim)
        k = sim.add(Constant(value=10.0, id="k"))
        s = sim.add(scale(id="s"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(m, s, dst_idx=0)
        sim.connect(k, s, dst_idx=1)
        sim.connect(s, sc)
        sim.run()
        np.testing.assert_array_equal(np.asarray(sc.values)[0], [10.0, 20.0, 30.0])

    def test_inputs_n_with_vector_ports_gets_tuple(self) -> None:
        @block(inputs=2, outputs=1, port_shapes_in=((2,), (2,)), port_shapes_out=((2,),))
        def add(t: float, u: np.ndarray) -> np.ndarray:
            assert isinstance(u, tuple)
            return u[0] + u[1]

        sim = Simulator(t_end=0.02, dt=0.01)
        a = sim.add(Mux(n=2, id="a"))
        b = sim.add(Mux(n=2, id="b"))
        c1 = sim.add(Constant(value=1.0, id="c1"))
        c2 = sim.add(Constant(value=2.0, id="c2"))
        for m in (a, b):
            sim.connect(c1, m, dst_idx=0)
            sim.connect(c2, m, dst_idx=1)
        blk = sim.add(add(id="add"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(a, blk, dst_idx=0)
        sim.connect(b, blk, dst_idx=1)
        sim.connect(blk, sc)
        sim.run()
        np.testing.assert_array_equal(np.asarray(sc.values)[0], [2.0, 4.0])

    def test_scalar_ports_keep_legacy_argument_forms(self) -> None:
        """全ポートスカラの宣言なら SM-T path でも従来の float / 1D ndarray が渡る。"""
        seen: dict[str, Any] = {}

        @block(inputs=2, outputs=1)
        def add(t: float, u: np.ndarray) -> float:
            seen["type"] = type(u)
            return float(u[0] + u[1])

        blk = add(id="add")
        (y,) = blk.output_v(0.0, np.zeros(0), (np.asarray(1.0), np.asarray(2.0)))
        assert seen["type"] is np.ndarray
        assert float(y) == 3.0

    def test_wrong_output_shape_is_error(self) -> None:
        @block(port_shapes_in=((3,),), port_shapes_out=((2,),))
        def bad(t: float, u: float) -> float:
            return u  # (3,) を返すが (2,) 宣言

        blk = bad(id="bad")
        with pytest.raises(BlockSpecError, match="port_shapes_out declares"):
            blk.output_v(0.0, np.zeros(0), (np.zeros(3),))

    def test_undeclared_block_rejects_vector_at_build(self) -> None:
        @block
        def ident(t: float, u: float) -> float:
            return u

        sim = Simulator(t_end=0.02, dt=0.01)
        m = _mux3(sim)
        blk = sim.add(ident(id="i"))
        sim.connect(m, blk)
        with pytest.raises(SignalShapeError, match="shape.opaque_scalar_island"):
            sim.run()

    def test_vector_state_with_declared_ports(self) -> None:
        @block(states=3, outputs=1, port_shapes_in=((3,),), port_shapes_out=((3,),))
        def integ3(
            t: float, x: np.ndarray, u: float, *, x0: np.ndarray = np.zeros(3)
        ) -> tuple[np.ndarray, np.ndarray]:
            return x, np.asarray(u)

        sim = Simulator(t_end=0.1, dt=0.01)
        m = _mux3(sim)
        blk = sim.add(integ3(id="i3"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(m, blk)
        sim.connect(blk, sc)
        sim.run()
        v = np.asarray(sc.values)
        np.testing.assert_allclose(v[-1], [0.1, 0.2, 0.3], atol=1e-9)


class TestClassForm:
    def test_infer_output_shapes_hook(self) -> None:
        @block
        class Square:
            def output(self, t: float, u: float) -> float:
                return u * u

            def infer_output_shapes(
                self, in_shapes: tuple[tuple[int, ...], ...]
            ) -> tuple[tuple[int, ...], ...]:
                return (in_shapes[0],)

        inst = Square(id="sq")
        assert signals._classify_shape(inst) == "inferred"
        sim = Simulator(t_end=0.02, dt=0.01)
        m = _mux3(sim)
        blk = sim.add(Square(id="sq"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(m, blk)
        sim.connect(blk, sc)
        res = sim.resolve_signals()
        assert res.out_shape("sq", 0) == (3,)
        sim.run()
        np.testing.assert_array_equal(np.asarray(sc.values)[0], [1.0, 4.0, 9.0])

    def test_hook_returning_wrong_count_is_error(self) -> None:
        @block
        class Bad:
            def output(self, t: float, u: float) -> float:
                return u

            def infer_output_shapes(
                self, in_shapes: tuple[tuple[int, ...], ...]
            ) -> tuple[tuple[int, ...], ...]:
                return (in_shapes[0], in_shapes[0])

        sim = Simulator(t_end=0.02, dt=0.01)
        m = _mux3(sim)
        blk = sim.add(Bad(id="bad"))
        sim.connect(m, blk)
        with pytest.raises(BlockSpecError, match="returned 2 shape"):
            sim.run()

    def test_declared_shapes_on_class_form(self) -> None:
        @block(port_shapes_in=((2,),), port_shapes_out=((2,),))
        class Neg:
            def output(self, t: float, u: float) -> float:
                return -u

        inst = Neg(id="n")
        assert inst.port_shapes_in == ((2,),)
        (y,) = inst.output_v(0.0, np.zeros(0), (np.array([1.0, -2.0]),))
        np.testing.assert_array_equal(y, [-1.0, 2.0])


class TestPythonFunctionDeclaration:
    CODE = textwrap.dedent(
        """
        import numpy as np
        from flode import block

        @block(port_shapes_in=((3,),), port_shapes_out=((3,),))
        def triple(t: float, u: float, *, k: float = 3.0) -> float:
            return k * u
        """
    )

    def test_static_analysis_reads_port_shapes(self) -> None:
        pf = PythonFunction(code=self.CODE, id="pf")
        assert pf.spec.port_shapes_in == ((3,),)
        assert pf.port_shapes_in == ((3,),)
        assert pf.port_shapes_out == ((3,),)
        assert signals._classify_shape(pf) == "declared"

    def test_runs_with_vector(self) -> None:
        sim = Simulator(t_end=0.02, dt=0.01)
        m = _mux3(sim)
        pf = sim.add(PythonFunction(code=self.CODE, id="pf"))
        d = sim.add(Demux(n=3, id="d"))
        sc = sim.add(Scope(n_inputs=3, id="sc"))
        sim.connect(m, pf)
        sim.connect(pf, d)
        for i in range(3):
            sim.connect(d, sc, src_idx=i, dst_idx=i)
        sim.run()
        np.testing.assert_array_equal(np.asarray(sc.values)[0], [3.0, 6.0, 9.0])

    def test_non_literal_port_shapes_rejected(self) -> None:
        code = textwrap.dedent(
            """
            from flode import block
            N = 3

            @block(port_shapes_in=((N,),))
            def f(t: float, u: float) -> float:
                return u
            """
        )
        with pytest.raises(BlockSpecError, match="must be a literal"):
            PythonFunction(code=code, id="pf")

    def test_static_mode_reports_declared_shapes(self) -> None:
        """REST 経路 (static mode、exec なし) でも宣言 shape が payload に出る。"""
        sim = Simulator(t_end=0.02, dt=0.01)
        m = _mux3(sim)
        pf = sim.add(PythonFunction(code=self.CODE, id="pf"))
        sim.connect(m, pf)
        res = signals.resolve_signals(sim, mode="static")
        assert res.out_shape("pf", 0) == (3,)
        assert res.in_shape("pf", 0) == (3,)


def _dummy_npt() -> npt.NDArray[Any]:  # pragma: no cover - 型 import の保持
    return np.zeros(1)
