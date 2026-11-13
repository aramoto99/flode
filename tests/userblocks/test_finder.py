"""予約ルートの finder とソース専用 loader (ADR-0081 §1-A / §1-C)。"""

from __future__ import annotations

import importlib
import inspect
import os
import py_compile
import sys
import textwrap
import traceback
from pathlib import Path

import pytest

from flode.userblocks._finder import FinderRoots, ReservedRootFinder, SourceOnlyLoader


@pytest.fixture
def finder() -> ReservedRootFinder:
    """``sys.meta_path`` の先頭に入れた finder (後始末は conftest が meta_path を戻す)。"""
    f = ReservedRootFinder()
    sys.meta_path.insert(0, f)
    return f


def _write(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return path


class TestWorkspaceRoot:
    def test_imports_module_and_relative_helper(self, finder: ReservedRootFinder, tmp_path: Path):
        _write(tmp_path / "common.py", "SCALE = 3\n")
        _write(tmp_path / "filters.py", "from . import common\nVALUE = common.SCALE * 2\n")
        finder.roots = FinderRoots(workspace=tmp_path)

        mod = importlib.import_module("flode_ws.filters")

        assert mod.VALUE == 6
        assert isinstance(mod.__spec__.loader, SourceOnlyLoader)
        assert Path(mod.__file__) == tmp_path / "filters.py"

    def test_subpackage_with_init_and_parent_relative_import(
        self, finder: ReservedRootFinder, tmp_path: Path
    ):
        _write(tmp_path / "common.py", "BASE = 10\n")
        _write(tmp_path / "control" / "__init__.py", "INIT_RAN = True\n")
        _write(tmp_path / "control" / "pid.py", "from ..common import BASE\nGAIN = BASE + 1\n")
        finder.roots = FinderRoots(workspace=tmp_path)

        pid = importlib.import_module("flode_ws.control.pid")

        assert pid.GAIN == 11
        assert sys.modules["flode_ws.control"].INIT_RAN is True

    def test_root_init_is_not_executed(self, finder: ReservedRootFinder, tmp_path: Path):
        _write(tmp_path / "__init__.py", "raise RuntimeError('root init must not run')\n")
        _write(tmp_path / "a.py", "X = 1\n")
        finder.roots = FinderRoots(workspace=tmp_path)

        assert importlib.import_module("flode_ws.a").X == 1
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("flode_ws.__init__")

    def test_folder_without_init_is_not_a_package(self, finder: ReservedRootFinder, tmp_path: Path):
        _write(tmp_path / "loose" / "mod.py", "X = 1\n")
        finder.roots = FinderRoots(workspace=tmp_path)

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("flode_ws.loose")
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("flode_ws.loose.mod")

    def test_name_must_match_case_exactly(self, finder: ReservedRootFinder, tmp_path: Path):
        _write(tmp_path / "filters.py", "X = 1\n")
        finder.roots = FinderRoots(workspace=tmp_path)

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("flode_ws.Filters")

    def test_missing_module_is_not_found(self, finder: ReservedRootFinder, tmp_path: Path):
        finder.roots = FinderRoots(workspace=tmp_path)
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("flode_ws.nothing")

    def test_does_not_create_pycache(self, finder: ReservedRootFinder, tmp_path: Path):
        _write(tmp_path / "a.py", "X = 1\n")
        _write(tmp_path / "pkg" / "__init__.py", "")
        _write(tmp_path / "pkg" / "b.py", "Y = 2\n")
        finder.roots = FinderRoots(workspace=tmp_path)

        importlib.import_module("flode_ws.a")
        importlib.import_module("flode_ws.pkg.b")

        assert not list(tmp_path.rglob("__pycache__"))

    def test_stale_bytecode_is_ignored(self, finder: ReservedRootFinder, tmp_path: Path):
        """同じ秒・同じサイズで書き換えても、古い pyc ではなくソースが使われる (F-24)。"""
        path = _write(tmp_path / "a.py", "X = 1\n")
        py_compile.compile(str(path), cfile=importlib.util.cache_from_source(str(path)))
        stat = path.stat()
        path.write_text("X = 2\n", encoding="utf-8")
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        finder.roots = FinderRoots(workspace=tmp_path)

        assert importlib.import_module("flode_ws.a").X == 2

    def test_getsource_and_traceback_show_user_lines(
        self, finder: ReservedRootFinder, tmp_path: Path
    ):
        _write(tmp_path / "a.py", "def f():\n    raise ValueError('boom')\n")
        finder.roots = FinderRoots(workspace=tmp_path)
        mod = importlib.import_module("flode_ws.a")

        assert "raise ValueError" in inspect.getsource(mod.f)
        with pytest.raises(ValueError) as info:
            mod.f()
        last = traceback.extract_tb(info.value.__traceback__)[-1]
        assert last.lineno == 2
        assert last.line == "raise ValueError('boom')"


class TestScope:
    def test_other_names_are_left_to_other_finders(
        self, finder: ReservedRootFinder, tmp_path: Path
    ):
        finder.roots = FinderRoots(workspace=tmp_path)
        assert finder.find_spec("json") is None
        assert finder.find_spec("flode_wsx") is None

    def test_inactive_root_is_not_claimed(self, finder: ReservedRootFinder):
        assert finder.find_spec("flode_ws") is None
        assert finder.find_spec("flode_dirs") is None

    def test_dirs_root(self, finder: ReservedRootFinder, tmp_path: Path):
        lab = tmp_path / "lab"
        _write(lab / "io.py", "Z = 5\n")
        finder.roots = FinderRoots(dirs={"lab": lab}, dirs_enabled=True)

        assert importlib.import_module("flode_dirs.lab.io").Z == 5
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("flode_dirs.other")
