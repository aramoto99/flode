"""ADR-0026: 線形化の基本ブロック単体検証。

LTI ブロック (Integrator / StateSpace / TransferFunction) を線形化に流して、
解析解と数値一致することを確認する。中心差分の数値誤差は全て
``rtol=1e-4`` 以下、Integrator は ``atol=1e-12`` (純線形)。
"""

from __future__ import annotations

import numpy as np
import pytest

from pyflw import Simulator, linearize
from pyflw.blocks import Constant, Integrator, Scope, StateSpace, TransferFunction
from pyflw.blocks.continuous import MimoTransferFunction


class TestIntegrator:
    """``Integrator`` 単体: ``A=[[0]], B=[[1]], C=[[1]], D=[[0]]``。"""

    def test_canonical_form(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator())
        sc = sim.add(Scope())
        sim.connect(i, sc)
        ls = linearize(sim)
        np.testing.assert_allclose(ls.A, [[0.0]], atol=1e-12)
        np.testing.assert_allclose(ls.B, [[1.0]], atol=1e-12)
        np.testing.assert_allclose(ls.C, [[1.0]], atol=1e-12)
        np.testing.assert_allclose(ls.D, [[0.0]], atol=1e-12)

    def test_state_label(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator())
        sim.connect(i, sim.add(Scope()))
        ls = linearize(sim)
        assert ls.state_names == [f"{i.id}.x[0]"]
        assert ls.input_names == [f"{i.id}.in[0][0]"]
        # 出力は Integrator の output[0] が Scope を駆動するので external 認定
        assert ls.output_names == [f"{i.id}.out[0][0]"]

    def test_operating_point_default(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator(x0=3.0))
        sim.connect(i, sim.add(Scope()))
        ls = linearize(sim)
        np.testing.assert_allclose(ls.operating_point["x"], [3.0])
        np.testing.assert_allclose(ls.operating_point["u"], [0.0])
        assert ls.operating_point["t"] == 0.0


class TestStateSpace:
    """``StateSpace`` ブロック: 任意 (A,B,C,D) を渡して同じ値が返ること。"""

    def test_2x1_siso(self) -> None:
        # 2 状態 SISO: x_dot = A x + B u, y = C x + D u
        A = np.array([[0.0, 1.0], [-2.0, -3.0]])
        B = np.array([[0.0], [1.0]])
        C = np.array([[1.0, 0.0]])
        D = np.array([[0.0]])
        sim = Simulator(t_end=1.0, dt=0.01)
        ss = sim.add(StateSpace(A, B, C, D))
        sim.connect(ss, sim.add(Scope()))
        ls = linearize(sim)
        np.testing.assert_allclose(ls.A, A, rtol=1e-9, atol=1e-12)
        np.testing.assert_allclose(ls.B, B, rtol=1e-9, atol=1e-12)
        np.testing.assert_allclose(ls.C, C, rtol=1e-9, atol=1e-12)
        np.testing.assert_allclose(ls.D, D, rtol=1e-9, atol=1e-12)

    def test_with_direct_feedthrough(self) -> None:
        # D != 0
        A = np.array([[-1.0]])
        B = np.array([[1.0]])
        C = np.array([[2.0]])
        D = np.array([[0.5]])
        sim = Simulator(t_end=1.0, dt=0.01)
        ss = sim.add(StateSpace(A, B, C, D))
        sim.connect(ss, sim.add(Scope()))
        ls = linearize(sim)
        np.testing.assert_allclose(ls.A, A, rtol=1e-9)
        np.testing.assert_allclose(ls.B, B, rtol=1e-9)
        np.testing.assert_allclose(ls.C, C, rtol=1e-9)
        np.testing.assert_allclose(ls.D, D, rtol=1e-9)


