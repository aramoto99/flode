"""MimoTransferFunction (ADR-0010 §(2)、ADR-0016 Phase 3 #1) の回帰テスト。

companion form 自前構築の動作 (scipy.signal.tf2ss バグ回避を含む) と、SISO
``TransferFunction`` との数値一致、解析解との一致、JSON round-trip を検証する。
"""

from __future__ import annotations

import numpy as np
import pytest

from pyflw import Simulator
from pyflw.blocks import (
    Constant,
    MimoTransferFunction,
    Scope,
    Step,
    TransferFunction,
)
from pyflw.blocks._lti_utils import build_companion_form_siso
from pyflw.exceptions import BlockSpecError


def _flat(scope: Scope) -> np.ndarray:
    return np.asarray(scope.values).reshape(-1)


# ---------------------------------------------------------------------------
# Companion form helper の単体テスト
# ---------------------------------------------------------------------------


class TestCompanionFormSiso:
    def test_first_order_strict_proper(self) -> None:
        """H(s) = 1/(s+1) の SS 実現 (controllable canonical form)。"""
        A, B, C, D = build_companion_form_siso(np.array([1.0]), np.array([1.0, 1.0]))
        assert A.shape == (1, 1)
        assert B.shape == (1, 1)
        assert C.shape == (1, 1)
        assert D.shape == (1, 1)
        # A = [[-1]], B = [[1]], C = [[1]], D = [[0]]
        np.testing.assert_allclose(A, [[-1.0]])
        np.testing.assert_allclose(B, [[1.0]])
        np.testing.assert_allclose(C, [[1.0]])
        np.testing.assert_allclose(D, [[0.0]])

    def test_second_order_strict_proper(self) -> None:
        """H(s) = (s+2)/(s^2+3s+2) の SS 実現 (controllable canonical)。"""
        A, B, C, D = build_companion_form_siso(np.array([1.0, 2.0]), np.array([1.0, 3.0, 2.0]))
        assert A.shape == (2, 2)
        # A = [[0, 1], [-2, -3]]
        np.testing.assert_allclose(A, [[0.0, 1.0], [-2.0, -3.0]])
        # B = [[0], [1]]
        np.testing.assert_allclose(B, [[0.0], [1.0]])
        # C = [b_0 - b_n*a_0, b_1 - b_n*a_1] (b_n=0 since strict proper)
        # numerator = [1, 2] → b_asc = [2, 1] (= [b_0, b_1])。b_2 = 0。
        # C = [b_0 - 0*a_0, b_1 - 0*a_1] = [2, 1]
        np.testing.assert_allclose(C, [[2.0, 1.0]])
        np.testing.assert_allclose(D, [[0.0]])

    def test_zero_numerator_is_safe(self) -> None:
        """ゼロ numerator (scipy.signal.tf2ss の BadCoefficients ケース) を許容。"""
        A, B, C, D = build_companion_form_siso(np.array([0.0]), np.array([1.0, 1.0]))
        # A = [[-1]] (denominator のみ)、B = [[1]]、C = [[0]] (zero numerator)、D = [[0]]
        np.testing.assert_allclose(A, [[-1.0]])
        np.testing.assert_allclose(B, [[1.0]])
        np.testing.assert_allclose(C, [[0.0]])
        np.testing.assert_allclose(D, [[0.0]])

    def test_biproper_d_term(self) -> None:
        """biproper (deg(num) == deg(den)) で D が非ゼロ。"""
        # H(s) = (s+1)/(s+2) = 1 - 1/(s+2) → biproper、D = b_n/a_n = 1/1 = 1
        A, B, C, D = build_companion_form_siso(np.array([1.0, 1.0]), np.array([1.0, 2.0]))
        # A = [[-2]], B = [[1]], D = [[1]] (b_1/a_1 = 1)
        # C = b_0 - b_1*a_0 = 1 - 1*2 = -1 → C = [[-1]]
        np.testing.assert_allclose(A, [[-2.0]])
        np.testing.assert_allclose(B, [[1.0]])
        np.testing.assert_allclose(C, [[-1.0]])
        np.testing.assert_allclose(D, [[1.0]])

    def test_improper_raises(self) -> None:
        """deg(num) > deg(den) で BlockSpecError。"""
        with pytest.raises(BlockSpecError, match="improper"):
            build_companion_form_siso(np.array([1.0, 2.0, 3.0]), np.array([1.0, 1.0]))

    def test_zero_denominator_leading_raises(self) -> None:
        """denominator[0] == 0 で BlockSpecError。"""
        with pytest.raises(BlockSpecError, match="leading coefficient"):
            build_companion_form_siso(np.array([1.0]), np.array([0.0, 1.0, 1.0]))

    def test_pure_gain_denominator_raises(self) -> None:
        """deg(den) == 0 (pure gain) は SS realization 不可で BlockSpecError。"""
        with pytest.raises(BlockSpecError, match="pure gain"):
            build_companion_form_siso(np.array([1.0]), np.array([1.0]))


