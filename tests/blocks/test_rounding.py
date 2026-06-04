"""SPEC-0013 / ADR-0059 (v5.6.0): Rounding の網羅テスト。"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from pyflw import Simulator
from pyflw.blocks import Rounding, Scope, Sine
from pyflw.exceptions import BlockSpecError

_EMPTY_X = np.array([])


def _out(blk: Rounding, u_val: float) -> float:
    y = blk.output(0.0, _EMPTY_X, np.array([u_val]))
    return float(y[0])


class TestRoundingConstruction:
    def test_default_is_round(self) -> None:
        b = Rounding()
        assert b.mode == "round"
        assert b.n_inputs == 1
        assert b.n_outputs == 1
        assert b.direct_feedthrough is True
        assert b.n_states == 0

    def test_all_modes_accepted(self) -> None:
        for m in ("floor", "ceil", "round", "trunc"):
            assert Rounding(mode=m).mode == m

    def test_bad_mode_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="mode must be one of"):
            Rounding(mode="banker")


class TestRoundingModes:
    @pytest.mark.parametrize(
        "mode, u, expected",
        [
            # floor
            ("floor", 2.7, 2.0),
            ("floor", -2.7, -3.0),
            # ceil
            ("ceil", 2.3, 3.0),
            ("ceil", -2.3, -2.0),
            # round (banker's)
            ("round", 2.7, 3.0),
            ("round", -2.7, -3.0),
            ("round", 2.5, 2.0),   # banker's: 2.5 → 2 (even)
            ("round", 3.5, 4.0),   # banker's: 3.5 → 4 (even)
            # trunc
            ("trunc", 2.7, 2.0),
            ("trunc", -2.7, -2.0),
            # integer 入力
            ("round", 5.0, 5.0),
            ("floor", -3.0, -3.0),
        ],
    )
    def test_mode_value(self, mode: str, u: float, expected: float) -> None:
        assert _out(Rounding(mode=mode), u) == pytest.approx(expected)


class TestRoundingEdgeCases:
    @pytest.mark.parametrize("mode", ["floor", "ceil", "round", "trunc"])
    def test_nan_propagates(self, mode: str) -> None:
        assert math.isnan(_out(Rounding(mode=mode), float("nan")))

    @pytest.mark.parametrize("mode", ["floor", "ceil", "round", "trunc"])
    def test_inf_propagates(self, mode: str) -> None:
        assert _out(Rounding(mode=mode), float("inf")) == float("inf")
        assert _out(Rounding(mode=mode), float("-inf")) == float("-inf")

    def test_int_input_handled(self) -> None:
        y = Rounding().output(0.0, _EMPTY_X, np.array([3]))
        assert float(y[0]) == 3.0


class TestRoundingStateless:
    def test_repeated_same_value(self) -> None:
        b = Rounding(mode="floor")
        rs = [_out(b, 2.5) for _ in range(5)]
        assert all(r == rs[0] for r in rs)


class TestRoundingRegistry:
    def test_translation_entry(self) -> None:
        from pyflw.server.registry_translations import _BLOCK_TRANSLATIONS

        e = _BLOCK_TRANSLATIONS["pyflw.blocks.rounding.Rounding"]
        assert e["en"]["display_name"] == "Rounding"
        assert e["ja"]["display_name"] == "丸め"

    def test_metadata_entry(self) -> None:
        from pyflw.server.registry import _BUILTIN_METADATA

        cat, name, icon = _BUILTIN_METADATA["pyflw.blocks.rounding.Rounding"]
        assert cat == "mathops"
        assert name == "Rounding"
        assert icon == "math.rounding"


class TestRoundingInModel:
    def test_sine_through_rounding(self, tmp_path: Path) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Sine(amplitude=2.5, frequency=1.0, id="src"))
        sim.add(Rounding(mode="floor", id="r"))
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("src", "r")
        sim.connect("r", "sc")
        sim.run()
        vals = np.asarray(sim.get_block("sc").values)[:, 0]
        # 全て整数 (floor 結果)
        assert all(v == np.floor(v) for v in vals)

    def test_save_load_round_trip(self, tmp_path: Path) -> None:
        sim1 = Simulator(t_end=0.1, dt=0.01)
        sim1.add(Rounding(mode="ceil", id="r"))
        path = tmp_path / "m.flw.json"
        sim1.save(path)
        sim2 = Simulator.load(path)
        assert sim2.get_block("r").mode == "ceil"
