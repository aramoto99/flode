"""``TriggeredSubsystem`` (ADR-0036 §(2)(3)) のテスト。

ADR-0058 で ``TriggeredSubsystem`` は ``Subsystem`` + 内部 ``Trigger`` block 構築の
deprecation factory に縮退した。本テストは:

- ``_is_trigger_edge`` / ``TRIGGER_MODES`` の backward-compat shim 動作
- ``TriggeredSubsystem(trigger_mode=...)`` 経由でも edge 駆動 / 状態凍結 / output
  キャッシュが ADR-0036 仕様通りに動くこと (= 戻り値は ``Subsystem`` 実体だが、
  内部 ``Trigger`` block が自動配置されているため挙動は完全互換)
- ``DeprecationWarning`` が発生すること

ADR-0036 §(8) / ADR-0058 §論点 14 数値完全不変ガード: control block を持たない
Subsystem は既存 hot-path をそのまま通る (= 既存 949+ 件の pytest 数値は変化なし)。
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from pyflw import Inport, Outport, TriggeredSubsystem
from pyflw.blocks import Gain, UnitDelay
from pyflw.exceptions import BlockSpecError
from pyflw.subsystems.control_blocks import Trigger
from pyflw.subsystems.triggered import TRIGGER_MODES, _is_trigger_edge


def _get_inner_trigger(sub: object) -> Trigger:
    """``TriggeredSubsystem(...)`` から返された Subsystem の内部 Trigger block を取得。"""
    # _inner_blocks は build 前から存在
    inner = getattr(sub, "_inner_blocks", [])
    for b in inner:
        if isinstance(b, Trigger):
            return b
    raise AssertionError("expected an inner Trigger block from TriggeredSubsystem factory")


# ``TriggeredSubsystem(...)`` 呼び出しで出る DeprecationWarning をテスト全体で許容。
pytestmark = pytest.mark.filterwarnings(
    "ignore:TriggeredSubsystem is deprecated:DeprecationWarning"
)

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
    """ADR-0058: ``TriggeredSubsystem(...)`` は ``__new__`` で ``Subsystem`` +
    内部 ``Trigger`` block を構築する factory に縮退。trigger_mode は内部 Trigger
    block の ``trigger_type`` に転送される。"""

    def test_default_trigger_mode_is_rising(self) -> None:
        sub = _build_simple_triggered()
        assert _get_inner_trigger(sub).trigger_type == "rising"

    def test_explicit_falling(self) -> None:
        sub = _build_simple_triggered("falling")
        assert _get_inner_trigger(sub).trigger_type == "falling"

    def test_explicit_either(self) -> None:
        sub = _build_simple_triggered("either")
        assert _get_inner_trigger(sub).trigger_type == "either"

    def test_invalid_trigger_mode_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="trigger_mode must be one of"):
            TriggeredSubsystem(
                trigger_mode="invalid",
            )

    def test_n_inputs_argument_rejected(self) -> None:
        """ADR-0039: ``n_inputs`` / ``n_outputs`` 引数は v2.0 で廃止 (TypeError)。

        v1 では ``n_inputs=0`` で BlockSpecError("must be >= 1") を返したが、
        v2 では ``n_inputs`` 引数自体が削除されたため、TypeError で migration
        を促す。"""
        with pytest.raises(TypeError, match="were removed in v2.0"):
            TriggeredSubsystem(n_inputs=0, n_outputs=1)  # type: ignore[call-arg]

    def test_initial_prev_trigger_is_nan(self) -> None:
        sub = _build_simple_triggered()
        assert np.isnan(sub._prev_trigger_value)

    def test_initial_last_y_is_zeros_after_build(self) -> None:
        # ADR-0058: _last_y は build 後に zeros(n_outputs) で初期化される
        # (build 前は None。Subsystem ベース実装に変更されたため)
        sub = _build_simple_triggered()
        sub._build()
        np.testing.assert_array_equal(sub._last_y, np.zeros(1))

    def test_trigger_modes_constant_lists_three(self) -> None:
        assert set(TRIGGER_MODES) == {"rising", "falling", "either"}

    def test_deprecation_warning_emitted(self) -> None:
        """ADR-0058 §論点 9: 旧 API 呼び出しで DeprecationWarning が出る。"""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            TriggeredSubsystem(id="dep_test")
            dep = [w for w in caught if issubclass(w.category, DeprecationWarning)]
            assert len(dep) >= 1
            assert "TriggeredSubsystem is deprecated" in str(dep[0].message)


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
    """ADR-0058: factory 経由で構築された Subsystem (+内部 Trigger) は、
    JSON save/load 後も内部 Trigger が保持され trigger_type が一致する。"""

    def test_save_load_round_trip_rising(self, tmp_path) -> None:
        from pyflw import Simulator
        from pyflw.subsystems import Subsystem

        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(_build_simple_triggered("rising"))
        path = tmp_path / "trig.flw.json"
        sim.save(path)

        sim2 = Simulator.load(path)
        sub2 = sim2.get_block("trig_sub")
        # ADR-0058: load 後の実体は Subsystem。内部 Trigger block で識別する
        assert isinstance(sub2, Subsystem)
        assert _get_inner_trigger(sub2).trigger_type == "rising"

    def test_save_load_round_trip_either(self, tmp_path) -> None:
        from pyflw import Simulator
        from pyflw.subsystems import Subsystem

        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(_build_simple_triggered("either"))
        path = tmp_path / "trig.flw.json"
        sim.save(path)

        sim2 = Simulator.load(path)
        sub2 = sim2.get_block("trig_sub")
        assert isinstance(sub2, Subsystem)
        assert _get_inner_trigger(sub2).trigger_type == "either"
