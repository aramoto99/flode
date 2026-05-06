"""MimoTransferFunction 境界値・エッジケーステスト (補強)。

ADR-0010 §(2) / ADR-0016 の実装に対して以下の観点を追加検証する:

観点 1 : biproper 単一 SISO ケース       — direct_feedthrough=True に切り替わるか
観点 2 : MIMO biproper/strict-proper 混在 — D 行列一部非ゼロ・direct_feedthrough=True
観点 3 : 高次 (n=5) companion form の数値安定性 — 解析解との一致 (10× 安定極)
観点 4 : SIMO (p=3, q=1) / MISO (p=1, q=3) の形状検証
観点 5 : x0 初期状態指定 — ゼロと非ゼロで出力差が正しく現れる
観点 6 : JSON round-trip + run() — save → load → run で結果が一致する
観点 7 : ゼロ多項式複数混ざる疎な MIMO TF — H = [[0, 0], [0, 1/(s+1)]]
観点 8 : 連続→MIMO→連続 のフロー — Integrator → MimoTransferFunction → Integrator
観点 9 : Subsystem 内部で MimoTransferFunction を使用
観点 10: derivative 直接呼び出し (sample_time 解決不要)
"""

from __future__ import annotations

import numpy as np
import pytest
import scipy.signal

from pyflw import Simulator
from pyflw.blocks import (
    Constant,
    Integrator,
    MimoTransferFunction,
    Scope,
    Step,
    TransferFunction,
)
from pyflw.blocks._lti_utils import _DF_TOLERANCE
from pyflw.exceptions import BlockSpecError


def _flat(scope: Scope) -> np.ndarray:
    return np.asarray(scope.values).reshape(-1)


# ---------------------------------------------------------------------------
# 観点 1: biproper 単一 SISO — direct_feedthrough=True
# ---------------------------------------------------------------------------


class TestBiproper:
    def test_siso_biproper_direct_feedthrough_true(self) -> None:
        """H(s) = (s+1)/(s+2) (biproper) は direct_feedthrough=True になる。"""
        mimo = MimoTransferFunction(
            numerators=[[[1.0, 1.0]]],  # s+1
            denominator=[1.0, 2.0],    # s+2
        )
        assert mimo.direct_feedthrough is True

    def test_siso_strict_proper_direct_feedthrough_false(self) -> None:
        """H(s) = 1/(s+1) (strict proper) は direct_feedthrough=False になる。"""
        mimo = MimoTransferFunction(
            numerators=[[[1.0]]],
            denominator=[1.0, 1.0],
        )
        assert mimo.direct_feedthrough is False

    def test_siso_biproper_step_response_matches_analytic(self) -> None:
        """H(s) = (s+1)/(s+2) の Step 応答が解析解に一致する。

        U(s) = 1/s、Y(s) = (s+1) / (s*(s+2))。
        部分分数: Y(s) = 1/(2s) + 1/(2*(s+2))。
        y(t) = 1/2 + 1/2 * exp(-2t)。
        """
        sim = Simulator(t_end=2.0, dt=0.01, rtol=1e-8, atol=1e-10)
        src = sim.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0))
        mimo = sim.add(
            MimoTransferFunction(
                numerators=[[[1.0, 1.0]]],
                denominator=[1.0, 2.0],
            )
        )
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(src, mimo)
        sim.connect(mimo, sc)
        sim.run()

        arr = _flat(sc)
        times = np.array(sc.times)
        for k in (50, 100, 150):
            t = times[k]
            expected = 0.5 + 0.5 * np.exp(-2.0 * t)
            assert arr[k] == pytest.approx(expected, abs=1e-5)

    def test_siso_biproper_matches_transfer_function_block(self) -> None:
        """biproper MimoTF と TransferFunction の数値一致検証。"""
        num = [2.0, 3.0]   # 2s + 3
        den = [1.0, 4.0]   # s + 4

        sim_a = Simulator(t_end=1.0, dt=0.01, rtol=1e-9, atol=1e-12)
        src_a = sim_a.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0))
        tf_a = sim_a.add(TransferFunction(numerator=num, denominator=den))
        sc_a = sim_a.add(Scope(n_inputs=1))
        sim_a.connect(src_a, tf_a)
        sim_a.connect(tf_a, sc_a)
        sim_a.run()

        sim_b = Simulator(t_end=1.0, dt=0.01, rtol=1e-9, atol=1e-12)
        src_b = sim_b.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0))
        mimo_b = sim_b.add(
            MimoTransferFunction(numerators=[[num]], denominator=den)
        )
        sc_b = sim_b.add(Scope(n_inputs=1))
        sim_b.connect(src_b, mimo_b)
        sim_b.connect(mimo_b, sc_b)
        sim_b.run()

        np.testing.assert_allclose(_flat(sc_a), _flat(sc_b), atol=1e-6)


