"""``.flwlib.json`` ファイルフォーマットの schema validation と migration registry (ADR-0029)。

`.flwlib.json` はマスク Subsystem 集合の配布形式。本 module は:

  1. ``CURRENT_LIBRARY_SCHEMA_VERSION`` / ``SUPPORTED_LIBRARY_SCHEMA_VERSIONS`` の宣言
  2. dict (= JSON ロード結果) の schema 検証 → ``validate_library_dict`` で
     :class:`pyflw.Library` を組み立てる
  3. ``_LIBRARY_MIGRATIONS`` registry (Phase 4 v0.11.1 では空、Phase 5+ 用枠)

を提供する。``Subsystem.to_dict()`` の "params" 形式 (ADR-0009 §(7) +
ADR-0021 §(8)) と byte-identical な辞書を ``entries[*].subsystem`` に格納する。

.. note::

   本 module はパッケージ内部実装 (= ``pyflw.libraries`` の ``__init__.py`` から
   呼ばれる)。外部公開 API は ``pyflw.libraries`` 経由で使うこと。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..exceptions import LibraryFileError

if TYPE_CHECKING:
    from . import Library, LibraryEntry

# ----------------------------------------------------------------------------
# Schema version
# ----------------------------------------------------------------------------

CURRENT_LIBRARY_SCHEMA_VERSION = "libraries.v1"
SUPPORTED_LIBRARY_SCHEMA_VERSIONS: tuple[str, ...] = (CURRENT_LIBRARY_SCHEMA_VERSION,)

# Phase 4 では空。Phase 5+ で v2 を導入したとき (from, to) -> migrate fn を登録する。
_LIBRARY_MIGRATIONS: dict[
    tuple[str, str], Callable[[dict[str, Any]], dict[str, Any]]
] = {}


# ----------------------------------------------------------------------------
# Validation helpers
# ----------------------------------------------------------------------------


def _require(data: dict[str, Any], key: str, type_: type | tuple[type, ...]) -> Any:
    if key not in data:
        raise LibraryFileError(f"Missing required key {key!r} in library data")
    value = data[key]
    if not isinstance(value, type_):
        type_label = (
            type_.__name__
            if isinstance(type_, type)
            else " | ".join(t.__name__ for t in type_)
        )
        raise LibraryFileError(
            f"Key {key!r} must be {type_label}, got {type(value).__name__}"
        )
    return value


def _optional(
    data: dict[str, Any], key: str, type_: type | tuple[type, ...], *, default: Any
) -> Any:
    if key not in data:
        return default
    value = data[key]
    if not isinstance(value, type_):
        type_label = (
            type_.__name__
            if isinstance(type_, type)
            else " | ".join(t.__name__ for t in type_)
        )
        raise LibraryFileError(
            f"Key {key!r} must be {type_label}, got {type(value).__name__}"
        )
    return value


def _validate_i18n_dict(value: Any, path: str) -> dict[str, str]:
    """``{en: "...", ja: "..."}`` 形式の i18n dict を検証する。

    None / 不在 → 空 dict。空文字値は許容 (= ``localizedDisplayName`` で fallback)。
    """
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise LibraryFileError(f"{path!r} must be a dict[str, str]")
    out: dict[str, str] = {}
    for k, v in value.items():
        if not isinstance(k, str):
            raise LibraryFileError(f"{path!r} keys must be str, got {type(k).__name__}")
        if not isinstance(v, str):
            raise LibraryFileError(
                f"{path!r}[{k!r}] must be str, got {type(v).__name__}"
            )
        out[k] = v
    return out


def _ensure_schema_version(data: dict[str, Any]) -> dict[str, Any]:
    """``schema_version`` を確認し、必要なら最新版に migrate する。

    Phase 4 v0.11.1 では ``CURRENT_LIBRARY_SCHEMA_VERSION = "libraries.v1"`` のみが
    実在する。Phase 5+ で v2 が追加されたときは、v1 ファイルが読まれた場合に
    ``_LIBRARY_MIGRATIONS[("libraries.v1", "libraries.v2")]`` を経由して migrate
    される (= ``SUPPORTED_LIBRARY_SCHEMA_VERSIONS`` に含まれていても CURRENT より
    古ければ migration ループを通る)。
    """
    if "schema_version" not in data:
        raise LibraryFileError(
            "Missing required key 'schema_version' in .flwlib.json"
        )
    version = data["schema_version"]
    if not isinstance(version, str):
        raise LibraryFileError(
            f"schema_version must be a string, got {type(version).__name__}"
        )
    if version == CURRENT_LIBRARY_SCHEMA_VERSION:
        return data
    # NOTE: ``SUPPORTED_LIBRARY_SCHEMA_VERSIONS in version`` で早期 return しない
    # こと。SUPPORTED に含まれていても CURRENT より古いバージョンは必ず migration
    # ループを経由しなければならない (= さもなくば古い JSON 形式のまま load される)。
    cur = version
    visited: set[str] = {cur}
    while cur != CURRENT_LIBRARY_SCHEMA_VERSION:
        next_step = next(
            (to for (frm, to) in _LIBRARY_MIGRATIONS if frm == cur), None
        )
        if next_step is None:
            raise LibraryFileError(
                f"Unsupported library schema_version {version!r}. "
                f"Supported: {SUPPORTED_LIBRARY_SCHEMA_VERSIONS}, "
                f"current: {CURRENT_LIBRARY_SCHEMA_VERSION!r}. "
                f"No migration registered from {cur!r}."
            )
        if next_step in visited:
            raise LibraryFileError(
                f"Library migration cycle detected at {next_step!r}; aborting"
            )
        data = _LIBRARY_MIGRATIONS[(cur, next_step)](data)
        visited.add(next_step)
        cur = next_step
    return data


# ----------------------------------------------------------------------------
# Public entry point: validate dict → Library
# ----------------------------------------------------------------------------


def _validate_entry(
    raw: Any, *, library_name: str, index: int
) -> LibraryEntry:
    """``entries[i]`` の dict を ``LibraryEntry`` に検証 + 変換する (内部)。"""
    # Library / LibraryEntry は ``pyflw.libraries.__init__`` 側に存在 (= public API)。
    # 循環 import を避けるため遅延 import する。
    from . import LibraryEntry

    where = f"library {library_name!r} entry #{index}"
    if not isinstance(raw, dict):
        raise LibraryFileError(
            f"{where}: entry must be a dict, got {type(raw).__name__}"
        )
    entry_id = _require(raw, "id", str)
    display_name = _require(raw, "display_name", str)
    description = _optional(raw, "description", str, default="")
    category_suffix = _optional(raw, "category_suffix", str, default="")
    subsystem = _require(raw, "subsystem", dict)
    # subsystem は ``Subsystem.to_dict()`` の出力と同じ {id, type, params} 形式。
    # ``type`` は ``Subsystem`` 系のみ許可 (= マスク Subsystem の配布が ADR-0029 の主目的)。
    sub_type = subsystem.get("type")
    if not isinstance(sub_type, str):
        raise LibraryFileError(
            f"{where}: subsystem.type must be a string, got {type(sub_type).__name__}"
        )
    if not sub_type.endswith(".Subsystem"):
        raise LibraryFileError(
            f"{where}: subsystem.type must be a Subsystem class path "
            f"(e.g. 'pyflw.subsystems.subsystem.Subsystem'), got {sub_type!r}"
        )
    if not isinstance(subsystem.get("params"), dict):
        raise LibraryFileError(
            f"{where}: subsystem.params must be a dict (Subsystem.to_dict() output)"
        )
    return LibraryEntry(
        id=entry_id,
        display_name=display_name,
        description=description,
        category_suffix=category_suffix,
        subsystem=subsystem,
        display_name_i18n=_validate_i18n_dict(
            raw.get("display_name_i18n"), f"{where}.display_name_i18n"
        ),
        description_i18n=_validate_i18n_dict(
            raw.get("description_i18n"), f"{where}.description_i18n"
        ),
    )


def validate_library_dict(
    data: dict[str, Any], *, source_path: Path | None = None
) -> Library:
    """既に load 済みの dict を schema 検証して :class:`pyflw.Library` を返す。

    本関数が ``pyflw.libraries.__init__`` から呼ばれる唯一の public entry point。
    ``__init__`` は ``Library`` / ``LibraryEntry`` の dataclass 定義のみを保持し、
    検証ロジックは全て本 module に閉じる (= モジュール境界の整理)。

    Args:
        data: ``json.loads()`` で読んだ辞書。
        source_path: 読み込み元 path (debug 用、オプショナル)。

    Raises:
        LibraryFileError: 必須キー欠落、schema_version 未対応、entries 不正など。
    """
    from . import Library  # 循環 import 回避の遅延 import

    if not isinstance(data, dict):
        raise LibraryFileError(
            f"Library data must be a dict, got {type(data).__name__}"
        )
    data = _ensure_schema_version(data)
    name = _require(data, "name", str)
    if not name:
        raise LibraryFileError("Library 'name' must be a non-empty string")
    display_name = _optional(data, "display_name", str, default=name)
    description = _optional(data, "description", str, default="")
    version = _optional(data, "version", str, default="")
    raw_entries = _require(data, "entries", list)
    seen_ids: set[str] = set()
    entries = []
    for idx, raw in enumerate(raw_entries):
        entry = _validate_entry(raw, library_name=name, index=idx)
        if entry.id in seen_ids:
            raise LibraryFileError(
                f"Library {name!r}: duplicate entry id {entry.id!r}"
            )
        seen_ids.add(entry.id)
        entries.append(entry)
    return Library(
        name=name,
        display_name=display_name,
        description=description,
        version=version,
        entries=entries,
        display_name_i18n=_validate_i18n_dict(
            data.get("display_name_i18n"), "library.display_name_i18n"
        ),
        description_i18n=_validate_i18n_dict(
            data.get("description_i18n"), "library.description_i18n"
        ),
        source_path=source_path,
    )
