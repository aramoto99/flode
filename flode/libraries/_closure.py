"""エントリ本体の Goto / From 閉包検査 (ADR-0080 §A4-5)。

ライブラリエントリは 「単体で閉じた部品」 でなければならない。本体の部分木の中で
次のどちらかに当たるブロックがあれば、登録・取り込みを拒否する:

* ``From`` の tag が、同じスコープ (同じ ``blocks`` 配列) の Local ``Goto`` で
  解決されない (= 部分木の外の Goto に依存している)
* Global visibility の ``Goto`` を含む (同じエントリを 2 個置くと Global tag が
  重複してモデルを build できなくなる)
* 同じスコープに同じ tag の Local ``Goto`` が複数ある (Simulator が build エラーにする
  ので、置いても実行できない部品になる)

Global ``Goto`` を含む本体はそれだけで拒否されるので、``From`` の解決先として
Global ``Goto`` は数えない。

検査は本体の JSON を走査するだけで、ブロックを構築せずユーザーコードも実行しない。

.. note::

   本 module はパッケージ内部実装。外部からは
   ``flode.libraries.find_goto_from_violations`` を使うこと。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..exceptions import UnknownBlockTypeError
from ._loader import BLOCK_PATH_SEPARATOR, MAX_ENTRY_BLOCK_DEPTH

#: ``Goto`` の tag_visibility の既定値 (params に無いときに仮定する)。
_DEFAULT_TAG_VISIBILITY = "local"
_LOCAL_VISIBILITY = "local"

#: 違反の種別: Global visibility の Goto を含む。
VIOLATION_GLOBAL_GOTO = "global_goto"
#: 違反の種別: From の tag が同一スコープの Local Goto で解決されない。
VIOLATION_UNRESOLVED_FROM = "unresolved_from"
#: 違反の種別: 同一スコープに同じ tag の Local Goto が既にある (2 つ目以降に付く)。
VIOLATION_DUPLICATE_GOTO = "duplicate_goto"


@dataclass(frozen=True)
class GotoFromViolation:
    """閉包検査の違反 1 件。

    Attributes:
        path: 該当ブロックの部分木内パス (``/`` 区切りの block id 列)。
        tag: 該当ブロックの tag。
        reason: :data:`VIOLATION_GLOBAL_GOTO` / :data:`VIOLATION_UNRESOLVED_FROM` /
            :data:`VIOLATION_DUPLICATE_GOTO`。
    """

    path: str
    tag: str
    reason: str


def _scan_scope(
    blocks: list[Any], prefix: str, violations: list[GotoFromViolation], depth: int
) -> None:
    """1 スコープ (``blocks`` 配列) を検査し、入れ子の Subsystem へ再帰する。"""
    from ..blocks.routing import From, Goto
    from ..core.persistence import resolve_block_class

    if depth > MAX_ENTRY_BLOCK_DEPTH:
        # 深すぎる本体は浅い検証 (analyze_entry_block) が先に拒否する
        return
    local_tags: set[str] = set()
    from_blocks: list[tuple[str, str]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_id = str(block.get("id"))
        path = f"{prefix}{BLOCK_PATH_SEPARATOR}{block_id}" if prefix else block_id
        raw_params = block.get("params")
        params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}
        # 壊れた入力では str とは限らない (resolve_block_class が型も検査して拒否する)
        block_type: Any = block.get("type")
        try:
            cls: type | None = resolve_block_class(block_type)
        except UnknownBlockTypeError:
            cls = None  # 未知の型は深い検証 (canonicalize_entry_block) が拒否する
        tag = str(params.get("tag"))
        if cls is not None and issubclass(cls, Goto):
            if params.get("tag_visibility", _DEFAULT_TAG_VISIBILITY) == _LOCAL_VISIBILITY:
                if tag in local_tags:
                    violations.append(GotoFromViolation(path, tag, VIOLATION_DUPLICATE_GOTO))
                local_tags.add(tag)
            else:
                violations.append(GotoFromViolation(path, tag, VIOLATION_GLOBAL_GOTO))
        elif cls is not None and issubclass(cls, From):
            from_blocks.append((path, tag))
        inner = params.get("blocks")
        if isinstance(inner, list):
            _scan_scope(inner, path, violations, depth + 1)
    violations.extend(
        GotoFromViolation(path, tag, VIOLATION_UNRESOLVED_FROM)
        for path, tag in from_blocks
        if tag not in local_tags
    )


def find_goto_from_violations(block: dict[str, Any]) -> list[GotoFromViolation]:
    """エントリ本体の Goto / From が部分木の中で閉じているか検査する。

    Args:
        block: エントリ本体 (``{id, type, params}``)。書き換えない。

    Returns:
        違反の一覧 (走査順)。空なら閉じている。
    """
    violations: list[GotoFromViolation] = []
    params = block.get("params")
    inner = params.get("blocks") if isinstance(params, dict) else None
    if isinstance(inner, list):
        _scan_scope(inner, "", violations, depth=1)
    return violations
