"""``export_subsystem_to_library`` の round-trip テスト (ADR-0029)。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pytest_mock import MockerFixture

from flode import Inport, Library, LibraryFileError, Outport, Subsystem, load_library
from flode.blocks.mathops import Gain
from flode.core.persistence import CURRENT_SCHEMA_VERSION
from flode.exceptions import LibraryWriteBusyError
from flode.libraries import (
    CURRENT_LIBRARY_SCHEMA_VERSION,
    export_subsystem_to_library,
    library_to_dict,
)


def _build_simple_subsystem() -> Subsystem:
    """1 入力 1 出力の最小 Subsystem (Gain=2.0、マスクなし)。"""
    sub = Subsystem()
    inp = sub.add(Inport(port_idx=0))
    g = sub.add(Gain(k=2.0))
    out = sub.add(Outport(port_idx=0))
    sub.connect(inp, g)
    sub.connect(g, out)
    return sub


def test_export_subsystem_to_library_creates_new(tmp_path: Path) -> None:
    """新規 .flwlib.json を作成して entry を書き出す。"""
    sub = _build_simple_subsystem()
    out_path = tmp_path / "my.flwlib.json"
    library = export_subsystem_to_library(
        sub,
        out_path,
        library_metadata={
            "name": "myproj",
            "display_name": "My Project",
            "description": "Test library",
        },
        entry_metadata={
            "id": "double_gain",
            "display_name": "Double Gain",
            "description": "y = 2 * u",
        },
        append=False,
    )
    assert library.name == "myproj"
    assert len(library.entries) == 1
    assert out_path.exists()
    # ファイルから再読み込みして内容が一致するか
    reloaded = load_library(out_path)
    assert reloaded.name == "myproj"
    assert reloaded.entries[0].id == "double_gain"
    # subsystem body が再構築可能 (= byte-identical round-trip)
    rebuilt = Subsystem._from_dict(**reloaded.entries[0].block["params"])
    assert rebuilt.n_inputs == 1
    assert rebuilt.n_outputs == 1


def test_export_subsystem_to_library_append(tmp_path: Path) -> None:
    """既存 library に entry 追加 (append=True)。"""
    out_path = tmp_path / "lib.flwlib.json"
    sub1 = _build_simple_subsystem()
    sub2 = _build_simple_subsystem()
    export_subsystem_to_library(
        sub1,
        out_path,
        library_metadata={"name": "lib"},
        entry_metadata={"id": "e1", "display_name": "Entry 1"},
        append=False,
    )
    library = export_subsystem_to_library(
        sub2,
        out_path,
        entry_metadata={"id": "e2", "display_name": "Entry 2"},
        append=True,
    )
    assert [e.id for e in library.entries] == ["e1", "e2"]


def test_export_subsystem_rejects_duplicate_id(tmp_path: Path) -> None:
    """append 時に同じ entry id が既に存在すると ``LibraryFileError``。"""
    out_path = tmp_path / "lib.flwlib.json"
    sub = _build_simple_subsystem()
    export_subsystem_to_library(
        sub,
        out_path,
        library_metadata={"name": "lib"},
        entry_metadata={"id": "e1", "display_name": "Entry 1"},
        append=False,
    )
    with pytest.raises(LibraryFileError, match="already has entry"):
        export_subsystem_to_library(
            sub,
            out_path,
            entry_metadata={"id": "e1", "display_name": "Entry Again"},
            append=True,
        )


def test_export_round_trip_byte_identical(tmp_path: Path) -> None:
    """``Subsystem.to_dict()`` と export 後の ``subsystem`` body が一致する。

    マスク Subsystem の placeholder + mask_values が変わらず保たれることを確認。
    """
    sub = Subsystem(
        mask_params=[
            {"name": "K", "type": "float", "default": 3.0, "description": ""},
        ],
    )
    inp = sub.add(Inport(port_idx=0))
    out = sub.add(Outport(port_idx=0))
    sub.connect(inp, out)
    expected = sub.to_dict()
    out_path = tmp_path / "round.flwlib.json"
    library = export_subsystem_to_library(
        sub,
        out_path,
        library_metadata={"name": "round"},
        entry_metadata={"id": "x", "display_name": "X"},
        append=False,
    )
    reloaded = load_library(out_path)
    assert reloaded.entries[0].block == library.entries[0].block
    assert reloaded.entries[0].block == expected


# ----------------------------------------------------------------------------
# ADR-0080: v4 出力・アトミック書き込み
# ----------------------------------------------------------------------------


def _export(sub: Subsystem, path: Path, entry_id: str, **kwargs: Any) -> Library:
    return export_subsystem_to_library(
        sub,
        path,
        entry_metadata={"id": entry_id, "display_name": entry_id.title()},
        **kwargs,
    )


def test_export_writes_v4_format(tmp_path: Path) -> None:
    """書き出しは v4 (``block`` / ``revision`` / ``updated_at`` / ``model_schema_version``)。"""
    out_path = tmp_path / "lib.flwlib.json"
    library = _export(
        _build_simple_subsystem(), out_path, "e1", library_metadata={"name": "lib"}, append=False
    )
    raw = json.loads(out_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == CURRENT_LIBRARY_SCHEMA_VERSION == "libraries.v4"
    assert raw["model_schema_version"] == CURRENT_SCHEMA_VERSION
    assert "uid" not in raw
    entry = raw["entries"][0]
    assert "subsystem" not in entry
    assert entry["block"] == library.entries[0].block
    assert entry["revision"] == 1
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", entry["updated_at"])
    # 導出値 (kind / contains_python 等) は保存しない (ADR-0080 §A1-2)
    assert set(entry) == {"id", "display_name", "revision", "updated_at", "block"}
    assert library.entries[0].updated_at == entry["updated_at"]
    assert library.model_schema_version == CURRENT_SCHEMA_VERSION


def test_export_round_trips_v4_fields(tmp_path: Path) -> None:
    """v4 round-trip: 書いた内容を読み直して同じ dict に戻る。"""
    out_path = tmp_path / "lib.flwlib.json"
    _export(
        _build_simple_subsystem(),
        out_path,
        "e1",
        library_metadata={"name": "lib", "uid": "11111111-2222-4333-8444-555555555555"},
        append=False,
    )
    raw = json.loads(out_path.read_text(encoding="utf-8"))
    reloaded = load_library(out_path)
    assert reloaded.uid == "11111111-2222-4333-8444-555555555555"
    assert library_to_dict(reloaded) == raw


def test_export_append_preserves_uid_and_existing_entries(tmp_path: Path) -> None:
    out_path = tmp_path / "lib.flwlib.json"
    _export(
        _build_simple_subsystem(),
        out_path,
        "e1",
        library_metadata={"name": "lib", "uid": "uid-1"},
        append=False,
    )
    first = json.loads(out_path.read_text(encoding="utf-8"))["entries"][0]
    library = _export(_build_simple_subsystem(), out_path, "e2")
    assert library.uid == "uid-1"
    raw = json.loads(out_path.read_text(encoding="utf-8"))
    assert raw["uid"] == "uid-1"
    assert raw["entries"][0] == first  # 既存エントリは revision / updated_at ごと保持


def test_export_append_to_v3_file_upgrades_to_v4_and_keeps_bak(tmp_path: Path) -> None:
    """v3 ファイルへの追記は v4 で書き戻し、直前の内容を ``.bak`` に残す。"""
    out_path = tmp_path / "old.flwlib.json"
    v3 = {
        "schema_version": "libraries.v3",
        "name": "old",
        "display_name": "Old",
        "entries": [
            {
                "id": "legacy",
                "display_name": "Legacy",
                "subsystem": _build_simple_subsystem().to_dict(),
            }
        ],
    }
    original_bytes = json.dumps(v3).encode("utf-8")
    out_path.write_bytes(original_bytes)
    _export(_build_simple_subsystem(), out_path, "added")
    raw = json.loads(out_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == "libraries.v4"
    assert [e["id"] for e in raw["entries"]] == ["legacy", "added"]
    assert raw["entries"][0]["revision"] == 1
    assert "updated_at" not in raw["entries"][0]  # 実時刻を捏造しない
    backup = out_path.with_name(out_path.name + ".bak")
    assert backup.read_bytes() == original_bytes
    assert sorted(f.name for f in tmp_path.iterdir()) == [out_path.name, backup.name]


def test_export_output_is_lf_terminated_utf8(tmp_path: Path) -> None:
    out_path = tmp_path / "lib.flwlib.json"
    _export(
        _build_simple_subsystem(),
        out_path,
        "e1",
        library_metadata={"name": "lib", "display_name": "ライブラリ"},
        append=False,
    )
    data = out_path.read_bytes()
    assert data.endswith(b"\n")
    assert b"\r\n" not in data
    assert "ライブラリ".encode() in data  # ensure_ascii=False


def test_export_busy_file_raises_library_file_error(tmp_path: Path, mocker: MockerFixture) -> None:
    """置換が再試行後も失敗したら ``LibraryWriteBusyError`` (``LibraryFileError`` 派生)。"""
    from flode.libraries import _atomic

    mocker.patch.object(_atomic, "_RETRY_PERMISSION_ERRORS", True)
    mocker.patch.object(_atomic.time, "sleep")
    mocker.patch.object(_atomic.os, "replace", side_effect=PermissionError("locked"))
    out_path = tmp_path / "lib.flwlib.json"
    with pytest.raises(LibraryWriteBusyError) as excinfo:
        _export(
            _build_simple_subsystem(),
            out_path,
            "e1",
            library_metadata={"name": "lib"},
            append=False,
        )
    assert isinstance(excinfo.value, LibraryFileError)
    assert list(tmp_path.iterdir()) == []
