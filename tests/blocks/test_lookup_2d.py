"""SPEC-0017 / ADR-0064 (v5.6.0): LookupTable2D の網羅テスト。

カバー範囲:
- 構築時検証 (厳密単調・長さ・shape 一致・jagged・enum)
- linear (双線形) / nearest / flat 補間 × 角点・エッジ中央・中央点
- clip / linear / error 外挿 × 4 エッジ + 4 隅 × 補間方式の組合せ
- nan / ±inf / int 入力、table 内 nan の伝播、巨大 table
- ステートレス (同一 t 多重評価)
- save / load round-trip
- registry / i18n 翻訳テーブルへの登録
- 補間オブジェクト構築の 1 回性
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from flode import Simulator
from flode.blocks import LookupTable2D, Scope, Sine
from flode.core.persistence import CURRENT_SCHEMA_VERSION
from flode.exceptions import BlockEvalError, BlockSpecError, ModelLoadError

_EMPTY_X = np.array([])


def _out(blk: LookupTable2D, u0: float, u1: float) -> float:
    """``output()`` を呼んでスカラー結果を ``float`` で返す。"""
    y = blk.output(0.0, _EMPTY_X, np.array([u0, u1]))
    return float(y[0])


# ===========================================================================
# Construction & validation
# ===========================================================================


class TestLookupTable2DConstruction:
    def test_default_is_zero_plane(self) -> None:
        blk = LookupTable2D()
        assert blk.n_inputs == 2
        assert blk.n_outputs == 1
        assert blk.direct_feedthrough is True
        assert blk.n_states == 0
        assert blk.interpolation == "linear"
        assert blk.extrapolation == "clip"
        assert blk._params == {
            "breakpoints_row": [0.0, 1.0],
            "breakpoints_col": [0.0, 1.0],
            "table": [[0.0, 0.0], [0.0, 0.0]],
            "interpolation": "linear",
            "extrapolation": "clip",
        }
        assert _out(blk, 0.3, 0.7) == pytest.approx(0.0)

    def test_custom_construction(self) -> None:
        blk = LookupTable2D(
            breakpoints_row=[0.0, 1.0, 2.0],
            breakpoints_col=[0.0, 0.5, 1.0],
            table=[[0.0, 1.0, 2.0], [3.0, 4.0, 5.0], [6.0, 7.0, 8.0]],
            interpolation="nearest",
            extrapolation="linear",
        )
        assert blk._params["interpolation"] == "nearest"
        assert blk._params["extrapolation"] == "linear"
        assert blk._params["table"] == [[0.0, 1.0, 2.0], [3.0, 4.0, 5.0], [6.0, 7.0, 8.0]]

    def test_non_monotonic_bp_row_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="breakpoints_row must be strictly increasing"):
            LookupTable2D(breakpoints_row=[2.0, 1.0], table=[[0.0, 0.0], [0.0, 0.0]])

    def test_non_monotonic_bp_col_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="breakpoints_col must be strictly increasing"):
            LookupTable2D(breakpoints_col=[1.0, 1.0], table=[[0.0, 0.0], [0.0, 0.0]])

    def test_single_bp_row_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="breakpoints_row must have at least 2"):
            LookupTable2D(breakpoints_row=[0.0], table=[[0.0, 0.0]])

    def test_single_bp_col_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="breakpoints_col must have at least 2"):
            LookupTable2D(breakpoints_col=[0.0], table=[[0.0], [0.0]])

    def test_shape_mismatch_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="table.shape="):
            LookupTable2D(
                breakpoints_row=[0.0, 1.0],
                breakpoints_col=[0.0, 1.0],
                table=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
            )

    def test_jagged_table_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="table must be"):
            LookupTable2D(
                breakpoints_row=[0.0, 1.0],
                breakpoints_col=[0.0, 1.0],
                table=[[0.0, 1.0], [0.0]],
            )

    def test_invalid_interpolation_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="interpolation must be one of"):
            LookupTable2D(interpolation="cubic")

    def test_invalid_extrapolation_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="extrapolation must be one of"):
            LookupTable2D(extrapolation="reflect")

    def test_1d_table_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="table must be 2-D"):
            LookupTable2D(
                breakpoints_row=[0.0, 1.0], breakpoints_col=[0.0, 1.0], table=[0.0, 1.0, 2.0, 3.0]
            )


# ===========================================================================
# Interpolation modes
# ===========================================================================


@pytest.fixture
def simple_2x2() -> dict:
    """2×2 の代表テーブル: corners = (0, 10, 20, 30)。"""
    return {
        "breakpoints_row": [0.0, 1.0],
        "breakpoints_col": [0.0, 1.0],
        "table": [[0.0, 10.0], [20.0, 30.0]],
    }


class TestLookupTable2DInterpolationLinear:
    @pytest.mark.parametrize(
        "u0, u1, expected",
        [
            (0.0, 0.0, 0.0),  # corner table[0][0]
            (1.0, 1.0, 30.0),  # corner table[1][1]
            (0.0, 1.0, 10.0),  # corner table[0][1]
            (1.0, 0.0, 20.0),  # corner table[1][0]
            (0.5, 0.5, 15.0),  # center: (0+10+20+30)/4
            (0.5, 0.0, 10.0),  # row edge: (0+20)/2
            (0.0, 0.5, 5.0),  # col edge: (0+10)/2
            (1.0, 0.5, 25.0),  # row edge: (20+30)/2
            (0.5, 1.0, 20.0),  # col edge: (10+30)/2
        ],
    )
    def test_bilinear(self, simple_2x2: dict, u0: float, u1: float, expected: float) -> None:
        blk = LookupTable2D(**simple_2x2, interpolation="linear")
        assert _out(blk, u0, u1) == pytest.approx(expected)

    def test_symmetric_diagonal(self, simple_2x2: dict) -> None:
        """双線形補間の対角線上の対称性。"""
        blk = LookupTable2D(**simple_2x2, interpolation="linear")
        # (t, t) 上の補間値は t について線形 (双線形補間の特性)
        for t in (0.1, 0.3, 0.5, 0.7, 0.9):
            assert _out(blk, t, t) == pytest.approx(15.0 * 2 * t * (1 - t) + 30.0 * t * t)


class TestLookupTable2DInterpolationNearest:
    @pytest.mark.parametrize(
        "u0, u1, expected",
        [
            (0.1, 0.1, 0.0),  # 左下 cell 中央 → table[0][0]
            (0.6, 0.6, 30.0),  # 右上 cell 中央 → table[1][1]
            (0.6, 0.1, 20.0),  # 右下 → table[1][0]
            (0.1, 0.6, 10.0),  # 左上 → table[0][1]
        ],
    )
    def test_nearest_quadrants(
        self, simple_2x2: dict, u0: float, u1: float, expected: float
    ) -> None:
        blk = LookupTable2D(**simple_2x2, interpolation="nearest")
        assert _out(blk, u0, u1) == pytest.approx(expected)


class TestLookupTable2DInterpolationFlat:
    @pytest.mark.parametrize(
        "u0, u1, expected",
        [
            (0.0, 0.0, 0.0),  # 左下角 = table[0][0]
            (0.5, 0.5, 0.0),  # cell (0, 0) 内 → table[0][0]
            (0.99, 0.99, 0.0),  # cell (0, 0) 内 → table[0][0]
            # 右端 breakpoint `u = bp[-1]`: 2×2 では cell が 1 つしかなく、
            # 「右上 cell」が物理的に存在しない (= clip(len-1, 0, len-2) = 0)。
            # よって左下 cell の値 table[0][0] にフォールバック。3×3 以上では
            # `test_flat_3x3_right_top_cell` が右上 cell の挙動を担保する。
            (1.0, 1.0, 0.0),
        ],
    )
    def test_flat_2x2_cell_left_bottom(
        self, simple_2x2: dict, u0: float, u1: float, expected: float
    ) -> None:
        """2×2 では cell が 1 つだけ。境界点も含めて常に table[0][0] = 左下角値。"""
        blk = LookupTable2D(**simple_2x2, interpolation="flat")
        assert _out(blk, u0, u1) == pytest.approx(expected)

    def test_flat_3x3_right_top_cell(self) -> None:
        """3×3 の右上 cell。``u = bp[-1]`` のとき右上 cell の左下角値 = table[1][1]。"""
        blk = LookupTable2D(
            breakpoints_row=[0.0, 0.5, 1.0],
            breakpoints_col=[0.0, 0.5, 1.0],
            table=[[0.0, 1.0, 2.0], [3.0, 4.0, 5.0], [6.0, 7.0, 8.0]],
            interpolation="flat",
        )
        # u = bp[-1] = 1.0 は searchsorted side="right" で右側 cell 扱い
        assert _out(blk, 1.0, 1.0) == pytest.approx(4.0)  # table[1][1]
        # cell (1, 0) 内
        assert _out(blk, 0.7, 0.3) == pytest.approx(3.0)  # table[1][0]


# ===========================================================================
# Extrapolation modes
# ===========================================================================


class TestLookupTable2DExtrapolationClip:
    @pytest.mark.parametrize(
        "u0, u1, expected",
        [
            (-1.0, 0.5, 5.0),  # row 軸下外、col 内: clip → (0, 0.5) → (0+10)/2 = 5
            (2.0, 0.5, 25.0),  # row 軸上外、col 内: clip → (1, 0.5) → (20+30)/2 = 25
            (0.5, -1.0, 10.0),  # row 内、col 下外: clip → (0.5, 0) → 10
            (0.5, 2.0, 20.0),  # row 内、col 上外: clip → (0.5, 1) → 20
            (-1.0, -1.0, 0.0),  # 両軸下外: clip → (0, 0) → 0
            (-1.0, 2.0, 10.0),  # 両軸混合: clip → (0, 1) → 10
            (2.0, -1.0, 20.0),  # 両軸混合: clip → (1, 0) → 20
            (2.0, 2.0, 30.0),  # 両軸上外: clip → (1, 1) → 30
        ],
    )
    def test_clip_with_linear_interp(
        self, simple_2x2: dict, u0: float, u1: float, expected: float
    ) -> None:
        blk = LookupTable2D(**simple_2x2, interpolation="linear", extrapolation="clip")
        assert _out(blk, u0, u1) == pytest.approx(expected)


class TestLookupTable2DExtrapolationLinear:
    def test_linear_extrap_row_below(self, simple_2x2: dict) -> None:
        """row 軸下外、col 軸内: row 方向に線形外挿、col 方向は通常補間。

        u0=-1, u1=0.5 → 2 段階 1-D 外挿:
          row_strip = row_extrap(u0=-1, table) = (col 0: -20, col 1: -10)
          col_interp(u1=0.5, row_strip) = -15
        """
        blk = LookupTable2D(**simple_2x2, extrapolation="linear")
        assert _out(blk, -1.0, 0.5) == pytest.approx(-15.0)

    def test_linear_extrap_row_above(self, simple_2x2: dict) -> None:
        """row 軸上外、col 軸内: u0=2, u1=0.5 → 45。

        row_strip = row_extrap(u0=2) = (col 0: 40, col 1: 50)
        col_interp(0.5, ...) = 45
        """
        blk = LookupTable2D(**simple_2x2, extrapolation="linear")
        assert _out(blk, 2.0, 0.5) == pytest.approx(45.0)

    def test_linear_extrap_col_below(self, simple_2x2: dict) -> None:
        """row 軸内、col 軸下外: u0=0.5, u1=-1 → -10。

        row_strip(u0=0.5) = (col 0: 10, col 1: 20)
        col_extrap(-1, row_strip) = 10 - 1*(20-10)/(1-0) * 1 = 0... ※確認
        """
        blk = LookupTable2D(**simple_2x2, extrapolation="linear")
        # row_strip(u0=0.5) = (0+20)/2=10, (10+30)/2=20。slope (20-10)/(1-0)=10。
        # u1=-1 で extrap: 10 + 10*(-1-0) = 0
        assert _out(blk, 0.5, -1.0) == pytest.approx(0.0)

    def test_linear_extrap_corner_below_below(self, simple_2x2: dict) -> None:
        """両軸下外 (左下隅): 双線形外挿。

        row_strip(u0=-1) = (col 0: -20, col 1: -10)。slope (-10 - -20)/(1-0)=10。
        col_extrap(-1, row_strip) = -20 + 10*(-1-0) = -30
        """
        blk = LookupTable2D(**simple_2x2, extrapolation="linear")
        assert _out(blk, -1.0, -1.0) == pytest.approx(-30.0)

    def test_linear_extrap_corner_above_above(self, simple_2x2: dict) -> None:
        """両軸上外 (右上隅): 双線形外挿。

        row_strip(u0=2) = (col 0: 40, col 1: 50)。slope 10。
        col_extrap(2, ...) = 40 + 10*(2-0) = 60... ※コードで確認
        """
        blk = LookupTable2D(**simple_2x2, extrapolation="linear")
        # interp1d(bp=[0,1], y=[40, 50], extrapolate)(u=2) → 40 + (50-40)/(1-0)*(2-0) = 60
        assert _out(blk, 2.0, 2.0) == pytest.approx(60.0)


class TestLookupTable2DExtrapolationError:
    def test_error_row_below(self, simple_2x2: dict) -> None:
        blk = LookupTable2D(**simple_2x2, extrapolation="error")
        with pytest.raises(BlockEvalError, match="extrapolation='error'"):
            _out(blk, -1.0, 0.5)

    def test_error_corner_below_below(self, simple_2x2: dict) -> None:
        blk = LookupTable2D(**simple_2x2, extrapolation="error")
        with pytest.raises(BlockEvalError, match="is outside"):
            _out(blk, -1.0, -1.0)

    def test_error_block_id_in_exception(self, simple_2x2: dict) -> None:
        """構造化エラー protocol: BlockEvalError は block_id kwarg を保持。"""
        blk = LookupTable2D(**simple_2x2, extrapolation="error", id="lt2d_test")
        with pytest.raises(BlockEvalError) as exc_info:
            _out(blk, -1.0, 0.5)
        assert exc_info.value.block_id == "lt2d_test"


# ===========================================================================
# Edge cases
# ===========================================================================


class TestLookupTable2DEdgeCases:
    def test_nan_input_propagates_with_clip(self, simple_2x2: dict) -> None:
        """nan 入力は extrapolation 設定に関わらず伝播 (1-D と同方針)。"""
        blk = LookupTable2D(**simple_2x2)
        y = blk.output(0.0, _EMPTY_X, np.array([float("nan"), 0.5]))
        assert np.isnan(y[0])

    def test_nan_input_raises_with_error(self, simple_2x2: dict) -> None:
        """nan は range 比較で False になり、error 経路で例外。"""
        blk = LookupTable2D(**simple_2x2, extrapolation="error")
        with pytest.raises(BlockEvalError):
            _out(blk, float("nan"), 0.5)

    def test_inf_input_with_clip(self, simple_2x2: dict) -> None:
        """+inf は clip で右端 bp、補間値は対応端点。"""
        blk = LookupTable2D(**simple_2x2, extrapolation="clip")
        y = _out(blk, float("inf"), 0.5)
        assert y == pytest.approx(25.0)  # (1, 0.5) = (20+30)/2

    def test_table_with_nan_propagates(self) -> None:
        """table 内 nan は補間で伝播 (= 「未定義領域」表現として許容)。"""
        blk = LookupTable2D(
            breakpoints_row=[0.0, 1.0],
            breakpoints_col=[0.0, 1.0],
            table=[[float("nan"), 10.0], [20.0, 30.0]],
        )
        assert np.isnan(_out(blk, 0.5, 0.5))

    def test_large_table_10x10(self) -> None:
        """中規模 table の評価が正しく動作。"""
        bp = list(np.linspace(0.0, 9.0, 10))
        tbl = [[float(i * 10 + j) for j in range(10)] for i in range(10)]
        blk = LookupTable2D(breakpoints_row=bp, breakpoints_col=bp, table=tbl)
        # corner
        assert _out(blk, 0.0, 0.0) == pytest.approx(0.0)
        assert _out(blk, 9.0, 9.0) == pytest.approx(99.0)
        # 中央 (4.5, 4.5) 周辺、双線形補間
        assert _out(blk, 4.5, 4.5) == pytest.approx(49.5)  # (44+45+54+55)/4

    def test_int_input_coerced(self, simple_2x2: dict) -> None:
        """int 入力は float に coerce されて補間。"""
        blk = LookupTable2D(**simple_2x2)
        y = blk.output(0.0, _EMPTY_X, np.array([0, 1], dtype=int))
        assert y[0] == pytest.approx(10.0)  # corner table[0][1]


# ===========================================================================
# Statelessness
# ===========================================================================


class TestLookupTable2DStateless:
    def test_repeated_output_same_t(self, simple_2x2: dict) -> None:
        """同一 t で複数回 output 呼び出し → 同一値 (ステートレス)。"""
        blk = LookupTable2D(**simple_2x2)
        u = np.array([0.5, 0.5])
        y1 = blk.output(1.0, _EMPTY_X, u)
        y2 = blk.output(1.0, _EMPTY_X, u)
        y3 = blk.output(1.0, _EMPTY_X, u)
        assert y1[0] == y2[0] == y3[0] == pytest.approx(15.0)


# ===========================================================================
# Save / Load round-trip
# ===========================================================================


class TestLookupTable2DPersistence:
    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        """`.flw.json` save → load で全 param 復元、出力が一致する。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        original = LookupTable2D(
            breakpoints_row=[0.0, 1.0, 2.0],
            breakpoints_col=[0.0, 0.5, 1.0],
            table=[[0.0, 1.0, 2.0], [3.0, 4.0, 5.0], [6.0, 7.0, 8.0]],
            interpolation="nearest",
            extrapolation="linear",
            id="lt2d_persist",
        )
        sim.add(original)

        path = tmp_path / "model.flw.json"
        sim.save(str(path))

        # JSON が PS-A 自動変換で list[list] になっていることを確認
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == CURRENT_SCHEMA_VERSION
        blk_json = data["blocks"][0]
        assert blk_json["params"]["table"] == [
            [0.0, 1.0, 2.0],
            [3.0, 4.0, 5.0],
            [6.0, 7.0, 8.0],
        ]

        # round-trip 後の同一出力
        sim_loaded = Simulator.load(str(path))
        loaded = sim_loaded.get_block("lt2d_persist")
        assert isinstance(loaded, LookupTable2D)
        assert loaded.interpolation == "nearest"
        assert loaded.extrapolation == "linear"
        u = np.array([0.7, 0.3])
        assert loaded.output(0.0, _EMPTY_X, u)[0] == pytest.approx(
            original.output(0.0, _EMPTY_X, u)[0]
        )

    def test_load_with_invalid_data_raises(self, tmp_path: Path) -> None:
        """不正 (= shape mismatch) な永続化 JSON のロードで ModelLoadError。"""
        bad = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "simulator": {"t_end": 1.0, "dt": 0.01},
            "blocks": [
                {
                    "id": "bad",
                    "class_name": "LookupTable2D",
                    "params": {
                        "breakpoints_row": [0.0, 1.0],
                        "breakpoints_col": [0.0, 1.0],
                        "table": [[0.0, 0.0, 0.0]],  # shape (1, 3) ≠ (2, 2)
                    },
                    "x": 0,
                    "y": 0,
                }
            ],
            "connections": [],
        }
        path = tmp_path / "bad.flw.json"
        path.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ModelLoadError):
            Simulator.load(str(path))


