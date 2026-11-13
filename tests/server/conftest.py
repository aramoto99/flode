"""``tests/server/`` 共通 fixtures。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.userblocks._isolation import restore_userblocks_state


@pytest.fixture(autouse=True)
def _isolate_real_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """全テストで ``Path.home()`` を一時フォルダに向け、実ホーム (``~/.flode``) を読み書きしない。

    CLI 経由の起動は ``~/.flode/config.toml`` の ``[blocks]`` を読み、ユーザーブロックの
    読み込みはホームディレクトリを判定に使う (ADR-0081 §R-1)。個別に home を作りたいテストは
    ``isolated_home`` を使う (後から patch するのでそちらが優先される)。
    ``HOME`` / ``USERPROFILE`` も同じ一時フォルダに向ける (``os.path.expanduser`` 等、
    ``Path.home()`` を経由しない ``~`` 展開への備え)。
    """
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


@pytest.fixture(autouse=True)
def _isolate_userblocks(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """ユーザーブロックの読み込み状態 (管理型表・``sys.modules``・finder) をテストごとに戻す。"""
    yield from restore_userblocks_state(tmp_path_factory)


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """``Path.home()`` を ``tmp_path`` 配下に切り替えて ``~/.flode/config.toml``
    の暗黙探索を隔離する (SPEC-0004)。

    flode.server.config の ``_expand_home`` / ``default_user_config_path`` は
    ``Path.home()`` 経由なので、この monkeypatch 1 つで CLI / Resolver / template
    の全経路の暗黙 home 解決をテスト隔離できる。
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home
