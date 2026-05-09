"""``.flwlib.json`` loader / validator のテスト (ADR-0029)。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pyflw import LibraryFileError, load_library, validate_library
from pyflw.libraries._loader import (
    _LIBRARY_MIGRATIONS,
    CURRENT_LIBRARY_SCHEMA_VERSION,
    SUPPORTED_LIBRARY_SCHEMA_VERSIONS,
)


def _minimal_library_dict(**overrides: Any) -> dict[str, Any]:
    """テスト用に最小の有効 .flwlib.json dict を返す。"""
    base: dict[str, Any] = {
        "schema_version": CURRENT_LIBRARY_SCHEMA_VERSION,
        "name": "test",
        "display_name": "Test Library",
        "entries": [
            {
                "id": "trivial",
                "display_name": "Trivial",
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
    base.update(overrides)
    return base


def test_load_valid_library(tmp_path: Path) -> None:
    """最小限の有効な .flwlib.json が pass する。"""
    p = tmp_path / "test.flwlib.json"
    p.write_text(
        json.dumps(_minimal_library_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lib = load_library(p)
    assert lib.name == "test"
    assert len(lib.entries) == 1
    assert lib.entries[0].id == "trivial"
    assert lib.source_path == p.resolve()


def test_load_invalid_schema_version(tmp_path: Path) -> None:
    """``schema_version`` が未対応値だと ``LibraryFileError`` を raise する。"""
    p = tmp_path / "bad.flwlib.json"
    p.write_text(
        json.dumps(_minimal_library_dict(schema_version="libraries.v999")),
        encoding="utf-8",
    )
    with pytest.raises(LibraryFileError, match="Unsupported library schema_version"):
        load_library(p)


def test_load_missing_required_field(tmp_path: Path) -> None:
    """``name`` 欠落で ``LibraryFileError`` を raise する。"""
    data = _minimal_library_dict()
    del data["name"]
    p = tmp_path / "no_name.flwlib.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(LibraryFileError, match="Missing required key 'name'"):
        load_library(p)


def test_validate_library_in_memory() -> None:
    """``validate_library`` が dict を受け取り ``Library`` を返すパスを検証。"""
    lib = validate_library(_minimal_library_dict())
    assert lib.name == "test"
    assert lib.source_path is None


def test_migration_registry_has_v1_to_v2() -> None:
    """ADR-0039: ``libraries.v1`` → ``libraries.v2`` migration が登録されている。

    `libraries.v2` は Subsystem の派生 property 化 (n_inputs/n_outputs/
    port_shapes_*) に追従するため bump された。`libraries.v1` も migration 経由
    で受け入れる (= 既存 .flwlib.json の互換性維持)。
    """
    assert ("libraries.v1", "libraries.v2") in _LIBRARY_MIGRATIONS
    assert CURRENT_LIBRARY_SCHEMA_VERSION == "libraries.v2"
    # ADR-0039 code-reviewer SHOULD-3: v1 も SUPPORTED に含めて
    # 「migration 経由で受け入れ可能」を明示 (= エラーメッセージの誤解防止)
    assert "libraries.v2" in SUPPORTED_LIBRARY_SCHEMA_VERSIONS
    assert "libraries.v1" in SUPPORTED_LIBRARY_SCHEMA_VERSIONS


def test_load_std_bundle() -> None:
    """組み込み ``pyflw/libraries/std.flwlib.json`` の 3 entry が load 可能。"""
    import pyflw.libraries

    pkg_dir = Path(pyflw.libraries.__file__).parent
    lib = load_library(pkg_dir / "std.flwlib.json")
    assert lib.name == "std"
    ids = [e.id for e in lib.entries]
    assert ids == ["pid_controller", "first_order_plant", "second_order_plant"]
    # 組み込み entries は全て Subsystem._from_dict() で再構築可能 (= byte-identical 検証)
    from pyflw.subsystems import Subsystem

    for entry in lib.entries:
        sub = Subsystem._from_dict(**entry.subsystem["params"])
        assert sub.n_inputs >= 1
        assert sub.n_outputs >= 1


def test_std_bundle_resource_resolves_via_importlib() -> None:
    """``importlib.resources`` 経由で std.flwlib.json が見える (= wheel package_data 設定)。

    `pyproject.toml` の ``[tool.setuptools.package-data]`` で
    ``"pyflw.libraries" = ["*.json"]`` が抜けると wheel に bundle されず
    `LibraryRegistry` の `bundle_builtin=True` がサイレントに失敗する。本テストは
    `editable install` でも `wheel install` でも同じ resource lookup が成功する
    ことを確認するゲート。
    """
    import importlib.resources

    ref = importlib.resources.files("pyflw.libraries").joinpath("std.flwlib.json")
    assert ref.is_file(), (
        "pyflw/libraries/std.flwlib.json must be discoverable via "
        "importlib.resources (check pyproject.toml package-data)"
    )


def test_std_bundle_byte_identical_to_generator(tmp_path: Path) -> None:
    """``tools/build_std_library.py`` が生成する dict と bundle ファイルが
    byte-identical であることを検証する (= ジェネレータ更新後の commit 忘れ検出)。

    ``Subsystem.to_dict()`` の出力は決定的なので、本 generator を毎回実行しても
    同じ JSON が得られる前提。差分が出るのは ``Subsystem.to_dict()`` の挙動が
    変わった or ジェネレータが変わったが checked-in ファイルが追従していないとき。
    """
    import json
    import sys

    repo_root = Path(__file__).parent.parent.parent
    tools_path = repo_root / "tools"
    sys.path.insert(0, str(tools_path))
    try:
        import build_std_library  # type: ignore[import-not-found]
    finally:
        sys.path.remove(str(tools_path))

    # generator が使う dict 構築関数 → Subsystem._from_dict → to_dict
    expected_entries = [
        ("pid_controller", build_std_library.build_pid_params()),
        ("first_order_plant", build_std_library.build_first_order_plant_params()),
        ("second_order_plant", build_std_library.build_second_order_plant_params()),
    ]
    bundle_path = repo_root / "pyflw" / "libraries" / "std.flwlib.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle_entries = bundle["entries"]
    assert len(bundle_entries) == len(expected_entries)
    for (entry_id, params), bundle_entry in zip(expected_entries, bundle_entries, strict=True):
        assert bundle_entry["id"] == entry_id
        regen_subsystem = build_std_library._build_subsystem(params)
        assert bundle_entry["subsystem"] == regen_subsystem, (
            f"Entry {entry_id!r} subsystem body drifted from generator output. "
            f"Re-run `python tools/build_std_library.py` and commit the result."
        )


def test_load_invalid_entry_subsystem_type(tmp_path: Path) -> None:
    """subsystem.type が Subsystem 以外だと ``LibraryFileError``。"""
    data = _minimal_library_dict()
    data["entries"][0]["subsystem"]["type"] = "pyflw.blocks.mathops.Gain"
    p = tmp_path / "wrong_type.flwlib.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(LibraryFileError, match="must be a Subsystem class path"):
        load_library(p)


def test_load_duplicate_entry_id(tmp_path: Path) -> None:
    """同じ library 内で ``entry.id`` が重複したら ``LibraryFileError``。"""
    data = _minimal_library_dict()
    dup = json.loads(json.dumps(data["entries"][0]))  # deep copy
    data["entries"].append(dup)
    p = tmp_path / "dup.flwlib.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(LibraryFileError, match="duplicate entry id"):
        load_library(p)