# ---------------------------------------------------------------------------
# 観点 2: MIMO biproper/strict-proper 混在 — D 行列一部非ゼロ
# ---------------------------------------------------------------------------


class TestBiproperMimoCases:
    def test_mixed_biproper_strict_proper_direct_feedthrough(self) -> None:
        """2x2 MIMO で [0,0] biproper・他 strict proper → direct_feedthrough=True。

        H(s) = [[(s+1)/(s+2),  1/(s+2)],
                [1/(s+2),      1/(s+2)]]
        (0,0) は biproper → D[0,0] != 0 → direct_feedthrough=True
        """
        mimo = MimoTransferFunction(
            numerators=[
                [[1.0, 1.0], [1.0]],   # row 0: [(s+1)/(s+2), 1/(s+2)]
                [[1.0], [1.0]],         # row 1: [1/(s+2), 1/(s+2)]
            ],
            denominator=[1.0, 2.0],
        )
        assert mimo.direct_feedthrough is True
        # D[0,0] が biproper 由来で非ゼロ
        assert abs(mimo._D[0, 0]) > _DF_TOLERANCE
        # D[0,1], D[1,0], D[1,1] はゼロ (strict proper)
        assert abs(mimo._D[0, 1]) <= _DF_TOLERANCE
        assert abs(mimo._D[1, 0]) <= _DF_TOLERANCE
        assert abs(mimo._D[1, 1]) <= _DF_TOLERANCE

    def test_all_strict_proper_direct_feedthrough_false(self) -> None:
        """全要素 strict proper → direct_feedthrough=False、D はゼロ行列。"""
        mimo = MimoTransferFunction(
            numerators=[
                [[1.0], [2.0]],
                [[3.0], [4.0]],
            ],
            denominator=[1.0, 5.0, 6.0],
        )
        assert mimo.direct_feedthrough is False
        np.testing.assert_array_equal(mimo._D, np.zeros((2, 2)))

    def test_mixed_biproper_step_response(self) -> None:
        """biproper (0,0) と strict proper (0,1) 混在の 1x2 MIMO Step 応答確認。

        H(s) = [[(s+1)/(s+2),  1/(s+2)]]
        u1=u2=1(Step)
        y = (1/2 + 1/2*e^{-2t}) + 0.5*(1 - e^{-2t})
          = 1
        """
        sim = Simulator(t_end=2.0, dt=0.01, rtol=1e-9, atol=1e-12)
        u1 = sim.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0))
        u2 = sim.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0))
        mimo = sim.add(
            MimoTransferFunction(
                numerators=[[[1.0, 1.0], [1.0]]],
                denominator=[1.0, 2.0],
            )
        )
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(u1, mimo, dst_idx=0)
        sim.connect(u2, mimo, dst_idx=1)
        sim.connect(mimo, sc)
        sim.run()

        arr = _flat(sc)
        times = np.array(sc.times)
        for k in (50, 100, 150):
            t = times[k]
            # H00*(s+1)/(s+2) Step : 1/2 + 1/2*exp(-2t)
            # H01=1/(s+2) Step : 0.5*(1-exp(-2t))
            expected = (0.5 + 0.5 * np.exp(-2.0 * t)) + 0.5 * (1.0 - np.exp(-2.0 * t))
            assert arr[k] == pytest.approx(expected, abs=1e-4)


# ---------------------------------------------------------------------------
# 観点 3: 高次 (n=5) companion form の数値安定性
# ---------------------------------------------------------------------------


