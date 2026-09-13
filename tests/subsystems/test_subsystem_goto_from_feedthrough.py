"""Subsystem 境界をまたぐ / Subsystem 内に閉じた Goto/From の値伝搬の回帰テスト。

2026-09-13 発見:

1. Subsystem 内で ``Inport → Goto`` / ``From → Gain → Outport`` と組むと、直達
   推論 (``_infer_direct_feedthrough``) が仮想配線を辿らないため Subsystem が
   非直達と判定され、パス 1 で入力ゼロのまま Goto が値を記録 → From が 0 を読む。
2. 非直達 Subsystem の深い階層にある global Goto を root の From が読むと、
   パス 1 (入力ゼロ) で記録された値を読んでしまう (= 常に 0)。
3. Triggered Subsystem 内の Goto を外の From が読むと、初回 fire 前に
   ``has not produced any output yet`` の ``BlockSpecError`` で run できない。
"""

from __future__ import annotations

import numpy as np
import pytest

from flode import Inport, Outport, Simulator, Subsystem, Trigger
from flode.blocks import Constant, From, Gain, Goto, Integrator, PulseGenerator, Scope, Sine


def _local_goto_sub(sid: str, k: float, tag: str) -> Subsystem:
    s = Subsystem(id=sid)
    s.add(Inport(port_idx=0, id="i"))
    s.add(Goto(tag=tag, id="gt"))
    s.add(From(tag=tag, id="fr"))
    s.add(Gain(k=k, id="g"))
    s.add(Outport(port_idx=0, id="o"))
    s.connect("i", "gt")
    s.connect("fr", "g")
    s.connect("g", "o")
    return s


class TestLocalGotoFromInsideSubsystem:
    def test_single_subsystem_passes_value_through_virtual_wire(self) -> None:
        sim = Simulator(t_end=0.2, dt=0.1)
        sim.add(Constant(value=1.0, id="one"))
        sim.add(_local_goto_sub("a", 2.0, "x"))
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("one", "a")
        sim.connect("a", "sc")
        sim.run()
        np.testing.assert_allclose(sim.get_block("sc").values[:, 0], 2.0)
        assert sim.get_block("a").direct_feedthrough is True

    def test_same_local_tag_in_two_subsystems_is_independent(self) -> None:
        sim = Simulator(t_end=0.2, dt=0.1)
        sim.add(Constant(value=1.0, id="one"))
        sim.add(_local_goto_sub("a", 2.0, "x"))
        sim.add(_local_goto_sub("b", 5.0, "x"))
        sim.add(Scope(n_inputs=2, id="sc"))
        sim.connect("one", "a")
        sim.connect("one", "b")
        sim.connect("a", "sc", dst_idx=0)
        sim.connect("b", "sc", dst_idx=1)
        sim.run()
        np.testing.assert_allclose(sim.get_block("sc").values[-1], [2.0, 5.0])


def _deep(use_goto: bool) -> Subsystem:
    """mid( leaf(Gain 2) → Integrator )。use_goto なら leaf 内の 2*u を global Goto で公開。"""
    leaf = Subsystem(id="leaf")
    leaf.add(Inport(port_idx=0, id="i"))
    leaf.add(Gain(k=2.0, id="g"))
    leaf.add(Outport(port_idx=0, id="o"))
    leaf.connect("i", "g")
    leaf.connect("g", "o")
    if use_goto:
        leaf.add(Goto(tag="deep", tag_visibility="global", id="gd"))
        leaf.connect("g", "gd")
    mid = Subsystem(id="mid")
    mid.add(Inport(port_idx=0, id="i"))
    mid.add(leaf)
    mid.add(Integrator(x0=0.0, id="acc"))
    mid.add(Outport(port_idx=0, id="o"))
    mid.connect("i", "leaf")
    mid.connect("leaf", "acc")
    mid.connect("acc", "o")
    return mid


