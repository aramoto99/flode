"""``pyflw.__version__`` と ``pyproject.toml`` の version が一致することを検証する
(ADR-0013 §V-A)。

リリースのたびに両者を同 PR で更新する運用のため、ズレた状態で merge されないよう
CI でガードする。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pyflw

# ``tomllib`` is 3.11+; fall back to ``tomli`` on 3.10 (added to dev extras
# below, ADR-0013 §V-A).
if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - tested only when running on 3.10
    import tomli as tomllib  # type: ignore[no-redef, import-not-found]


def test_version_matches_pyproject() -> None:
    project_root = Path(__file__).parent.parent
    pyproject_path = project_root / "pyproject.toml"
    assert pyproject_path.is_file(), f"pyproject.toml not found at {pyproject_path}"
    with pyproject_path.open("rb") as fh:
        project_meta = tomllib.load(fh)
    project_version = project_meta["project"]["version"]
    assert pyflw.__version__ == project_version, (
        f"Version mismatch: pyflw.__version__={pyflw.__version__!r}, "
        f"pyproject.toml [project].version={project_version!r}. "
        "Update both in the same PR (ADR-0013 §V-A)."
    )
