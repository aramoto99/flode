"""userblocks テスト共通の隔離 fixture。

すべてのテストで、読み込み状態 (管理型表・``sys.modules``・``sys.meta_path``・allowlist) を
テスト前の状態に戻す。ユーザーブロックの .py は必ず ``tmp_path`` 配下に作る。
"""

from __future__ import annotations

import textwrap
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from tests.userblocks._isolation import restore_userblocks_state

WriteFile = Callable[[str, str], Path]


@pytest.fixture(autouse=True)
def isolate_userblocks(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """読み込み状態をテストごとに元へ戻す。"""
    yield from restore_userblocks_state(tmp_path_factory)


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
