"""userblocks テスト共通の隔離 fixture。

すべてのテストで、読み込み状態 (管理型表・``sys.modules``・``sys.meta_path``・allowlist) を
テスト前の状態に戻す。ユーザーブロックの .py は必ず ``tmp_path`` 配下に作る。
"""

from __future__ import annotations

import os
import sys
import textwrap
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from flode.core import persistence
from flode.userblocks import _loader

WriteFile = Callable[[str, str], Path]


def _is_under(module: object, base: str) -> bool:
    file = getattr(module, "__file__", None)
    if not isinstance(file, str):
        return False
    return os.path.normcase(os.path.abspath(file)).startswith(base)


@pytest.fixture(autouse=True)
def isolate_userblocks(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """読み込み状態をテストごとに元へ戻す。"""
    base = os.path.normcase(str(tmp_path_factory.getbasetemp().resolve()))
    meta_path_before = list(sys.meta_path)
    modules_before = set(sys.modules)
    allowlist_before = set(persistence._extra_allowed_prefixes)
    table_before = dict(persistence.managed_block_types())
    yield
    if _loader._RELOAD_LOCK.locked():
        _loader._RELOAD_LOCK.release()
    _loader.unload_sources()
    sys.meta_path[:] = meta_path_before
    for name in list(sys.modules):
        if name in modules_before:
            continue
        top = name.split(".", 1)[0]
        if top in persistence.RESERVED_USER_BLOCK_ROOTS or _is_under(sys.modules[name], base):
            del sys.modules[name]
    persistence._extra_allowed_prefixes.clear()
    persistence._extra_allowed_prefixes.update(allowlist_before)
    persistence._replace_managed_block_types(table_before)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """``blocks/`` を持つ空のワークスペース。"""
    ws = tmp_path / "ws"
    (ws / "blocks").mkdir(parents=True)
    return ws


@pytest.fixture
def write_block(workspace: Path) -> WriteFile:
    """``<workspace>/blocks/<rel>`` に (dedent した) ソースを書くヘルパー。"""

    def _write(rel: str, source: str) -> Path:
        path = workspace / "blocks" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source), encoding="utf-8")
        return path

    return _write
