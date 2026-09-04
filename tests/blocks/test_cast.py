"""SPEC-0026 / ADR-0076: Cast (値の意味論の型変換) の網羅テスト。"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from flode import Simulator
from flode.blocks import Cast, Rounding, Scope, Sine
from flode.blocks.cast import OUTPUT_TYPES, apply_value_semantics
from flode.exceptions import BlockSpecError

_EMPTY_X = np.array([])


def _out(blk: Cast, u_val: float) -> float:
    y = blk.output(0.0, _EMPTY_X, np.array([u_val]))
    return float(y[0])


class TestCastConstruction:
    def test_default_is_float_identity(self) -> None:
        """受入基準 1 (§確定事項 2): 既定は "float" = 恒等。"""
        b = Cast()
        assert b.output_type == "float"
        assert _out(b, 2.7) == 2.7  # 置いただけでは何も変換しない

    def test_structure(self) -> None:
        b = Cast()
        assert b.n_inputs == 1
        assert b.n_outputs == 1
        assert b.direct_feedthrough is True
        assert b.n_states == 0

    def test_all_types_accepted(self) -> None:
        for ot in OUTPUT_TYPES:
            assert Cast(output_type=ot).output_type == ot

    def test_bad_type_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="output_type must be one of"):
            Cast(output_type="int8")


class TestCastFloat:
    @pytest.mark.parametrize("u", [2.7, -2.5, 0.0, 1e-300, 1e300])
    def test_identity(self, u: float) -> None:
        assert _out(Cast(output_type="float"), u) == u


class TestCastInt:
    @pytest.mark.parametrize(
        "u, expected",
        [
            (2.7, 3.0),
            (2.5, 2.0),  # banker's: 最近接偶数
            (3.5, 4.0),
            (-2.5, -2.0),
            (5.0, 5.0),  # 整数入力は不変
            (1e300, 1e300),  # 固定幅を持たない帰結 (overflow しない)
        ],
    )
    def test_round_half_even(self, u: float, expected: float) -> None:
        assert _out(Cast(output_type="int"), u) == pytest.approx(expected)

    def test_matches_rounding_round_mode(self) -> None:
        """受入基準 4: Cast(int) ≡ Rounding(mode="round") (棲み分けの根拠)。"""
        r = Rounding(mode="round")
        c = Cast(output_type="int")
        for u in (2.5, 3.5, -2.5, 2.7, -2.7, 0.0, 100.49):
            assert _out(c, u) == float(r.output(0.0, _EMPTY_X, np.array([u]))[0])


class TestCastBool:
    @pytest.mark.parametrize(
        "u, expected",
        [
            (3.2, 1.0),
            (-3.2, 1.0),
            (0.0, 0.0),
            (-0.0, 0.0),
            (1e-300, 1.0),  # 閾値は厳密に != 0
            (1e300, 1.0),
        ],
    )
    def test_zero_threshold(self, u: float, expected: float) -> None:
        assert _out(Cast(output_type="bool"), u) == expected


class TestCastEdgeCases:
    def test_nan_to_bool_is_one(self) -> None:
        """受入基準 5 (§確定事項 3): nan != 0 は真 → 1.0。例外規則を作らない。"""
        assert _out(Cast(output_type="bool"), float("nan")) == 1.0

    def test_nan_propagates_for_float_and_int(self) -> None:
        assert math.isnan(_out(Cast(output_type="float"), float("nan")))
        assert math.isnan(_out(Cast(output_type="int"), float("nan")))

    @pytest.mark.parametrize("ot", ["float", "int"])
    def test_inf_propagates(self, ot: str) -> None:
        assert _out(Cast(output_type=ot), float("inf")) == float("inf")
        assert _out(Cast(output_type=ot), float("-inf")) == float("-inf")

    def test_inf_to_bool_is_one(self) -> None:
        assert _out(Cast(output_type="bool"), float("inf")) == 1.0
        assert _out(Cast(output_type="bool"), float("-inf")) == 1.0

    def test_int_input_handled(self) -> None:
        y = Cast(output_type="bool").output(0.0, _EMPTY_X, np.array([3]))
        assert float(y[0]) == 1.0


class TestCastStateless:
    def test_repeated_same_value(self) -> None:
        b = Cast(output_type="int")
        rs = [_out(b, 2.5) for _ in range(5)]
        assert all(r == rs[0] for r in rs)


class TestCastRegistry:
    def test_translation_entry(self) -> None:
        from flode.server.registry_translations import _BLOCK_TRANSLATIONS

        e = _BLOCK_TRANSLATIONS["flode.blocks.cast.Cast"]
        assert e["en"]["display_name"] == "Cast"
        assert e["ja"]["display_name"] == "型変換"

    def test_metadata_entry(self) -> None:
        from flode.server.registry import _BUILTIN_METADATA

        cat, name, icon = _BUILTIN_METADATA["flode.blocks.cast.Cast"]
        assert cat == "mathops"
        assert name == "Cast"
        assert icon == "math.cast"


class TestCastInModel:
    def test_sine_through_bool_cast(self, tmp_path: Path) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Sine(amplitude=2.5, frequency=1.0, id="src"))
        sim.add(Cast(output_type="bool", id="c"))
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("src", "c")
        sim.connect("c", "sc")
        sim.run()
        vals = np.asarray(sim.get_block("sc").values)[:, 0]
        assert set(np.unique(vals)) <= {0.0, 1.0}

    def test_save_load_round_trip(self, tmp_path: Path) -> None:
        sim1 = Simulator(t_end=0.1, dt=0.01)
        sim1.add(Cast(output_type="bool", id="c"))
        path = tmp_path / "m.flw.json"
        sim1.save(path)
        sim2 = Simulator.load(path)
        assert sim2.get_block("c").output_type == "bool"


class TestApplyValueSemantics:
    def test_shared_function_rules(self) -> None:
        assert apply_value_semantics(2.5, "int") == 2.0
        assert apply_value_semantics(-3.2, "bool") == 1.0
        assert apply_value_semantics(1.5, "float") == 1.5
