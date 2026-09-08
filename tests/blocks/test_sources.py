"""``flode.blocks.sources`` のテスト (Constant の dtype param、SPEC-0028)。

v0.56.0 で ``output_type`` (値の意味論、旧 SPEC-0026) は撤去された。
Constant は ``dtype`` のみを持ち、既定 ``"auto"`` = 未宣言 = ただの float64 定数。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from flode import Simulator
from flode.blocks import Constant
from flode.exceptions import BlockSpecError

_EMPTY = np.array([])


def _out_array(blk: Constant) -> np.ndarray:
    return blk.output(0.0, _EMPTY, _EMPTY)


def _out(blk: Constant) -> float:
    return float(_out_array(blk)[0])


class TestConstantDtype:
    def test_default_is_auto_plain_float64(self) -> None:
        """既定 "auto" = 宣言なし = float64 定数 (SM-B を起動しない)。"""
        c = Constant(value=1.5)
        assert c.dtype == "auto"
        y = _out_array(c)
        assert y.dtype == np.float64
        assert float(y[0]) == 1.5
        assert _out(Constant()) == 1.0

    def test_declared_dtype_applies(self) -> None:
        y = _out_array(Constant(value=2.7, dtype="int32"))
        assert y.dtype == np.int32
        assert int(y[0]) == 2  # ゼロ方向切り捨て (cast_value SSOT)

    def test_bool_dtype(self) -> None:
        assert bool(_out_array(Constant(value=0.4, dtype="bool"))[0]) is True
        assert bool(_out_array(Constant(value=0.0, dtype="bool"))[0]) is False

    def test_raw_value_is_preserved(self) -> None:
        """生値保持: dtype を戻すと元の値が復活する (可逆)。"""
        c = Constant(value=1.5, dtype="int32")
        assert c.value == 1.5
        assert c._params["value"] == 1.5
        assert c._params["dtype"] == "int32"

    def test_auto_not_in_params(self) -> None:
        """Q1: "auto" は保存 JSON に出さない。"""
        assert "dtype" not in Constant(value=2.0)._params

    def test_bad_dtype_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="dtype must be one of"):
            Constant(value=1.0, dtype="double")

    def test_output_type_removed(self) -> None:
        """v0.56.0: output_type param は受け付けない (完全撤去)。"""
        with pytest.raises(TypeError):
            Constant(value=1.0, output_type="int")  # type: ignore[call-arg]

    def test_legacy_params_without_dtype(self) -> None:
        """dtype なしの旧 dict からの復元は挙動不変 (auto 扱い)。"""
        c = Constant(**{"value": 2.0})
        assert c.dtype == "auto"
        assert _out(c) == 2.0

    def test_save_load_round_trip(self, tmp_path: Path) -> None:
        sim1 = Simulator(t_end=0.1, dt=0.01)
        sim1.add(Constant(value=0.4, dtype="bool", id="k"))
        path = tmp_path / "m.flw.json"
        sim1.save(path)
        sim2 = Simulator.load(path)
        k = sim2.get_block("k")
        assert k.dtype == "bool"
        assert k.value == 0.4
        assert bool(_out_array(k)[0]) is True
