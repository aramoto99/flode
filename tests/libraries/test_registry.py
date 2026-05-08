"""Library registry build のテスト (ADR-0029)。"""

from __future__ import annotations

import json
from pathlib import Path

from pyflw.libraries._loader import CURRENT_LIBRARY_SCHEMA_VERSION
from pyflw.server.library_registry import build_library_registry


def _write_minimal_library(path: Path, name: str) -> None:
    data = {
        "schema_version": CURRENT_LIBRARY_SCHEMA_VERSION,
        "name": name,
        "display_name": name.title(),
        "entries": [
            {
                "id": "ent",
                "display_name": "Entry",
                "subsystem": {
                    "id": None,
                    "type": "pyflw.subsystems.subsystem.Subsystem",
                    "params": {
                        "n_inputs": 1,
                        "n_outputs": 1,
                        "blocks": [
                            {
                                "id": "Inport_0",
                                "type": "pyflw.subsystems.ports.Inport",
                                "params": {"port_idx": 0},
                            },
                            {
                                "id": "Outport_0",
                                "type": "pyflw.subsystems.ports.Outport",
                                "params": {"port_idx": 0},
                            },
                        ],
                        "connections": [
                            {
                                "src": "Inport_0",
                                "src_idx": 0,
                                "dst": "Outport_0",
                                "dst_idx": 0,
                            }
                        ],
                    },
                },
            }
        ],
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def test_build_library_registry_with_paths(tmp_path: Path) -> None:
    """``library_paths`` で指定した複数ファイルが load される。"""
    a = tmp_path / "a.flwlib.json"
    b = tmp_path / "b.flwlib.json"
    _write_minimal_library(a, "alpha")
    _write_minimal_library(b, "beta")
    reg = build_library_registry([a, b], bundle_builtin=False)
    assert set(reg.libraries.keys()) == {"alpha", "beta"}
    assert reg.load_errors == []


def test_build_library_registry_handles_invalid_file(tmp_path: Path) -> None:
    """1 ファイルが不正でも他は継続、``load_errors`` に記録される。"""
    good = tmp_path / "good.flwlib.json"
    bad = tmp_path / "bad.flwlib.json"
    _write_minimal_library(good, "good")
    bad.write_text("{not json}", encoding="utf-8")
    reg = build_library_registry([good, bad], bundle_builtin=False)
    assert "good" in reg.libraries
    assert len(reg.load_errors) == 1
    assert "bad.flwlib.json" in reg.load_errors[0].path


def test_bundle_builtin_libraries() -> None:
    """``bundle_builtin=True`` で組み込み ``std`` が自動追加される。"""
    reg = build_library_registry([], bundle_builtin=True)
    assert "std" in reg.libraries
    std = reg.libraries["std"]
    ids = [e.id for e in std.entries]
    assert ids == ["pid_controller", "first_order_plant", "second_order_plant"]


def test_directory_path_recursive_search(tmp_path: Path) -> None:
    """``library_paths`` にディレクトリを渡すと再帰検索される。"""
    sub = tmp_path / "sub"
    sub.mkdir()
    f = sub / "nested.flwlib.json"
    _write_minimal_library(f, "nested")
    reg = build_library_registry([tmp_path], bundle_builtin=False)
    assert "nested" in reg.libraries


def test_duplicate_library_name_first_wins(tmp_path: Path) -> None:
    """同名 library の重複は先勝ち + ``load_errors`` に記録。"""
    a = tmp_path / "a.flwlib.json"
    b = tmp_path / "b.flwlib.json"
    _write_minimal_library(a, "same_name")
    _write_minimal_library(b, "same_name")
    reg = build_library_registry([a, b], bundle_builtin=False)
    assert list(reg.libraries.keys()) == ["same_name"]
    assert len(reg.load_errors) == 1
    assert "duplicate library name" in reg.load_errors[0].message
