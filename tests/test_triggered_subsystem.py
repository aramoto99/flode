"""``TriggeredSubsystem`` (ADR-0036 §(2)(3)) のテスト。

- ``trigger_mode``: ``"rising"`` / ``"falling"`` / ``"either"`` の edge 検出
- 内部ブロックは fire 時のみ実行 (= ``_step_inner`` 経由)、fire しないステップでは
  内部状態凍結 + 前回 ``_last_y`` キャッシュ維持
- NaN sentinel で起動時の偽 edge を防ぐ
- ``_is_trigger_edge`` ヘルパの単体テスト

ADR-0036 §(8) 数値完全不変ガード: TriggeredSubsystem を含まないモデルでは
``Simulator._run_sm_a_loop`` の挙動は本 ADR 前と完全に同一。本テストは新規追加のみ
で既存テストを変更しない。
"""

from __future__ import annotations

import numpy as np
import pytest

from pyflw import Inport, Outport, TriggeredSubsystem
from pyflw.blocks import Gain, UnitDelay
from pyflw.exceptions import BlockSpecError
from pyflw.subsystems.triggered import TRIGGER_MODES, _is_trigger_edge

# ---------------------------------------------------------------------------
# _is_trigger_edge ヘルパ
# ---------------------------------------------------------------------------


class TestIsEdgeHelper:
    def test_rising_zero_to_positive(self) -> None:
        assert _is_trigger_edge(0.0, 1.0, "rising") is True

    def test_rising_negative_to_positive(self) -> None:
        assert _is_trigger_edge(-0.5, 0.5, "rising") is True

    def test_rising_no_edge_when_already_positive(self) -> None:
        assert _is_trigger_edge(1.0, 2.0, "rising") is False

    def test_rising_no_edge_on_falling(self) -> None:
        assert _is_trigger_edge(1.0, -1.0, "rising") is False

    def test_falling_positive_to_negative(self) -> None:
        assert _is_trigger_edge(1.0, -0.5, "falling") is True

    def test_falling_no_edge_on_rising(self) -> None:
        assert _is_trigger_edge(-1.0, 1.0, "falling") is False

    def test_either_detects_both(self) -> None:
        assert _is_trigger_edge(-1.0, 1.0, "either") is True
        assert _is_trigger_edge(1.0, -1.0, "either") is True

    def test_either_no_edge_when_constant(self) -> None:
        assert _is_trigger_edge(1.0, 1.0, "either") is False
        assert _is_trigger_edge(-1.0, -1.0, "either") is False

    def test_nan_prev_never_triggers(self) -> None:
        # 起動時 (= prev=NaN) の偽 edge 防止
        assert _is_trigger_edge(float("nan"), 1.0, "rising") is False
        assert _is_trigger_edge(float("nan"), -1.0, "falling") is False
        assert _is_trigger_edge(float("nan"), 1.0, "either") is False

    def test_nan_curr_never_triggers(self) -> None:
        assert _is_trigger_edge(1.0, float("nan"), "rising") is False

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="unknown mode"):
            _is_trigger_edge(0.0, 1.0, "invalid")


# ---------------------------------------------------------------------------
# TriggeredSubsystem コンストラクタ
# ---------------------------------------------------------------------------


def _build_simple_triggered(trigger_mode: str = "rising") -> TriggeredSubsystem:
    """1 データ入力 (Gain*2) + 1 trigger 入力 + 1 出力の TriggeredSubsystem。"""
    return TriggeredSubsystem(
        n_inputs=2,
        n_outputs=1,
        trigger_mode=trigger_mode,
        blocks=[
            Inport(port_idx=0, id="in_data"),
            Gain(k=2.0, id="gain"),
            Outport(port_idx=0, id="out"),
        ],
        connections=[
            {"src": "in_data", "dst": "gain"},
            {"src": "gain", "dst": "out"},
        ],
        id="trig_sub",
    )