class TestHighOrderNumericalStability:
    def test_5th_order_companion_form_shape(self) -> None:
        """deg(den)=5 の companion form が正しい形状を持つ。"""
        # 5 つの実安定極: (s+1)(s+2)(s+3)(s+4)(s+5)
        roots = [-1.0, -2.0, -3.0, -4.0, -5.0]
        poly = np.poly(roots)  # shape (6,)
        mimo = MimoTransferFunction(
            numerators=[[[1.0]]],
            denominator=list(poly),
        )
        assert mimo.n_states == 5
        assert mimo._A.shape == (5, 5)
        assert mimo._B.shape == (5, 1)
        assert mimo._C.shape == (1, 5)

    def test_5th_order_step_response_matches_scipy(self) -> None:
        """deg(den)=5 の Step 応答が scipy.signal.lsim と一致する (数値安定性)。

        H(s) = 1 / ((s+1)(s+2)(s+3)(s+4)(s+5))
        DC gain = 1/(1*2*3*4*5) = 1/120
        """
        roots = [-1.0, -2.0, -3.0, -4.0, -5.0]
        den_poly = np.poly(roots)
        num_poly = [1.0]

        sim = Simulator(t_end=5.0, dt=0.01, rtol=1e-9, atol=1e-12)
        src = sim.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0))
        mimo = sim.add(
            MimoTransferFunction(
                numerators=[[num_poly]],
                denominator=list(den_poly),
            )
        )
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(src, mimo)
        sim.connect(mimo, sc)
        sim.run()

        arr = _flat(sc)
        times = np.array(sc.times)

        # scipy.signal.lsim で参照解を生成
        sys_ref = scipy.signal.TransferFunction(num_poly, den_poly)
        u_ref = np.ones_like(times)  # Step 入力 (t>=0 で 1)
        _, y_ref, _ = scipy.signal.lsim(sys_ref, u_ref, times)

        np.testing.assert_allclose(arr, y_ref, rtol=1e-4, atol=1e-7)

    def test_5th_order_dc_gain(self) -> None:
        """定常値が DC ゲイン 1/120 に収束する (最終値定理)。"""
        roots = [-1.0, -2.0, -3.0, -4.0, -5.0]
        den_poly = np.poly(roots)

        sim = Simulator(t_end=20.0, dt=0.05, rtol=1e-9, atol=1e-12)
        src = sim.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0))
        mimo = sim.add(
            MimoTransferFunction(numerators=[[[1.0]]], denominator=list(den_poly))
        )
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(src, mimo)
        sim.connect(mimo, sc)
        sim.run()

        arr = _flat(sc)
        # 後半 20% を定常値として評価
        steady = arr[int(len(arr) * 0.8):]
        dc_gain = 1.0 / (1.0 * 2.0 * 3.0 * 4.0 * 5.0)  # 1/120
        np.testing.assert_allclose(np.mean(steady), dc_gain, rtol=1e-3)


# ---------------------------------------------------------------------------
# 観点 4: SIMO (p=3, q=1) / MISO (p=1, q=3)
# ---------------------------------------------------------------------------


