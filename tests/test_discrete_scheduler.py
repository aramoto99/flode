"""ADR-0002 離散時間 + マルチレートスケジューラのテスト。"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from flode import BlockSpecError, Simulator
from flode.blocks import Constant, Gain, Scope, Sine, UnitDelay


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

    with caplog.at_level(logging.WARNING, logger="flode.scheduler"):
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


def test_unit_delay_inherited_without_upstream_rate_falls_back_to_dt(caplog):
    """バグ再現 (2026-09-09 オーナー報告): 上流に離散レートがない UnitDelay(-1) が
    連続扱いに解決され、update が一度も呼ばれず x0 で無警告凍結していた。

    修正後: 離散専用ブロックの -1 は dt にフォールバックし、WARNING を出す。
    Constant(1.0) → Add ← UnitDelay(-1) の加算ループが dt=0.01 で t_end=0.05 まで
    に 6 tick (t=0..0.05) 進む。UnitDelay は 2-state augmentation (ADR-0015) の
    ため feedback ループでは 2 fire で 1 増える系列 (1,2,2,3,3,4) になる。
    """
    from flode.blocks.mathops import Add

    sim = Simulator(t_end=0.05, dt=0.01)
    src = sim.add(Constant(value=1.0, id="src"))
    add = sim.add(Add(signs="++", id="add"))
    delay = sim.add(UnitDelay(sample_time=-1.0, x0=0.0, id="delay"))
    scope = sim.add(Scope(n_inputs=1, id="scope"))
    sim.connect(src, add, dst_idx=0)
    sim.connect(delay, add, dst_idx=1)
    sim.connect(add, delay)
    sim.connect(add, scope)
    with caplog.at_level(logging.WARNING, logger="flode"):
        sim.run()

    assert delay._resolved_sample_time == pytest.approx(0.01)  # dt にフォールバック
    values = scope.values[:, 0]
    assert values.tolist() == pytest.approx([1.0, 2.0, 2.0, 3.0, 3.0, 4.0])
    assert values[-1] > values[0]  # 凍結していれば 1.0 のまま増えない
    assert any(
        "delay" in r.message and "dt" in r.message
        for r in caplog.records
        if r.levelno >= logging.WARNING
    ), "フォールバックの WARNING が出ていない"


def test_discrete_integrator_inherited_without_upstream_rate_falls_back_to_dt():
    """同型バグの横展開: DiscreteIntegrator(-1) も離散専用なので dt に落ちる。"""
    from flode.blocks.discrete import DiscreteIntegrator

    sim = Simulator(t_end=0.05, dt=0.01)
    src = sim.add(Constant(value=1.0, id="src"))
    di = sim.add(DiscreteIntegrator(sample_time=-1.0, id="di"))
    scope = sim.add(Scope(n_inputs=1, id="scope"))
    sim.connect(src, di)
    sim.connect(di, scope)
    sim.run()

    assert di._resolved_sample_time == pytest.approx(0.01)
    # 前進 Euler: t=0.05 で x ≈ 0.05 (凍結していれば 0.0 のまま)
    assert scope.values[-1, 0] == pytest.approx(0.05, abs=1e-12)


def test_stateless_inherited_without_upstream_rate_stays_continuous():
    """無状態ブロック (Gain) の -1 + 連続上流は従来どおり連続 (None) のまま。

    dt フォールバックは離散専用ブロック限定 — デコレータ製ポリモーフィック
    ブロックの「-1 → 連続」機能 (ADR-0003) と無状態ブロックの従来挙動を壊さない。
    """
    sim = Simulator(t_end=0.05, dt=0.01)
    src = sim.add(Constant(value=1.0, id="src"))
    g = sim.add(Gain(k=2.0, id="g"))
    g.sample_time = -1.0
    scope = sim.add(Scope(n_inputs=1, id="scope"))
    sim.connect(src, g)
    sim.connect(g, scope)
    sim.run()

    assert g._resolved_sample_time is None
    assert scope.values[-1, 0] == pytest.approx(2.0)


def test_inherited_resolution_is_add_order_independent():
    """v0.57.0 code-reviewer MUST の再現: 非 feedthrough ブロック同士の直列連鎖。

    UnitDelay 同士は依存辺を持たないため、旧 1 パス実装では解決順が sim.add()
    順に依存し、下流 (-1) を先に追加すると上流の明示 0.03 を読めず dt に
    誤フォールバックしていた。2 相解決後は追加順によらず 0.03 を継承する。
    """
    sim = Simulator(t_end=0.09, dt=0.01)
    src = sim.add(Constant(value=1.0, id="src"))
    d2 = sim.add(UnitDelay(sample_time=-1.0, x0=0.0, id="d2"))  # 追加は先、結線上は下流
    d1 = sim.add(UnitDelay(sample_time=0.03, x0=0.0, id="d1"))  # 追加は後、結線上は上流
    sim.connect(src, d1)
    sim.connect(d1, d2)
    sim.run()

    assert d1._resolved_sample_time == pytest.approx(0.03)
    assert d2._resolved_sample_time == pytest.approx(0.03)  # dt (0.01) ではない


def test_inherited_chain_of_minus_one_resolves_transitively():
    """-1 → -1 の連鎖: 上流の -1 が解決されてから下流が継承する (固定点反復)。"""
    sim = Simulator(t_end=0.09, dt=0.01)
    src = sim.add(Constant(value=1.0, id="src"))
    # 追加順を結線と逆にして順序非依存性も同時に確認する
    d3 = sim.add(UnitDelay(sample_time=-1.0, x0=0.0, id="d3"))
    d2 = sim.add(UnitDelay(sample_time=-1.0, x0=0.0, id="d2"))
    d1 = sim.add(UnitDelay(sample_time=0.03, x0=0.0, id="d1"))
    sim.connect(src, d1)
    sim.connect(d1, d2)
    sim.connect(d2, d3)
    sim.run()

    assert d2._resolved_sample_time == pytest.approx(0.03)
    assert d3._resolved_sample_time == pytest.approx(0.03)


def test_inherited_cycle_of_minus_one_falls_back_deterministically():
    """-1 同士の循環は「循環内上流 = レートなし」で一括解決 → 両方 dt に落ちる。"""
    sim = Simulator(t_end=0.03, dt=0.01)
    a = sim.add(UnitDelay(sample_time=-1.0, x0=1.0, id="a"))
    b = sim.add(UnitDelay(sample_time=-1.0, x0=2.0, id="b"))
    sim.connect(a, b)
    sim.connect(b, a)
    sim.run()

    assert a._resolved_sample_time == pytest.approx(0.01)
    assert b._resolved_sample_time == pytest.approx(0.01)


def test_discrete_only_builtins_declare_requires_discrete_rate():
    """ADR-0002 Amendment (2026-09-10) 申し送り: フラグ宣言忘れの再発防止ガード。

    ``update`` を override し ``derivative`` を override しないブロック
    (= 離散専用) は、-1 継承で連続扱いになると無警告凍結する。
    ``requires_discrete_rate=True`` を宣言するか、__init__ で ``sample_time > 0``
    を強制して -1 を構造的に不可能にするか、どちらかが必須。
    新規離散ブロックがどちらもしていなければこのテストが落ちて判断を強制する。

    既知の限界: ``derivative`` を no-op で override した実質離散なハイブリッド
    ブロックが将来追加された場合、この判定 (override の有無) では検出できない。
    その場合はここに個別追加すること。
    """
    import importlib
    import pkgutil

    import flode.blocks as blocks_pkg
    from flode.core.block import Block

    # __init__ が sample_time > 0 を強制するクラス (-1 が構造的に不可能 → フラグ不要)
    rejects_inherit = {
        "RateLimiter",
        "Relay",
        "RandomSource",
        "TransportDelay",
        "RateTransition",
    }
    offenders: list[str] = []
    # walk_packages: 将来 flode/blocks/ にサブパッケージが増えても再帰走査する
    # (iter_modules だと直下のみで無言にすり抜ける — code-reviewer SHOULD)
    for modinfo in pkgutil.walk_packages(blocks_pkg.__path__, prefix="flode.blocks."):
        mod = importlib.import_module(modinfo.name)
        for cls in vars(mod).values():
            if not (
                isinstance(cls, type)
                and issubclass(cls, Block)
                and cls.__module__ == mod.__name__
            ):
                continue
            overrides_update = cls.update is not Block.update
            overrides_derivative = cls.derivative is not Block.derivative
            if (
                overrides_update
                and not overrides_derivative
                and cls.__name__ not in rejects_inherit
                and not cls.requires_discrete_rate
            ):
                offenders.append(f"{cls.__module__}.{cls.__name__}")
    assert not offenders, (
        f"離散専用ブロックが requires_discrete_rate を宣言していない: {offenders}"
    )


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
