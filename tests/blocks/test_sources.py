"""``flode.blocks.sources`` のテスト (SPEC-0026: Constant.output_type から新設)。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from flode import Simulator
from flode.blocks import Cast, Constant
from flode.exceptions import BlockSpecError

_EMPTY = np.array([])


def _out(blk: Constant) -> float:
    return float(blk.output(0.0, _EMPTY, _EMPTY)[0])


class TestConstantOutputType:
    def test_default_is_float_backward_compatible(self) -> None:
        """受入基準 2: 既定 "float" は v0.52.1 と bit-identical。"""
        assert _out(Constant(value=1.5)) == 1.5
        assert _out(Constant()) == 1.0

    def test_int_rounds_half_even(self) -> None:
        assert _out(Constant(value=1.5, output_type="int")) == 2.0
        assert _out(Constant(value=2.5, output_type="int")) == 2.0  # 偶数丸め

    def test_bool_normalizes(self) -> None:
        assert _out(Constant(value=-3.2, output_type="bool")) == 1.0
        assert _out(Constant(value=0.4, output_type="bool")) == 1.0
        assert _out(Constant(value=0.0, output_type="bool")) == 0.0

    def test_raw_value_is_preserved(self) -> None:
        """§確定事項 7: 生値保持 (int にしても _params の value は 1.5 のまま = 可逆)。"""
        c = Constant(value=1.5, output_type="int")
        assert c.value == 1.5
        assert c._params["value"] == 1.5
        assert c._params["output_type"] == "int"

    def test_bad_type_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="output_type must be one of"):
            Constant(value=1.0, output_type="double")

    def test_legacy_params_without_output_type(self) -> None:
        """受入基準 3: output_type なしの旧 dict からの復元は挙動不変。"""
        c = Constant(**{"value": 2.0})
        assert c.output_type == "float"
        assert _out(c) == 2.0

    def test_save_load_round_trip(self, tmp_path: Path) -> None:
        sim1 = Simulator(t_end=0.1, dt=0.01)
        sim1.add(Constant(value=0.4, output_type="bool", id="k"))
        path = tmp_path / "m.flw.json"
        sim1.save(path)
        sim2 = Simulator.load(path)
        k = sim2.get_block("k")
        assert k.output_type == "bool"
        assert k.value == 0.4
        assert _out(k) == 1.0

    def test_matches_cast_rules(self) -> None:
        """受入基準 6: Constant と Cast の変換規則が同一 (共有関数経由)。"""
        for v in (2.5, 3.5, -2.5, 0.0, -0.0, 1e-300):
            for ot in ("float", "int", "bool"):
                const_out = _out(Constant(value=v, output_type=ot))
                cast_out = float(Cast(output_type=ot).output(0.0, _EMPTY, np.array([v]))[0])
                assert const_out == cast_out or (np.isnan(const_out) and np.isnan(cast_out))
