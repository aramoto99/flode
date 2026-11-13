"""Block registry の合成 (組み込み + ユーザーブロック) と ``blocks.v3`` payload (ADR-0081 §8-A)。

``app.state.block_registry`` には ``BlockCatalog`` (不変) を置く。組み込みのメタデータは起動時に
1 回だけ作り、ユーザーブロックの分は起動時と再読み込み時に作り直して、新しい ``BlockCatalog``
を 1 回の代入で差し替える (ADR-0081 §2-A 手順 6)。読み手は 1 度だけ参照を取るので、
``GET /blocks`` は差し替え前後どちらか一方の完全な一覧 (ブロック・読み込みエラー・ソース・
files API で守るルート) を返す。

非 loopback bind (``Settings.loopback_bind=False``) では、REST に絶対パスやユーザーコード由来の
文字列を出さない: ``sources[].root`` は ``null``、``load_errors[].message`` は種別ごとの固定文
(``LOAD_ERROR_SUMMARIES``) にする。場所は ``kind`` / ``path`` (ルートからの相対) / ``line`` /
``type_path`` で分かる。全文はサーバのログ (``flode.userblocks``) にある。
"""

from __future__ import annotations

import importlib.machinery
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..userblocks import (
    WORKSPACE_BLOCKS_DIR,
    BlockLoadReport,
    LoadError,
    LoadRequest,
    SourceInfo,
    load_sources,
)
from .registry import (
    BlockMetadata,
    build_block_registry,
    build_user_block_metadata,
    metadata_to_dict,
)
from .registry_translations import SUPPORTED_LOCALES
from .settings import Settings

#: ``GET /api/v1/blocks`` の schema (ADR-0081 §8-A、blocks.v2 からの追加のみ)。
BLOCKS_SCHEMA_VERSION = "blocks.v3"

#: 非 loopback bind で ``load_errors[].message`` の代わりに返す固定文 (``kind`` ごと)。
LOAD_ERROR_SUMMARIES: dict[str, str] = {
    "syntax": "The file has a syntax error. Details are in the server log.",
    "import": "The file raised an error while it was imported. Details are in the server log.",
    "spec": "The block definition was not accepted. Details are in the server log.",
    "conflict": "The name conflicts with another block or package. Details are in the server log.",
    "config": "The source could not be read. Details are in the server log.",
}
_GENERIC_LOAD_ERROR_SUMMARY = "The block could not be loaded. Details are in the server log."
#: ``severity="info"`` (動作に影響しない告知) の固定文。
_INFO_SUMMARY = "A notice about this source. Details are in the server log."

_DISABLED_REASON = "user blocks are not enabled in this server configuration"
_RELOAD_NON_LOOPBACK_REASON = (
    "reloading blocks is not available when the server is bound to a non-loopback address; "
    "blocks are read only at startup"
)
_RELOAD_DISABLED_REASON = "reloading blocks is disabled in this server configuration"


@dataclass(frozen=True)
class BlockCatalog:
    """block registry の 1 世代分 (不変)。

    Attributes:
        builtin: 組み込みブロックのメタデータ (起動時に 1 回だけ作り、再読み込みでは使い回す)。
        report: ユーザーブロックの読み込み結果 (読まない設定なら ``None``)。
        blocks: パレットに出す全ブロック (組み込み → ユーザーブロック)。ユーザーブロックと
            同じ型名の組み込み側エントリは捨てる (管理型表を優先、ADR-0081 §1-D)。
        protected_roots: 非 loopback bind で files API による変更を拒否するフォルダ / ファイル
            (``user_block_roots`` の結果)。
    """

    builtin: tuple[BlockMetadata, ...]
    report: BlockLoadReport | None
    blocks: tuple[BlockMetadata, ...]
    protected_roots: tuple[Path, ...]


def _module_locations(module_name: str) -> list[Path]:
    """``modules`` の 1 件の実体の場所 (パッケージはフォルダ、単一ファイルはそのファイル)。

    読み込み済みなら ``sys.modules`` の ``__file__``、さらにトップレベルの名前を
    ``PathFinder.find_spec`` で探す (どちらもユーザーコードを実行しない)。見つからなければ空。
    """
    locations: list[Path] = []
    module = sys.modules.get(module_name)
    file = getattr(module, "__file__", None) if module is not None else None
    if isinstance(file, str):
        path = Path(file)
        is_package = getattr(module, "__path__", None) is not None
        locations.append(path.parent if is_package else path)
    top = module_name.split(".", 1)[0]
    if not top.isidentifier():
        return locations
    try:
        spec = importlib.machinery.PathFinder.find_spec(top)
    except (ImportError, OSError, ValueError):
        return locations
    if spec is None:
        return locations
    if spec.submodule_search_locations:
        locations.extend(Path(p) for p in spec.submodule_search_locations)
    elif spec.origin and os.path.isabs(spec.origin):
        locations.append(Path(spec.origin))
    return locations


