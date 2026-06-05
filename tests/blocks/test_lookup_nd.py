"""SPEC-0018 / ADR-0068 (v5.8.0): LookupTableND の網羅テスト。

カバー範囲:
- 構築検証 (軸数 / 各軸長さ / 厳密単調 / shape 一致 / enum)
- 3-D / 4-D で linear / nearest / flat 補間
- clip / linear / error 外挿 (各軸境界外)
- nan / inf 伝播 / 大規模 table / 軸数 > 6 warning
- save/load round-trip
- registry / i18n / dynamic n_inputs resolver
- 2-D ケースで LookupTable2D との数値一致 cross-check
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pytest

from pyflw import Simulator
from pyflw.blocks import LookupTable2D, LookupTableND, Scope, Sine
from pyflw.core.persistence import CURRENT_SCHEMA_VERSION
from pyflw.exceptions import BlockEvalError, BlockSpecError, ModelLoadError

_EMPTY_X = np.array([])


def _out(blk: LookupTableND, *u_vals: float) -> float:
    y = blk.output(0.0, _EMPTY_X, np.array(u_vals, dtype=float))
    return float(y[0])


# ===========================================================================
# Construction & validation
# ===========================================================================


class TestLookupTableNDConstruction:
    def test_default_is_2d_zero(self) -> None:
        blk = LookupTableND()
        assert blk.n_inputs == 2
        assert blk.n_outputs == 1
        assert blk.direct_feedthrough is True
        assert blk.n_states == 0
        assert blk.interpolation == "linear"
        assert blk.extrapolation == "clip"
        assert _out(blk, 0.3, 0.7) == pytest.approx(0.0)

    def test_3d_construction(self) -> None:
        bp = [0.0, 1.0]
        table_3d = [[[i * 100 + j * 10 + k for k in range(2)] for j in range(2)] for i in range(2)]
        blk = LookupTableND(breakpoints_axes=[bp, bp, bp], table=table_3d)
        assert blk.n_inputs == 3

    def test_too_few_axes_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="at least 2 axes"):
            LookupTableND(breakpoints_axes=[[0.0, 1.0]], table=[0.0, 1.0])

    def test_too_few_axes_error_message_suggests_1d(self) -> None:
        """エラーメッセージで LookupTable1D への誘導を含む (SPEC-0018 §1.3)。"""
        with pytest.raises(BlockSpecError, match="use LookupTable1D for 1-D"):
            LookupTableND(breakpoints_axes=[[0.0, 1.0]], table=[0.0, 1.0])

    def test_axis_too_short_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="at least 2 elements"):
            LookupTableND(breakpoints_axes=[[0.0], [0.0, 1.0]], table=[[0.0, 0.0]])

    def test_non_monotonic_axis_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="strictly increasing"):
            LookupTableND(
                breakpoints_axes=[[1.0, 0.0], [0.0, 1.0]],
                table=[[0.0, 0.0], [0.0, 0.0]],
            )

    def test_shape_mismatch_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="table.shape="):
            LookupTableND(
                breakpoints_axes=[[0.0, 1.0], [0.0, 1.0]],
                table=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
            )

    def test_table_ndim_mismatch_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="must be 3-D"):
            LookupTableND(
                breakpoints_axes=[[0.0, 1.0], [0.0, 1.0], [0.0, 1.0]],
                table=[[0.0, 0.0], [0.0, 0.0]],  # 2-D instead of 3-D
            )

    def test_invalid_interpolation_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="interpolation must be one of"):
            LookupTableND(interpolation="cubic")

    def test_invalid_extrapolation_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="extrapolation must be one of"):
            LookupTableND(extrapolation="reflect")

    def test_warning_for_axis_count_above_threshold(self, caplog: pytest.LogCaptureFixture) -> None:
        """7 軸以上で warning が出る (hard limit ではない、ADR-0068 §D-1)。"""
        bp = [0.0, 1.0]
        table_7d = np.zeros((2,) * 7).tolist()
        with caplog.at_level(logging.WARNING, logger="pyflw.blocks.lookup"):
            blk = LookupTableND(breakpoints_axes=[bp] * 7, table=table_7d)
        assert "exceeds the recommended threshold" in caplog.text
        assert blk.n_inputs == 7  # 構築自体は成功


# ===========================================================================
# 3-D Interpolation
# ===========================================================================


@pytest.fixture
def simple_3d() -> dict:
    """2×2×2 の代表 cube: table[i][j][k] = i*100 + j*10 + k。"""
    bp = [0.0, 1.0]
    return {
        "breakpoints_axes": [bp, bp, bp],
        "table": [[[i * 100 + j * 10 + k for k in range(2)] for j in range(2)] for i in range(2)],
    }


class TestLookupTableND3D:
    @pytest.mark.parametrize(
        "u, expected",
        [
            ((0.0, 0.0, 0.0), 0.0),  # corner (0, 0, 0)
            ((1.0, 1.0, 1.0), 111.0),  # corner (1, 1, 1)
            ((0.5, 0.5, 0.5), 55.5),  # center
            ((0.0, 0.0, 1.0), 1.0),  # corner (0, 0, 1)
            ((1.0, 0.0, 0.0), 100.0),  # corner (1, 0, 0)
        ],
    )
    def test_linear(self, simple_3d: dict, u: tuple[float, ...], expected: float) -> None:
        blk = LookupTableND(**simple_3d, interpolation="linear")
        assert _out(blk, *u) == pytest.approx(expected)

    def test_nearest_quadrants(self, simple_3d: dict) -> None:
        blk = LookupTableND(**simple_3d, interpolation="nearest")
        assert _out(blk, 0.1, 0.1, 0.1) == pytest.approx(0.0)
        assert _out(blk, 0.6, 0.6, 0.6) == pytest.approx(111.0)

    def test_flat(self, simple_3d: dict) -> None:
        blk = LookupTableND(**simple_3d, interpolation="flat")
        assert _out(blk, 0.5, 0.5, 0.5) == pytest.approx(0.0)  # cell (0,0,0)
        assert _out(blk, 0.99, 0.99, 0.99) == pytest.approx(0.0)


# ===========================================================================
# 4-D Sanity
# ===========================================================================


class TestLookupTableND4D:
    def test_4d_corners(self) -> None:
        bp = [0.0, 1.0]
        # table[i][j][k][l] = i*1000 + j*100 + k*10 + l
        table_4d = [
            [
                [[i * 1000 + j * 100 + k * 10 + m for m in range(2)] for k in range(2)]
                for j in range(2)
            ]
            for i in range(2)
        ]
        blk = LookupTableND(breakpoints_axes=[bp, bp, bp, bp], table=table_4d)
        assert blk.n_inputs == 4
        assert _out(blk, 0.0, 0.0, 0.0, 0.0) == pytest.approx(0.0)
        assert _out(blk, 1.0, 1.0, 1.0, 1.0) == pytest.approx(1111.0)
        # 4-D 中心: 16 隅の平均
        assert _out(blk, 0.5, 0.5, 0.5, 0.5) == pytest.approx(
            (
                0
                + 1
                + 10
                + 11
                + 100
                + 101
                + 110
                + 111
                + 1000
                + 1001
                + 1010
                + 1011
                + 1100
                + 1101
                + 1110
                + 1111
            )
            / 16
        )

    def test_3d_construction_check(self) -> None:
        """構造的に 3 軸ブロックが構築可能。"""
        bp = [0.0, 1.0, 2.0]
        table = np.zeros((3, 3, 3)).tolist()
        blk = LookupTableND(breakpoints_axes=[bp, bp, bp], table=table)
        assert blk.n_inputs == 3


# ===========================================================================
# Extrapolation
# ===========================================================================


class TestLookupTableNDExtrapolation:
    def test_clip_one_axis_out(self, simple_3d: dict) -> None:
        """1 軸が外、他は内側で clip → 端点に飽和して補間。"""
        blk = LookupTableND(**simple_3d, extrapolation="clip")
        # u=(2, 0.5, 0.5) → clip → (1, 0.5, 0.5) → (1, 1, 1)/(1, 1, 0) 中央
        y = _out(blk, 2.0, 0.5, 0.5)
        # (1, 0.5, 0.5) は (1, *, *) の中央 = (100+101+110+111)/4 = 105.5
        assert y == pytest.approx(105.5)

    def test_clip_corner_out(self, simple_3d: dict) -> None:
        """全軸外 → corner にクリップ。"""
        blk = LookupTableND(**simple_3d, extrapolation="clip")
        assert _out(blk, 2.0, 2.0, 2.0) == pytest.approx(111.0)  # (1, 1, 1)
        assert _out(blk, -1.0, -1.0, -1.0) == pytest.approx(0.0)  # (0, 0, 0)

    def test_linear_extrapolation_one_axis(self, simple_3d: dict) -> None:
        """1 軸外 + linear: 2 段階 1-D 外挿合成で線形外挿。"""
        blk = LookupTableND(**simple_3d, extrapolation="linear")
        # u=(2, 0.5, 0.5) で外挿
        y = _out(blk, 2.0, 0.5, 0.5)
        # 軸 0 で u=2 を線形外挿: table[1][*][*] + (2-1)*(table[1][*][*] - table[0][*][*])
        # = (200+201+210+211)/4 = 205.5 を期待
        assert y == pytest.approx(205.5)

    def test_error_extrap(self, simple_3d: dict) -> None:
        blk = LookupTableND(**simple_3d, extrapolation="error")
        with pytest.raises(BlockEvalError, match="extrapolation='error'"):
            _out(blk, 2.0, 0.5, 0.5)

    def test_error_extrap_block_id(self, simple_3d: dict) -> None:
        blk = LookupTableND(**simple_3d, extrapolation="error", id="lt_nd_test")
        with pytest.raises(BlockEvalError) as exc_info:
            _out(blk, -1.0, 0.5, 0.5)
        assert exc_info.value.block_id == "lt_nd_test"

    def test_n_inputs_mismatch_raises(self, simple_3d: dict) -> None:
        """入力数が n_axes と一致しない場合は BlockEvalError。"""
        blk = LookupTableND(**simple_3d)
        with pytest.raises(BlockEvalError, match="expected 3 inputs"):
            blk.output(0.0, _EMPTY_X, np.array([0.5, 0.5]))


# ===========================================================================
# Edge cases
# ===========================================================================


class TestLookupTableNDEdgeCases:
    def test_nan_input_propagates(self, simple_3d: dict) -> None:
        blk = LookupTableND(**simple_3d, extrapolation="clip")
        y = blk.output(0.0, _EMPTY_X, np.array([float("nan"), 0.5, 0.5]))
        assert np.isnan(y[0])

    def test_inf_input_with_clip(self, simple_3d: dict) -> None:
        blk = LookupTableND(**simple_3d, extrapolation="clip")
        y = _out(blk, float("inf"), 0.5, 0.5)
        # (1, 0.5, 0.5) 上で 105.5
        assert y == pytest.approx(105.5)

    def test_table_with_nan_propagates(self) -> None:
        bp = [0.0, 1.0]
        table = [[[float("nan"), 0.0], [0.0, 0.0]], [[0.0, 0.0], [0.0, 0.0]]]
        blk = LookupTableND(breakpoints_axes=[bp, bp, bp], table=table)
        assert np.isnan(_out(blk, 0.5, 0.5, 0.5))

    def test_int_input_coerced(self, simple_3d: dict) -> None:
        blk = LookupTableND(**simple_3d)
        y = blk.output(0.0, _EMPTY_X, np.array([0, 1, 0], dtype=int))
        assert y[0] == pytest.approx(10.0)  # table[0][1][0]


# ===========================================================================
# Persistence
# ===========================================================================


class TestLookupTableNDPersistence:
    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        sim = Simulator(t_end=0.1, dt=0.01)
        bp = [0.0, 1.0, 2.0]
        table_3d = np.linspace(0, 26, 27).reshape(3, 3, 3).tolist()
        original = LookupTableND(
            breakpoints_axes=[bp, bp, bp],
            table=table_3d,
            interpolation="nearest",
            extrapolation="linear",
            id="lt_nd_persist",
        )
        sim.add(original)

        path = tmp_path / "model.flw.json"
        sim.save(str(path))

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == CURRENT_SCHEMA_VERSION

        sim_loaded = Simulator.load(str(path))
        loaded = sim_loaded.get_block("lt_nd_persist")
        assert isinstance(loaded, LookupTableND)
        assert loaded.interpolation == "nearest"
        assert loaded.extrapolation == "linear"
        u = np.array([0.7, 1.3, 0.5])
        assert loaded.output(0.0, _EMPTY_X, u)[0] == pytest.approx(
            original.output(0.0, _EMPTY_X, u)[0]
        )

    def test_load_invalid_shape_raises(self, tmp_path: Path) -> None:
        bad = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "simulator": {"t_end": 1.0, "dt": 0.01},
            "blocks": [
                {
                    "id": "bad",
                    "class_name": "LookupTableND",
                    "params": {
                        "breakpoints_axes": [[0.0, 1.0], [0.0, 1.0]],
                        "table": [[0.0, 0.0, 0.0]],  # shape 不一致
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
# Registry / i18n / dynamic n_inputs
# ===========================================================================


class TestLookupTableNDRegistry:
    def test_in_builtin_metadata(self) -> None:
        from pyflw.server.registry import _BUILTIN_METADATA

        assert "pyflw.blocks.lookup.LookupTableND" in _BUILTIN_METADATA
        category, display, icon = _BUILTIN_METADATA["pyflw.blocks.lookup.LookupTableND"]
        assert category == "lookup"
        assert display == "Lookup Table (N-D)"

    def test_in_translations(self) -> None:
        from pyflw.server.registry_translations import _BLOCK_TRANSLATIONS

        entry = _BLOCK_TRANSLATIONS["pyflw.blocks.lookup.LookupTableND"]
        assert "ja" in entry and "en" in entry
        assert "ルックアップテーブル (N-D)" in entry["ja"]["display_name"]

    def test_dynamic_n_inputs_resolver_in_payload(self) -> None:
        """SPEC-0018 / ADR-0068 §A-1: registry payload に resolver 式が含まれる。"""
        from pyflw.server.registry import build_block_registry, metadata_to_dict

        registry = build_block_registry()
        for meta in registry:
            if meta.type_path == "pyflw.blocks.lookup.LookupTableND":
                d = metadata_to_dict(meta)
                assert d.get("n_inputs_resolver") == "len(params.breakpoints_axes)"
                return
        pytest.fail("LookupTableND not found in registry")

    def test_existing_blocks_have_no_resolver(self) -> None:
        """既存 builtin (固定 n_inputs) は resolver なし (= 後方互換)。"""
        from pyflw.server.registry import build_block_registry, metadata_to_dict

        registry = build_block_registry()
        for meta in registry:
            if meta.type_path in ("pyflw.blocks.sources.Constant", "pyflw.blocks.mathops.Gain"):
                d = metadata_to_dict(meta)
                assert "n_inputs_resolver" not in d


# ===========================================================================
# Cross-check with LookupTable2D
# ===========================================================================


class TestLookupTableNDCrossCheck2D:
    """n=2 のとき LookupTable2D と完全一致 (= LookupTableND の 2-D 縮退)。"""

    @pytest.mark.parametrize(
        "u",
        [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0), (0.3, 0.7), (0.7, 0.3)],
    )
    def test_2d_linear_matches(self, u: tuple[float, float]) -> None:
        bp = [0.0, 1.0]
        tbl = [[0.0, 10.0], [20.0, 30.0]]
        lt_nd = LookupTableND(breakpoints_axes=[bp, bp], table=tbl)
        lt_2d = LookupTable2D(breakpoints_row=bp, breakpoints_col=bp, table=tbl)
        y_nd = float(lt_nd.output(0.0, _EMPTY_X, np.array(u))[0])
        y_2d = float(lt_2d.output(0.0, _EMPTY_X, np.array(u))[0])
        assert y_nd == pytest.approx(y_2d)

    def test_2d_nearest_matches_corner(self) -> None:
        bp = [0.0, 1.0]
        tbl = [[0.0, 10.0], [20.0, 30.0]]
        lt_nd = LookupTableND(breakpoints_axes=[bp, bp], table=tbl, interpolation="nearest")
        lt_2d = LookupTable2D(
            breakpoints_row=bp, breakpoints_col=bp, table=tbl, interpolation="nearest"
        )
        for u in ((0.1, 0.1), (0.9, 0.9)):
            y_nd = float(lt_nd.output(0.0, _EMPTY_X, np.array(u))[0])
            y_2d = float(lt_2d.output(0.0, _EMPTY_X, np.array(u))[0])
            assert y_nd == pytest.approx(y_2d)

    @pytest.mark.parametrize(
        "u",
        [(-0.5, 0.5), (1.5, 0.5), (0.5, -0.5), (0.5, 1.5), (-0.5, -0.5), (1.5, 1.5)],
    )
    def test_2d_linear_extrapolation_matches(self, u: tuple[float, float]) -> None:
        """code-reviewer SHOULD: extrapolation="linear" でも LookupTable2D と数値一致。

        ADR-0068 §C-1 の「2 段階 1-D 外挿合成」が 2-D 縮退で SPEC-0017 §B-1 と
        完全一致することを RTOL=1e-12 で確認。
        """
        bp = [0.0, 1.0]
        tbl = [[0.0, 10.0], [20.0, 30.0]]
        lt_nd = LookupTableND(breakpoints_axes=[bp, bp], table=tbl, extrapolation="linear")
        lt_2d = LookupTable2D(
            breakpoints_row=bp, breakpoints_col=bp, table=tbl, extrapolation="linear"
        )
        y_nd = float(lt_nd.output(0.0, _EMPTY_X, np.array(u))[0])
        y_2d = float(lt_2d.output(0.0, _EMPTY_X, np.array(u))[0])
        assert y_nd == pytest.approx(y_2d, rel=1e-12)


# ===========================================================================
# Integration: Sine x 3 → LookupTableND → Scope
# ===========================================================================


class TestLookupTableNDIntegration:
    def test_3d_in_simulator(self) -> None:
        sim = Simulator(t_end=0.3, dt=0.05)
        sim.add(Sine(amplitude=0.5, frequency=1.0, id="sin_x"))
        sim.add(Sine(amplitude=0.5, frequency=1.0, phase=np.pi / 3, id="sin_y"))
        sim.add(Sine(amplitude=0.5, frequency=1.0, phase=2 * np.pi / 3, id="sin_z"))
        bp = [-1.0, 0.0, 1.0]
        # 中央に山を持つ 3-D pyramid
        table = [
            [[0.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 0.0]],
            [[0.0, 5.0, 0.0], [5.0, 10.0, 5.0], [0.0, 5.0, 0.0]],
            [[0.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 0.0]],
        ]
        sim.add(LookupTableND(breakpoints_axes=[bp, bp, bp], table=table, id="lt_nd"))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("sin_x", "lt_nd", dst_idx=0)
        sim.connect("sin_y", "lt_nd", dst_idx=1)
        sim.connect("sin_z", "lt_nd", dst_idx=2)
        sim.connect("lt_nd", "scope")
        sim.run()
        scope = sim.get_block("scope")
        values = np.asarray(scope.values)
        assert float(values.max()) <= 10.0 + 1e-9
        assert float(values.min()) >= -1e-9
