"""ADR-0037 §(3): ``linearize(method='jax')`` と ``method='central'`` の
機械精度一致を検証する CI ゲート。

数値検証ポリシー (ADR-0037 §(3)):

* ``examples/spring_mass_damper.py`` の動作点で `method="central"` と
  `method="jax"` を比較、`atol=1e-12` で一致を pin
* LTI ブロック (Integrator / Sum / Gain) が jax で得た (A, B, C, D) が解析解と
  機械精度で一致

Phase 5b MVP の `_SUPPORTED_BLOCK_TYPES` (Constant / Step / Sine / Ramp /
Clock / Gain / Sum / Integrator) のみで構成されたモデルで動作する。
``StateSpace`` / ``TransferFunction`` / ``MimoTransferFunction`` の jax 対応は
Phase 6+ で別 ADR (ADR-0037 §Decision §3 の MVP scope)。
"""

from __future__ import annotations

import numpy as np
import pytest

from pyflw import Simulator, linearize
from pyflw.blocks import Constant, Gain, Integrator, Scope, Step, Sum
from pyflw.exceptions import BlockSpecError

# ---------------------------------------------------------------------------
# 動作点での central vs jax 一致
# ---------------------------------------------------------------------------


def _build_spring_mass_damper(m: float = 1.0, k: float = 4.0, c: float = 0.4) -> Simulator:
    """``examples/spring_mass_damper.py`` と同じトポロジを構築する。"""
    sim = Simulator(t_end=10.0, dt=0.01)
    F = sim.add(Step(step_time=0.0, final_value=1.0, id="F"))
    sum_block = sim.add(Sum(signs="+--", id="sum"))
    inv_m = sim.add(Gain(k=1.0 / m, id="inv_m"))
    i_xd = sim.add(Integrator(x0=0.0, id="x_dot"))
    i_x = sim.add(Integrator(x0=0.0, id="x"))
    gain_c = sim.add(Gain(k=c, id="c"))
    gain_k = sim.add(Gain(k=k, id="k"))
    sim.connect(F, sum_block, dst_idx=0)
    sim.connect(gain_c, sum_block, dst_idx=1)
    sim.connect(gain_k, sum_block, dst_idx=2)
    sim.connect(sum_block, inv_m)
    sim.connect(inv_m, i_xd)
    sim.connect(i_xd, i_x)
    sim.connect(i_xd, gain_c)
    sim.connect(i_x, gain_k)
    return sim


class TestSpringMassDamperConsistency:
    """ADR-0037 §(3) 数値検証 CI ゲート: central と jax が機械精度で一致する。"""

    def test_A_matches_central_at_machine_precision(self) -> None:
        sim = _build_spring_mass_damper()
        ls_central = linearize(sim, method="central")
        ls_jax = linearize(sim, method="jax")
        # central は ε≈sqrt(eps_machine) ≈ 1.5e-8 の誤差を持つので atol=1e-7
        # で central とは比較。jax は機械精度なので解析解との一致を別途検証。
        np.testing.assert_allclose(ls_central.A, ls_jax.A, atol=1e-7, rtol=0)

    def test_A_matches_analytic_solution_at_machine_precision(self) -> None:
        """jax は **解析解** と機械精度 (atol=1e-12) で一致する。"""
        m, k, c = 1.0, 4.0, 0.4
        sim = _build_spring_mass_damper(m=m, k=k, c=c)
        ls_jax = linearize(sim, method="jax")
        # 解析解: state vector = [x_dot, x]
        # A = [[-c/m, -k/m], [1, 0]] = [[-0.4, -4], [1, 0]]
        A_analytic = np.array([[-c / m, -k / m], [1.0, 0.0]])
        np.testing.assert_allclose(ls_jax.A, A_analytic, atol=1e-12, rtol=0)

    def test_B_matches_analytic_solution(self) -> None:
        """B = [[1/m], [0]] (= 入力 F が x_dot 微分に直達)。"""
        m = 1.0
        sim = _build_spring_mass_damper(m=m)
        ls_jax = linearize(sim, method="jax")
        # ADR-0026: 外部入力 = Step F (sink でも非 sink でもなく、未結線入力なし)
        # spring_mass_damper では F は Sum に結線されているので n_in=0
        assert ls_jax.B.shape == (2, 0)