class TestSimoMiso:
    def test_simo_shape_and_outputs(self) -> None:
        """SIMO (3 outputs, 1 input): 形状が正しく、各出力が独立した TF に従う。

        H(s) = [[1/(s+1)],
                [2/(s+2)],
                [3/(s+3)]]
        """
        mimo = MimoTransferFunction(
            numerators=[
                [[1.0]],    # 1/(s+1)
                [[2.0]],    # 2/(s+2)
                [[3.0]],    # 3/(s+3)
            ],
            denominator=[1.0, 6.0, 11.0, 6.0],  # (s+1)(s+2)(s+3)
        )
        # p=3, q=1, n=3 → n_states = 3*1*3 = 9
        assert mimo.n_inputs == 1
        assert mimo.n_outputs == 3
        assert mimo.n_states == 9
        assert mimo._A.shape == (9, 9)
        assert mimo._B.shape == (9, 1)
        assert mimo._C.shape == (3, 9)
        assert mimo._D.shape == (3, 1)

    def test_simo_step_response(self) -> None:
        """SIMO H(s) = [[1/(s+1)], [2/(s+1)]] の Step 応答検証。

        共通分母 (s+1)、入力 1 つ、出力 2 つ。
        y0 = 1*(1 - exp(-t))、y1 = 2*(1 - exp(-t))。
        """
        sim = Simulator(t_end=2.0, dt=0.01, rtol=1e-9, atol=1e-12)
        src = sim.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0))
        mimo = sim.add(
            MimoTransferFunction(
                numerators=[[[1.0]], [[2.0]]],
                denominator=[1.0, 1.0],
            )
        )
        sc0 = sim.add(Scope(n_inputs=1, id="sc0"))
        sc1 = sim.add(Scope(n_inputs=1, id="sc1"))
        sim.connect(src, mimo, dst_idx=0)
        sim.connect(mimo, sc0, src_idx=0)
        sim.connect(mimo, sc1, src_idx=1)
        sim.run()

        arr0 = _flat(sc0)
        arr1 = _flat(sc1)
        times = np.array(sc0.times)
        for k in (50, 100, 150):
            t = times[k]
            assert arr0[k] == pytest.approx(1.0 * (1.0 - np.exp(-t)), abs=1e-5)
            assert arr1[k] == pytest.approx(2.0 * (1.0 - np.exp(-t)), abs=1e-5)

    def test_miso_shape_and_outputs(self) -> None:
        """MISO (1 output, 3 inputs): 形状が正しく、出力が全入力の合計に従う。

        H(s) = [[1/(s+1), 1/(s+1), 1/(s+1)]]
        """
        mimo = MimoTransferFunction(
            numerators=[[[1.0], [1.0], [1.0]]],
            denominator=[1.0, 1.0],
        )
        # p=1, q=3, n=1 → n_states = 1*3*1 = 3
        assert mimo.n_inputs == 3
        assert mimo.n_outputs == 1
        assert mimo.n_states == 3
        assert mimo._A.shape == (3, 3)
        assert mimo._B.shape == (3, 3)
        assert mimo._C.shape == (1, 3)
        assert mimo._D.shape == (1, 3)

    def test_miso_step_response(self) -> None:
        """MISO H(s) = [[1/(s+1), 2/(s+1), 3/(s+1)]] の Step 応答検証。

        u0=u1=u2=1 なので y = (1+2+3)*(1-exp(-t)) = 6*(1-exp(-t))。
        """
        sim = Simulator(t_end=2.0, dt=0.01, rtol=1e-9, atol=1e-12)
        u0 = sim.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0, id="u0"))
        u1 = sim.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0, id="u1"))
        u2 = sim.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0, id="u2"))
        mimo = sim.add(
            MimoTransferFunction(
                numerators=[[[1.0], [2.0], [3.0]]],
                denominator=[1.0, 1.0],
            )
        )
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(u0, mimo, dst_idx=0)
        sim.connect(u1, mimo, dst_idx=1)
        sim.connect(u2, mimo, dst_idx=2)
        sim.connect(mimo, sc)
        sim.run()

        arr = _flat(sc)
        times = np.array(sc.times)
        for k in (50, 100, 150):
            t = times[k]
            expected = 6.0 * (1.0 - np.exp(-t))
            assert arr[k] == pytest.approx(expected, abs=1e-4)


# ---------------------------------------------------------------------------
# 観点 5: x0 初期状態指定
# ---------------------------------------------------------------------------


