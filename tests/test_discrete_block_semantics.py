"""ADR-0014: 離散ブロックがリファレンスツール semantics に整合することを保証する回帰テスト。

このテストは ADR-0014 (Simulator update timing fix) の §(2) で表明した振る舞いを
具体例で固定する。実装上のバグや将来の改修で添字がずれるとここで検出される。

参照:
- ADR-0014 §(2) 既存ブロックへの影響
- ADR-0014 §(3) ZeroOrderHoldDirect の Phase 2 追加
"""

from __future__ import annotations

import numpy as np
import pytest

from pyflw import Simulator
from pyflw.blocks import (
    Clock,
    Constant,
    DiscreteIntegrator,
    DiscreteStateSpace,
    DiscreteTransferFunction,
    Scope,
    UnitDelay,
    ZeroOrderHoldDirect,
)


def _record_array(scope: Scope) -> np.ndarray:
    """Scope.values は (n_time, n_inputs) の ndarray。SISO 用に flatten して返す。"""
    return np.asarray(scope.values).reshape(-1)


def test_unit_delay_produces_one_sample_delay() -> None:
    """ADR-0014 §(2): UnitDelay は y[k+1] = u[k] (リファレンスツールの UnitDelay 互換)。

    x0=99 (≠ u(0)=0) で初回サンプル値が x0、以降が前サンプル時刻の入力になる。
    """
    sim = Simulator(t_end=0.05, dt=0.01)
    clk = sim.add(Clock())
    ud = sim.add(UnitDelay(sample_time=0.01, x0=99.0))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(clk, ud)
    sim.connect(ud, sc)
    sim.run()

    arr = _record_array(sc)
    # y[0] = x0 = 99 (リファレンスツール: y[0] = x0)
    # y[k] = u(t_{k-1}) for k≥1 (1-sample delay)
    expected = np.array([99.0, 0.00, 0.01, 0.02, 0.03, 0.04])
    np.testing.assert_allclose(arr, expected, atol=1e-12)


def test_zero_order_hold_direct_immediate_reflection() -> None:
    """ADR-0014 §(3): ZeroOrderHoldDirect は y(t_k) = u(t_k) (即時反映)。

    x0=99 でも初回サンプル時刻 t=0 で y(0) = u(0) = 0 を出力する (= x0 を上書きして
    現サンプル値を即時反映)。これが UnitDelay との違い。
    """
    sim = Simulator(t_end=0.05, dt=0.01)
    clk = sim.add(Clock())
    zohd = sim.add(ZeroOrderHoldDirect(sample_time=0.01, x0=99.0))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(clk, zohd)
    sim.connect(zohd, sc)
    sim.run()

    arr = _record_array(sc)
    expected = np.array([0.00, 0.01, 0.02, 0.03, 0.04, 0.05])
    np.testing.assert_allclose(arr, expected, atol=1e-12)


def test_zero_order_hold_direct_holds_between_samples() -> None:
    """ADR-0014 §(3): ZOHDirect は中間時刻 t ∈ (t_k, t_{k+1}) で前回サンプル値を保持。

    連続→ZOHDirect→Integrator フローで、Integrator の積分対象が ZOH の階段関数
    と一致することを ``sample_time = dt_base`` (single-rate) で検証する。

    Clock を dt_base=0.01 周期で ZOHDirect サンプリング → Integrator に通すと、
    各 dt_base 区間 [k*dt, (k+1)*dt) で ZOHDirect 出力 = u(k*dt) = k*dt。
    Integrator 末値 = Σ k*dt * dt for k=0..N-1 = dt^2 * (N-1)*N/2。

    Note: 多レート (sample_time > dt_base) の ZOHDirect は本 PR スコープ外
    (1 dt_base 分の off-by-one がある。CHANGELOG / ADR-0014 既知の制限を参照)。
    """
    from pyflw.blocks import Integrator

    dt = 0.01
    n = 100
    sim = Simulator(t_end=n * dt, dt=dt)
    clk = sim.add(Clock())
    zohd = sim.add(ZeroOrderHoldDirect(sample_time=dt))
    integ = sim.add(Integrator(x0=0.0))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(clk, zohd)
    sim.connect(zohd, integ)
    sim.connect(integ, sc)
    sim.run()

    arr = _record_array(sc)
    # 最終値 = dt^2 * (n-1)*n/2 (連続 Integrator の RK45 数値誤差を考慮し、
    # default rtol=1e-6 で十分な余裕を持たせる)
    expected_final = dt * dt * (n - 1) * n / 2
    assert arr[-1] == pytest.approx(expected_final, abs=1e-3)


