"""ライブラリ書き込み API のテストで共有するブロック本体・ライブラリ dict のビルダー。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flode.libraries import CURRENT_LIBRARY_SCHEMA_VERSION

SUBSYSTEM_TYPE = "flode.subsystems.subsystem.Subsystem"
PYTHON_FUNCTION_TYPE = "flode.blocks.pythonfunc.PythonFunction"
GAIN_TYPE = "flode.blocks.mathops.Gain"
GOTO_TYPE = "flode.blocks.routing.Goto"
FROM_TYPE = "flode.blocks.routing.From"
INPORT_TYPE = "flode.subsystems.ports.Inport"
OUTPORT_TYPE = "flode.subsystems.ports.Outport"

PASSTHROUGH_CODE = "@block\ndef passthrough(t: float, u: float) -> float:\n    return u\n"


def wire(src: str, dst: str) -> dict[str, Any]:
    return {"src": src, "src_idx": 0, "dst": dst, "dst_idx": 0}


def subsystem_body(
    inner: list[dict[str, Any]] | None = None, *, block_id: str | None = "Sub"
) -> dict[str, Any]:
    """``Inport → (inner の直列) → Outport`` の Subsystem 本体を返す。"""
    chain = [
        {"id": "Inport_0", "type": INPORT_TYPE, "params": {"port_idx": 0}},
        *(inner or []),
        {"id": "Outport_0", "type": OUTPORT_TYPE, "params": {"port_idx": 0}},
    ]
    connections = [wire(a["id"], b["id"]) for a, b in zip(chain, chain[1:], strict=False)]
    return {
        "id": block_id,
        "type": SUBSYSTEM_TYPE,
        "params": {"blocks": chain, "connections": connections},
    }


def gain_block(block_id: str = "gain", k: float = 2.0) -> dict[str, Any]:
    return {"id": block_id, "type": GAIN_TYPE, "params": {"k": k}}


def python_function_body(
    code: str = PASSTHROUGH_CODE, *, block_id: str | None = "pf"
) -> dict[str, Any]:
    return {
        "id": block_id,
        "type": PYTHON_FUNCTION_TYPE,
        "params": {"code": code, "user_params": {}},
    }


def sentinel_code(sentinel: Path) -> str:
    """モジュールレベルに副作用 (センチネルファイル作成) を持つ PythonFunction ソース。"""
    return (
        "import pathlib\n"
        f"pathlib.Path({str(sentinel)!r}).write_text('executed')\n"
        "@block\n"
        "def leaky(t: float, u: float) -> float:\n"
        "    return u\n"
    )


def library_dict(name: str, entries: dict[str, dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    """最小の有効な v4 ``.flwlib.json`` dict を返す (``entries`` は id → 本体)。"""
    data: dict[str, Any] = {
        "schema_version": CURRENT_LIBRARY_SCHEMA_VERSION,
        "name": name,
        "display_name": name.title(),
        "entries": [
            {"id": entry_id, "display_name": entry_id.title(), "block": body}
            for entry_id, body in entries.items()
        ],
    }
    data.update(overrides)
    return data


def legacy_v3_library_dict(name: str, entries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """v3 形式 (本体フィールドが ``subsystem``、revision 無し) の dict を返す。"""
    return {
        "schema_version": "libraries.v3",
        "name": name,
        "display_name": name.title(),
        "entries": [
            {"id": entry_id, "display_name": entry_id.title(), "subsystem": body}
            for entry_id, body in entries.items()
        ],
    }