# ---------------------------------------------------------------------------
# SISO degenerate ケース (TransferFunction との一致)
# ---------------------------------------------------------------------------


class TestMimoSiso:
    def test_first_order_step_response(self) -> None:
        """1x1 MIMO TF H(s) = 1/(s+1) で Step 応答 = 1 - exp(-t)。"""
        sim = Simulator(t_end=1.0, dt=0.01, rtol=1e-8, atol=1e-10)
        src = sim.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0))
        mimo = sim.add(MimoTransferFunction(numerators=[[[1.0]]], denominator=[1.0, 1.0]))
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(src, mimo)
        sim.connect(mimo, sc)
        sim.run()
        arr = _flat(sc)
        times = np.array(sc.times)
        # 解析解 1 - exp(-t)
        for k in (10, 50, 100):
            assert arr[k] == pytest.approx(1.0 - np.exp(-times[k]), abs=1e-6)

    def test_matches_transfer_function_block(self) -> None:
        """SISO 限定で TransferFunction (scipy.signal.tf2ss ベース) と数値一致。"""
        # H(s) = (s+2)/(s^2+3s+2) (strict proper)
        num = [1.0, 2.0]
        den = [1.0, 3.0, 2.0]

        sim_a = Simulator(t_end=2.0, dt=0.01, rtol=1e-9, atol=1e-12)
        src_a = sim_a.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0))
        tf_a = sim_a.add(TransferFunction(numerator=num, denominator=den))
        sc_a = sim_a.add(Scope(n_inputs=1))
        sim_a.connect(src_a, tf_a)
        sim_a.connect(tf_a, sc_a)
        sim_a.run()

        sim_b = Simulator(t_end=2.0, dt=0.01, rtol=1e-9, atol=1e-12)
        src_b = sim_b.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0))
        mimo_b = sim_b.add(MimoTransferFunction(numerators=[[num]], denominator=den))
        sc_b = sim_b.add(Scope(n_inputs=1))
        sim_b.connect(src_b, mimo_b)
        sim_b.connect(mimo_b, sc_b)
        sim_b.run()

        np.testing.assert_allclose(_flat(sc_a), _flat(sc_b), atol=1e-6)


# ---------------------------------------------------------------------------
# MIMO ケース
# ---------------------------------------------------------------------------


class TestMimoCases:
    def test_2x1_miso(self) -> None:
        """2 入力 1 出力: H = [[(s+2)/d, (s+1)/d]] with d = (s+1)(s+2)。両入力 Step=1。

        H[0,0] = 1/(s+1)、H[0,1] = 1/(s+2)。Step 応答 (Laplace 逆変換):
            L^{-1}{1/(s(s+a))} = (1/a)(1 - exp(-at))
        合成: y(t) = (1 - exp(-t)) + 0.5*(1 - exp(-2t))。
        """
        sim = Simulator(t_end=1.0, dt=0.01, rtol=1e-9, atol=1e-12)
        u1 = sim.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0))
        u2 = sim.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0))
        mimo = sim.add(
            MimoTransferFunction(
                numerators=[[[1.0, 2.0], [1.0, 1.0]]],  # H = [[(s+2)/d, (s+1)/d]]
                denominator=[1.0, 3.0, 2.0],  # d = (s+1)(s+2)
            )
        )
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(u1, mimo, dst_idx=0)
        sim.connect(u2, mimo, dst_idx=1)
        sim.connect(mimo, sc)
        sim.run()

        arr = _flat(sc)
        times = np.array(sc.times)
        for k in (50, 100):
            t = times[k]
            expected = (1.0 - np.exp(-t)) + 0.5 * (1.0 - np.exp(-2.0 * t))
            assert arr[k] == pytest.approx(expected, abs=1e-5)

    def test_zero_off_diagonal_no_crash(self) -> None:
        """ゼロ off-diagonal numerator (= scipy.signal.tf2ss bug ケース) を扱える。

        H(s) = [[1/(s+1), 0], [0, 1/(s+1)]] (= 対角 MIMO)
        """
        sim = Simulator(t_end=1.0, dt=0.01, rtol=1e-9, atol=1e-12)
        u1 = sim.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0))
        u2 = sim.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0))
        mimo = sim.add(
            MimoTransferFunction(
                numerators=[
                    [[1.0], [0.0]],
                    [[0.0], [1.0]],
                ],
                denominator=[1.0, 1.0],
            )
        )
        sc1 = sim.add(Scope(n_inputs=1, id="sc1"))
        sc2 = sim.add(Scope(n_inputs=1, id="sc2"))
        sim.connect(u1, mimo, dst_idx=0)
        sim.connect(u2, mimo, dst_idx=1)
        sim.connect(mimo, sc1, src_idx=0)
        sim.connect(mimo, sc2, src_idx=1)
        sim.run()

        arr1 = _flat(sc1)
        arr2 = _flat(sc2)
        times = np.array(sc1.times)
        # 各 output は 1/(s+1) の Step 応答 = 1 - exp(-t)
        for k in (10, 50, 100):
            expected = 1.0 - np.exp(-times[k])
            assert arr1[k] == pytest.approx(expected, abs=1e-5)
            assert arr2[k] == pytest.approx(expected, abs=1e-5)

    def test_2x2_full_mimo(self) -> None:
        """2x2 MIMO で対角と off-diag が混ざるケース。

        H(s) = [[1/(s+1), 0.5/(s+1)],
                [0.0,     2/(s+1)]]
        u1 = u2 = 1 (Step):
        y1 = 1*(1-exp(-t)) + 0.5*(1-exp(-t)) = 1.5*(1-exp(-t))
        y2 = 0 + 2*(1-exp(-t)) = 2*(1-exp(-t))
        """
        sim = Simulator(t_end=1.0, dt=0.01, rtol=1e-9, atol=1e-12)
        u1 = sim.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0))
        u2 = sim.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0))
        mimo = sim.add(
            MimoTransferFunction(
                numerators=[
                    [[1.0], [0.5]],
                    [[0.0], [2.0]],
                ],
                denominator=[1.0, 1.0],
            )
        )
        sc1 = sim.add(Scope(n_inputs=1, id="sc1"))
        sc2 = sim.add(Scope(n_inputs=1, id="sc2"))
        sim.connect(u1, mimo, dst_idx=0)
        sim.connect(u2, mimo, dst_idx=1)
        sim.connect(mimo, sc1, src_idx=0)
        sim.connect(mimo, sc2, src_idx=1)
        sim.run()

        arr1 = _flat(sc1)
        arr2 = _flat(sc2)
        times = np.array(sc1.times)
        for k in (50, 100):
            t = times[k]
            base = 1.0 - np.exp(-t)
            assert arr1[k] == pytest.approx(1.5 * base, abs=1e-5)
            assert arr2[k] == pytest.approx(2.0 * base, abs=1e-5)


