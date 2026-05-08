"""ADR-0026: 入出力次元の組み合わせテスト (専用ファイル)。

各テストクラスは「入力次元 m × 出力次元 p × 状態次元 n」の組み合わせを
網羅し、B/D の shape が常に 2D を維持し、labels の長さが行列次元と一致する
ことを body-of-evidence として確認する。
"""

from __future__ import annotations

import numpy as np
import pytest

from pyflw import Simulator, linearize
from pyflw.blocks import (
    Constant,
    Display,
    Integrator,
    Scope,
    StateSpace,
    Terminator,
)


class TestZeroInputDimension:
    """m=0 (全入力結線済み): B.shape==(n,0), D.shape==(p,0) かつ両者が 2D 配列。"""

    def test_b_is_2d_with_shape_n0(self) -> None:
        """Constant→Integrator→Scope: B shape (1,0), D shape (1,0), 両者 ndim==2。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        c = sim.add(Constant(value=1.0))
        i = sim.add(Integrator())
        sim.connect(c, i)
        sim.connect(i, sim.add(Scope()))
        ls = linearize(sim)
        assert ls.B.shape == (1, 0), f"Expected (1,0), got {ls.B.shape}"
        assert ls.D.shape == (1, 0), f"Expected (1,0), got {ls.D.shape}"
        assert ls.B.ndim == 2
        assert ls.D.ndim == 2

    def test_multi_state_zero_input(self) -> None:
        """2状態 StateSpace、全入力結線済み: B.shape==(2,0)。"""
        A_mat = np.array([[0.0, 1.0], [-1.0, -2.0]])
        B_mat = np.array([[0.0], [1.0]])
        C_mat = np.array([[1.0, 0.0]])
        sim = Simulator(t_end=1.0, dt=0.01)
        ss = sim.add(StateSpace(A_mat, B_mat, C_mat, id="ss"))
        c = sim.add(Constant(value=0.0))
        sim.connect(c, ss)
        sim.connect(ss, sim.add(Scope()))
        ls = linearize(sim)
        assert ls.B.shape == (2, 0)
        assert ls.D.ndim == 2

    def test_input_names_empty_when_zero_inputs(self) -> None:
        """外部入力ゼロのとき input_names は空リスト。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        c = sim.add(Constant(value=0.0))
        i = sim.add(Integrator())
        sim.connect(c, i)
        sim.connect(i, sim.add(Scope()))
        ls = linearize(sim)
        assert ls.input_names == []
        assert len(ls.input_names) == ls.B.shape[1]


class TestZeroOutputDimension:
    """p=0 (有効な外部出力なし): C.shape==(0,n), D.shape==(0,m) かつ 2D 配列。"""

    def test_terminator_only_gives_zero_output_dim(self) -> None:
        """Integrator → Terminator: p=0, C/D は shape (0,n)/(0,m)。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator(id="i"))
        term = sim.add(Terminator(id="term"))
        sim.connect(i, term)
        ls = linearize(sim)
        assert ls.C.shape == (0, 1), f"Expected (0,1), got {ls.C.shape}"
        assert ls.D.shape == (0, 1), f"Expected (0,1), got {ls.D.shape}"
        assert ls.C.ndim == 2
        assert ls.D.ndim == 2

    def test_output_names_empty_when_zero_outputs(self) -> None:
        """外部出力ゼロのとき output_names は空リスト。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator(id="i"))
        sim.connect(i, sim.add(Terminator()))
        ls = linearize(sim)
        assert ls.output_names == []
        assert len(ls.output_names) == ls.C.shape[0]


class TestScalar1x1x1:
    """1入力 1出力 1状態 (スカラー) モデルで全行列が 1×1。"""

    def test_integrator_all_matrices_1x1(self) -> None:
        """Integrator: A/B/C/D が全て shape (1,1)。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator())
        sim.connect(i, sim.add(Scope()))
        ls = linearize(sim)
        for name, mat in [("A", ls.A), ("B", ls.B), ("C", ls.C), ("D", ls.D)]:
            assert mat.shape == (1, 1), f"{name}.shape expected (1,1), got {mat.shape}"

    def test_labels_length_1_for_scalar_model(self) -> None:
        """スカラーモデルで state/input/output_names が長さ 1 のリスト。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator())
        sim.connect(i, sim.add(Scope()))
        ls = linearize(sim)
        assert len(ls.state_names) == 1
        assert len(ls.input_names) == 1
        assert len(ls.output_names) == 1


class TestDualScopeNoDuplication:
    """同一ポートを 2 つの sink が消費しても外部出力は 1 回だけカウントされる。"""

    def test_two_scopes_count_as_one_output(self) -> None:
        """Integrator の出力を 2 つの Scope に接続 → C.shape[0] == 1。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator(id="i"))
        sc1 = sim.add(Scope(id="sc1"))
        sc2 = sim.add(Scope(id="sc2"))
        sim.connect(i, sc1)
        sim.connect(i, sc2)
        ls = linearize(sim)
        assert ls.C.shape[0] == 1
        assert len(ls.output_names) == 1

    def test_scope_and_display_count_as_one_output(self) -> None:
        """同一ポートを Scope + Display が消費しても出力次元は 1。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator(id="i"))
        sc = sim.add(Scope(id="sc"))
        disp = sim.add(Display(id="disp"))
        sim.connect(i, sc)
        sim.connect(i, disp)
        ls = linearize(sim)
        assert ls.C.shape[0] == 1


class TestLabelsLengthInvariant:
    """全パターンで labels の長さが対応する行列次元に一致するという不変条件。"""

    @pytest.mark.parametrize(
        "n_states,n_inputs,n_outputs",
        [
            (1, 1, 1),
            (2, 1, 1),
            (2, 2, 2),
        ],
    )
    def test_labels_lengths_match_dims(
        self, n_states: int, n_inputs: int, n_outputs: int
    ) -> None:
        """state/input/output の labels 長が A/B/C の各次元に一致する (parametrize)。"""
        A_mat = -np.eye(n_states)
        B_mat = np.ones((n_states, n_inputs)) / n_states
        C_mat = np.ones((n_outputs, n_states)) / n_states
        D_mat = np.zeros((n_outputs, n_inputs))
        sim = Simulator(t_end=1.0, dt=0.01)
        ss = sim.add(StateSpace(A_mat, B_mat, C_mat, D_mat, id="ss"))
        sim.connect(ss, sim.add(Scope(n_inputs=n_outputs)))
        ls = linearize(sim)
        assert len(ls.state_names) == ls.A.shape[0]
        assert len(ls.input_names) == ls.B.shape[1]
        assert len(ls.output_names) == ls.C.shape[0]
