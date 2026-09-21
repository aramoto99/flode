"""ADR-0078 の離散タイミング回帰をベクトル状態で再現する (ADR-0079 Stage 2 受け入れ基準)。

``tests/test_discrete_timing_semantics.py`` の代表ケース (直列遅延 / 帰還 / 厳密解 /
Triggered Subsystem) を ``Mux(2)`` の 2 要素ベクトルで組み、各列が同じモデルの
スカラ版と **bit-identical** であることを確認する。advance → output → update の
1 パスと出力キャッシュがベクトル状態 (2-state 配置 ``x[:n]`` / ``x[n:]``) でも
成立していれば、列ごとの値はスカラ版と一致する。
"""

from __future__ import annotations

import numpy as np
import pytest

from flode import Simulator, Subsystem
from flode.blocks import (
    Clock,
    Constant,
    Demux,
    DiscreteIntegrator,
    Gain,
    Integrator,
    Mux,
    PulseGenerator,
    Scope,
    Step,
    Sum,
    UnitDelay,
    ZeroOrderHoldDirect,
)
from flode.subsystems import Inport, Outport, Trigger

TS = 0.1


def _vector_source(sim: Simulator) -> Mux:
    """2 要素ベクトル (t, 2t) の起点。"""
    clk = sim.add(Clock(id="clk"))
    g2 = sim.add(Gain(k=2.0, id="g2"))
    m = sim.add(Mux(n=2, id="src"))
    sim.connect(clk, g2)
    sim.connect(clk, m, dst_idx=0)
    sim.connect(g2, m, dst_idx=1)
    return m


def _chain_scalar(blocks_factory, *, source_gain: float, t_end: float = 0.6):  # type: ignore[no-untyped-def]
    sim = Simulator(t_end=t_end, dt=TS)
    clk = sim.add(Clock(id="clk"))
    prev = sim.add(Gain(k=source_gain, id="gs"))
    sim.connect(clk, prev)
    for b in blocks_factory():
        sim.add(b)
        sim.connect(prev, b)
        prev = b
    sc = sim.add(Scope(id="sc"))
    sim.connect(prev, sc)
    sim.run()
    return np.asarray(sc.values)[:, 0]


def _chain_vector(blocks_factory, *, t_end: float = 0.6):  # type: ignore[no-untyped-def]
    sim = Simulator(t_end=t_end, dt=TS)
    prev = _vector_source(sim)
    for b in blocks_factory():
        sim.add(b)
        sim.connect(prev, b)
        prev = b
    sc = sim.add(Scope(id="sc"))
    sim.connect(prev, sc)
    sim.run()
    return np.asarray(sc.values)


_CHAINS = {
    "two_unit_delays": lambda: [UnitDelay(sample_time=TS), UnitDelay(sample_time=TS)],
    "unit_delay_gain_unit_delay": lambda: [
        UnitDelay(sample_time=TS),
        Gain(k=1.0),
        UnitDelay(sample_time=TS),
    ],
    "unit_delay_then_discrete_integrator": lambda: [
        UnitDelay(sample_time=TS),
        DiscreteIntegrator(sample_time=TS),
    ],
    "zoh_then_unit_delay": lambda: [ZeroOrderHoldDirect(sample_time=TS), UnitDelay(sample_time=TS)],
}


class TestDiscreteChainDelayVector:
    @pytest.mark.parametrize("name", list(_CHAINS))
    def test_columns_match_scalar_runs(self, name: str) -> None:
        factory = _CHAINS[name]
        vec = _chain_vector(factory)
        col0 = _chain_scalar(factory, source_gain=1.0)
        col1 = _chain_scalar(factory, source_gain=2.0)
        assert vec.shape == (7, 2)
        assert np.array_equal(vec[:, 0], col0)
        assert np.array_equal(vec[:, 1], col1)


