"""``.flwlib.json`` ファイルフォーマットの schema validation と migration registry。

`.flwlib.json` は再利用ブロック (Subsystem / PythonFunction) の配布形式 (ADR-0029、
ADR-0080 で v4 に拡張)。本 module は:

  1. ``CURRENT_LIBRARY_SCHEMA_VERSION`` / ``SUPPORTED_LIBRARY_SCHEMA_VERSIONS`` の宣言
  2. ``_LIBRARY_MIGRATIONS`` registry (v1 → v2 → v3 → v4)
  3. dict (= JSON ロード結果) の schema 検証 → ``validate_library_dict`` で
     :class:`flode.Library` を組み立てる
  4. エントリ本体の検証 2 層 (ADR-0080 §A2):
     **浅い検証** (:func:`analyze_entry_block`、読み込み時) と
     **深い検証** (:func:`canonicalize_entry_block`、書き込み経路のみ)

を提供する。エントリ本体 ``entries[*].block`` は ``Block.to_dict()`` の出力
``{id, type, params}`` (由来 ``provenance`` を除く) をそのまま格納する。

ライブラリ schema はライブラリの**構造**が変わるときだけ bump する。本体のモデル
schema 版は ``model_schema_version`` に記録し、古ければモデル側の migration 連鎖
(``flode.core.persistence``) に通す (ADR-0080 §A1-4)。

.. note::

   本 module はパッケージ内部実装 (= ``flode.libraries`` の ``__init__.py`` から
   呼ばれる)。外部公開 API は ``flode.libraries`` 経由で使うこと。
"""

from __future__ import annotations

import copy
import datetime
import importlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..exceptions import FlodeError, LibraryFileError, UnknownBlockTypeError

if TYPE_CHECKING:
    from . import Library, LibraryEntry

_logger = logging.getLogger("flode.libraries")

# ----------------------------------------------------------------------------
# Schema version / 定数
# ----------------------------------------------------------------------------

CURRENT_LIBRARY_SCHEMA_VERSION = "libraries.v4"
# 旧バージョンも migration 経由で読み込める (= メモリ上で自動的に v4 に変換)。
# v1 → v2 → v3 → v4 のチェーンが ``_LIBRARY_MIGRATIONS`` に登録済。
SUPPORTED_LIBRARY_SCHEMA_VERSIONS: tuple[str, ...] = (
    CURRENT_LIBRARY_SCHEMA_VERSION,
    "libraries.v3",
    "libraries.v2",
    "libraries.v1",
)

#: エントリ ``revision`` の既定値 (省略時) かつ最小値。
DEFAULT_ENTRY_REVISION = 1

#: エントリ種別 (``LibraryEntry.kind``)。保存せず ``block.type`` から導出する。
ENTRY_KIND_SUBSYSTEM = "subsystem"
ENTRY_KIND_PYTHON_FUNCTION = "python_function"

# 許可するエントリ種別の対応表 (ADR-0080 §A2 2B): (種別, 基底クラスの完全修飾名)。
# 本体の ``type`` を解決したクラスがいずれかの派生なら、その種別になる。
# クラスは :func:`_entry_kind_classes` で遅延 import する (``flode.libraries`` は
# ``flode.subsystems`` より先に import されるため、module import 時には解決しない)。
_ENTRY_KINDS: tuple[tuple[str, str], ...] = (
    (ENTRY_KIND_SUBSYSTEM, "flode.subsystems.subsystem.Subsystem"),
    (ENTRY_KIND_PYTHON_FUNCTION, "flode.blocks.pythonfunc.PythonFunction"),
)

#: ``python_block_paths`` で使う部分木内パスの区切り
#: (block id は Unicode 識別子なので ``/`` を含まない)。
BLOCK_PATH_SEPARATOR = "/"

# ``updated_at`` の形式: UTC 秒精度の "Z" 表記 (モデル ``metadata.created_at`` と同形式)。
_UPDATED_AT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_UPDATED_AT_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")

