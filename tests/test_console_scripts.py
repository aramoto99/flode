"""``[project.scripts]`` の console script 定義テスト (SPEC-0021)。

``pyflw`` が主コマンド、``pyflw-server`` が互換 alias として、いずれも
``pyflw.server.cli:main`` を指すことを pyproject.toml から検証する。
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_scripts() -> dict[str, str]:
    with (_REPO_ROOT / "pyproject.toml").open("rb") as f:
        return dict(tomllib.load(f)["project"]["scripts"])


class TestConsoleScripts:
    def test_pyflw_is_primary_command(self) -> None:
        scripts = _load_scripts()
        assert scripts["pyflw"] == "pyflw.server.cli:main"

    def test_pyflw_server_alias_kept_for_compatibility(self) -> None:
        scripts = _load_scripts()
        assert scripts["pyflw-server"] == "pyflw.server.cli:main"

    def test_both_point_to_same_entry_point(self) -> None:
        scripts = _load_scripts()
        assert scripts["pyflw"] == scripts["pyflw-server"]
