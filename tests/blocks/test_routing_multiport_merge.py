"""SPEC-0014 / ADR-0059 (v5.7.0): MultiportSwitch + Merge の網羅テスト。"""

from __future__ import annotations

import numpy as np
import pytest

from pyflw import Simulator
from pyflw.blocks import Constant, Merge, MultiportSwitch, Scope
from pyflw.exceptions import BlockEvalError, BlockSpecError

_EMPTY_X = np.array([])


def _out(blk, *us) -> float:
    y = blk.output(0.0, _EMPTY_X, np.array(us, dtype=float))
    return float(y[0])


# ===========================================================================
# MultiportSwitch
# ===========================================================================


class TestMultiportSwitchConstruction:
    def test_defaults(self) -> None:
        b = MultiportSwitch()
        assert b.n_choices == 2
        assert b.index_base == "zero"
        assert b.out_of_range_mode == "clip"
        assert b.n_inputs == 3  # 1 selector + 2 data

    def test_custom(self) -> None:
        b = MultiportSwitch(n_choices=5, index_base="one", out_of_range_mode="error")
        assert b.n_inputs == 6

    def test_bad_n_choices_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="n_choices must be >= 1"):
            MultiportSwitch(n_choices=0)

    def test_bad_n_choices_type_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="must be an int"):
            MultiportSwitch(n_choices=2.5)  # type: ignore[arg-type]

    def test_bad_index_base_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="index_base must be one of"):
            MultiportSwitch(index_base="bogus")

    def test_bad_oor_mode_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="out_of_range_mode must be one of"):
            MultiportSwitch(out_of_range_mode="bogus")


class TestMultiportSwitchEvaluation:
    def test_zero_base_select(self) -> None:
        b = MultiportSwitch(n_choices=3, index_base="zero")
        # selector=0 → u[1]=10, selector=1 → u[2]=20, selector=2 → u[3]=30
        assert _out(b, 0, 10, 20, 30) == 10.0
        assert _out(b, 1, 10, 20, 30) == 20.0
        assert _out(b, 2, 10, 20, 30) == 30.0

    def test_one_base_select(self) -> None:
        b = MultiportSwitch(n_choices=3, index_base="one")
        # selector=1 → u[1]=10, selector=2 → u[2]=20, selector=3 → u[3]=30
        assert _out(b, 1, 10, 20, 30) == 10.0
        assert _out(b, 3, 10, 20, 30) == 30.0

    def test_round_half_to_even(self) -> None:
        b = MultiportSwitch(n_choices=3)
        # 0.6 → round(0.6)=1
        assert _out(b, 0.6, 10, 20, 30) == 20.0
        # 0.4 → round(0.4)=0
        assert _out(b, 0.4, 10, 20, 30) == 10.0

    def test_clip_low(self) -> None:
        b = MultiportSwitch(n_choices=3, out_of_range_mode="clip")
        assert _out(b, -5, 10, 20, 30) == 10.0

    def test_clip_high(self) -> None:
        b = MultiportSwitch(n_choices=3, out_of_range_mode="clip")
        assert _out(b, 99, 10, 20, 30) == 30.0

    def test_error_mode_low(self) -> None:
        b = MultiportSwitch(n_choices=3, out_of_range_mode="error")
        with pytest.raises(BlockEvalError, match="out of range"):
            _out(b, -1, 10, 20, 30)

    def test_error_mode_high(self) -> None:
        b = MultiportSwitch(n_choices=3, out_of_range_mode="error")
        with pytest.raises(BlockEvalError, match="out of range"):
            _out(b, 5, 10, 20, 30)


class TestMultiportSwitchInModel:
    def test_in_simulator(self) -> None:
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(Constant(value=1.0, id="sel"))
        sim.add(Constant(value=100.0, id="d0"))
        sim.add(Constant(value=200.0, id="d1"))
        sim.add(MultiportSwitch(n_choices=2, id="sw"))
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("sel", "sw", dst_idx=0)
        sim.connect("d0", "sw", dst_idx=1)
        sim.connect("d1", "sw", dst_idx=2)
        sim.connect("sw", "sc")
        sim.run()
        vals = np.asarray(sim.get_block("sc").values)[:, 0]
        # selector=1 → d1=200
        assert all(v == 200.0 for v in vals)


# ===========================================================================
# Merge
# ===========================================================================


class TestMergeConstruction:
    def test_defaults(self) -> None:
        b = Merge()
        assert b.n_inputs == 2
        assert b.initial_value == 0.0

    def test_custom(self) -> None:
        b = Merge(n_inputs=4, initial_value=-1.0)
        assert b.n_inputs == 4
        assert b.initial_value == -1.0

    def test_bad_n_inputs_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="n_inputs must be >= 1"):
            Merge(n_inputs=0)

    def test_bad_n_inputs_type_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="must be an int"):
            Merge(n_inputs=True)  # type: ignore[arg-type]


class TestMergeEvaluation:
    def test_first_non_default(self) -> None:
        b = Merge(n_inputs=3, initial_value=0.0)
        assert _out(b, 0.0, 5.0, 7.0) == 5.0  # u[1]=5 is first non-zero

    def test_all_default_returns_default(self) -> None:
        b = Merge(n_inputs=3, initial_value=0.0)
        assert _out(b, 0.0, 0.0, 0.0) == 0.0

    def test_priority_lowest_index_wins(self) -> None:
        b = Merge(n_inputs=3, initial_value=0.0)
        # u[0]=3 (non-default) wins despite u[1]=5, u[2]=7
        assert _out(b, 3.0, 5.0, 7.0) == 3.0

    def test_custom_initial_value(self) -> None:
        b = Merge(n_inputs=3, initial_value=-1.0)
        # u[0]=-1 (matches initial), u[1]=0 (non-default) wins
        assert _out(b, -1.0, 0.0, 5.0) == 0.0

    def test_all_match_custom_default(self) -> None:
        b = Merge(n_inputs=2, initial_value=2.5)
        assert _out(b, 2.5, 2.5) == 2.5


class TestMergeInModel:
    def test_in_simulator(self) -> None:
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(Constant(value=0.0, id="inactive"))
        sim.add(Constant(value=42.0, id="active"))
        sim.add(Merge(n_inputs=2, initial_value=0.0, id="m"))
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("inactive", "m", dst_idx=0)
        sim.connect("active", "m", dst_idx=1)
        sim.connect("m", "sc")
        sim.run()
        vals = np.asarray(sim.get_block("sc").values)[:, 0]
        # inactive=0 (default), active=42 → output 42
        assert all(v == 42.0 for v in vals)


class TestRegistry:
    def test_multiport_switch_registered(self) -> None:
        from pyflw.server.registry import _BUILTIN_METADATA
        from pyflw.server.registry_translations import _BLOCK_TRANSLATIONS

        assert "pyflw.blocks.routing.MultiportSwitch" in _BUILTIN_METADATA
        assert "pyflw.blocks.routing.MultiportSwitch" in _BLOCK_TRANSLATIONS

    def test_merge_registered(self) -> None:
        from pyflw.server.registry import _BUILTIN_METADATA
        from pyflw.server.registry_translations import _BLOCK_TRANSLATIONS

        assert "pyflw.blocks.routing.Merge" in _BUILTIN_METADATA
        assert "pyflw.blocks.routing.Merge" in _BLOCK_TRANSLATIONS
