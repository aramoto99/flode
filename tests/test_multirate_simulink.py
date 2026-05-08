"""ADR-0015: multi-rate (sample_time > dt_base) で全離散ブロックが Simulink semantics
と完全一致することを保証する回帰テスト。

v0.3.0 までの multi-rate off-by-one (UnitDelay で `1 dt_base` 分のずれ、
DiscreteIntegrator/StateSpace/TF で同様の挙動) は ADR-0015 で根本治療済み。

参照:
- ADR-0015 §(2)(3) UnitDelay の 2-state、DiscreteIntegrator/SS/TF の 2n-state
- ADR-0015 §(7) 新規 multi-rate Simulink semantics 検証
- legacy ``ZeroOrderHold`` は v0.13.0 (ADR-0033) で削除済 (= UnitDelay と完全同一
  挙動だったため別実装を残す価値がなかった)。Simulink ZOH 互換は
  ``ZeroOrderHoldDirect``。
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


def _flat(scope: Scope) -> np.ndarray:
    return np.asarray(scope.values).reshape(-1)


def _sample_indices(times: np.ndarray, sample_time: float, tol: float = 1e-9) -> list[int]:
    """sample_time の整数倍に該当する times の index リスト。"""
    return [i for i, t in enumerate(times) if abs(round(t / sample_time) * sample_time - t) < tol]


# ---------------------------------------------------------------------------
# UnitDelay multi-rate
# ---------------------------------------------------------------------------


def test_multirate_unit_delay_clock_input() -> None:
    """UnitDelay (sample_time=0.1, dt_base=0.01) で y(t in [n*T, (n+1)*T)) = u((n-1)*T)。

    Clock 入力 u(t)=t、x0=0:
    - y in [0, 0.1): x0 = 0
    - y in [0.1, 0.2): u(0) = 0
    - y in [0.2, 0.3): u(0.1) = 0.1
    - y in [0.3, 0.4): u(0.2) = 0.2
    - y in [0.4, 0.5): u(0.3) = 0.3
    """
    sim = Simulator(t_end=0.5, dt=0.01)
    clk = sim.add(Clock())
    ud = sim.add(UnitDelay(sample_time=0.1, x0=0.0))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(clk, ud)
    sim.connect(ud, sc)
    sim.run()

    arr = _flat(sc)
    times = np.array(sc.times)
    sample_idx = _sample_indices(times, 0.1)
    y_at_samples = arr[sample_idx]

    # 各サンプル時刻 t_n = n*0.1 で y(t_n) = u(t_{n-1}) = (n-1)*0.1 (n>=1), x0 (n=0)
    assert y_at_samples[0] == pytest.approx(0.0)  # x0
    assert y_at_samples[1] == pytest.approx(0.0, abs=1e-10)  # u(0)
    assert y_at_samples[2] == pytest.approx(0.1, abs=1e-10)  # u(0.1)
    assert y_at_samples[3] == pytest.approx(0.2, abs=1e-10)  # u(0.2)
    assert y_at_samples[4] == pytest.approx(0.3, abs=1e-10)  # u(0.3)


def test_multirate_unit_delay_constant_input() -> None:
    """UnitDelay multi-rate with Constant: y(t in [0, T)) = x0、y(t >= T) = u。"""
    sim = Simulator(t_end=0.3, dt=0.01)
    src = sim.add(Constant(value=5.0))
    ud = sim.add(UnitDelay(sample_time=0.1, x0=99.0))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(src, ud)
    sim.connect(ud, sc)
    sim.run()

    arr = _flat(sc)
    times = np.array(sc.times)
    # t in [0, 0.1) で 99 (= x0)
    for i, t in enumerate(times):
        if 0 <= t < 0.1 - 1e-9:
            assert arr[i] == pytest.approx(99.0), f"t={t}: expected 99 (x0)"
    # t >= 0.1 で 5 (= u)
    for i, t in enumerate(times):
        if t >= 0.1 - 1e-9:
            assert arr[i] == pytest.approx(5.0), f"t={t}: expected 5 (u)"


# ---------------------------------------------------------------------------
# ZeroOrderHoldDirect multi-rate
# ---------------------------------------------------------------------------


def test_multirate_zero_order_hold_direct_immediate_reflection() -> None:
    """ZOHDirect multi-rate: y(t in [n*T, (n+1)*T)) = u(n*T) (即時反映、df=True)。

    Clock 入力、sample_time=0.1:
    - y in [0, 0.1): u(0) = 0
    - y in [0.1, 0.2): u(0.1) = 0.1
    - y in [0.2, 0.3): u(0.2) = 0.2
    """
    sim = Simulator(t_end=0.3, dt=0.01)
    clk = sim.add(Clock())
    zohd = sim.add(ZeroOrderHoldDirect(sample_time=0.1))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(clk, zohd)
    sim.connect(zohd, sc)
    sim.run()

    arr = _flat(sc)
    times = np.array(sc.times)
    sample_idx = _sample_indices(times, 0.1)
    y_at_samples = arr[sample_idx]

    # ZOHDirect は即時反映なので y(n*T) = u(n*T) = n*T
    assert y_at_samples[0] == pytest.approx(0.0)
    assert y_at_samples[1] == pytest.approx(0.1, abs=1e-10)
    assert y_at_samples[2] == pytest.approx(0.2, abs=1e-10)


# ---------------------------------------------------------------------------
# DiscreteIntegrator multi-rate
# ---------------------------------------------------------------------------


def test_multirate_discrete_integrator_constant_input() -> None:
    """DiscreteIntegrator (sample_time=0.1, gain=1) Forward Euler 標準形 (Simulink 互換)。

    Constant u=1, x0=0:
        x[k+1] = x[k] + T*g*u[k]
        y(n*T) = x[n]
    → y = [0, 0.1, 0.2, 0.3, 0.4, 0.5]
    """
    sim = Simulator(t_end=0.5, dt=0.01)
    src = sim.add(Constant(value=1.0))
    di = sim.add(DiscreteIntegrator(sample_time=0.1, gain=1.0, x0=0.0))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(src, di)
    sim.connect(di, sc)
    sim.run()

    arr = _flat(sc)
    times = np.array(sc.times)
    sample_idx = _sample_indices(times, 0.1)
    y_at_samples = arr[sample_idx]

    expected = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    for i, val in enumerate(expected[: len(y_at_samples)]):
        assert y_at_samples[i] == pytest.approx(val, abs=1e-12), (
            f"sample {i}: expected {val}, got {y_at_samples[i]}"
        )


def test_multirate_discrete_integrator_clock_input() -> None:
    """DiscreteIntegrator multi-rate with Clock u(t)=t (Forward Euler 標準形)。

    x[k+1] = x[k] + T*g*u(k*T) = x[k] + 0.01*k
    y(0)   = 0
    y(0.1) = 0 + 0.01*0 = 0
    y(0.2) = 0 + 0.01*1 = 0.01
    y(0.3) = 0.01 + 0.01*2 = 0.03
    y(0.4) = 0.03 + 0.01*3 = 0.06
    y(0.5) = 0.06 + 0.01*4 = 0.10
    """
    sim = Simulator(t_end=0.5, dt=0.01)
    clk = sim.add(Clock())
    di = sim.add(DiscreteIntegrator(sample_time=0.1, gain=1.0, x0=0.0))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(clk, di)
    sim.connect(di, sc)
    sim.run()

    arr = _flat(sc)
    times = np.array(sc.times)
    sample_idx = _sample_indices(times, 0.1)
    y_at_samples = arr[sample_idx]

    expected = [0.0, 0.0, 0.01, 0.03, 0.06, 0.10]
    for i, val in enumerate(expected[: len(y_at_samples)]):
        assert y_at_samples[i] == pytest.approx(val, abs=1e-12), (
            f"sample {i}: expected {val}, got {y_at_samples[i]}"
        )


# ---------------------------------------------------------------------------
# DiscreteStateSpace multi-rate
# ---------------------------------------------------------------------------


def test_multirate_discrete_state_space_first_order() -> None:
    """1 次離散 SS x[k+1] = 0.5 x[k] + u[k] (constant u=1, x0=0) multi-rate。

    解析解 x[k] = 2*(1 - 0.5^k) (with k = sample index).
    """
    sim = Simulator(t_end=0.5, dt=0.01)
    src = sim.add(Constant(value=1.0))
    dss = sim.add(
        DiscreteStateSpace(
            A=np.array([[0.5]]),
            B=np.array([[1.0]]),
            C=np.array([[1.0]]),
            D=np.array([[0.0]]),
            sample_time=0.1,
            x0=np.array([0.0]),
        )
    )
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(src, dss)
    sim.connect(dss, sc)
    sim.run()

    arr = _flat(sc)
    times = np.array(sc.times)
    sample_idx = _sample_indices(times, 0.1)
    y_at_samples = arr[sample_idx]

    # y(n*T) = x[n] = 2*(1 - 0.5^n) (geometric series for x[k+1]=0.5*x[k]+1, x[0]=0)
    expected = [2.0 * (1.0 - 0.5**n) for n in range(len(y_at_samples))]
    for i, val in enumerate(expected):
        assert y_at_samples[i] == pytest.approx(val, abs=1e-12), (
            f"sample {i}: expected {val}, got {y_at_samples[i]}"
        )


# ---------------------------------------------------------------------------
# DiscreteTransferFunction multi-rate
# ---------------------------------------------------------------------------


def test_multirate_discrete_transfer_function_first_order() -> None:
    """H(z) = 1 / (z - 0.5) (= 1 次離散 SS) multi-rate で SS と同じ解析解。"""
    sim = Simulator(t_end=0.5, dt=0.01)
    src = sim.add(Constant(value=1.0))
    dtf = sim.add(
        DiscreteTransferFunction(
            numerator=[1.0],
            denominator=[1.0, -0.5],
            sample_time=0.1,
            x0=np.array([0.0]),
        )
    )
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(src, dtf)
    sim.connect(dtf, sc)
    sim.run()

    arr = _flat(sc)
    times = np.array(sc.times)
    sample_idx = _sample_indices(times, 0.1)
    y_at_samples = arr[sample_idx]

    expected = [2.0 * (1.0 - 0.5**n) for n in range(len(y_at_samples))]
    for i, val in enumerate(expected):
        assert y_at_samples[i] == pytest.approx(val, abs=1e-12), (
            f"sample {i}: expected {val}, got {y_at_samples[i]}"
        )


# ---------------------------------------------------------------------------
# Single-rate degenerate (= sample_time = dt_base、step_ratio = 1) で v0.3.0 と
# 数値結果が同じであることを保証する
# ---------------------------------------------------------------------------


def test_single_rate_unit_delay_unchanged_from_v030() -> None:
    """sample_time=dt_base=0.01 で UnitDelay は ADR-0014 v0.3.0 の数値と一致 (single-rate Simulink)。"""
    sim = Simulator(t_end=0.05, dt=0.01)
    clk = sim.add(Clock())
    ud = sim.add(UnitDelay(sample_time=0.01, x0=99.0))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(clk, ud)
    sim.connect(ud, sc)
    sim.run()

    arr = _flat(sc)
    expected = np.array([99.0, 0.00, 0.01, 0.02, 0.03, 0.04])
    np.testing.assert_allclose(arr, expected, atol=1e-12)


def test_single_rate_discrete_integrator_unchanged_from_v030() -> None:
    """sample_time=dt_base で DiscreteIntegrator は v0.3.0 と数値同一。"""
    sim = Simulator(t_end=0.05, dt=0.01)
    src = sim.add(Constant(value=1.0))
    di = sim.add(DiscreteIntegrator(sample_time=0.01, gain=1.0, x0=0.0))
    sc = sim.add(Scope(n_inputs=1))
    sim.connect(src, di)
    sim.connect(di, sc)
    sim.run()

    arr = _flat(sc)
    expected = np.array([0.00, 0.01, 0.02, 0.03, 0.04, 0.05])
    np.testing.assert_allclose(arr, expected, atol=1e-12)
