"""ADR-0027 §(10) C/D/F: 固有値 / 漸近安定性 / 根軌跡 の数値検証。

固有値・安定性は ``np.linalg.eig`` ベースで extras 不要。根軌跡は
``pyflw[control]`` extras 必須なので importorskip。
"""

from __future__ import annotations

import numpy as np
import pytest

from pyflw import Simulator, linearize
from pyflw.analysis import eigenvalues, is_stable, root_locus
from pyflw.blocks import Integrator, Scope, StateSpace, TransferFunction
from pyflw.exceptions import BlockSpecError

# ---------------------------------------------------------------------------
# eigenvalues / is_stable (numpy のみ、extras 不要)
# ---------------------------------------------------------------------------


class TestEigenvalues:
    """``np.linalg.eig`` の薄ラッパ。"""

    def test_diagonal_state_space(self) -> None:
        """A = diag([-1, -2, -3]) → eigenvalues = [-1, -2, -3]。"""
        A = np.diag([-1.0, -2.0, -3.0])
        B = np.array([[1.0], [1.0], [1.0]])
        C = np.array([[1.0, 1.0, 1.0]])
        sim = Simulator(t_end=1.0, dt=0.01)
        ss = sim.add(StateSpace(A, B, C))
        sim.connect(ss, sim.add(Scope()))
        ls = linearize(sim)
        eigs = eigenvalues(ls)
        # 順序は LAPACK 依存だが、集合としては {-1, -2, -3}
        eigs_sorted = np.sort(np.real(eigs))
        np.testing.assert_allclose(eigs_sorted, [-3.0, -2.0, -1.0], rtol=1e-12)
        # 虚部はすべてゼロ (実固有値)
        np.testing.assert_allclose(np.imag(eigs), 0.0, atol=1e-9)

    def test_complex_eigenvalues(self) -> None:
        """A = [[0, 1], [-1, 0]] → 純虚軸固有値 ±j。"""
        A = np.array([[0.0, 1.0], [-1.0, 0.0]])
        B = np.array([[0.0], [1.0]])
        C = np.array([[1.0, 0.0]])
        sim = Simulator(t_end=1.0, dt=0.01)
        ss = sim.add(StateSpace(A, B, C))
        sim.connect(ss, sim.add(Scope()))
        ls = linearize(sim)
        eigs = eigenvalues(ls)
        # 実部はゼロ
        np.testing.assert_allclose(np.real(eigs), 0.0, atol=1e-9)
        # 虚部は ±1 (絶対値で 1)
        np.testing.assert_allclose(np.sort(np.abs(np.imag(eigs))), [1.0, 1.0], rtol=1e-9)

    def test_dtype_complex(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls = linearize(sim)
        eigs = eigenvalues(ls)
        assert np.iscomplexobj(eigs)


class TestIsStable:
    """漸近安定性判定の境界値ハンドリング (ADR-0027 §(6))。"""

    def test_stable_diagonal(self) -> None:
        """全固有値の実部が負 → True。"""
        A = np.diag([-1.0, -2.0, -3.0])
        sim = Simulator(t_end=1.0, dt=0.01)
        ss = sim.add(StateSpace(A, np.array([[1.0], [1.0], [1.0]]), np.array([[1.0, 1.0, 1.0]])))
        sim.connect(ss, sim.add(Scope()))
        ls = linearize(sim)
        assert is_stable(ls) is True

    def test_marginal_returns_false(self) -> None:
        """純虚軸極 (Re(λ)=0) は False (= 限界安定は不安定扱い、ADR-0027 §(6))。"""
        A = np.array([[0.0, 1.0], [-1.0, 0.0]])
        sim = Simulator(t_end=1.0, dt=0.01)
        ss = sim.add(StateSpace(A, np.array([[0.0], [1.0]]), np.array([[1.0, 0.0]])))
        sim.connect(ss, sim.add(Scope()))
        ls = linearize(sim)
        assert is_stable(ls) is False

    def test_unstable_mixed(self) -> None:
        """A = diag([1, -1]) → 不安定 (1 つは Re(λ) > 0)。"""
        A = np.diag([1.0, -1.0])
        sim = Simulator(t_end=1.0, dt=0.01)
        ss = sim.add(StateSpace(A, np.array([[1.0], [1.0]]), np.array([[1.0, 1.0]])))
        sim.connect(ss, sim.add(Scope()))
        ls = linearize(sim)
        assert is_stable(ls) is False

    def test_pure_integrator_marginal(self) -> None:
        """Integrator: A=[[0]] → eigenvalue 0 → False。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls = linearize(sim)
        assert is_stable(ls) is False

    def test_custom_tol_strict(self) -> None:
        """tol=1.0 のとき Re(λ) = -0.5 (= -1.0 より大きい) は False。"""
        A = np.array([[-0.5]])
        sim = Simulator(t_end=1.0, dt=0.01)
        ss = sim.add(StateSpace(A, np.array([[1.0]]), np.array([[1.0]])))
        sim.connect(ss, sim.add(Scope()))
        ls = linearize(sim)
        # default tol=1e-9 では True
        assert is_stable(ls) is True
        # tol=1.0 では Re(λ)=-0.5 < -1.0 ではないので False
        assert is_stable(ls, tol=1.0) is False

    def test_negative_tol_raises(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls = linearize(sim)
        with pytest.raises(ValueError, match="tol must be"):
            is_stable(ls, tol=-1e-9)


class TestEigenvaluesEmptyState:
    """空の状態空間 (= linearize 不可) が拒否される。"""

    def test_no_continuous_states_raises(self) -> None:
        # linearize() 自体が BlockSpecError を出すので、eigenvalues は呼ばれる前に
        # 失敗する。代わりに直接 LinearSystem を組んで test。
        from pyflw.analysis import LinearSystem

        ls = LinearSystem(
            A=np.zeros((0, 0)),
            B=np.zeros((0, 0)),
            C=np.zeros((0, 0)),
            D=np.zeros((0, 0)),
            state_names=[],
            input_names=[],
            output_names=[],
            operating_point={"t": 0.0, "x": np.zeros(0), "u": np.zeros(0)},
        )
        with pytest.raises(BlockSpecError, match="empty state-space"):
            eigenvalues(ls)


# ---------------------------------------------------------------------------
# LinearSystem メソッド版 (numpy のみ — control 不要、importorskip より前に置く)
# ---------------------------------------------------------------------------


class TestLinearSystemMethodsNoExtras:
    """``ls.eigenvalues()`` / ``.is_stable()`` メソッド版 (extras 不要)。

    ``control`` extras 不在の CI 環境でもこの class は実行される
    (`importorskip` は ``TestRootLocus`` 等の extras 必須 class 直前まで遅延)。
    """

    def test_eigenvalues_method(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0]))
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls = linearize(sim)
        np.testing.assert_allclose(ls.eigenvalues(), eigenvalues(ls))

    def test_is_stable_method(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0]))
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls = linearize(sim)
        assert ls.is_stable() == is_stable(ls)


# ---------------------------------------------------------------------------
# root_locus (python-control 必須)
# ---------------------------------------------------------------------------


pytest.importorskip("control")  # 以下、root_locus は extras 必須

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


class TestRootLocus:
    """SISO 根軌跡。"""

    def test_first_order_root_locus(self) -> None:
        """G(s) = 1/(s+1)、K 増加で極が s=-1 から s→-∞ に実軸上を移動。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        tf = sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0]))
        sim.connect(tf, sim.add(Scope()))
        ls = linearize(sim)
        rl = root_locus(ls)
        # 1 状態系
        assert rl.roots.shape[1] == 1
        assert rl.gains.size == rl.roots.shape[0]
        # K=0 付近の極は s=-1 近傍
        idx_low = int(np.argmin(rl.gains))
        np.testing.assert_allclose(np.real(rl.roots[idx_low, 0]), -1.0, rtol=1e-4)
        np.testing.assert_allclose(np.imag(rl.roots[idx_low, 0]), 0.0, atol=1e-9)

    def test_root_locus_idx_out_of_range(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls = linearize(sim)
        with pytest.raises(BlockSpecError, match="input_idx"):
            root_locus(ls, input_idx=99)
        with pytest.raises(BlockSpecError, match="output_idx"):
            root_locus(ls, output_idx=99)

    def test_root_locus_invalid_k_range(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls = linearize(sim)
        with pytest.raises(BlockSpecError, match="invalid k_range"):
            root_locus(ls, k_range=(0.0, 1.0))  # k_min must be > 0
        with pytest.raises(BlockSpecError, match="invalid k_range"):
            root_locus(ls, k_range=(10.0, 1.0))  # k_max < k_min

    def test_root_locus_explicit_k_array(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0]))
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls = linearize(sim)
        ks = np.array([0.1, 1.0, 10.0])
        rl = root_locus(ls, k_range=ks)
        np.testing.assert_allclose(rl.gains, ks)
        assert rl.roots.shape == (3, 1)

    def test_root_locus_plot_smoke(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0]))
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls = linearize(sim)
        rl = root_locus(ls)
        ax = rl.plot()
        assert ax is not None
        plt.close("all")


class TestLinearSystemRootLocusMethod:
    """``ls.root_locus()`` メソッド版 (extras 必須)。"""

    def test_root_locus_method_match(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0]))
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls = linearize(sim)
        rl_method = ls.root_locus()
        rl_func = root_locus(ls)
        np.testing.assert_allclose(rl_method.gains, rl_func.gains)
