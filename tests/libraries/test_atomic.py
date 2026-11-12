"""アトミック書き込み (``flode.libraries._atomic``) のテスト (ADR-0080 §A6-1)。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from flode.exceptions import LibraryFileError, LibraryWriteBusyError, LibraryWriteError
from flode.libraries import _atomic, atomic_write_text
from flode.libraries._atomic import (
    BACKUP_SUFFIX,
    REPLACE_INITIAL_BACKOFF_SECONDS,
    REPLACE_MAX_ATTEMPTS,
    backup_path_for,
)

TARGET_NAME = "user.flwlib.json"


@pytest.fixture
def target(tmp_path: Path) -> Path:
    return tmp_path / TARGET_NAME


@pytest.fixture
def retry_enabled(mocker: MockerFixture) -> list[float]:
    """OS に依らず ``PermissionError`` の再試行を有効にし、sleep を記録だけにする。"""
    sleeps: list[float] = []
    mocker.patch.object(_atomic, "_RETRY_PERMISSION_ERRORS", True)
    mocker.patch.object(_atomic.time, "sleep", side_effect=sleeps.append)
    return sleeps


def _names(directory: Path) -> list[str]:
    return sorted(f.name for f in directory.iterdir())


def test_retry_constants_match_adr() -> None:
    """最大 5 回・50 ms 起点 (ADR-0080 §A6-1)。"""
    assert REPLACE_MAX_ATTEMPTS == 5
    assert REPLACE_INITIAL_BACKOFF_SECONDS == pytest.approx(0.05)


def test_write_new_file_creates_no_backup(target: Path) -> None:
    atomic_write_text(target, "new\n")
    assert target.read_bytes() == b"new\n"
    assert _names(target.parent) == [TARGET_NAME]


def test_write_does_not_translate_newlines(target: Path) -> None:
    """OS に依らずバイト列が一致する (Windows で ``\\r\\n`` に変換しない)。"""
    atomic_write_text(target, "a\nb\n")
    assert target.read_bytes() == b"a\nb\n"


def test_write_encodes_utf8(target: Path) -> None:
    atomic_write_text(target, "標準ライブラリ\n")
    assert target.read_text(encoding="utf-8") == "標準ライブラリ\n"


def test_overwrite_keeps_previous_content_as_bak(target: Path) -> None:
    atomic_write_text(target, "first\n")
    atomic_write_text(target, "second\n")
    assert target.read_bytes() == b"second\n"
    backup = backup_path_for(target)
    assert backup.name == TARGET_NAME + BACKUP_SUFFIX
    assert backup.read_bytes() == b"first\n"
    # 一時ファイルは残らない
    assert _names(target.parent) == [TARGET_NAME, TARGET_NAME + BACKUP_SUFFIX]


def test_backup_is_single_generation(target: Path) -> None:
    for text in ("first\n", "second\n", "third\n"):
        atomic_write_text(target, text)
    assert backup_path_for(target).read_bytes() == b"second\n"
    assert _names(target.parent) == [TARGET_NAME, TARGET_NAME + BACKUP_SUFFIX]


def test_backup_and_temp_names_are_not_picked_up_by_library_glob(target: Path) -> None:
    """``.bak`` は registry の ``*.flwlib.json`` glob に拾われない (ADR-0080 §A6-1)。"""
    atomic_write_text(target, "first\n")
    atomic_write_text(target, "second\n")
    assert [f.name for f in target.parent.rglob("*.flwlib.json")] == [TARGET_NAME]


def test_backup_can_be_disabled(target: Path) -> None:
    atomic_write_text(target, "first\n")
    atomic_write_text(target, "second\n", backup=False)
    assert _names(target.parent) == [TARGET_NAME]


def test_fsync_called_before_replace(target: Path, mocker: MockerFixture) -> None:
    """一時ファイルを fsync してから置換する (順序を固定)。"""
    calls: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace
    mocker.patch.object(
        _atomic.os, "fsync", side_effect=lambda fd: (calls.append("fsync"), real_fsync(fd))[1]
    )
    mocker.patch.object(
        _atomic.os,
        "replace",
        side_effect=lambda src, dst: (calls.append("replace"), real_replace(src, dst))[1],
    )
    atomic_write_text(target, "x\n")
    assert calls[:2] == ["fsync", "replace"]


def test_permission_error_is_retried_then_succeeds(
    target: Path, retry_enabled: list[float], mocker: MockerFixture
) -> None:
    real_replace = os.replace
    failures = [PermissionError("locked"), PermissionError("locked")]

    def flaky(src: str | Path, dst: str | Path) -> None:
        if failures:
            raise failures.pop()
        real_replace(src, dst)

    mocker.patch.object(_atomic.os, "replace", side_effect=flaky)
    atomic_write_text(target, "ok\n")
    assert target.read_bytes() == b"ok\n"
    assert retry_enabled == pytest.approx([0.05, 0.1])
    assert _names(target.parent) == [TARGET_NAME]


def test_permission_error_exhausts_retries(
    target: Path, retry_enabled: list[float], mocker: MockerFixture
) -> None:
    """5 回失敗したら一時ファイルを消して ``LibraryWriteBusyError``。既存ファイルは無傷。"""
    target.write_bytes(b"original\n")
    replace = mocker.patch.object(_atomic.os, "replace", side_effect=PermissionError("locked"))
    with pytest.raises(LibraryWriteBusyError, match="user.flwlib.json") as excinfo:
        atomic_write_text(target, "new\n")
    assert isinstance(excinfo.value.__cause__, PermissionError)
    assert replace.call_count == REPLACE_MAX_ATTEMPTS
    # 指数バックオフ: 50 ms 起点で倍々、最終試行の後は待たない
    assert retry_enabled == pytest.approx([0.05, 0.1, 0.2, 0.4])
    assert target.read_bytes() == b"original\n"
    assert _names(target.parent) == [TARGET_NAME]


def test_busy_error_is_a_library_write_error() -> None:
    """既存の ``except LibraryFileError`` でも捕まえられる階層にする。"""
    assert issubclass(LibraryWriteBusyError, LibraryWriteError)
    assert issubclass(LibraryWriteError, LibraryFileError)


def test_permission_error_not_retried_when_disabled(target: Path, mocker: MockerFixture) -> None:
    """再試行しない OS では ``PermissionError`` を即 ``LibraryWriteError`` にする。"""
    mocker.patch.object(_atomic, "_RETRY_PERMISSION_ERRORS", False)
    sleep = mocker.patch.object(_atomic.time, "sleep")
    replace = mocker.patch.object(_atomic.os, "replace", side_effect=PermissionError("denied"))
    with pytest.raises(LibraryWriteError) as excinfo:
        atomic_write_text(target, "new\n")
    assert not isinstance(excinfo.value, LibraryWriteBusyError)
    assert replace.call_count == 1
    sleep.assert_not_called()
    assert _names(target.parent) == []


def test_other_os_error_cleans_up_temp_file(target: Path, mocker: MockerFixture) -> None:
    mocker.patch.object(_atomic.os, "replace", side_effect=OSError("disk full"))
    with pytest.raises(LibraryWriteError, match="disk full"):
        atomic_write_text(target, "new\n")
    assert _names(target.parent) == []


def test_unencodable_text_raises_library_write_error(target: Path) -> None:
    """UTF-8 に符号化できない内容 (孤立サロゲート) でも既存ファイルを壊さない。"""
    target.write_text("old\n", encoding="utf-8")
    with pytest.raises(LibraryWriteError):
        atomic_write_text(target, "broken \ud800\n")
    assert target.read_text(encoding="utf-8") == "old\n"
    assert _names(target.parent) == [TARGET_NAME]


def test_missing_directory_raises_library_write_error(tmp_path: Path) -> None:
    with pytest.raises(LibraryWriteError):
        atomic_write_text(tmp_path / "missing" / TARGET_NAME, "x\n")


# ----------------------------------------------------------------------------
# write_text_exclusive / move_to_backup (ADR-0080 §A6-2 / §A6-4)
# ----------------------------------------------------------------------------


def test_write_text_exclusive_creates_file(target: Path) -> None:
    _atomic.write_text_exclusive(target, "new\n")
    assert target.read_bytes() == b"new\n"


def test_write_text_exclusive_never_overwrites(target: Path) -> None:
    target.write_bytes(b"original\n")
    with pytest.raises(FileExistsError):
        _atomic.write_text_exclusive(target, "new\n")
    assert target.read_bytes() == b"original\n"


def test_write_text_exclusive_missing_directory_is_write_error(tmp_path: Path) -> None:
    with pytest.raises(LibraryWriteError):
        _atomic.write_text_exclusive(tmp_path / "missing" / TARGET_NAME, "x\n")


def test_write_text_exclusive_removes_partial_file_on_failure(
    target: Path, mocker: MockerFixture
) -> None:
    mocker.patch.object(_atomic.os, "fsync", side_effect=OSError("disk full"))
    with pytest.raises(LibraryWriteError, match="disk full"):
        _atomic.write_text_exclusive(target, "x\n")
    assert _names(target.parent) == []


def test_move_to_backup_renames_and_replaces_old_backup(target: Path) -> None:
    target.write_bytes(b"current\n")
    backup_path_for(target).write_bytes(b"older\n")
    assert _atomic.move_to_backup(target) == backup_path_for(target)
    assert _names(target.parent) == [TARGET_NAME + BACKUP_SUFFIX]
    assert backup_path_for(target).read_bytes() == b"current\n"


def test_move_to_backup_missing_file_is_write_error(target: Path) -> None:
    with pytest.raises(LibraryWriteError):
        _atomic.move_to_backup(target)


def test_move_to_backup_busy_file_is_busy_error(
    target: Path, retry_enabled: list[float], mocker: MockerFixture
) -> None:
    target.write_bytes(b"current\n")
    mocker.patch.object(_atomic.os, "replace", side_effect=PermissionError("locked"))
    with pytest.raises(LibraryWriteBusyError):
        _atomic.move_to_backup(target)
    assert target.read_bytes() == b"current\n"
