"""``[project.scripts]`` の console script 定義テスト (SPEC-0021)。

``flode`` が唯一のコマンドとして ``flode.server.cli:main`` を指すことを
pyproject.toml から検証する。旧コマンド ``pyflw`` / ``pyflw-server`` は
プロジェクト名変更 (v0.43.0) で削除済み。
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_scripts() -> dict[str, str]:
    with (_REPO_ROOT / "pyproject.toml").open("rb") as f:
        return dict(tomllib.load(f)["project"]["scripts"])


class TestConsoleScripts:
    def test_flode_is_the_only_command(self) -> None:
        scripts = _load_scripts()
        assert scripts == {"flode": "flode.server.cli:main"}

    def test_legacy_commands_removed(self) -> None:
        scripts = _load_scripts()
        assert "pyflw" not in scripts
        assert "pyflw-server" not in scripts