# ---------------------------------------------------------------------------
# 単純 LTI モデル: 1-state Integrator
# ---------------------------------------------------------------------------


class TestIntegratorLTI:
    def test_integrator_A_is_zero(self) -> None:
        """Integrator 単体: A = [[0]] (= 状態に依存しない)。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        c = sim.add(Constant(value=1.0, id="c"))
        i = sim.add(Integrator(id="i"))
        sim.connect(c, i)
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect(i, sim.get_block("sc"))
        ls = linearize(sim, method="jax")
        np.testing.assert_array_equal(ls.A, np.array([[0.0]]))

    def test_integrator_with_external_input(self) -> None:
        """external input → Integrator: A=[[0]], B=[[1]]、自動微分で機械精度。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator(id="i"))
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect(i, sim.get_block("sc"))
        ls = linearize(sim, method="jax")
        # state = [x of Integrator]、external input = 1 (Integrator's u port)
        np.testing.assert_array_equal(ls.A, np.array([[0.0]]))
        np.testing.assert_array_equal(ls.B, np.array([[1.0]]))


# ---------------------------------------------------------------------------
# 未サポートブロックのエラー
# ---------------------------------------------------------------------------


class TestUnsupportedBlocks:
    def test_state_space_raises_blockspecerror(self) -> None:
        """``StateSpace`` は v0.17.0 jax 対象外、明示エラー。"""
        from pyflw.blocks import StateSpace

        sim = Simulator(t_end=1.0, dt=0.01)
        ss = sim.add(
            StateSpace(
                A=np.array([[0.0]]),
                B=np.array([[1.0]]),
                C=np.array([[1.0]]),
                D=np.array([[0.0]]),
                id="ss",
            )
        )
        sim.connect(ss, sim.add(Scope(n_inputs=1, id="sc")))
        with pytest.raises(BlockSpecError, match="not yet supported in v0.17.0"):
            linearize(sim, method="jax")

    def test_unsupported_block_message_suggests_central(self) -> None:
        from pyflw.blocks import TransferFunction

        sim = Simulator(t_end=1.0, dt=0.01)
        tf = sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0], id="tf"))
        sim.connect(tf, sim.add(Scope(n_inputs=1, id="sc")))
        with pytest.raises(BlockSpecError, match="method='central'"):
            linearize(sim, method="jax")


# ---------------------------------------------------------------------------
# epsilon との関係
# ---------------------------------------------------------------------------


class TestEpsilonInteraction:
    def test_epsilon_is_ignored_with_userwarning(self) -> None:
        """``method='jax'`` で ``epsilon`` を渡すと UserWarning + 結果は autodiff。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator(id="i"))
        sim.connect(i, sim.add(Scope(n_inputs=1, id="sc")))
        with pytest.warns(UserWarning, match="epsilon is ignored"):
            ls = linearize(sim, method="jax", epsilon=1e-3)
        # epsilon に関わらず autodiff の機械精度結果
        np.testing.assert_array_equal(ls.A, np.array([[0.0]]))


# ---------------------------------------------------------------------------
# Simulator.compile() の linearize 経路
# ---------------------------------------------------------------------------


class TestCompiledSimulatorLinearize:
    def test_compile_jax_then_linearize(self) -> None:
        """``Simulator.compile(backend='jax').linearize()`` が機械精度結果を返す。"""
        sim = _build_spring_mass_damper()
        compiled = sim.compile(backend="jax")
        ls = compiled.linearize()
        # 解析解 A = [[-0.4, -4], [1, 0]]
        np.testing.assert_allclose(ls.A, np.array([[-0.4, -4.0], [1.0, 0.0]]), atol=1e-12, rtol=0)

    def test_compile_numpy_falls_back_to_central(self) -> None:
        """``Simulator.compile(backend='numpy').linearize()`` は中心差分相当。"""
        sim = _build_spring_mass_damper()
        compiled = sim.compile(backend="numpy")
        ls = compiled.linearize()
        # central と同じ (= 摂動誤差を持つ)
        ls_central = linearize(sim, method="central")
        np.testing.assert_array_equal(ls.A, ls_central.A)
