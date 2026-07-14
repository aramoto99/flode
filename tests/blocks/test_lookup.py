"""SPEC-0008 / ADR-0059 (v5.1.0): LookupTable1D の網羅テスト。

カバー範囲:
- 構築時検証 (厳密単調・長さ・最小2点・enum)
- linear / nearest / flat 補間 × 境界点・中間点
- clip / linear / error 外挿 × 左右端外 × 補間方式の組合せ
- nan / ±inf / int 入力、巨大 breakpoints
- ステートレス (同一 t 多重評価)
- save / load round-trip
- registry / i18n 翻訳テーブルへの登録
- 統合: Sine → LookupTable1D → Scope モデル
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from pyflw import Simulator
from pyflw.blocks import LookupTable1D, Scope, Sine
from pyflw.core.persistence import CURRENT_SCHEMA_VERSION
from pyflw.exceptions import BlockEvalError, BlockSpecError, ModelLoadError

_EMPTY_X = np.array([])


def _out(blk: LookupTable1D, u_val: float) -> float:
    """``output()`` を呼んでスカラー結果を ``float`` で返す。"""
    y = blk.output(0.0, _EMPTY_X, np.array([u_val]))
    return float(y[0])


# ===========================================================================
# Construction & validation
# ===========================================================================


class TestLookupTable1DConstruction:
    def test_default_is_identity_2_points(self) -> None:
        blk = LookupTable1D()
        assert blk.n_inputs == 1
        assert blk.n_outputs == 1
        assert blk.direct_feedthrough is True
        assert blk.n_states == 0
        assert blk.interpolation == "linear"
        assert blk.extrapolation == "clip"
        assert blk._params == {
            "breakpoints": [0.0, 1.0],
            "table": [0.0, 1.0],
            "interpolation": "linear",
            "extrapolation": "clip",
        }
        # 既定で恒等写像
        assert _out(blk, 0.3) == pytest.approx(0.3)

    def test_custom_construction(self) -> None:
        blk = LookupTable1D(
            breakpoints=[0.0, 1.0, 2.0],
            table=[0.0, 10.0, 5.0],
            interpolation="nearest",
            extrapolation="linear",
        )
        assert blk._params == {
            "breakpoints": [0.0, 1.0, 2.0],
            "table": [0.0, 10.0, 5.0],
            "interpolation": "nearest",
            "extrapolation": "linear",
        }

    def test_non_monotonic_breakpoints_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="strictly increasing"):
            LookupTable1D(breakpoints=[2.0, 1.0], table=[0.0, 1.0])

    def test_equal_breakpoints_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="strictly increasing"):
            LookupTable1D(breakpoints=[1.0, 1.0, 2.0], table=[0.0, 1.0, 2.0])

    def test_single_breakpoint_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="at least 2"):
            LookupTable1D(breakpoints=[0.0], table=[1.0])

    def test_empty_breakpoints_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="at least 2"):
            LookupTable1D(breakpoints=[], table=[])

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="must equal"):
            LookupTable1D(breakpoints=[0.0, 1.0, 2.0], table=[0.0, 1.0])

    def test_invalid_interpolation_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="interpolation must be one of"):
            LookupTable1D(interpolation="cubic")

    def test_invalid_extrapolation_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="extrapolation must be one of"):
            LookupTable1D(extrapolation="reflect")

    def test_non_1d_breakpoints_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="1-D arrays"):
            LookupTable1D(breakpoints=[[0.0, 1.0]], table=[[0.0, 1.0]])


# ===========================================================================
# Interpolation modes
# ===========================================================================


@pytest.fixture
def calib_curve() -> tuple[list[float], list[float]]:
    """3 点の非線形カーブ (補間 / 外挿テストの共通フィクスチャ)。"""
    return [0.0, 1.0, 2.0], [0.0, 10.0, 5.0]


class TestLookupTable1DInterpolation:
    @pytest.mark.parametrize(
        "u_val, expected",
        [
            (0.0, 0.0),
            (0.5, 5.0),
            (1.0, 10.0),
            (1.5, 7.5),
            (2.0, 5.0),
        ],
    )
    def test_linear_interpolation(
        self, calib_curve: tuple[list[float], list[float]], u_val: float, expected: float
    ) -> None:
        bp, tbl = calib_curve
        blk = LookupTable1D(breakpoints=bp, table=tbl, interpolation="linear")
        assert _out(blk, u_val) == pytest.approx(expected)

    @pytest.mark.parametrize(
        "u_val, expected",
        [
            (0.0, 0.0),
            (0.4, 0.0),
            (0.5, 0.0),  # 中点同点: scipy kind="nearest" は左側採用
            (0.6, 10.0),
            (1.4, 10.0),
            (1.6, 5.0),
            (2.0, 5.0),
        ],
    )
    def test_nearest_interpolation(
        self, calib_curve: tuple[list[float], list[float]], u_val: float, expected: float
    ) -> None:
        bp, tbl = calib_curve
        blk = LookupTable1D(breakpoints=bp, table=tbl, interpolation="nearest")
        assert _out(blk, u_val) == pytest.approx(expected)

    @pytest.mark.parametrize(
        "u_val, expected",
        [
            (0.0, 0.0),
            (0.5, 0.0),
            (0.99, 0.0),
            (1.0, 10.0),
            (1.99, 10.0),
            (2.0, 5.0),
        ],
    )
    def test_flat_interpolation(
        self, calib_curve: tuple[list[float], list[float]], u_val: float, expected: float
    ) -> None:
        bp, tbl = calib_curve
        blk = LookupTable1D(breakpoints=bp, table=tbl, interpolation="flat")
        assert _out(blk, u_val) == pytest.approx(expected)


# ===========================================================================
# Extrapolation modes (× interpolation の組合せ)
# ===========================================================================


class TestLookupTable1DExtrapolation:
    @pytest.mark.parametrize(
        "interp, u_val, expected",
        [
            ("linear", -1.0, 0.0),  # 左端外 → table[0]
            ("linear", 10.0, 5.0),  # 右端外 → table[-1]
            ("nearest", -5.0, 0.0),
            ("nearest", 100.0, 5.0),
            ("flat", -0.5, 0.0),
            ("flat", 3.0, 5.0),
        ],
    )
    def test_clip_extrapolation(
        self,
        calib_curve: tuple[list[float], list[float]],
        interp: str,
        u_val: float,
        expected: float,
    ) -> None:
        bp, tbl = calib_curve
        blk = LookupTable1D(breakpoints=bp, table=tbl, interpolation=interp, extrapolation="clip")
        assert _out(blk, u_val) == pytest.approx(expected)

    def test_linear_extrap_with_linear_interp(
        self, calib_curve: tuple[list[float], list[float]]
    ) -> None:
        """linear + linear: scipy 標準の "extrapolate" 経路。"""
        bp, tbl = calib_curve
        blk = LookupTable1D(
            breakpoints=bp, table=tbl, interpolation="linear", extrapolation="linear"
        )
        # 左端 slope = (10-0)/(1-0) = 10, u=-1 → 0 + 10*(-1-0) = -10
        assert _out(blk, -1.0) == pytest.approx(-10.0)
        # 右端 slope = (5-10)/(2-1) = -5, u=3 → 5 + (-5)*(3-2) = 0
        assert _out(blk, 3.0) == pytest.approx(0.0)

    def test_linear_extrap_with_nearest_interp(
        self, calib_curve: tuple[list[float], list[float]]
    ) -> None:
        """nearest + linear 外挿: scipy 非対応のため独自 slope 実装。"""
        bp, tbl = calib_curve
        blk = LookupTable1D(
            breakpoints=bp, table=tbl, interpolation="nearest", extrapolation="linear"
        )
        # 定義域外は端点近傍の slope で外挿
        assert _out(blk, -1.0) == pytest.approx(-10.0)
        assert _out(blk, 3.0) == pytest.approx(0.0)
        # 定義域内は nearest として動く
        assert _out(blk, 0.4) == pytest.approx(0.0)
        assert _out(blk, 0.6) == pytest.approx(10.0)

    def test_linear_extrap_with_flat_interp(
        self, calib_curve: tuple[list[float], list[float]]
    ) -> None:
        """flat + linear 外挿: 同じく独自 slope 実装。"""
        bp, tbl = calib_curve
        blk = LookupTable1D(breakpoints=bp, table=tbl, interpolation="flat", extrapolation="linear")
        assert _out(blk, -1.0) == pytest.approx(-10.0)
        assert _out(blk, 3.0) == pytest.approx(0.0)
        # 定義域内は flat (前値ホールド)
        assert _out(blk, 0.99) == pytest.approx(0.0)

    def test_error_extrapolation(self, calib_curve: tuple[list[float], list[float]]) -> None:
        bp, tbl = calib_curve
        blk = LookupTable1D(
            breakpoints=bp, table=tbl, interpolation="linear", extrapolation="error"
        )
        # 定義域内は通常評価
        assert _out(blk, 0.5) == pytest.approx(5.0)
        # 定義域外は BlockEvalError
        with pytest.raises(BlockEvalError, match="outside breakpoints"):
            _out(blk, -1.0)
        with pytest.raises(BlockEvalError, match="outside breakpoints"):
            _out(blk, 10.0)

    def test_error_message_carries_block_id_and_name(
        self, calib_curve: tuple[list[float], list[float]]
    ) -> None:
        """ADR-0056 構造化エラーで UI から発生ブロックへ飛べること。"""
        bp, tbl = calib_curve
        blk = LookupTable1D(breakpoints=bp, table=tbl, extrapolation="error", name="calib")
        with pytest.raises(BlockEvalError) as excinfo:
            _out(blk, -1.0)
        assert "calib" in str(excinfo.value)
        assert excinfo.value.block_id == blk.id


# ===========================================================================
# Edge cases (nan / inf / int / large size)
# ===========================================================================


class TestLookupTable1DEdgeCases:
    @pytest.mark.parametrize("extrap", ["clip", "linear", "error"])
    def test_nan_input_propagates(self, extrap: str) -> None:
        """``nan`` 入力は ``extrapolation`` 設定に関わらず ``nan`` を伝播 (scipy 仕様)。"""
        blk = LookupTable1D(breakpoints=[0, 1, 2], table=[0, 10, 5], extrapolation=extrap)
        assert math.isnan(_out(blk, float("nan")))

    def test_inf_input_clip(self) -> None:
        blk = LookupTable1D(breakpoints=[0, 1, 2], table=[0, 10, 5], extrapolation="clip")
        assert _out(blk, float("inf")) == pytest.approx(5.0)
        assert _out(blk, float("-inf")) == pytest.approx(0.0)

    def test_inf_input_linear_extrap(self) -> None:
        blk = LookupTable1D(breakpoints=[0, 1, 2], table=[0, 10, 5], extrapolation="linear")
        # 右側 slope = -5、+inf に向かって -inf
        assert _out(blk, float("inf")) == float("-inf")
        # 左側 slope = 10、-inf に向かって -inf
        assert _out(blk, float("-inf")) == float("-inf")

    def test_inf_input_linear_extrap_zero_slope(self) -> None:
        """端点 slope = 0 のとき ±inf 入力は極限値 (= 端点値) を返す。

        自前外挿の ``slope * (val - edge_x)`` は 0 * inf = nan になるため、
        ゼロ slope を特別扱いする分岐の回帰テスト (scipy 1.18 互換対応で追加)。
        """
        blk = LookupTable1D(breakpoints=[0, 1], table=[5, 5], extrapolation="linear")
        assert _out(blk, float("inf")) == pytest.approx(5.0)
        assert _out(blk, float("-inf")) == pytest.approx(5.0)

    @pytest.mark.parametrize("interp", ["nearest", "flat"])
    def test_inf_input_linear_extrap_nearest_flat(self, interp: str) -> None:
        """nearest / flat 補間でも ±inf 入力は端点 slope の極限値を返す。"""
        blk = LookupTable1D(
            breakpoints=[0, 1, 2],
            table=[0, 10, 5],
            interpolation=interp,
            extrapolation="linear",
        )
        # 右側 slope = -5 → +inf で -inf、左側 slope = 10 → -inf で -inf
        assert _out(blk, float("inf")) == float("-inf")
        assert _out(blk, float("-inf")) == float("-inf")

    def test_int_input_handled(self) -> None:
        """numpy int 配列入力でも float 化されて動作 (混在モデルで重要)。"""
        blk = LookupTable1D(breakpoints=[0, 1, 2], table=[0, 10, 5])
        y = blk.output(0.0, _EMPTY_X, np.array([1]))
        assert float(y[0]) == pytest.approx(10.0)

    def test_large_breakpoints(self) -> None:
        """N=1000 ブレークポイントでも実用的に動作 (二分探索 O(log N))。"""
        n = 1000
        bp = np.linspace(0.0, 100.0, n)
        tbl = np.sin(bp)
        blk = LookupTable1D(breakpoints=bp.tolist(), table=tbl.tolist())
        assert _out(blk, 50.0) == pytest.approx(math.sin(50.0), abs=1e-3)


# ===========================================================================
# Stateless (same t × multiple evals)
# ===========================================================================


class TestLookupTable1DStateless:
    def test_repeated_output_same_value(self) -> None:
        """同一 ``t`` で多重 ``output`` 呼出 → 同一値 (RK ステージ多重評価で安全)。"""
        blk = LookupTable1D(breakpoints=[0, 1, 2], table=[0, 10, 5])
        results = [_out(blk, 0.5) for _ in range(10)]
        assert all(r == results[0] for r in results)
        assert results[0] == pytest.approx(5.0)


# ===========================================================================
# Persistence (save / load round-trip + 不正データ拒否)
# ===========================================================================


class TestLookupTable1DPersistence:
    def test_save_load_round_trip(self, tmp_path: Path) -> None:
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(
            LookupTable1D(
                breakpoints=[0.0, 1.0, 2.0, 3.0, 4.0],
                table=[0.0, 25.0, 50.0, 75.0, 100.0],
                interpolation="linear",
                extrapolation="clip",
                id="calib",
            )
        )
        path = tmp_path / "model.flw.json"
        sim.save(path)
        sim2 = Simulator.load(path)
        loaded = sim2.get_block("calib")
        assert isinstance(loaded, LookupTable1D)
        assert loaded._params["breakpoints"] == [0.0, 1.0, 2.0, 3.0, 4.0]
        assert loaded._params["table"] == [0.0, 25.0, 50.0, 75.0, 100.0]
        assert loaded.interpolation == "linear"
        assert loaded.extrapolation == "clip"

    def test_load_with_non_monotonic_breakpoints_raises_model_load_error(
        self, tmp_path: Path
    ) -> None:
        """不正な breakpoints はロード時に ``ModelLoadError`` で実行前に拒否される。"""
        bad_payload = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "metadata": {},
            "simulator": {
                "t_end": 1.0,
                "dt": 0.01,
                "solver": "RK45",
                "rtol": 1e-6,
                "atol": 1e-9,
                "dt_base": 0.01,
            },
            "blocks": [
                {
                    "id": "bad",
                    "type": "pyflw.blocks.lookup.LookupTable1D",
                    "params": {
                        "breakpoints": [2.0, 1.0],
                        "table": [0.0, 1.0],
                    },
                }
            ],
            "connections": [],
        }
        path = tmp_path / "bad.flw.json"
        path.write_text(json.dumps(bad_payload))
        # ModelLoadError でラップされ、元の BlockSpecError メッセージが string に保持される
        with pytest.raises(ModelLoadError, match="Cannot instantiate block") as excinfo:
            Simulator.load(path)
        assert "strictly increasing" in str(excinfo.value)


# ===========================================================================
# Registry & i18n
# ===========================================================================


class TestLookupTable1DRegistry:
    def test_translation_entry_exists(self) -> None:
        from pyflw.server.registry_translations import _BLOCK_TRANSLATIONS

        entry = _BLOCK_TRANSLATIONS["pyflw.blocks.lookup.LookupTable1D"]
        assert "display_name" in entry["en"]
        assert "display_name" in entry["ja"]
        assert entry["ja"]["display_name"] == "ルックアップテーブル (1-D)"
        assert entry["en"]["display_name"] == "Lookup Table (1-D)"

    def test_registry_metadata_entry(self) -> None:
        from pyflw.server.registry import _BUILTIN_METADATA

        cat, name, icon = _BUILTIN_METADATA["pyflw.blocks.lookup.LookupTable1D"]
        assert cat == "lookup"
        assert name == "Lookup Table (1-D)"
        assert icon == "lookup.lookuptable1d"


# ===========================================================================
# Integration in Simulator (Sine → LookupTable1D → Scope)
# ===========================================================================


class TestLookupTable1DInModel:
    def test_sine_through_linear_calib_curve(self, tmp_path: Path) -> None:
        """Sine 入力を線形較正カーブ (gain=2) で変換し save/load round-trip。"""

        def build_sim() -> Simulator:
            sim = Simulator(t_end=1.0, dt=0.01)
            sim.add(Sine(amplitude=1.0, frequency=1.0, id="src"))
            sim.add(
                LookupTable1D(
                    breakpoints=[-1.0, 0.0, 1.0],
                    table=[-2.0, 0.0, 2.0],
                    id="calib",
                )
            )
            sim.add(Scope(n_inputs=1, id="out"))
            sim.connect("src", "calib")
            sim.connect("calib", "out")
            return sim

        sim1 = build_sim()
        sim1.run()
        scope1 = sim1.get_block("out")
        y1 = np.asarray(scope1.values)[:, 0].copy()

        path = tmp_path / "calib_model.flw.json"
        sim1.save(path)
        sim2 = Simulator.load(path)
        sim2.run()
        scope2 = sim2.get_block("out")
        y2 = np.asarray(scope2.values)[:, 0]

        np.testing.assert_allclose(y1, y2, rtol=1e-12)
        # Sine 振幅 1 × gain 2 = 振幅 2
        assert np.max(np.abs(y2)) == pytest.approx(2.0, abs=0.05)
