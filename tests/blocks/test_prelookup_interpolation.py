"""SPEC-0019 / ADR-0067 (v5.7.0): Prelookup + InterpolationUsingPrelookup 網羅テスト。

カバー範囲:
- Prelookup 構築検証 (厳密単調 / 長さ / enum)
- Prelookup の (k, f) 出力: 定義域内 / clip / linear / error 外挿
- nan / ±inf 入力の伝播
- InterpolationUsingPrelookup 構築検証 + linear/nearest/flat
- Pipeline で LookupTable1D との数値クロスチェック
- registry / i18n 登録
"""

from __future__ import annotations

import numpy as np
import pytest

from pyflw.blocks import InterpolationUsingPrelookup, LookupTable1D, Prelookup
from pyflw.exceptions import BlockEvalError, BlockSpecError

_EMPTY_X = np.array([])


def _prelookup_out(blk: Prelookup, u_val: float) -> tuple[float, float]:
    y = blk.output(0.0, _EMPTY_X, np.array([u_val]))
    return float(y[0]), float(y[1])


def _interp_out(blk: InterpolationUsingPrelookup, k: float, f: float) -> float:
    y = blk.output(0.0, _EMPTY_X, np.array([k, f]))
    return float(y[0])


# ===========================================================================
# Prelookup: Construction & validation
# ===========================================================================


class TestPrelookupConstruction:
    def test_default(self) -> None:
        blk = Prelookup()
        assert blk.n_inputs == 1
        assert blk.n_outputs == 2
        assert blk.direct_feedthrough is True
        assert blk.n_states == 0
        assert blk.extrapolation == "clip"
        assert blk._params == {"breakpoints": [0.0, 1.0], "extrapolation": "clip"}

    def test_custom_breakpoints(self) -> None:
        blk = Prelookup(breakpoints=[0.0, 1.0, 2.5, 5.0], extrapolation="linear")
        assert blk._params["breakpoints"] == [0.0, 1.0, 2.5, 5.0]
        assert blk._params["extrapolation"] == "linear"

    def test_non_monotonic_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="strictly increasing"):
            Prelookup(breakpoints=[2.0, 1.0])

    def test_single_bp_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="at least 2"):
            Prelookup(breakpoints=[0.0])

    def test_invalid_extrapolation_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="extrapolation must be one of"):
            Prelookup(extrapolation="reflect")


# ===========================================================================
# Prelookup: In-domain (k, f)
# ===========================================================================


@pytest.fixture
def bp_0_1_2_3() -> list[float]:
    return [0.0, 1.0, 2.0, 3.0]


class TestPrelookupInDomain:
    @pytest.mark.parametrize(
        "u, exp_k, exp_f",
        [
            (0.0, 0, 0.0),  # 左端 breakpoint そのもの
            (0.5, 0, 0.5),  # cell 0 中央
            (1.0, 1, 0.0),  # 内側 breakpoint そのもの (searchsorted side=right で右側)
            (1.5, 1, 0.5),
            (2.0, 2, 0.0),
            (2.7, 2, 0.7),
            (3.0, 2, 1.0),  # 右端 breakpoint そのもの (clip で cell n-2)
        ],
    )
    def test_kf_values(self, bp_0_1_2_3: list[float], u: float, exp_k: int, exp_f: float) -> None:
        blk = Prelookup(breakpoints=bp_0_1_2_3)
        k, f = _prelookup_out(blk, u)
        assert int(k) == exp_k
        assert f == pytest.approx(exp_f)

    def test_irregular_breakpoints(self) -> None:
        """非等間隔 bp での f が正規化されている。"""
        blk = Prelookup(breakpoints=[0.0, 1.0, 3.0])  # 後段の cell が長い
        k, f = _prelookup_out(blk, 2.0)
        assert int(k) == 1
        assert f == pytest.approx(0.5)  # (2-1) / (3-1)


# ===========================================================================
# Prelookup: Extrapolation
# ===========================================================================


