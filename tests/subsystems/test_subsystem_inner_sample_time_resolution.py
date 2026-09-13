"""Subsystem 内部の離散ブロックが ``_resolved_sample_time`` を持つことの回帰テスト。

2026-09-13 発見: ``Simulator._resolve_sample_times`` はルート直下のブロックしか
解決しないため、Subsystem 内の ``DiscreteIntegrator`` / ``RateLimiter`` /
``ZeroOrderHoldDirect`` (update / output で ``_resolved_sample_time`` を要求する
ブロック) は ``sample_time has not been resolved`` の ``BlockSpecError`` で
run できなかった (SPEC-0030 導入以降の回帰。``UnitDelay`` / ``Relay`` は
参照しないため気付かれなかった)。
"""

from __future__ import annotations

import numpy as np
import pytest

from flode import Enable, Inport, Outport, Simulator, Subsystem
from flode.blocks import (
    Constant,
    DiscreteIntegrator,
    RateLimiter,
    Scope,
    Sine,
    ZeroOrderHoldDirect,
)
from flode.core.block import Block
from flode.exceptions import BlockSpecError


def _wrap(inner: Block, *, enable: bool = False, nested: bool = False) -> Subsystem:
    sub = Subsystem(id="sub")
    sub.add(Inport(port_idx=0, id="i"))
    sub.add(inner)
    sub.add(Outport(port_idx=0, id="o"))
    if enable:
        sub.add(Enable(id="e"))
    sub.connect("i", inner.id)
    sub.connect(inner.id, "o")
    if not nested:
        return sub
    outer = Subsystem(id="outer")
    outer.add(Inport(port_idx=0, id="i"))
    outer.add(sub)
    outer.add(Outport(port_idx=0, id="o"))
    outer.connect("i", "sub")
    outer.connect("sub", "o")
    return outer


def _run(sub: Subsystem, source: Block, *, enable: bool = False) -> np.ndarray:
    sim = Simulator(t_end=0.5, dt=0.1)
    sim.add(source)
    sim.add(sub)
    sim.add(Scope(n_inputs=1, id="sc"))
    sim.connect(source, sub, dst_idx=0)
    if enable:
        sim.add(Constant(value=1.0, id="en"))
        sim.connect("en", sub, dst_idx=1)
    sim.connect(sub, "sc")
    sim.run()
    return sim.get_block("sc").values[:, 0]


class TestInnerDiscreteBlocksRun:
    @pytest.mark.parametrize("nested", [False, True], ids=["1-level", "2-level"])
    def test_discrete_integrator_inside_subsystem(self, nested: bool) -> None:
        y = _run(
            _wrap(DiscreteIntegrator(sample_time=0.1, id="di"), nested=nested),
            Constant(value=1.0, id="one"),
        )
        # 前進 Euler: y[k] = 0.1 * k
        np.testing.assert_allclose(y, np.arange(6) * 0.1, atol=1e-12)

    def test_discrete_integrator_inside_enabled_subsystem(self) -> None:
        y = _run(
            _wrap(DiscreteIntegrator(sample_time=0.1, id="di"), enable=True),
            Constant(value=1.0, id="one"),
            enable=True,
        )
        np.testing.assert_allclose(y, np.arange(6) * 0.1, atol=1e-12)

    def test_rate_limiter_inside_subsystem_matches_root_level(self) -> None:
        y = _run(
            _wrap(
                RateLimiter(sample_time=0.1, rising_slew_rate=2.0, falling_slew_rate=-2.0, id="rl")
            ),
            Constant(value=1.0, id="one"),
        )
        # ルート直下に置いた同じブロックと bit 一致 (update-before-output なので
        # t=0 で既に 0.2: 0.2, 0.4, 0.6, 0.8, 1.0, 1.0)
        ref = Simulator(t_end=0.5, dt=0.1)
        ref.add(Constant(value=1.0, id="one"))
        ref.add(RateLimiter(sample_time=0.1, rising_slew_rate=2.0, falling_slew_rate=-2.0, id="rl"))
        ref.add(Scope(n_inputs=1, id="sc"))
        ref.connect("one", "rl")
        ref.connect("rl", "sc")
        ref.run()
        np.testing.assert_array_equal(y, ref.get_block("sc").values[:, 0])
        np.testing.assert_allclose(y, [0.2, 0.4, 0.6, 0.8, 1.0, 1.0], atol=1e-12)

    def test_zero_order_hold_inside_subsystem_holds_between_samples(self) -> None:
        # ZOH(0.2) を dt=0.1 で回す → 奇数 k では前サンプル値を保持
        sub = _wrap(ZeroOrderHoldDirect(sample_time=0.2, id="zoh"))
        y = _run(sub, Sine(amplitude=1.0, frequency=0.5, id="s"))
        t_samples = np.array([0.0, 0.0, 0.2, 0.2, 0.4, 0.4])
        np.testing.assert_allclose(y, np.sin(2 * np.pi * 0.5 * t_samples), atol=1e-9)

    def test_mixed_inner_discrete_rates_are_rejected(self) -> None:
        """code-reviewer MUST: 周期の異なる離散ブロックの混在は fail-closed。

        Subsystem は内部離散ブロックを最速周期で一括 update するため、遅い方が
        誤った速さで進む (従来は解決エラーで落ちていたので顕在化しなかった)。
        """
        sub = Subsystem(id="sub")
        sub.add(Inport(port_idx=0, id="i"))
        sub.add(DiscreteIntegrator(sample_time=0.1, id="fast"))
        sub.add(DiscreteIntegrator(sample_time=0.2, id="slow"))
        sub.add(Outport(port_idx=0, id="o"))
        sub.connect("i", "fast")
        sub.connect("i", "slow")
        sub.connect("slow", "o")
        sim = Simulator(t_end=0.5, dt=0.1)
        sim.add(Constant(value=1.0, id="one"))
        sim.add(sub)
        sim.connect("one", "sub")
        with pytest.raises(BlockSpecError, match="different sample_time"):
            sim.run()

    def test_inner_blocks_have_resolved_sample_time_after_run(self) -> None:
        sub = _wrap(DiscreteIntegrator(sample_time=0.1, id="di"))
        _run(sub, Constant(value=1.0, id="one"))
        assert sub.get_block("di")._resolved_sample_time == pytest.approx(0.1)
        assert sub.get_block("i")._resolved_sample_time is None
