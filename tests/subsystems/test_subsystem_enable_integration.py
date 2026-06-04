"""ADR-0058: ``Subsystem`` + 内部 ``Enable`` block 統合テスト。

Subsystem に Enable control block を配置すると、親 Subsystem は enable 入力 1 個を
持ち、enable=true (= `> 0`) の間だけ内部ブロックを動作させる。disable 中の state /
output は ``states_when_enabling`` / ``outputs_when_disabled`` policy に従う。
"""

from __future__ import annotations

import numpy as np
import pytest

from pyflw import Inport, Outport
from pyflw.blocks import Gain, UnitDelay
from pyflw.exceptions import BlockSpecError
from pyflw.subsystems import Enable, Subsystem


def _build_enabled(states_policy: str = "held", outputs_policy: str = "held") -> Subsystem:
    """1 データ入力 (Gain*2) + 1 enable 入力 + 1 出力の Subsystem。"""
    return Subsystem(
        blocks=[
            Inport(port_idx=0, id="in_data"),
            Gain(k=2.0, id="gain"),
            Outport(port_idx=0, id="out"),
            Enable(
                states_when_enabling=states_policy,  # type: ignore[arg-type]
                outputs_when_disabled=outputs_policy,  # type: ignore[arg-type]
                id="en",
            ),
        ],
        connections=[
            {"src": "in_data", "dst": "gain"},
            {"src": "gain", "dst": "out"},
        ],
        id="en_sub",
    )


class TestSubsystemEnablePortStructure:
    """Enable を内蔵した Subsystem の port 構造。"""

    def test_n_inputs_includes_enable_slot(self) -> None:
        sub = _build_enabled()
        assert sub.n_inputs == 2  # 1 data + 1 enable

    def test_enable_slot_after_data(self) -> None:
        sub = _build_enabled()
        sub._build()
        assert sub._enable_slot_idx == sub._n_data_inports
        assert sub._trigger_slot_idx is None  # Trigger なし

    def test_has_enable_flag(self) -> None:
        sub = _build_enabled()
        sub._build()
        assert sub._has_enable is True
        assert sub._has_trigger is False


class TestSubsystemEnableLevelDriven:
    """Enable=true の間は毎ステップ動作、Enable=false で凍結。"""

    def test_enabled_normal_operation(self) -> None:
        """Enable=1 で通常 Subsystem として動く (Gain*2)。"""
        sub = _build_enabled()
        y = sub.output(0.0, np.zeros(0), np.array([3.0, 1.0]))
        np.testing.assert_array_equal(y, np.array([6.0]))

    def test_disabled_output_held(self) -> None:
        """outputs_when_disabled="held": disable 中は直前 fire の値を保持。"""
        sub = _build_enabled(outputs_policy="held")
        # First step: enabled, output = 5*2 = 10
        sub.update(0.0, np.zeros(0), np.array([5.0, 1.0]))
        y = sub.output(0.0, np.zeros(0), np.array([5.0, 1.0]))
        np.testing.assert_array_equal(y, np.array([10.0]))
        # Disable: 出力は直前値 10 を保持
        y_dis = sub.output(0.1, np.zeros(0), np.array([20.0, -1.0]))
        np.testing.assert_array_equal(y_dis, np.array([10.0]))

    def test_disabled_output_reset(self) -> None:
        """outputs_when_disabled="reset": disable 中は 0 を返す。"""
        sub = _build_enabled(outputs_policy="reset")
        sub.update(0.0, np.zeros(0), np.array([5.0, 1.0]))
        # Disable: 0 を返す
        y_dis = sub.output(0.1, np.zeros(0), np.array([20.0, -1.0]))
        np.testing.assert_array_equal(y_dis, np.zeros(1))