class TestTransferFunction:
    """``TransferFunction`` を内部 (A,B,C,D) (companion form) と一致させる。"""

    def test_first_order(self) -> None:
        # G(s) = 1/(s+1) → companion form
        sim = Simulator(t_end=1.0, dt=0.01)
        tf = sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0]))
        sim.connect(tf, sim.add(Scope()))
        ls = linearize(sim)
        np.testing.assert_allclose(ls.A, tf._A, rtol=1e-9, atol=1e-12)
        np.testing.assert_allclose(ls.B, tf._B, rtol=1e-9, atol=1e-12)
        np.testing.assert_allclose(ls.C, tf._C, rtol=1e-9, atol=1e-12)
        np.testing.assert_allclose(ls.D, tf._D, rtol=1e-9, atol=1e-12)

    def test_second_order(self) -> None:
        # G(s) = (s+2)/(s²+3s+2) → 2 状態
        sim = Simulator(t_end=1.0, dt=0.01)
        tf = sim.add(TransferFunction(numerator=[1.0, 2.0], denominator=[1.0, 3.0, 2.0]))
        sim.connect(tf, sim.add(Scope()))
        ls = linearize(sim)
        np.testing.assert_allclose(ls.A, tf._A, rtol=1e-4, atol=1e-9)
        np.testing.assert_allclose(ls.B, tf._B, rtol=1e-4, atol=1e-9)
        np.testing.assert_allclose(ls.C, tf._C, rtol=1e-4, atol=1e-9)


class TestMimoTransferFunction:
    """``MimoTransferFunction`` の 2x2 共通分母 / 独立分母 で flatten 順序検証。"""

    def test_2x2_common_denominator(self) -> None:
        # 2 入力 2 出力 共通分母 (s+1)
        # G_ij(s) = (i+j)/(s+1)
        numerators = [
            [[1.0], [2.0]],
            [[3.0], [4.0]],
        ]
        denominator = [1.0, 1.0]
        sim = Simulator(t_end=1.0, dt=0.01)
        tf = sim.add(MimoTransferFunction(numerators=numerators, denominator=denominator))
        sim.connect(tf, sim.add(Scope(n_inputs=2)))
        ls = linearize(sim)
        # MIMO companion form: state size = p*q*n = 2*2*1 = 4
        np.testing.assert_allclose(ls.A, tf._A, rtol=1e-4, atol=1e-9)
        np.testing.assert_allclose(ls.B, tf._B, rtol=1e-4, atol=1e-9)
        np.testing.assert_allclose(ls.C, tf._C, rtol=1e-4, atol=1e-9)
        # D は 0 (proper TF)
        np.testing.assert_allclose(ls.D, np.zeros((2, 2)), atol=1e-9)


class TestSimulatorMethod:
    """``Simulator.linearize()`` メソッド経由でも同じ結果が得られる。"""

    def test_method_equivalent_to_function(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls_func = linearize(sim)
        ls_method = sim.linearize()
        np.testing.assert_allclose(ls_func.A, ls_method.A)
        np.testing.assert_allclose(ls_func.B, ls_method.B)
        np.testing.assert_allclose(ls_func.C, ls_method.C)
        np.testing.assert_allclose(ls_func.D, ls_method.D)


class TestForwardDifference:
    """``method="forward"`` の前進差分も基本ブロックでは正確。"""

    def test_integrator_forward(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator())
        sim.connect(i, sim.add(Scope()))
        ls = linearize(sim, method="forward")
        np.testing.assert_allclose(ls.A, [[0.0]], atol=1e-7)
        np.testing.assert_allclose(ls.B, [[1.0]], atol=1e-7)
        np.testing.assert_allclose(ls.C, [[1.0]], atol=1e-7)


class TestNoSideEffects:
    """``linearize()`` は ``Simulator`` の状態を変更しない。"""

    def test_run_after_linearize_unchanged(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator(x0=2.5))
        sc = sim.add(Scope())
        sim.connect(i, sc)
        # 線形化を呼んでから run しても結果は通常通り (x(t) = 2.5、入力ゼロなので)
        linearize(sim)
        sim.run()
        # Integrator は x_dot = u = 0 なので終始 2.5 のまま
        np.testing.assert_allclose(sc.values[-1], [2.5], atol=1e-9)

    def test_linearize_twice_consistent(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator())
        sim.connect(i, sim.add(Scope()))
        ls1 = linearize(sim)
        ls2 = linearize(sim)
        np.testing.assert_allclose(ls1.A, ls2.A)
        np.testing.assert_allclose(ls1.B, ls2.B)
        np.testing.assert_allclose(ls1.C, ls2.C)


@pytest.mark.parametrize("method", ["central", "forward"])
class TestUserOperatingPoint:
    """ユーザー指定の動作点 ``(t, x, u)`` が反映される。"""

    def test_explicit_x(self, method: str) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator(x0=0.0))
        sim.connect(i, sim.add(Scope()))
        ls = linearize(sim, x=np.array([5.0]), method=method)  # type: ignore[arg-type]
        np.testing.assert_allclose(ls.operating_point["x"], [5.0])
        # 線形 Integrator なので動作点に依らず A/B/C/D は不変
        np.testing.assert_allclose(ls.A, [[0.0]], atol=1e-7)
        np.testing.assert_allclose(ls.B, [[1.0]], atol=1e-7)

    def test_explicit_u(self, method: str) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator())
        sim.connect(i, sim.add(Scope()))
        ls = linearize(sim, u=np.array([7.5]), method=method)  # type: ignore[arg-type]
        np.testing.assert_allclose(ls.operating_point["u"], [7.5])


