"""エントリ本体の Goto / From 閉包検査のテスト (ADR-0080 §A4-5)。"""

from __future__ import annotations

from typing import Any

from flode.libraries import GotoFromViolation, find_goto_from_violations

SUBSYSTEM_TYPE = "flode.subsystems.subsystem.Subsystem"
GOTO_TYPE = "flode.blocks.routing.Goto"
FROM_TYPE = "flode.blocks.routing.From"


def _goto(block_id: str, tag: str, visibility: str | None = "local") -> dict[str, Any]:
    params: dict[str, Any] = {"tag": tag}
    if visibility is not None:
        params["tag_visibility"] = visibility
    return {"id": block_id, "type": GOTO_TYPE, "params": params}


def _from(block_id: str, tag: str) -> dict[str, Any]:
    return {"id": block_id, "type": FROM_TYPE, "params": {"tag": tag}}


def _subsystem(block_id: str | None, blocks: list[Any]) -> dict[str, Any]:
    return {"id": block_id, "type": SUBSYSTEM_TYPE, "params": {"blocks": blocks, "connections": []}}


def test_local_goto_and_from_in_same_scope_are_closed() -> None:
    body = _subsystem("top", [_goto("g", "A"), _from("f", "A")])
    assert find_goto_from_violations(body) == []


def test_missing_tag_visibility_defaults_to_local() -> None:
    body = _subsystem("top", [_goto("g", "A", visibility=None), _from("f", "A")])
    assert find_goto_from_violations(body) == []


def test_from_without_goto_is_reported_with_path_and_tag() -> None:
    body = _subsystem("top", [_subsystem("inner", [_from("f", "A")])])
    assert find_goto_from_violations(body) == [
        GotoFromViolation(path="inner/f", tag="A", reason="unresolved_from")
    ]


def test_local_goto_in_another_scope_does_not_resolve_from() -> None:
    """Local は同一スコープのみ: 親の Goto は子の From を解決しない (逆も同じ)。"""
    body = _subsystem("top", [_goto("g", "A"), _subsystem("inner", [_from("f", "A")])])
    assert find_goto_from_violations(body) == [
        GotoFromViolation(path="inner/f", tag="A", reason="unresolved_from")
    ]
    body = _subsystem("top", [_from("f", "A"), _subsystem("inner", [_goto("g", "A")])])
    assert find_goto_from_violations(body) == [
        GotoFromViolation(path="f", tag="A", reason="unresolved_from")
    ]


def test_global_goto_is_rejected_even_when_from_is_inside() -> None:
    """Global Goto は 2 個置くと tag が重複するので、部分木内で閉じていても拒否する。"""
    body = _subsystem(
        "top", [_subsystem("a", [_goto("g", "A", "global")]), _subsystem("b", [_from("f", "A")])]
    )
    assert find_goto_from_violations(body) == [
        GotoFromViolation(path="a/g", tag="A", reason="global_goto"),
        GotoFromViolation(path="b/f", tag="A", reason="unresolved_from"),
    ]


def test_body_without_inner_blocks_has_no_violations() -> None:
    body = {
        "id": "pf",
        "type": "flode.blocks.pythonfunc.PythonFunction",
        "params": {"code": "", "user_params": {}},
    }
    assert find_goto_from_violations(body) == []


def test_duplicate_local_goto_tag_in_one_scope_is_reported() -> None:
    """同一スコープに同じ tag の Local Goto が 2 つあるとモデルを build できない。"""
    body = _subsystem(
        "top", [_goto("g1", "A"), _goto("g2", "A"), _goto("g3", "A"), _from("f", "A")]
    )
    assert find_goto_from_violations(body) == [
        GotoFromViolation(path="g2", tag="A", reason="duplicate_goto"),
        GotoFromViolation(path="g3", tag="A", reason="duplicate_goto"),
    ]


def test_same_local_tag_in_different_scopes_is_fine() -> None:
    inner = _subsystem("inner", [_goto("g", "A"), _from("f", "A")])
    body = _subsystem("top", [_goto("g", "A"), _from("f", "A"), inner])
    assert find_goto_from_violations(body) == []


def test_malformed_blocks_are_skipped() -> None:
    body = _subsystem("top", ["not a block", {"id": "x"}, {"id": "y", "type": 3, "params": 4}])
    assert find_goto_from_violations(body) == []