class TestConstructor:
    def test_default_trigger_mode_is_rising(self) -> None:
        sub = _build_simple_triggered()
        assert sub.trigger_mode == "rising"

    def test_explicit_falling(self) -> None:
        sub = _build_simple_triggered("falling")
        assert sub.trigger_mode == "falling"

    def test_explicit_either(self) -> None:
        sub = _build_simple_triggered("either")
        assert sub.trigger_mode == "either"

    def test_invalid_trigger_mode_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="trigger_mode must be one of"):
            TriggeredSubsystem(
                n_inputs=2,
                n_outputs=1,
                trigger_mode="invalid",
            )

    def test_n_inputs_zero_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="must be >= 1"):
            TriggeredSubsystem(n_inputs=0, n_outputs=1)

    def test_initial_prev_trigger_is_nan(self) -> None:
        sub = _build_simple_triggered()
        assert np.isnan(sub._prev_trigger_value)

    def test_initial_last_y_is_zeros(self) -> None:
        sub = _build_simple_triggered()
        np.testing.assert_array_equal(sub._last_y, np.zeros(1))

    def test_trigger_modes_constant_lists_three(self) -> None:
        assert set(TRIGGER_MODES) == {"rising", "falling", "either"}


# ---------------------------------------------------------------------------
# update / output: edge detection + state freezing
# ---------------------------------------------------------------------------


class TestEdgeDetection:
    def test_first_step_no_fire(self) -> None:
        """NaN sentinel: 起動時の最初の step では fire しない。"""
        sub = _build_simple_triggered()
        sub.update(0.0, np.zeros(0), np.array([5.0, 1.0]))
        np.testing.assert_array_equal(sub._last_y, np.zeros(1))

    def test_rising_edge_fires(self) -> None:
        """rising edge で内部ブロックが実行され ``_last_y`` が更新される。"""
        sub = _build_simple_triggered("rising")
        # NaN → 0.0: edge ではない
        sub.update(0.0, np.zeros(0), np.array([3.0, 0.0]))
        # 0.0 → 1.0: rising edge
        sub.update(0.1, np.zeros(0), np.array([7.0, 1.0]))
        # Gain k=2.0 で u=7 → y=14
        np.testing.assert_array_equal(sub._last_y, np.array([14.0]))

    def test_no_fire_when_trigger_unchanged(self) -> None:
        sub = _build_simple_triggered("rising")
        sub.update(0.0, np.zeros(0), np.array([5.0, 1.0]))  # NaN→1: no fire
        sub.update(0.1, np.zeros(0), np.array([5.0, 1.0]))  # 1→1: no edge
        np.testing.assert_array_equal(sub._last_y, np.zeros(1))

    def test_falling_edge_fires_in_falling_mode(self) -> None:
        sub = _build_simple_triggered("falling")
        sub.update(0.0, np.zeros(0), np.array([5.0, 1.0]))  # NaN→1: no fire
        sub.update(0.1, np.zeros(0), np.array([3.0, -0.5]))  # 1 → -0.5: falling
        np.testing.assert_array_equal(sub._last_y, np.array([6.0]))

    def test_falling_edge_does_not_fire_in_rising_mode(self) -> None:
        sub = _build_simple_triggered("rising")
        sub.update(0.0, np.zeros(0), np.array([5.0, 1.0]))  # NaN→1: no fire
        sub.update(0.1, np.zeros(0), np.array([3.0, -0.5]))  # 1→-0.5: falling, but rising mode
        np.testing.assert_array_equal(sub._last_y, np.zeros(1))

    def test_either_mode_fires_on_rising_and_falling(self) -> None:
        sub = _build_simple_triggered("either")
        sub.update(0.0, np.zeros(0), np.array([5.0, 1.0]))  # NaN→1: no fire
        sub.update(0.1, np.zeros(0), np.array([3.0, -1.0]))  # 1→-1: falling fires
        np.testing.assert_array_equal(sub._last_y, np.array([6.0]))
        sub.update(0.2, np.zeros(0), np.array([4.0, 1.0]))  # -1→1: rising fires
        np.testing.assert_array_equal(sub._last_y, np.array([8.0]))

    def test_output_returns_cached_value(self) -> None:
        """``output`` は fire の有無に関わらず ``_last_y`` を返す。"""
        sub = _build_simple_triggered()
        # Initial state: _last_y = [0]
        y0 = sub.output(0.0, np.zeros(0), np.array([5.0, 0.0]))
        np.testing.assert_array_equal(y0, np.zeros(1))

        # No fire (NaN→1)
        sub.update(0.0, np.zeros(0), np.array([5.0, 1.0]))
        y1 = sub.output(0.0, np.zeros(0), np.array([5.0, 1.0]))
        np.testing.assert_array_equal(y1, np.zeros(1))  # まだ default

        # Fire (1→0→1 で rising)
        sub.update(0.1, np.zeros(0), np.array([3.0, 0.0]))  # 1→0: no fire
        sub.update(0.2, np.zeros(0), np.array([10.0, 1.0]))  # 0→1: fire (Gain*2 → 20)
        y2 = sub.output(0.2, np.zeros(0), np.array([10.0, 1.0]))
        np.testing.assert_array_equal(y2, np.array([20.0]))