class TestInitialState:
    def test_zero_x0_default(self) -> None:
        """x0 未指定時はゼロベクトル (shape (p*q*n,))。"""
        # p=1, q=1, n=2 → n_total=2
        mimo = MimoTransferFunction(
            numerators=[[[1.0, 2.0]]],
            denominator=[1.0, 3.0, 2.0],
        )
        np.testing.assert_array_equal(mimo.x0, np.zeros(2))

    def test_nonzero_x0_is_stored(self) -> None:
        """指定した x0 が正しく格納される。"""
        # p=1, q=1, n=2 → n_total=2
        x0_val = np.array([1.0, -0.5])
        mimo = MimoTransferFunction(
            numerators=[[[1.0, 2.0]]],
            denominator=[1.0, 3.0, 2.0],
            x0=x0_val,
        )
        np.testing.assert_array_equal(mimo.x0, x0_val)

    def test_wrong_x0_shape_raises(self) -> None:
        """x0 の shape が (p*q*n,) でなければ BlockSpecError。"""
        with pytest.raises(BlockSpecError, match="x0 must have shape"):
            MimoTransferFunction(
                numerators=[[[1.0]]],
                denominator=[1.0, 1.0],
                x0=np.array([1.0, 2.0]),  # shape (2,) is wrong; expected (1,)
            )

    def test_nonzero_x0_differs_from_zero_x0(self) -> None:
        """非ゼロ x0 と ゼロ x0 で出力が異なる (自由応答が加算される)。

        H(s) = 1/(s+1)、x0=[1.0]。
        強制応答 (ゼロ x0): 1 - exp(-t)。
        非ゼロ x0 の自由応答: exp(-t)。
        合計: y_nonzero = (1 - exp(-t)) + exp(-t) = 1。
        (初期状態 x0=1 を使った場合、DC steady state に即時到達)
        """
        # ゼロ x0 の系
        sim_zero = Simulator(t_end=1.0, dt=0.01, rtol=1e-9, atol=1e-12)
        src_z = sim_zero.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0))
        mimo_z = sim_zero.add(
            MimoTransferFunction(
                numerators=[[[1.0]]],
                denominator=[1.0, 1.0],
                x0=None,
            )
        )
        sc_z = sim_zero.add(Scope(n_inputs=1))
        sim_zero.connect(src_z, mimo_z)
        sim_zero.connect(mimo_z, sc_z)
        sim_zero.run()

        # 非ゼロ x0 = [1.0] の系
        sim_nz = Simulator(t_end=1.0, dt=0.01, rtol=1e-9, atol=1e-12)
        src_nz = sim_nz.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0))
        mimo_nz = sim_nz.add(
            MimoTransferFunction(
                numerators=[[[1.0]]],
                denominator=[1.0, 1.0],
                x0=np.array([1.0]),
            )
        )
        sc_nz = sim_nz.add(Scope(n_inputs=1))
        sim_nz.connect(src_nz, mimo_nz)
        sim_nz.connect(mimo_nz, sc_nz)
        sim_nz.run()

        arr_z = _flat(sc_z)
        arr_nz = _flat(sc_nz)
        times = np.array(sc_z.times)

        # 2 つの軌跡は異なる
        assert not np.allclose(arr_z, arr_nz, atol=1e-4)

        # 非ゼロ x0 版は t>0 ですぐに ~1 に近い (自由応答 + 強制応答 ≈ 1)
        # 解析解: y = (1 - exp(-t)) + exp(-t) = 1
        for k in (1, 5, 20):
            assert arr_nz[k] == pytest.approx(1.0, abs=1e-4)
        del times  # 使わない

    def test_x0_for_mimo_2x2(self) -> None:
        """2x2 MIMO (n=1) の x0 shape は (2*2*1,) = (4,)。"""
        x0_val = np.array([0.1, 0.2, 0.3, 0.4])
        mimo = MimoTransferFunction(
            numerators=[
                [[1.0], [0.5]],
                [[0.0], [2.0]],
            ],
            denominator=[1.0, 1.0],
            x0=x0_val,
        )
        np.testing.assert_array_equal(mimo.x0, x0_val)


# ---------------------------------------------------------------------------
# 観点 6: JSON round-trip + run() — save → load → run で結果が一致
# ---------------------------------------------------------------------------


class TestJsonRoundTripRun:
    def test_roundtrip_run_results_match(self, tmp_path) -> None:
        """save → load → run で Step 応答が元の結果と一致する。"""
        path = tmp_path / "mimo_roundtrip.flw.json"

        # オリジナル run
        sim1 = Simulator(t_end=1.0, dt=0.01, rtol=1e-9, atol=1e-12)
        sim1.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0, id="src"))
        sim1.add(
            MimoTransferFunction(
                numerators=[[[1.0, 2.0], [0.5, 1.0]]],
                denominator=[1.0, 3.0, 2.0],
                id="mimo",
            )
        )
        sc1 = sim1.add(Scope(n_inputs=1, id="sc"))
        sim1.connect("src", "mimo", dst_idx=0)
        sim1.connect("src", "mimo", dst_idx=1)
        sim1.connect("mimo", "sc", src_idx=0)
        sim1.run()
        arr1 = _flat(sc1)

        sim1.save(path)

        # ロード後 run
        sim2 = Simulator.load(path)
        sim2.run()
        sc2 = sim2.get_block("sc")
        arr2 = _flat(sc2)

        np.testing.assert_allclose(arr1, arr2, rtol=1e-9, atol=1e-12)

    def test_roundtrip_with_nonzero_x0(self, tmp_path) -> None:
        """非ゼロ x0 を持つ MIMO TF の round-trip で x0 が正しく復元される。"""
        path = tmp_path / "mimo_x0_rt.flw.json"
        x0_val = np.array([0.5, -0.3])

        sim1 = Simulator(t_end=0.5, dt=0.01)
        sim1.add(
            MimoTransferFunction(
                numerators=[[[1.0, 2.0]]],
                denominator=[1.0, 3.0, 2.0],
                x0=x0_val,
                id="mimo",
            )
        )
        sim1.save(path)

        sim2 = Simulator.load(path)
        mimo2 = sim2.get_block("mimo")
        np.testing.assert_allclose(mimo2.x0, x0_val, atol=1e-12)

    def test_roundtrip_simo_structure(self, tmp_path) -> None:
        """SIMO (p=3, q=1) の save/load でブロック構造が復元される。"""
        path = tmp_path / "simo_rt.flw.json"

        sim1 = Simulator(t_end=0.1, dt=0.01)
        sim1.add(
            MimoTransferFunction(
                numerators=[[[1.0]], [[2.0]], [[3.0]]],
                denominator=[1.0, 1.0],
                id="simo",
            )
        )
        sim1.save(path)

        sim2 = Simulator.load(path)
        simo2 = sim2.get_block("simo")
        assert simo2.n_inputs == 1
        assert simo2.n_outputs == 3
        assert simo2.n_states == 3  # 3*1*1


