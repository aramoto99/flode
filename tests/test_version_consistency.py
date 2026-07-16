"""``flode.__version__`` と ``pyproject.toml`` + frontend ``package.json`` の version が
一致することを検証する (ADR-0013 §V-A、ADR-0032 §6-A で 3 ファイル整合に拡張)。

リリースのたびに 3 ファイルを同コミットで更新する運用のため、ズレた状態で merge
されないよう CI でガードする。``tools/check_version_sync.py`` と同じ検証ロジックを
pytest 経由でも走らせる (= CI 内 2 箇所で fail-fast)。
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import flode


def test_version_matches_pyproject() -> None:
    project_root = Path(__file__).parent.parent
    pyproject_path = project_root / "pyproject.toml"
    assert pyproject_path.is_file(), f"pyproject.toml not found at {pyproject_path}"
    with pyproject_path.open("rb") as fh:
        project_meta = tomllib.load(fh)
    project_version = project_meta["project"]["version"]
    assert flode.__version__ == project_version, (
        f"Version mismatch: flode.__version__={flode.__version__!r}, "
        f"pyproject.toml [project].version={project_version!r}. "
        "Update all three files (flode/__init__.py + pyproject.toml + "
        "flode/web/frontend/package.json) in the same commit (ADR-0032 §6-A)."
    )


def test_version_matches_frontend_package_json() -> None:
    """frontend ``package.json`` の version も同期する (ADR-0032 §6-A)。"""
    project_root = Path(__file__).parent.parent
    package_json_path = project_root / "flode" / "web" / "frontend" / "package.json"
    assert package_json_path.is_file(), f"package.json not found at {package_json_path}"
    package_json = json.loads(package_json_path.read_text(encoding="utf-8"))
    package_version = package_json["version"]
    assert flode.__version__ == package_version, (
        f"Version mismatch: flode.__version__={flode.__version__!r}, "
        f"package.json version={package_version!r}. "
        "Update all three files (flode/__init__.py + pyproject.toml + "
        "flode/web/frontend/package.json) in the same commit (ADR-0032 §6-A)."
    )
