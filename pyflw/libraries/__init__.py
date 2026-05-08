"""Block library file format ``.flwlib.json`` の public API (ADR-0029)。

`.flwlib.json` はマスク Subsystem 集合 (PID コントローラ・1 次遅れプラント等) を
配布するための JSON ファイル形式。``Subsystem.to_dict()`` の出力 (ADR-0009 §(7) +
ADR-0021 §(8)) と byte-identical な subsystem body を ``entries[*].subsystem`` に
格納する (= round-trip 安全性が保証される)。

Phase 4 v0.11.1 でサポートする操作:

* :func:`load_library` — `.flwlib.json` を読み込んで :class:`Library` を返す
* :func:`validate_library` — 既に load 済みの dict を検証して :class:`Library` を返す
* :func:`export_subsystem_to_library` — 既存 :class:`pyflw.Subsystem` を library entry
  として `.flwlib.json` に書き出す (Python API; GUI からの編集は Phase 5+)

.. note::

   ライブラリの利用 (= drop で配置 / inline 展開) は frontend が REST
   ``GET /api/v1/libraries/{lib}/{entry}`` 経由で行う。Python 側で直接 instantiate
   したい場合は ``Subsystem._from_dict(**entry.subsystem["params"])`` で再構築できる
   (= byte-identical 保証)。
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..exceptions import LibraryFileError
from ._loader import (
    CURRENT_LIBRARY_SCHEMA_VERSION,
    SUPPORTED_LIBRARY_SCHEMA_VERSIONS,
    validate_library_dict,
)

if TYPE_CHECKING:
    from ..subsystems import Subsystem

_logger = logging.getLogger("pyflw.libraries")

__all__ = [
    "CURRENT_LIBRARY_SCHEMA_VERSION",
    "SUPPORTED_LIBRARY_SCHEMA_VERSIONS",
    "Library",
    "LibraryEntry",
    "LibraryFileError",
    "export_subsystem_to_library",
    "load_library",
    "validate_library",
]


# ----------------------------------------------------------------------------
# Dataclasses (immutable, hashable by identity)
# ----------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class LibraryEntry:
    """Library 内の 1 つの再利用可能な Subsystem (ADR-0029 §(2))。

    Attributes:
        id: ライブラリ内で一意な identifier (= ``"pid_controller"`` 等)。
            REST URL ``/api/v1/libraries/{lib}/{entry}`` の ``{entry}`` に対応。
        display_name: GUI palette に表示する英語名 (= 旧 schema 互換)。
        display_name_i18n: locale → 表示名 (ADR-0028 と同形式)。
        description: 1 行説明 (= palette tooltip)。
        description_i18n: locale → 1 行説明。
        category_suffix: ``library.<lib_name>.<suffix>`` の suffix 部分。
            空文字なら ``library.<lib_name>`` 直下に出る (= ADR-0029 §CAT-A)。
        subsystem: ``Subsystem.to_dict()`` の戻り値と同じ形式
            (``{"id": ..., "type": "pyflw.subsystems.subsystem.Subsystem",
            "params": {...}}``)。``Subsystem._from_dict(**subsystem["params"])`` で
            再構築可能 (= byte-identical round-trip)。
    """

    id: str
    display_name: str
    description: str
    category_suffix: str
    subsystem: dict[str, Any]
    display_name_i18n: dict[str, str] = field(default_factory=dict)
    description_i18n: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, eq=False)
class Library:
    """``.flwlib.json`` 1 ファイルから組み立てられる library (ADR-0029 §(2))。

    Attributes:
        name: library 識別子 (= REST URL 上の ``{lib}``)。一般に拡張子なしのファイル
            名と同じだが、ファイル内 ``"name"`` が source of truth。
        display_name: GUI に表示する英語名。
        display_name_i18n: locale → 表示名。
        description: 1 行説明。
        description_i18n: locale → 1 行説明。
        version: library 自体のバージョン (= 配布管理用、optional)。
        entries: :class:`LibraryEntry` のリスト。順序は JSON ファイル上の順序を保つ
            (= GUI palette 上の表示順を library 作者がコントロール可能)。
        source_path: 読み込み元ファイルの絶対 path (export / debug 用)。
            in-memory build の場合は ``None``。
    """

    name: str
    display_name: str
    description: str
    entries: list[LibraryEntry]
    display_name_i18n: dict[str, str] = field(default_factory=dict)
    description_i18n: dict[str, str] = field(default_factory=dict)
    version: str = ""
    source_path: Path | None = None

    def get_entry(self, entry_id: str) -> LibraryEntry | None:
        """``entry_id`` から :class:`LibraryEntry` を返す。未登録なら ``None``。"""
        for e in self.entries:
            if e.id == entry_id:
                return e
        return None


# ----------------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------------


def validate_library(
    data: dict[str, Any], *, source_path: Path | None = None
) -> Library:
    """既に load 済みの dict を検証して :class:`Library` を返す。

    実装は :mod:`pyflw.libraries._loader` に閉じ、本関数は public API surface
    として薄い wrapper を提供する。

    Args:
        data: ``json.loads()`` で読んだ辞書。
        source_path: 読み込み元 path (debug 用、オプショナル)。

    Raises:
        LibraryFileError: 必須キー欠落、schema_version 未対応、entries 不正など。
    """
    return validate_library_dict(data, source_path=source_path)


def load_library(path: str | Path) -> Library:
    """``.flwlib.json`` を読み込んで :class:`Library` を返す (ADR-0029)。

    Args:
        path: 読み込み元 path。``.flwlib.json`` 拡張子は強制しない (組み込み bundle
            はそのまま使う)。

    Raises:
        LibraryFileError: ファイル不在、JSON パース失敗、schema 検証失敗など。
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise LibraryFileError(
            f"Cannot read library file {str(p)!r}: {e}"
        ) from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise LibraryFileError(
            f"Library file {str(p)!r} is not valid JSON: {e}"
        ) from e
    return validate_library(data, source_path=p.resolve())


