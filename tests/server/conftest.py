"""``tests/server/`` 共通 fixtures。"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _never_touch_real_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``tests/server/`` の全テストで ``Path.home()`` を一時ディレクトリに向ける。

    CLI / ``SettingsResolver`` は ``~/.flode/config.toml`` を探し、ユーザーライブラリの
    既定 ``~/.flode/libraries`` を解決する (ADR-0080)。``isolated_home`` を明示しない
    テストでも実ホームを読み書きしないための保険。``isolated_home`` を使うテストでは
    そちらの差し替えが後から効く。

    ``Path.expanduser()`` / ``os.path.expanduser()`` は ``Path.home()`` ではなく環境変数
    ``HOME`` / ``USERPROFILE`` を見るので、そちらも同じ一時ディレクトリへ向ける
    (将来 ``~`` の展開方法が変わっても実ホームへ届かない)。
    """
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))


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
