"""ライブラリの書き込み・取り込み・registry の実行時差し替え (ADR-0080 §A4〜§A6)。

:class:`LibraryStore` はサーバが持つライブラリ registry の唯一の所有者で、次を集約する:

* **書き込みの可否** (loopback bind か / ユーザーライブラリが有効か) の判定
* **書き込み先 path** の組み立てと包含確認。クライアントからは path を一切受け取らない。
  書き込むのは ``<user_library_dir>/user.flwlib.json`` と
  ``<user_library_dir>/imported/<サーバ生成名>.flwlib.json`` の 2 種類だけ
* **並行制御**: ``threading.Lock`` 1 本で全書き込みを直列化する (サーバは単一プロセスで、
  ルートは threadpool で動く同期関数)。読み取りはロックを取らず :attr:`LibraryStore.registry`
  の参照を 1 回読むだけ。registry は in-place で変更せず、新しいものを組み立てて差し替える
* **競合検出**: ``expected_revision`` と、読み込み時点の ``(size, mtime_ns)`` によるディスク上の
  変更検知
* **壊れたファイルの保護**: 読めない / 新しすぎるユーザーライブラリには書き込まない
* **登録・取り込みの検証**: 深い検証 (``serialization_build`` 区間内での構築) と Goto / From の
  閉包検査。どの経路でも PythonFunction のユーザーコードは実行しない
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import secrets
import threading
import unicodedata
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ..exceptions import (
    LibraryChangedOnDiskError,
    LibraryEntryConflictError,
    LibraryEntryInvalidError,
    LibraryEntryMissingError,
    LibraryEntryNameConflictError,
    LibraryFileError,
    LibraryFileInvalidError,
    LibraryNameConflictError,
    LibraryNotFoundError,
    LibraryPathUnsafeError,
    LibraryReadOnlyError,
    LibrarySchemaTooNewError,
    LibraryWriteError,
    LibraryWriteForbiddenError,
    PathTraversalError,
    UserLibraryCorruptError,
    UserLibraryDisabledError,
)
from ..libraries import (
    CURRENT_LIBRARY_SCHEMA_VERSION,
    Library,
    LibraryEntry,
    atomic_write_text,
    backup_path_for,
    canonicalize_entry_block,
    find_goto_from_violations,
    load_library,
    move_to_backup,
    serialize_library,
    utc_timestamp,
    validate_library,
    write_text_exclusive,
)
from ..libraries._loader import DEFAULT_ENTRY_REVISION, analyze_entry_block
from .library_registry import (
    IMPORTED_DIRNAME,
    ORIGIN_IMPORTED,
    ORIGIN_USER,
    RESERVED_ENTRY_IDS,
    RESERVED_LIBRARY_NAMES,
    USER_LIBRARY_FILENAME,
    USER_LIBRARY_NAME,
    LibraryRegistry,
    build_library_registry,
    reserved_entry_id_rejection,
    resolve_uid_conflicts,
    sort_by_origin,
)
from .security.paths import ensure_direct_child, is_windows_reserved_name

_logger = logging.getLogger("flode.server.library_store")

# ----------------------------------------------------------------------------
# 定数
# ----------------------------------------------------------------------------

#: 書き込みルートで受け付ける JSON の入れ子の最大深さ (ADR-0080 §A4-4)。
MAX_LIBRARY_JSON_DEPTH = 128

#: エントリの表示名の最大文字数 (SPEC-0032 §1.2)。
MAX_DISPLAY_NAME_CHARS = 64
#: エントリの説明の最大文字数 (SPEC-0032 §1.2)。
MAX_DESCRIPTION_CHARS = 1000
#: エントリの分類 (``category_suffix``) の最大文字数。
MAX_CATEGORY_SUFFIX_CHARS = 64
#: 表示名から生成するエントリ id の最大文字数 (採番の接尾辞を除く)。
MAX_ENTRY_ID_CHARS = 40
#: 取り込みで受け付けるライブラリ名の最大文字数。
MAX_IMPORT_LIBRARY_NAME_CHARS = 64
#: 取り込みで受け付けるエントリ id の最大文字数 (生成する id より長い手書きの id も許す)。
MAX_IMPORT_ENTRY_ID_CHARS = 64

#: schema を上げて書き戻す前に 1 回だけ作るバックアップの接尾辞 (ADR-0080 §A6-2)。
PRE_V4_BACKUP_SUFFIX = ".pre-v4.bak"

#: GUI が作るユーザーライブラリの表示名 (SPEC-0032 §1.1)。
USER_LIBRARY_DISPLAY_NAME = "My Blocks"
USER_LIBRARY_DISPLAY_NAME_I18N: Mapping[str, str] = {"en": "My Blocks", "ja": "マイブロック"}

#: 取り込みファイル名 / 書き出しファイル名の slug の最大文字数 (ADR-0080 §A6-4)。
FILE_SLUG_MAX_CHARS = 40
#: slug が空になったときの代替名。
FILE_SLUG_FALLBACK = "library"
#: slug が Windows の予約デバイス名に当たったときの接頭辞。
FILE_SLUG_RESERVED_PREFIX = "lib-"
#: ライブラリファイルの拡張子。
LIBRARY_FILE_SUFFIX = ".flwlib.json"
# 取り込みファイル名に付ける乱数のバイト数 (hex で 8 桁)。
_IMPORT_TOKEN_BYTES = 4
# 取り込みファイル名が衝突したときに乱数を振り直す最大回数。
_IMPORT_NAME_MAX_ATTEMPTS = 8

#: ``user`` ライブラリを書き出すときの改名に使う uid の桁数 (``user-<uid 先頭 8 桁>``)。
EXPORT_UID_PREFIX_CHARS = 8

# 表示名から id を作れなかったときの代替 id。
_ENTRY_ID_FALLBACK = "entry"
# 衝突時の採番の開始値 (``pid`` → ``pid_2``、``PID`` → ``PID (2)``)。
_FIRST_DUPLICATE_NUMBER = 2

#: ``write_disabled_reason`` / エラー詳細に載せる理由文字列の最大文字数。検証エラーの
#: メッセージは外部由来の値を含みうるので、応答とログへ無制限に流さない。
MAX_REASON_CHARS = 500

#: ``library_entry_invalid`` の ``template_args.reason``。
INVALID_REASON_METADATA = "invalid_metadata"
INVALID_REASON_BLOCK = "invalid_block"
INVALID_REASON_UNKNOWN_TYPES = "unknown_types"
INVALID_REASON_GOTO_FROM = "goto_from_not_closed"

#: ``library_name_conflict`` の ``template_args.reason`` / dry-run の ``conflict.reason``。
NAME_CONFLICT_RESERVED = "reserved"
NAME_CONFLICT_EXISTS = "exists"
#: 取り込むライブラリの ``uid`` が既存のライブラリと同じ (名前は違っても拒否する)。
NAME_CONFLICT_UID_EXISTS = "uid_exists"

#: ``library_file_invalid`` の ``template_args.reason``。
FILE_REASON_INVALID_JSON = "invalid_json"
FILE_REASON_TOO_DEEP = "too_deep"
FILE_REASON_INVALID_LIBRARY = "invalid_library"
FILE_REASON_INVALID_NAME = "invalid_name"
FILE_REASON_INVALID_METADATA = "invalid_metadata"
FILE_REASON_RESERVED_ENTRY_ID = "reserved_entry_id"

_SCHEMA_VERSION_PATTERN = re.compile(r"libraries\.v(\d{1,9})")
_NON_FILE_SLUG_RUN = re.compile(r"[^a-z0-9_-]+")
_SEPARATOR_RUN = re.compile(r"[-_]{2,}")
_NON_ALNUM = re.compile(r"[^0-9A-Za-z]")
_UNDERSCORE_RUN = re.compile(r"_{2,}")
# ライブラリ名・エントリ id は REST の path 1 区間になるので、区切り文字を許さない
_PATH_SEPARATORS = ("/", "\\")
# 表示用文字列で不可とする Unicode カテゴリ: Cc (制御) / Cf (書式) / Cs (孤立サロゲート) /
# Zl・Zp (行区切り U+2028・段落区切り U+2029。見た目は改行だが多くの処理系で改行扱い
# されず、1 行の表示を崩せる)
_UNSAFE_CATEGORIES: frozenset[str] = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})
# 表示用文字列で、文字と文字の間に限って許す書式文字: ZWNJ (U+200C) / ZWJ (U+200D)。
# 絵文字の合成 (家族の絵文字など) や、ペルシア語などの正書法に必要
_JOINERS = "‌‍"
_JOINER_REMOVAL = {ord(ch): None for ch in _JOINERS}
# 複数行を許すフィールド (説明) でだけ使える空白類
_MULTILINE_WHITESPACE = "\n\r\t"

# stat の結果 ``(size, mtime_ns)``。ファイルが無ければ ``None``。
_Fingerprint = tuple[int, int] | None


# ----------------------------------------------------------------------------
# 純粋関数
# ----------------------------------------------------------------------------


def _clip(text: str) -> str:
    """``text`` を :data:`MAX_REASON_CHARS` 文字に丸める。"""
    return text if len(text) <= MAX_REASON_CHARS else text[: MAX_REASON_CHARS - 1] + "…"


def _exceeds_json_depth(value: Any, limit: int) -> bool:
    """``value`` の dict / list の入れ子が ``limit`` を超えるか (再帰を使わずに走査する)。"""
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        node, depth = stack.pop()
        if not isinstance(node, (dict, list)):
            continue
        if depth > limit:
            return True
        children: Iterable[Any] = node.values() if isinstance(node, dict) else node
        stack.extend((child, depth + 1) for child in children)
    return False


def parse_bounded_json(text: str | bytes) -> Any:
    """JSON を読み、入れ子が :data:`MAX_LIBRARY_JSON_DEPTH` 以内であることを確かめる。

    Args:
        text: JSON 文字列 (またはその UTF-8 バイト列)。

    Returns:
        ``json.loads`` の結果。

    Raises:
        LibraryFileInvalidError: JSON として読めない、または入れ子が深すぎる
            (``json.loads`` の ``RecursionError`` を含む)。
    """
    try:
        value = json.loads(text)
    except RecursionError as e:
        raise LibraryFileInvalidError(
            f"JSON is nested deeper than {MAX_LIBRARY_JSON_DEPTH} levels",
            reason=FILE_REASON_TOO_DEEP,
        ) from e
    except ValueError as e:  # JSONDecodeError / UnicodeDecodeError
        # int 変換の桁数上限を超える整数 (素の ValueError) もここに来る
        raise LibraryFileInvalidError(
            _clip(f"not valid JSON: {e}"), reason=FILE_REASON_INVALID_JSON
        ) from e
    if _exceeds_json_depth(value, MAX_LIBRARY_JSON_DEPTH):
        raise LibraryFileInvalidError(
            f"JSON is nested deeper than {MAX_LIBRARY_JSON_DEPTH} levels",
            reason=FILE_REASON_TOO_DEEP,
        )
    return value


def normalized_name_key(display_name: str) -> str:
    """同名判定用のキー (前後 trim + NFC + casefold、ADR-0080 §A5)。

    ZWJ / ZWNJ は見えない文字なので、取り除いてからキーにする (``"PID"`` と、間に ZWJ を
    挟んだ ``"PID"`` を同名として扱い、見た目が同じ名前で既存エントリを偽装させない)。
    """
    visible = display_name.translate(_JOINER_REMOVAL)
    return unicodedata.normalize("NFC", visible.strip()).casefold()


def file_slug(name: str) -> str:
    """ライブラリ名からファイル名用の slug を作る (ADR-0080 §A6-4)。

    NFKC → ASCII 小文字 ``[a-z0-9_-]`` に畳み込み、連続する区切りを 1 つにして 40 文字で
    切る。空なら ``library``、Windows の予約デバイス名なら ``lib-`` を前置する。
    """
    folded = unicodedata.normalize("NFKC", name).lower()
    slug = _NON_FILE_SLUG_RUN.sub("-", folded)
    slug = _SEPARATOR_RUN.sub(lambda m: m.group(0)[0], slug)
    slug = slug.strip("-_")[:FILE_SLUG_MAX_CHARS].strip("-_")
    if not slug:
        return FILE_SLUG_FALLBACK
    if is_windows_reserved_name(slug):
        return FILE_SLUG_RESERVED_PREFIX + slug
    return slug


def _has_unsafe_chars(text: str, *, multiline: bool = False, joiners: bool = False) -> bool:
    """文字列に制御文字・書式文字・孤立サロゲート・行区切り文字が含まれるか。

    Unicode カテゴリ Cc (制御文字)・Cf (書式文字。文字順を偽装できる双方向制御やゼロ幅
    文字、Tag 文字を含む)・Cs (孤立サロゲート。UTF-8 で保存できない)・Zl / Zp (行・段落
    区切り) を不可とする。

    Args:
        text: 検査する文字列。
        multiline: 改行とタブを許すか (説明文は複数行)。
        joiners: ZWNJ / ZWJ を**文字と文字の間に限って**許すか (表示用文字列向け)。
            前後のどちらかが文字列の端・空白・別の ZWNJ / ZWJ なら不可 (見えない文字だけで
            名前を水増しさせない)。REST のパスに乗る識別子では ``False`` にする。
    """
    allowed = _MULTILINE_WHITESPACE if multiline else ""
    for index, ch in enumerate(text):
        if ch in allowed or unicodedata.category(ch) not in _UNSAFE_CATEGORIES:
            continue
        if joiners and ch in _JOINERS and 0 < index < len(text) - 1:
            neighbours = (text[index - 1], text[index + 1])
            if not any(n.isspace() or n in _JOINERS for n in neighbours):
                continue
        return True
    return False


def _is_utf8_encodable(value: Any) -> bool:
    """JSON 値 ``value`` をライブラリファイル (UTF-8 の JSON) として保存できるか。

    JSON の ``\\ud800`` のような孤立サロゲートは読み込めるが UTF-8 に符号化できない。
    書き込みの段階で失敗 (500) させず、入口で拒否するために使う。
    """
    try:
        json.dumps(value, ensure_ascii=False).encode("utf-8")
    except (UnicodeEncodeError, TypeError, ValueError):
        return False
    return True


def _entry_id_slug(display_name: str) -> str:
    """表示名からエントリ id の候補を作る。

    Unicode の英数字と結合文字 (カテゴリ M*: 母音記号・濁点など、語の一部) を残し、
    それ以外の並びは ``_`` 1 つに畳む。
    """
    folded = unicodedata.normalize("NFKC", display_name).casefold()
    kept = "".join(
        ch if ch.isalnum() or unicodedata.category(ch).startswith("M") else "_" for ch in folded
    )
    slug = _UNDERSCORE_RUN.sub("_", kept).strip("_")[:MAX_ENTRY_ID_CHARS].strip("_")
    return slug or _ENTRY_ID_FALLBACK


def _unique_entry_id(display_name: str, taken: set[str]) -> str:
    """既存 id・予約 id と衝突しないエントリ id を返す (衝突時は ``_2``, ``_3``, …)。"""
    base = _entry_id_slug(display_name)
    unavailable = taken | RESERVED_ENTRY_IDS
    if base not in unavailable:
        return base
    number = _FIRST_DUPLICATE_NUMBER
    while f"{base}_{number}" in unavailable:
        number += 1
    return f"{base}_{number}"


def _unique_display_name(display_name: str, taken_keys: set[str]) -> str:
    """既存の表示名と重ならない名前を返す (``PID`` → ``PID (2)``、上限文字数に収める)。"""
    number = _FIRST_DUPLICATE_NUMBER
    while True:
        suffix = f" ({number})"
        candidate = display_name[: MAX_DISPLAY_NAME_CHARS - len(suffix)].rstrip() + suffix
        if normalized_name_key(candidate) not in taken_keys:
            return candidate
        number += 1


def _is_newer_schema_version(version: object) -> bool:
    """``version`` が現行より新しいライブラリ schema 版 (``libraries.v<N>``) か。"""
    if not isinstance(version, str):
        return False
    declared = _SCHEMA_VERSION_PATTERN.fullmatch(version)
    current = _SCHEMA_VERSION_PATTERN.fullmatch(CURRENT_LIBRARY_SCHEMA_VERSION)
    return declared is not None and current is not None and int(declared[1]) > int(current[1])


def _text_problem(
    value: str,
    *,
    max_chars: int,
    required: bool = False,
    multiline: bool = False,
    identifier: bool = False,
) -> str | None:
    """文字列 ``value`` (trim 済み) が制約に反していれば、その説明を返す。

    登録・編集・取り込みで同じ規則を使う: 必須なら空でない、``max_chars`` 以内、
    制御文字・書式文字・行区切り文字を含まない (``multiline`` なら改行とタブは可)。
    表示用文字列では ZWNJ / ZWJ を文字と文字の間に限って許す。``identifier`` (エントリ id
    のように REST のパスに乗る値) では、それも許さない。
    """
    if required and not value:
        return "must not be empty"
    if len(value) > max_chars:
        return f"must be at most {max_chars} characters"
    if _has_unsafe_chars(value, multiline=multiline, joiners=not identifier):
        return "must not contain control or formatting characters"
    return None


def _clean_text(
    value: str, *, field: str, max_chars: int, required: bool = False, multiline: bool = False
) -> str:
    """メタデータの文字列を trim し、制約を確かめる。

    Raises:
        LibraryEntryInvalidError: 必須なのに空、``max_chars`` を超える、または制御文字・
            書式文字を含む。
    """
    cleaned = value.strip()
    problem = _text_problem(cleaned, max_chars=max_chars, required=required, multiline=multiline)
    if problem is not None:
        raise LibraryEntryInvalidError(
            f"{field} {problem}",
            reason=INVALID_REASON_METADATA,
            field=field,
            max_chars=max_chars,
        )
    return cleaned


def _imported_entry_problem(entry: LibraryEntry) -> tuple[str, str] | None:
    """取り込むエントリのメタデータが制約に反していれば ``(フィールド名, 説明)`` を返す。

    表示名・説明・分類には登録時と同じ制約を掛ける (取り込みを、登録では作れない
    エントリを持ち込む抜け道にしない)。id は REST の path 1 区間になるので区切り文字も不可。
    """
    if any(sep in entry.id for sep in _PATH_SEPARATORS):
        return "id", "must not contain path separators"
    id_problem = _text_problem(
        entry.id, max_chars=MAX_IMPORT_ENTRY_ID_CHARS, required=True, identifier=True
    )
    if id_problem is not None:
        return "id", id_problem
    checks: list[tuple[str, str, int, bool, bool]] = [
        ("display_name", entry.display_name.strip(), MAX_DISPLAY_NAME_CHARS, True, False),
        ("description", entry.description, MAX_DESCRIPTION_CHARS, False, True),
        ("category_suffix", entry.category_suffix, MAX_CATEGORY_SUFFIX_CHARS, False, False),
        *(
            ("display_name_i18n", text, MAX_DISPLAY_NAME_CHARS, False, False)
            for text in entry.display_name_i18n.values()
        ),
        *(
            ("description_i18n", text, MAX_DESCRIPTION_CHARS, False, True)
            for text in entry.description_i18n.values()
        ),
    ]
    for field, value, max_chars, required, multiline in checks:
        problem = _text_problem(value, max_chars=max_chars, required=required, multiline=multiline)
        if problem is not None:
            return field, problem
    return None


def _imported_library_problem(library: Library) -> tuple[str, str] | None:
    """取り込むライブラリの表示名・説明が制約に反していれば ``(フィールド名, 説明)`` を返す。"""
    checks: list[tuple[str, str, int, bool]] = [
        ("display_name", library.display_name, MAX_DISPLAY_NAME_CHARS, False),
        ("description", library.description, MAX_DESCRIPTION_CHARS, True),
        *(
            ("display_name_i18n", text, MAX_DISPLAY_NAME_CHARS, False)
            for text in library.display_name_i18n.values()
        ),
        *(
            ("description_i18n", text, MAX_DESCRIPTION_CHARS, True)
            for text in library.description_i18n.values()
        ),
    ]
    for field, value, max_chars, multiline in checks:
        problem = _text_problem(value, max_chars=max_chars, multiline=multiline)
        if problem is not None:
            return field, problem
    return None


def validate_entry_block(block: object, *, entry_id: str | None = None) -> dict[str, Any]:
    """エントリ本体の深い検証を行い、保存する正規形を返す (ADR-0080 §A2 / §A4-5)。

    ブロックを ``serialization_build`` 区間内で構築して ``to_dict()`` を取り直し (ユーザー
    コードは実行されない)、Goto / From が部分木の中で閉じていることを確かめる。
    トップレベルの由来 (``provenance``) だけが落ち、内部のブロックの由来は残る。

    Args:
        block: エントリ本体 (``{id, type, params}``)。書き換えない。
        entry_id: エラー詳細に載せるエントリ id (取り込み時)。

    Returns:
        正規形の本体。

    Raises:
        LibraryEntryInvalidError: 種別外・未知の型・構築不能・Goto / From の非閉包。
    """
    context: dict[str, object] = {} if entry_id is None else {"entry_id": entry_id}
    if not isinstance(block, dict):
        raise LibraryEntryInvalidError(
            "block must be a JSON object", reason=INVALID_REASON_BLOCK, **context
        )
    try:
        info = analyze_entry_block(block)
        if info.unknown_types:
            raise LibraryEntryInvalidError(
                _clip(f"block contains unknown block type(s): {', '.join(info.unknown_types)}"),
                reason=INVALID_REASON_UNKNOWN_TYPES,
                unknown_types=list(info.unknown_types),
                **context,
            )
        canonical = canonicalize_entry_block(block)
    except LibraryFileError as e:
        # 深い検証は構築時の例外を広く LibraryFileError に包む。内部の不具合が 422 に
        # 化けて見えなくならないよう、元の例外の型をログに残す (値は外部由来なので %r)
        cause = e.__cause__
        _logger.warning(
            "library store: entry block rejected by deep validation (%s): %r",
            type(cause).__name__ if cause is not None else type(e).__name__,
            _clip(str(e)),
        )
        raise LibraryEntryInvalidError(_clip(str(e)), reason=INVALID_REASON_BLOCK, **context) from e
    if not _is_utf8_encodable(canonical):
        raise LibraryEntryInvalidError(
            "block contains text that cannot be encoded as UTF-8 (lone surrogate)",
            reason=INVALID_REASON_BLOCK,
            **context,
        )
    violations = find_goto_from_violations(canonical)
    if violations:
        raise LibraryEntryInvalidError(
            "block is not self-contained: it has a From whose tag is not provided by a Goto "
            "in the same scope, a Goto with global visibility, or two Gotos with the same "
            "tag in one scope",
            reason=INVALID_REASON_GOTO_FROM,
            violations=[dataclasses.asdict(v) for v in violations],
            **context,
        )
    return canonical


@dataclasses.dataclass(frozen=True)
class ImportReport:
    """取り込み (dry-run / 本番) の結果。

    Attributes:
        library: 取り込むライブラリ (本番では保存後に読み直したもの)。dry-run では ``uid`` は
            ファイルに書かれていた値のまま (無ければ ``None``。乱数の付与は本番だけ)。
        unknown_types: 本体内部で解決できなかった型 (重複なし・昇順)。本番では常に空。
        conflict: 衝突の種別 (``"reserved"`` / ``"exists"`` / ``"uid_exists"``)。無ければ
            空文字。本番では常に空。
        conflict_name: 衝突している相手の名前 (名前の衝突なら取り込むライブラリの名前、
            ``uid`` の衝突なら同じ ``uid`` を持つ既存ライブラリの名前)。無ければ空文字。
        dry_run: dry-run の結果か。
    """

    library: Library
    unknown_types: tuple[str, ...]
    conflict: str
    conflict_name: str
    dry_run: bool


def export_library(registry: LibraryRegistry, name: str) -> tuple[str, str]:
    """ライブラリを現行 schema で再シリアライズして返す (ADR-0080 §A4-6)。

    ``user`` ライブラリは ``name`` を ``user-<uid 先頭 8 桁>`` に書き換える (予約名の
    ままでは受け取った側が取り込めない)。``uid`` は保持する。ファイルにも registry にも
    触れない。

    Args:
        registry: 呼び出し側がそのリクエストで掴んだ registry。
        name: ライブラリ名。

    Returns:
        ``(ダウンロード用ファイル名, ファイル内容)``。

    Raises:
        LibraryNotFoundError: ``name`` のライブラリが無い。
    """
    library = registry.libraries.get(name)
    if library is None:
        raise LibraryNotFoundError("Library not found", library=_clip(name))
    if registry.origin_of(name) == ORIGIN_USER:
        # uid を持たない手書きのユーザーライブラリには、書き出し物にだけ uid を振る
        uid = library.uid or str(uuid.uuid4())
        prefix = _NON_ALNUM.sub("", uid)[:EXPORT_UID_PREFIX_CHARS].lower()
        library = dataclasses.replace(
            library,
            name=f"{USER_LIBRARY_NAME}-{prefix or secrets.token_hex(_IMPORT_TOKEN_BYTES)}",
            uid=uid,
        )
    return file_slug(library.name) + LIBRARY_FILE_SUFFIX, serialize_library(library)


def _import_conflict(library: Library, registry: LibraryRegistry) -> tuple[str, str]:
    """取り込むライブラリと registry の衝突を ``(種別, 相手の名前)`` で返す (無ければ空文字)。

    名前 (予約名 / 既存名) を先に見て、次に ``uid`` を見る。``uid`` は由来の突合キーなので、
    名前が違っても既存のライブラリと同じ ``uid`` を名乗るものは取り込まない (既存
    ライブラリ由来のブロックの差し替え先に化けられるため)。
    """
    if library.name in RESERVED_LIBRARY_NAMES:
        return NAME_CONFLICT_RESERVED, library.name
    if library.name in registry.libraries:
        return NAME_CONFLICT_EXISTS, library.name
    if library.uid is not None:
        for existing in registry.libraries.values():
            if existing.uid == library.uid:
                return NAME_CONFLICT_UID_EXISTS, existing.name
    return "", ""


# ----------------------------------------------------------------------------
# LibraryStore
# ----------------------------------------------------------------------------


class LibraryStore:
    """ライブラリ registry の所有者。書き込み・取り込み・再読み込みを直列化して行う。

    Args:
        library_paths: ``Settings.library_paths``。
        bundle_builtin: 組み込み ``std`` を読み込むか。
        user_library_dir: ユーザーライブラリのディレクトリ (解決済みの絶対 path)。
            ``None`` ならユーザーライブラリ無効で、ホーム配下を読みも書きもしない。
        write_allowed: 書き込み API を許可するか (CLI が bind host から決める)。
        write_reason: 許可しない理由 (エラーメッセージ用)。
    """

    def __init__(
        self,
        *,
        library_paths: Iterable[Path] = (),
        bundle_builtin: bool = True,
        user_library_dir: Path | None = None,
        write_allowed: bool = False,
        write_reason: str = "",
    ) -> None:
        self._library_paths = [Path(p) for p in library_paths]
        self._bundle_builtin = bundle_builtin
        # 包含確認は解決後の path 同士の比較なので、ここで 1 回だけ解決して固定する
        # (CLI 経由なら解決済み。埋め込み利用で未解決の path を渡されても同じ結果になる)
        self._user_library_dir = None if user_library_dir is None else user_library_dir.resolve()
        self._write_allowed = write_allowed
        self._write_reason = write_reason
        self._lock = threading.Lock()
        self._registry = LibraryRegistry()
        self._user_fingerprint: _Fingerprint = None
        with self._lock:
            self._rebuild()

    # --- 読み取り (ロックを取らない) -----------------------------------------

    @property
    def registry(self) -> LibraryRegistry:
        """現在の registry。呼び出し側は 1 リクエストにつき 1 回だけ読むこと。"""
        return self._registry

    @property
    def user_library_enabled(self) -> bool:
        """ユーザーライブラリが有効か (``user_library_dir`` が設定されているか)。"""
        return self._user_library_dir is not None

    def write_disabled_reason(self, registry: LibraryRegistry) -> str:
        """ユーザーライブラリに書き込めない理由のエラーコードを返す (書き込めるなら空文字)。

        Args:
            registry: 呼び出し側がそのリクエストで掴んだ registry (ユーザーライブラリの
                ファイルの健全性はここから読む。応答の他の部分と同じ時点の状態で答える)。
        """
        if not self._write_allowed:
            return LibraryWriteForbiddenError.code
        if self._user_library_dir is None:
            return UserLibraryDisabledError.code
        return registry.user_library_problem

    def require_write(self, *, needs_user_library: bool = True) -> None:
        """書き込み API が許可されていることを確かめる (ADR-0080 §A4-1)。

        全書き込みルート共通の判定点。ルートの dependency と store の各メソッドの
        両方がこれを呼ぶ。

        Args:
            needs_user_library: ユーザーライブラリのディレクトリに書き込む操作か。
                再読み込みのように書き込まない操作は ``False`` (サーバの設定で許可されて
                いれば、ユーザーライブラリが無効でも通す)。

        Raises:
            LibraryWriteForbiddenError: サーバの設定で書き込みが許可されていない。
            UserLibraryDisabledError: ユーザーライブラリが無効 (``needs_user_library`` 時)。
        """
        if not self._write_allowed:
            raise LibraryWriteForbiddenError(
                "Library write API is disabled: "
                + (self._write_reason or "it was not enabled for this server"),
                reason=self._write_reason,
            )
        if needs_user_library:
            self._writable_directory()

    def _writable_directory(self) -> Path:
        """ユーザーライブラリのディレクトリを返す (無効なら ``UserLibraryDisabledError``)。"""
        if self._user_library_dir is None:
            raise UserLibraryDisabledError(
                "The user library is disabled (no user_library_dir is in effect for this server)"
            )
        return self._user_library_dir

    # --- 書き込み (すべてロック内) -------------------------------------------

    def reload(self) -> LibraryRegistry:
        """起動時と同じ手順で registry を全体再構築する (手動 「再読み込み」)。

        ユーザーライブラリには書き込まないので、書き込みが許可されていれば
        ユーザーライブラリが無効でも実行できる。
        """
        self.require_write(needs_user_library=False)
        with self._lock:
            self._rebuild()
            return self._registry

    def register_entry(
        self,
        *,
        block: object,
        display_name: str,
        description: str = "",
        category_suffix: str = "",
        overwrite_entry_id: str | None = None,
        expected_revision: int | None = None,
        save_as_new: bool = False,
    ) -> tuple[Library, LibraryEntry]:
        """ブロックをユーザーライブラリのエントリとして登録する (新規 / 上書き)。

        Args:
            block: 登録するブロック (``Block.to_dict()`` の出力)。
            display_name: 表示名 (前後 trim 後に 1〜64 文字)。
            description: 説明 (〜1000 文字)。
            category_suffix: 分類 (〜64 文字)。
            overwrite_entry_id: 上書きするエントリの id。指定時は ``expected_revision`` 必須。
            expected_revision: 上書き対象の、呼び出し側が知っている revision。
            save_as_new: 同名のエントリがあっても別エントリとして保存する (表示名に
                ``(2)`` などを付けて重複を避ける)。

        Returns:
            ``(書き込み後のユーザーライブラリ, 登録したエントリ)``。

        Raises:
            LibraryEntryInvalidError: メタデータまたは本体が検証を通らない。
            LibraryEntryNameConflictError: 同名のエントリがある。
            LibraryEntryConflictError: ``expected_revision`` が一致しない。
            LibraryEntryMissingError: ``overwrite_entry_id`` のエントリが無い。
            LibraryApiError: 書き込みの可否・ファイルの健全性に関するその他の拒否。
            LibraryWriteError: ファイルの書き込みに失敗した。
        """
        self.require_write()
        name = _clean_text(
            display_name, field="display_name", max_chars=MAX_DISPLAY_NAME_CHARS, required=True
        )
        description = _clean_text(
            description, field="description", max_chars=MAX_DESCRIPTION_CHARS, multiline=True
        )
        category_suffix = _clean_text(
            category_suffix, field="category_suffix", max_chars=MAX_CATEGORY_SUFFIX_CHARS
        )
        if overwrite_entry_id is not None and (save_as_new or expected_revision is None):
            raise LibraryEntryInvalidError(
                "overwrite_entry_id requires expected_revision and excludes save_as_new",
                reason=INVALID_REASON_METADATA,
                field="overwrite_entry_id",
            )
        if overwrite_entry_id is None and expected_revision is not None:
            # 上書きのつもりで id を付け忘れた要求を、黙って新規登録にしない
            raise LibraryEntryInvalidError(
                "expected_revision is only valid together with overwrite_entry_id",
                reason=INVALID_REASON_METADATA,
                field="expected_revision",
            )
        # 深い検証はロックの外で行う (ファイルにも registry にも触れない純粋な計算)
        canonical = validate_entry_block(block)

        with self._lock:
            path, library, original = self._open_user_library()
            entries = list(library.entries)
            others = [e for e in entries if e.id != overwrite_entry_id]
            same_name = next(
                (
                    e
                    for e in others
                    if normalized_name_key(e.display_name) == normalized_name_key(name)
                ),
                None,
            )
            if overwrite_entry_id is not None:
                index = self._index_of(entries, overwrite_entry_id)
                revision = self._check_revision(entries[index], expected_revision) + 1
                entry_id = overwrite_entry_id
            else:
                index = len(entries)
                revision = DEFAULT_ENTRY_REVISION
                if same_name is not None and save_as_new:
                    name = _unique_display_name(
                        name, {normalized_name_key(e.display_name) for e in entries}
                    )
                    same_name = None
                entry_id = _unique_entry_id(name, {e.id for e in entries})
            if same_name is not None:
                raise LibraryEntryNameConflictError(
                    "An entry with the same name already exists",
                    entry_id=same_name.id,
                    revision=same_name.revision,
                    display_name=same_name.display_name,
                )
            # 表示名・説明を書き換えるので、旧エントリの i18n 表記は引き継がない
            entry = LibraryEntry(
                id=entry_id,
                display_name=name,
                description=description,
                category_suffix=category_suffix,
                block=canonical,
                revision=revision,
                updated_at=utc_timestamp(),
            )
            entries[index : index + 1] = [entry]
            saved = self._save_user_library(path, library, entries, original)
        _logger.info(
            "library store: registered entry %r (revision %d, kind=%s, total entries=%d)",
            entry_id,
            revision,
            entry.kind,
            len(saved.entries),
        )
        return saved, self._entry_of(saved, entry_id)

    def update_entry_metadata(
        self, entry_id: str, changes: Mapping[str, str]
    ) -> tuple[Library, LibraryEntry]:
        """エントリの表示名・説明・分類を更新する (本体と revision は変えない)。

        渡されたフィールドだけを後勝ちで更新する (ADR-0080 §A5)。

        Args:
            entry_id: 対象エントリの id。
            changes: ``display_name`` / ``description`` / ``category_suffix`` の部分集合。

        Returns:
            ``(書き込み後のユーザーライブラリ, 更新したエントリ)``。

        Raises:
            LibraryEntryInvalidError: 値が制約に反する。
            LibraryEntryNameConflictError: 変更後の表示名が別のエントリと重なる。
            LibraryEntryMissingError: ``entry_id`` のエントリが無い。
        """
        self.require_write()
        cleaned: dict[str, Any] = {}
        if "display_name" in changes:
            cleaned["display_name"] = _clean_text(
                changes["display_name"],
                field="display_name",
                max_chars=MAX_DISPLAY_NAME_CHARS,
                required=True,
            )
            cleaned["display_name_i18n"] = {}
        if "description" in changes:
            cleaned["description"] = _clean_text(
                changes["description"],
                field="description",
                max_chars=MAX_DESCRIPTION_CHARS,
                multiline=True,
            )
            cleaned["description_i18n"] = {}
        if "category_suffix" in changes:
            cleaned["category_suffix"] = _clean_text(
                changes["category_suffix"],
                field="category_suffix",
                max_chars=MAX_CATEGORY_SUFFIX_CHARS,
            )

        with self._lock:
            path, library, original = self._open_user_library()
            entries = list(library.entries)
            index = self._index_of(entries, entry_id)
            if not cleaned:
                # 変更が無ければファイルを書き換えない (.bak の世代も進めない)
                return library, entries[index]
            if "display_name" in cleaned:
                key = normalized_name_key(cleaned["display_name"])
                clash = next(
                    (
                        e
                        for e in entries
                        if e.id != entry_id and normalized_name_key(e.display_name) == key
                    ),
                    None,
                )
                if clash is not None:
                    raise LibraryEntryNameConflictError(
                        "An entry with the same name already exists",
                        entry_id=clash.id,
                        revision=clash.revision,
                        display_name=clash.display_name,
                    )
            entries[index] = dataclasses.replace(entries[index], **cleaned)
            saved = self._save_user_library(path, library, entries, original)
        _logger.info("library store: updated metadata of entry %r", entry_id)
        return saved, self._entry_of(saved, entry_id)

    def delete_entry(self, entry_id: str, expected_revision: int) -> Library:
        """ユーザーライブラリからエントリを削除する。

        Args:
            entry_id: 削除するエントリの id。
            expected_revision: 呼び出し側が知っている revision。

        Returns:
            書き込み後のユーザーライブラリ。

        Raises:
            LibraryEntryConflictError: ``expected_revision`` が一致しない。
            LibraryEntryMissingError: ``entry_id`` のエントリが無い。
        """
        self.require_write()
        with self._lock:
            path, library, original = self._open_user_library()
            entries = list(library.entries)
            index = self._index_of(entries, entry_id)
            self._check_revision(entries[index], expected_revision)
            del entries[index]
            saved = self._save_user_library(path, library, entries, original)
        _logger.info(
            "library store: deleted entry %r (total entries=%d)", entry_id, len(saved.entries)
        )
        return saved

    def import_library(self, content: str, *, dry_run: bool) -> ImportReport:
        """ライブラリファイルの内容を検証し、read-only の別ライブラリとして取り込む。

        ``content`` はサーバ側で JSON として読み、旧 schema の migration・各エントリの
        深い検証を通してから、現行 schema に正規化して再シリアライズしたものを
        ``<user_library_dir>/imported/<サーバ生成名>.flwlib.json`` に保存する
        (ADR-0080 §A4-4 / §A6-4)。どの段階でもユーザーコードは実行しない。

        Args:
            content: ライブラリファイルの本文 (JSON 文字列)。
            dry_run: ``True`` なら検証結果だけを返し、何も書き込まない。未知の型と
                名前の衝突はエラーにせず結果に載せる。

        Returns:
            取り込み結果。

        Raises:
            LibraryFileInvalidError: JSON として読めない・schema 検証に失敗・名前が不正。
            LibraryEntryInvalidError: エントリが深い検証を通らない。本番では未知の型も含む。
            LibraryNameConflictError: (本番のみ) 名前が予約名または既存と同じ。
        """
        self.require_write()
        directory = self._writable_directory()
        data = parse_bounded_json(content)
        if not _is_utf8_encodable(data):
            raise LibraryFileInvalidError(
                "the file contains text that cannot be encoded as UTF-8 (lone surrogate)",
                reason=FILE_REASON_INVALID_JSON,
            )
        try:
            library = validate_library(data)
        except LibraryFileError as e:
            raise LibraryFileInvalidError(_clip(str(e)), reason=FILE_REASON_INVALID_LIBRARY) from e
        self._check_imported_metadata(library)
        unknown_types = tuple(sorted({t for e in library.entries for t in e.unknown_types}))
        if not unknown_types:
            library = dataclasses.replace(
                library,
                entries=[
                    dataclasses.replace(e, block=validate_entry_block(e.block, entry_id=e.id))
                    for e in library.entries
                ],
                source_path=None,
            )
        if dry_run:
            conflict, conflict_name = _import_conflict(library, self._registry)
            return ImportReport(
                library=library,
                unknown_types=unknown_types,
                conflict=conflict,
                conflict_name=conflict_name,
                dry_run=True,
            )
        if unknown_types:
            raise LibraryEntryInvalidError(
                _clip(f"library contains unknown block type(s): {', '.join(unknown_types)}"),
                reason=INVALID_REASON_UNKNOWN_TYPES,
                unknown_types=list(unknown_types),
            )

        with self._lock:
            conflict, conflict_name = _import_conflict(library, self._registry)
            if conflict:
                raise LibraryNameConflictError(
                    "The library cannot be imported: its name is reserved or already in use, "
                    "or its uid belongs to a library that is already loaded",
                    library=library.name,
                    reason=conflict,
                    conflicts_with=conflict_name,
                )
            # uid を持たないライブラリには、ディスクに書く直前に 1 回だけ付与する
            # (dry-run では付けない。書くのは 1 回なので以後は安定する、ADR-0080 §A6-4)
            library = dataclasses.replace(library, uid=library.uid or str(uuid.uuid4()))
            path = self._write_imported_file(directory, library.name, serialize_library(library))
            try:
                saved = self._load_written(path)
            except LibraryWriteError:
                # 読み戻せないファイルを残すと、registry に載らない孤児になる (次回の
                # 起動で load_error を出し続ける)。作ったファイルを巻き戻してから伝える
                self._discard_written_file(path)
                raise
            saved = self._install(saved, ORIGIN_IMPORTED)
        _logger.info(
            "library store: imported library as %s (entries=%d, with python=%d)",
            path.name,
            len(saved.entries),
            sum(1 for e in saved.entries if e.contains_python),
        )
        return ImportReport(
            library=saved, unknown_types=(), conflict="", conflict_name="", dry_run=False
        )

    def delete_imported_library(self, name: str) -> None:
        """取り込みライブラリを削除する (ファイルは ``<name>.bak`` にリネームして残す)。

        対象は registry の ``source_path`` から特定し、``origin == "imported"`` で、かつ
        ``<user_library_dir>/imported/`` の直下に実体があるものだけを消す。

        Args:
            name: ライブラリ名。

        Raises:
            LibraryNotFoundError: ``name`` のライブラリが無い。
            LibraryReadOnlyError: 取り込みライブラリではない。
            LibraryPathUnsafeError: ファイルが ``imported/`` の外を指している。
        """
        self.require_write()
        directory = self._writable_directory()
        with self._lock:
            old = self._registry
            library = old.libraries.get(name)
            if library is None:
                raise LibraryNotFoundError("Library not found", library=_clip(name))
            origin = old.origin_of(name)
            if origin != ORIGIN_IMPORTED or library.source_path is None:
                raise LibraryReadOnlyError(
                    "Only imported libraries can be deleted", library=name, origin=origin
                )
            target = self._checked(library.source_path, directory / IMPORTED_DIRNAME)
            backup = move_to_backup(target)
            self._registry = dataclasses.replace(
                old,
                libraries={k: v for k, v in old.libraries.items() if k != name},
                load_errors=list(old.load_errors),
                origins={k: v for k, v in old.origins.items() if k != name},
            )
        _logger.info(
            "library store: deleted imported library file %s (kept as %s)", target.name, backup.name
        )

    # --- internals (ロック内から呼ぶ) ----------------------------------------

    def _rebuild(self) -> None:
        """registry を全体再構築し、ユーザーライブラリのファイルの状態を記録する。"""
        # 読む前に stat する: 読み込みとの間にファイルが変わった場合、記録が内容より古く
        # なるので次の書き込みは 409 になる (逆順だと変更を見落として上書きしうる)
        fingerprint = self._stat_user_file()
        registry = build_library_registry(
            self._library_paths,
            bundle_builtin=self._bundle_builtin,
            user_library_dir=self._user_library_dir,
        )
        registry.user_library_problem = self._diagnose_user_file(registry, fingerprint)
        self._user_fingerprint = fingerprint
        self._registry = registry

    def _user_file(self) -> Path | None:
        if self._user_library_dir is None:
            return None
        return self._user_library_dir / USER_LIBRARY_FILENAME

    def _stat_user_file(self) -> _Fingerprint:
        """ユーザーライブラリのファイルの ``(size, mtime_ns)`` を返す (無ければ ``None``)。

        外部での書き換えを検知する指紋 (ADR-0080 §A5)。内容のハッシュではないので限界が
        ある: 更新時刻の粒度が粗いファイルシステム (FAT 系の 2 秒、一部のネットワーク
        ファイルシステムの 1 秒など) では、**同じサイズ**の内容に**同じ tick の中で**
        書き換えられた場合を見逃す。その場合は外部の変更を上書きしうる (直前の内容は
        ``.bak`` に 1 世代残る)。
        """
        path = self._user_file()
        if path is None:
            return None
        try:
            st = path.stat()
        except OSError:
            return None
        return (st.st_size, st.st_mtime_ns)

    def _diagnose_user_file(self, registry: LibraryRegistry, fingerprint: _Fingerprint) -> str:
        """ユーザーライブラリのファイルが読めない理由のエラーコードを返す (健全なら空文字)。"""
        path = self._user_file()
        if path is None or fingerprint is None:
            return ""
        if registry.origins.get(USER_LIBRARY_NAME) == ORIGIN_USER:
            return ""
        try:
            self._read_user_file(path)
        except (UserLibraryCorruptError, LibrarySchemaTooNewError) as e:
            return e.code
        return ""

    def _checked(self, target: Path, directory: Path) -> Path:
        """書き込み・削除対象が ``directory`` の直下を指すことを確かめる (ADR-0080 §A4-3)。

        Raises:
            LibraryPathUnsafeError: 対象 (または途中のディレクトリ) が symlink などで外を指す。
        """
        try:
            return ensure_direct_child(target, directory)
        except PathTraversalError as e:
            _logger.warning("library store: refused to touch %s: %s", target.name, e)
            raise LibraryPathUnsafeError(
                "The library file resolves outside the user library directory",
                file=target.name,
            ) from e

    def _read_user_file(self, path: Path) -> tuple[Library, str, bool]:
        """ユーザーライブラリのファイルを読み、健全性を確かめる (ADR-0080 §A6-3)。

        Returns:
            ``(検証済みのライブラリ, ファイルの元の内容, 旧 schema で書かれていたか)``。
            内容は改行を変換せずに UTF-8 で復号したもの (書き戻せば元のバイト列になる)。

        Raises:
            UserLibraryCorruptError: 読めない・JSON でない・schema 検証に失敗・名前が
                ``user`` でない。
            LibrarySchemaTooNewError: 現行より新しい schema 版で書かれている。
        """

        def corrupt(reason: str) -> UserLibraryCorruptError:
            return UserLibraryCorruptError(
                f"The user library file is corrupt and was left untouched: {_clip(reason)}",
                path=str(path),
                reason=_clip(reason),
                has_backup=backup_path_for(path).is_file(),
            )

        try:
            raw = path.read_bytes().decode("utf-8")
            data = json.loads(raw)
        except (OSError, ValueError, RecursionError) as e:
            raise corrupt(f"{type(e).__name__}: {e}") from e
        if not isinstance(data, dict):
            raise corrupt("the file is not a JSON object")
        version = data.get("schema_version")
        if _is_newer_schema_version(version):
            raise LibrarySchemaTooNewError(
                "The user library file was written by a newer flode and was left untouched",
                path=str(path),
                schema_version=str(version),
                supported=CURRENT_LIBRARY_SCHEMA_VERSION,
            )
        try:
            library = validate_library(data, source_path=path)
        except LibraryFileError as e:
            raise corrupt(str(e)) from e
        if library.name != USER_LIBRARY_NAME:
            raise corrupt(f"the file must declare name {USER_LIBRARY_NAME!r}")
        # registry が読み込まないファイルには書き込みもしない (判定を registry と揃える)
        reserved = reserved_entry_id_rejection(library)
        if reserved is not None:
            raise corrupt(reserved)
        return library, raw, version != CURRENT_LIBRARY_SCHEMA_VERSION

    def _open_user_library(self) -> tuple[Path, Library, str | None]:
        """書き込みの前段: 対象 path の確認・ディスク変更検知・現在の内容の読み込み。

        Returns:
            ``(書き込み先, 現在のライブラリ, 旧 schema だった場合の元の内容)``。
            ファイルがまだ無ければ、空の新しいユーザーライブラリを返す。

        Raises:
            LibraryPathUnsafeError: 書き込み先が外を指す。
            LibraryChangedOnDiskError: registry に読み込んだ後でファイルが変わった。
            UserLibraryCorruptError: 既存ファイルが壊れている。
            LibrarySchemaTooNewError: 既存ファイルが新しい版で書かれている。
        """
        self.require_write()
        directory = self._writable_directory()
        path = self._checked(directory / USER_LIBRARY_FILENAME, directory)
        if self._stat_user_file() != self._user_fingerprint:
            raise LibraryChangedOnDiskError(
                "The user library file was changed on disk after it was loaded; "
                "reload the libraries and try again",
                path=str(path),
            )
        if self._user_fingerprint is None:
            from ..core.persistence import CURRENT_SCHEMA_VERSION

            empty = Library(
                name=USER_LIBRARY_NAME,
                display_name=USER_LIBRARY_DISPLAY_NAME,
                description="",
                entries=[],
                display_name_i18n=dict(USER_LIBRARY_DISPLAY_NAME_I18N),
                model_schema_version=CURRENT_SCHEMA_VERSION,
            )
            return path, empty, None
        library, raw, legacy = self._read_user_file(path)
        return path, library, raw if legacy else None

    def _save_user_library(
        self,
        path: Path,
        library: Library,
        entries: list[LibraryEntry],
        original: str | None,
    ) -> Library:
        """ユーザーライブラリをアトミックに書き込み、registry を差し替える (ADR-0080 §A6)。

        Args:
            path: 書き込み先 (確認済み)。
            library: 書き込み前のライブラリ。
            entries: 書き込むエントリ。
            original: 旧 schema で書かれていた既存ファイルの内容 (``.pre-v4.bak`` 用)。
                現行 schema または新規作成なら ``None``。

        Returns:
            書き込み後に読み直したライブラリ。

        Raises:
            LibraryWriteBusyError: 他プロセスがファイルを開いていて置換できなかった。
                ファイルも registry も変わっていない。
            LibraryWriteError: ディレクトリ作成・書き込みに失敗した (ファイルも registry も
                変わっていない)、または書き込んだファイルを読み戻せなかった。後者では
                ファイルは**置き換わっており**、registry と変更検知の記録を起動時と同じ
                手順でディスクの状態に揃えてから送出する (読めなければ ``load_errors`` と
                ``user_library_problem`` に現れる)。
        """
        # GUI が初めて書き込むときに uid を付与する (以後は変えない、ADR-0080 §A1-3)
        updated = dataclasses.replace(
            library, entries=entries, uid=library.uid or str(uuid.uuid4()), source_path=path
        )
        text = serialize_library(updated)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise LibraryWriteError(
                f"Cannot create library directory {str(path.parent)!r}: {e}"
            ) from e
        if original is not None:
            pre_v4 = path.with_name(path.name + PRE_V4_BACKUP_SUFFIX)
            if not pre_v4.exists():
                # 旧版 flode へ戻すときの復元元。1 回だけ作り、以後は上書きしない
                atomic_write_text(pre_v4, original, backup=False)
        atomic_write_text(path, text)
        fingerprint = self._stat_user_file()
        try:
            saved = self._load_written(path)
        except LibraryWriteError:
            # ファイルは既に置き換わっている。registry と変更検知の記録を古いままにすると
            # 以後の書き込みがすべて 409 になるので、ディスクの状態に揃えてから伝える
            self._rebuild()
            raise
        saved = self._install(saved, ORIGIN_USER)
        self._user_fingerprint = fingerprint
        return saved

    def _install(self, library: Library, origin: str) -> Library:
        """読み直した 1 ライブラリを載せた新しい registry に差し替える (copy-on-write)。

        起動時・再読み込み時と同じ規則で並べ、``uid`` の重複を解決する
        (``resolve_uid_conflicts``: 出所の信頼度で決める)。どの経路で registry を組んでも
        結果が同じになるようにするため。

        Args:
            library: 書き込んだ直後にディスクから読み直したライブラリ。
            origin: その出所 (``"user"`` / ``"imported"``)。

        Returns:
            registry に載ったライブラリ (``uid`` の解決後)。
        """
        old = self._registry
        origins = {**old.origins, library.name: origin}
        libraries, notes = resolve_uid_conflicts(
            sort_by_origin({**old.libraries, library.name: library}, origins), origins
        )
        self._registry = LibraryRegistry(
            libraries=libraries,
            load_errors=[*old.load_errors, *notes],
            origins=origins,
            # ユーザーライブラリを書けた = 健全。それ以外の差し替えでは状態を変えない
            user_library_problem="" if origin == ORIGIN_USER else old.user_library_problem,
        )
        return libraries[library.name]

    @staticmethod
    def _check_imported_metadata(library: Library) -> None:
        """取り込むライブラリの名前・表示用文字列・エントリ id を検査する。

        Raises:
            LibraryFileInvalidError: ライブラリの名前・表示名・説明が不正、または REST の
                path と紛れる予約エントリ id (``export`` / ``entries``) を持つ。
            LibraryEntryInvalidError: エントリの id・表示名・説明・分類が、登録時と同じ
                制約 (長さ・制御文字 / 書式文字の禁止) に反する。
        """
        name = library.name
        if (
            len(name) > MAX_IMPORT_LIBRARY_NAME_CHARS
            or any(sep in name for sep in _PATH_SEPARATORS)
            or _has_unsafe_chars(name)
            or name in (".", "..")
        ):
            raise LibraryFileInvalidError(
                f"library name must be at most {MAX_IMPORT_LIBRARY_NAME_CHARS} characters "
                "and must not contain path separators, control or formatting characters",
                reason=FILE_REASON_INVALID_NAME,
            )
        library_problem = _imported_library_problem(library)
        if library_problem is not None:
            field, problem = library_problem
            raise LibraryFileInvalidError(
                f"library {field} {problem}", reason=FILE_REASON_INVALID_METADATA, field=field
            )
        for entry in library.entries:
            entry_problem = _imported_entry_problem(entry)
            if entry_problem is not None:
                field, problem = entry_problem
                raise LibraryEntryInvalidError(
                    f"entry {field} {problem}",
                    reason=INVALID_REASON_METADATA,
                    field=field,
                    entry_id=_clip(entry.id),
                )
            if entry.id in RESERVED_ENTRY_IDS:
                raise LibraryFileInvalidError(
                    f"entry id {entry.id!r} is reserved by the REST API and cannot be imported",
                    reason=FILE_REASON_RESERVED_ENTRY_ID,
                    entry_id=entry.id,
                )

    @staticmethod
    def _discard_written_file(path: Path) -> None:
        """取り込みで作ったファイルを消す (消せなくても元の失敗を上書きしない)。"""
        try:
            path.unlink(missing_ok=True)
        except OSError as e:
            _logger.warning(
                "library store: could not remove %s after a failed import: %r", path.name, str(e)
            )

    @staticmethod
    def _load_written(path: Path) -> Library:
        """書き込んだ直後のファイルを読み直す (registry にはディスクの内容を載せる)。"""
        try:
            return load_library(path)
        except LibraryFileError as e:
            raise LibraryWriteError(
                f"Library file {str(path)!r} could not be read back after writing: {_clip(str(e))}"
            ) from e

    def _write_imported_file(self, directory: Path, library_name: str, text: str) -> Path:
        """取り込みライブラリを ``imported/<slug>-<8 桁 hex>.flwlib.json`` に排他作成する。"""
        imported_dir = directory / IMPORTED_DIRNAME
        try:
            imported_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise LibraryWriteError(
                f"Cannot create library directory {str(imported_dir)!r}: {e}"
            ) from e
        slug = file_slug(library_name)
        for _ in range(_IMPORT_NAME_MAX_ATTEMPTS):
            token = secrets.token_hex(_IMPORT_TOKEN_BYTES)
            path = self._checked(
                imported_dir / f"{slug}-{token}{LIBRARY_FILE_SUFFIX}", imported_dir
            )
            try:
                write_text_exclusive(path, text)
            except FileExistsError:
                continue
            return path
        raise LibraryWriteError(
            f"Cannot pick an unused file name in {str(imported_dir)!r} "
            f"after {_IMPORT_NAME_MAX_ATTEMPTS} attempts"
        )

    @staticmethod
    def _index_of(entries: list[LibraryEntry], entry_id: str) -> int:
        for index, entry in enumerate(entries):
            if entry.id == entry_id:
                return index
        raise LibraryEntryMissingError(
            "Entry not found in the user library", entry_id=_clip(entry_id)
        )

    @staticmethod
    def _check_revision(entry: LibraryEntry, expected_revision: int | None) -> int:
        """``expected_revision`` が現在の revision と一致することを確かめ、現在値を返す。"""
        if entry.revision != expected_revision:
            raise LibraryEntryConflictError(
                "The entry was changed by someone else; reload the libraries and try again",
                entry_id=entry.id,
                expected_revision=expected_revision,
                current_revision=entry.revision,
            )
        return entry.revision

    @staticmethod
    def _entry_of(library: Library, entry_id: str) -> LibraryEntry:
        entry = library.get_entry(entry_id)
        if entry is None:  # 書き込んだ直後に読み直したライブラリなので起こらない
            raise LibraryWriteError(f"Entry {entry_id!r} is missing after writing the library")
        return entry
