"""ADR-0020 §(1)〜(8): JSON schema レイアウト永続化のテスト。

カバレッジ:
  #1 schema 0.4 → 0.5 migration (no-op)
  #2 chained migration: 0.1 → 0.5
  #3 layout 引数なし save: ``layout`` キーが JSON に出ない (byte-identical)
  #4 layout 引数あり save → load: ``last_loaded_layout`` で復元
  #5 stale block id を含む layout は drop + warning
  #6 部分指定 layout (一部 block だけ position あり)
  #7 Subsystem 内部 ``params.layout`` round-trip
  #8 ``normalize_layout`` の型エラー / 形式エラー
  #9 layout を持つ 0.5 ファイルを load → save round-trip
  #10 layout のキー順 (canonical = blocks 順)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from pyflw import Simulator
from pyflw.blocks import Constant, Gain, Scope
from pyflw.core.persistence import (
    CURRENT_SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    normalize_layout,
)
from pyflw.exceptions import ModelLoadError
from pyflw.subsystems import Inport, Outport, Subsystem


def _build_simple_sim() -> Simulator:
    sim = Simulator(t_end=0.05, dt=0.01)
    sim.add(Constant(value=1.0, id="src"))
    sim.add(Gain(k=2.0, id="g"))
    sim.add(Scope(n_inputs=1, id="sc"))
    sim.connect("src", "g")
    sim.connect("g", "sc")
    return sim


# ---------------------------------------------------------------------------
# Schema version & migration
# ---------------------------------------------------------------------------


class TestSchemaVersion:
    def test_current_is_0_6(self) -> None:
        # ADR-0021: 0.5 → 0.6 bump (mask params)
        assert CURRENT_SCHEMA_VERSION == "0.6"

    def test_supported_includes_0_6(self) -> None:
        assert "0.6" in SUPPORTED_SCHEMA_VERSIONS


class TestMigration0_4_to_0_5:
    def test_no_op_migration(self, tmp_path: Path) -> None:
        """0.4 ファイル (layout 無し) を load → CURRENT (0.5) として動く。"""
        legacy = {
            "schema_version": "0.4",
            "simulator": {
                "t_end": 0.05,
                "dt": 0.01,
                "solver": "RK45",
                "rtol": 1e-6,
                "atol": 1e-9,
                "dt_base": None,
            },
            "blocks": [
                {
                    "id": "src",
                    "type": "pyflw.blocks.sources.Constant",
                    "params": {"value": 5.0},
                }
            ],
            "connections": [],
        }
        path = tmp_path / "legacy_0_4.flw.json"
        path.write_text(json.dumps(legacy), encoding="utf-8")
        sim = Simulator.load(path)
        assert sim.last_loaded_layout is None  # layout 無し → None
        assert len(sim.blocks) == 1

    def test_chain_migration_0_1_to_0_5(self, tmp_path: Path) -> None:
        legacy = {
            "schema_version": "0.1",
            "simulator": {
                "t_end": 0.05,
                "dt": 0.01,
                "solver": "RK45",
                "rtol": 1e-6,
                "atol": 1e-9,
                "dt_base": None,
            },
            "blocks": [],
            "connections": [],
        }
        path = tmp_path / "legacy_0_1.flw.json"
        path.write_text(json.dumps(legacy), encoding="utf-8")
        sim = Simulator.load(path)
        assert sim.last_loaded_layout is None


# ---------------------------------------------------------------------------
# Save without layout (byte-identical to v0.6.x for SM-A)
# ---------------------------------------------------------------------------


class TestSaveWithoutLayout:
    def test_no_layout_key_in_json(self, tmp_path: Path) -> None:
        sim = _build_simple_sim()
        path = tmp_path / "no_layout.flw.json"
        sim.save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "layout" not in data

    def test_save_with_none_layout_is_same(self, tmp_path: Path) -> None:
        sim = _build_simple_sim()
        path = tmp_path / "none_layout.flw.json"
        sim.save(path, layout=None)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "layout" not in data

    def test_save_with_empty_dict_layout_is_same(self, tmp_path: Path) -> None:
        sim = _build_simple_sim()
        path = tmp_path / "empty_layout.flw.json"
        sim.save(path, layout={})
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "layout" not in data


# ---------------------------------------------------------------------------
# Save with layout → load round-trip
# ---------------------------------------------------------------------------


class TestSaveLoadLayoutRoundTrip:
    def test_full_layout_roundtrip(self, tmp_path: Path) -> None:
        sim = _build_simple_sim()
        layout = {
            "src": {"x": 100.0, "y": 60.0},
            "g": {"x": 300.0, "y": 60.0},
            "sc": {"x": 500.0, "y": 60.0},
        }
        path = tmp_path / "layout.flw.json"
        sim.save(path, layout=layout)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["layout"] == layout

        sim2 = Simulator.load(path)
        assert sim2.last_loaded_layout == layout

    def test_partial_layout_only_positions_some_blocks(self, tmp_path: Path) -> None:
        """一部の block にだけ position が存在する layout は許容される。"""
        sim = _build_simple_sim()
        partial = {"src": {"x": 100.0, "y": 60.0}}  # g, sc は欠落
        path = tmp_path / "partial.flw.json"
        sim.save(path, layout=partial)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["layout"] == {"src": {"x": 100.0, "y": 60.0}}

        sim2 = Simulator.load(path)
        assert sim2.last_loaded_layout == {"src": {"x": 100.0, "y": 60.0}}

    def test_canonical_key_order_matches_blocks_order(self, tmp_path: Path) -> None:
        """layout の key 順は blocks の出現順に揃える (ADR-0020 §Decision (1))。"""
        sim = _build_simple_sim()
        # blocks 順 = ['src', 'g', 'sc']、layout 入力は逆順だが save 後は blocks 順
        layout_unordered = {
            "sc": {"x": 500.0, "y": 60.0},
            "g": {"x": 300.0, "y": 60.0},
            "src": {"x": 100.0, "y": 60.0},
        }
        path = tmp_path / "ordered.flw.json"
        sim.save(path, layout=layout_unordered)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert list(data["layout"].keys()) == ["src", "g", "sc"]

    def test_int_values_normalized_to_float(self, tmp_path: Path) -> None:
        sim = _build_simple_sim()
        layout = {"src": {"x": 100, "y": 60}}  # int
        path = tmp_path / "int_layout.flw.json"
        sim.save(path, layout=layout)
        sim2 = Simulator.load(path)
        assert sim2.last_loaded_layout is not None
        assert isinstance(sim2.last_loaded_layout["src"]["x"], float)
        assert sim2.last_loaded_layout["src"]["x"] == 100.0


# ---------------------------------------------------------------------------
# Stale layout entries
# ---------------------------------------------------------------------------


class TestStaleLayoutEntries:
    def test_save_drops_stale_id_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        sim = _build_simple_sim()  # blocks: src, g, sc
        layout = {
            "src": {"x": 100.0, "y": 60.0},
            "deleted": {"x": 200.0, "y": 60.0},  # stale
        }
        path = tmp_path / "stale.flw.json"
        with caplog.at_level(logging.WARNING):
            sim.save(path, layout=layout)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "deleted" not in data["layout"]
        assert any("deleted" in record.getMessage() for record in caplog.records)

    def test_load_drops_stale_id_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "stale.flw.json"
        payload = {
            "schema_version": "0.5",
            "simulator": {
                "t_end": 0.05,
                "dt": 0.01,
                "solver": "RK45",
                "rtol": 1e-6,
                "atol": 1e-9,
                "dt_base": None,
            },
            "blocks": [
                {
                    "id": "src",
                    "type": "pyflw.blocks.sources.Constant",
                    "params": {"value": 1.0},
                }
            ],
            "connections": [],
            "layout": {
                "src": {"x": 100.0, "y": 60.0},
                "ghost": {"x": 50.0, "y": 50.0},
            },
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            sim = Simulator.load(path)
        assert sim.last_loaded_layout == {"src": {"x": 100.0, "y": 60.0}}
        assert any("ghost" in record.getMessage() for record in caplog.records)


# ---------------------------------------------------------------------------
# Subsystem internal layout
# ---------------------------------------------------------------------------


class TestSubsystemLayoutRoundTrip:
    def _build_subsystem_model(self, layout: dict[str, dict[str, float]] | None) -> Simulator:
        sub = Subsystem(n_inputs=1, n_outputs=1, id="sub", layout=layout)
        sub.add(Inport(port_idx=0, id="ip0"))
        sub.add(Gain(k=2.0, id="g_inner"))
        sub.add(Outport(port_idx=0, id="op0"))
        sub.connect("ip0", "g_inner")
        sub.connect("g_inner", "op0")
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(sub)
        return sim

    def test_subsystem_without_layout_omits_params_layout(self, tmp_path: Path) -> None:
        sim = self._build_subsystem_model(layout=None)
        path = tmp_path / "no_layout.flw.json"
        sim.save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        sub_entry = next(b for b in data["blocks"] if b["id"] == "sub")
        assert "layout" not in sub_entry["params"]

    def test_subsystem_with_layout_persists_in_params(self, tmp_path: Path) -> None:
        layout = {
            "ip0": {"x": 40.0, "y": 80.0},
            "g_inner": {"x": 200.0, "y": 80.0},
            "op0": {"x": 360.0, "y": 80.0},
        }
        sim = self._build_subsystem_model(layout=layout)
        path = tmp_path / "with_layout.flw.json"
        sim.save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        sub_entry = next(b for b in data["blocks"] if b["id"] == "sub")
        assert sub_entry["params"]["layout"] == layout

    def test_subsystem_layout_load_round_trip(self, tmp_path: Path) -> None:
        layout = {
            "ip0": {"x": 40.0, "y": 80.0},
            "g_inner": {"x": 200.0, "y": 80.0},
            "op0": {"x": 360.0, "y": 80.0},
        }
        sim = self._build_subsystem_model(layout=layout)
        path = tmp_path / "rt.flw.json"
        sim.save(path)
        sim2 = Simulator.load(path)
        sub2 = sim2.get_block("sub")
        assert sub2.layout == layout


# ---------------------------------------------------------------------------
# normalize_layout behavior
# ---------------------------------------------------------------------------


class TestNormalizeLayout:
    def test_none_returns_none(self) -> None:
        assert normalize_layout(None) is None

    def test_empty_dict_returns_none(self) -> None:
        assert normalize_layout({}) is None

    def test_int_x_y_become_float(self) -> None:
        out = normalize_layout({"a": {"x": 1, "y": 2}})
        assert out == {"a": {"x": 1.0, "y": 2.0}}
        assert isinstance(out["a"]["x"], float)

    def test_non_dict_raises(self) -> None:
        with pytest.raises(ModelLoadError, match="layout must be a dict"):
            normalize_layout([1, 2, 3])  # type: ignore[arg-type]

    def test_non_str_key_raises(self) -> None:
        with pytest.raises(ModelLoadError, match="block id"):
            normalize_layout({1: {"x": 0.0, "y": 0.0}})  # type: ignore[dict-item]

    def test_missing_x_raises(self) -> None:
        with pytest.raises(ModelLoadError, match="must contain both 'x' and 'y'"):
            normalize_layout({"a": {"y": 1.0}})

    def test_missing_y_raises(self) -> None:
        with pytest.raises(ModelLoadError, match="must contain both 'x' and 'y'"):
            normalize_layout({"a": {"x": 1.0}})

    def test_non_numeric_x_raises(self) -> None:
        with pytest.raises(ModelLoadError, match="non-numeric"):
            normalize_layout({"a": {"x": "abc", "y": 0}})

    def test_non_dict_value_raises(self) -> None:
        with pytest.raises(ModelLoadError, match="must be a dict"):
            normalize_layout({"a": "not a dict"})  # type: ignore[dict-item]

    # --- optional w/h (NodeResizer 用、ユーザー要望で追加) ---

    def test_w_h_round_trip(self) -> None:
        out = normalize_layout({"a": {"x": 1.0, "y": 2.0, "w": 100.0, "h": 50.0}})
        assert out == {"a": {"x": 1.0, "y": 2.0, "w": 100.0, "h": 50.0}}

    def test_w_h_int_coerced_to_float(self) -> None:
        out = normalize_layout({"a": {"x": 0, "y": 0, "w": 80, "h": 40}})
        assert out == {"a": {"x": 0.0, "y": 0.0, "w": 80.0, "h": 40.0}}

    def test_missing_w_h_is_ok(self) -> None:
        # 既存の x/y のみのエントリは依然として valid
        out = normalize_layout({"a": {"x": 1.0, "y": 2.0}})
        assert out == {"a": {"x": 1.0, "y": 2.0}}

    def test_zero_or_negative_size_is_dropped(self) -> None:
        # 不正値 (NodeResizer の minWidth/Height で起こり得ない) は黙って drop
        out = normalize_layout({"a": {"x": 1.0, "y": 2.0, "w": 0.0, "h": -10.0}})
        assert out == {"a": {"x": 1.0, "y": 2.0}}

    def test_partial_w_only(self) -> None:
        out = normalize_layout({"a": {"x": 0.0, "y": 0.0, "w": 80.0}})
        assert out == {"a": {"x": 0.0, "y": 0.0, "w": 80.0}}

    def test_non_numeric_w_raises(self) -> None:
        with pytest.raises(ModelLoadError, match="non-numeric"):
            normalize_layout({"a": {"x": 0.0, "y": 0.0, "w": "abc"}})


# ---------------------------------------------------------------------------
# v0.6.x → v0.7.0 forward compatibility
# ---------------------------------------------------------------------------


class TestForwardCompat:
    def test_load_0_5_with_layout_then_resave_includes_layout(self, tmp_path: Path) -> None:
        """0.5 ファイル (layout あり) を load → 同じ layout で再 save できる。"""
        path1 = tmp_path / "in.flw.json"
        sim = _build_simple_sim()
        layout = {"src": {"x": 10.0, "y": 20.0}}
        sim.save(path1, layout=layout)
        sim2 = Simulator.load(path1)
        path2 = tmp_path / "out.flw.json"
        sim2.save(path2, layout=sim2.last_loaded_layout)
        data = json.loads(path2.read_text(encoding="utf-8"))
        assert data["layout"] == layout
