"""ADR-0027 §(10) A/B/F: Bode / Nyquist の数値検証 + 描画 smoke。

LTI ブロック (Integrator / 1 次系 / 2 次系) を線形化に流して bode 結果を解析解
と比較する。``rtol=1e-4`` (= SPEC §非機能要件「正確性」)。

``python-control`` extras (= ``flode[control]``) が CI で常時利用可能 (``dev``
extras 経由)。
"""

from __future__ import annotations

import numpy as np
import pytest

from flode import Simulator, linearize
from flode.analysis import bode, nyquist
from flode.blocks import Integrator, Scope, StateSpace, TransferFunction

pytest.importorskip("control")  # 全テストが python-control 必須

# matplotlib は Agg backend (CI 用 headless)
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# ---------------------------------------------------------------------------
# Bode 数値検証 (ADR-0027 §(10) A1〜A5)
# ---------------------------------------------------------------------------


class TestBodeAnalytical:
    """解析解との rtol=1e-4 比較。"""

    def test_integrator_bode(self) -> None:
        """Integrator: G(s) = 1/s → mag = 1/ω, phase = -π/2 (= -90°)。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls = linearize(sim)
        omega = np.logspace(-2, 2, 50)
        br = bode(ls, omega=omega)
        # SISO → shape (1, 1, n_omega)
        assert br.magnitude.shape == (1, 1, omega.size)
        np.testing.assert_allclose(br.magnitude[0, 0, :], 1.0 / omega, rtol=1e-4)
        np.testing.assert_allclose(br.phase[0, 0, :], -np.pi / 2 * np.ones_like(omega), rtol=1e-4)

    def test_first_order_lpf(self) -> None:
        """G(s) = 1/(s+1) → mag = 1/sqrt(1+ω²), phase = -atan(ω)。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        tf = sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0]))
        sim.connect(tf, sim.add(Scope()))
        ls = linearize(sim)
        omega = np.array([0.1, 0.5, 1.0, 2.0, 5.0, 10.0])
        br = bode(ls, omega=omega)
        expected_mag = 1.0 / np.sqrt(1.0 + omega**2)
        expected_phase = -np.arctan(omega)
        np.testing.assert_allclose(br.magnitude[0, 0, :], expected_mag, rtol=1e-4)
        np.testing.assert_allclose(br.phase[0, 0, :], expected_phase, rtol=1e-4)

    def test_second_order_resonance(self) -> None:
        """G(s) = 1/(s² + 0.4s + 1) (ζ=0.2, ωn=1) で共振ピーク確認。

        共振振幅 |G(jωr)| ≈ 1/(2ζ√(1-ζ²)) ≈ 2.55 at ωr ≈ ωn√(1-2ζ²) ≈ 0.96。
        """
        sim = Simulator(t_end=1.0, dt=0.01)
        tf = sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 0.4, 1.0]))
        sim.connect(tf, sim.add(Scope()))
        ls = linearize(sim)
        omega = np.linspace(0.85, 1.05, 21)  # 共振周辺を細かくサンプル
        br = bode(ls, omega=omega)
        peak_idx = int(np.argmax(br.magnitude[0, 0, :]))
        zeta = 0.2
        expected_peak = 1.0 / (2.0 * zeta * np.sqrt(1.0 - zeta**2))
        # 線形化は厳密なので、共振ピークは解析解と RTOL=1e-3 内
        np.testing.assert_allclose(br.magnitude[0, 0, peak_idx], expected_peak, rtol=1e-3)


class TestBodeReturnShape:
    """``BodeResponse`` の構造検証。"""

    def test_3d_shape_even_for_siso(self) -> None:
        """SISO 入力でも shape (1, 1, n_omega) を維持。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls = linearize(sim)
        br = bode(ls, omega=np.array([1.0, 10.0]))
        assert br.magnitude.ndim == 3
        assert br.magnitude.shape == (1, 1, 2)
        assert br.phase.shape == (1, 1, 2)

    def test_labels_inherited_from_linear_system(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator(id="my_int"))
        sim.connect(i, sim.add(Scope()))
        ls = linearize(sim)
        br = bode(ls, omega=np.array([1.0]))
        assert br.input_names == ls.input_names
        assert br.output_names == ls.output_names

    def test_omega_default_auto(self) -> None:
        """omega=None で python-control の自動 omega が使われ、出力が finite。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0]))
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls = linearize(sim)
        br = bode(ls)
        assert br.omega.size > 0
        assert np.all(np.isfinite(br.magnitude))
        assert np.all(np.isfinite(br.phase))

    def test_mimo_2x2_shape(self) -> None:
        """ADR-0027 §(10) A4: MIMO 2x2 で magnitude/phase shape が (2, 2, n_omega)。"""
        # 対角な状態空間 2x2: 各 channel は独立の 1 次系
        A = np.diag([-1.0, -2.0])
        B = np.eye(2)
        C = np.eye(2)
        D = np.zeros((2, 2))
        sim = Simulator(t_end=1.0, dt=0.01)
        ss = sim.add(StateSpace(A, B, C, D))
        # ADR-0079 D-9: 出力は (2,) のベクトルポート 1 本 (Scope が 2 列に展開)
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(ss, sc)
        ls = linearize(sim)
        omega = np.logspace(-1, 1, 7)
        br = bode(ls, omega=omega)
        # MIMO 3D shape (p, m, n_omega) = (2, 2, 7)
        assert br.magnitude.shape == (2, 2, 7)
        assert br.phase.shape == (2, 2, 7)
        # チャネル (0,0) は 1/(s+1)、解析解と一致 (rtol=1e-4)
        np.testing.assert_allclose(br.magnitude[0, 0, :], 1.0 / np.sqrt(1.0 + omega**2), rtol=1e-4)
        # チャネル (1,1) は 1/(s+2)
        np.testing.assert_allclose(br.magnitude[1, 1, :], 1.0 / np.sqrt(4.0 + omega**2), rtol=1e-4)
        # 対角 → off-diagonal はゼロ
        assert np.all(np.abs(br.magnitude[0, 1, :]) < 1e-9)
        assert np.all(np.abs(br.magnitude[1, 0, :]) < 1e-9)


