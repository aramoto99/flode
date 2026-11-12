"""Library registry build のテスト (ADR-0029)。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from flode.libraries._loader import CURRENT_LIBRARY_SCHEMA_VERSION
from flode.server.library_registry import build_library_registry


def _write_minimal_library(path: Path, name: str) -> None:
    data = {
        "schema_version": CURRENT_LIBRARY_SCHEMA_VERSION,
        "name": name,
        "display_name": name.title(),
        "entries": [
            {
                "id": "ent",
                "display_name": "Entry",
                "block": {
                    "id": None,
                    "type": "flode.subsystems.subsystem.Subsystem",
                    "params": {
                        "n_inputs": 1,
                        "n_outputs": 1,
                        "blocks": [
                            {
                                "id": "Inport_0",
                                "type": "flode.subsystems.ports.Inport",
                                "params": {"port_idx": 0},
                            },
                            {
                                "id": "Outport_0",
                                "type": "flode.subsystems.ports.Outport",
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


def test_registry_loads_legacy_v3_file(tmp_path: Path) -> None:
    """v3 形式 (本体が ``subsystem``) のファイルも registry に読み込める (ADR-0080 §A1-3)。"""
    f = tmp_path / "old.flwlib.json"
    _write_minimal_library(f, "old")
    data = json.loads(f.read_text(encoding="utf-8"))
    data["schema_version"] = "libraries.v3"
    data["entries"][0]["subsystem"] = data["entries"][0].pop("block")
    f.write_text(json.dumps(data), encoding="utf-8")
    reg = build_library_registry([f], bundle_builtin=False)
    assert reg.load_errors == []
    entry = reg.libraries["old"].entries[0]
    assert entry.kind == "subsystem"
    assert entry.revision == 1


def test_registry_records_disallowed_entry_type_as_load_error(tmp_path: Path) -> None:
    """許可外の型を本体に持つファイルは丸ごと ``load_errors`` に落ち、他は読み込まれる。"""
    good = tmp_path / "good.flwlib.json"
    bad = tmp_path / "bad.flwlib.json"
    _write_minimal_library(good, "good")
    _write_minimal_library(bad, "bad")
    data = json.loads(bad.read_text(encoding="utf-8"))
    data["entries"][0]["block"]["type"] = "flode.blocks.mathops.Gain"
    bad.write_text(json.dumps(data), encoding="utf-8")
    reg = build_library_registry([good, bad], bundle_builtin=False)
    assert list(reg.libraries) == ["good"]
    assert len(reg.load_errors) == 1
    assert "Subsystem or PythonFunction" in reg.load_errors[0].message


# ----------------------------------------------------------------------------
# ADR-0080 §A1-5: 読み込み順・重複除去・予約名・origin
# ----------------------------------------------------------------------------


def _user_dir_with_everything(tmp_path: Path) -> tuple[Path, Path]:
    """``user`` / 取り込み / 手置き / ``library_paths`` の 4 種を持つディレクトリ構成を作る。"""
    user_dir = tmp_path / "libraries"
    (user_dir / "imported" / "nested").mkdir(parents=True)
    (user_dir / "manual").mkdir()
    _write_minimal_library(user_dir / "user.flwlib.json", "user")
    _write_minimal_library(user_dir / "imported" / "zeta-0a1b2c3d.flwlib.json", "zeta")
    _write_minimal_library(user_dir / "imported" / "nested" / "deep.flwlib.json", "deep")
    _write_minimal_library(user_dir / "aaa.flwlib.json", "aaa")
    _write_minimal_library(user_dir / "manual" / "hand.flwlib.json", "hand")
    extra = tmp_path / "extra.flwlib.json"
    _write_minimal_library(extra, "extra")
    return user_dir, extra


def test_load_order_and_origins(tmp_path: Path) -> None:
    user_dir, extra = _user_dir_with_everything(tmp_path)
    reg = build_library_registry([extra], bundle_builtin=True, user_library_dir=user_dir)
    assert reg.load_errors == []
    # std → user → imported/** → user_library_dir のその他 → library_paths
    assert list(reg.libraries) == ["std", "user", "deep", "zeta", "aaa", "hand", "extra"]
    assert reg.origins == {
        "std": "builtin",
        "user": "user",
        # imported/ の直下 (サーバが生成する場所) だけが "imported"
        "zeta": "imported",
        "deep": "path",
        "aaa": "path",
        "hand": "path",
        "extra": "path",
    }
    assert reg.user_library_problem == ""


def test_same_file_is_loaded_once(tmp_path: Path) -> None:
    """``library_paths`` がユーザーライブラリのディレクトリを含んでいても二重読込しない。"""
    user_dir, extra = _user_dir_with_everything(tmp_path)
    reg = build_library_registry(
        [user_dir, user_dir / "user.flwlib.json", extra, extra],
        bundle_builtin=False,
        user_library_dir=user_dir,
    )
    assert reg.load_errors == []
    assert list(reg.libraries) == ["user", "deep", "zeta", "aaa", "hand", "extra"]
    assert reg.origins["user"] == "user"


def test_missing_user_library_dir_is_not_an_error(tmp_path: Path) -> None:
    reg = build_library_registry([], bundle_builtin=False, user_library_dir=tmp_path / "nope")
    assert reg.libraries == {}
    assert reg.load_errors == []


def test_disabled_user_library_dir_is_never_scanned(tmp_path: Path) -> None:
    _user_dir_with_everything(tmp_path)
    reg = build_library_registry([], bundle_builtin=False, user_library_dir=None)
    assert reg.libraries == {}


@pytest.mark.parametrize("user_library_dir_enabled", [True, False])
def test_reserved_name_user_outside_default_path_is_rejected(
    tmp_path: Path, user_library_dir_enabled: bool
) -> None:
    """既定パス以外の ``user`` は、ユーザーライブラリが無効・未作成でも拒否する。"""
    impostor = tmp_path / "impostor.flwlib.json"
    _write_minimal_library(impostor, "user")
    user_dir = tmp_path / "libraries" if user_library_dir_enabled else None
    reg = build_library_registry([impostor], bundle_builtin=False, user_library_dir=user_dir)
    assert reg.libraries == {}
    assert len(reg.load_errors) == 1
    assert "reserved" in reg.load_errors[0].message


def test_reserved_name_user_in_imported_dir_is_rejected(tmp_path: Path) -> None:
    user_dir = tmp_path / "libraries"
    (user_dir / "imported").mkdir(parents=True)
    _write_minimal_library(user_dir / "imported" / "x.flwlib.json", "user")
    reg = build_library_registry([], bundle_builtin=False, user_library_dir=user_dir)
    assert reg.libraries == {}
    assert "reserved" in reg.load_errors[0].message


def test_default_path_file_with_other_name_is_corrupt(tmp_path: Path) -> None:
    user_dir = tmp_path / "libraries"
    user_dir.mkdir()
    _write_minimal_library(user_dir / "user.flwlib.json", "not_user")
    reg = build_library_registry([], bundle_builtin=False, user_library_dir=user_dir)
    assert reg.libraries == {}
    assert "corrupt" in reg.load_errors[0].message


def test_backup_and_temp_files_are_not_loaded(tmp_path: Path) -> None:
    user_dir = tmp_path / "libraries"
    user_dir.mkdir()
    _write_minimal_library(user_dir / "user.flwlib.json", "user")
    _write_minimal_library(user_dir / "user.flwlib.json.bak", "user")
    _write_minimal_library(user_dir / "user.flwlib.json.pre-v4.bak", "user")
    _write_minimal_library(user_dir / ".user.flwlib.json.abcd.tmp", "user")
    reg = build_library_registry([], bundle_builtin=False, user_library_dir=user_dir)
    assert list(reg.libraries) == ["user"]
    assert reg.load_errors == []


# ----------------------------------------------------------------------------
# 1 ファイルの失敗が registry 全体 (= サーバ起動) を巻き込まない
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        # int 変換の桁数上限を超える整数: json.loads が素の ValueError を出す
        b'{"schema_version": "libraries.v4", "name": "x", "entries": [], "n": '
        + b"9" * 5000
        + b"}",
        b'{"schema_version": "libraries.v4", "name": "\xff\xfe", "entries": []}',
        b"[" * 200_000,
    ],
    ids=["huge-int", "bad-utf8", "absurdly-deep"],
)
def test_unreadable_file_is_recorded_and_others_still_load(tmp_path: Path, content: bytes) -> None:
    good = tmp_path / "good.flwlib.json"
    bad = tmp_path / "bad.flwlib.json"
    _write_minimal_library(good, "good")
    bad.write_bytes(content)
    reg = build_library_registry([bad, good], bundle_builtin=False)
    assert list(reg.libraries) == ["good"]
    assert [Path(e.path).name for e in reg.load_errors] == ["bad.flwlib.json"]


@pytest.mark.parametrize("error", [ValueError("boom"), RecursionError("deep"), MemoryError()])
def test_unexpected_loader_failure_is_contained_per_file(
    tmp_path: Path, mocker: MockerFixture, error: Exception
) -> None:
    """ローダが ``LibraryFileError`` に包み損ねた失敗も、1 ファイルの load_error に留める。"""
    from flode.libraries import load_library
    from flode.server import library_registry

    good = tmp_path / "good.flwlib.json"
    bad = tmp_path / "bad.flwlib.json"
    _write_minimal_library(good, "good")
    _write_minimal_library(bad, "bad")

    def flaky(path: Path) -> object:
        if Path(path).name == "bad.flwlib.json":
            raise error
        return load_library(path)

    mocker.patch.object(library_registry, "load_library", side_effect=flaky)
    reg = build_library_registry([bad, good], bundle_builtin=False)
    assert list(reg.libraries) == ["good"]
    assert len(reg.load_errors) == 1
    assert type(error).__name__ in reg.load_errors[0].message


def test_load_failure_log_cannot_be_forged_with_newlines(
    tmp_path: Path, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    from flode.exceptions import LibraryFileError
    from flode.server import library_registry

    f = tmp_path / "x.flwlib.json"
    _write_minimal_library(f, "x")
    mocker.patch.object(
        library_registry,
        "load_library",
        side_effect=LibraryFileError("bad\n2026-01-01 [INFO] forged line"),
    )
    with caplog.at_level("WARNING", logger="flode.library_registry"):
        build_library_registry([f], bundle_builtin=False)
    (message,) = [r.getMessage() for r in caplog.records]
    assert "\n" not in message
    assert "forged line" in message


# ----------------------------------------------------------------------------
# uid は registry 内で一意
# ----------------------------------------------------------------------------


def _write_library_with_uid(path: Path, name: str, uid: str | None) -> None:
    _write_minimal_library(path, name)
    if uid is not None:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["uid"] = uid
        path.write_text(json.dumps(data), encoding="utf-8")


def test_duplicate_uid_is_dropped_from_the_later_library(tmp_path: Path) -> None:
    """同じ uid を名乗る後発のライブラリは、uid 無しとして読み込む (由来の突合で先発に化けない)。"""
    first = tmp_path / "a_first.flwlib.json"
    second = tmp_path / "b_second.flwlib.json"
    third = tmp_path / "c_third.flwlib.json"
    _write_library_with_uid(first, "first", "same-uid")
    _write_library_with_uid(second, "second", "same-uid")
    _write_library_with_uid(third, "third", "other-uid")
    reg = build_library_registry([first, second, third], bundle_builtin=False)
    assert list(reg.libraries) == ["first", "second", "third"]
    assert [reg.libraries[n].uid for n in reg.libraries] == ["same-uid", None, "other-uid"]
    assert len(reg.load_errors) == 1
    assert Path(reg.load_errors[0].path).name == "b_second.flwlib.json"
    assert "uid" in reg.load_errors[0].message and "first" in reg.load_errors[0].message


def test_user_library_keeps_its_uid_over_hand_placed_copies(tmp_path: Path) -> None:
    user_dir = tmp_path / "libraries"
    (user_dir / "imported").mkdir(parents=True)
    _write_library_with_uid(user_dir / "user.flwlib.json", "user", "my-uid")
    _write_library_with_uid(user_dir / "imported" / "x.flwlib.json", "copy", "my-uid")
    reg = build_library_registry([], bundle_builtin=False, user_library_dir=user_dir)
    assert reg.libraries["user"].uid == "my-uid"
    assert reg.libraries["copy"].uid is None


def test_libraries_without_uid_do_not_collide(tmp_path: Path) -> None:
    a = tmp_path / "a.flwlib.json"
    b = tmp_path / "b.flwlib.json"
    _write_library_with_uid(a, "a", None)
    _write_library_with_uid(b, "b", None)
    reg = build_library_registry([a, b], bundle_builtin=False)
    assert reg.load_errors == []
