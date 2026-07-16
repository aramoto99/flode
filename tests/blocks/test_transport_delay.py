"""SPEC-0015 / ADR-0065 (v5.8.0): TransportDelay の網羅テスト。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from flode import Simulator
from flode.blocks import Scope, Sine, Step, TransportDelay
from flode.exceptions import BlockSpecError


class TestConstruction:
    def test_defaults_via_factory(self) -> None:
        td = TransportDelay(delay_time=1.0, sample_time=0.1)
        assert td.delay_time == 1.0
        assert td.initial_output == 0.0
        # N = ceil(1.0/0.1) + 1 = 11 (Simulator order 補正のため +1)
        assert td.n_states == 11
        assert td.direct_feedthrough is False

    def test_non_integer_ratio_ceil(self) -> None:
        # delay=0.25, sample=0.1 → ceil(2.5) + 1 = 4
        td = TransportDelay(delay_time=0.25, sample_time=0.1)
        assert td.n_states == 4

    def test_min_n_states_is_two(self) -> None:
        # delay < sample → ceil=1、N=2 (最小、1 サンプル delay)
        td = TransportDelay(delay_time=0.05, sample_time=0.1)
        assert td.n_states == 2

    def test_delay_zero_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="delay_time must be > 0"):
            TransportDelay(delay_time=0.0, sample_time=0.1)

    def test_delay_negative_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="delay_time must be > 0"):
            TransportDelay(delay_time=-1.0, sample_time=0.1)

    def test_sample_time_zero_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="sample_time must be > 0"):
            TransportDelay(delay_time=1.0, sample_time=0.0)

    def test_initial_output_set(self) -> None:
        td = TransportDelay(delay_time=0.5, sample_time=0.1, initial_output=3.5)
        assert td.initial_output == 3.5
        assert np.all(td.x0 == 3.5)


class TestDelay:
    def test_step_input_delayed_output(self) -> None:
        """step 0→1 が delay_time 後に出力に現れる。"""
        sim = Simulator(t_end=2.0, dt=0.1)
        sim.add(Step(step_time=0.0, initial_value=0.0, final_value=1.0, id="src"))
        sim.add(TransportDelay(delay_time=0.5, sample_time=0.1, id="td"))
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("src", "td")
        sim.connect("td", "sc")
        sim.run()
        vals = np.asarray(sim.get_block("sc").values)[:, 0]
        # delay=0.5、sample=0.1 → 5 サンプル遅延
        # vals[0..4] = 0 (initial_output)、vals[5] = 1 (delay 経過後)
        assert vals[0] == 0.0
        assert vals[4] == 0.0
        assert vals[5] == 1.0

    def test_initial_output_value(self) -> None:
        sim = Simulator(t_end=0.5, dt=0.1)
        sim.add(Step(step_time=10.0, initial_value=99.0, final_value=99.0, id="src"))
        sim.add(
            TransportDelay(
                delay_time=0.3,
                sample_time=0.1,
                initial_output=7.5,
                id="td",
            )
        )
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("src", "td")
        sim.connect("td", "sc")
        sim.run()
        vals = np.asarray(sim.get_block("sc").values)[:, 0]
        # N=4 buffer、delay=3 sample。最初の 3 サンプル (vals[0..2]) は
        # initial_output=7.5、vals[3] 以降は入力 99 が出力される
        assert vals[0] == 7.5
        assert vals[1] == 7.5
        assert vals[2] == 7.5
        assert vals[3] == 99.0

    def test_n_states_two_acts_as_unit_delay(self) -> None:
        """delay < sample_time のとき N=2 (最小) で 1 サンプル遅延。"""
        sim = Simulator(t_end=0.3, dt=0.1)
        sim.add(Step(step_time=0.0, initial_value=0.0, final_value=1.0, id="src"))
        sim.add(TransportDelay(delay_time=0.05, sample_time=0.1, id="td"))
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("src", "td")
        sim.connect("td", "sc")
        sim.run()
        vals = np.asarray(sim.get_block("sc").values)[:, 0]
        # N=2 → 1 サンプル遅延
        assert vals[0] == 0.0
        assert vals[1] == 1.0


class TestPersistence:
    def test_round_trip(self, tmp_path: Path) -> None:
        sim1 = Simulator(t_end=0.5, dt=0.1)
        sim1.add(
            TransportDelay(
                delay_time=0.3,
                sample_time=0.1,
                initial_output=2.0,
                id="td",
            )
        )
        path = tmp_path / "m.flw.json"
        sim1.save(path)
        sim2 = Simulator.load(path)
        loaded = sim2.get_block("td")
        assert isinstance(loaded, TransportDelay)
        assert loaded.delay_time == 0.3
        assert loaded.initial_output == 2.0


class TestRegistry:
    def test_registered(self) -> None:
        from flode.server.registry import _BUILTIN_METADATA
        from flode.server.registry_translations import _BLOCK_TRANSLATIONS

        assert "flode.blocks.transport_delay.TransportDelay" in _BUILTIN_METADATA
        cat, _, _ = _BUILTIN_METADATA["flode.blocks.transport_delay.TransportDelay"]
        assert cat == "continuous"
        assert (
            _BLOCK_TRANSLATIONS["flode.blocks.transport_delay.TransportDelay"]["ja"]["display_name"]
            == "むだ時間"
        )


class TestInModel:
    def test_sine_through_transport_delay(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Sine(amplitude=1.0, frequency=1.0, id="src"))
        sim.add(TransportDelay(delay_time=0.1, sample_time=0.01, id="td"))
        sim.add(Scope(n_inputs=2, id="sc"))
        sim.connect("src", "sc", dst_idx=0)
        sim.connect("src", "td")
        sim.connect("td", "sc", dst_idx=1)
        sim.run()
        vals = np.asarray(sim.get_block("sc").values)
        sine_in = vals[:, 0]
        sine_out = vals[:, 1]
        # delay=0.1 s = 10 sample → sine_out[delay_samples] ≈ sine_in[0]
        # 浮動小数誤差を許容 (TransportDelay の sample 化丸めも含む)
        delay_samples = 10
        diff = abs(sine_out[delay_samples] - sine_in[0])
        # 数値誤差以下
        assert diff < 1e-9