class TestPrelookupExtrapolation:
    def test_clip_left_out(self, bp_0_1_2_3: list[float]) -> None:
        blk = Prelookup(breakpoints=bp_0_1_2_3, extrapolation="clip")
        k, f = _prelookup_out(blk, -1.0)
        assert (int(k), f) == (0, 0.0)

    def test_clip_right_out(self, bp_0_1_2_3: list[float]) -> None:
        blk = Prelookup(breakpoints=bp_0_1_2_3, extrapolation="clip")
        k, f = _prelookup_out(blk, 5.0)
        assert (int(k), f) == (2, 1.0)

    def test_linear_left_out(self, bp_0_1_2_3: list[float]) -> None:
        """linear 外挿: k=0 固定、f = (u - bp[0]) / (bp[1] - bp[0]) (負の値)。"""
        blk = Prelookup(breakpoints=bp_0_1_2_3, extrapolation="linear")
        k, f = _prelookup_out(blk, -1.0)
        assert int(k) == 0
        assert f == pytest.approx(-1.0)

    def test_linear_right_out(self, bp_0_1_2_3: list[float]) -> None:
        """linear 外挿: k=n-2 固定、f = (u - bp[-2]) / (bp[-1] - bp[-2]) (>1)。"""
        blk = Prelookup(breakpoints=bp_0_1_2_3, extrapolation="linear")
        k, f = _prelookup_out(blk, 5.0)
        assert int(k) == 2
        assert f == pytest.approx(3.0)  # (5 - 2) / (3 - 2)

    def test_error_left_out(self, bp_0_1_2_3: list[float]) -> None:
        blk = Prelookup(breakpoints=bp_0_1_2_3, extrapolation="error")
        with pytest.raises(BlockEvalError, match="extrapolation='error'"):
            _prelookup_out(blk, -1.0)

    def test_error_right_out(self, bp_0_1_2_3: list[float]) -> None:
        blk = Prelookup(breakpoints=bp_0_1_2_3, extrapolation="error")
        with pytest.raises(BlockEvalError, match="is outside"):
            _prelookup_out(blk, 5.0)

    def test_error_block_id(self, bp_0_1_2_3: list[float]) -> None:
        """構造化エラー: block_id kwarg が保持される。"""
        blk = Prelookup(breakpoints=bp_0_1_2_3, extrapolation="error", id="prel_test")
        with pytest.raises(BlockEvalError) as exc_info:
            _prelookup_out(blk, 5.0)
        assert exc_info.value.block_id == "prel_test"

    def test_clip_inf_input(self, bp_0_1_2_3: list[float]) -> None:
        """+inf → 右端飽和。"""
        blk = Prelookup(breakpoints=bp_0_1_2_3, extrapolation="clip")
        k, f = _prelookup_out(blk, float("inf"))
        assert (int(k), f) == (2, 1.0)

    def test_clip_neg_inf_input(self, bp_0_1_2_3: list[float]) -> None:
        """-inf → 左端飽和。"""
        blk = Prelookup(breakpoints=bp_0_1_2_3, extrapolation="clip")
        k, f = _prelookup_out(blk, float("-inf"))
        assert (int(k), f) == (0, 0.0)


# ===========================================================================
# Prelookup: nan
# ===========================================================================


class TestPrelookupEdgeCases:
    def test_nan_input_propagates(self, bp_0_1_2_3: list[float]) -> None:
        blk = Prelookup(breakpoints=bp_0_1_2_3, extrapolation="clip")
        y = blk.output(0.0, _EMPTY_X, np.array([float("nan")]))
        assert np.isnan(y[0]) and np.isnan(y[1])

    def test_nan_with_error_extrapolation(self, bp_0_1_2_3: list[float]) -> None:
        """nan は範囲判定が False になるが、error 経路には行かず nan 伝播。"""
        blk = Prelookup(breakpoints=bp_0_1_2_3, extrapolation="error")
        y = blk.output(0.0, _EMPTY_X, np.array([float("nan")]))
        assert np.isnan(y[0]) and np.isnan(y[1])

    def test_int_input_coerced(self) -> None:
        blk = Prelookup(breakpoints=[0.0, 1.0, 2.0])
        y = blk.output(0.0, _EMPTY_X, np.array([1], dtype=int))
        assert int(y[0]) == 1
        assert y[1] == pytest.approx(0.0)