# ---------------------------------------------------------------------------
# 観点 7: ゼロ多項式複数混ざる疎な MIMO TF
# ---------------------------------------------------------------------------


class TestSparseMimo:
    def test_all_zeros_except_one_element(self) -> None:
        """H = [[0, 0], [0, 1/(s+1)]] — ゼロ以外は (1,1) のみ。"""
        sim = Simulator(t_end=1.0, dt=0.01, rtol=1e-9, atol=1e-12)
        u1 = sim.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0, id="u1"))
        u2 = sim.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0, id="u2"))
        mimo = sim.add(
            MimoTransferFunction(
                numerators=[
                    [[0.0], [0.0]],
                    [[0.0], [1.0]],
                ],
                denominator=[1.0, 1.0],
            )
        )
        sc0 = sim.add(Scope(n_inputs=1, id="sc0"))
        sc1 = sim.add(Scope(n_inputs=1, id="sc1"))
        sim.connect(u1, mimo, dst_idx=0)
        sim.connect(u2, mimo, dst_idx=1)
        sim.connect(mimo, sc0, src_idx=0)
        sim.connect(mimo, sc1, src_idx=1)
        sim.run()

        arr0 = _flat(sc0)
        arr1 = _flat(sc1)
        times = np.array(sc0.times)

        # y0 は常に 0
        np.testing.assert_allclose(arr0, np.zeros_like(arr0), atol=1e-10)

        # y1 = 1 - exp(-t)
        for k in (10, 50, 100):
            t = times[k]
            assert arr1[k] == pytest.approx(1.0 - np.exp(-t), abs=1e-5)

    def test_first_row_all_zeros(self) -> None:
        """H = [[0, 0], [1/(s+1), 1/(s+2)]] — 第 1 行全ゼロ。"""
        mimo = MimoTransferFunction(
            numerators=[
                [[0.0], [0.0]],
                [[1.0], [1.0]],
            ],
            denominator=[1.0, 3.0, 2.0],
        )
        # n_states = p*q*n = 2*2*2 = 8
        assert mimo.n_states == 8
        # B/C 行列の第 0 行出力は 0 (ゼロ numerator block)
        # C の第 0 行 (output 0) はゼロ
        np.testing.assert_array_equal(mimo._C[0, :], np.zeros(8))

    def test_single_column_only_one_nonzero(self) -> None:
        """H = [[0], [0], [1/(s+1)]] — SIMO で最終行のみ非ゼロ。"""
        sim = Simulator(t_end=1.0, dt=0.01, rtol=1e-9, atol=1e-12)
        src = sim.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0))
        mimo = sim.add(
            MimoTransferFunction(
                numerators=[[[0.0]], [[0.0]], [[1.0]]],
                denominator=[1.0, 1.0],
            )
        )
        sc0 = sim.add(Scope(n_inputs=1, id="sc0"))
        sc1 = sim.add(Scope(n_inputs=1, id="sc1"))
        sc2 = sim.add(Scope(n_inputs=1, id="sc2"))
        sim.connect(src, mimo, dst_idx=0)
        sim.connect(mimo, sc0, src_idx=0)
        sim.connect(mimo, sc1, src_idx=1)
        sim.connect(mimo, sc2, src_idx=2)
        sim.run()

        arr0 = _flat(sc0)
        arr1 = _flat(sc1)
        arr2 = _flat(sc2)
        times = np.array(sc2.times)

        np.testing.assert_allclose(arr0, np.zeros_like(arr0), atol=1e-10)
        np.testing.assert_allclose(arr1, np.zeros_like(arr1), atol=1e-10)
        for k in (10, 50, 100):
            assert arr2[k] == pytest.approx(1.0 - np.exp(-times[k]), abs=1e-5)