class TestLinearBlockOperatingPointInvariance:
    """線形ブロックは動作点に依らず A/B/C/D が一定である (境界値: 3 点)。"""

    @pytest.mark.parametrize("x_val", [0.0, 5.0, -10.0])
    def test_integrator_abcd_constant_across_x(self, x_val: float) -> None:
        """Integrator は動作点 x を変えても A/B/C/D が不変である。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator())
        sim.connect(i, sim.add(Scope()))
        ls = linearize(sim, x=np.array([x_val]))
        np.testing.assert_allclose(ls.A, [[0.0]], atol=1e-12)
        np.testing.assert_allclose(ls.B, [[1.0]], atol=1e-12)
        np.testing.assert_allclose(ls.C, [[1.0]], atol=1e-12)
        np.testing.assert_allclose(ls.D, [[0.0]], atol=1e-12)

    def test_state_space_abcd_constant_across_x(self) -> None:
        """StateSpace (2状態) は動作点 x を 3 点変えても A が一定である。"""
        A_mat = np.array([[0.0, 1.0], [-2.0, -3.0]])
        B_mat = np.array([[0.0], [1.0]])
        C_mat = np.array([[1.0, 0.0]])
        D_mat = np.zeros((1, 1))
        sim = Simulator(t_end=1.0, dt=0.01)
        ss = sim.add(StateSpace(A_mat, B_mat, C_mat, D_mat))
        sim.connect(ss, sim.add(Scope()))
        for x_op in [
            np.array([0.0, 0.0]),
            np.array([1.0, 2.0]),
            np.array([-5.0, 3.0]),
        ]:
            ls = linearize(sim, x=x_op)
            np.testing.assert_allclose(ls.A, A_mat, rtol=1e-9, atol=1e-12)

    def test_transfer_function_abcd_constant_across_x(self) -> None:
        """TransferFunction (2状態) は動作点 x を変えても A が一定である。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        tf = sim.add(TransferFunction(numerator=[1.0, 2.0], denominator=[1.0, 3.0, 2.0]))
        sim.connect(tf, sim.add(Scope()))
        ls1 = linearize(sim, x=np.array([0.0, 0.0]))
        ls2 = linearize(sim, x=np.array([1.0, -1.0]))
        np.testing.assert_allclose(ls1.A, ls2.A, atol=1e-9)
        np.testing.assert_allclose(ls1.B, ls2.B, atol=1e-9)


class TestZeroInputModel:
    """全入力結線済み (= 外部入力なし) のモデルで B/D が (n,0)/(p,0) shape を維持する。"""

    def test_b_shape_with_zero_inputs(self) -> None:
        """Constant → Integrator の場合 B.shape == (1, 0)。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        c = sim.add(Constant(value=1.0))
        i = sim.add(Integrator())
        sc = sim.add(Scope())
        sim.connect(c, i)
        sim.connect(i, sc)
        ls = linearize(sim)
        assert ls.B.shape == (1, 0), f"Expected (1, 0), got {ls.B.shape}"
        assert ls.D.shape == (1, 0), f"Expected (1, 0), got {ls.D.shape}"

    def test_b_d_are_2d_with_zero_inputs(self) -> None:
        """B.size == 0 のときも B が 2D 配列である (ndim == 2)。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        c = sim.add(Constant(value=0.0))
        i = sim.add(Integrator())
        sim.connect(c, i)
        sim.connect(i, sim.add(Scope()))
        ls = linearize(sim)
        assert ls.B.ndim == 2
        assert ls.D.ndim == 2


