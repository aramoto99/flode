"""ブロック / モデル ID の検証・正規化ユーティリティ。

ADR-0071: Block ID は Unicode 識別子 (UAX #31 XID、Python の
``str.isidentifier()`` と同じ判定) を許容する。日本語などの非 ASCII 文字が
使える一方、空白・記号・絵文字・制御文字は XID の帰結として拒否される。

- 保存 / 表示 / 参照キーは **NFC** 形 (``normalize_block_id``)。正規化は
  「外から文字列が入る境界」(``Block.__init__`` / ``Simulator.rename`` /
  ``persistence`` の load) でのみ行い、``validate_block_id`` は正規化しない
  純粋述語に保つ (SSOT、ADR-0071 §(3))。
- 同一スコープ内の重複判定は **NFKC fold key** (``fold_block_id``) で行う。
  ``Gain_1`` と全角の ``Gain_１`` のような「見た目が近く実体が違う id」の
  共存を拒否するための比較専用キーで、保存はしない (ADR-0071 §(2))。

ADR-0004 の ASCII 制約 ``[A-Za-z_][A-Za-z0-9_]*`` は ADR-0071 により Amend
された (最大長 64 は code point 数として据え置き)。

ADR-0011 §(1) で導入された ``validate_model_id`` は ADR-0071 の対象外で、
ASCII のまま維持する (ファイル名は OS 依存の正規化差を抱えるため)。
"""

from __future__ import annotations

import keyword
import logging
import re
import unicodedata

from ..exceptions import BlockSpecError

_MAX_LEN = 64  # NFC 後の code point 数 (ADR-0004 の 64 を数値として据え置き)
# ADR-0071 §(1)-(4): 明示拒否する Unicode カテゴリ。
# Cc/Cf (制御・書式: bidi 上書き, ZWJ/ZWNJ 等の Trojan Source 系), Cs (サロゲート),
# Co (私用), Cn (未割当), Zs/Zl/Zp (空白・区切り)。
# 注意: この検査は「XID と重複する保険」では **ない**。ZWJ (U+200D) / ZWNJ
# (U+200C) は ``str.isidentifier()`` を **通過する** (実測、CPython 3.13) ため、
# 不可視文字入り id を防ぐ唯一の防波堤がこの Cf 検査である。削除不可
# (security-reviewer 指摘、tests/data/block_id_cases.json で回帰固定)。
_FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zs", "Zl", "Zp"})
# ADR-0011 §(1): モデル ID 用、ハイフン許容、最大 128 chars。``..`` や ``/`` を
# 禁止して Path traversal を防ぐ目的。
_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_logger = logging.getLogger("flode.identifiers")


def normalize_block_id(raw: str) -> str:
    """ブロック ID 候補を保存形 (NFC) に正規化する (検証はしない)。

    入口層 (``Block.__init__`` / ``Simulator.rename`` / persistence load /
    GUI の rename) のみが呼ぶ。内部では二度と正規化しない (ADR-0071 §(3))。

    Args:
        raw: 正規化対象の文字列。

    Returns:
        NFC 正規化済み文字列。ASCII 入力は恒等。
    """
    return unicodedata.normalize("NFC", raw)


def fold_block_id(nfc_id: str) -> str:
    """重複判定専用の NFKC fold key を返す (保存しない、ADR-0071 §(2))。

    全角/半角・互換文字・結合文字による「見た目が近く実体が違う id」を同一視
    するための比較キー。``Gain_1`` と ``Gain_１`` (全角数字)、``ソクド`` と
    ``ｿｸﾄﾞ`` (半角カナ) は同じ fold key になる。case-sensitive は維持する
    (case-fold はしない)。

    Args:
        nfc_id: NFC 正規化済みの ID 文字列。

    Returns:
        NFKC fold key (比較専用の内部文字列)。
    """
    return unicodedata.normalize("NFKC", nfc_id)


def validate_block_id(block_id: str) -> None:
    """ブロック ID 文字列を検証する (純粋述語、正規化はしない)。

    ADR-0071 §(1) の 5 条件: 非空 / NFC 済 / ``str.isidentifier()``
    (UAX #31 XID) / 禁止カテゴリなし / 64 code points 以内。

    Args:
        block_id: 検証対象の ID 文字列 (NFC 正規化済であること)。

    Raises:
        BlockSpecError: 型違い、空文字、NFC 未正規化、文字集合違反、
            または 64 code points 超過。

    Note:
        Python keyword (例: ``for``, ``class``) と一致する場合は warning を
        発するが有効な ID として許可する (ADR-0071 §(4): codegen は id を
        変数名に使わないため error には昇格しない)。
    """
    if not isinstance(block_id, str):
        raise BlockSpecError(f"Block id must be a string, got {type(block_id).__name__}")
    if not block_id:
        raise BlockSpecError("Block id must not be empty")
    if len(block_id) > _MAX_LEN:
        # 巨大入力の丸ごと echo によるログ/レスポンス増幅を避けるため先頭のみ表示
        raise BlockSpecError(
            f"Block id {block_id[:_MAX_LEN]!r}... (length {len(block_id)}) "
            f"exceeds max length {_MAX_LEN} (code points)"
        )
    if not unicodedata.is_normalized("NFC", block_id):
        raise BlockSpecError(
            f"Block id {block_id!r} is not NFC-normalized. Pass it through "
            f"normalize_block_id() first (ADR-0071: ids are stored in NFC form)."
        )
    if not block_id.isidentifier():
        raise BlockSpecError(
            f"Block id {block_id!r} contains invalid characters. Allowed: "
            f"letters (including non-ASCII, e.g. Japanese), digits, and '_', "
            f"starting with a letter or '_' (Unicode identifier, UAX #31). "
            f"Spaces, symbols, and emoji are not allowed; use '_' instead of "
            f"spaces (ADR-0071)."
        )
    for ch in block_id:
        if unicodedata.category(ch) in _FORBIDDEN_CATEGORIES:
            raise BlockSpecError(
                f"Block id {block_id!r} contains a forbidden character "
                f"U+{ord(ch):04X} (control/format/space/unassigned characters "
                f"are rejected, ADR-0071)."
            )
    if keyword.iskeyword(block_id):
        _logger.warning(
            "Block id %r matches a Python keyword. It is allowed (generated "
            "code never uses ids as variable names, ADR-0071), but consider "
            "renaming for clarity.",
            block_id,
        )


def validate_model_id(model_id: str) -> None:
    """モデルファイル ID (``.flw.json`` のファイル名 stem) を検証する (ADR-0011 §(1))。

    ``[A-Za-z0-9_-]{1,128}`` のみ許容し、``..`` / ``/`` / 空文字を拒否することで
    Path traversal を防ぐ。Block ID (ADR-0071 で非 ASCII 許容) と異なり ASCII の
    まま維持する: ファイル名は OS の正規化差 (macOS の NFD、Windows の
    case-insensitive) を抱え込むため。

    Args:
        model_id: 検証対象の ID 文字列。

    Raises:
        BlockSpecError: 文字集合違反、空文字、または長さ違反。
    """
    if not isinstance(model_id, str):
        raise BlockSpecError(f"Model id must be a string, got {type(model_id).__name__}")
    if not model_id:
        raise BlockSpecError("Model id must not be empty")
    if not _MODEL_ID_PATTERN.match(model_id):
        raise BlockSpecError(
            f"Model id {model_id!r} contains invalid characters. "
            f"Allowed: ^[A-Za-z0-9_-]{{1,128}}$ (no '..', '/', spaces, or non-ASCII)."
        )