# ----------------------------------------------------------------------------
# Export
# ----------------------------------------------------------------------------


def export_subsystem_to_library(
    subsystem: Subsystem,
    path: str | Path,
    *,
    library_metadata: dict[str, Any] | None = None,
    entry_metadata: dict[str, Any] | None = None,
    append: bool = True,
) -> Library:
    """既存の :class:`pyflw.Subsystem` を library entry として `.flwlib.json` に書き出す。

    Phase 4 v0.11.1: GUI 編集は未実装 (Phase 5+)、Python API 経由のみで提供する。

    Args:
        subsystem: 書き出す Subsystem (マスクパラメータ宣言を持つことを推奨)。
        path: 書き出し先。``append=True`` で既存ファイルに追記、``False`` で上書き作成。
        library_metadata: 新規 library 作成時の metadata (``{"name", "display_name",
            "description", "version", "display_name_i18n", "description_i18n"}``)。
            ``append=True`` で既存を読む場合は無視される。
        entry_metadata: ``LibraryEntry`` の metadata (``{"id", "display_name",
            "description", "category_suffix", "display_name_i18n",
            "description_i18n"}``)。``id`` と ``display_name`` は必須。
        append: 既存 library に entry を追加するか。``False`` なら新規 library として
            作成 (= 既存ファイル上書き)。

    Returns:
        書き出し後の :class:`Library` (= 直前にディスクに書いた内容と一致)。

    Raises:
        LibraryFileError: ``entry_metadata`` 必須キー欠落、id 衝突、ファイル書き込み失敗。
    """
    p = Path(path)
    em = entry_metadata or {}
    if "id" not in em or not isinstance(em["id"], str) or not em["id"]:
        raise LibraryFileError(
            "export_subsystem_to_library: entry_metadata must contain a non-empty "
            "string 'id'"
        )
    if "display_name" not in em or not isinstance(em["display_name"], str):
        raise LibraryFileError(
            "export_subsystem_to_library: entry_metadata must contain a string "
            "'display_name'"
        )

    lib_name: str
    lib_display_name: str
    lib_description: str
    lib_version: str
    lib_display_name_i18n: dict[str, str]
    lib_description_i18n: dict[str, str]
    existing_entries: list[LibraryEntry]
    if append and p.exists():
        existing = load_library(p)
        if existing.get_entry(em["id"]) is not None:
            raise LibraryFileError(
                f"Library {existing.name!r} already has entry {em['id']!r}; "
                f"choose a different id or use append=False to overwrite the file"
            )
        lib_name = existing.name
        lib_display_name = existing.display_name
        lib_description = existing.description
        lib_version = existing.version
        lib_display_name_i18n = dict(existing.display_name_i18n)
        lib_description_i18n = dict(existing.description_i18n)
        existing_entries = list(existing.entries)
    else:
        lm = library_metadata or {}
        derived_name = lm.get("name") or p.stem.removesuffix(".flwlib")
        if not isinstance(derived_name, str) or not derived_name:
            raise LibraryFileError(
                "export_subsystem_to_library: library_metadata['name'] must be a "
                "non-empty string (or derivable from the file name)"
            )
        lib_name = derived_name
        lib_display_name = str(lm.get("display_name", lib_name))
        lib_description = str(lm.get("description", ""))
        lib_version = str(lm.get("version", ""))
        lib_display_name_i18n = dict(lm.get("display_name_i18n") or {})
        lib_description_i18n = dict(lm.get("description_i18n") or {})
        existing_entries = []

    # ``Subsystem.to_dict()`` の出力をそのまま subsystem body として格納する
    # (= byte-identical 維持)。entry の id は library 側で管理するので、subsystem
    # 内部 id は一旦保持するが、Inline 配置時に frontend 側で再採番される (= ADR-0029
    # §PLACE-A)。
    sub_dict = subsystem.to_dict()
    new_entry = LibraryEntry(
        id=em["id"],
        display_name=em["display_name"],
        description=str(em.get("description", "")),
        category_suffix=str(em.get("category_suffix", "")),
        subsystem=sub_dict,
        display_name_i18n=dict(em.get("display_name_i18n") or {}),
        description_i18n=dict(em.get("description_i18n") or {}),
    )

    # ``source_path`` は **最終書き込み先の絶対 path** を指す (= 引数 ``path`` を
    # resolve したもの)。append=True の場合でも、existing.source_path ではなく今回の
    # 書き込み先を使う (= symlink / 相対 path 指定で混乱を避ける、code-reviewer SHOULD 修正)。
    library = Library(
        name=lib_name,
        display_name=lib_display_name,
        description=lib_description,
        version=lib_version,
        display_name_i18n=lib_display_name_i18n,
        description_i18n=lib_description_i18n,
        entries=[*existing_entries, new_entry],
        source_path=p.resolve(),
    )

    out_dict = _library_to_dict(library)
    try:
        p.write_text(
            json.dumps(out_dict, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as e:
        raise LibraryFileError(
            f"Cannot write library file {str(p)!r}: {e}"
        ) from e
    _logger.info(
        "exported subsystem to library %s (entry id=%s, total entries=%d)",
        p,
        new_entry.id,
        len(library.entries),
    )
    return library


def _library_to_dict(library: Library) -> dict[str, Any]:
    """:class:`Library` を ``.flwlib.json`` 用の dict に変換する。

    空の i18n / description / version は出力しない (= byte-identical / minimal JSON)。
    """
    out: dict[str, Any] = {
        "schema_version": CURRENT_LIBRARY_SCHEMA_VERSION,
        "name": library.name,
        "display_name": library.display_name,
    }
    if library.description:
        out["description"] = library.description
    if library.version:
        out["version"] = library.version
    if library.display_name_i18n:
        out["display_name_i18n"] = dict(library.display_name_i18n)
    if library.description_i18n:
        out["description_i18n"] = dict(library.description_i18n)
    out["entries"] = [_entry_to_dict(e) for e in library.entries]
    return out


def _entry_to_dict(entry: LibraryEntry) -> dict[str, Any]:
    """:class:`LibraryEntry` を ``.flwlib.json`` 用 dict に変換する。

    .. note::

        byte-identical 保証は **``subsystem`` フィールドの値** のみに対するもので、
        フィールドの並び順は対象外 (= 手書きの ``.flwlib.json`` と export 経路で
        並びが異なってもよい)。``Subsystem.to_dict()`` の出力 ``subsystem`` は
        deep-copy で共有参照を切ったうえでそのまま格納する。
    """
    out: dict[str, Any] = {
        "id": entry.id,
        "display_name": entry.display_name,
    }
    if entry.description:
        out["description"] = entry.description
    if entry.category_suffix:
        out["category_suffix"] = entry.category_suffix
    if entry.display_name_i18n:
        out["display_name_i18n"] = dict(entry.display_name_i18n)
    if entry.description_i18n:
        out["description_i18n"] = dict(entry.description_i18n)
    out["subsystem"] = copy.deepcopy(entry.subsystem)
    return out
