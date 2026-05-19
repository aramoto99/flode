"""``tests/server/`` 共通 fixtures。"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """``Path.home()`` を ``tmp_path`` 配下に切り替えて ``~/.pyflw/config.toml``
    の暗黙探索を隔離する (SPEC-0004)。

    pyflw.server.config の ``_expand_home`` / ``default_user_config_path`` は
    ``Path.home()`` 経由なので、この monkeypatch 1 つで CLI / Resolver / template
    の全経路の暗黙 home 解決をテスト隔離できる。
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home
