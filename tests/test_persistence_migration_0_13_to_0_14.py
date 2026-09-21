"""v0.62.0 (ADR-0079 Stage 1): schema 0.13 → 0.14 migration の単体テスト。

内容は version 更新のみ (D-12)。AC-9: 既存 0.13 ファイルの load → save の差分が
``schema_version`` 行だけであることを round-trip で固定する。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from flode import Simulator
from flode.core.persistence import (
    CURRENT_SCHEMA_VERSION,
    _builtin_migrate_0_13_to_0_14,
    migrate_to_current,
)


def test_current_schema_version_is_0_14() -> None:
    assert CURRENT_SCHEMA_VERSION == "0.15"


def _model_0_13(
    blocks: list[dict[str, Any]], connections: list[Any] | None = None
) -> dict[str, Any]:
    return {
        "schema_version": "0.13",
        "metadata": {"created_at": "2026-09-14T00:00:00Z", "tool": "flode 0.61.0"},
        "simulator": {
            "t_end": 0.05,
            "dt": 0.01,
            "solver": "RK45",
            "rtol": 1e-6,
            "atol": 1e-9,
            "dt_base": None,
        },
        "blocks": blocks,
        "connections": connections or [],
        "layout": {},
    }


_BLOCKS = [
    {"id": "c0", "type": "flode.blocks.sources.Constant", "params": {"value": 1.0}},
    {"id": "c1", "type": "flode.blocks.sources.Constant", "params": {"value": 2.0}},
    {"id": "m", "type": "flode.blocks.routing.Mux", "params": {"n": 2}},
    {"id": "g", "type": "flode.blocks.mathops.Gain", "params": {"k": 3.0}},
    {"id": "d", "type": "flode.blocks.routing.Demux", "params": {"n": 2}},
    {
        "id": "sc",
        "type": "flode.blocks.sinks.Scope",
        "params": {
            "n_inputs": 2,
            "labels": ["a", "b"],
            "buffer_mode": "ring",
            "buffer_capacity": 100000,
        },
    },
]
_CONNS = [
    {"src": "c0", "src_idx": 0, "dst": "m", "dst_idx": 0},
    {"src": "c1", "src_idx": 0, "dst": "m", "dst_idx": 1},
    {"src": "m", "src_idx": 0, "dst": "g", "dst_idx": 0},
    {"src": "g", "src_idx": 0, "dst": "d", "dst_idx": 0},
    {"src": "d", "src_idx": 0, "dst": "sc", "dst_idx": 0},
    {"src": "d", "src_idx": 1, "dst": "sc", "dst_idx": 1},
]


class TestMigration:
    def test_only_version_changes(self) -> None:
        data = _model_0_13(_BLOCKS, _CONNS)
        out = _builtin_migrate_0_13_to_0_14(data)
        assert out["schema_version"] == "0.14"
        assert out["blocks"] == data["blocks"]
        assert out["connections"] == data["connections"]
        assert data["schema_version"] == "0.13"  # 入力は非破壊

    def test_chain_from_0_13_reaches_current(self) -> None:
        out = migrate_to_current(_model_0_13([]))
        assert out["schema_version"] == "0.15"
        assert out["_migrated_from"] == "0.13"

    def test_load_save_diff_is_schema_version_only(self, tmp_path: Path) -> None:
        """AC-9: 0.13 ファイルの load → save で変わる行は schema_version だけ。"""
        before = tmp_path / "before.flw.json"
        after = tmp_path / "after.flw.json"
        before.write_text(json.dumps(_model_0_13(_BLOCKS, _CONNS), indent=2), encoding="utf-8")
        sim = Simulator.load(before)
        sim.save(after)
        saved = json.loads(after.read_text(encoding="utf-8"))
        original = json.loads(before.read_text(encoding="utf-8"))
        assert saved["schema_version"] == "0.15"
        assert saved["blocks"] == original["blocks"]
        assert saved["connections"] == original["connections"]
        # metadata は tool / created_at が更新されうるので比較しない

    def test_migrated_vector_model_runs_through_gain(self) -> None:
        """0.13 では Mux → Gain は shape 不一致で拒否されていたが、0.14 (ADR-0079) では
        Gain が要素ごとにベクトルを処理する。"""
        sim = Simulator.from_dict(migrate_to_current(_model_0_13(_BLOCKS, _CONNS)))
        sim.run()
        values = np.asarray(sim.get_block("sc").values)
        np.testing.assert_allclose(values[0], [3.0, 6.0])
