"""ADR-0058: ``Subsystem`` + 内部 ``Trigger`` block 統合テスト。

Subsystem に Trigger control block を配置すると、親 Subsystem は trigger 入力 1 個を
持つ Triggered Subsystem として動作する。旧 ``TriggeredSubsystem`` と同等の semantics
(edge 駆動、state 凍結、output キャッシュ、NaN sentinel) を新方式で検証する。
"""

from __future__ import annotations

import numpy as np
import pytest

from pyflw import Inport, Outport
from pyflw.blocks import Gain, UnitDelay
from pyflw.exceptions import BlockSpecError
from pyflw.subsystems import Subsystem, Trigger


def _build_triggered(trigger_type: str = "rising") -> Subsystem:
    """1 データ入力 (Gain*2) + 1 trigger 入力 + 1 出力の Subsystem。"""
    return Subsystem(
        blocks=[
            Inport(port_idx=0, id="in_data"),
            Gain(k=2.0, id="gain"),
            Outport(port_idx=0, id="out"),
            Trigger(trigger_type=trigger_type, id="trig"),  # type: ignore[arg-type]
        ],
        connections=[
            {"src": "in_data", "dst": "gain"},
            {"src": "gain", "dst": "out"},
        ],
        id="trig_sub",
    )


class TestSubsystemTriggerPortStructure:
    """Trigger を内蔵した Subsystem の port 数 / slot 順序。"""

    def test_n_inputs_includes_trigger_slot(self) -> None:
        sub = _build_triggered()
        assert sub.n_inputs == 2  # 1 data + 1 trigger

    def test_n_outputs_unchanged(self) -> None:
        sub = _build_triggered()
        assert sub.n_outputs == 1

    def test_trigger_slot_is_last(self) -> None:
        """ADR-0058 §論点 4: slot 順序は [data..., trigger]、trigger は末尾。"""
        sub = _build_triggered()
        sub._build()
        assert sub._trigger_slot_idx == sub._n_data_inports
        # SHOULD 4: slot index は実際に末尾 (= n_inputs - 1) と等しい
        assert sub._trigger_slot_idx == sub.n_inputs - 1

    def test_has_trigger_flag(self) -> None:
        sub = _build_triggered()
        sub._build()
        assert sub._has_trigger is True
        assert sub._has_enable is False


class TestSubsystemTriggerEdgeDetection:
    """update() の edge 検出 (旧 TriggeredSubsystem と同 semantics)。"""

    def test_first_step_no_fire(self) -> None:
        """NaN sentinel: 起動時は edge にしない。"""
        sub = _build_triggered()
        sub.update(0.0, np.zeros(0), np.array([5.0, 1.0]))
        np.testing.assert_array_equal(sub._last_y, np.zeros(1))

    def test_rising_edge_fires(self) -> None:
        sub = _build_triggered("rising")
        sub.update(0.0, np.zeros(0), np.array([3.0, 0.0]))  # NaN→0: no fire
        sub.update(0.1, np.zeros(0), np.array([7.0, 1.0]))  # 0→1: rising
        np.testing.assert_array_equal(sub._last_y, np.array([14.0]))

    def test_no_fire_when_trigger_unchanged(self) -> None:
        sub = _build_triggered("rising")
        sub.update(0.0, np.zeros(0), np.array([5.0, 1.0]))  # NaN→1
        sub.update(0.1, np.zeros(0), np.array([5.0, 1.0]))  # 1→1: no edge
        np.testing.assert_array_equal(sub._last_y, np.zeros(1))

    def test_falling_edge_in_falling_mode(self) -> None:
        sub = _build_triggered("falling")
        sub.update(0.0, np.zeros(0), np.array([5.0, 1.0]))
        sub.update(0.1, np.zeros(0), np.array([3.0, -0.5]))  # 1→-0.5
        np.testing.assert_array_equal(sub._last_y, np.array([6.0]))

    def test_either_mode_fires_both(self) -> None:
        sub = _build_triggered("either")
        sub.update(0.0, np.zeros(0), np.array([5.0, 1.0]))
        sub.update(0.1, np.zeros(0), np.array([3.0, -1.0]))  # 1→-1: falling
        np.testing.assert_array_equal(sub._last_y, np.array([6.0]))
        sub.update(0.2, np.zeros(0), np.array([4.0, 1.0]))  # -1→1: rising
        np.testing.assert_array_equal(sub._last_y, np.array([8.0]))