# ===========================================================================
# InterpolationUsingPrelookup: Construction & numerics
# ===========================================================================


class TestInterpolationUsingPrelookupConstruction:
    def test_default(self) -> None:
        blk = InterpolationUsingPrelookup()
        assert blk.n_inputs == 2
        assert blk.n_outputs == 1
        assert blk.direct_feedthrough is True
        assert blk.n_states == 0
        assert blk.interpolation == "linear"
        assert blk._params == {"table": [0.0, 1.0], "interpolation": "linear"}

    def test_single_table_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="at least 2"):
            InterpolationUsingPrelookup(table=[0.0])

    def test_2d_table_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="1-D"):
            InterpolationUsingPrelookup(table=[[0.0, 1.0], [2.0, 3.0]])

    def test_invalid_interpolation_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="interpolation must be one of"):
            InterpolationUsingPrelookup(interpolation="cubic")


class TestInterpolationUsingPrelookupLinear:
    def test_linear_interior(self) -> None:
        blk = InterpolationUsingPrelookup(table=[0.0, 10.0, 30.0, 60.0])
        assert _interp_out(blk, 0, 0.5) == pytest.approx(5.0)
        assert _interp_out(blk, 1, 0.5) == pytest.approx(20.0)
        assert _interp_out(blk, 2, 0.5) == pytest.approx(45.0)

    def test_linear_f_extrapolation(self) -> None:
        """f が [0,1] 範囲外でも線形外挿になる (ADR-0067 §B-1 設計の本質)。"""
        blk = InterpolationUsingPrelookup(table=[0.0, 10.0])
        # f = -1 → y = 0 + (-1) * (10 - 0) = -10 (左外線形外挿)
        assert _interp_out(blk, 0, -1.0) == pytest.approx(-10.0)
        # f = 2 → y = 0 + 2 * (10 - 0) = 20 (右外線形外挿)
        assert _interp_out(blk, 0, 2.0) == pytest.approx(20.0)


class TestInterpolationUsingPrelookupNearest:
    @pytest.mark.parametrize(
        "k, f, expected",
        [
            (0, 0.0, 0.0),  # f=0 → 左
            (0, 0.4, 0.0),  # f<0.5 → 左
            (0, 0.5, 10.0),  # f=0.5 → 右 (ADR-0067 §OQ5: 1 LSB 差を許容)
            (0, 0.9, 10.0),
            (1, 0.5, 20.0),
        ],
    )
    def test_nearest(self, k: int, f: float, expected: float) -> None:
        blk = InterpolationUsingPrelookup(table=[0.0, 10.0, 20.0], interpolation="nearest")
        assert _interp_out(blk, k, f) == pytest.approx(expected)


class TestInterpolationUsingPrelookupFlat:
    @pytest.mark.parametrize(
        "k, f, expected",
        [
            (0, 0.0, 0.0),
            (0, 0.9, 0.0),  # f 無視
            (1, 0.5, 10.0),
        ],
    )
    def test_flat(self, k: int, f: float, expected: float) -> None:
        blk = InterpolationUsingPrelookup(table=[0.0, 10.0, 20.0], interpolation="flat")
        assert _interp_out(blk, k, f) == pytest.approx(expected)


class TestInterpolationUsingPrelookupKBoundary:
    def test_k_clipped_to_n_minus_2(self) -> None:
        """k > n-2 は黙って clip (ADR-0067 §R3)。"""
        blk = InterpolationUsingPrelookup(table=[0.0, 10.0, 20.0])  # n=3, n-2=1
        # k=5 → clip(1) → table[1] + f*(table[2]-table[1])
        assert _interp_out(blk, 5, 0.5) == pytest.approx(15.0)

    def test_k_clipped_to_zero(self) -> None:
        """負の k も clip(0)。"""
        blk = InterpolationUsingPrelookup(table=[0.0, 10.0, 20.0])
        assert _interp_out(blk, -2, 0.5) == pytest.approx(5.0)


# ===========================================================================
# Combined pipeline: Prelookup → Interp vs LookupTable1D
# ===========================================================================