# ---------------------------------------------------------------------------
# 観点 8: 連続→MIMO→連続 のフロー
# ---------------------------------------------------------------------------


class TestContinuousChain:
    def test_integrator_mimo_integrator(self) -> None:
        """Constant → Integrator → MimoTF → Integrator → Scope。

        入力 u=1 → Integrator → y_int1 = t。
        y_int1 を MimoTF H(s)=1/(s+1) に入力 → H の出力 = L^{-1}{1/(s*(s+1))} = 1-exp(-t)。
        (実際は Integrator が出力 x=t を供給するので数値計算の近似が入る)
        最終 Integrator は積分するのでここでは応答が 0 でない (クラッシュしないこと確認)。
        """
        sim = Simulator(t_end=1.0, dt=0.01, rtol=1e-8, atol=1e-10)
        src = sim.add(Constant(value=1.0))
        int1 = sim.add(Integrator(x0=0.0))
        mimo = sim.add(
            MimoTransferFunction(
                numerators=[[[1.0]]],
                denominator=[1.0, 1.0],
            )
        )
        int2 = sim.add(Integrator(x0=0.0))
        sc = sim.add(Scope(n_inputs=1))

        sim.connect(src, int1)
        sim.connect(int1, mimo)
        sim.connect(mimo, int2)
        sim.connect(int2, sc)
        sim.run()

        arr = _flat(sc)
        # クラッシュなし + 最終値は正の有限値であること
        assert np.isfinite(arr).all()
        assert arr[-1] > 0.0

    def test_mimo_output_feeds_back_via_integrator(self) -> None:
        """MimoTF の出力を Integrator で積分して Scope に渡す閉ループっぽい構成。

        Constant(1) → MimoTF 1/(s+1) → Integrator → Scope。
        MimoTF 出力: 1 - exp(-t)。
        Integrator 出力: t - (1 - exp(-t)) = t + exp(-t) - 1。
        """
        sim = Simulator(t_end=2.0, dt=0.01, rtol=1e-9, atol=1e-12)
        src = sim.add(Constant(value=1.0))
        mimo = sim.add(
            MimoTransferFunction(
                numerators=[[[1.0]]],
                denominator=[1.0, 1.0],
            )
        )
        integ = sim.add(Integrator(x0=0.0))
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(src, mimo)
        sim.connect(mimo, integ)
        sim.connect(integ, sc)
        sim.run()

        arr = _flat(sc)
        times = np.array(sc.times)

        for k in (50, 100, 150):
            t = times[k]
            # 解析解: ∫_0^t (1 - exp(-τ)) dτ = t + exp(-t) - 1
            expected = t + np.exp(-t) - 1.0
            assert arr[k] == pytest.approx(expected, rel=1e-3, abs=1e-5)


# ---------------------------------------------------------------------------
# 観点 9: Subsystem 内部で MimoTransferFunction を使用
# ---------------------------------------------------------------------------


