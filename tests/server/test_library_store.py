"""``LibraryStore`` と補助関数の単体テスト (ADR-0080 §A5 / §A6)。

REST 経由の振る舞いは ``test_libraries_write_api.py`` が持つ。ここでは並行制御・
copy-on-write・純粋関数を直接確かめる。
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pytest_mock import MockerFixture

from flode.exceptions import (
    LibraryApiError,
    LibraryEntryConflictError,
    LibraryFileInvalidError,
    LibraryWriteBusyError,
    LibraryWriteForbiddenError,
    UserLibraryDisabledError,
)
from flode.libraries import _atomic, load_library
from flode.server.library_store import (
    MAX_LIBRARY_JSON_DEPTH,
    LibraryStore,
    file_slug,
    normalized_name_key,
    parse_bounded_json,
)
from tests.server._library_models import gain_block, library_dict, subsystem_body

USER_FILE = "user.flwlib.json"


def _store(user_dir: Path | None, **kwargs: Any) -> LibraryStore:
    kwargs.setdefault("write_allowed", True)
    kwargs.setdefault("bundle_builtin", False)
    return LibraryStore(user_library_dir=user_dir, **kwargs)


# ----------------------------------------------------------------------------
# 純粋関数
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Shared Lib", "shared-lib"),
        ("ＡＢＣ　１２３", "abc-123"),  # NFKC で半角に畳む
        ("a__b--c", "a_b-c"),  # 連続する区切りは 1 つに
        ("  --x--  ", "x"),
        ("日本語", "library"),  # ASCII に残る文字が無ければ代替名
        ("", "library"),
        ("../../etc/passwd", "etc-passwd"),
        ("CON", "lib-con"),  # Windows の予約デバイス名
        ("com1", "lib-com1"),
        ("x" * 100, "x" * 40),
        ("a" * 39 + "-b", "a" * 39),  # 切った後に区切りで終わらない
    ],
)
def test_file_slug(name: str, expected: str) -> None:
    assert file_slug(name) == expected


@pytest.mark.parametrize(
    ("left", "right"),
    [("PID", " pid "), ("Straße", "STRASSE"), ("Café", "Café")],
)
def test_normalized_name_key_equates(left: str, right: str) -> None:
    assert normalized_name_key(left) == normalized_name_key(right)


def test_normalized_name_key_keeps_distinct_names_apart() -> None:
    assert normalized_name_key("PID") != normalized_name_key("PID 2")
    assert normalized_name_key("PID") != normalized_name_key("ＰＩＤ")


def _nested(depth: int) -> str:
    return "[" * depth + "]" * depth


def test_parse_bounded_json_depth_boundary() -> None:
    assert parse_bounded_json(_nested(MAX_LIBRARY_JSON_DEPTH)) is not None
    with pytest.raises(LibraryFileInvalidError, match="nested deeper"):
        parse_bounded_json(_nested(MAX_LIBRARY_JSON_DEPTH + 1))
    # スカラは深さに数えない / dict と list の混在も数える
    mixed: Any = 1
    for level in range(MAX_LIBRARY_JSON_DEPTH):
        mixed = {"k": mixed} if level % 2 else [mixed]
    assert parse_bounded_json(json.dumps(mixed)) == mixed
    with pytest.raises(LibraryFileInvalidError):
        parse_bounded_json(json.dumps([mixed]))


@pytest.mark.parametrize(
    "text",
    ["", "{", "nope", b"\xff\xfe", "[" * 500_000],
    ids=["empty", "truncated", "not-json", "not-utf8", "absurdly-deep"],
)
def test_parse_bounded_json_rejects_unreadable_input(text: str | bytes) -> None:
    with pytest.raises(LibraryFileInvalidError):
        parse_bounded_json(text)


def test_parse_bounded_json_wide_document_is_fine() -> None:
    wide = json.dumps({"entries": [{"k": i} for i in range(20_000)]})
    assert len(parse_bounded_json(wide)["entries"]) == 20_000


# ----------------------------------------------------------------------------
# 可否の判定
# ----------------------------------------------------------------------------


def test_default_store_is_fail_closed(tmp_path: Path) -> None:
    store = LibraryStore(bundle_builtin=False)
    assert store.user_library_enabled is False
    assert store.write_disabled_reason(store.registry) == "library_write_forbidden"
    with pytest.raises(LibraryWriteForbiddenError):
        store.require_write()
    with pytest.raises(LibraryWriteForbiddenError):
        store.register_entry(block=subsystem_body(), display_name="X")


def test_forbidden_takes_precedence_over_disabled() -> None:
    store = _store(None, write_allowed=False, write_reason="bound to 0.0.0.0")
    with pytest.raises(LibraryWriteForbiddenError, match=r"0\.0\.0\.0"):
        store.require_write()
    with pytest.raises(UserLibraryDisabledError):
        _store(None).require_write()


def test_reload_needs_permission_but_not_a_user_library(tmp_path: Path) -> None:
    """再読み込みはユーザーライブラリに書かないので、無効でも許可されていれば通す。"""
    extra = tmp_path / "extra"
    extra.mkdir()
    store = _store(None, library_paths=[extra])
    store.require_write(needs_user_library=False)
    (extra / "late.flwlib.json").write_text(
        json.dumps(library_dict("late", {"e": subsystem_body()})), encoding="utf-8"
    )
    assert list(store.reload().libraries) == ["late"]
    forbidden = _store(None, write_allowed=False)
    with pytest.raises(LibraryWriteForbiddenError):
        forbidden.require_write(needs_user_library=False)
    with pytest.raises(LibraryWriteForbiddenError):
        forbidden.reload()


def test_readers_use_the_registry_they_were_given(tmp_path: Path) -> None:
    """読み取り側は 1 回掴んだ registry だけを見る (途中で差し替わっても応答が混ざらない)。"""
    from flode.server.library_registry import LibraryRegistry
    from flode.server.library_store import export_library

    store = _store(tmp_path / "libraries")
    store.register_entry(block=subsystem_body(), display_name="A")
    held = store.registry
    store.delete_entry("a", 1)
    store.register_entry(block=subsystem_body(), display_name="B")
    # 掴んだ時点の内容で書き出される
    _, text = export_library(held, "user")
    assert [e["id"] for e in json.loads(text)["entries"]] == ["a"]
    # 書き込めない理由も、渡された registry の状態から答える
    broken = LibraryRegistry(user_library_problem="user_library_corrupt")
    assert store.write_disabled_reason(broken) == "user_library_corrupt"
    assert store.write_disabled_reason(held) == ""


def test_every_mutating_method_checks_the_policy(tmp_path: Path) -> None:
    """ルートの dependency を通らずに呼ばれても、store 自身が拒否する (多層防御)。"""
    store = _store(tmp_path / "libraries", write_allowed=False)
    calls = [
        lambda: store.register_entry(block=subsystem_body(), display_name="X"),
        lambda: store.update_entry_metadata("x", {"description": "d"}),
        lambda: store.delete_entry("x", 1),
        lambda: store.import_library("{}", dry_run=True),
        lambda: store.import_library("{}", dry_run=False),
        lambda: store.delete_imported_library("x"),
        store.reload,
    ]
    for call in calls:
        with pytest.raises(LibraryWriteForbiddenError):
            call()
    assert not (tmp_path / "libraries").exists()


def test_unresolved_user_library_dir_is_accepted(tmp_path: Path) -> None:
    """埋め込み利用で未解決の path を渡されても、包含確認は解決後の path 同士で行う。"""
    (tmp_path / "a").mkdir()
    store = _store(tmp_path / "a" / ".." / "libraries")
    store.register_entry(block=subsystem_body(), display_name="X")
    assert (tmp_path / "libraries" / USER_FILE).is_file()


# ----------------------------------------------------------------------------
# copy-on-write / 並行制御 (ADR-0080 §A5)
# ----------------------------------------------------------------------------


def test_registry_is_replaced_not_mutated(tmp_path: Path) -> None:
    store = _store(tmp_path / "libraries")
    before = store.registry
    snapshot = (dict(before.libraries), list(before.load_errors), dict(before.origins))
    store.register_entry(block=subsystem_body(), display_name="A")
    after_register = store.registry
    store.import_library(json.dumps(library_dict("lib", {"e": subsystem_body()})), dry_run=False)
    after_import = store.registry
    store.delete_imported_library("lib")
    # 古い参照を持っている読み手から見た内容は変わらない
    assert (before.libraries, before.load_errors, before.origins) == snapshot
    assert list(after_register.libraries) == ["user"]
    assert list(after_import.libraries) == ["user", "lib"]
    assert list(store.registry.libraries) == ["user"]
    assert len({id(before), id(after_register), id(after_import), id(store.registry)}) == 4


def test_failed_write_leaves_registry_untouched(tmp_path: Path) -> None:
    store = _store(tmp_path / "libraries")
    store.register_entry(block=subsystem_body(), display_name="A")
    registry = store.registry
    with pytest.raises(LibraryEntryConflictError):
        store.delete_entry("a", expected_revision=9)
    with pytest.raises(LibraryApiError):
        store.register_entry(block=gain_block(), display_name="B")
    assert store.registry is registry


OK = "ok"
CONFLICT = "conflict"
BUSY = "busy"
# 「他プロセスがファイルを開いていた」(LibraryWriteBusyError) で 1 本の worker が再試行する回数
BUSY_RETRIES = 5


def _run_concurrently(n_threads: int, attempt: Callable[[int], None]) -> list[str]:
    """``attempt(index)`` を ``n_threads`` 本のスレッドから同時に呼び、結果を index 順に返す。

    結果は ``"ok"`` / ``"conflict"`` (``LibraryEntryConflictError``) / ``"busy"``
    (``LibraryWriteBusyError`` が再試行後も続いた) / ``"error: <型名>: <内容>"`` (想定外)。

    ``LibraryWriteBusyError`` は Windows でウイルス対策やインデクサがファイルを掴んだときに
    起きる外乱で、ファイルも registry も変えない (検証したい不変条件を破らない)。
    そのため worker は数回やり直し、それでも駄目なら ``"busy"`` として記録する
    (スレッドを例外で死なせて結果を欠落させない)。
    """
    barrier = threading.Barrier(n_threads)
    outcomes = ["error: worker did not finish"] * n_threads

    def worker(index: int) -> None:
        outcome = BUSY
        try:
            barrier.wait(timeout=10)
            for _ in range(BUSY_RETRIES):
                try:
                    attempt(index)
                except LibraryWriteBusyError:
                    continue
                outcome = OK
                break
        except LibraryEntryConflictError:
            outcome = CONFLICT
        except BaseException as e:  # noqa: BLE001 - スレッド内の失敗を主スレッドへ運ぶ
            outcome = f"error: {type(e).__name__}: {e}"
        outcomes[index] = outcome

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in threads), f"workers did not finish: {outcomes}"
    unexpected = [o for o in outcomes if o not in (OK, CONFLICT, BUSY)]
    assert not unexpected, f"unexpected worker failures: {unexpected} (all outcomes: {outcomes})"
    return outcomes


def _settled_files(directory: Path) -> list[str]:
    """ディレクトリの中身 (書き込み途中の一時ファイル ``*.tmp`` を除く)。"""
    return sorted(p.name for p in directory.iterdir() if not p.name.endswith(".tmp"))


@pytest.fixture
def transient_busy(request: pytest.FixtureRequest, mocker: MockerFixture) -> bool:
    """``True`` のとき、最初の書き込み 1 回分の ``os.replace`` を「使用中」で失敗させる。

    外乱 (他プロセスがファイルを掴む) を決定的に再現し、並行テストがそれで落ちないことを
    確かめる。OS に依らず再試行を有効にし、待ち時間は無くす。
    """
    inject = bool(request.param)
    if inject:
        real_replace = _atomic.os.replace
        remaining = [_atomic.REPLACE_MAX_ATTEMPTS]
        guard = threading.Lock()

        def flaky_replace(src: Any, dst: Any) -> None:
            with guard:
                fail = remaining[0] > 0
                remaining[0] -= 1
            if fail:
                raise PermissionError("in use by another process")
            real_replace(src, dst)

        mocker.patch.object(_atomic, "_RETRY_PERMISSION_ERRORS", True)
        mocker.patch.object(_atomic.time, "sleep")
        mocker.patch.object(_atomic.os, "replace", side_effect=flaky_replace)
    return inject


@pytest.mark.parametrize("transient_busy", [False, True], indirect=True, ids=["quiet", "busy"])
def test_concurrent_registrations_are_serialized(tmp_path: Path, transient_busy: bool) -> None:
    """複数スレッドから同時に登録しても、成功した分はすべて反映されファイルが壊れない。"""
    user_dir = tmp_path / "libraries"
    store = _store(user_dir)
    n_threads = 8

    def register(index: int) -> None:
        store.register_entry(
            block=subsystem_body([gain_block(k=float(index))]), display_name=f"Block {index}"
        )

    outcomes = _run_concurrently(n_threads, register)
    assert CONFLICT not in outcomes, outcomes
    succeeded = {f"block_{i}" for i, outcome in enumerate(outcomes) if outcome == OK}
    # 外乱が無い (または 1 回分だけの) ときは再試行で全件が通る
    assert len(succeeded) == n_threads, outcomes
    on_disk = load_library(user_dir / USER_FILE)  # 壊れていれば読めない
    assert {e.id for e in on_disk.entries} == succeeded, outcomes
    assert {e.id for e in store.registry.libraries["user"].entries} == succeeded, outcomes
    assert _settled_files(user_dir) == [USER_FILE, USER_FILE + ".bak"]


@pytest.mark.parametrize("transient_busy", [False, True], indirect=True, ids=["quiet", "busy"])
def test_concurrent_overwrites_of_one_entry_conflict_instead_of_losing_updates(
    tmp_path: Path, transient_busy: bool
) -> None:
    """同じ revision を前提にした同時上書きは、1 本だけが通り残りは 409 になる。"""
    user_dir = tmp_path / "libraries"
    store = _store(user_dir)
    n_threads = 6

    def overwrite(index: int) -> None:
        store.register_entry(
            block=subsystem_body([gain_block(k=float(index))]),
            display_name="PID",
            overwrite_entry_id="pid",
            expected_revision=1,
        )

    # 準備の登録も同じ外乱を受けうるので、同じ再試行つきの経路で行う
    assert _run_concurrently(
        1, lambda _i: store.register_entry(block=subsystem_body(), display_name="PID")
    ) == [OK]
    outcomes = _run_concurrently(n_threads, overwrite)
    assert outcomes.count(OK) == 1, outcomes
    assert outcomes.count(CONFLICT) == n_threads - 1, outcomes
    (entry,) = load_library(user_dir / USER_FILE).entries
    assert entry.revision == 2, outcomes
    winner = float(outcomes.index(OK))
    gain = next(b for b in entry.block["params"]["blocks"] if b["id"] == "gain")
    assert gain["params"]["k"] == winner  # 通った 1 本の内容がそのまま残っている


def test_worker_that_stays_busy_is_reported_not_lost(tmp_path: Path, mocker: MockerFixture) -> None:
    """置換がずっと阻まれる場合も、結果は欠けずに ``busy`` として記録され、ファイルは変わらない。"""
    user_dir = tmp_path / "libraries"
    store = _store(user_dir)
    store.register_entry(block=subsystem_body(), display_name="Kept")
    before = (user_dir / USER_FILE).read_bytes()
    mocker.patch.object(_atomic, "_RETRY_PERMISSION_ERRORS", True)
    mocker.patch.object(_atomic.time, "sleep")
    mocker.patch.object(_atomic.os, "replace", side_effect=PermissionError("in use"))
    outcomes = _run_concurrently(
        3, lambda i: store.register_entry(block=subsystem_body(), display_name=f"New {i}")
    )
    mocker.stopall()
    assert outcomes == [BUSY, BUSY, BUSY]
    assert (user_dir / USER_FILE).read_bytes() == before
    assert [e.id for e in store.registry.libraries["user"].entries] == ["kept"]
    assert _settled_files(user_dir) == [USER_FILE]


def test_two_stores_on_one_directory_detect_each_other(tmp_path: Path) -> None:
    """同じディレクトリを 2 プロセスが使う状況: 後から書く側はディスク変更として検知する。"""
    user_dir = tmp_path / "libraries"
    first = _store(user_dir)
    second = _store(user_dir)
    first.register_entry(block=subsystem_body(), display_name="From first")
    with pytest.raises(LibraryApiError) as excinfo:
        second.register_entry(block=subsystem_body(), display_name="From second")
    assert excinfo.value.code == "library_changed_on_disk"
    second.reload()
    second.register_entry(block=subsystem_body(), display_name="From second")
    assert [e.id for e in load_library(user_dir / USER_FILE).entries] == [
        "from_first",
        "from_second",
    ]