class TestLabelsConsistency:
    """labels の長さと内容の整合性テスト。"""

    def test_labels_lengths_match_matrix_dims(self) -> None:
        """state/input/output の名前リスト長が各行列次元に一致する。"""
        A_mat = np.array([[0.0, 1.0], [-2.0, -3.0]])
        B_mat = np.array([[0.0], [1.0]])
        C_mat = np.array([[1.0, 0.0]])
        D_mat = np.zeros((1, 1))
        sim = Simulator(t_end=1.0, dt=0.01)
        ss = sim.add(StateSpace(A_mat, B_mat, C_mat, D_mat, id="ss"))
        sim.connect(ss, sim.add(Scope()))
        ls = linearize(sim)
        assert len(ls.state_names) == ls.A.shape[0]
        assert len(ls.input_names) == ls.B.shape[1]
        assert len(ls.output_names) == ls.C.shape[0]

    def test_labels_are_unique(self) -> None:
        """state/input/output の名前リストに重複がない。"""
        A_mat = np.array([[0.0, 1.0], [-2.0, -3.0]])
        B_mat = np.array([[0.0], [1.0]])
        C_mat = np.array([[1.0, 0.0]])
        D_mat = np.zeros((1, 1))
        sim = Simulator(t_end=1.0, dt=0.01)
        ss = sim.add(StateSpace(A_mat, B_mat, C_mat, D_mat, id="ss"))
        sim.connect(ss, sim.add(Scope()))
        ls = linearize(sim)
        assert len(ls.state_names) == len(set(ls.state_names))
        assert len(ls.input_names) == len(set(ls.input_names))
        assert len(ls.output_names) == len(set(ls.output_names))

    def test_subsystem_state_label_format(self) -> None:
        """Subsystem の状態ラベルは ``'{subsystem_id}.x[{i}]'`` 形式 (ADR-0026 §(8))。"""
        from pyflw import Inport, Outport, Subsystem
        from pyflw.blocks import Gain

        sub = Subsystem(id="sub")
        sub.add(Inport(port_idx=0))
        sub.add(Gain(k=2.0, id="g"))
        sub.add(Integrator(id="i"))
        sub.add(Outport(port_idx=0))
        sub.connect("Inport_0", "g")
        sub.connect("g", "i")
        sub.connect("i", "Outport_0")
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(sub)
        sim.connect(sub, sim.add(Scope()))
        ls = linearize(sim)
        assert ls.state_names == ["sub.x[0]"]


class TestDualScopeNoDuplication:
    """同一ポートを 2 つの Scope が消費する場合、出力次元は 1 回だけカウントされる。"""

    def test_two_scopes_from_same_port(self) -> None:
        """Integrator → Scope1, Scope2 のとき output_names は 1 エントリのみ。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator(id="i"))
        sc1 = sim.add(Scope(id="sc1"))
        sc2 = sim.add(Scope(id="sc2"))
        sim.connect(i, sc1)
        sim.connect(i, sc2)
        ls = linearize(sim)
        assert ls.C.shape[0] == 1
        assert len(ls.output_names) == 1


class TestLargeStateSpaceSmoke:
    """n=20 の StateSpace で線形化が短時間で完了し数値精度を満たす (スモーク)。"""

    def test_n20_finishes_quickly(self) -> None:
        """n=20 の StateSpace で linearize が正確な A を返す。"""
        import time

        n = 20
        A_mat = np.diag(-np.ones(n)) + np.diag(0.5 * np.ones(n - 1), 1)
        B_mat = np.zeros((n, 1))
        B_mat[0, 0] = 1.0
        C_mat = np.zeros((1, n))
        C_mat[0, n - 1] = 1.0
        D_mat = np.zeros((1, 1))
        sim = Simulator(t_end=1.0, dt=0.01)
        ss = sim.add(StateSpace(A_mat, B_mat, C_mat, D_mat, id="ss"))
        sim.connect(ss, sim.add(Scope()))
        t0 = time.perf_counter()
        ls = linearize(sim)
        elapsed = time.perf_counter() - t0
        # 線形時間 (O(n) 評価) で完了することを秒単位の余裕で確認
        assert elapsed < 5.0, f"linearize took {elapsed:.2f}s for n=20"
        np.testing.assert_allclose(ls.A, A_mat, rtol=1e-6, atol=1e-9)