class TestSubsystemTriggerOutputCache:
    """output() は fire の有無に関わらず ``_last_y`` を返す。"""

    def test_output_returns_cached_value(self) -> None:
        sub = _build_triggered()
        y0 = sub.output(0.0, np.zeros(0), np.array([5.0, 0.0]))
        np.testing.assert_array_equal(y0, np.zeros(1))
        sub.update(0.1, np.zeros(0), np.array([10.0, 0.0]))  # NaN→0: no fire
        sub.update(0.2, np.zeros(0), np.array([10.0, 1.0]))  # 0→1: fire
        y2 = sub.output(0.2, np.zeros(0), np.array([10.0, 1.0]))
        np.testing.assert_array_equal(y2, np.array([20.0]))


class TestSubsystemTriggerStateFreeze:
    """Trigger 配下の UnitDelay は fire 時のみ advance。"""

    def test_unit_delay_advances_only_on_fire(self) -> None:
        sub = Subsystem(
            blocks=[
                Inport(port_idx=0, id="in_data"),
                UnitDelay(sample_time=0.1, x0=99.0, id="ud"),
                Outport(port_idx=0, id="out"),
                Trigger(trigger_type="rising", id="trig"),
            ],
            connections=[
                {"src": "in_data", "dst": "ud"},
                {"src": "ud", "dst": "out"},
            ],
            id="trig_ud",
        )
        sub._build()
        assert sub.n_states == 2  # UnitDelay 2-state

        # 初期 state: [99, 99]
        x0 = sub.x0.copy()
        # NaN→1: no fire、state 凍結
        x1 = sub.update(0.0, x0, np.array([5.0, 1.0]))
        np.testing.assert_array_equal(x1, x0)

        # 1→1: no edge、state 凍結
        x2 = sub.update(0.1, x1, np.array([5.0, 1.0]))
        np.testing.assert_array_equal(x2, x1)

        # 1→0: no rising、state 凍結
        x3 = sub.update(0.2, x2, np.array([5.0, 0.0]))
        np.testing.assert_array_equal(x3, x2)

        # 0→1: rising、fire → state advance
        x4 = sub.update(0.3, x3, np.array([5.0, 1.0]))
        # UnitDelay: x[0] = x[1] (= 99), x[1] = input (= 5)
        np.testing.assert_array_equal(x4, np.array([99.0, 5.0]))


class TestSubsystemTriggerMultiplePlacement:
    """ADR-0058 §論点 8: 多重配置は build 時に reject。"""

    def test_multiple_trigger_blocks_rejected(self) -> None:
        sub = Subsystem(
            blocks=[
                Inport(port_idx=0),
                Outport(port_idx=0),
                Trigger(id="trig0"),
                Trigger(id="trig1"),
            ],
            id="multi_trig",
        )
        with pytest.raises(BlockSpecError, match="at most one Trigger"):
            sub._build()


class TestSubsystemTriggerFunctionCallNotImplemented:
    """ADR-0058 §論点 10: function-call trigger は MVP では NotImplementedError。"""

    def test_function_call_rejected_at_build(self) -> None:
        sub = Subsystem(
            blocks=[
                Outport(port_idx=0),
                Trigger(trigger_type="function-call", id="trig"),
            ],
            id="fc_sub",
        )
        with pytest.raises(NotImplementedError, match="function-call"):
            sub._build()