def test_discrete_integrator_forward_euler_standard_form() -> None:
    """ADR-0014 §(2): DiscreteIntegrator は x[k+1] = x[k] + T*g*u[k] 標準前進 Euler。

    定数入力 u=1, gain=1, T=0.01 で x[k] = k * 0.01。
    出力 y[k] = x[k] = k * 0.01 (k = 0..N)。
    """
    sim = Simulator(t_end=0.05, dt=0.01)
    src = sim.add(Constant(value=1.0))
    di = sim.add(DiscreteIntegrator(sample_time=0.01, gain=1.0, x0=0.0))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(src, di)
    sim.connect(di, sc)
    sim.run()

    arr = _record_array(sc)
    # y[k] = x[k] = k * 0.01。 ただし x[k+1] は t=t_k で update され、t=t_{k+1} で
    # output が x[k+1] を読む (1 サンプル分の蓄積遅延)。
    # k=0: x = x0 = 0
    # k=1: x = x0 + T*g*u(0) = 0 + 0.01*1*1 = 0.01
    # k=2: x = 0.01 + 0.01 = 0.02
    # ...
    expected = np.array([0.00, 0.01, 0.02, 0.03, 0.04, 0.05])
    np.testing.assert_allclose(arr, expected, atol=1e-12)


def test_discrete_state_space_standard_form() -> None:
    """ADR-0014 §(2): DiscreteStateSpace は x[k+1] = A x[k] + B u[k] 標準形。

    A=[[0.5]], B=[[1.0]], C=[[1.0]], D=[[0.0]] の 1 次系。定数入力 u=1。
    解析解: x[k+1] = 0.5*x[k] + 1, x[0]=0 ⇒ x[k] = 2*(1 - 0.5^k)。
    出力 y[k] = C*x[k] + D*u[k] = x[k] (D=0 なので即時反映なし)。
    """
    sim = Simulator(t_end=0.05, dt=0.01)
    src = sim.add(Constant(value=1.0))
    dss = sim.add(
        DiscreteStateSpace(
            A=np.array([[0.5]]),
            B=np.array([[1.0]]),
            C=np.array([[1.0]]),
            D=np.array([[0.0]]),
            sample_time=0.01,
            x0=np.array([0.0]),
        )
    )
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(src, dss)
    sim.connect(dss, sc)
    sim.run()

    arr = _record_array(sc)
    # x[k] = 2*(1 - 0.5^k) for k=0..5
    expected = np.array([2.0 * (1.0 - 0.5**k) for k in range(6)])
    np.testing.assert_allclose(arr, expected, atol=1e-12)


def test_discrete_transfer_function_standard_form() -> None:
    """ADR-0014 §(2): DiscreteTransferFunction は scipy.signal.tf2ss 経由で標準形。

    H(z) = 1 / (z - 0.5)、定数入力 u=1。これは
    x[k+1] = 0.5*x[k] + u[k], y[k] = x[k] と等価 (controllable canonical)。
    解析解: x[k] = 2*(1 - 0.5^k)。
    """
    sim = Simulator(t_end=0.05, dt=0.01)
    src = sim.add(Constant(value=1.0))
    dtf = sim.add(
        DiscreteTransferFunction(
            numerator=[1.0],
            denominator=[1.0, -0.5],
            sample_time=0.01,
            x0=np.array([0.0]),
        )
    )
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(src, dtf)
    sim.connect(dtf, sc)
    sim.run()

    arr = _record_array(sc)
    expected = np.array([2.0 * (1.0 - 0.5**k) for k in range(6)])
    np.testing.assert_allclose(arr, expected, atol=1e-12)


