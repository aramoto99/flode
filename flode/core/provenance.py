"""ブロック entry の任意キー ``provenance`` (ライブラリ由来) の検証と受け渡し (ADR-0080 §A3)。

由来は「このブロックはどのライブラリのどのエントリの第何版から置かれたか」を表す
**情報のみ** の記録で、モデル JSON のブロック entry 直下に置かれる::

    {"id": "PID", "type": "...", "params": {...},
     "provenance": {"library": "user", "library_uid": "8c1e…", "entry": "pid", "revision": 3}}

不変条件:

* **意味論に影響しない**: シミュレーション・承認 digest・信号面 (shape / dtype) 解決は
  由来を一切読まない。読むのは永続化 (``Block.to_dict`` と各 ``from_dict``) だけ。
* **壊れた由来はロードを妨げない**: 型が不正なら WARNING を出して捨てる
  (``ModelLoadError`` にしない。モデルは由来が無くても自己完結している)。
* **開いた dict**: 未知の追加キーは JSON 互換である限りそのまま保持する
  (後の版がキーを足しても、古い版の load → save で落とさない)。

モデル ``schema_version`` はこのキーのために bump しない (無視しても意味論が変わらない
optional キー)。
"""

from __future__ import annotations

import copy
import logging
import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - 循環 import 回避 (block.py が本モジュールを import する)
    from .block import Block

_logger = logging.getLogger("flode.core.provenance")

#: ブロック entry 上の由来キー名。
PROVENANCE_KEY: str = "provenance"

#: 由来の必須キーのうち、空でない文字列でなければならないもの。
PROVENANCE_REQUIRED_STR_KEYS: tuple[str, ...] = ("library", "entry")

#: 由来の任意キーのうち、存在するなら空でない文字列でなければならないもの
#: (``library_uid`` を持たないライブラリ由来では省略される)。
PROVENANCE_OPTIONAL_STR_KEYS: tuple[str, ...] = ("library_uid",)

#: 由来の必須キー: エントリ内容の世代 (整数、bool 不可)。
PROVENANCE_REVISION_KEY: str = "revision"

#: ``revision`` の最小値 (ライブラリエントリの revision は 1 始まり)。
MIN_PROVENANCE_REVISION: int = 1

#: 由来の値として許す入れ子の最大深さ (由来 dict 自身を深さ 1 と数える)。
#: 開いた dict の追加キーが際限なく深い構造を持ち込むのを防ぐ。
MAX_PROVENANCE_DEPTH: int = 8

#: WARNING に載せる block id の最大文字数 (id はロード時点で未検証・任意長のため丸める)。
_MAX_LOGGED_ID_CHARS: int = 80


def _json_incompatibility(value: Any, depth: int) -> str | None:
    """``value`` が JSON 互換でない理由を返す (互換なら ``None``)。

    許す型は ``None`` / ``bool`` / ``int`` / 有限の ``float`` / ``str`` / ``list`` /
    キーが ``str`` の ``dict`` のみ。``tuple`` や numpy スカラは受け付けない
    (JSON から読んだ値には現れず、黙って別の型へ変換すると round-trip が崩れる)。
    """
    if depth > MAX_PROVENANCE_DEPTH:
        return f"nesting deeper than {MAX_PROVENANCE_DEPTH} levels"
    if value is None or isinstance(value, (bool, int, str)):
        return None
    if isinstance(value, float):
        return None if math.isfinite(value) else "non-finite float"
    if isinstance(value, list):
        for item in value:
            reason = _json_incompatibility(item, depth + 1)
            if reason is not None:
                return reason
        return None
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                return f"non-string key of type {type(key).__name__}"
            reason = _json_incompatibility(item, depth + 1)
            if reason is not None:
                return reason
        return None
    return f"non-JSON value of type {type(value).__name__}"


