"""ADR-0002 離散時間 + マルチレートスケジューラのテスト。"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from pyflw import BlockSpecError, Simulator
from pyflw.blocks import Constant, Gain, Scope, Sine, UnitDelay


def test_unit_delay_basic_one_step_lag():
    """UnitDelay の基本動作: 出力 = 1 ステップ前の入力。"""
    sim = Simulator(t_end=0.05, dt=0.01)
    src = sim.add(Constant(value=1.0, id="src"))
    delay = sim.add(UnitDelay(sample_time=0.01, x0=0.0, id="d"))
    scope = sim.add(Scope(n_inputs=1, id="scope"))
    sim.connect(src, delay)
    sim.connect(delay, scope)
    sim.run()

    values = scope.values[:, 0]
    assert values[0] == pytest.approx(0.0)
    for v in values[1:]:
        assert v == pytest.approx(1.0)


def test_unit_delay_with_continuous_source():
    """連続 (Sine) → 離散 (UnitDelay) → Scope。"""
    sim = Simulator(t_end=0.1, dt=0.01)
    src = sim.add(Sine(amplitude=1.0, frequency=1.0, id="sine"))
    delay = sim.add(UnitDelay(sample_time=0.01, x0=0.0, id="d"))
    scope = sim.add(Scope(n_inputs=1, id="scope"))
    sim.connect(src, delay)
    sim.connect(delay, scope)
    sim.run()
    assert scope.values.shape[0] >= 10


def test_multirate_integer_ratio():
    """整数比 (5:1) の 2 つの UnitDelay が動作する。"""
    sim = Simulator(t_end=0.1, dt=0.01)
    src = sim.add(Constant(value=1.0, id="src"))
    fast = sim.add(UnitDelay(sample_time=0.01, x0=0.0, id="fast"))
    slow = sim.add(UnitDelay(sample_time=0.05, x0=0.0, id="slow"))
    scope_fast = sim.add(Scope(n_inputs=1, id="scope_fast"))
    scope_slow = sim.add(Scope(n_inputs=1, id="scope_slow"))
    sim.connect(src, fast)
    sim.connect(src, slow)
    sim.connect(fast, scope_fast)
    sim.connect(slow, scope_slow)
    sim.run()

    assert fast._step_ratio == 1
    assert slow._step_ratio == 5


def test_non_integer_ratio_warns(caplog):
    """非整数比 sample_time は warning を出して丸める。"""
    sim = Simulator(t_end=0.1, dt=0.01)
    src = sim.add(Constant(value=1.0, id="src"))
    a = sim.add(UnitDelay(sample_time=0.01, x0=0.0, id="a"))
    b = sim.add(UnitDelay(sample_time=0.007, x0=0.0, id="b"))
    sim.connect(src, a)
    sim.connect(src, b)

    with caplog.at_level(logging.WARNING, logger="pyflw.scheduler"):
        sim.run()
    assert any("not integer multiples" in r.message for r in caplog.records)


def test_inherited_sample_time_from_discrete_upstream():
    """sample_time=-1.0 のブロックが上流の離散周期を継承する。"""
    sim = Simulator(t_end=0.1, dt=0.01)
    src = sim.add(Constant(value=1.0, id="src"))
    delay = sim.add(UnitDelay(sample_time=0.05, x0=0.0, id="delay"))
    g = sim.add(Gain(k=2.0, id="g"))
    g.sample_time = -1.0  # mark inherited

    sim.connect(src, delay)
    sim.connect(delay, g)
    sim.run()

    assert g._resolved_sample_time == 0.05


def test_inherited_with_no_inputs_raises():
    """入力 0 のブロックが sample_time=-1.0 を持つとエラー。"""
    sim = Simulator(t_end=0.1, dt=0.01)
    src = sim.add(Constant(value=1.0, id="src"))
    src.sample_time = -1.0  # invalid for 0-input block

    with pytest.raises(BlockSpecError, match="inherited"):
        sim.run()


def test_invalid_sample_time_value():
    """sample_time が -1.0 以外の負値はエラー。"""
    with pytest.raises(BlockSpecError, match="invalid"):
        UnitDelay(sample_time=-2.0)


def test_counter_based_no_drift_long_simulation():
    """長時間シミュレーションで離散発火回数が誤差なく一致する。"""
    t_end = 10.0
    dt_base = 0.001
    period = 0.01

    sim = Simulator(t_end=t_end, dt=dt_base)
    src = sim.add(Constant(value=1.0, id="src"))
    delay = sim.add(UnitDelay(sample_time=period, x0=0.0, id="d"))
    sim.connect(src, delay)
    sim.run()

    expected_step_ratio = round(period / dt_base)
    assert delay._step_ratio == expected_step_ratio


def test_double_buffering_simultaneous_updates():
    """同時刻に発火する 2 つの UnitDelay が互いの旧状態を見ること。

    a → UnitDelay(T=0.01, x0=10) → consumer_b の状態
    b → UnitDelay(T=0.01, x0=20) → consumer_a の状態

    Phase 1 では UnitDelay は input → state なので、
    a と b が互いを参照すると無限再帰になる代わりに、Plant 構成で確認する。
    ここでは「2 つの UnitDelay の入力をクロス結線」して、
    update 時に古い値を参照することを確認する。
    """
    sim = Simulator(t_end=0.03, dt=0.01)
    a = sim.add(UnitDelay(sample_time=0.01, x0=10.0, id="a"))
    b = sim.add(UnitDelay(sample_time=0.01, x0=20.0, id="b"))
    scope_a = sim.add(Scope(n_inputs=1, id="scope_a"))
    scope_b = sim.add(Scope(n_inputs=1, id="scope_b"))
    sim.connect(a, b)
    sim.connect(b, a)
    sim.connect(a, scope_a)
    sim.connect(b, scope_b)
    sim.run()

    a_values = scope_a.values[:, 0]
    b_values = scope_b.values[:, 0]

    # ADR-0015 で UnitDelay が 2-state augmentation になり、feedback loop での
    # 出力 sequence は v0.3.0 (1-state、period 2 alternating) から period 4 に
    # 変化した。state[0] が 1 fire 分遅れて state[1] の値を反映するため。
    # double buffering は引き続き機能している (a と b が独立に同じ pattern で更新される)。
    assert a_values[0] == pytest.approx(10.0)
    assert b_values[0] == pytest.approx(20.0)
    assert a_values[1] == pytest.approx(20.0)
    assert b_values[1] == pytest.approx(10.0)
    # ADR-0015: 2-state shift により iter 2 で state[0] = state[1]_post-iter-1 = u_a(1) = 20
    assert a_values[2] == pytest.approx(20.0)
    assert b_values[2] == pytest.approx(10.0)


def test_continuous_only_phase0_compat():
    """離散ブロックを使わないモデルでは Phase 0 と同様に動作する。"""
    sim = Simulator(t_end=0.1, dt=0.01)
    src = sim.add(Constant(value=2.0, id="src"))
    g = sim.add(Gain(k=3.0, id="g"))
    scope = sim.add(Scope(n_inputs=1, id="scope"))
    sim.connect(src, g)
    sim.connect(g, scope)
    sim.run()

    np.testing.assert_allclose(scope.values[:, 0], 6.0)
