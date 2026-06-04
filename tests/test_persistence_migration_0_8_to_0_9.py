"""ADR-0058: schema 0.8 → 0.9 migration の単体テスト。

旧 ``pyflw.subsystems.triggered.TriggeredSubsystem`` を新
``pyflw.subsystems.subsystem.Subsystem`` + 内部 ``Trigger`` block に自動変換する。
``_migrated_from`` メタが付与され、frontend / API はこれを見て dirty flag を立てる。
"""

from __future__ import annotations

from pyflw.core.persistence import (
    CURRENT_SCHEMA_VERSION,
    _builtin_migrate_0_8_to_0_9,
    migrate_to_current,
)

# ---------------------------------------------------------------------------
# _builtin_migrate_0_8_to_0_9 単体
# ---------------------------------------------------------------------------


def test_current_schema_version_is_0_9() -> None:
    assert CURRENT_SCHEMA_VERSION == "0.9"


def test_migrate_simple_triggered_subsystem() -> None:
    """旧 TriggeredSubsystem 1 個 → Subsystem + 内部 Trigger block。"""
    data = {
        "schema_version": "0.8",
        "simulator": {},
        "blocks": [
            {
                "id": "ts0",
                "type": "pyflw.subsystems.triggered.TriggeredSubsystem",
                "params": {
                    "trigger_mode": "rising",
                    "blocks": [
                        {
                            "id": "in0",
                            "type": "pyflw.subsystems.ports.Inport",
                            "params": {"port_idx": 0},
                        },
                        {
                            "id": "out0",
                            "type": "pyflw.subsystems.ports.Outport",
                            "params": {"port_idx": 0},
                        },
                    ],
                    "connections": [{"src": "in0", "src_idx": 0, "dst": "out0", "dst_idx": 0}],
                },
            }
        ],
        "connections": [],
    }
    out = _builtin_migrate_0_8_to_0_9(data)
    assert out["schema_version"] == "0.9"
    # type が Subsystem に書き換わる
    entry = out["blocks"][0]
    assert entry["type"] == "pyflw.subsystems.subsystem.Subsystem"
    # trigger_mode は削除される
    assert "trigger_mode" not in entry["params"]
    # 内部 blocks に Trigger が追加される
    inner = entry["params"]["blocks"]
    trigger_entries = [b for b in inner if b["type"] == "pyflw.subsystems.control_blocks.Trigger"]
    assert len(trigger_entries) == 1
    trig = trigger_entries[0]
    # ADR-0058 §論点 6: id は決定的 {parent_id}_trigger
    assert trig["id"] == "ts0_trigger"
    assert trig["params"]["trigger_type"] == "rising"


def test_migrate_trigger_mode_falling() -> None:
    data = {
        "schema_version": "0.8",
        "simulator": {},
        "blocks": [
            {
                "id": "ts1",
                "type": "pyflw.subsystems.triggered.TriggeredSubsystem",
                "params": {"trigger_mode": "falling", "blocks": [], "connections": []},
            }
        ],
        "connections": [],
    }
    out = _builtin_migrate_0_8_to_0_9(data)
    inner = out["blocks"][0]["params"]["blocks"]
    trig = next(b for b in inner if b["type"].endswith(".Trigger"))
    assert trig["params"]["trigger_type"] == "falling"
    assert trig["id"] == "ts1_trigger"


def test_migrate_trigger_id_collision_appends_counter() -> None:
    """``{parent_id}_trigger`` が既に内部にあれば counter 付き id にする。"""
    data = {
        "schema_version": "0.8",
        "simulator": {},
        "blocks": [
            {
                "id": "ts2",
                "type": "pyflw.subsystems.triggered.TriggeredSubsystem",
                "params": {
                    "trigger_mode": "rising",
                    "blocks": [
                        {
                            "id": "ts2_trigger",
                            "type": "pyflw.blocks.sources.Constant",
                            "params": {"value": 1.0},
                        }
                    ],
                    "connections": [],
                },
            }
        ],
        "connections": [],
    }
    out = _builtin_migrate_0_8_to_0_9(data)
    inner = out["blocks"][0]["params"]["blocks"]
    trig_block = next(b for b in inner if b["type"] == "pyflw.subsystems.control_blocks.Trigger")
    # 衝突したので連番 (= ts2_trigger_1)
    assert trig_block["id"] == "ts2_trigger_1"


def test_migrate_nested_triggered_subsystem() -> None:
    """ネスト Subsystem 内部の旧型も再帰的に変換される。"""
    data = {
        "schema_version": "0.8",
        "simulator": {},
        "blocks": [
            {
                "id": "outer",
                "type": "pyflw.subsystems.subsystem.Subsystem",
                "params": {
                    "blocks": [
                        {
                            "id": "inner_ts",
                            "type": "pyflw.subsystems.triggered.TriggeredSubsystem",
                            "params": {
                                "trigger_mode": "either",
                                "blocks": [],
                                "connections": [],
                            },
                        }
                    ],
                    "connections": [],
                },
            }
        ],
        "connections": [],
    }
    out = _builtin_migrate_0_8_to_0_9(data)
    inner_outer = out["blocks"][0]["params"]["blocks"]
    assert inner_outer[0]["type"] == "pyflw.subsystems.subsystem.Subsystem"
    inner_inner = inner_outer[0]["params"]["blocks"]
    trig = next(b for b in inner_inner if b["type"].endswith(".Trigger"))
    assert trig["params"]["trigger_type"] == "either"
    assert trig["id"] == "inner_ts_trigger"


def test_migrate_no_triggered_subsystem_unchanged() -> None:
    """旧型を含まないモデルは migration で blocks の内容が変わらない。"""
    data = {
        "schema_version": "0.8",
        "simulator": {},
        "blocks": [
            {
                "id": "src",
                "type": "pyflw.blocks.sources.Constant",
                "params": {"value": 1.0},
            },
        ],
        "connections": [],
    }
    out = _builtin_migrate_0_8_to_0_9(data)
    assert out["schema_version"] == "0.9"
    assert out["blocks"] == data["blocks"]  # 元の参照と内容一致


# ---------------------------------------------------------------------------
# migrate_to_current 経由 (= chained migration + _migrated_from メタ)
# ---------------------------------------------------------------------------


def test_migrate_to_current_sets_migrated_from() -> None:
    """ADR-0058 §論点 10: 1 段以上 migration したら ``_migrated_from`` メタ付与。"""
    data = {
        "schema_version": "0.8",
        "simulator": {},
        "blocks": [],
        "connections": [],
    }
    out = migrate_to_current(data)
    assert out["schema_version"] == "0.9"
    assert out["_migrated_from"] == "0.8"


def test_migrate_to_current_no_meta_when_already_current() -> None:
    """現バージョンでロードした場合は ``_migrated_from`` メタを付けない。"""
    data = {
        "schema_version": "0.9",
        "simulator": {},
        "blocks": [],
        "connections": [],
    }
    out = migrate_to_current(data)
    assert out["schema_version"] == "0.9"
    assert "_migrated_from" not in out


def test_migrate_to_current_records_oldest_version() -> None:
    """連鎖 migration の場合、``_migrated_from`` には元の最古バージョンが入る。"""
    # 0.7 → 0.8 → 0.9 と 2 段経由する
    data = {
        "schema_version": "0.7",
        "simulator": {},
        "blocks": [],
        "connections": [],
    }
    out = migrate_to_current(data)
    assert out["schema_version"] == "0.9"
    assert out["_migrated_from"] == "0.7"