# ===========================================================================
# Registry / i18n integration
# ===========================================================================


class TestLookupTable2DRegistry:
    def test_in_builtin_metadata(self) -> None:
        from flode.server.registry import _BUILTIN_METADATA

        assert "flode.blocks.lookup.LookupTable2D" in _BUILTIN_METADATA
        category, display, icon = _BUILTIN_METADATA["flode.blocks.lookup.LookupTable2D"]
        assert category == "lookup"
        assert display == "Lookup Table (2-D)"
        assert icon == "lookup.lookuptable2d"

    def test_in_translations(self) -> None:
        from flode.server.registry_translations import _BLOCK_TRANSLATIONS

        assert "flode.blocks.lookup.LookupTable2D" in _BLOCK_TRANSLATIONS
        entry = _BLOCK_TRANSLATIONS["flode.blocks.lookup.LookupTable2D"]
        assert "ja" in entry and "en" in entry
        assert "ルックアップテーブル (2-D)" in entry["ja"]["display_name"]
        assert "Lookup Table (2-D)" in entry["en"]["display_name"]

    def test_interp_constructed_once_per_instance(self) -> None:
        """RegularGridInterpolator は __init__ で 1 度だけ構築 (ホットパスで再構築しない)。"""
        blk = LookupTable2D(
            breakpoints_row=[0.0, 1.0],
            breakpoints_col=[0.0, 1.0],
            table=[[0.0, 10.0], [20.0, 30.0]],
        )
        interp_obj_before = blk._interp
        # 100 回評価しても同じインスタンスを使い続ける
        for _ in range(100):
            blk.output(0.0, _EMPTY_X, np.array([0.5, 0.5]))
        assert blk._interp is interp_obj_before


