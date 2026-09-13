"""Trigger / Enable 付き Subsystem を ``Simulator`` に組み込んだときのスケジューリング回帰テスト。

2026-09-13 の複雑モデル検証 (``examples/hybrid_torture_verification.py``) で
見つかった 2 件のバグの再現テスト:

1. 内部に状態を持たない Triggered Subsystem (Inport → Outport + Trigger) は
   discrete_state に登録されず ``update()`` が一度も呼ばれない → 出力が 0 のまま。
2. 内部データ経路が非直達 (Integrator のみ) の Enabled Subsystem は、Simulator が
   非直達ブロックの ``output()`` を入力ゼロで呼ぶため enable ポートが常に 0 と
   読まれ、出力が初期値で固定される (状態は積分されているのに出力だけ凍結)。
"""

from __future__ import annotations

import numpy as np
import pytest

from flode import Enable, Inport, Outport, Simulator, Subsystem, Trigger
from flode.blocks import (
    Clock,
    Constant,
    Demux,
    Gain,
    Integrator,
    Mux,
    PulseGenerator,
    Scope,
    Step,
    Sum,
)
from flode.exceptions import AlgebraicLoopError, BlockSpecError


def _sample_and_hold() -> Subsystem:
    """状態を持たない Triggered Subsystem (= 純粋なサンプル & ホールド)。"""
    sub = Subsystem(id="sh")
    sub.add(Inport(port_idx=0, id="in_data"))
    sub.add(Outport(port_idx=0, id="out"))
    sub.add(Trigger(trigger_type="rising", id="trig"))
    sub.connect("in_data", "out")
    return sub


def _enabled_integrator(outputs_policy: str = "held") -> Subsystem:
    """内部が Integrator のみ (= 非直達) の Enabled Subsystem。"""
    sub = Subsystem(id="en_int")
    sub.add(Inport(port_idx=0, id="in_data"))
    sub.add(Integrator(x0=0.0, id="I"))
    sub.add(Outport(port_idx=0, id="out"))
    sub.add(Enable(outputs_when_disabled=outputs_policy, id="en"))  # type: ignore[arg-type]
    sub.connect("in_data", "I")
    sub.connect("I", "out")
    return sub


class TestStatelessTriggeredSubsystemFires:
    """バグ 1: 状態なし Triggered Subsystem が Simulator 上で発火すること。"""

    def test_stateless_triggered_subsystem_samples_on_rising_edge(self) -> None:
        sim = Simulator(t_end=2.0, dt=0.1)
        sim.add(Clock(id="clk"))
        # 周期 0.5 s、duty 50% → 立ち上がり t = 0.5, 1.0, 1.5, 2.0 (t=0 は NaN sentinel で不発)
        sim.add(PulseGenerator(period=0.5, pulse_width=50.0, id="pulse"))
        sim.add(_sample_and_hold())
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("clk", "sh", dst_idx=0)
        sim.connect("pulse", "sh", dst_idx=1)
        sim.connect("sh", "scope")
        sim.run()

        held = sim.get_block("scope").values[:, 0]
        expected = np.array([0.0] * 5 + [0.5] * 5 + [1.0] * 5 + [1.5] * 5 + [2.0])
        np.testing.assert_allclose(held, expected, atol=1e-12)

    def test_stateless_triggered_subsystem_nested_in_subsystem_is_rejected(self) -> None:
        """入れ子 (Subsystem 内) では内部にクロック解決が走らないため fail-closed。"""
        outer = Subsystem(id="outer")
        outer.add(Inport(port_idx=0, id="d"))
        outer.add(Inport(port_idx=1, id="trg"))
        outer.add(_sample_and_hold())
        outer.add(Outport(port_idx=0, id="o"))
        outer.connect("d", "sh", dst_idx=0)
        outer.connect("trg", "sh", dst_idx=1)
        outer.connect("sh", "o")
        sim = Simulator(t_end=1.0, dt=0.1)
        sim.add(Clock(id="clk"))
        sim.add(PulseGenerator(period=0.5, id="pulse"))
        sim.add(outer)
        sim.connect("clk", "outer", dst_idx=0)
        sim.connect("pulse", "outer", dst_idx=1)
        with pytest.raises(BlockSpecError, match="sh"):
            sim.run()