def user_block_roots(settings: Settings, report: BlockLoadReport | None) -> tuple[Path, ...]:
    """非 loopback bind で files API から守る管理ソースのルートを集める (ADR-0081 §6-A)。

    ワークスペースの ``blocks/`` (読まない設定でも常に)、config ``dirs`` のフォルダ、
    ``modules`` の実体 (パッケージのフォルダ、単一ファイルのモジュールはそのファイル)。
    ``settings.user_blocks_request`` は読まない設定でも CLI が入れるので、次回の起動で
    読まれるものも守れる。ワークスペースの外のものは files API では触れないので害は無い。

    Args:
        settings: サーバ設定。
        report: 起動時の読み込み結果 (読まない設定なら ``None``)。

    Returns:
        重複を除いたパス (最初に現れた表記のまま)。
    """
    candidates: list[Path] = [Path(settings.workspace_root) / WORKSPACE_BLOCKS_DIR]
    modules: list[str] = []
    request = settings.user_blocks_request
    if request is not None:
        if request.workspace is not None:
            candidates.append(request.workspace / WORKSPACE_BLOCKS_DIR)
        candidates.extend(directory for _, directory in request.dirs)
        modules.extend(request.modules)
    if report is not None:
        candidates.extend(Path(s.root) for s in report.sources if s.root)
        modules.extend(s.label for s in report.sources if s.kind == "module")
    for module_name in dict.fromkeys(modules):
        candidates.extend(_module_locations(module_name))
    seen: set[str] = set()
    roots: list[Path] = []
    for path in candidates:
        key = os.path.normcase(str(path.resolve()))
        if key not in seen:
            seen.add(key)
            roots.append(path)
    return tuple(roots)


def compose_catalog(
    builtin: Sequence[BlockMetadata], report: BlockLoadReport | None, settings: Settings
) -> BlockCatalog:
    """組み込みのメタデータと読み込み結果から ``BlockCatalog`` を作る。

    Args:
        builtin: 組み込みブロックのメタデータ。
        report: ユーザーブロックの読み込み結果 (読まない設定なら ``None``)。
        settings: サーバ設定 (files API で守るルートの計算に使う)。

    Returns:
        新しい世代の ``BlockCatalog``。
    """
    user = [build_user_block_metadata(info) for info in report.block_infos] if report else []
    user_types = {m.type_path for m in user}
    blocks = tuple(m for m in builtin if m.type_path not in user_types) + tuple(user)
    return BlockCatalog(
        builtin=tuple(builtin),
        report=report,
        blocks=blocks,
        protected_roots=user_block_roots(settings, report),
    )


def load_user_blocks(settings: Settings) -> BlockLoadReport | None:
    """設定に従ってユーザーブロックを読む (起動時)。

    ``user_blocks_request`` が無ければワークスペース ``blocks/`` だけを読む。

    Args:
        settings: サーバ設定。

    Returns:
        読み込み結果。読まない設定なら ``None``。

    Raises:
        BlockReloadInProgressError: 別の読み込み (Python API 等) が進行中。
    """
    if not settings.user_blocks_enabled:
        return None
    request = settings.user_blocks_request or LoadRequest(workspace=settings.workspace_root)
    return load_sources(request)


def initial_catalog(settings: Settings) -> BlockCatalog:
    """起動時の ``BlockCatalog`` (組み込みを作り、設定に従ってユーザーブロックを読む)。

    サーバの終了時 (lifespan の後始末) に ``unload_sources()`` は呼ばない: 読み込み状態は
    プロセス全体のもので、プロセスの終了とともに消える。同じプロセスで Python API
    (``flode.load_blocks``) を使っている埋め込み利用者の状態を、アプリの終了で勝手に
    外さないためでもある。

    Args:
        settings: サーバ設定。

    Returns:
        起動時の ``BlockCatalog``。

    Raises:
        BlockReloadInProgressError: 別の読み込み (Python API 等) が進行中。
    """
    builtin = build_block_registry()
    return compose_catalog(builtin, load_user_blocks(settings), settings)


