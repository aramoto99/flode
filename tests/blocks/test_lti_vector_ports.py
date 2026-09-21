"""ADR-0079 Stage 3 (D-9): ``StateSpace`` 系のベクトルポート 1 本化。

- ポート規則: m / p ≥ 2 → shape ``(m,)`` / ``(p,)`` の 1 ポート、== 1 → ``()`` の 1 ポート
- ``port_shapes_*`` は行列次元から一意なので JSON に書かない
- m == p == 1 では SM-A ``output`` と ``output_v`` が bit-identical (従来経路の不変)
- ``Mux → SS → Demux`` の実行結果が解析解 / 手計算の漸化式と一致
- ``linearize`` は 1 ポートを flat index で展開する (B は m 列、C は p 行)
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from flode import Simulator, linearize
from flode.blocks import (
    Constant,
    Demux,
    DiscreteStateSpace,
    MimoTransferFunction,
    Mux,
    Scope,
    StateSpace,
    Step,
)
from flode.blocks._lti_utils import lti_port_layout


class TestPortLayout:
    @pytest.mark.parametrize(
        "n,expected",
        [(0, (0, ())), (1, (1, ((),))), (2, (1, ((2,),))), (5, (1, ((5,),)))],
    )
    def test_layout_rule(self, n: int, expected: tuple[int, tuple[tuple[int, ...], ...]]) -> None:
        assert lti_port_layout(n) == expected

    @pytest.mark.parametrize("m", [1, 2, 3])
    @pytest.mark.parametrize("p", [1, 2, 3])
    def test_state_space_ports(self, m: int, p: int) -> None:
        ss = StateSpace(A=-np.eye(2), B=np.ones((2, m)), C=np.ones((p, 2)))
        assert ss.n_inputs == 1 and ss.n_outputs == 1
        assert ss.port_shapes_in == ((m,) if m >= 2 else (),)
        assert ss.port_shapes_out == ((p,) if p >= 2 else (),)

    @pytest.mark.parametrize("m", [1, 2])
    @pytest.mark.parametrize("p", [1, 2])
    def test_discrete_state_space_ports(self, m: int, p: int) -> None:
        dss = DiscreteStateSpace(
            A=0.5 * np.eye(2), B=np.ones((2, m)), C=np.ones((p, 2)), sample_time=0.1
        )
        assert dss.n_inputs == 1 and dss.n_outputs == 1
        assert dss.port_shapes_in == ((m,) if m >= 2 else (),)
        assert dss.port_shapes_out == ((p,) if p >= 2 else (),)

    def test_mimo_tf_ports(self) -> None:
        mimo = MimoTransferFunction(
            numerators=[[[1.0], [2.0], [3.0]], [[0.0], [1.0], [0.0]]], denominator=[1.0, 1.0]
        )
        assert (mimo.n_inputs, mimo.n_outputs) == (1, 1)
        assert mimo.port_shapes_in == ((3,),)
        assert mimo.port_shapes_out == ((2,),)

    def test_port_shapes_not_serialized(self, tmp_path: Path) -> None:
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(StateSpace(A=-np.eye(2), B=np.eye(2), C=np.eye(2), id="ss"))
        sim.add(
            DiscreteStateSpace(
                A=0.5 * np.eye(2), B=np.eye(2), C=np.eye(2), sample_time=0.01, id="dss"
            )
        )
        path = tmp_path / "m.flw.json"
        sim.save(path)
        for entry in json.loads(path.read_text(encoding="utf-8"))["blocks"]:
            assert "port_shapes_in" not in entry
            assert "port_shapes_out" not in entry
        sim2 = Simulator.load(path)
        assert sim2.get_block("ss").port_shapes_in == ((2,),)
        assert sim2.get_block("dss").port_shapes_out == ((2,),)


class TestVectorApiMatchesScalarApi:
    """``*_v`` は SM-A 版に flat ``u`` を渡すだけなので値は同一。"""

    def test_siso_bit_identical(self) -> None:
        ss = StateSpace(A=[[-1.0, 0.5], [0.0, -2.0]], B=[[1.0], [2.0]], C=[[1.0, 1.0]], D=[[0.5]])
        x = np.array([0.3, -0.7])
        u1d = np.array([1.25])
        (y_v,) = ss.output_v(0.0, x, (np.asarray(1.25),))
        assert y_v.shape == ()
        assert np.array_equal(y_v, ss.output(0.0, x, u1d)[0])
        assert np.array_equal(
            ss.derivative_v(0.0, x, (np.asarray(1.25),)), ss.derivative(0.0, x, u1d)
        )

    def test_mimo_vector_port_equals_scalar_api(self) -> None:
        ss = StateSpace(
            A=[[-1.0, 0.5], [0.0, -2.0]],
            B=[[1.0, 0.0], [0.0, 1.0]],
            C=[[1.0, 1.0], [1.0, -1.0], [2.0, 0.0]],
            D=[[0.1, 0.0], [0.0, 0.2], [0.0, 0.0]],
        )
        x = np.array([0.3, -0.7])
        u = np.array([1.25, -0.5])
        (y_v,) = ss.output_v(0.0, x, (u,))
        assert y_v.shape == (3,)
        assert np.array_equal(y_v, ss.output(0.0, x, u))
        assert np.array_equal(ss.derivative_v(0.0, x, (u,)), ss.derivative(0.0, x, u))

    def test_discrete_update_v_equals_update(self) -> None:
        dss = DiscreteStateSpace(
            A=[[0.9, 0.1], [0.0, 0.8]], B=np.eye(2), C=np.eye(2), sample_time=0.1
        )
        x = np.array([1.0, 2.0, 3.0, 4.0])
        u = np.array([0.5, -0.5])
        assert np.array_equal(dss.update_v(0.0, x, (u,)), dss.update(0.0, x, u))
        assert np.array_equal(dss.advance_v(0.0, x, (u,)), dss.advance(0.0, x, u))
        (y_v,) = dss.output_v(0.0, x, (u,))
        assert np.array_equal(y_v, dss.output(0.0, x, u))


class TestRunThroughMuxDemux:
    def test_continuous_diagonal_channels(self) -> None:
        """A = diag(-1, -2)、B = C = I: 各チャネルが独立の 1 次系。Step 応答の解析解。"""
        sim = Simulator(t_end=1.0, dt=0.01, rtol=1e-9, atol=1e-12)
        u0 = sim.add(Step(step_time=0.0, initial_value=0.0, final_value=1.0))
        u1 = sim.add(Step(step_time=0.0, initial_value=0.0, final_value=2.0))
        mux = sim.add(Mux(n=2))
        ss = sim.add(StateSpace(A=np.diag([-1.0, -2.0]), B=np.eye(2), C=np.eye(2)))
        demux = sim.add(Demux(n=2))
        sc = sim.add(Scope(n_inputs=2))
        sim.connect(u0, mux, dst_idx=0)
        sim.connect(u1, mux, dst_idx=1)
        sim.connect(mux, ss)
        sim.connect(ss, demux)
        sim.connect(demux, sc, src_idx=0, dst_idx=0)
        sim.connect(demux, sc, src_idx=1, dst_idx=1)
        sim.run()
        t = np.asarray(sc.times)
        y = np.asarray(sc.values)
        np.testing.assert_allclose(y[:, 0], 1.0 - np.exp(-t), atol=1e-6)
        np.testing.assert_allclose(y[:, 1], 1.0 - np.exp(-2.0 * t), atol=1e-6)

    def test_vector_output_direct_to_scope(self) -> None:
        """Demux を挟まず Scope に直結すると 2 列に展開される。"""
        sim = Simulator(t_end=0.5, dt=0.01)
        u = sim.add(Constant(value=1.0))
        ss = sim.add(StateSpace(A=np.diag([-1.0, -2.0]), B=np.ones((2, 1)), C=np.eye(2)))
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(u, ss)
        sim.connect(ss, sc)
        sim.run()
        assert np.asarray(sc.values).shape[1] == 2
        assert sc.column_labels == ["in0[0]", "in0[1]"]

    def test_discrete_recursion_matches_numpy(self) -> None:
        """Constant 入力の DiscreteStateSpace 2×2 を numpy の漸化式と突合する。"""
        A = np.array([[0.9, 0.1], [0.0, 0.8]])
        B = np.array([[1.0, 0.0], [0.5, 1.0]])
        C = np.array([[1.0, 1.0], [1.0, -1.0]])
        ts = 0.1
        sim = Simulator(t_end=1.0, dt=ts)
        c0 = sim.add(Constant(value=1.0))
        c1 = sim.add(Constant(value=-0.5))
        mux = sim.add(Mux(n=2))
        dss = sim.add(DiscreteStateSpace(A=A, B=B, C=C, sample_time=ts))
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(c0, mux, dst_idx=0)
        sim.connect(c1, mux, dst_idx=1)
        sim.connect(mux, dss)
        sim.connect(dss, sc)
        sim.run()
        y = np.asarray(sc.values)
        u = np.array([1.0, -0.5])
        x = np.zeros(2)
        expected = []
        for _ in range(y.shape[0]):
            expected.append(C @ x)
            x = A @ x + B @ u
        np.testing.assert_allclose(y, np.asarray(expected), rtol=1e-12, atol=1e-12)


class TestLinearize:
    def test_dims_and_labels_use_flat_index(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        ss = sim.add(StateSpace(A=-np.eye(2), B=np.ones((2, 3)), C=np.ones((2, 2)), id="ss"))
        sim.connect(ss, sim.add(Scope(n_inputs=1)))
        ls = linearize(sim)
        assert ls.B.shape == (2, 3)
        assert ls.C.shape == (2, 2)
        assert ls.input_names == ["ss.in[0][0]", "ss.in[0][1]", "ss.in[0][2]"]
        assert ls.output_names == ["ss.out[0][0]", "ss.out[0][1]"]
        np.testing.assert_allclose(ls.B, np.ones((2, 3)), atol=1e-9)
