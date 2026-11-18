"""``strip_gui_only_scope_keys`` の単体テスト (GUI 専用のスコープキーを全階層から外す)。"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from flode.core.persistence import GUI_ONLY_SCOPE_KEYS, strip_gui_only_scope_keys


def _subsystem(params: dict[str, Any]) -> dict[str, Any]:
    return {"id": "s", "type": "flode.subsystems.subsystem.Subsystem", "params": params}


def test_removes_keys_at_top_level_and_nested_subsystems() -> None:
    inner = _subsystem({"blocks": [], "connections": [], "branch_waypoints": {"a:0": []}})
    outer = _subsystem({"blocks": [inner], "connections": [], "branch_waypoints": {"s:0": []}})
    model = {"blocks": [outer], "connections": [], "branch_waypoints": {"x:0": []}}

    out = strip_gui_only_scope_keys(model)

    assert "branch_waypoints" not in out
    outer_params = out["blocks"][0]["params"]
    assert "branch_waypoints" not in outer_params
    assert "branch_waypoints" not in outer_params["blocks"][0]["params"]


def test_does_not_mutate_input() -> None:
    model = {
        "blocks": [_subsystem({"blocks": [], "branch_waypoints": {"a:0": []}})],
        "branch_waypoints": {"x:0": []},
    }
    before = copy.deepcopy(model)

    strip_gui_only_scope_keys(model)

    assert model == before


def test_keeps_other_keys_and_ordinary_block_params() -> None:
    gain = {"id": "g", "type": "flode.blocks.mathops.Gain", "params": {"k": 2.0}}
    model = {"blocks": [gain], "connections": [{"src": "g"}], "layout": {"g": {}}}

    out = strip_gui_only_scope_keys(model)

    assert out == model


@pytest.mark.parametrize("value", [None, 1, "text", [1, 2]])
def test_non_dict_input_is_returned_unchanged(value: Any) -> None:
    assert strip_gui_only_scope_keys(value) is value


@pytest.mark.parametrize(
    "entry",
    [
        "not-a-dict",
        {"id": "b", "type": "T"},
        {"id": "b", "type": "T", "params": "not-a-dict"},
        {"id": "b", "type": "T", "params": {"blocks": "not-a-list", "branch_waypoints": {}}},
    ],
    ids=["entry-not-dict", "no-params", "params-not-dict", "blocks-not-list"],
)
def test_non_subsystem_or_malformed_entries_pass_through(entry: Any) -> None:
    """Subsystem と判定できない entry はそのまま残す (壊れた Subsystem は構築側でエラーになる)。"""
    out = strip_gui_only_scope_keys({"blocks": [entry]})

    assert out["blocks"][0] is entry


def test_blocks_not_list_at_top_level_is_left_as_is() -> None:
    out = strip_gui_only_scope_keys({"blocks": "broken", "branch_waypoints": {}})

    assert out == {"blocks": "broken"}


def test_branch_waypoints_is_a_gui_only_key() -> None:
    assert "branch_waypoints" in GUI_ONLY_SCOPE_KEYS