# ---------------------------------------------------------------------------
# 内部状態を持つ TriggeredSubsystem (= UnitDelay 内蔵)
# ---------------------------------------------------------------------------


class TestStateFreeze:
    def test_internal_unit_delay_advances_only_on_fire(self) -> None:
        """UnitDelay (n_states=2) を内蔵した TriggeredSubsystem。

        rising edge でのみ UnitDelay が advance、それ以外では state 凍結。
        """
        sub = TriggeredSubsystem(
            n_inputs=2,
            n_outputs=1,
            trigger_mode="rising",
            blocks=[
                Inport(port_idx=0, id="in_data"),
                UnitDelay(sample_time=0.1, x0=99.0, id="ud"),
                Outport(port_idx=0, id="out"),
            ],
            connections=[
                {"src": "in_data", "dst": "ud"},
                {"src": "ud", "dst": "out"},
            ],
            id="trig_ud",
        )
        # _build を発火させて n_states を確定
        sub._build()
        assert sub.n_states == 2  # UnitDelay は 2-state (ADR-0015)

        # NaN→1: no fire
        x_after = sub.update(0.0, sub.x0, np.array([5.0, 1.0]))
        np.testing.assert_array_equal(x_after, sub.x0)  # 凍結

        # 1→0: no fire (rising mode)
        x_after = sub.update(0.1, sub.x0, np.array([5.0, 0.0]))
        np.testing.assert_array_equal(x_after, sub.x0)  # 凍結

        # 0→1: rising → fire
        x_after = sub.update(0.2, sub.x0, np.array([7.0, 1.0]))
        # UnitDelay update: state[0]=state[1]=99, state[1]<-u=7
        np.testing.assert_array_equal(x_after, np.array([99.0, 7.0]))


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_save_load_round_trip_rising(self, tmp_path) -> None:
        from pyflw import Simulator

        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(_build_simple_triggered("rising"))
        path = tmp_path / "trig.flw.json"
        sim.save(path)

        sim2 = Simulator.load(path)
        sub2 = sim2.get_block("trig_sub")
        assert isinstance(sub2, TriggeredSubsystem)
        assert sub2.trigger_mode == "rising"

    def test_save_load_round_trip_either(self, tmp_path) -> None:
        from pyflw import Simulator

        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(_build_simple_triggered("either"))
        path = tmp_path / "trig.flw.json"
        sim.save(path)

        sim2 = Simulator.load(path)
        sub2 = sim2.get_block("trig_sub")
        assert isinstance(sub2, TriggeredSubsystem)
        assert sub2.trigger_mode == "either"
