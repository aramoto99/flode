"""3 ファイル version 整合性チェック (ADR-0032 §(1)、§6-A)。

検証対象:
  1. ``flode/__init__.py`` の ``__version__``
  2. ``pyproject.toml`` の ``[project] version``
  3. ``flode/web/frontend/package.json`` の ``version``

CI (push 時) と release.yml / pypi-publish.yml (tag push 時) の両方で実行する。
整合 OK で exit 0、mismatch で exit 1 + diagnostic message を stderr へ。

実行方法 (リポジトリルートから):

    python tools/check_version_sync.py
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path


_VERSION_LINE_RE = re.compile(r'^\s*__version__\s*=\s*"([^"]+)"')


def _read_init_version(repo_root: Path) -> str:
    """``flode/__init__.py`` の ``__version__ = "X.Y.Z"`` 行を抽出する。

    末尾コメント (``  # ADR-0029: ...``) は許容し、文字列リテラル部分のみ取り出す。
    """
    init_text = (repo_root / "flode" / "__init__.py").read_text(encoding="utf-8")
    for line in init_text.splitlines():
        m = _VERSION_LINE_RE.match(line)
        if m:
            return m.group(1)
    raise RuntimeError("flode/__init__.py に __version__ = \"...\" が見つかりません")


def _read_pyproject_version(repo_root: Path) -> str:
    pyproject_path = repo_root / "pyproject.toml"
    with pyproject_path.open("rb") as fh:
        meta = tomllib.load(fh)
    version = meta["project"]["version"]
    if not isinstance(version, str):
        raise RuntimeError(f"pyproject.toml の version が string でない: {version!r}")
    return version


def _read_package_json_version(repo_root: Path) -> str:
    package_json_path = (
        repo_root / "flode" / "web" / "frontend" / "package.json"
    )
    data = json.loads(package_json_path.read_text(encoding="utf-8"))
    version = data["version"]
    if not isinstance(version, str):
        raise RuntimeError(f"package.json の version が string でない: {version!r}")
    return version


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent

    versions = {
        "flode/__init__.py": _read_init_version(repo_root),
        "pyproject.toml": _read_pyproject_version(repo_root),
        "flode/web/frontend/package.json": _read_package_json_version(repo_root),
    }

    if len(set(versions.values())) != 1:
        print("ERROR: version mismatch detected (ADR-0032 §6-A):", file=sys.stderr)
        for path, ver in versions.items():
            print(f"  {path}: {ver!r}", file=sys.stderr)
        print(
            "Update all three files to the same version in the same commit, "
            "then re-run.",
            file=sys.stderr,
        )
        return 1

    print(f"Version sync OK: {next(iter(versions.values()))} (3 files matched)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