# v3 → v4 migration が記録するボディのモデル schema 版。migration は凍結された
# 過去仕様の再現なので ``CURRENT_SCHEMA_VERSION`` を参照しない (ADR-0080 §A1-3)。
_V3_BODY_MODEL_SCHEMA_VERSION = "0.15"

# migration は 「検証済みの旧形式」 を前提に書かれており、壊れた入力に対して
# ``FlodeError`` 以外の例外を出しうる。ライブラリは外部から持ち込まれるファイルなので、
# ここで ``LibraryFileError`` に揃えて registry build (サーバ起動) を巻き込まない。
_MIGRATION_ERRORS: tuple[type[Exception], ...] = (
    FlodeError,
    KeyError,
    TypeError,
    ValueError,
    AttributeError,
)

# 本体の構築 (深い検証) が壊れた入力で出しうる例外。migration と同じ集合に、
# 際限なく深い入れ子で起きる ``RecursionError`` を加える。
_BODY_BUILD_ERRORS: tuple[type[Exception], ...] = (*_MIGRATION_ERRORS, RecursionError)

#: エントリ本体で許す Subsystem の入れ子の最大深さ (本体直下の ``blocks`` を深さ 1 と数える)。
#: 浅い検証の再帰走査が ``RecursionError`` に達する前に ``LibraryFileError`` で拒否する。
MAX_ENTRY_BLOCK_DEPTH: int = 64


def utc_timestamp(now: datetime.datetime | None = None) -> str:
    """``updated_at`` 用の UTC 秒精度 "Z" 表記の時刻文字列を返す。

    Args:
        now: 変換する時刻 (timezone-aware)。省略時は現在時刻。

    Returns:
        ``"2026-11-12T10:00:00Z"`` 形式の文字列。
    """
    moment = now if now is not None else datetime.datetime.now(datetime.UTC)
    return moment.astimezone(datetime.UTC).strftime(_UPDATED_AT_FORMAT)


# ----------------------------------------------------------------------------
# Migrations
# ----------------------------------------------------------------------------


def _migrate_libraries_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """ADR-0039: ``libraries.v1`` → ``libraries.v2`` migration。

    各 entry の ``subsystem.params`` (= ``Subsystem.to_dict()`` の出力) は schema
    0.7 形式のため、Subsystem の ``n_inputs`` / ``n_outputs`` / ``port_shapes_*``
    フィールドが含まれる。Phase 5b 以降の派生 property 化に伴い、これらを除去
    する必要がある。``persistence._builtin_migrate_0_7_to_0_8`` 内のヘルパを
    そのまま流用して、entry ごとに再帰除去する。
    """
    from ..core.persistence import _strip_subsystem_port_fields_recursive

    out, entries = _copy_legacy_entries(data)
    for entry in entries:
        subsystem = entry.get("subsystem") if isinstance(entry, dict) else None
        if not isinstance(subsystem, dict):
            continue
        # subsystem 自体が Subsystem entry なので、blocks=[subsystem] を
        # 一時的に作って再帰除去ロジックに通す。
        _strip_subsystem_port_fields_recursive(
            [subsystem],
            parent_path=f"library.entries[{entry.get('id', '?')}]",
        )
    out["schema_version"] = "libraries.v2"
    return out


def _migrate_libraries_v2_to_v3(data: dict[str, Any]) -> dict[str, Any]:
    """v0.56.0 (output_type 撤去): ``libraries.v2`` → ``libraries.v3``。

    各 entry の ``subsystem`` (= ``Subsystem.to_dict()`` 出力) に含まれる
    ``Cast`` / ``Constant`` の旧 ``output_type`` param を、model 側の 0.11 → 0.12
    migration と同じロジック (``_remove_output_type_recursive``) で数値等価な
    新語彙へ変換する。v1 → v2 と同じく blocks=[subsystem] を一時的に作って
    再帰ロジックに通す。
    """
    from ..core.persistence import (
        _contains_dtype_declaration_recursive,
        _remove_output_type_recursive,
    )

    out, entries = _copy_legacy_entries(data)
    for entry in entries:
        subsystem = entry.get("subsystem") if isinstance(entry, dict) else None
        if not isinstance(subsystem, dict):
            continue
        wrapper = [subsystem]
        _remove_output_type_recursive(
            wrapper,
            delete_identity_casts=_contains_dtype_declaration_recursive(wrapper),
            parent_path=f"library.entries[{entry.get('id', '?')}]",
        )
    out["schema_version"] = "libraries.v3"
    return out


