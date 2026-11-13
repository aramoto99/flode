"""ユーザーブロックの読み込み状態をテスト前に戻すヘルパー (userblocks / server の conftest 共用)。

管理型表・``sys.modules``・``sys.meta_path``・allowlist を戻す。ユーザーブロックの .py は
必ず ``tmp_path`` 配下に作る前提で、その配下から import されたモジュールも外す。
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator

import pytest

from flode.core import persistence
from flode.userblocks import _loader


def _is_under(module: object, base: str) -> bool:
    file = getattr(module, "__file__", None)
    if not isinstance(file, str):
        return False
    return os.path.normcase(os.path.abspath(file)).startswith(base)


def restore_userblocks_state(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """``yield`` の前後で読み込み状態を保存・復元する (fixture 本体から ``yield from`` で使う)。"""
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