def reload_allowed(settings: Settings) -> bool:
    """``POST /blocks/reload`` を受け付けるか (有効・許可あり・loopback bind の 3 条件)。

    Args:
        settings: サーバ設定。

    Returns:
        3 条件をすべて満たすときだけ ``True``。
    """
    return (
        settings.user_blocks_enabled
        and settings.user_blocks_reload_allowed
        and settings.loopback_bind
    )


def disabled_reason(settings: Settings) -> str:
    """ユーザーブロックを読まない理由 (``user_blocks_enabled=False`` のとき)。

    Args:
        settings: サーバ設定。

    Returns:
        ``settings.user_blocks_reason``、空なら既定の説明。
    """
    return settings.user_blocks_reason or _DISABLED_REASON


def reload_rejection_reason(settings: Settings) -> str:
    """再読み込みを受け付けない理由 (``reload_allowed(settings)`` が偽のとき)。

    Args:
        settings: サーバ設定。

    Returns:
        英語の 1 文。
    """
    if not settings.user_blocks_enabled:
        return disabled_reason(settings)
    if not settings.loopback_bind:
        return _RELOAD_NON_LOOPBACK_REASON
    return _RELOAD_DISABLED_REASON


# ---------------------------------------------------------------------------
# payload
# ---------------------------------------------------------------------------


def _source_dict(source: SourceInfo, *, remote: bool) -> dict[str, Any]:
    return {
        "id": source.id,
        "kind": source.kind,
        "label": source.label,
        "root": None if remote else source.root,
        "reloadable": source.reloadable,
        "from_cwd": source.from_cwd,
        "files": [{"path": f.path, "status": f.status} for f in source.files],
    }


def _error_dict(error: LoadError, *, remote: bool) -> dict[str, Any]:
    data = error.to_dict()
    if remote:
        if error.severity == "info":
            data["message"] = _INFO_SUMMARY
        else:
            data["message"] = LOAD_ERROR_SUMMARIES.get(error.kind, _GENERIC_LOAD_ERROR_SUMMARY)
    return data


def user_blocks_status(settings: Settings, report: BlockLoadReport | None) -> dict[str, Any]:
    """``GET /blocks`` の ``user_blocks`` (有効か・再読み込みできるか・できない理由)。

    Args:
        settings: サーバ設定。
        report: 読み込み結果 (読まない設定なら ``None``)。

    Returns:
        ``{enabled, reason, reload_allowed, reload_reason, restart_required_sources}``。
    """
    enabled = settings.user_blocks_enabled
    can_reload = reload_allowed(settings)
    return {
        "enabled": enabled,
        "reason": None if enabled else disabled_reason(settings),
        "reload_allowed": can_reload,
        "reload_reason": None if can_reload else reload_rejection_reason(settings),
        "restart_required_sources": list(report.restart_required_sources) if report else [],
    }


def registry_payload(catalog: BlockCatalog, settings: Settings) -> dict[str, Any]:
    """``GET /api/v1/blocks`` の本文 (``blocks.v3``)。

    Args:
        catalog: 返す世代。
        settings: サーバ設定 (非 loopback なら ``root`` と ``message`` を出さない)。

    Returns:
        JSON にそのまま載せられる dict。
    """
    remote = not settings.loopback_bind
    report = catalog.report
    return {
        "schema_version": BLOCKS_SCHEMA_VERSION,
        "supported_locales": list(SUPPORTED_LOCALES),
        "blocks": [metadata_to_dict(m, include_full_docstring=False) for m in catalog.blocks],
        "sources": [_source_dict(s, remote=remote) for s in report.sources] if report else [],
        "load_errors": [_error_dict(e, remote=remote) for e in report.errors] if report else [],
        "user_blocks": user_blocks_status(settings, report),
    }


def reload_payload(catalog: BlockCatalog, settings: Settings) -> dict[str, Any]:
    """``POST /api/v1/blocks/reload`` の本文 (``GET /blocks`` と同じ形 + 差分)。

    ``errors`` は ``load_errors`` と同じ内容 (SPEC-0033 の応答形との互換のため)。

    Args:
        catalog: 再読み込み後の世代。
        settings: サーバ設定。

    Returns:
        ``registry_payload`` に ``added`` / ``removed`` / ``changed`` /
        ``restart_required_sources`` / ``errors`` を足した dict。
    """
    payload = registry_payload(catalog, settings)
    report = catalog.report
    payload["added"] = list(report.added) if report else []
    payload["removed"] = list(report.removed) if report else []
    payload["changed"] = list(report.changed) if report else []
    payload["restart_required_sources"] = list(report.restart_required_sources) if report else []
    payload["errors"] = payload["load_errors"]
    return payload