# ---------------------------------------------------------------------------
# エラーパス
# ---------------------------------------------------------------------------


class TestMimoErrors:
    def test_empty_numerators_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="non-empty"):
            MimoTransferFunction(numerators=[], denominator=[1.0, 1.0])

    def test_inconsistent_row_length_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="length"):
            MimoTransferFunction(
                numerators=[[[1.0]], [[1.0], [1.0]]],
                denominator=[1.0, 1.0],
            )

    def test_empty_polynomial_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="non-empty sequence"):
            MimoTransferFunction(
                numerators=[[[]]],
                denominator=[1.0, 1.0],
            )

    def test_zero_leading_denominator_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="leading coefficient"):
            MimoTransferFunction(
                numerators=[[[1.0]]],
                denominator=[0.0, 1.0, 1.0],
            )

    def test_improper_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="improper"):
            MimoTransferFunction(
                numerators=[[[1.0, 2.0, 3.0]]],
                denominator=[1.0, 1.0],
            )

    def test_pure_gain_denominator_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="pure gain"):
            MimoTransferFunction(
                numerators=[[[1.0]]],
                denominator=[2.0],
            )


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------


class TestMimoPersistence:
    def test_save_load_roundtrip(self, tmp_path) -> None:
        sim = Simulator(t_end=0.5, dt=0.01)
        src = sim.add(Constant(value=1.0, id="src"))
        sim.add(
            MimoTransferFunction(
                numerators=[[[1.0], [2.0]], [[3.0], [4.0]]],
                denominator=[1.0, 5.0, 6.0],
                id="mimo",
            )
        )
        sim.connect(src, "mimo", dst_idx=0)
        sim.connect(src, "mimo", dst_idx=1)

        path = tmp_path / "mimo.flw.json"
        sim.save(path)

        sim2 = Simulator.load(path)
        mimo2 = sim2.get_block("mimo")
        # n_states = p * q * n = 2 * 2 * 2 = 8
        assert mimo2.n_states == 8
        assert mimo2.n_inputs == 2
        assert mimo2.n_outputs == 2

    def test_block_type_string(self, tmp_path) -> None:
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(
            MimoTransferFunction(
                numerators=[[[1.0]]],
                denominator=[1.0, 1.0],
                id="m",
            )
        )
        path = tmp_path / "m.flw.json"
        sim.save(path)
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        m_entry = next(b for b in data["blocks"] if b["id"] == "m")
        assert m_entry["type"] == "pyflw.blocks.continuous.MimoTransferFunction"
