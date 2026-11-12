"""Block library file format ``.flwlib.json`` の public API (ADR-0029 / ADR-0080)。

`.flwlib.json` は再利用ブロック (PID コントローラ・1 次遅れプラント等のマスク
Subsystem、および PythonFunction) を配布するための JSON ファイル形式。エントリ本体
``entries[*].block`` には ``Block.to_dict()`` の出力 ``{id, type, params}`` を
そのまま格納する (= round-trip 安全性が保証される)。

サポートする操作:

* :func:`load_library` — `.flwlib.json` を読み込んで :class:`Library` を返す
* :func:`validate_library` — 既に load 済みの dict を検証して :class:`Library` を返す
* :func:`export_subsystem_to_library` — 既存 :class:`flode.Subsystem` を library entry
  として `.flwlib.json` に書き出す (Python API)
* :func:`library_to_dict` / :func:`serialize_library` — :class:`Library` を
  `.flwlib.json` 用の dict / ファイル内容に変換する
* :func:`canonicalize_entry_block` — エントリ本体の深い検証 (書き込み経路用)
* :func:`atomic_write_text` — ライブラリファイルのアトミック書き込み

.. note::

   ライブラリの利用 (= drop で配置 / inline 展開) は frontend が REST
   ``GET /api/v1/libraries/{lib}/{entry}`` 経由で行う。Python 側で Subsystem エントリを
   直接 instantiate したい場合は ``Subsystem._from_dict(**entry.block["params"])`` で
   再構築できる (= byte-identical 保証)。
"""

from __future__ import annotations

import copy
import json
import logging
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..exceptions import LibraryFileError, LibraryWriteBusyError, LibraryWriteError
from ._atomic import atomic_write_text
from ._loader import (
    CURRENT_LIBRARY_SCHEMA_VERSION,
    DEFAULT_ENTRY_REVISION,
    SUPPORTED_LIBRARY_SCHEMA_VERSIONS,
    analyze_entry_block,
    canonicalize_entry_block,
    utc_timestamp,
    validate_library_dict,
)

if TYPE_CHECKING:
    from ..subsystems import Subsystem

_logger = logging.getLogger("flode.libraries")

__all__ = [
    "CURRENT_LIBRARY_SCHEMA_VERSION",
    "SUPPORTED_LIBRARY_SCHEMA_VERSIONS",
    "Library",
    "LibraryEntry",
    "LibraryFileError",
    "LibraryWriteBusyError",
    "LibraryWriteError",
    "atomic_write_text",
    "canonicalize_entry_block",
    "export_subsystem_to_library",
    "library_to_dict",
    "load_library",
    "serialize_library",
    "utc_timestamp",
    "validate_library",
]


