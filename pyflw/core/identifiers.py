"""ブロック ID の検証ユーティリティ。

ADR-0004 の文字集合制約 `[A-Za-z_][A-Za-z0-9_]*` (max 64 chars) を強制する。
Python keyword と一致する ID は warning を出す (Phase 3 codegen で error 昇格予定)。
"""

from __future__ import annotations

import keyword
import logging
import re

from ..exceptions import BlockSpecError

_ID_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_LEN = 64
_logger = logging.getLogger("pyflw.identifiers")


def validate_block_id(block_id: str) -> None:
    """ブロック ID 文字列を検証する。

    Args:
        block_id: 検証対象の ID 文字列。

    Raises:
        BlockSpecError: 文字集合違反、空文字、または 64 文字超過。

    Note:
        Python keyword (例: ``for``, ``class``) と一致する場合は warning を発する
        (将来的に Phase 3 codegen で error に昇格する想定)。
    """
    if not isinstance(block_id, str):
        raise BlockSpecError(f"Block id must be a string, got {type(block_id).__name__}")
    if not block_id:
        raise BlockSpecError("Block id must not be empty")
    if len(block_id) > _MAX_LEN:
        raise BlockSpecError(f"Block id {block_id!r} exceeds max length {_MAX_LEN}")
    if not _ID_PATTERN.match(block_id):
        raise BlockSpecError(
            f"Block id {block_id!r} contains invalid characters. "
            f"Allowed: ^[A-Za-z_][A-Za-z0-9_]*$ (Python identifier rules, no spaces, "
            f"slashes, dots, or non-ASCII characters)."
        )
    if keyword.iskeyword(block_id):
        _logger.warning(
            "Block id %r matches a Python keyword. This will cause an error in "
            "Phase 3 code generation; consider renaming.",
            block_id,
        )