class TestGlobalGotoAcrossHierarchy:
    def test_global_goto_in_deep_non_feedthrough_subsystem_read_at_root(self) -> None:
        """root の From は「現在の入力で計算した」Goto 値を読むこと (= 0 ではない)。"""
        sim = Simulator(t_end=1.0, dt=0.01, rtol=1e-10, atol=1e-13)
        sim.add(Sine(amplitude=1.0, frequency=1.0, id="sine"))
        sim.add(_deep(use_goto=True))
        sim.add(From(tag="deep", id="fd"))
        sim.add(Scope(n_inputs=2, id="sc"))
        sim.connect("sine", "mid")
        sim.connect("mid", "sc", dst_idx=0)
        sim.connect("fd", "sc", dst_idx=1)
        sim.run()
        t = np.array(sim.get_block("sc").times)
        v = sim.get_block("sc").values
        np.testing.assert_allclose(v[:, 1], 2.0 * np.sin(2 * np.pi * t), atol=1e-12)
        # Outport 側 (積分) は直結線版と bit 一致
        ref = Simulator(t_end=1.0, dt=0.01, rtol=1e-10, atol=1e-13)
        ref.add(Sine(amplitude=1.0, frequency=1.0, id="sine"))
        ref.add(_deep(use_goto=False))
        ref.add(Scope(n_inputs=1, id="sc"))
        ref.connect("sine", "mid")
        ref.connect("mid", "sc")
        ref.run()
        np.testing.assert_array_equal(v[:, 0], ref.get_block("sc").values[:, 0])

    def test_global_goto_at_root_read_inside_deep_subsystem(self) -> None:
        leaf = Subsystem(id="leaf")
        leaf.add(From(tag="src", id="f"))
        leaf.add(Gain(k=2.0, id="g"))
        leaf.add(Outport(port_idx=0, id="o"))
        leaf.connect("f", "g")
        leaf.connect("g", "o")
        mid = Subsystem(id="mid")
        mid.add(leaf)
        mid.add(Outport(port_idx=0, id="o"))
        mid.connect("leaf", "o")
        sim = Simulator(t_end=0.3, dt=0.1)
        sim.add(Constant(value=1.5, id="c"))
        sim.add(Goto(tag="src", tag_visibility="global", id="gt"))
        sim.add(mid)
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("c", "gt")
        sim.connect("mid", "sc")
        sim.run()
        np.testing.assert_allclose(sim.get_block("sc").values[:, 0], 3.0)


class TestGotoInsideTriggeredSubsystem:
    def test_never_fired_goto_is_reported_as_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """code-reviewer SHOULD: 一生 fire しない (配線ミス) Goto は run 後に WARNING で分かる。"""
        sim = Simulator(t_end=0.5, dt=0.1)
        sim.add(Constant(value=1.0, id="one"))
        sim.add(Constant(value=0.0, id="never"))
        sh = Subsystem(id="sh")
        sh.add(Inport(port_idx=0, id="i"))
        sh.add(Outport(port_idx=0, id="o"))
        sh.add(Goto(tag="held", tag_visibility="global", id="gt"))
        sh.add(Trigger(id="trig"))
        sh.connect("i", "o")
        sh.connect("i", "gt")
        sim.add(sh)
        sim.add(From(tag="held", id="fr"))
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("one", "sh", dst_idx=0)
        sim.connect("never", "sh", dst_idx=1)
        sim.connect("fr", "sc")
        with caplog.at_level("WARNING", logger="flode.routing.goto"):
            sim.run()
        assert np.all(sim.get_block("sc").values == 0.0)
        assert any("never fired" in rec.getMessage() for rec in caplog.records)

    def test_from_outside_reads_held_value_and_zero_before_first_fire(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.1)
        sim.add(Sine(amplitude=1.0, frequency=0.25, id="sine"))
        sim.add(PulseGenerator(period=0.4, pulse_width=50.0, id="pulse"))
        sh = Subsystem(id="sh")
        sh.add(Inport(port_idx=0, id="i"))
        sh.add(Outport(port_idx=0, id="o"))
        sh.add(Goto(tag="held", tag_visibility="global", id="gt"))
        sh.add(Trigger(id="trig"))
        sh.connect("i", "o")
        sh.connect("i", "gt")
        sim.add(sh)
        sim.add(From(tag="held", id="fr"))
        sim.add(Scope(n_inputs=2, labels=["outport", "via_goto"], id="sc"))
        sim.connect("sine", "sh", dst_idx=0)
        sim.connect("pulse", "sh", dst_idx=1)
        sim.connect("sh", "sc", dst_idx=0)
        sim.connect("fr", "sc", dst_idx=1)
        sim.run()
        v = sim.get_block("sc").values
        # 初回 fire (t=0.4) までは 0、以後は Outport と同じホールド値
        assert np.all(v[:4, 1] == 0.0)
        np.testing.assert_array_equal(v[:, 1], v[:, 0])
        assert v[-1, 0] == pytest.approx(np.sin(2 * np.pi * 0.25 * 0.8), abs=1e-12)