class TestDiscreteFeedbackVector:
    @staticmethod
    def _loop(vector: bool) -> np.ndarray:
        """x[k+1] = 0.5 x[k] + c (c = 1 / 3 の 2 要素) を Sum / UnitDelay / Gain で構成。"""
        sim = Simulator(t_end=0.6, dt=TS)
        if vector:
            c1 = sim.add(Constant(value=1.0, id="c1"))
            c3 = sim.add(Constant(value=3.0, id="c3"))
            c = sim.add(Mux(n=2, id="c"))
            sim.connect(c1, c, dst_idx=0)
            sim.connect(c3, c, dst_idx=1)
        else:
            c = sim.add(Constant(value=1.0, id="c"))
        s = sim.add(Sum(signs="++", id="s"))
        d = sim.add(UnitDelay(sample_time=TS, id="d"))
        g = sim.add(Gain(k=0.5, id="g"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(c, s, dst_idx=0)
        sim.connect(g, s, dst_idx=1)
        sim.connect(s, d)
        sim.connect(d, g)
        sim.connect(d, sc)
        sim.run()
        return np.asarray(sc.values)

    def test_vector_loop_matches_scalar_loops(self) -> None:
        vec = self._loop(vector=True)
        scalar = self._loop(vector=False)[:, 0]
        assert np.array_equal(vec[:, 0], scalar)
        # 2 列目は c=3 → 3 倍 (線形) — 厳密に 3 倍か確認
        np.testing.assert_allclose(vec[:, 1], 3.0 * scalar, rtol=1e-15)

    def test_cross_coupled_vector_unit_delays_period_two(self) -> None:
        sim = Simulator(t_end=0.05, dt=0.01)
        a = sim.add(UnitDelay(sample_time=0.01, x0=[10.0, 1.0], id="a"))
        b = sim.add(UnitDelay(sample_time=0.01, x0=[20.0, 2.0], id="b"))
        sa = sim.add(Scope(id="sa"))
        sb = sim.add(Scope(id="sb"))
        sim.connect(a, b)
        sim.connect(b, a)
        sim.connect(a, sa)
        sim.connect(b, sb)
        sim.run()
        np.testing.assert_array_equal(np.asarray(sa.values)[:, 0], [10, 20, 10, 20, 10, 20])
        np.testing.assert_array_equal(np.asarray(sa.values)[:, 1], [1, 2, 1, 2, 1, 2])
        np.testing.assert_array_equal(np.asarray(sb.values)[:, 0], [20, 10, 20, 10, 20, 10])


class TestSampledDataVector:
    """厳密解テスト (TestSampledDataExactSolution) の閉ループをベクトル状態で再現。"""

    @staticmethod
    def _closed_loop(vector: bool) -> np.ndarray:
        # プラント 1/s (Integrator)、制御器 DiscreteIntegrator + 演算遅れ UnitDelay、
        # 単位ステップ指令。ベクトル版は指令を (1, 2) の 2 要素にする
        sim = Simulator(t_end=2.0, dt=0.05, rtol=1e-11, atol=1e-13)
        r1 = sim.add(Step(step_time=0.0, id="r1"))
        if vector:
            r2 = sim.add(Step(step_time=0.0, final_value=2.0, id="r2"))
            r = sim.add(Mux(n=2, id="r"))
            sim.connect(r1, r, dst_idx=0)
            sim.connect(r2, r, dst_idx=1)
        else:
            r = r1
        e = sim.add(Sum(signs="+-", id="e"))
        ctrl = sim.add(DiscreteIntegrator(sample_time=0.05, gain=3.0, id="ctrl"))
        d = sim.add(UnitDelay(sample_time=0.05, id="d"))
        plant = sim.add(Integrator(x0=0.0, id="plant"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(r, e, dst_idx=0)
        sim.connect(plant, e, dst_idx=1)
        sim.connect(e, ctrl)
        sim.connect(ctrl, d)
        sim.connect(d, plant)
        sim.connect(plant, sc)
        sim.run()
        return np.asarray(sc.values)

    def test_vector_closed_loop_matches_scalar(self) -> None:
        vec = self._closed_loop(vector=True)
        scalar = self._closed_loop(vector=False)[:, 0]
        assert vec.shape[1] == 2
        # 連続状態を含むので solve_ivp の誤差制御 (状態ベクトル全体のノルム) が
        # 刻み幅を変え、bit 一致にはならない。ソルバ許容誤差 (rtol=1e-11) より
        # 十分厳しい範囲で一致することを要求する (離散部分の意味論は上の
        # 純離散テストが bit 一致で固定している)
        np.testing.assert_allclose(vec[:, 0], scalar, rtol=1e-9, atol=1e-11)
        np.testing.assert_allclose(vec[:, 1], 2.0 * scalar, rtol=1e-9, atol=1e-11)


class TestTriggeredSubsystemVector:
    @staticmethod
    def _triggered(vector: bool) -> np.ndarray:
        sub = Subsystem(
            blocks=[
                Inport(port_idx=0, id="in_data"),
                UnitDelay(sample_time=TS, id="d"),
                Outport(port_idx=0, id="out"),
                Trigger(trigger_type="rising", id="trig"),
            ],
            connections=[{"src": "in_data", "dst": "d"}, {"src": "d", "dst": "out"}],
            id="trig_delay",
        )
        sim = Simulator(t_end=0.6, dt=TS)
        pulse = sim.add(PulseGenerator(period=0.2, id="pulse"))
        clk = sim.add(Clock(id="clk"))
        if vector:
            g2 = sim.add(Gain(k=2.0, id="g2"))
            src = sim.add(Mux(n=2, id="src"))
            sim.connect(clk, g2)
            sim.connect(clk, src, dst_idx=0)
            sim.connect(g2, src, dst_idx=1)
        else:
            src = clk
        sim.add(sub)
        sc = sim.add(Scope(id="sc"))
        sim.connect(src, sub, dst_idx=0)
        sim.connect(pulse, sub, dst_idx=1)
        sim.connect(sub, sc)
        sim.run()
        return np.asarray(sc.values)

    def test_vector_triggered_matches_scalar(self) -> None:
        vec = self._triggered(vector=True)
        scalar = self._triggered(vector=False)[:, 0]
        assert vec.shape[1] == 2
        assert np.array_equal(vec[:, 0], scalar)
        assert np.array_equal(vec[:, 1], 2.0 * scalar)


class TestDemuxAfterVectorState:
    def test_vector_unit_delay_then_demux(self) -> None:
        """ベクトル UnitDelay の後段で Demux し、各要素が 1 サンプル遅れる。"""
        sim = Simulator(t_end=0.6, dt=TS)
        m = _vector_source(sim)
        d = sim.add(UnitDelay(sample_time=TS, id="d"))
        dm = sim.add(Demux(n=2, id="dm"))
        sc = sim.add(Scope(n_inputs=2, id="sc"))
        sim.connect(m, d)
        sim.connect(d, dm)
        sim.connect(dm, sc, src_idx=0, dst_idx=0)
        sim.connect(dm, sc, src_idx=1, dst_idx=1)
        sim.run()
        v = np.asarray(sc.values)
        t = np.arange(7) * TS
        np.testing.assert_allclose(v[:, 0], np.concatenate([[0.0], t[:-1]]))
        np.testing.assert_allclose(v[:, 1], 2.0 * np.concatenate([[0.0], t[:-1]]))