# ----------------------------------------------------------------------------
# Dataclasses (immutable, hashable by identity)
# ----------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class LibraryEntry:
    """Library 内の 1 つの再利用可能なブロック (ADR-0029 §(2) / ADR-0080 §A1)。

    Attributes:
        id: ライブラリ内で一意な identifier (= ``"pid_controller"`` 等)。
            REST URL ``/api/v1/libraries/{lib}/{entry}`` の ``{entry}`` に対応。
        display_name: GUI palette に表示する英語名 (= 旧 schema 互換)。
        display_name_i18n: locale → 表示名 (ADR-0028 と同形式)。
        description: 1 行説明 (= palette tooltip)。
        description_i18n: locale → 1 行説明。
        category_suffix: ``library.<lib_name>.<suffix>`` の suffix 部分。
            空文字なら ``library.<lib_name>`` 直下に出る (= ADR-0029 §CAT-A)。
        block: エントリ本体。``Block.to_dict()`` の戻り値と同じ形式
            (``{"id": ..., "type": "flode.subsystems.subsystem.Subsystem",
            "params": {...}}``)。``type`` は Subsystem または PythonFunction の派生。
        revision: エントリ内容の世代 (整数 >= 1)。本体を上書きするたびに増える。
            ライブラリ全体の ``version`` (配布物のラベル) とは独立。
        updated_at: 最終更新時刻 (UTC 秒精度の "Z" 表記)。不明なら ``None``。
        kind: エントリ種別 (``"subsystem"`` / ``"python_function"``)。``block`` の
            ``type`` から導出する (保存しない)。
        contains_python: 本体 (入れ子を含む) に PythonFunction があるか (導出)。
        python_block_paths: PythonFunction の部分木内パス (``/`` 区切りの block id 列、
            本体自身なら空文字)。導出。
        unknown_types: 本体内部で解決できなかった ``type`` 文字列 (導出)。

    Raises:
        LibraryFileError: ``block`` の ``type`` が解決できない、または Subsystem /
            PythonFunction の派生でない (導出属性の算出時)。
    """

    id: str
    display_name: str
    description: str
    category_suffix: str
    block: dict[str, Any]
    display_name_i18n: dict[str, str] = field(default_factory=dict)
    description_i18n: dict[str, str] = field(default_factory=dict)
    revision: int = DEFAULT_ENTRY_REVISION
    updated_at: str | None = None
    kind: str = field(init=False)
    contains_python: bool = field(init=False)
    python_block_paths: tuple[str, ...] = field(init=False)
    unknown_types: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        # 導出属性は本体から算出して保持する (本体は不変なので再計算不要)。
        # 保存値を受け取らないことで ``type`` と食い違う状態を表現できなくする
        # (ADR-0080 §A1-2 / データ整合性の SSOT)。
        info = analyze_entry_block(self.block)
        object.__setattr__(self, "kind", info.kind)
        object.__setattr__(self, "contains_python", info.contains_python)
        object.__setattr__(self, "python_block_paths", info.python_block_paths)
        object.__setattr__(self, "unknown_types", info.unknown_types)

    @property
    def subsystem(self) -> dict[str, Any]:
        """``block`` の非推奨 alias (読み取り専用、ADR-0080 §A1-1)。

        v0.64.x までの名前。PythonFunction エントリでも本体を返すため名前と中身が
        一致しない。``block`` を使うこと。
        """
        warnings.warn(
            "LibraryEntry.subsystem is deprecated; use LibraryEntry.block instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.block


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
        version: library 自体のバージョン (= 配布物のラベル、optional)。エントリの
            ``revision`` とは独立。
        entries: :class:`LibraryEntry` のリスト。順序は JSON ファイル上の順序を保つ
            (= GUI palette 上の表示順を library 作者がコントロール可能)。
        source_path: 読み込み元ファイルの絶対 path (export / debug 用)。
            in-memory build の場合は ``None``。
        uid: ライブラリの同一性を表す識別子 (ADR-0080 §A3-3)。名前が同じ別人の
            ライブラリと区別するために使う。持たないライブラリは ``None``。
        model_schema_version: ``entries[*].block`` のモデル schema 版
            (ADR-0080 §A1-4)。:func:`load_library` / :func:`validate_library` は本体を
            現行形式に変換して返すので、読み込んだ ``Library`` では常に現行値。
            空文字は 「現行」 を意味する。
    """

    name: str
    display_name: str
    description: str
    entries: list[LibraryEntry]
    display_name_i18n: dict[str, str] = field(default_factory=dict)
    description_i18n: dict[str, str] = field(default_factory=dict)
    version: str = ""
    source_path: Path | None = None
    uid: str | None = None
    model_schema_version: str = ""

    def get_entry(self, entry_id: str) -> LibraryEntry | None:
        """``entry_id`` から :class:`LibraryEntry` を返す。未登録なら ``None``。"""
        for e in self.entries:
            if e.id == entry_id:
                return e
        return None


# ----------------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------------


def validate_library(data: dict[str, Any], *, source_path: Path | None = None) -> Library:
    """既に load 済みの dict を検証して :class:`Library` を返す。

    実装は :mod:`flode.libraries._loader` に閉じ、本関数は public API surface
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

    旧 schema のファイルはメモリ上で現行形式に変換する。読み込みだけでは
    ファイルを書き換えない。

    Args:
        path: 読み込み元 path。``.flwlib.json`` 拡張子は強制しない (組み込み bundle
            はそのまま使う)。

    Raises:
        LibraryFileError: ファイル不在、JSON パース失敗、schema 検証失敗など。
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise LibraryFileError(f"Cannot read library file {str(p)!r}: {e}") from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise LibraryFileError(f"Library file {str(p)!r} is not valid JSON: {e}") from e
    except RecursionError as e:
        raise LibraryFileError(f"Library file {str(p)!r} is nested too deeply") from e
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
    """既存の :class:`flode.Subsystem` を library entry として `.flwlib.json` に書き出す。

    現行の library schema で書き出す (既存ファイルが旧 schema でも、追記すると現行
    schema に上がる)。書き込みはアトミックで、既存ファイルの直前の内容は
    ``<ファイル名>.bak`` に 1 世代残る (:func:`atomic_write_text`)。

    Args:
        subsystem: 書き出す Subsystem (マスクパラメータ宣言を持つことを推奨)。
        path: 書き出し先。``append=True`` で既存ファイルに追記、``False`` で上書き作成。
        library_metadata: 新規 library 作成時の metadata (``{"name", "display_name",
            "description", "version", "uid", "display_name_i18n",
            "description_i18n"}``)。``append=True`` で既存を読む場合は無視される。
        entry_metadata: ``LibraryEntry`` の metadata (``{"id", "display_name",
            "description", "category_suffix", "display_name_i18n",
            "description_i18n"}``)。``id`` と ``display_name`` は必須。
        append: 既存 library に entry を追加するか。``False`` なら新規 library として
            作成 (= 既存ファイル上書き)。

    Returns:
        書き出し後の :class:`Library` (= 直前にディスクに書いた内容と一致)。

    Raises:
        LibraryFileError: ``entry_metadata`` 必須キー欠落、id 衝突、ファイル書き込み失敗
            (書き込み失敗は派生の :class:`~flode.exceptions.LibraryWriteError` /
            :class:`~flode.exceptions.LibraryWriteBusyError`)。
    """
    p = Path(path)
    em = entry_metadata or {}
    if "id" not in em or not isinstance(em["id"], str) or not em["id"]:
        raise LibraryFileError(
            "export_subsystem_to_library: entry_metadata must contain a non-empty string 'id'"
        )
    if "display_name" not in em or not isinstance(em["display_name"], str):
        raise LibraryFileError(
            "export_subsystem_to_library: entry_metadata must contain a string 'display_name'"
        )

    lib_name: str
    lib_display_name: str
    lib_description: str
    lib_version: str
    lib_uid: str | None
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
        lib_uid = existing.uid
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
        raw_uid = lm.get("uid")
        if raw_uid is not None and (not isinstance(raw_uid, str) or not raw_uid):
            raise LibraryFileError(
                "export_subsystem_to_library: library_metadata['uid'] must be a non-empty string"
            )
        lib_uid = raw_uid
        lib_display_name_i18n = dict(lm.get("display_name_i18n") or {})
        lib_description_i18n = dict(lm.get("description_i18n") or {})
        existing_entries = []

    # ``Subsystem.to_dict()`` の出力をそのまま本体として格納する (= byte-identical
    # 維持)。entry の id は library 側で管理するので、本体の内部 id は一旦保持するが、
    # Inline 配置時に frontend 側で再採番される (= ADR-0029 §PLACE-A)。
    # 由来 (provenance) は本体に含めない (ADR-0080 §A1-1): top-level のものだけ除く。
    sub_dict = subsystem.to_dict()
    sub_dict.pop("provenance", None)
    new_entry = LibraryEntry(
        id=em["id"],
        display_name=em["display_name"],
        description=str(em.get("description", "")),
        category_suffix=str(em.get("category_suffix", "")),
        block=sub_dict,
        display_name_i18n=dict(em.get("display_name_i18n") or {}),
        description_i18n=dict(em.get("description_i18n") or {}),
        revision=DEFAULT_ENTRY_REVISION,
        updated_at=utc_timestamp(),
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
        uid=lib_uid,
        model_schema_version=_current_model_schema_version(),
    )

    atomic_write_text(p, serialize_library(library))
    _logger.info(
        "exported subsystem to library %s (entry id=%s, total entries=%d)",
        p,
        new_entry.id,
        len(library.entries),
    )
    return library


def _current_model_schema_version() -> str:
    # ``flode.core.persistence`` は numpy 等を引くため、module import 時ではなく
    # 使う時点で import する (``_loader`` と同じ方針)。
    from ..core.persistence import CURRENT_SCHEMA_VERSION

    return CURRENT_SCHEMA_VERSION


def serialize_library(library: Library) -> str:
    """:class:`Library` を ``.flwlib.json`` のファイル内容 (文字列) に直列化する。

    ADR-0071 の規約 (``ensure_ascii=False`` / ``indent=2`` / 末尾改行 1 つ) に従う。
    """
    return json.dumps(library_to_dict(library), ensure_ascii=False, indent=2) + "\n"


def library_to_dict(library: Library) -> dict[str, Any]:
    """:class:`Library` を ``.flwlib.json`` 用の dict (現行 schema) に変換する。

    空の i18n / description / version と ``uid`` (``None``) は出力しない (= minimal
    JSON)。``model_schema_version`` は常に出力する (ADR-0080 §A1-2: 書き込み時は必須)。
    導出属性 (``kind`` / ``contains_python`` 等) は出力しない。

    Args:
        library: 変換する library。本体は ``model_schema_version`` の形式であること。

    Returns:
        ``json.dumps`` 可能な dict。本体は deep copy されるので、戻り値を書き換えても
        ``library`` に影響しない。
    """
    out: dict[str, Any] = {
        "schema_version": CURRENT_LIBRARY_SCHEMA_VERSION,
        "name": library.name,
    }
    if library.uid is not None:
        out["uid"] = library.uid
    out["display_name"] = library.display_name
    out["model_schema_version"] = library.model_schema_version or _current_model_schema_version()
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

        byte-identical 保証は **``block`` フィールドの値** のみに対するもので、
        フィールドの並び順は対象外 (= 手書きの ``.flwlib.json`` と export 経路で
        並びが異なってもよい)。本体は deep-copy で共有参照を切ったうえでそのまま
        格納する。
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
    out["revision"] = entry.revision
    if entry.updated_at is not None:
        out["updated_at"] = entry.updated_at
    out["block"] = copy.deepcopy(entry.block)
    return out
