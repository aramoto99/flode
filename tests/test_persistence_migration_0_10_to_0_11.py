"""SM-D Stage 1 (SPEC-0028): schema 0.10 → 0.11 migration の単体テスト。

0.11 は `Cast` / `Constant` への ``dtype`` param 追加に伴う **no-op bump**
(旧ファイルは ``dtype`` キーを持たない = ``"auto"`` = 従来挙動)。
"""

from __future__ import annotations

import json
from pathlib import Path

from flode import Simulator
from flode.blocks.cast import Cast
from flode.blocks.sources import Constant
from flode.core.persistence import (
    _builtin_migrate_0_10_to_0_11,
    migrate_to_current,
)

# CURRENT_SCHEMA_VERSION の pin は test_persistence_migration_0_11_to_0_12.py に移動


def test_migrate_is_noop_except_version() -> None:
    data = {
        "schema_version": "0.10",
        "simulator": {"t_end": 1.0, "dt": 0.01},
        "blocks": [{"id": "c", "type": "flode.blocks.sources.Constant", "params": {"value": 1.0}}],
        "connections": [],
    }
    out = _builtin_migrate_0_10_to_0_11(data)
    assert out["schema_version"] == "0.11"
    assert out["blocks"] == data["blocks"]
    assert out["connections"] == data["connections"]
    assert out["simulator"] == data["simulator"]


def test_migrate_does_not_mutate_input() -> None:
    data = {"schema_version": "0.10", "blocks": [], "connections": []}
    _builtin_migrate_0_10_to_0_11(data)
    assert data["schema_version"] == "0.10"


def test_chain_from_0_10_reaches_current() -> None:
    data = {"schema_version": "0.10", "simulator": {}, "blocks": [], "connections": []}
    out = migrate_to_current(data)
    assert out["schema_version"] == "0.14"
    assert out["_migrated_from"] == "0.10"


def test_0_10_file_loads_and_runs_as_before(tmp_path: Path) -> None:
    # AC-6: dtype キーが無い旧ファイル = 全ブロック "auto" = 従来挙動
    model = {
        "schema_version": "0.10",
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
                "id": "c",
                "type": "flode.blocks.sources.Constant",
                "params": {"value": 1.5, "output_type": "float"},
            }
        ],
        "connections": [],
    }
    path = tmp_path / "old.flw.json"
    path.write_text(json.dumps(model), encoding="utf-8")
    sim = Simulator.load(path)
    blk = sim.get_block("c")
    assert getattr(blk, "dtype", "auto") == "auto"
    sim.run()  # 従来どおり実行できる


def test_dtype_param_round_trips(tmp_path: Path) -> None:
    sim = Simulator(t_end=0.05, dt=0.01)
    sim.add(Constant(value=2.7, dtype="int32", id="c"))
    sim.add(Cast(dtype="bool", id="k"))
    path = tmp_path / "m.flw.json"
    sim.save(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == "0.14"
    params_by_id = {b["id"]: b["params"] for b in data["blocks"]}
    assert params_by_id["c"]["dtype"] == "int32"
    assert params_by_id["k"]["dtype"] == "bool"

    loaded = Simulator.load(path)
    assert loaded.get_block("c").dtype == "int32"  # type: ignore[attr-defined]
    assert loaded.get_block("k").dtype == "bool"  # type: ignore[attr-defined]


def test_auto_dtype_is_not_serialized(tmp_path: Path) -> None:
    # Q1: Constant の "auto" は JSON に出さない (既存モデルの diff 最小化)。
    # Cast は v0.56.0 から常に宣言ブロックのため dtype が必ず出る。
    sim = Simulator(t_end=0.05, dt=0.01)
    sim.add(Constant(value=1.0, id="c"))
    sim.add(Cast(id="k"))
    path = tmp_path / "m.flw.json"
    sim.save(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    params_by_id = {b["id"]: b["params"] for b in data["blocks"]}
    assert "dtype" not in params_by_id["c"]
    assert params_by_id["k"]["dtype"] == "float64"


def test_0_10_round_trip_diff_is_schema_version_only(tmp_path: Path) -> None:
    # AC-6: 0.10 ファイルを load → save したとき、変わるのは schema_version のみ
    sim = Simulator(t_end=0.05, dt=0.01)
    sim.add(Constant(value=1.0, id="c"))
    path = tmp_path / "m.flw.json"
    sim.save(path)
    text_current = path.read_text(encoding="utf-8")
    # 0.10 相当のファイルを作る (schema_version を書き戻すだけ)
    path.write_text(
        text_current.replace('"schema_version": "0.14"', '"schema_version": "0.10"'),
        encoding="utf-8",
    )
    loaded = Simulator.load(path)
    out_path = tmp_path / "resaved.flw.json"
    loaded.save(out_path)
    resaved = json.loads(out_path.read_text(encoding="utf-8"))
    original = json.loads(text_current)
    # metadata (created_at) はタイムスタンプなので除外して比較
    resaved.pop("metadata", None)
    original.pop("metadata", None)
    assert resaved == original