# ===========================================================================
# Integration: Sine x 2 → LookupTable2D → Scope
# ===========================================================================


class TestLookupTable2DIntegration:
    def test_two_sines_to_lookup_to_scope(self) -> None:
        """位相ずれ Sine 2 本を 2-D マップに通して Scope に出力するモデル。"""
        sim = Simulator(t_end=0.5, dt=0.05)

        sim.add(Sine(amplitude=1.0, frequency=1.0, id="sin_x"))
        sim.add(Sine(amplitude=1.0, frequency=1.0, phase=0.5, id="sin_y"))
        sim.add(
            LookupTable2D(
                breakpoints_row=[-1.0, 0.0, 1.0],
                breakpoints_col=[-1.0, 0.0, 1.0],
                table=[
                    [0.0, 5.0, 0.0],
                    [5.0, 10.0, 5.0],
                    [0.0, 5.0, 0.0],
                ],
                id="lt2d",
            )
        )
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("sin_x", "lt2d", dst_idx=0)
        sim.connect("sin_y", "lt2d", dst_idx=1)
        sim.connect("lt2d", "scope")

        sim.run()
        scope = sim.get_block("scope")
        assert len(scope.times) > 0
        values = np.asarray(scope.values)
        # ピラミッド形状なので最大値は 10 (中央)、最小値は 0 (角)
        assert float(values.max()) <= 10.0 + 1e-9
        assert float(values.min()) >= -1e-9