class TestEnabledSubsystemNonFeedthroughPath:
    """バグ 2: 非直達な内部経路を持つ Enabled Subsystem の出力が状態を反映すること。"""

    @pytest.mark.parametrize("outputs_policy", ["held", "reset"])
    def test_enabled_integrator_output_follows_state(self, outputs_policy: str) -> None:
        sim = Simulator(t_end=1.0, dt=0.1, rtol=1e-10, atol=1e-13)
        sim.add(Constant(value=1.0, id="one"))
        sim.add(Constant(value=1.0, id="enable_on"))
        sim.add(_enabled_integrator(outputs_policy))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("one", "en_int", dst_idx=0)
        sim.connect("enable_on", "en_int", dst_idx=1)
        sim.connect("en_int", "scope")
        sim.run()

        y = sim.get_block("scope").values[:, 0]
        np.testing.assert_allclose(y, np.linspace(0.0, 1.0, 11), atol=1e-9)

    def test_enabled_integrator_holds_output_while_disabled(self) -> None:
        """enable が t=0.5 で落ちると、状態も出力もその時点の値で凍結する (held)。"""
        sim = Simulator(t_end=1.0, dt=0.1, rtol=1e-10, atol=1e-13)
        sim.add(Constant(value=1.0, id="one"))
        sim.add(Step(step_time=0.5, initial_value=1.0, final_value=0.0, id="enable_sig"))
        sim.add(_enabled_integrator("held"))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("one", "en_int", dst_idx=0)
        sim.connect("enable_sig", "en_int", dst_idx=1)
        sim.connect("en_int", "scope")
        sim.run()

        y = sim.get_block("scope").values[:, 0]
        expected = np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5])
        np.testing.assert_allclose(y, expected, atol=1e-9)

    def test_enabled_integrator_in_feedback_loop_is_not_an_algebraic_loop(self) -> None:
        """データ経路は非直達のまま (= 自身の出力を入力に戻しても代数ループにならない)。

        enable ポートだけを直達扱いにする修正であることの保証。x' = 1 - x, x(0) = 0。
        """
        sim = Simulator(t_end=1.0, dt=0.1, rtol=1e-10, atol=1e-13)
        sim.add(Constant(value=1.0, id="one"))
        sim.add(Constant(value=1.0, id="enable_on"))
        sim.add(Sum(signs="+-", id="err"))
        sim.add(_enabled_integrator("held"))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("one", "err", dst_idx=0)
        sim.connect("en_int", "err", dst_idx=1)
        sim.connect("err", "en_int", dst_idx=0)
        sim.connect("enable_on", "en_int", dst_idx=1)
        sim.connect("en_int", "scope")
        try:
            sim.run()
        except AlgebraicLoopError as exc:  # pragma: no cover - 失敗時の診断用
            pytest.fail(f"non-feedthrough data path must not form an algebraic loop: {exc}")

        t = np.array(sim.get_block("scope").times)
        y = sim.get_block("scope").values[:, 0]
        np.testing.assert_allclose(y, 1.0 - np.exp(-t), atol=1e-8)

    @pytest.mark.parametrize("sm_b", [False, True], ids=["sm_a", "sm_b"])
    def test_enabled_integrator_feedback_loop_runs_in_both_paths(self, sm_b: bool) -> None:
        """フィードバックループ構成が SM-A (_step) / SM-B (_step_vector) の両経路で動くこと。

        code-reviewer MUST (2026-09-13): 制御ポートの値埋めに全ポート解決ヘルパーを
        流用すると、データ経路の上流が未計算の SM-B 経路で KeyError になる。
        """
        sim = Simulator(t_end=1.0, dt=0.1, rtol=1e-10, atol=1e-13)
        sim.add(Constant(value=1.0, id="one"))
        sim.add(Constant(value=1.0, id="enable_on"))
        sim.add(Sum(signs="+-", id="err"))
        sim.add(_enabled_integrator("held"))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("one", "err", dst_idx=0)
        sim.connect("en_int", "err", dst_idx=1)
        sim.connect("err", "en_int", dst_idx=0)
        sim.connect("enable_on", "en_int", dst_idx=1)
        if sm_b:
            # ベクトルポートを 1 つ置くだけで Simulator は SM-B 経路に切り替わる
            sim.add(Mux(n=2, id="mux"))
            sim.add(Demux(n=2, id="demux"))
            sim.connect("en_int", "mux", dst_idx=0)
            sim.connect("one", "mux", dst_idx=1)
            sim.connect("mux", "demux")
            sim.connect("demux", "scope", src_idx=0)
        else:
            sim.connect("en_int", "scope")
        sim.run()
        t = np.array(sim.get_block("scope").times)
        y = sim.get_block("scope").values[:, 0]
        np.testing.assert_allclose(y, 1.0 - np.exp(-t), atol=1e-8)

    @pytest.mark.parametrize("sm_b", [False, True], ids=["sm_a", "sm_b"])
    def test_linearize_enabled_integrator_feedback_loop(self, sm_b: bool) -> None:
        """linearize の 2 パス複製でもフィードバックループ構成が KeyError にならず A = [[-1]]。"""
        sim = Simulator(t_end=1.0, dt=0.1)
        sim.add(Constant(value=1.0, id="one"))
        sim.add(Constant(value=1.0, id="enable_on"))
        sim.add(Sum(signs="+-", id="err"))
        sim.add(_enabled_integrator("held"))
        sim.connect("one", "err", dst_idx=0)
        sim.connect("en_int", "err", dst_idx=1)
        sim.connect("err", "en_int", dst_idx=0)
        sim.connect("enable_on", "en_int", dst_idx=1)
        if sm_b:
            sim.add(Mux(n=2, id="mux"))
            sim.connect("en_int", "mux", dst_idx=0)
            sim.connect("one", "mux", dst_idx=1)
        ls = sim.linearize()
        np.testing.assert_allclose(ls.A, [[-1.0]], atol=1e-6)

    def test_linearize_reads_enable_port_of_non_feedthrough_subsystem(self) -> None:
        """linearize の 2 パス複製でも enable ポートが読まれ、C = [[1]] になること。"""
        sim = Simulator(t_end=1.0, dt=0.1)
        sim.add(Constant(value=1.0, id="enable_on"))
        sim.add(_enabled_integrator("held"))
        sim.connect("enable_on", "en_int", dst_idx=1)  # データ入力は未結線 = 外部入力
        ls = sim.linearize()
        np.testing.assert_allclose(ls.A, [[0.0]], atol=1e-9)
        np.testing.assert_allclose(ls.B, [[1.0]], atol=1e-6)
        np.testing.assert_allclose(ls.C, [[1.0]], atol=1e-6)

    def test_enable_port_fed_back_from_own_output_is_an_algebraic_loop(self) -> None:
        """enable ポートは直達なので、自身の出力 (直達 Gain 経由) で駆動すると代数ループ。"""
        sub = Subsystem(id="en_gain")
        sub.add(Inport(port_idx=0, id="in_data"))
        sub.add(Gain(k=2.0, id="g"))
        sub.add(Outport(port_idx=0, id="out"))
        sub.add(Enable(id="en"))
        sub.connect("in_data", "g")
        sub.connect("g", "out")
        sim = Simulator(t_end=0.1, dt=0.1)
        sim.add(Constant(value=1.0, id="one"))
        sim.add(sub)
        sim.connect("one", "en_gain", dst_idx=0)
        sim.connect("en_gain", "en_gain", dst_idx=1)
        with pytest.raises(AlgebraicLoopError):
            sim.run()