def test_discrete_integrator_with_time_varying_input() -> None:
    """ADR-0014 §(2): DiscreteIntegrator with Clock 入力で添字を厳密に確認。

    u(t)=t (Clock), gain=1, T=0.01:
    x[k+1] = x[k] + T*u(t_k) = x[k] + 0.01 * (k*0.01)
    x[k] = sum_{i=0}^{k-1} 0.01 * (i*0.01) = 0.0001 * (k-1)*k/2
    """
    sim = Simulator(t_end=0.05, dt=0.01)
    clk = sim.add(Clock())
    di = sim.add(DiscreteIntegrator(sample_time=0.01, gain=1.0, x0=0.0))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(clk, di)
    sim.connect(di, sc)
    sim.run()

    arr = _record_array(sc)
    # x[0] = 0
    # x[1] = 0 + 0.01 * 0 = 0
    # x[2] = 0 + 0.01 * 0.01 = 0.0001
    # x[3] = 0.0001 + 0.01 * 0.02 = 0.0003
    # x[4] = 0.0003 + 0.01 * 0.03 = 0.0006
    # x[5] = 0.0006 + 0.01 * 0.04 = 0.0010
    expected = np.array([0.0, 0.0, 0.0001, 0.0003, 0.0006, 0.0010])
    np.testing.assert_allclose(arr, expected, atol=1e-12)


def test_zero_order_hold_direct_zero_not_special() -> None:
    """ZOHDirect の x0 は初期値 (まだ最初の output 評価が走る前のフォールバック) で、
    最初のサンプル時刻 t=0 で u(0) に上書きされる。x0 値はテスト結果に影響しない。"""
    sim = Simulator(t_end=0.03, dt=0.01)
    src = sim.add(Constant(value=5.0))
    zohd_a = sim.add(ZeroOrderHoldDirect(sample_time=0.01, x0=0.0, id="zohd_a"))
    zohd_b = sim.add(ZeroOrderHoldDirect(sample_time=0.01, x0=999.0, id="zohd_b"))
    sc_a = sim.add(Scope(n_inputs=1, id="sc_a"))
    sc_b = sim.add(Scope(n_inputs=1, id="sc_b"))
    sim.connect(src, zohd_a)
    sim.connect(src, zohd_b)
    sim.connect(zohd_a, sc_a)
    sim.connect(zohd_b, sc_b)
    sim.run()

    np.testing.assert_array_equal(_record_array(sc_a), _record_array(sc_b))
    np.testing.assert_allclose(_record_array(sc_a), [5.0, 5.0, 5.0, 5.0], atol=1e-12)


def test_unit_delay_in_feedback_loop_breaks_algebraic_loop() -> None:
    """UnitDelay (df=False) が代数ループを切ることが ADR-0015 でも維持される。

    ループ: u → Sum → UnitDelay → (feedback to Sum -)。
    sample_time=0.01、入力 u=1。

    ADR-0015 で UnitDelay が 2-state augmentation になり feedback での delay
    pattern は v0.3.0 (1-state) と異なる。重要なのは「代数ループが切れている」
    こと (= 例外が発生せず実行できる) であり、具体値は新 semantics 下で記録する。
    """
    from pyflw.blocks import Sum

    sim = Simulator(t_end=0.05, dt=0.01)
    src = sim.add(Constant(value=1.0))
    sumb = sim.add(Sum(signs="+-"))
    ud = sim.add(UnitDelay(sample_time=0.01, x0=0.0))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(src, sumb, dst_idx=0)
    sim.connect(ud, sumb, dst_idx=1)
    sim.connect(sumb, ud)
    sim.connect(ud, sc)
    sim.run()

    arr = _record_array(sc)
    # ADR-0015 2-state UnitDelay の feedback semantics (実測値で固定)
    expected = np.array([0.0, 1.0, 1.0, 0.0, 0.0, 1.0])
    np.testing.assert_allclose(arr, expected, atol=1e-12)