class TestMimoInSubsystem:
    def test_mimo_inside_subsystem_basic(self) -> None:
        """Subsystem 内部に MimoTransferFunction を配置して正しく動作する。

        Subsystem: input → MimoTF 1/(s+1) → output。
        外部: Step → Subsystem → Scope。
        期待: 1 - exp(-t)。
        """
        from pyflw import Subsystem
        from pyflw.subsystems.ports import Inport, Outport

        sub = Subsystem(n_inputs=1, n_outputs=1, id="sub")
        sub.add(Inport(port_idx=0, id="sub_in"))
        sub.add(
            MimoTransferFunction(
                numerators=[[[1.0]]],
                denominator=[1.0, 1.0],
                id="sub_mimo",
            )
        )
        sub.add(Outport(port_idx=0, id="sub_out"))
        sub.connect("sub_in", "sub_mimo")
        sub.connect("sub_mimo", "sub_out")

        sim = Simulator(t_end=1.0, dt=0.01, rtol=1e-9, atol=1e-12)
        src = sim.add(Step(initial_value=0.0, final_value=1.0, step_time=0.0))
        sim.add(sub)
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(src, sub)
        sim.connect(sub, sc)
        sim.run()

        arr = _flat(sc)
        times = np.array(sc.times)
        for k in (10, 50, 100):
            t = times[k]
            assert arr[k] == pytest.approx(1.0 - np.exp(-t), abs=1e-5)

    def test_mimo_subsystem_direct_feedthrough_propagation(self) -> None:
        """biproper MimoTF を持つ Subsystem は direct_feedthrough=True を継承する。"""
        from pyflw import Subsystem
        from pyflw.subsystems.ports import Inport, Outport

        sub = Subsystem(n_inputs=1, n_outputs=1, id="sub_bp")
        sub.add(Inport(port_idx=0, id="in0"))
        sub.add(
            MimoTransferFunction(
                numerators=[[[1.0, 1.0]]],
                denominator=[1.0, 2.0],
                id="bp_mimo",
            )
        )
        sub.add(Outport(port_idx=0, id="out0"))
        sub.connect("in0", "bp_mimo")
        sub.connect("bp_mimo", "out0")

        # _build を発火させる
        dummy_x = np.zeros(1)
        dummy_u = np.zeros(1)
        sub.output(0.0, dummy_x, dummy_u)

        assert sub.direct_feedthrough is True


# ---------------------------------------------------------------------------
# 観点 10: derivative / output の直接呼び出し
# ---------------------------------------------------------------------------


class TestDirectMethodCall:
    def test_output_direct_call_without_simulator(self) -> None:
        """Simulator を通さずに output() を直接呼べる (連続ブロックは sample_time 解決不要)。"""
        mimo = MimoTransferFunction(
            numerators=[[[1.0]]],
            denominator=[1.0, 1.0],
        )
        x = np.array([0.5])
        u = np.array([1.0])
        y = mimo.output(0.0, x, u)
        # y = C*x + D*u = 1*0.5 + 0*1 = 0.5
        assert y.shape == (1,)
        assert y[0] == pytest.approx(0.5, abs=1e-10)

    def test_derivative_direct_call_without_simulator(self) -> None:
        """Simulator を通さずに derivative() を直接呼べる。

        H(s) = 1/(s+1): A=[[-1]], B=[[1]], C=[[1]], D=[[0]]
        xdot = A*x + B*u = -1*0.5 + 1*1 = 0.5
        """
        mimo = MimoTransferFunction(
            numerators=[[[1.0]]],
            denominator=[1.0, 1.0],
        )
        x = np.array([0.5])
        u = np.array([1.0])
        xdot = mimo.derivative(0.0, x, u)
        assert xdot.shape == (1,)
        assert xdot[0] == pytest.approx(0.5, abs=1e-10)

    def test_output_and_derivative_2x2_direct(self) -> None:
        """2x2 MIMO の output / derivative を直接呼び出して形状・値を確認。

        H(s) = [[1/(s+1), 0], [0, 2/(s+1)]]
        A: block-diag([[-1],[-1]])、B: block、C: [[1,0],[0,2]]、D=0
        x = [0.5, 0.3, 0.0, 0.0] (4 states for 2x2x1)
        u = [1.0, 0.5]
        y = C * x + D * u
        """
        mimo = MimoTransferFunction(
            numerators=[
                [[1.0], [0.0]],
                [[0.0], [2.0]],
            ],
            denominator=[1.0, 1.0],
        )
        # n_states = 2*2*1 = 4
        x = np.array([0.5, 0.3, 0.0, 0.0])
        u = np.array([1.0, 0.5])
        y = mimo.output(0.0, x, u)
        xdot = mimo.derivative(0.0, x, u)
        assert y.shape == (2,)
        assert xdot.shape == (4,)
        # 出力は有限値
        assert np.isfinite(y).all()
        assert np.isfinite(xdot).all()

    def test_output_biproper_direct_call(self) -> None:
        """biproper H(s)=(s+1)/(s+2): D=1、output に u が直接寄与する。"""
        mimo = MimoTransferFunction(
            numerators=[[[1.0, 1.0]]],
            denominator=[1.0, 2.0],
        )
        x = np.array([0.0])
        u = np.array([3.0])
        y = mimo.output(0.0, x, u)
        # y = C*x + D*u = C[0,0]*0 + 1*3 = 3
        # (x=0 なので C 寄与はゼロ)
        assert y[0] == pytest.approx(3.0, abs=1e-10)
