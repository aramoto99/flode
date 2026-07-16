"""プロジェクト名変更 (pyflw → flode): schema 0.9 → 0.10 migration の単体テスト。

ブロック型 FQN の ``pyflw.`` prefix を ``flode.`` に書き換え (ネスト Subsystem 含む)、
``metadata.tool`` の ``pyflw`` も ``flode`` に更新する。フィールド構成は不変。

NOTE: fixture の ``pyflw.*`` FQN は schema <=0.9 ファイルの実際の内容を再現する
意図的なリテラル (旧プロジェクト名)。
"""

from __future__ import annotations

from flode.core.persistence import (
    CURRENT_SCHEMA_VERSION,
    _builtin_migrate_0_9_to_0_10,
    migrate_to_current,
)

# ---------------------------------------------------------------------------
# _builtin_migrate_0_9_to_0_10 単体
# ---------------------------------------------------------------------------


def test_current_schema_version_is_0_10() -> None:
    assert CURRENT_SCHEMA_VERSION == "0.10"


def test_migrate_renames_top_level_block_types() -> None:
    """トップレベル blocks の ``pyflw.`` prefix が ``flode.`` に書き換わる。"""
    data = {
        "schema_version": "0.9",
        "simulator": {},
        "blocks": [
            {"id": "src", "type": "pyflw.blocks.sources.Sine", "params": {}},
            {"id": "scope", "type": "pyflw.blocks.sinks.Scope", "params": {}},
        ],
        "connections": [{"src": "src", "src_idx": 0, "dst": "scope", "dst_idx": 0}],
    }
    out = _builtin_migrate_0_9_to_0_10(data)
    assert out["schema_version"] == "0.10"
    assert out["blocks"][0]["type"] == "flode.blocks.sources.Sine"
    assert out["blocks"][1]["type"] == "flode.blocks.sinks.Scope"
    # connections は不変
    assert out["connections"] == data["connections"]


def test_migrate_renames_nested_subsystem_blocks_recursively() -> None:
    """2 段ネストした Subsystem 内部の FQN も再帰的に書き換わる。"""
    data = {
        "schema_version": "0.9",
        "simulator": {},
        "blocks": [
            {
                "id": "outer",
                "type": "pyflw.subsystems.subsystem.Subsystem",
                "params": {
                    "blocks": [
                        {
                            "id": "in0",
                            "type": "pyflw.subsystems.ports.Inport",
                            "params": {"port_idx": 0},
                        },
                        {
                            "id": "inner",
                            "type": "pyflw.subsystems.subsystem.Subsystem",
                            "params": {
                                "blocks": [
                                    {
                                        "id": "gain",
                                        "type": "pyflw.blocks.mathops.Gain",
                                        "params": {"gain": 2.0},
                                    }
                                ],
                                "connections": [],
                            },
                        },
                    ],
                    "connections": [],
                },
            }
        ],
        "connections": [],
    }
    out = _builtin_migrate_0_9_to_0_10(data)
    outer = out["blocks"][0]
    assert outer["type"] == "flode.subsystems.subsystem.Subsystem"
    level1 = outer["params"]["blocks"]
    assert level1[0]["type"] == "flode.subsystems.ports.Inport"
    assert level1[1]["type"] == "flode.subsystems.subsystem.Subsystem"
    level2 = level1[1]["params"]["blocks"]
    assert level2[0]["type"] == "flode.blocks.mathops.Gain"


def test_migrate_keeps_third_party_block_types() -> None:
    """``register_block_module`` で登録するサードパーティ FQN は変更しない。"""
    data = {
        "schema_version": "0.9",
        "simulator": {},
        "blocks": [
            {"id": "ext", "type": "myapp.blocks.MyBlock", "params": {}},
            {"id": "src", "type": "pyflw.blocks.sources.Step", "params": {}},
        ],
        "connections": [],
    }
    out = _builtin_migrate_0_9_to_0_10(data)
    assert out["blocks"][0]["type"] == "myapp.blocks.MyBlock"
    assert out["blocks"][1]["type"] == "flode.blocks.sources.Step"


def test_migrate_updates_metadata_tool() -> None:
    """``metadata.tool`` の ``pyflw x.y.z`` が ``flode x.y.z`` になる。"""
    data = {
        "schema_version": "0.9",
        "simulator": {},
        "blocks": [],
        "connections": [],
        "metadata": {"tool": "pyflw 0.42.0", "created_at": "2026-01-01T00:00:00"},
    }
    out = _builtin_migrate_0_9_to_0_10(data)
    assert out["metadata"]["tool"] == "flode 0.42.0"
    # tool 以外の metadata フィールドは保持
    assert out["metadata"]["created_at"] == "2026-01-01T00:00:00"


def test_migrate_tolerates_missing_or_malformed_metadata() -> None:
    """metadata 欠落 / tool 非 str / blocks 欠落でも例外を出さない。"""
    for data in (
        {"schema_version": "0.9", "simulator": {}, "blocks": [], "connections": []},
        {
            "schema_version": "0.9",
            "simulator": {},
            "blocks": [],
            "connections": [],
            "metadata": {"tool": 123},
        },
        {"schema_version": "0.9", "simulator": {}, "connections": []},
        {
            "schema_version": "0.9",
            "simulator": {},
            "blocks": [{"id": "x"}, "not-a-dict", {"id": "y", "type": 42}],
            "connections": [],
        },
    ):
        out = _builtin_migrate_0_9_to_0_10(data)
        assert out["schema_version"] == "0.10"


def test_migrate_does_not_mutate_input_top_level() -> None:
    """入力 dict の top-level は copy され、schema_version が書き換わらない。"""
    data = {
        "schema_version": "0.9",
        "simulator": {},
        "blocks": [],
        "connections": [],
        "metadata": {"tool": "pyflw 0.42.0"},
    }
    out = _builtin_migrate_0_9_to_0_10(data)
    assert data["schema_version"] == "0.9"
    assert data["metadata"]["tool"] == "pyflw 0.42.0"
    assert out is not data


# ---------------------------------------------------------------------------
# migrate_to_current 経由 (= chained migration)
# ---------------------------------------------------------------------------


def test_chain_from_0_8_converts_triggered_subsystem_to_flode() -> None:
    """0.8 の TriggeredSubsystem 入りモデルが 0.8 → 0.9 → 0.10 のチェーンで
    最終的に flode FQN の Subsystem + Trigger になる。"""
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
                        }
                    ],
                    "connections": [],
                },
            }
        ],
        "connections": [],
        "metadata": {"tool": "pyflw 0.37.0"},
    }
    out = migrate_to_current(data)
    assert out["schema_version"] == "0.10"
    assert out["_migrated_from"] == "0.8"
    entry = out["blocks"][0]
    assert entry["type"] == "flode.subsystems.subsystem.Subsystem"
    inner = entry["params"]["blocks"]
    assert inner[0]["type"] == "flode.subsystems.ports.Inport"
    trig = next(b for b in inner if b["type"].endswith(".Trigger"))
    assert trig["type"] == "flode.subsystems.control_blocks.Trigger"
    assert trig["params"]["trigger_type"] == "rising"
    assert out["metadata"]["tool"] == "flode 0.37.0"


def test_chain_from_oldest_version_reaches_current() -> None:
    """最古の 0.1 からでも migration チェーンが 0.10 まで到達する。"""
    data = {
        "schema_version": "0.1",
        "simulator": {},
        "blocks": [],
        "connections": [],
    }
    out = migrate_to_current(data)
    assert out["schema_version"] == "0.10"
    assert out["_migrated_from"] == "0.1"