class TestBodeMagnitudeDb:
    """``magnitude_db()`` のヘルパが 20*log10 を返す。"""

    def test_magnitude_db_value(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls = linearize(sim)
        omega = np.array([1.0])  # mag = 1.0 → 0 dB
        br = bode(ls, omega=omega)
        np.testing.assert_allclose(br.magnitude_db()[0, 0, 0], 0.0, atol=1e-9)


class TestBodeErrors:
    """例外パス。"""

    def test_omega_and_omega_limits_exclusive(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls = linearize(sim)
        from flode.exceptions import BlockSpecError

        with pytest.raises(BlockSpecError, match="omega or omega_limits"):
            bode(ls, omega=np.array([1.0]), omega_limits=(0.1, 10.0))


# ---------------------------------------------------------------------------
# Nyquist 数値検証 (ADR-0027 §(10) B)
# ---------------------------------------------------------------------------


class TestNyquist:
    def test_first_order_unit_circle_half(self) -> None:
        """G(s) = 1/(s+1) は単位円内の半円軌跡。原点の右半平面を通る。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        tf = sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0]))
        sim.connect(tf, sim.add(Scope()))
        ls = linearize(sim)
        omega = np.logspace(-2, 2, 100)
        ny = nyquist(ls, omega=omega)
        assert ny.response.shape == (1, 1, omega.size)
        # ω=0 で G(0)=1 (実軸上)、ω→∞ で G→0
        # サンプルした最低 omega での実部が 1 に近い
        g_low = ny.response[0, 0, 0]  # ω=0.01
        np.testing.assert_allclose(np.real(g_low), 1.0, rtol=1e-2)
        # 高 omega で magnitude が小さい
        g_high = ny.response[0, 0, -1]  # ω=100
        assert abs(g_high) < 0.05

    def test_response_dtype_complex(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls = linearize(sim)
        ny = nyquist(ls, omega=np.array([1.0]))
        assert np.iscomplexobj(ny.response)


# ---------------------------------------------------------------------------
# 描画 smoke (ADR-0027 §(10) F)
# ---------------------------------------------------------------------------


class TestPlotSmoke:
    """matplotlib の plot メソッドが Axes を返す。"""

    def test_bode_plot_with_default_axes(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls = linearize(sim)
        br = bode(ls, omega=np.logspace(-1, 1, 10))
        ax = br.plot()
        assert ax is not None
        plt.close("all")

    def test_bode_plot_with_existing_ax(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls = linearize(sim)
        br = bode(ls, omega=np.logspace(-1, 1, 10))
        fig, ax = plt.subplots()
        ax_ret = br.plot(ax=ax)
        assert ax_ret is ax
        plt.close("all")

    def test_nyquist_plot(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0]))
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls = linearize(sim)
        ny = nyquist(ls, omega=np.logspace(-2, 2, 20))
        ax = ny.plot()
        assert ax is not None
        plt.close("all")

    def test_bode_plot_idx_out_of_range(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls = linearize(sim)
        br = bode(ls, omega=np.array([1.0]))
        from flode.exceptions import BlockSpecError

        with pytest.raises(BlockSpecError, match="input_idx"):
            br.plot(input_idx=99)
        with pytest.raises(BlockSpecError, match="output_idx"):
            br.plot(output_idx=99)


# ---------------------------------------------------------------------------
# LinearSystem.bode / .nyquist メソッド版
# ---------------------------------------------------------------------------


class TestLinearSystemMethods:
    """``ls.bode()`` / ``ls.nyquist()`` が関数版と同じ結果を返す。"""

    def test_method_equivalent_to_function(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls = linearize(sim)
        omega = np.logspace(-1, 1, 10)
        br_f = bode(ls, omega=omega)
        br_m = ls.bode(omega=omega)
        np.testing.assert_allclose(br_f.magnitude, br_m.magnitude)
        np.testing.assert_allclose(br_f.phase, br_m.phase)
        ny_f = nyquist(ls, omega=omega)
        ny_m = ls.nyquist(omega=omega)
        np.testing.assert_allclose(ny_f.response, ny_m.response)