def _copy_legacy_entries(data: dict[str, Any]) -> tuple[dict[str, Any], list[Any]]:
    """v1 / v2 の migration 用に ``(浅いコピー, deep copy した entries)`` を返す。

    v1 → v2 / v2 → v3 はモデル側のヘルパで本体を in-place に書き換えるので、
    呼び出し側が持つ dict を壊さないよう先に ``entries`` を複製する。``entries`` が
    list でない壊れた入力は値をそのまま残し (後段の検証が拒否する)、走査対象は空にする。
    """
    out = dict(data)
    entries = out.get("entries")
    if not isinstance(entries, list):
        return out, []
    copied: list[Any] = copy.deepcopy(entries)
    out["entries"] = copied
    return out, copied


def _is_port_index_at_least_one(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _has_stale_lti_scalar_wiring(blocks: Any, connections: Any) -> bool:
    """StateSpace 系 (m>=2 / p>=2) にスカラポート時代の結線が残っているか (再帰)。

    モデル schema 0.14 以前は StateSpace / DiscreteStateSpace / MimoTransferFunction が
    m 本 / p 本のスカラポートを持っていた。0.15 では 1 本のベクトルポートなので、
    ``dst_idx >= 1`` / ``src_idx >= 1`` の結線が残っていれば 0.14 以前の形とみなせる。
    """
    from ..core.persistence import _lti_signal_counts

    if not isinstance(blocks, list):
        return False
    wires = [c for c in connections if isinstance(c, dict)] if isinstance(connections, list) else []
    for block in blocks:
        params = block.get("params") if isinstance(block, dict) else None
        if not isinstance(block, dict) or not isinstance(params, dict):
            continue
        if _has_stale_lti_scalar_wiring(params.get("blocks"), params.get("connections")):
            return True
        counts = _lti_signal_counts(block.get("type"), params)
        if counts is None:
            continue
        n_in, n_out = counts
        block_id = block.get("id")
        if n_in >= 2 and any(
            c.get("dst") == block_id and _is_port_index_at_least_one(c.get("dst_idx"))
            for c in wires
        ):
            return True
        if n_out >= 2 and any(
            c.get("src") == block_id and _is_port_index_at_least_one(c.get("src_idx"))
            for c in wires
        ):
            return True
    return False


def _migrate_libraries_v3_to_v4(data: dict[str, Any]) -> dict[str, Any]:
    """ADR-0080 §A1-3: ``libraries.v3`` → ``libraries.v4``。

    * 各エントリの ``subsystem`` を ``block`` に改名する
    * ``revision`` を 1 にする。``updated_at`` は付けない (実時刻を捏造しない)
    * ``model_schema_version`` をリテラル ``"0.15"`` にする
    * ``uid`` は付けない (読み込みのたびに乱数を振ると同一性が不安定になる)
    * v0.64.0 以前に書き出された StateSpace 系 (m>=2 / p>=2) 入りエントリを発見的に
      検出して WARNING を出す。自動修復はしない (モデル 0.14 → 0.15 は非冪等で、版が
      分からないまま流すと Mux / Demux の二重挿入になる)

    入力 dict は書き換えない (エントリは浅いコピーを作り、本体には触れない)。
    """
    out = dict(data)
    entries = out.get("entries")
    if isinstance(entries, list):
        new_entries: list[Any] = []
        for entry in entries:
            if not isinstance(entry, dict):
                new_entries.append(entry)
                continue
            new_entry = {k: v for k, v in entry.items() if k not in ("subsystem", "block")}
            if "subsystem" in entry:
                new_entry["block"] = entry["subsystem"]
            new_entry["revision"] = DEFAULT_ENTRY_REVISION
            if _has_stale_lti_scalar_wiring([new_entry.get("block")], []):
                _logger.warning(
                    "library %r entry %r: a multi-input / multi-output state-space block "
                    "still has per-scalar port wiring. The entry was probably exported by "
                    "flode v0.64.0 or earlier and its connections will not line up after "
                    "placement. Re-export it from the original model (it is not repaired "
                    "automatically).",
                    out.get("name"),
                    entry.get("id"),
                )
            new_entries.append(new_entry)
        out["entries"] = new_entries
    out["model_schema_version"] = _V3_BODY_MODEL_SCHEMA_VERSION
    out["schema_version"] = "libraries.v4"
    return out


# 旧バージョンは migration 経由で受け入れる。v1 → v2 は Subsystem の派生 property 化
# (ADR-0039)、v2 → v3 は output_type 撤去 (v0.56.0)、v3 → v4 は本体フィールドの汎用化
# (ADR-0080)。v4 以降はモデル schema の変更ではライブラリ schema を bump しない
# (``model_schema_version`` + モデル側 migration、ADR-0080 §A1-4)。
_LIBRARY_MIGRATIONS: dict[tuple[str, str], Callable[[dict[str, Any]], dict[str, Any]]] = {
    ("libraries.v1", "libraries.v2"): _migrate_libraries_v1_to_v2,
    ("libraries.v2", "libraries.v3"): _migrate_libraries_v2_to_v3,
    ("libraries.v3", "libraries.v4"): _migrate_libraries_v3_to_v4,
}


# ----------------------------------------------------------------------------
# Validation helpers
# ----------------------------------------------------------------------------


def _require(data: dict[str, Any], key: str, type_: type | tuple[type, ...]) -> Any:
    if key not in data:
        raise LibraryFileError(f"Missing required key {key!r} in library data")
    value = data[key]
    if not isinstance(value, type_):
        type_label = (
            type_.__name__ if isinstance(type_, type) else " | ".join(t.__name__ for t in type_)
        )
        raise LibraryFileError(f"Key {key!r} must be {type_label}, got {type(value).__name__}")
    return value


def _optional(
    data: dict[str, Any], key: str, type_: type | tuple[type, ...], *, default: Any
) -> Any:
    if key not in data:
        return default
    value = data[key]
    if not isinstance(value, type_):
        type_label = (
            type_.__name__ if isinstance(type_, type) else " | ".join(t.__name__ for t in type_)
        )
        raise LibraryFileError(f"Key {key!r} must be {type_label}, got {type(value).__name__}")
    return value


def _optional_non_empty_str(data: dict[str, Any], key: str) -> str | None:
    """任意キー ``key`` を読む。あれば空でない文字列でなければならない。"""
    if key not in data:
        return None
    value = data[key]
    if not isinstance(value, str) or not value:
        raise LibraryFileError(f"Key {key!r} must be a non-empty string, got {value!r}")
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
            raise LibraryFileError(f"{path!r}[{k!r}] must be str, got {type(v).__name__}")
        out[k] = v
    return out


def _validate_revision(raw: dict[str, Any], where: str) -> int:
    """エントリの ``revision`` を読む。整数 >= 1 (bool 不可)、省略時は 1。"""
    if "revision" not in raw:
        return DEFAULT_ENTRY_REVISION
    revision = raw["revision"]
    if (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < DEFAULT_ENTRY_REVISION
    ):
        raise LibraryFileError(
            f"{where}: revision must be an integer >= {DEFAULT_ENTRY_REVISION}, got {revision!r}"
        )
    return revision


def _validate_updated_at(raw: dict[str, Any], where: str) -> str | None:
    """エントリの ``updated_at`` を読む。UTC 秒精度の "Z" 表記のみ、省略可。"""
    if "updated_at" not in raw:
        return None
    updated_at = raw["updated_at"]
    valid = isinstance(updated_at, str) and _UPDATED_AT_PATTERN.fullmatch(updated_at) is not None
    if valid:
        try:
            datetime.datetime.strptime(updated_at, _UPDATED_AT_FORMAT)
        except ValueError:
            valid = False
    if not valid:
        raise LibraryFileError(
            f"{where}: updated_at must be a UTC timestamp with second precision "
            f"(e.g. '2026-11-12T10:00:00Z'), got {updated_at!r}"
        )
    return str(updated_at)


def _ensure_schema_version(data: dict[str, Any]) -> dict[str, Any]:
    """``schema_version`` を確認し、必要なら最新版に migrate する。

    ``SUPPORTED_LIBRARY_SCHEMA_VERSIONS`` に含まれていても CURRENT より古ければ
    ``_LIBRARY_MIGRATIONS`` の連鎖を必ず通る。migration はメモリ上で行い、入力 dict も
    ファイルも書き換えない。
    """
    if "schema_version" not in data:
        raise LibraryFileError("Missing required key 'schema_version' in .flwlib.json")
    version = data["schema_version"]
    if not isinstance(version, str):
        raise LibraryFileError(f"schema_version must be a string, got {type(version).__name__}")
    if version == CURRENT_LIBRARY_SCHEMA_VERSION:
        return data
    # NOTE: ``SUPPORTED_LIBRARY_SCHEMA_VERSIONS in version`` で早期 return しない
    # こと。SUPPORTED に含まれていても CURRENT より古いバージョンは必ず migration
    # ループを経由しなければならない (= さもなくば古い JSON 形式のまま load される)。
    cur = version
    visited: set[str] = {cur}
    while cur != CURRENT_LIBRARY_SCHEMA_VERSION:
        next_step = next((to for (frm, to) in _LIBRARY_MIGRATIONS if frm == cur), None)
        if next_step is None:
            raise LibraryFileError(
                f"Unsupported library schema_version {version!r}. "
                f"Supported: {SUPPORTED_LIBRARY_SCHEMA_VERSIONS}, "
                f"current: {CURRENT_LIBRARY_SCHEMA_VERSION!r}. "
                f"No migration registered from {cur!r}."
            )
        if next_step in visited:
            raise LibraryFileError(f"Library migration cycle detected at {next_step!r}; aborting")
        try:
            data = _LIBRARY_MIGRATIONS[(cur, next_step)](data)
        except _MIGRATION_ERRORS as e:
            raise LibraryFileError(
                f"Library migration {cur!r} -> {next_step!r} failed: {type(e).__name__}: {e}"
            ) from e
        visited.add(next_step)
        cur = next_step
    return data


# ----------------------------------------------------------------------------
# エントリ本体の検証 (ADR-0080 §A2)
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class EntryBlockInfo:
    """エントリ本体から導出した情報 (浅い検証の結果、ADR-0080 §A2)。

    Attributes:
        kind: エントリ種別 (``"subsystem"`` / ``"python_function"``)。
        contains_python: 本体 (入れ子を含む) に PythonFunction があるか。
        python_block_paths: PythonFunction の部分木内パス (``/`` 区切りの block id 列)。
            本体自身が PythonFunction のときは空文字 ``""``。走査順。
        unknown_types: 本体内部で解決できなかった ``type`` 文字列 (重複なし・昇順)。
    """

    kind: str
    contains_python: bool
    python_block_paths: tuple[str, ...]
    unknown_types: tuple[str, ...]


@lru_cache(maxsize=1)
def _entry_kind_classes() -> tuple[tuple[str, type], ...]:
    """``_ENTRY_KINDS`` の基底クラスを解決して返す (初回のみ import)。"""
    resolved: list[tuple[str, type]] = []
    for kind, class_path in _ENTRY_KINDS:
        module_name, class_name = class_path.rsplit(".", 1)
        resolved.append((kind, getattr(importlib.import_module(module_name), class_name)))
    return tuple(resolved)


def _python_function_class() -> type:
    return dict(_entry_kind_classes())[ENTRY_KIND_PYTHON_FUNCTION]


def _resolve_entry_kind(block_type: Any) -> tuple[str, type]:
    """本体の ``type`` を解決し、``(種別, クラス)`` を返す。

    Raises:
        LibraryFileError: ``type`` が解決できない、または許可された種別の派生でない。
    """
    from ..core.persistence import resolve_block_class

    try:
        cls = resolve_block_class(block_type)
    except UnknownBlockTypeError as e:
        raise LibraryFileError(f"block.type cannot be resolved: {e}") from e
    for kind, base in _entry_kind_classes():
        if issubclass(cls, base):
            return kind, cls
    raise LibraryFileError(
        f"block.type must be a Subsystem or PythonFunction class path, got {block_type!r}"
    )


def _scan_inner_blocks(
    blocks: list[Any],
    prefix: str,
    python_paths: list[str],
    unknown_types: set[str],
    depth: int = 1,
) -> None:
    """``blocks`` を再帰走査し、PythonFunction のパスと未解決型を集める (exec しない)。

    Raises:
        LibraryFileError: 入れ子が :data:`MAX_ENTRY_BLOCK_DEPTH` を超える。
    """
    from ..core.persistence import resolve_block_class

    if depth > MAX_ENTRY_BLOCK_DEPTH:
        raise LibraryFileError(
            f"block nesting is deeper than {MAX_ENTRY_BLOCK_DEPTH} levels (at {prefix!r})"
        )
    python_cls = _python_function_class()
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_id = str(block.get("id"))
        path = f"{prefix}{BLOCK_PATH_SEPARATOR}{block_id}" if prefix else block_id
        # 壊れた入力では str とは限らない (resolve_block_class が型も検査して拒否する)
        block_type: Any = block.get("type")
        try:
            cls: type | None = resolve_block_class(block_type)
        except UnknownBlockTypeError:
            cls = None
            unknown_types.add(str(block_type))
        if cls is not None and issubclass(cls, python_cls):
            python_paths.append(path)
        params = block.get("params")
        inner = params.get("blocks") if isinstance(params, dict) else None
        if isinstance(inner, list):
            _scan_inner_blocks(inner, path, python_paths, unknown_types, depth + 1)


def analyze_entry_block(block: Any) -> EntryBlockInfo:
    """エントリ本体の**浅い検証**を行い、導出情報を返す (ADR-0080 §A2)。

    JSON 構造とトップレベル ``type`` の種別を確かめ、本体を JSON のまま再帰走査して
    PythonFunction の位置と未解決型を集める。ブロックは構築せず、ユーザーコードも
    実行しない (型解決の import だけを行い、それも allowlist 内の module に限る)。

    Args:
        block: エントリ本体 (``{id, type, params}``)。

    Returns:
        導出情報。

    Raises:
        LibraryFileError: 本体が dict でない、``params`` が dict でない、トップレベルの
            ``type`` が解決できない、または Subsystem / PythonFunction の派生でない。
    """
    if not isinstance(block, dict):
        raise LibraryFileError(f"block must be a dict, got {type(block).__name__}")
    kind, cls = _resolve_entry_kind(block.get("type"))
    params = block.get("params")
    if not isinstance(params, dict):
        raise LibraryFileError("block.params must be a dict (Block.to_dict() output)")
    python_paths: list[str] = []
    unknown_types: set[str] = set()
    if issubclass(cls, _python_function_class()):
        python_paths.append("")
    inner = params.get("blocks")
    if isinstance(inner, list):
        _scan_inner_blocks(inner, "", python_paths, unknown_types)
    return EntryBlockInfo(
        kind=kind,
        contains_python=bool(python_paths),
        python_block_paths=tuple(python_paths),
        unknown_types=tuple(sorted(unknown_types)),
    )


def canonicalize_entry_block(block: dict[str, Any]) -> dict[str, Any]:
    """エントリ本体の**深い検証**を行い、正規形を返す (ADR-0080 §A2 / §A4-5)。

    本体からブロックを実際に構築し、``to_dict()`` を取り直す。構築と再シリアライズは
    必ず ``serialization_build()`` 区間内で行うので、PythonFunction (入れ子を含む) の
    ユーザーコードは実行されない (``__init__`` は静的解析のみ、区間内の ``_build`` は
    exec 前に return する)。書き込み経路 (登録・取り込み) 専用で、読み込み時には
    呼ばない。

    Args:
        block: エントリ本体 (``{id, type, params}``)。書き換えない。

    Returns:
        正規形の本体 (``Block.to_dict()`` の出力からトップレベルの ``provenance`` を
        除いたもの)。

    Raises:
        LibraryFileError: 浅い検証に失敗、未知のブロック型を含む、または本体を
            構築・再シリアライズできない。
    """
    from ..core.block import serialization_build

    info = analyze_entry_block(block)
    if info.unknown_types:
        raise LibraryFileError(
            f"block contains unknown block type(s): {', '.join(info.unknown_types)}"
        )
    body = copy.deepcopy(block)
    _, cls = _resolve_entry_kind(body["type"])
    # ``Simulator.from_dict`` と同じ規約: port_shapes は optional な top-level キー
    extra_kwargs: dict[str, Any] = {
        key: [tuple(shape) for shape in body[key]]
        for key in ("port_shapes_in", "port_shapes_out")
        if key in body
    }
    factory = getattr(cls, "_from_dict", None)
    try:
        with serialization_build():
            if callable(factory):
                instance = factory(id=body.get("id"), **body["params"], **extra_kwargs)
            else:
                instance = cls(id=body.get("id"), **body["params"], **extra_kwargs)
            canonical: dict[str, Any] = instance.to_dict()
    except _BODY_BUILD_ERRORS as e:
        raise LibraryFileError(f"block cannot be built: {type(e).__name__}: {e}") from e
    # 本体は 「由来を除いた Block.to_dict() 出力」 (ADR-0080 §A1-1)。入れ子の由来は残す
    canonical.pop("provenance", None)
    return canonical


# ----------------------------------------------------------------------------
# Public entry point: validate dict → Library
# ----------------------------------------------------------------------------


def _validate_entry(raw: Any, *, library_name: str, index: int) -> LibraryEntry:
    """``entries[i]`` の dict を ``LibraryEntry`` に検証 + 変換する (内部)。

    未知キーは無視する (v4 のまま任意キーを足せるようにする、ADR-0080 §A1-6)。
    """
    # Library / LibraryEntry は ``flode.libraries.__init__`` 側に存在 (= public API)。
    # 循環 import を避けるため遅延 import する。
    from . import LibraryEntry

    where = f"library {library_name!r} entry #{index}"
    if not isinstance(raw, dict):
        raise LibraryFileError(f"{where}: entry must be a dict, got {type(raw).__name__}")
    entry_id = _require(raw, "id", str)
    display_name = _require(raw, "display_name", str)
    description = _optional(raw, "description", str, default="")
    category_suffix = _optional(raw, "category_suffix", str, default="")
    block = _require(raw, "block", dict)
    revision = _validate_revision(raw, where)
    updated_at = _validate_updated_at(raw, where)
    display_name_i18n = _validate_i18n_dict(
        raw.get("display_name_i18n"), f"{where}.display_name_i18n"
    )
    description_i18n = _validate_i18n_dict(raw.get("description_i18n"), f"{where}.description_i18n")
    try:
        # 種別判定と浅い検証は ``LibraryEntry.__post_init__`` が行う (導出属性)
        return LibraryEntry(
            id=entry_id,
            display_name=display_name,
            description=description,
            category_suffix=category_suffix,
            block=block,
            display_name_i18n=display_name_i18n,
            description_i18n=description_i18n,
            revision=revision,
            updated_at=updated_at,
        )
    except LibraryFileError as e:
        raise LibraryFileError(f"{where} (id={entry_id!r}): {e}") from e


def _migrate_entry_bodies(data: dict[str, Any], model_schema_version: str | None) -> dict[str, Any]:
    """各エントリ本体をモデル側の migration 連鎖に通す (ADR-0080 §A1-4 4B)。

    ``model_schema_version`` が現行のモデル schema と異なるとき、各本体を
    ``{"schema_version": v, "blocks": [body], "connections": []}`` に包んで
    ``migrate_to_current`` に通し、取り出す。入力 dict は書き換えない。

    本体はモデルのトップレベルより 1 段下に置かれるので、トップレベル限定の
    migration は本体自身には効かない (本体の意味論と一致する)。

    Raises:
        LibraryFileError: 未対応の ``model_schema_version``、または migration の失敗。
    """
    from ..core.persistence import CURRENT_SCHEMA_VERSION, migrate_to_current

    if model_schema_version is None or model_schema_version == CURRENT_SCHEMA_VERSION:
        return data
    new_entries: list[Any] = []
    for entry in data["entries"]:
        body = entry.get("block") if isinstance(entry, dict) else None
        if not isinstance(body, dict):
            new_entries.append(entry)  # 後段の検証で拒否される
            continue
        where = f"entry {entry.get('id')!r}"
        wrapped = {
            "schema_version": model_schema_version,
            "blocks": [copy.deepcopy(body)],
            "connections": [],
        }
        try:
            migrated_blocks = migrate_to_current(wrapped).get("blocks")
        except _MIGRATION_ERRORS as e:
            raise LibraryFileError(
                f"{where}: cannot migrate block from model_schema_version "
                f"{model_schema_version!r} to {CURRENT_SCHEMA_VERSION!r}: "
                f"{type(e).__name__}: {e}"
            ) from e
        if (
            not isinstance(migrated_blocks, list)
            or len(migrated_blocks) != 1
            or not isinstance(migrated_blocks[0], dict)
        ):
            raise LibraryFileError(
                f"{where}: model migration from model_schema_version "
                f"{model_schema_version!r} did not yield exactly one block"
            )
        new_entries.append({**entry, "block": migrated_blocks[0]})
    return {**data, "entries": new_entries}


def validate_library_dict(data: dict[str, Any], *, source_path: Path | None = None) -> Library:
    """既に load 済みの dict を schema 検証して :class:`flode.Library` を返す。

    本関数が ``flode.libraries.__init__`` から呼ばれる唯一の public entry point。
    旧 schema (v1〜v3) と古い ``model_schema_version`` の本体は、メモリ上で現行形式に
    変換してから検証する (入力 dict もファイルも書き換えない)。未知キーは無視する。

    Args:
        data: ``json.loads()`` で読んだ辞書。
        source_path: 読み込み元 path (debug 用、オプショナル)。

    Returns:
        検証済みの :class:`flode.Library`。本体は常に現行のモデル schema 形式で、
        ``model_schema_version`` も現行値になる。

    Raises:
        LibraryFileError: 必須キー欠落、schema_version 未対応、entries 不正、
            本体の型が許可外など。
    """
    from ..core.persistence import CURRENT_SCHEMA_VERSION
    from . import Library  # 循環 import 回避の遅延 import

    if not isinstance(data, dict):
        raise LibraryFileError(f"Library data must be a dict, got {type(data).__name__}")
    data = _ensure_schema_version(data)
    name = _require(data, "name", str)
    if not name:
        raise LibraryFileError("Library 'name' must be a non-empty string")
    display_name = _optional(data, "display_name", str, default=name)
    description = _optional(data, "description", str, default="")
    version = _optional(data, "version", str, default="")
    uid = _optional_non_empty_str(data, "uid")
    model_schema_version = _optional_non_empty_str(data, "model_schema_version")
    _require(data, "entries", list)
    data = _migrate_entry_bodies(data, model_schema_version)
    seen_ids: set[str] = set()
    entries = []
    for idx, raw in enumerate(data["entries"]):
        entry = _validate_entry(raw, library_name=name, index=idx)
        if entry.id in seen_ids:
            raise LibraryFileError(f"Library {name!r}: duplicate entry id {entry.id!r}")
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
        uid=uid,
        # 本体はここまでで現行のモデル schema 形式になっている
        model_schema_version=CURRENT_SCHEMA_VERSION,
    )