class TestPrelookupInterpolationCombined:
    @pytest.mark.parametrize("u", [0.0, 0.3, 1.0, 1.5, 2.7, 3.0])
    def test_linear_matches_lookup_table_1d(self, u: float) -> None:
        """Pipeline (Prelookup + Interp linear) は LookupTable1D(linear) と数値一致。"""
        bp = [0.0, 1.0, 2.0, 3.0]
        tbl = [0.0, 10.0, 30.0, 60.0]
        p = Prelookup(breakpoints=bp)
        iup = InterpolationUsingPrelookup(table=tbl, interpolation="linear")
        lt = LookupTable1D(breakpoints=bp, table=tbl)

        kf = p.output(0.0, _EMPTY_X, np.array([u]))
        y_pipeline = float(iup.output(0.0, _EMPTY_X, kf)[0])
        y_direct = float(lt.output(0.0, _EMPTY_X, np.array([u]))[0])
        assert y_pipeline == pytest.approx(y_direct)

    def test_linear_extrapolation_matches(self) -> None:
        """linear 外挿でも一致 (ADR-0067 §B-1 の数学的綺麗さ検証)。"""
        bp = [0.0, 1.0, 2.0]
        tbl = [0.0, 10.0, 30.0]
        p = Prelookup(breakpoints=bp, extrapolation="linear")
        iup = InterpolationUsingPrelookup(table=tbl, interpolation="linear")
        lt = LookupTable1D(breakpoints=bp, table=tbl, extrapolation="linear")

        for u in (-1.0, 3.0):
            kf = p.output(0.0, _EMPTY_X, np.array([u]))
            y_pipeline = float(iup.output(0.0, _EMPTY_X, kf)[0])
            y_direct = float(lt.output(0.0, _EMPTY_X, np.array([u]))[0])
            assert y_pipeline == pytest.approx(y_direct), f"mismatch at u={u}"

    def test_shared_breakpoints_multiple_tables(self) -> None:
        """1 Prelookup → 複数 Interpolation で異なる table を補間できる (SPEC §設計目的)。"""
        bp = [0.0, 1.0, 2.0]
        p = Prelookup(breakpoints=bp)
        iup_a = InterpolationUsingPrelookup(table=[10.0, 20.0, 30.0])
        iup_b = InterpolationUsingPrelookup(table=[100.0, 50.0, 25.0])

        kf = p.output(0.0, _EMPTY_X, np.array([0.5]))
        assert float(iup_a.output(0.0, _EMPTY_X, kf)[0]) == pytest.approx(15.0)
        assert float(iup_b.output(0.0, _EMPTY_X, kf)[0]) == pytest.approx(75.0)


# ===========================================================================
# Registry / i18n
# ===========================================================================


class TestPrelookupRegistry:
    def test_in_builtin_metadata(self) -> None:
        from pyflw.server.registry import _BUILTIN_METADATA

        assert "pyflw.blocks.lookup.Prelookup" in _BUILTIN_METADATA
        assert "pyflw.blocks.lookup.InterpolationUsingPrelookup" in _BUILTIN_METADATA
        cat_p, disp_p, _ = _BUILTIN_METADATA["pyflw.blocks.lookup.Prelookup"]
        cat_i, disp_i, _ = _BUILTIN_METADATA["pyflw.blocks.lookup.InterpolationUsingPrelookup"]
        assert cat_p == "lookup"
        assert cat_i == "lookup"
        assert disp_p == "Prelookup"
        assert disp_i == "Interpolation Using Prelookup"

    def test_in_translations(self) -> None:
        from pyflw.server.registry_translations import _BLOCK_TRANSLATIONS

        for type_path in (
            "pyflw.blocks.lookup.Prelookup",
            "pyflw.blocks.lookup.InterpolationUsingPrelookup",
        ):
            assert type_path in _BLOCK_TRANSLATIONS
            entry = _BLOCK_TRANSLATIONS[type_path]
            assert "ja" in entry and "en" in entry
            assert entry["ja"]["display_name"]
            assert entry["en"]["display_name"]
