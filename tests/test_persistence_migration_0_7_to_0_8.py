"""ADR-0039: schema 0.7 → 0.8 migration テスト。

旧 v1 形式 (= ``n_inputs`` / ``n_outputs`` / ``port_shapes_*`` フィールド付き) の
モデルを load した時、migration が自動で派生フィールドを除去し、内部 Inport /
Outport から port count が復元されることを検証する。
"""

from __future__ import annotations

import logging

import pytest

from pyflw.core.persistence import (
    CURRENT_SCHEMA_VERSION,
    _builtin_migrate_0_7_to_0_8,
    migrate_to_current,
)


def _make_old_subsystem_entry(*, n_inputs: int, n_outputs: int) -> dict:
    inner_blocks = []
    for i in range(n_inputs):
        inner_blocks.append(
            {
                "id": f"in{i}",
                "type": "pyflw.subsystems.ports.Inport",
                "params": {"port_idx": i},
            }
        )
    for j in range(n_outputs):
        inner_blocks.append(
            {
                "id": f"out{j}",
                "type": "pyflw.subsystems.ports.Outport",
                "params": {"port_idx": j},
            }
        )
    return {
        "id": "sub",
        "type": "pyflw.subsystems.subsystem.Subsystem",
        "params": {
            "n_inputs": n_inputs,
            "n_outputs": n_outputs,
            "port_shapes_in": [[]] * n_inputs,
            "port_shapes_out": [[]] * n_outputs,
            "blocks": inner_blocks,
            "connections": [],
        },
    }


def _make_old_model(blocks: list) -> dict:
    return {
        "schema_version": "0.7",
        "simulator": {"t_end": 1, "dt": 0.01, "solver": "RK45"},
        "blocks": blocks,
        "connections": [],
    }


def test_current_schema_version_is_0_8() -> None:
    assert CURRENT_SCHEMA_VERSION == "0.8"


def test_migrate_0_7_to_0_8_removes_n_inputs_n_outputs() -> None:
    old = _make_old_model([_make_old_subsystem_entry(n_inputs=2, n_outputs=1)])
    new = _builtin_migrate_0_7_to_0_8(old)
    assert new["schema_version"] == "0.8"
    sub_params = new["blocks"][0]["params"]
    assert "n_inputs" not in sub_params
    assert "n_outputs" not in sub_params
    assert "port_shapes_in" not in sub_params
    assert "port_shapes_out" not in sub_params
    # 内部 blocks は維持
    assert len(sub_params["blocks"]) == 3  # 2 Inport + 1 Outport


def test_migrate_to_current_runs_0_7_to_0_8() -> None:
    old = _make_old_model([_make_old_subsystem_entry(n_inputs=1, n_outputs=1)])
    new = migrate_to_current(old)
    assert new["schema_version"] == CURRENT_SCHEMA_VERSION
    assert "n_inputs" not in new["blocks"][0]["params"]


def test_migrate_warns_on_count_mismatch(caplog: pytest.LogCaptureFixture) -> None:
    # n_inputs=5 と宣言されているが内部 Inport は 1 つしかない (= corrupt)
    sub = _make_old_subsystem_entry(n_inputs=1, n_outputs=0)
    sub["params"]["n_inputs"] = 5  # 嘘の値で上書き
    old = _make_old_model([sub])
    with caplog.at_level(logging.WARNING, logger="pyflw.persistence.migrate_0_7_to_0_8"):
        _builtin_migrate_0_7_to_0_8(old)
    assert any("does not match inner Inport" in r.message for r in caplog.records)


def test_migrate_recurses_into_nested_subsystem() -> None:
    inner = _make_old_subsystem_entry(n_inputs=1, n_outputs=1)
    inner["id"] = "inner"
    outer = {
        "id": "outer",
        "type": "pyflw.subsystems.subsystem.Subsystem",
        "params": {
            "n_inputs": 0,
            "n_outputs": 0,
            "blocks": [inner],
            "connections": [],
        },
    }
    old = _make_old_model([outer])
    new = _builtin_migrate_0_7_to_0_8(old)
    # 外側
    assert "n_inputs" not in new["blocks"][0]["params"]
    # 内側 (= 再帰削除)
    inner_after = new["blocks"][0]["params"]["blocks"][0]
    assert "n_inputs" not in inner_after["params"]
    assert "n_outputs" not in inner_after["params"]


def test_triggered_subsystem_count_includes_trigger() -> None:
    """ADR-0036 §(2): TriggeredSubsystem の n_inputs = 内部 Inport + 1。
    migration 時の不一致判定もこれを考慮する。"""
    inner_blocks = [
        {"id": "in0", "type": "pyflw.subsystems.ports.Inport", "params": {"port_idx": 0}},
    ]
    triggered_entry = {
        "id": "tsub",
        "type": "pyflw.subsystems.triggered.TriggeredSubsystem",
        "params": {
            "n_inputs": 2,  # 内部 Inport 1 + trigger 1 = 2 (= 一致、warning なし)
            "n_outputs": 0,
            "trigger_mode": "rising",
            "blocks": inner_blocks,
            "connections": [],
        },
    }
    old = _make_old_model([triggered_entry])
    new = _builtin_migrate_0_7_to_0_8(old)
    assert "n_inputs" not in new["blocks"][0]["params"]
    # trigger_mode は維持
    assert new["blocks"][0]["params"]["trigger_mode"] == "rising"
