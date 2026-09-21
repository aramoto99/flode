"""SPEC-0028 / ADR-0077: Cast (実 dtype 変換) の網羅テスト。

v0.56.0 で ``output_type`` (値の意味論、旧 SPEC-0026) は撤去され、Cast は
``dtype`` のみを持つ「常に変換するブロック」になった。変換規則の SSOT は
:func:`flode.core.dtypes.cast_value` (規則自体の網羅は ``test_dtypes.py``)。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from flode import Simulator
from flode.blocks import Cast, Scope, Sine
from flode.core.signals import DTYPE_VOCABULARY
from flode.exceptions import BlockSpecError

_EMPTY_X = np.array([])


def _out(blk: Cast, u_val: float) -> np.ndarray:
    return blk.output(0.0, _EMPTY_X, np.array([u_val]))


class TestCastConstruction:
    def test_default_is_float64_real_conversion(self) -> None:
        """既定は "float64" (恒等ではなく実変換)。恒等モード (auto) は存在しない。"""
        b = Cast()
        assert b.dtype == "float64"
        y = _out(b, 2.7)
        assert y.dtype == np.float64
        assert float(y[0]) == 2.7

    def test_structure(self) -> None:
        b = Cast()
        assert b.n_inputs == 1
        assert b.n_outputs == 1
        assert b.direct_feedthrough is True
        assert b.n_states == 0

    def test_all_vocabulary_accepted(self) -> None:
        for dt in DTYPE_VOCABULARY:
            assert Cast(dtype=dt).dtype == dt

    def test_auto_rejected(self) -> None:
        """Cast に "auto" はない — 置いたのに何も起きない Cast を許さない。"""
        with pytest.raises(BlockSpecError, match="dtype must be one of"):
            Cast(dtype="auto")

    def test_bad_dtype_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="dtype must be one of"):
            Cast(dtype="int8")

    def test_output_type_removed(self) -> None:
        """v0.56.0: output_type param は受け付けない (完全撤去)。"""
        with pytest.raises(TypeError):
            Cast(output_type="int")  # type: ignore[call-arg]

    def test_dtype_always_in_params(self) -> None:
        """Cast は常に宣言ブロック → dtype は保存 JSON に必ず出る。"""
        assert Cast()._params == {"dtype": "float64"}
        assert Cast(dtype="int32")._params == {"dtype": "int32"}


class TestCastOutputDtype:
    @pytest.mark.parametrize("dt", DTYPE_VOCABULARY)
    def test_output_has_declared_dtype(self, dt: str) -> None:
        y = _out(Cast(dtype=dt), 1.0)
        assert y.dtype == np.dtype(dt)


class TestCastIntConversion:
    @pytest.mark.parametrize(
        "u, expected",
        [
            (2.7, 2),  # ゼロ方向切り捨て (偶数丸めではない)
            (-2.7, -2),
            (2.5, 2),
            (5.0, 5),
            (float("nan"), 0),  # 決定的規則: nan → 0
        ],
    )
    def test_trunc_toward_zero(self, u: float, expected: int) -> None:
        y = _out(Cast(dtype="int32"), u)
        assert int(y[0]) == expected

    def test_inf_saturates(self) -> None:
        assert int(_out(Cast(dtype="int32"), float("inf"))[0]) == np.iinfo(np.int32).max
        assert int(_out(Cast(dtype="int32"), float("-inf"))[0]) == np.iinfo(np.int32).min

    def test_uint8_wraps(self) -> None:
        assert int(_out(Cast(dtype="uint8"), 257.0)[0]) == 1
        assert int(_out(Cast(dtype="uint8"), -1.0)[0]) == 255


class TestCastBoolConversion:
    @pytest.mark.parametrize(
        "u, expected",
        [(3.2, True), (-3.2, True), (0.0, False), (-0.0, False), (1e-300, True)],
    )
    def test_zero_threshold(self, u: float, expected: bool) -> None:
        assert bool(_out(Cast(dtype="bool"), u)[0]) is expected

    def test_nan_is_true(self) -> None:
        """nan != 0 は真 → True。例外規則を作らない (cast_value SSOT)。"""
        assert bool(_out(Cast(dtype="bool"), float("nan"))[0]) is True


class TestCastStateless:
    def test_repeated_same_value(self) -> None:
        b = Cast(dtype="int32")
        rs = [int(_out(b, 2.7)[0]) for _ in range(5)]
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
        sim.add(Cast(dtype="bool", id="c"))
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("src", "c")
        sim.connect("c", "sc")
        sim.run()
        vals = np.asarray(sim.get_block("sc").values)[:, 0]
        assert set(np.unique(vals)) <= {0.0, 1.0}

    def test_save_load_round_trip(self, tmp_path: Path) -> None:
        sim1 = Simulator(t_end=0.1, dt=0.01)
        sim1.add(Cast(dtype="bool", id="c"))
        path = tmp_path / "m.flw.json"
        sim1.save(path)
        sim2 = Simulator.load(path)
        assert sim2.get_block("c").dtype == "bool"
