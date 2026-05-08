"""``export_subsystem_to_library`` の round-trip テスト (ADR-0029)。"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyflw import Inport, LibraryFileError, Outport, Subsystem, load_library
from pyflw.blocks.mathops import Gain
from pyflw.libraries import export_subsystem_to_library


def _build_simple_subsystem() -> Subsystem:
    """1 入力 1 出力の最小 Subsystem (Gain=2.0、マスクなし)。"""
    sub = Subsystem(n_inputs=1, n_outputs=1)
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
    rebuilt = Subsystem._from_dict(**reloaded.entries[0].subsystem["params"])
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
        n_inputs=1,
        n_outputs=1,
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
    assert reloaded.entries[0].subsystem == library.entries[0].subsystem
    assert reloaded.entries[0].subsystem == expected
