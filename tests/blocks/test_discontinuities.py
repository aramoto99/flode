"""SPEC-0012 / ADR-0059 (v5.5.0): RateLimiter / Relay の網羅テスト。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from flode import Simulator
from flode.blocks import RateLimiter, Relay, Scope, Sine, Step
from flode.core.persistence import CURRENT_SCHEMA_VERSION
from flode.exceptions import BlockSpecError, ModelLoadError

_EMPTY_X = np.array([0.0])


def _samples(sim: Simulator, block_id: str = "sc") -> np.ndarray:
    return np.asarray(sim.get_block(block_id).values)[:, 0]


# ===========================================================================
# RateLimiter: Construction & validation
# ===========================================================================


class TestRateLimiterConstruction:
    def test_defaults(self) -> None:
        rl = RateLimiter(sample_time=0.1)
        assert rl.rising_slew_rate == 1.0
        assert rl.falling_slew_rate == -1.0
        assert rl.n_inputs == 1
        assert rl.n_outputs == 1
        assert rl.n_states == 1
        assert rl.direct_feedthrough is True
        assert rl._params["x0"] == 0.0

    def test_custom_params(self) -> None:
        rl = RateLimiter(
            sample_time=0.01,
            rising_slew_rate=100.0,
            falling_slew_rate=-50.0,
            x0=2.5,
        )
        assert rl.rising_slew_rate == 100.0
        assert rl.falling_slew_rate == -50.0
        assert rl._params["x0"] == 2.5
        assert rl.x0[0] == 2.5

    def test_rising_zero_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="rising_slew_rate must be > 0"):
            RateLimiter(sample_time=0.1, rising_slew_rate=0.0)

    def test_rising_negative_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="rising_slew_rate must be > 0"):
            RateLimiter(sample_time=0.1, rising_slew_rate=-1.0)

    def test_falling_zero_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="falling_slew_rate must be < 0"):
            RateLimiter(sample_time=0.1, falling_slew_rate=0.0)

    def test_falling_positive_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="falling_slew_rate must be < 0"):
            RateLimiter(sample_time=0.1, falling_slew_rate=1.0)

    def test_sample_time_zero_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="sample_time must be > 0"):
            RateLimiter(sample_time=0.0)

    def test_sample_time_bool_raises(self) -> None:
        """bool は int 派生だが、sample_time として受け取らない (型の意図と乖離)。"""
        with pytest.raises(BlockSpecError, match="sample_time must be a number"):
            RateLimiter(sample_time=True)  # type: ignore[arg-type]


# ===========================================================================
# RateLimiter: Evaluation
# ===========================================================================


class TestRateLimiterEvaluation:
    def test_linear_ramp_to_step(self) -> None:
        """step 0→1、rising=1, sample=0.1 で線形 ramp。"""
        sim = Simulator(t_end=1.5, dt=0.1)
        sim.add(Step(step_time=0.0, initial_value=0.0, final_value=1.0, id="src"))
        sim.add(
            RateLimiter(
                sample_time=0.1,
                rising_slew_rate=1.0,
                falling_slew_rate=-1.0,
                id="rl",
            )
        )
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("src", "rl")
        sim.connect("rl", "sc")
        sim.run()
        vals = _samples(sim)
        # vals[0]: t=0、t=0 で update により 0+0.1*1=0.1 (= rising slope = 1.0 * 0.1)
        assert vals[0] == pytest.approx(0.1)
        # 線形 ramp の途中
        assert vals[1] == pytest.approx(0.2)
        assert vals[5] == pytest.approx(0.6)
        # t=1.0 で 1.0 到達 (10 サンプルで)
        assert vals[9] == pytest.approx(1.0)
        # その後は clip で 1.0 維持
        assert vals[-1] == pytest.approx(1.0)

    def test_asymmetric_rising_falling(self) -> None:
        """rising=2.0, falling=-0.5 で非対称応答。"""
        sim = Simulator(t_end=2.0, dt=0.1)
        sim.add(Step(step_time=0.5, initial_value=1.0, final_value=0.0, id="src"))
        sim.add(
            RateLimiter(
                sample_time=0.1,
                rising_slew_rate=2.0,
                falling_slew_rate=-0.5,
                x0=0.0,
                id="rl",
            )
        )
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("src", "rl")
        sim.connect("rl", "sc")
        sim.run()
        vals = _samples(sim)
        # t=0..0.5: rising 2.0 で 0→1 へ (0.5s で 0+5*0.2=1.0、つまり 5 サンプルで到達)
        assert vals[4] == pytest.approx(1.0)
        # t=0.5 以降: falling -0.5 で 1→0 へ
        # t=0.6 で 0.95、t=1.5 で 0.5
        assert vals[5] < 1.0
        # t=2.5 までに 0 に到達するはずだが t_end=2.0 で打ち切り → 0.25 付近
        assert vals[-1] > 0.0

    def test_zero_input_change_preserves_state(self) -> None:
        """入力 = 現状態 のとき出力変化なし。"""
        sim = Simulator(t_end=0.5, dt=0.1)
        sim.add(Step(step_time=10.0, initial_value=2.0, final_value=99.0, id="src"))
        sim.add(RateLimiter(sample_time=0.1, x0=2.0, id="rl"))
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("src", "rl")
        sim.connect("rl", "sc")
        sim.run()
        vals = _samples(sim)
        # 入力=2.0、x0=2.0 → delta=0、state 維持
        assert all(v == pytest.approx(2.0) for v in vals)

    def test_initial_value_x0(self) -> None:
        """x0=5.0 で初期出力が 5.0、t=0 では入力 0 から 1 サンプル下降。"""
        sim = Simulator(t_end=0.2, dt=0.1)
        sim.add(Step(step_time=10.0, initial_value=0.0, final_value=99.0, id="src"))
        sim.add(
            RateLimiter(
                sample_time=0.1,
                rising_slew_rate=1.0,
                falling_slew_rate=-1.0,
                x0=5.0,
                id="rl",
            )
        )
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("src", "rl")
        sim.connect("rl", "sc")
        sim.run()
        vals = _samples(sim)
        # t=0 で update: delta = 0 - 5 = -5、clip(-5, -0.1, 0.1) = -0.1
        # state new = 5 + (-0.1) = 4.9
        assert vals[0] == pytest.approx(4.9)
        # t=0.1 で update: 4.9 → 4.8
        assert vals[1] == pytest.approx(4.8)

    def test_update_without_resolved_sample_time_raises(self) -> None:
        """Simulator なしで update() 直呼びすると BlockSpecError。"""
        rl = RateLimiter(sample_time=0.1)
        with pytest.raises(BlockSpecError, match="sample_time has not been resolved"):
            rl.update(0.0, np.array([0.0]), np.array([1.0]))


# ===========================================================================
# Relay: Construction & validation
# ===========================================================================


class TestRelayConstruction:
    def test_defaults(self) -> None:
        r = Relay(sample_time=0.1)
        assert r.switch_on_point == 0.5
        assert r.switch_off_point == -0.5
        assert r.output_on == 1.0
        assert r.output_off == 0.0
        assert r.x0_state == "off"
        assert r.x0[0] == 0.0

    def test_custom_x0_state_on(self) -> None:
        r = Relay(sample_time=0.1, x0_state="on")
        assert r.x0[0] == 1.0

    def test_bad_x0_state_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="x0_state must be one of"):
            Relay(sample_time=0.1, x0_state="bogus")

    def test_off_ge_on_point_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="must be < switch_on_point"):
            Relay(sample_time=0.1, switch_on_point=0.5, switch_off_point=0.5)

    def test_off_greater_than_on_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="must be < switch_on_point"):
            Relay(sample_time=0.1, switch_on_point=-0.5, switch_off_point=0.5)

    def test_sample_time_zero_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="sample_time must be > 0"):
            Relay(sample_time=0.0)

    def test_sample_time_bool_raises(self) -> None:
        """code-reviewer MUST: RateLimiter と対称な bool ガード。bool は int
        派生だが sample_time として受け取らない。"""
        with pytest.raises(BlockSpecError, match="sample_time must be a number"):
            Relay(sample_time=True)  # type: ignore[arg-type]


# ===========================================================================
# Relay: Hysteresis behavior
# ===========================================================================


class TestRelayHysteresis:
    def _make_sim(self, **rl_kwargs) -> Simulator:
        sim = Simulator(t_end=2.0, dt=0.05)
        sim.add(Sine(amplitude=1.0, frequency=1.0, id="src"))
        sim.add(Relay(sample_time=0.05, id="re", **rl_kwargs))
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("src", "re")
        sim.connect("re", "sc")
        return sim

    def test_initial_off_stays_off_below_on_point(self) -> None:
        """x0=off、入力 0.3 (< 0.5) → state OFF 維持。"""
        sim = Simulator(t_end=0.5, dt=0.1)
        sim.add(Step(step_time=10.0, initial_value=0.3, final_value=99.0, id="src"))
        sim.add(Relay(sample_time=0.1, x0_state="off", id="re"))
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("src", "re")
        sim.connect("re", "sc")
        sim.run()
        vals = _samples(sim)
        assert all(v == 0.0 for v in vals)  # output_off = 0.0

    def test_transition_off_to_on(self) -> None:
        """x0=off、入力が switch_on_point を超えたら ON 遷移。"""
        sim = Simulator(t_end=0.3, dt=0.1)
        sim.add(Step(step_time=10.0, initial_value=0.6, final_value=99.0, id="src"))
        sim.add(Relay(sample_time=0.1, x0_state="off", id="re"))
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("src", "re")
        sim.connect("re", "sc")
        sim.run()
        vals = _samples(sim)
        # t=0 で update により ON 遷移、output = 1.0
        assert all(v == 1.0 for v in vals)

    def test_hysteresis_no_transition_in_deadband(self) -> None:
        """ON 状態で入力が switch_off_point より大きい間は ON 維持 (deadband)。"""
        # x0=on、入力 0.0 (deadband 内: -0.5 < 0.0 < 0.5)
        sim = Simulator(t_end=0.3, dt=0.1)
        sim.add(Step(step_time=10.0, initial_value=0.0, final_value=99.0, id="src"))
        sim.add(
            Relay(
                sample_time=0.1,
                x0_state="on",
                switch_on_point=0.5,
                switch_off_point=-0.5,
                id="re",
            )
        )
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("src", "re")
        sim.connect("re", "sc")
        sim.run()
        vals = _samples(sim)
        # ON 維持 (output = 1.0)
        assert all(v == 1.0 for v in vals)

    def test_transition_on_to_off(self) -> None:
        """ON 状態で入力 <= switch_off_point になったら OFF 遷移。"""
        sim = Simulator(t_end=0.3, dt=0.1)
        sim.add(Step(step_time=10.0, initial_value=-0.6, final_value=99.0, id="src"))
        sim.add(Relay(sample_time=0.1, x0_state="on", id="re"))
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("src", "re")
        sim.connect("re", "sc")
        sim.run()
        vals = _samples(sim)
        # 全て OFF (output = 0.0)
        assert all(v == 0.0 for v in vals)

    def test_full_hysteresis_loop_with_sine(self) -> None:
        """Sine 入力で完全な hysteresis ループ動作。"""
        sim = self._make_sim()
        sim.run()
        vals = _samples(sim)
        # output_on=1.0 / output_off=0.0 の2値のみ取る
        assert set(np.unique(vals).tolist()) <= {0.0, 1.0}
        # 遷移回数: sine 1Hz で 2 秒、上下それぞれ閾値を 2 回ずつ通過 → 約 4 遷移
        transitions = int(np.sum(np.abs(np.diff(vals)) > 0.5))
        assert 2 <= transitions <= 6

    def test_custom_output_values(self) -> None:
        """output_on / output_off にカスタム値を指定。"""
        sim = Simulator(t_end=0.3, dt=0.1)
        sim.add(Step(step_time=10.0, initial_value=1.0, final_value=99.0, id="src"))
        sim.add(Relay(sample_time=0.1, output_on=42.0, output_off=-7.0, id="re"))
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("src", "re")
        sim.connect("re", "sc")
        sim.run()
        vals = _samples(sim)
        assert all(v == 42.0 for v in vals)


# ===========================================================================
# Sample-time hold & determinism
# ===========================================================================


class TestSampleTimeHold:
    def test_relay_state_hold_at_multirate(self) -> None:
        """sample_time > dt_base のとき、中間ステップでは Scope が前値を見続ける。"""
        sim = Simulator(t_end=1.0, dt=0.1)
        sim.add(Step(step_time=10.0, initial_value=1.0, final_value=99.0, id="src"))
        sim.add(Relay(sample_time=0.2, x0_state="off", id="re"))
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("src", "re")
        sim.connect("re", "sc")
        sim.run()
        vals = _samples(sim)
        # step_ratio=2 で偶数ステップだけ fire。すべて ON だが state は保持される。
        assert all(v == 1.0 for v in vals)

    def test_output_is_slew_limited_current_input(self) -> None:
        """output() は現入力から slew 制限後の値を返す (ADR-0078 Amendment、update と同じ決定値)。

        サンプル間のホールドは Simulator の出力キャッシュが担う (output は発火時のみ呼ばれる)。
        sample_time 未解決時は state をそのまま返す (fail-soft)。
        """
        rl = RateLimiter(sample_time=0.1, x0=2.5)
        assert rl.output(0.0, np.array([2.5]), np.array([99.0]))[0] == 2.5  # 未解決: hold
        rl._resolved_sample_time = 0.1
        assert rl.output(0.0, np.array([2.5]), np.array([99.0]))[0] == pytest.approx(2.6)
        assert rl.output(0.0, np.array([2.5]), np.array([2.55]))[0] == pytest.approx(2.55)
        np.testing.assert_allclose(
            rl.output(0.0, np.array([2.5]), np.array([99.0])),
            rl.update(0.0, np.array([2.5]), np.array([99.0])),
        )


class TestDeterminism:
    def test_two_runs_bit_identical(self) -> None:
        """同一 Simulator + 2 回 run で bit-identical (reset hook 動作)。"""
        sim = Simulator(t_end=2.0, dt=0.05)
        sim.add(Sine(amplitude=1.0, frequency=1.0, id="src"))
        sim.add(Relay(sample_time=0.05, x0_state="off", id="re"))
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("src", "re")
        sim.connect("re", "sc")
        sim.run()
        y1 = _samples(sim).copy()
        sim.run()
        y2 = _samples(sim).copy()
        np.testing.assert_array_equal(y1, y2)

    def test_relay_reset_restores_initial_state(self) -> None:
        """Relay.reset() を直呼びすると x0 が x0_state から再構築される。"""
        r = Relay(sample_time=0.1, x0_state="on")
        # x0_state を on から手で off に書き換えても、reset() で再初期化
        assert r.x0[0] == 1.0
        r.x0 = np.array([0.0])  # 手で書き換え (=run() 中の state 変化を模擬)
        r.reset()
        assert r.x0[0] == 1.0  # 再構築

    def test_relay_reset_with_off(self) -> None:
        r = Relay(sample_time=0.1, x0_state="off")
        r.x0 = np.array([1.0])
        r.reset()
        assert r.x0[0] == 0.0


# ===========================================================================
# Persistence (save / load round-trip)
# ===========================================================================


class TestPersistence:
    def test_rate_limiter_round_trip(self, tmp_path: Path) -> None:
        sim1 = Simulator(t_end=0.5, dt=0.05)
        sim1.add(
            RateLimiter(
                sample_time=0.05,
                rising_slew_rate=10.0,
                falling_slew_rate=-5.0,
                x0=1.5,
                id="rl",
            )
        )
        path = tmp_path / "model.flw.json"
        sim1.save(path)
        sim2 = Simulator.load(path)
        loaded = sim2.get_block("rl")
        assert isinstance(loaded, RateLimiter)
        assert loaded.rising_slew_rate == 10.0
        assert loaded.falling_slew_rate == -5.0
        assert loaded._params["x0"] == 1.5

    def test_relay_round_trip_with_x0_state(self, tmp_path: Path) -> None:
        sim1 = Simulator(t_end=0.5, dt=0.05)
        sim1.add(
            Relay(
                sample_time=0.05,
                switch_on_point=0.7,
                switch_off_point=-0.3,
                output_on=5.0,
                output_off=-5.0,
                x0_state="on",
                id="re",
            )
        )
        path = tmp_path / "model.flw.json"
        sim1.save(path)
        sim2 = Simulator.load(path)
        loaded = sim2.get_block("re")
        assert isinstance(loaded, Relay)
        assert loaded.switch_on_point == 0.7
        assert loaded.switch_off_point == -0.3
        assert loaded.output_on == 5.0
        assert loaded.output_off == -5.0
        assert loaded.x0_state == "on"
        assert loaded.x0[0] == 1.0

    def test_invalid_rate_limiter_load_raises(self, tmp_path: Path) -> None:
        bad = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "metadata": {},
            "simulator": {
                "t_end": 1.0,
                "dt": 0.01,
                "solver": "RK45",
                "rtol": 1e-6,
                "atol": 1e-9,
                "dt_base": 0.01,
            },
            "blocks": [
                {
                    "id": "bad",
                    "type": "flode.blocks.discontinuities.RateLimiter",
                    "params": {
                        "sample_time": 0.1,
                        "rising_slew_rate": -1.0,  # invalid
                        "falling_slew_rate": -1.0,
                        "x0": 0.0,
                    },
                }
            ],
            "connections": [],
        }
        path = tmp_path / "bad.flw.json"
        path.write_text(json.dumps(bad))
        with pytest.raises(ModelLoadError, match="Cannot instantiate block"):
            Simulator.load(path)

    def test_invalid_relay_x0_state_load_raises(self, tmp_path: Path) -> None:
        bad = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "metadata": {},
            "simulator": {
                "t_end": 1.0,
                "dt": 0.01,
                "solver": "RK45",
                "rtol": 1e-6,
                "atol": 1e-9,
                "dt_base": 0.01,
            },
            "blocks": [
                {
                    "id": "bad",
                    "type": "flode.blocks.discontinuities.Relay",
                    "params": {
                        "sample_time": 0.1,
                        "switch_on_point": 0.5,
                        "switch_off_point": -0.5,
                        "output_on": 1.0,
                        "output_off": 0.0,
                        "x0_state": "bogus",
                    },
                }
            ],
            "connections": [],
        }
        path = tmp_path / "bad.flw.json"
        path.write_text(json.dumps(bad))
        with pytest.raises(ModelLoadError, match="Cannot instantiate block"):
            Simulator.load(path)


# ===========================================================================
# Registry & i18n
# ===========================================================================


class TestRegistry:
    def test_rate_limiter_translation_entry(self) -> None:
        from flode.server.registry_translations import _BLOCK_TRANSLATIONS

        entry = _BLOCK_TRANSLATIONS["flode.blocks.discontinuities.RateLimiter"]
        assert entry["en"]["display_name"] == "Rate Limiter"
        assert entry["ja"]["display_name"] == "変化率リミッタ"

    def test_relay_translation_entry(self) -> None:
        from flode.server.registry_translations import _BLOCK_TRANSLATIONS

        entry = _BLOCK_TRANSLATIONS["flode.blocks.discontinuities.Relay"]
        assert entry["en"]["display_name"] == "Relay"
        assert entry["ja"]["display_name"] == "リレー"

    def test_rate_limiter_registry_metadata(self) -> None:
        from flode.server.registry import _BUILTIN_METADATA

        cat, name, icon = _BUILTIN_METADATA["flode.blocks.discontinuities.RateLimiter"]
        assert cat == "discontinuities"
        assert name == "Rate Limiter"
        assert icon == "discontinuities.ratelimiter"

    def test_relay_registry_metadata(self) -> None:
        from flode.server.registry import _BUILTIN_METADATA

        cat, name, icon = _BUILTIN_METADATA["flode.blocks.discontinuities.Relay"]
        assert cat == "discontinuities"
        assert name == "Relay"
        assert icon == "discontinuities.relay"

    def test_default_factory_args_provide_sample_time(self) -> None:
        from flode.server.registry import _BUILTIN_DEFAULT_ARGS

        for type_path in (
            "flode.blocks.discontinuities.RateLimiter",
            "flode.blocks.discontinuities.Relay",
        ):
            args = _BUILTIN_DEFAULT_ARGS[type_path]
            assert args["sample_time"] > 0


# ===========================================================================
# Integration in Simulator
# ===========================================================================


class TestInModel:
    def test_sine_through_rate_limiter_to_scope(self, tmp_path: Path) -> None:
        """Sine → RateLimiter → Scope モデル + save/load round-trip。"""

        def build() -> Simulator:
            sim = Simulator(t_end=1.0, dt=0.01)
            sim.add(Sine(amplitude=1.0, frequency=1.0, id="src"))
            sim.add(
                RateLimiter(
                    sample_time=0.01,
                    rising_slew_rate=2.0,
                    falling_slew_rate=-2.0,
                    id="rl",
                )
            )
            sim.add(Scope(n_inputs=1, id="sc"))
            sim.connect("src", "rl")
            sim.connect("rl", "sc")
            return sim

        sim1 = build()
        sim1.run()
        y1 = _samples(sim1).copy()

        path = tmp_path / "model.flw.json"
        sim1.save(path)
        sim2 = Simulator.load(path)
        sim2.run()
        y2 = _samples(sim2)
        np.testing.assert_array_equal(y1, y2)
        # slew rate 制限により |output| < 1 (Sine 振幅)
        assert y1.max() <= 1.0
        assert y1.min() >= -1.0

    def test_sine_through_relay_produces_two_levels(self) -> None:
        """Sine 入力 → Relay → 2 値出力のみ。"""
        sim = Simulator(t_end=2.0, dt=0.01)
        sim.add(Sine(amplitude=1.0, frequency=1.0, id="src"))
        sim.add(
            Relay(
                sample_time=0.01,
                switch_on_point=0.5,
                switch_off_point=-0.5,
                id="re",
            )
        )
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("src", "re")
        sim.connect("re", "sc")
        sim.run()
        y = _samples(sim)
        assert set(np.unique(y).tolist()) <= {0.0, 1.0}
