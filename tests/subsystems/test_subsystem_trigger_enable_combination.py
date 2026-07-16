"""ADR-0058 §論点 9: Trigger + Enable 同居 (edge AND enable で fire)。

両方を内蔵した Subsystem は、edge が立ったときかつ enable が true のときに fire する。
slot 順序は [data..., enable, trigger] (ADR-0058 §論点 4)。
"""

from __future__ import annotations

import numpy as np

from flode import Inport, Outport
from flode.blocks import Gain
from flode.subsystems import Enable, Subsystem, Trigger


def _build_trigger_enable() -> Subsystem:
    """1 データ + 1 enable + 1 trigger + 1 出力 (Gain*2)。"""
    return Subsystem(
        blocks=[
            Inport(port_idx=0, id="in_data"),
            Gain(k=2.0, id="gain"),
            Outport(port_idx=0, id="out"),
            Enable(id="en"),
            Trigger(trigger_type="rising", id="trig"),
        ],
        connections=[
            {"src": "in_data", "dst": "gain"},
            {"src": "gain", "dst": "out"},
        ],
        id="te_sub",
    )


class TestSlotOrder:
    """slot 順序は [data..., enable, trigger] (= enable は trigger より前)。"""

    def test_n_inputs_count(self) -> None:
        sub = _build_trigger_enable()
        assert sub.n_inputs == 3  # data + enable + trigger

    def test_slot_indices(self) -> None:
        sub = _build_trigger_enable()
        sub._build()
        assert sub._n_data_inports == 1
        assert sub._enable_slot_idx == 1
        assert sub._trigger_slot_idx == 2

    def test_both_flags_set(self) -> None:
        sub = _build_trigger_enable()
        sub._build()
        assert sub._has_enable is True
        assert sub._has_trigger is True


class TestFireCondition:
    """fire = edge AND enabled (ADR-0058 §論点 9)。"""

    def test_edge_with_enable_true_fires(self) -> None:
        sub = _build_trigger_enable()
        # u = [data, enable, trigger]
        # NaN→0: no edge → no fire
        sub.update(0.0, np.zeros(0), np.array([5.0, 1.0, 0.0]))
        # 0→1 (rising), enable=1: fire
        sub.update(0.1, np.zeros(0), np.array([5.0, 1.0, 1.0]))
        np.testing.assert_array_equal(sub._last_y, np.array([10.0]))

    def test_edge_with_enable_false_does_not_fire(self) -> None:
        sub = _build_trigger_enable()
        sub.update(0.0, np.zeros(0), np.array([5.0, -1.0, 0.0]))
        # rising edge but enable=-1: no fire
        sub.update(0.1, np.zeros(0), np.array([5.0, -1.0, 1.0]))
        np.testing.assert_array_equal(sub._last_y, np.zeros(1))

    def test_no_edge_with_enable_true_does_not_fire(self) -> None:
        sub = _build_trigger_enable()
        sub.update(0.0, np.zeros(0), np.array([5.0, 1.0, 1.0]))
        # No edge (trigger unchanged), enable=1
        sub.update(0.1, np.zeros(0), np.array([5.0, 1.0, 1.0]))
        np.testing.assert_array_equal(sub._last_y, np.zeros(1))


class TestOutputBehavior:
    """disabled 時は outputs_when_disabled policy、enabled 時は cached _last_y。"""

    def test_output_held_during_disable(self) -> None:
        sub = _build_trigger_enable()
        # Fire once with enable=1, value cached
        sub.update(0.0, np.zeros(0), np.array([7.0, 1.0, 0.0]))
        sub.update(0.1, np.zeros(0), np.array([7.0, 1.0, 1.0]))
        # _last_y = 14
        # Now disable
        y = sub.output(0.2, np.zeros(0), np.array([99.0, -1.0, 1.0]))
        # default outputs_when_disabled = "held"
        np.testing.assert_array_equal(y, np.array([14.0]))