class TestSubsystemEnableStatePolicy:
    """states_when_enabling: disable→enable 遷移時の state 扱い。"""

    def test_held_keeps_state_across_enable_transition(self) -> None:
        """states_when_enabling="held": 凍結された state がそのまま続行。"""
        sub = Subsystem(
            blocks=[
                Inport(port_idx=0, id="in_data"),
                UnitDelay(sample_time=0.1, x0=0.0, id="ud"),
                Outport(port_idx=0, id="out"),
                Enable(states_when_enabling="held", id="en"),
            ],
            connections=[
                {"src": "in_data", "dst": "ud"},
                {"src": "ud", "dst": "out"},
            ],
            id="en_held",
        )
        sub._build()
        x = sub.x0.copy()
        # Enabled: state advances to [0, 5]
        x = sub.update(0.0, x, np.array([5.0, 1.0]))
        # Disable: state frozen (still [0, 5])
        x = sub.update(0.1, x, np.array([99.0, -1.0]))
        np.testing.assert_array_equal(x, np.array([0.0, 5.0]))
        # Re-enable: state still [0, 5] (held policy)
        x = sub.update(0.2, x, np.array([7.0, 1.0]))
        # UnitDelay step: x = [prev_x1=5, new_input=7]
        np.testing.assert_array_equal(x, np.array([5.0, 7.0]))

    def test_first_step_enabled_does_not_trigger_reset(self) -> None:
        """ADR-0058 §論点 4 MUST 3: 初回ステップから enable=true で起動した場合、
        ``states_when_enabling="reset"`` policy でも追加の reset は走らない
        (= ``_prev_enable_value`` が NaN sentinel で「初回は遷移ではない」扱い)。
        起動直後の state は既に ``x0`` なので、追加 reset は冪等で意味がない。"""
        sub = Subsystem(
            blocks=[
                Inport(port_idx=0, id="in_data"),
                UnitDelay(sample_time=0.1, x0=42.0, id="ud"),
                Outport(port_idx=0, id="out"),
                Enable(states_when_enabling="reset", id="en"),
            ],
            connections=[
                {"src": "in_data", "dst": "ud"},
                {"src": "ud", "dst": "out"},
            ],
            id="en_first",
        )
        sub._build()
        x = sub.x0.copy()  # [42, 42]
        # 初回ステップで enable=1 から起動。UnitDelay が普通に advance する。
        # (reset policy が「初回も reset」だと state が再度 x0 に戻されてしまうが、
        # NaN sentinel により実際は遷移と見なされず普通に動く)
        x_after = sub.update(0.0, x, np.array([5.0, 1.0]))
        # UnitDelay step: x[0]=prev[1]=42, x[1]=input=5
        np.testing.assert_array_equal(x_after, np.array([42.0, 5.0]))

    def test_reset_resets_state_on_enable_transition(self) -> None:
        """states_when_enabling="reset": disable→enable で state を x0 に戻す。"""
        sub = Subsystem(
            blocks=[
                Inport(port_idx=0, id="in_data"),
                UnitDelay(sample_time=0.1, x0=99.0, id="ud"),
                Outport(port_idx=0, id="out"),
                Enable(states_when_enabling="reset", id="en"),
            ],
            connections=[
                {"src": "in_data", "dst": "ud"},
                {"src": "ud", "dst": "out"},
            ],
            id="en_reset",
        )
        sub._build()
        x = sub.x0.copy()  # [99, 99]
        # Enabled: state advances (UnitDelay: x[0]←99, x[1]←5)
        x = sub.update(0.0, x, np.array([5.0, 1.0]))
        np.testing.assert_array_equal(x, np.array([99.0, 5.0]))
        # Disable: frozen
        x = sub.update(0.1, x, np.array([99.0, -1.0]))
        np.testing.assert_array_equal(x, np.array([99.0, 5.0]))
        # Re-enable: state reset to x0 = [99, 99] BEFORE advancing
        # First _build → x = [99, 99]、次に UnitDelay step: x = [99, 7]
        x = sub.update(0.2, x, np.array([7.0, 1.0]))
        np.testing.assert_array_equal(x, np.array([99.0, 7.0]))


class TestSubsystemEnableNaNSignal:
    """ADR-0058 §エッジケース: enable=NaN は無効化扱い (safe fallback)。"""

    def test_nan_enable_treated_as_disabled(self) -> None:
        sub = _build_enabled(outputs_policy="reset")
        y = sub.output(0.0, np.zeros(0), np.array([5.0, float("nan")]))
        np.testing.assert_array_equal(y, np.zeros(1))


class TestSubsystemEnableMultiplePlacement:
    """ADR-0058 §論点 8: Enable 多重配置は build 時に reject。"""

    def test_multiple_enable_blocks_rejected(self) -> None:
        sub = Subsystem(
            blocks=[
                Inport(port_idx=0),
                Outport(port_idx=0),
                Enable(id="en0"),
                Enable(id="en1"),
            ],
            id="multi_en",
        )
        with pytest.raises(BlockSpecError, match="at most one Enable"):
            sub._build()