def _invalid_reason(raw: Any) -> str | None:
    """由来 ``raw`` が受け入れられない理由を返す (受け入れ可能なら ``None``)。

    理由には **値そのものを含めない** (壊れた値は任意長・任意内容でありうるため、
    ログへ増幅しない)。型名とキー名だけを載せる。
    """
    if not isinstance(raw, dict):
        return f"must be an object, got {type(raw).__name__}"
    for key in PROVENANCE_REQUIRED_STR_KEYS:
        if key not in raw:
            return f"missing required key {key!r}"
    if PROVENANCE_REVISION_KEY not in raw:
        return f"missing required key {PROVENANCE_REVISION_KEY!r}"
    for key in (*PROVENANCE_REQUIRED_STR_KEYS, *PROVENANCE_OPTIONAL_STR_KEYS):
        if key not in raw:
            continue
        value = raw[key]
        if not isinstance(value, str):
            return f"{key!r} must be a string, got {type(value).__name__}"
        if not value:
            return f"{key!r} must not be empty"
    revision = raw[PROVENANCE_REVISION_KEY]
    # bool は int のサブクラス。True が黙って revision 1 になるのを防ぐ
    if isinstance(revision, bool) or not isinstance(revision, int):
        return f"{PROVENANCE_REVISION_KEY!r} must be an integer, got {type(revision).__name__}"
    if revision < MIN_PROVENANCE_REVISION:
        return f"{PROVENANCE_REVISION_KEY!r} must be >= {MIN_PROVENANCE_REVISION}"
    return _json_incompatibility(raw, depth=1)


def sanitize_provenance(
    raw: Any, *, block_id: object, parent_id: object | None = None
) -> dict[str, Any] | None:
    """ブロック entry の ``provenance`` 値を浅く検証し、保持用のコピーを返す。

    検証するのは形だけ: dict であること、``library`` / ``entry`` が空でない文字列、
    ``library_uid`` (任意) が空でない文字列、``revision`` が 1 以上の整数 (bool 不可)、
    全体が JSON 互換で入れ子が :data:`MAX_PROVENANCE_DEPTH` 以内であること。
    由来先のライブラリやエントリが実在するかは確認しない。未知の追加キーは保持し、
    キー順も変えない。

    不正な値は例外にせず、WARNING を 1 件出して ``None`` を返す (= 由来を捨てる)。

    Args:
        raw: entry から取り出した ``provenance`` の値 (任意の JSON 値)。
        block_id: 由来を持つブロックの id (WARNING の文脈用。未検証でよい)。
        parent_id: そのブロックを直接内包する Subsystem の id。トップレベルなら ``None``。

    Returns:
        入力と内容の等しい独立したコピー。不正なら ``None``。
    """
    reason = _invalid_reason(raw)
    if reason is None:
        sanitized: dict[str, Any] = copy.deepcopy(raw)
        return sanitized
    where = f"block {str(block_id)[:_MAX_LOGGED_ID_CHARS]!r}"
    if parent_id is not None:
        where += f" (in subsystem {str(parent_id)[:_MAX_LOGGED_ID_CHARS]!r})"
    _logger.warning(
        "Ignoring invalid %r on %s: %s. The block is loaded without provenance "
        "(provenance is informational and does not affect simulation).",
        PROVENANCE_KEY,
        where,
        reason,
    )
    return None


def attach_provenance(
    block: Block, entry: dict[str, Any], *, parent_id: object | None = None
) -> None:
    """ブロック entry に ``provenance`` があれば検証して ``block`` に載せる。

    ``Simulator.from_dict`` と ``Subsystem._from_dict`` が、entry から構築した直後の
    ブロックに対して呼ぶ唯一の入口。キーが無い entry では何もしない (ログも出さない)。

    Args:
        block: ``entry`` から構築したブロック。
        entry: モデル JSON のブロック entry (``{"id", "type", "params", ...}``)。
        parent_id: ``entry`` を直接内包する Subsystem の id。トップレベルなら ``None``。
    """
    if PROVENANCE_KEY not in entry:
        return
    block._provenance = sanitize_provenance(
        entry[PROVENANCE_KEY], block_id=entry.get("id"), parent_id=parent_id
    )
