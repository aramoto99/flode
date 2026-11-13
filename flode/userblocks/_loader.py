"""管理ソースの走査・import・検証・管理型表の差し替え・再読み込み (ADR-0081 §論点 1・2・6・10)。

1 回の読み込み (``load_sources``) の手順 (§2-A):

1. プロセス全体のロックを非ブロッキングで取る (取れなければ ``BlockReloadInProgressError``)。
2. 予約ルート配下 (``flode_ws`` / ``flode_dirs``) を ``sys.modules`` から外す。``modules`` は外さない。
3. ``importlib.invalidate_caches()``、予約名の衝突確認、finder のルートを差し替える。
4. 走査 (相対パスの昇順)・import (ファイル単位で隔離)・ブロックの検証 (P1・P2・§10・X-1・P6・§7)。
5. コミット点: 管理型表を新しいオブジェクトで 1 回だけ差し替える。
6. 前回との差分 (追加・削除・変更) を ``type_path`` で突合して返す。

失敗したファイルがあっても前回の状態には戻さない (last-known-good を持たない)。
"""

from __future__ import annotations

import contextlib
import dataclasses
import functools
import importlib
import inspect
import json
import linecache
import logging
import os
import pkgutil
import sys
import threading
import traceback
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

from ..core import signals
from ..core.block import Block
from ..core.block_metadata import HIDDEN_ATTRIBUTE
from ..core.persistence import (
    RESERVED_USER_BLOCK_ROOTS,
    _clear_managed_block_types,
    _replace_managed_block_types,
    block_type_path,
    to_json_value,
)
from ..exceptions import BlockReloadInProgressError, BlockSpecError
from ._docmeta import read_params, resolve_metadata
from ._finder import (
    DIRS_ROOT_NAME,
    PACKAGE_INIT,
    SOURCE_SUFFIX,
    WORKSPACE_ROOT_NAME,
    FinderRoots,
    ReservedRootFinder,
    has_exact_entry,
    is_module_name_segment,
    is_our_module,
    is_within_root,
)
from ._model import (
    DIR_SOURCE_PREFIX,
    MODULE_SOURCE_PREFIX,
    WORKSPACE_SOURCE_ID,
    BlockLoadReport,
    LoadError,
    LoadErrorKind,
    LoadRequest,
    SourceFile,
    SourceInfo,
    UserBlockInfo,
    UserParamSpec,
)

_logger = logging.getLogger("flode.userblocks")

#: import がこの秒数を超えたら原因ファイル名入りの WARNING を出す (タイムアウトはしない、§6-C)。
IMPORT_WARN_SECONDS = 10.0
#: 読み込みエラーのメッセージ (ユーザーコード由来の例外文字列を含む) の最大長。
MAX_MESSAGE_CHARS = 500
#: ``blocks/`` 以下を走査する最大の深さ (シンボリックリンクの循環などへの保険)。
MAX_SCAN_DEPTH = 32
#: 1 つのルートから読み込むファイル数の上限 (リンクで同じ中身を何度も辿る場合への保険)。
MAX_SCAN_ENTRIES = 10_000
#: ワークスペース内のブロック置き場のフォルダ名。
WORKSPACE_BLOCKS_DIR = "blocks"
_TRUNCATION_MARK = "…"
_UNPRINTABLE = "<unprintable>"
_OUTSIDE_LINK_MESSAGE = (
    "this is a link (symlink / junction) pointing outside the source folder; it is not read"
)
_INVALID_NAME_MESSAGE = "not a valid Python module name; this file or folder is ignored"
_SHADOWED_MESSAGE = (
    "a package folder with the same name exists; the package is used and this file is ignored"
)
#: 組み込みクラス名の収集対象パッケージ (X-1、registry の walk 対象のうちブロックを定義する所)。
_BUILTIN_BLOCK_PACKAGES = ("flode.blocks", "flode.subsystems")


@dataclass(frozen=True)
class _ModuleResult:
    """モジュール 1 つ分の読み込み結果 (``modules`` の再読み込みで引き継ぐ)。"""

    infos: tuple[UserBlockInfo, ...]
    errors: tuple[LoadError, ...]


@dataclass(frozen=True)
class _State:
    request: LoadRequest
    report: BlockLoadReport
    infos: Mapping[str, UserBlockInfo]
    module_results: Mapping[str, _ModuleResult]
    roots: tuple[Path, ...]


@dataclass(frozen=True)
class _ScanEntry:
    module_suffix: str
    rel: str
    file: Path


@dataclass
class _Collector:
    """1 回の読み込みで集めるもの。"""

    infos: dict[str, UserBlockInfo] = field(default_factory=dict)
    errors: list[LoadError] = field(default_factory=list)
    sources: list[SourceInfo] = field(default_factory=list)
    module_results: dict[str, _ModuleResult] = field(default_factory=dict)
    roots: list[Path] = field(default_factory=list)

    def add_infos(self, infos: Iterable[UserBlockInfo]) -> None:
        for info in infos:
            # modules の重複指定 (同一クラス) は 1 つに畳む (§1-E)
            self.infos.setdefault(info.type_path, info)


_RELOAD_LOCK = threading.Lock()
_state: _State | None = None
_finder: ReservedRootFinder | None = None


class _BlockRejectedError(BlockSpecError):
    """ブロック単位の読み込みエラー (種別付き)。

    このモジュールの中で送出して ``_collect_blocks`` が必ず捕捉し、``LoadError`` に変換する
    (外へは出ない) ので、公開例外の ``exceptions.py`` ではなくここに置く。
    """

    def __init__(self, message: str, *, kind: LoadErrorKind = "spec") -> None:
        super().__init__(message)
        self.kind: LoadErrorKind = kind


# ---------------------------------------------------------------------------
# 公開 (パッケージ内) API
# ---------------------------------------------------------------------------


def current_report() -> BlockLoadReport | None:
    """最後の読み込み結果 (未読み込み / ``unload`` 後は ``None``)。"""
    state = _state
    return state.report if state is not None else None


def load_sources(request: LoadRequest) -> BlockLoadReport:
    """管理ソース全体を ``request`` で置き換えて読み込む。

    ワークスペースと ``dirs`` は毎回ソースから実行し直す。``modules`` は通常の import なので、
    既に ``sys.modules`` にあるモジュールは再実行せず、そのモジュールのクラスを読み直すだけ
    (前回の読み込みエラーは引き継がず、改めて検証する)。

    途中で想定外の例外 (``KeyboardInterrupt`` 等) で中断した場合は、予約ルートの
    ``sys.modules`` と finder のルートを呼び出し前の状態に戻してから再送出する (管理型表は
    最後にだけ差し替えるので前回のまま)。

    Args:
        request: 読み込む管理ソース。

    Returns:
        読み込み結果 (前回の状態との差分付き)。

    Raises:
        BlockReloadInProgressError: 別の読み込み / 再読み込みが進行中。
    """
    with _try_lock():
        return _load_locked(request, reuse_modules=False)


def reload_sources() -> BlockLoadReport:
    """前回と同じ管理ソースを読み込み直す (§2-A)。

    ワークスペースの ``blocks/`` と ``dirs`` だけを import し直し、``modules`` は前回の結果
    (クラス・エラー) を引き継ぐ (Q5a)。一度も読み込んでいなければ空の指定で読む。

    Raises:
        BlockReloadInProgressError: 別の読み込み / 再読み込みが進行中。
    """
    with _try_lock():
        previous = _state
        request = previous.request if previous is not None else LoadRequest()
        return _load_locked(request, reuse_modules=True)


def unload_sources() -> None:
    """全管理ソースを外す (管理型表を空にし、予約ルートを ``sys.modules`` から外し、finder を外す)。

    Raises:
        BlockReloadInProgressError: 別の読み込み / 再読み込みが進行中。
    """
    global _state, _finder
    with _try_lock():
        previous = _state
        _purge_reserved_modules()
        if previous is not None:
            _purge_linecache(previous.roots)
        if _finder is not None:
            if _finder in sys.meta_path:
                sys.meta_path.remove(_finder)
            _finder = None
        _clear_managed_block_types()
        _state = None
        importlib.invalidate_caches()


@contextlib.contextmanager
def _try_lock() -> Iterator[None]:
    """再読み込みロックを非ブロッキングで取る (待ち行列にしない、§2-A 手順 1)。"""
    if not _RELOAD_LOCK.acquire(blocking=False):
        raise BlockReloadInProgressError(
            "user blocks are already being loaded or reloaded; try again when it finishes"
        )
    try:
        yield
    finally:
        _RELOAD_LOCK.release()


# ---------------------------------------------------------------------------
# 読み込み本体
# ---------------------------------------------------------------------------


def _load_locked(request: LoadRequest, *, reuse_modules: bool) -> BlockLoadReport:
    """読み込み本体。中断されたら ``sys.modules`` と finder のルートを呼び出し前に戻す。"""
    saved_modules = _reserved_module_snapshot()
    saved_roots = _finder.roots if _finder is not None else None
    try:
        return _load_and_commit(request, reuse_modules=reuse_modules)
    except BaseException:
        # 管理型表は _load_and_commit の最後でしか差し替えないので前回のまま。
        # 予約ルートのモジュールと finder のルートをそれに合わせて戻す (表との整合)
        _purge_reserved_modules()
        sys.modules.update(saved_modules)
        if _finder is not None:
            _finder.roots = saved_roots if saved_roots is not None else FinderRoots()
        importlib.invalidate_caches()
        raise


def _reserved_module_snapshot() -> dict[str, ModuleType]:
    """この finder が作った予約ルート配下のモジュール (中断時の復元用)。"""
    return {
        name: module
        for name, module in list(sys.modules.items())
        if name.split(".", 1)[0] in RESERVED_USER_BLOCK_ROOTS and is_our_module(module)
    }


def _load_and_commit(request: LoadRequest, *, reuse_modules: bool) -> BlockLoadReport:
    global _state
    previous = _state
    _purge_reserved_modules()
    if previous is not None:
        _purge_linecache(previous.roots)
    importlib.invalidate_caches()

    collected = _Collector()
    workspace_blocks = _prepare_workspace(request, collected)
    dir_roots = _prepare_dirs(request, collected)
    finder = _install_finder()
    finder.roots = FinderRoots(
        workspace=workspace_blocks,
        dirs=dict(dir_roots),
        dirs_enabled=bool(dir_roots),
    )
    collected.roots.extend([*([workspace_blocks] if workspace_blocks else []), *dir_roots.values()])
    _purge_linecache(collected.roots)

    if workspace_blocks is not None:
        _load_tree(
            collected,
            source=SourceInfo(
                id=WORKSPACE_SOURCE_ID,
                kind="workspace",
                label=f"{WORKSPACE_BLOCKS_DIR}/",
                root=str(workspace_blocks),
                reloadable=True,
                from_cwd=request.workspace_from_cwd,
            ),
            root=workspace_blocks,
            package=WORKSPACE_ROOT_NAME,
            display_prefix=f"{WORKSPACE_BLOCKS_DIR}/",
        )
    for name, directory in dir_roots.items():
        _load_tree(
            collected,
            source=SourceInfo(
                id=f"{DIR_SOURCE_PREFIX}{name}",
                kind="dir",
                label=name,
                root=str(directory),
                reloadable=True,
            ),
            root=directory,
            package=f"{DIRS_ROOT_NAME}.{name}",
            display_prefix="",
        )
    previous_modules = previous.module_results if previous is not None and reuse_modules else {}
    for module_name in dict.fromkeys(request.modules):
        _load_module_source(collected, module_name, previous_modules.get(module_name))

    infos = dict(sorted(collected.infos.items()))
    old_infos: Mapping[str, UserBlockInfo] = previous.infos if previous is not None else {}
    report = BlockLoadReport(
        blocks=tuple(infos),
        block_infos=tuple(infos.values()),
        errors=tuple(collected.errors),
        sources=tuple(collected.sources),
        added=tuple(tp for tp in infos if tp not in old_infos),
        removed=tuple(tp for tp in old_infos if tp not in infos),
        changed=tuple(
            tp
            for tp, info in infos.items()
            if tp in old_infos and _comparable(old_infos[tp]) != _comparable(info)
        ),
        restart_required_sources=tuple(s.id for s in collected.sources if s.kind == "module"),
    )
    # コミット点 (§2-A 手順 6): 新しい表を 1 回の代入で差し替える (これより前で失敗したら
    # _load_locked が sys.modules と finder のルートを戻す)
    _replace_managed_block_types(
        {tp: info.block_class for tp, info in infos.items()},
        allowed_modules=request.modules,
    )
    _state = _State(
        request=request,
        report=report,
        infos=infos,
        module_results=dict(collected.module_results),
        roots=tuple(collected.roots),
    )
    _log_summary(report)
    return report


def _comparable(info: UserBlockInfo) -> str:
    """差分判定用の正規化文字列 (クラス本体を除く全フィールドの JSON)。

    既定値を JSON 文字列で比べるので、``NaN`` の既定値でも毎回「変更」にはならない。
    """
    data: dict[str, object] = {
        f.name: getattr(info, f.name) for f in dataclasses.fields(info) if f.name != "block_class"
    }
    data["params"] = [dataclasses.asdict(p) for p in info.params]
    return json.dumps(data, sort_keys=True, default=repr)


def _install_finder() -> ReservedRootFinder:
    global _finder
    if _finder is None:
        _finder = ReservedRootFinder()
    if _finder not in sys.meta_path:
        sys.meta_path.insert(0, _finder)
    return _finder


def _purge_reserved_modules() -> None:
    """予約ルート配下のモジュールを ``sys.modules`` から外す (この finder が作ったものだけ)。"""
    for name in list(sys.modules):
        top = name.split(".", 1)[0]
        if top in RESERVED_USER_BLOCK_ROOTS and is_our_module(sys.modules.get(name)):
            sys.modules.pop(name, None)


def _purge_linecache(roots: Iterable[Path]) -> None:
    """``roots`` 配下のファイルの行キャッシュを捨てる (同秒・同サイズの書き換えでも新しい行を表示)。"""
    prefixes = tuple(os.path.normcase(str(r)) + os.sep for r in roots)
    if not prefixes:
        return
    for filename in list(linecache.cache):
        if os.path.normcase(filename).startswith(prefixes):
            linecache.cache.pop(filename, None)


def _reserved_name_conflict(name: str) -> str | None:
    """予約名 ``name`` が既存のパッケージと衝突していれば、その場所の説明を返す (§1-E)。"""
    existing = sys.modules.get(name)
    if existing is not None and not is_our_module(existing):
        return str(getattr(existing, "__file__", None) or existing)
    for finder in list(sys.meta_path):
        if isinstance(finder, ReservedRootFinder):
            continue
        find_spec = getattr(finder, "find_spec", None)
        if find_spec is None:
            continue
        try:
            spec = find_spec(name, None)
        except Exception as e:  # noqa: BLE001 - 他者の finder の境界。判定不能は衝突扱い (fail-closed)
            _logger.warning(
                "user blocks: finder %r failed while checking the reserved name %r: %s",
                type(finder).__name__,
                name,
                _exception_text(e),
            )
            return f"<cannot be determined: {type(finder).__name__} raised {type(e).__name__}>"
        if spec is not None:
            locations = list(spec.submodule_search_locations or [])
            return str(spec.origin or (locations[0] if locations else name))
    return None


def _is_home_or_filesystem_root(path: Path) -> bool:
    """``path`` がファイルシステムのルートかホームディレクトリそのものか。

    ホームディレクトリが判定できないときは ``True`` (読まない側に倒す、fail-closed)。
    """
    if path == path.parent:
        return True
    try:
        home = Path.home().resolve()
    except (KeyError, OSError, RuntimeError):
        return True
    return path == home


def _prepare_workspace(request: LoadRequest, collected: _Collector) -> Path | None:
    """ワークスペースの ``blocks/`` を決める (読まない場合は理由を記録して ``None``)。"""
    if request.workspace is None:
        return None
    workspace = request.workspace.resolve()
    if request.workspace_from_cwd and _is_home_or_filesystem_root(workspace):
        # R-1: cwd から決まったワークスペースがホーム / ルートなら読まない (明示指定なら読む)
        _logger.info(
            "user blocks: not reading %r because the workspace was taken from the current "
            "directory and it is the home directory or a filesystem root",
            str(workspace / WORKSPACE_BLOCKS_DIR),
        )
        collected.errors.append(
            LoadError(
                source=WORKSPACE_SOURCE_ID,
                path=None,
                line=None,
                kind="config",
                message=(
                    "blocks/ was not read: the workspace is the current directory and it is the "
                    "home directory or a filesystem root (or the home directory could not be "
                    "determined). Pass the workspace explicitly to read it."
                ),
                severity="info",
            )
        )
        return None
    if not workspace.is_dir():
        collected.errors.append(
            _config_error(WORKSPACE_SOURCE_ID, f"workspace folder does not exist: {workspace}")
        )
        return None
    blocks = workspace / WORKSPACE_BLOCKS_DIR
    if not blocks.exists():
        return None
    if not blocks.is_dir():
        collected.errors.append(
            _config_error(WORKSPACE_SOURCE_ID, f"{blocks} is not a folder; blocks/ was not read")
        )
        return None
    conflict = _reserved_name_conflict(WORKSPACE_ROOT_NAME)
    if conflict is not None:
        collected.errors.append(_reserved_conflict_error(WORKSPACE_SOURCE_ID, conflict))
        return None
    return blocks


def _prepare_dirs(request: LoadRequest, collected: _Collector) -> dict[str, Path]:
    """config ``dirs`` のうち読めるフォルダを返す (不在・ファイル指定は読み込みエラー)。"""
    roots: dict[str, Path] = {}
    for name, directory in request.dirs:
        source_id = f"{DIR_SOURCE_PREFIX}{name}"
        if not directory.exists():
            collected.errors.append(_config_error(source_id, f"folder does not exist: {directory}"))
        elif not directory.is_dir():
            collected.errors.append(_config_error(source_id, f"not a folder: {directory}"))
        else:
            roots[name] = directory.resolve()
    if not roots:
        return roots
    conflict = _reserved_name_conflict(DIRS_ROOT_NAME)
    if conflict is not None:
        for name in roots:
            collected.errors.append(
                _reserved_conflict_error(f"{DIR_SOURCE_PREFIX}{name}", conflict, DIRS_ROOT_NAME)
            )
        return {}
    return roots


def _config_error(source: str, message: str) -> LoadError:
    return LoadError(source=source, path=None, line=None, kind="config", message=message)


def _reserved_conflict_error(
    source: str, location: str, name: str = WORKSPACE_ROOT_NAME
) -> LoadError:
    return LoadError(
        source=source,
        path=None,
        line=None,
        kind="conflict",
        message=_truncate(
            f"the reserved package name {name!r} is already used by an existing package "
            f"({location}); this source was not read"
        ),
    )


# ---------------------------------------------------------------------------
# フォルダ (ワークスペース / dirs) の走査と import
# ---------------------------------------------------------------------------


def _scan_tree(root: Path) -> tuple[list[_ScanEntry], list[tuple[str, str]]]:
    """``root`` 以下の読み込み対象を相対パスの昇順で返す。

    名前が ``_`` で始まるファイル・フォルダと、``__init__.py`` の無いフォルダは対象外 (§1-C、P1)。
    読まなかった理由を告知すべきもの (無効な名前、ルートの外を指すリンク、パッケージに隠れる
    同名の ``.py``) は ``(相対パス, 理由)`` で返す。

    Returns:
        ``(読み込み対象, 告知)``。
    """
    entries: list[_ScanEntry] = []
    notes: list[tuple[str, str]] = []

    def walk(directory: Path, parts: list[str], ancestors: frozenset[str]) -> None:
        real = os.path.normcase(os.path.realpath(directory))
        # 循環リンク (祖先の実体に戻るリンク) と深すぎる階層は辿らない
        if real in ancestors or len(parts) > MAX_SCAN_DEPTH:
            return
        try:
            items = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError:
            return
        package_names = {
            item.name
            for item in items
            if item.is_dir() and has_exact_entry(Path(item.path), PACKAGE_INIT)
        }
        for item in items:
            if item.name.startswith("_") or len(entries) >= MAX_SCAN_ENTRIES:
                continue
            rel = "/".join([*parts, item.name])
            path = Path(item.path)
            is_source = item.is_file() and item.name.endswith(SOURCE_SUFFIX)
            if not is_source and item.name not in package_names:
                continue
            if not is_within_root(path, root):
                notes.append((rel, _OUTSIDE_LINK_MESSAGE))
                continue
            if is_source:
                stem = item.name[: -len(SOURCE_SUFFIX)]
                if not is_module_name_segment(stem):
                    notes.append((rel, _INVALID_NAME_MESSAGE))
                elif stem in package_names:
                    notes.append((rel, _SHADOWED_MESSAGE))
                else:
                    entries.append(_ScanEntry(".".join([*parts, stem]), rel, path))
                continue
            if not is_module_name_segment(item.name):
                notes.append((f"{rel}/", _INVALID_NAME_MESSAGE))
                continue
            entries.append(
                _ScanEntry(
                    ".".join([*parts, item.name]), f"{rel}/{PACKAGE_INIT}", path / PACKAGE_INIT
                )
            )
            walk(path, [*parts, item.name], ancestors | {real})

    walk(root, [], frozenset())
    entries.sort(key=lambda e: e.rel)
    return entries, sorted(notes)


def _load_tree(
    collected: _Collector, *, source: SourceInfo, root: Path, package: str, display_prefix: str
) -> None:
    """フォルダ 1 つ (ワークスペース ``blocks/`` または ``dirs`` の 1 件) を読み込む。"""
    errors: list[LoadError] = []
    if has_exact_entry(root, PACKAGE_INIT):
        errors.append(
            LoadError(
                source=source.id,
                path=f"{display_prefix}{PACKAGE_INIT}",
                line=None,
                kind="spec",
                message=(
                    "the top-level __init__.py is not executed; put shared code in a module "
                    "such as common.py and import it with 'from . import common'"
                ),
                severity="info",
            )
        )
    entries, notes = _scan_tree(root)
    for rel, message in notes:
        errors.append(
            LoadError(
                source=source.id,
                path=f"{display_prefix}{rel}",
                line=None,
                kind="spec",
                message=message,
                severity="info",
            )
        )
    # 合成の親パッケージ (flode_dirs → flode_dirs.<name>) を先に作る。実行するコードは無い
    importlib.import_module(package)
    files: list[SourceFile] = []
    for entry in entries:
        display_path = f"{display_prefix}{entry.rel}"
        module_name = f"{package}.{entry.module_suffix}"
        module, error = _import_isolated(
            module_name, source_id=source.id, display_path=display_path, file=entry.file, root=root
        )
        file_errors: list[LoadError] = []
        if error is not None:
            file_errors.append(error)
        elif module is not None:
            infos, block_errors = _collect_blocks(
                module, module_name, source_id=source.id, display_path=display_path
            )
            collected.add_infos(infos)
            file_errors.extend(block_errors)
        errors.extend(file_errors)
        files.append(SourceFile(path=entry.rel, status="error" if file_errors else "ok"))
    collected.errors.extend(errors)
    collected.sources.append(
        SourceInfo(
            id=source.id,
            kind=source.kind,
            label=source.label,
            root=source.root,
            reloadable=source.reloadable,
            files=tuple(files),
            from_cwd=source.from_cwd,
        )
    )


def _load_module_source(
    collected: _Collector, module_name: str, previous: _ModuleResult | None
) -> None:
    """config ``modules`` の 1 件を読み込む (再読み込みでは前回の結果を引き継ぐ)。"""
    source_id = f"{MODULE_SOURCE_PREFIX}{module_name}"
    collected.sources.append(
        SourceInfo(id=source_id, kind="module", label=module_name, root=None, reloadable=False)
    )
    if previous is not None:
        result = previous
    else:
        result = _import_module_source(module_name, source_id)
    collected.module_results[module_name] = result
    collected.add_infos(result.infos)
    collected.errors.extend(result.errors)


def _import_module_source(module_name: str, source_id: str) -> _ModuleResult:
    segments = module_name.split(".")
    if not module_name or not all(is_module_name_segment(s) for s in segments):
        return _ModuleResult(
            infos=(),
            errors=(_config_error(source_id, f"{module_name!r} is not a dotted module name"),),
        )
    top = segments[0]
    if top == "flode" or top in RESERVED_USER_BLOCK_ROOTS:
        return _ModuleResult(
            infos=(),
            errors=(
                _config_error(
                    source_id,
                    f"{module_name!r} cannot be used in blocks modules (flode itself and the "
                    f"reserved names {list(RESERVED_USER_BLOCK_ROOTS)!r} are not allowed)",
                ),
            ),
        )
    module, error = _import_isolated(
        module_name, source_id=source_id, display_path=None, file=None, root=None
    )
    if error is not None:
        return _ModuleResult(infos=(), errors=(error,))
    assert module is not None
    infos, errors = _collect_blocks(module, module_name, source_id=source_id, display_path=None)
    return _ModuleResult(infos=tuple(infos), errors=tuple(errors))


# ---------------------------------------------------------------------------
# import の隔離 (§6-C)
# ---------------------------------------------------------------------------


def _warn_slow_import(label: str) -> None:
    _logger.warning(
        "user blocks: importing %r has taken more than %.0f seconds (it is not interrupted; "
        "check this file for an infinite loop or a blocking call)",
        label,
        IMPORT_WARN_SECONDS,
    )


def _truncate(text: str) -> str:
    if len(text) <= MAX_MESSAGE_CHARS:
        return text
    return text[: MAX_MESSAGE_CHARS - len(_TRUNCATION_MARK)] + _TRUNCATION_MARK


def _reraise_if_interrupt(exc: BaseException) -> None:
    """利用者の中断 (``KeyboardInterrupt``) と ``GeneratorExit`` は隔離せずに通す。"""
    if isinstance(exc, KeyboardInterrupt | GeneratorExit):
        raise exc


def _safe_text(value: object, *, use_repr: bool = False) -> str:
    """ユーザー由来の値を安全に文字列化する (失敗したら ``<unprintable>``、直後に長さを切る)。"""
    try:
        text = repr(value) if use_repr else str(value)
    except BaseException as e:  # noqa: BLE001 - ユーザーコードの __str__ / __repr__ の境界
        _reraise_if_interrupt(e)
        return _UNPRINTABLE
    if not isinstance(text, str):  # pragma: no cover - str() / repr() は str を返す
        return _UNPRINTABLE
    return _truncate(text)


def _exception_text(exc: BaseException) -> str:
    """``"<型名>: <メッセージ>"`` (メッセージの文字列化に失敗しても例外を出さない)。"""
    return _truncate(f"{type(exc).__name__}: {_safe_text(exc)}")


def _same_file(a: str | None, b: Path) -> bool:
    if not a:
        return False
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(str(b))


def _locate_error(
    exc: BaseException, file: Path | None, root: Path | None
) -> tuple[int | None, str]:
    """行番号 (``file`` 内) と、別ファイルで起きた場合の場所の補足を返す。"""
    if file is None:
        return None, ""
    frames = traceback.extract_tb(exc.__traceback__)
    if isinstance(exc, SyntaxError) and _same_file(exc.filename, file):
        return exc.lineno, ""
    in_file = [f for f in frames if _same_file(f.filename, file)]
    line = in_file[-1].lineno if in_file else None
    where: tuple[str, int | None] | None = None
    if isinstance(exc, SyntaxError) and exc.filename:
        where = (exc.filename, exc.lineno)
    elif root is not None:
        root_prefix = os.path.normcase(str(root)) + os.sep
        in_root = [
            f
            for f in frames
            if os.path.normcase(os.path.abspath(f.filename)).startswith(root_prefix)
        ]
        if in_root and not _same_file(in_root[-1].filename, file):
            where = (in_root[-1].filename, in_root[-1].lineno)
    if where is None:
        return line, ""
    filename, where_line = where
    try:
        shown = Path(filename).resolve().relative_to(root).as_posix() if root else filename
    except ValueError:
        shown = Path(filename).name
    return line, f" (in {shown}, line {where_line})"


def _import_isolated(
    module_name: str,
    *,
    source_id: str,
    display_path: str | None,
    file: Path | None,
    root: Path | None,
) -> tuple[ModuleType | None, LoadError | None]:
    """``module_name`` を import する。失敗はそのモジュールだけの読み込みエラーにする。

    ``SystemExit`` は捕捉し、``KeyboardInterrupt`` は捕捉しない (利用者の中断を尊重)。
    import が ``IMPORT_WARN_SECONDS`` を超えたら WARNING を 1 回出す (止めはしない)。
    """
    timer = threading.Timer(
        IMPORT_WARN_SECONDS, _warn_slow_import, args=(display_path or module_name,)
    )
    timer.daemon = True
    timer.start()
    try:
        return importlib.import_module(module_name), None
    except BaseException as e:  # noqa: BLE001 - ユーザーコードの境界: 中断以外はファイル単位に隔離 (§6-C)
        _reraise_if_interrupt(e)
        failure = e
    finally:
        timer.cancel()
    line, where = _safe_locate_error(failure, file, root)
    kind: LoadErrorKind = "import"
    if isinstance(failure, SyntaxError):
        kind = "syntax"
        message = f"SyntaxError: {_safe_text(getattr(failure, 'msg', ''))}"
    elif isinstance(failure, SystemExit):
        code = _safe_text(failure.code, use_repr=True)
        message = f"SystemExit({code}) was raised while importing"
    else:
        message = _exception_text(failure)
    return None, LoadError(
        source=source_id,
        path=display_path,
        line=line,
        kind=kind,
        message=_truncate(message + where),
    )


def _safe_locate_error(
    exc: BaseException, file: Path | None, root: Path | None
) -> tuple[int | None, str]:
    """``_locate_error`` の失敗 (ユーザーが細工した例外属性など) を「位置不明」に落とす。"""
    try:
        line, where = _locate_error(exc, file, root)
    except Exception as e:  # noqa: BLE001 - ユーザー由来の例外オブジェクトの境界
        _logger.debug("user blocks: cannot locate the error in %r: %s", str(file), type(e).__name__)
        return None, ""
    return (line if isinstance(line, int) else None), where


# ---------------------------------------------------------------------------
# ブロックの収集と検証
# ---------------------------------------------------------------------------


@functools.cache
def builtin_class_names() -> frozenset[str]:
    """組み込みブロックのクラス名の集合 (X-1 / R-2 の禁止名)。

    ``flode.blocks`` / ``flode.subsystems`` 配下で定義された ``Block`` サブクラスの名前と、
    信号面の名前引きの分類表 (``flode.core.signals``) のキー、``Block`` 自身。
    """
    names: set[str] = {Block.__name__}
    for package_name in _BUILTIN_BLOCK_PACKAGES:
        package = importlib.import_module(package_name)
        module_names = [package_name] + [
            info.name for info in pkgutil.walk_packages(package.__path__, prefix=f"{package_name}.")
        ]
        for module_name in module_names:
            try:
                module = importlib.import_module(module_name)
            except ImportError as e:
                _logger.debug("user blocks: skipping %r for builtin names: %s", module_name, e)
                continue
            names.update(
                obj.__name__
                for obj in vars(module).values()
                if isinstance(obj, type)
                and issubclass(obj, Block)
                and obj.__module__ == module_name
            )
    for table in (
        signals._CLASSIFICATION,
        signals._CONTROL_PORT_INDEX,
        signals._SHAPE_RULES,
        signals._SHAPE_SOURCES,
        signals._STATE_VIA_FLOAT64,
    ):
        names.update(table)
    return frozenset(names)


def _block_candidates(
    module: ModuleType, module_name: str, *, source_id: str, display_path: str | None
) -> tuple[dict[str, list[type]], list[LoadError]]:
    """パレットに出す候補を ``__name__`` ごとに集める (P1 の除外を適用)。

    属性の検査 (``isinstance`` / ``issubclass`` / ``__module__`` / ``__name__``) はユーザーの
    メタクラスやプロパティを通るので、属性ごとに隔離して読み込みエラーにする。
    """
    seen: dict[int, tuple[str, type]] = {}
    errors: list[LoadError] = []
    for attr_name, obj in list(vars(module).items()):
        if not isinstance(attr_name, str) or attr_name.startswith("_"):
            continue  # P1 (b): 属性名で判定 (@block def _helper → Helper)
        try:
            if not isinstance(obj, type) or obj is Block or not issubclass(obj, Block):
                continue
            if obj.__module__ != module_name:  # P1 (c): import しただけのクラス
                continue
            if vars(obj).get(HIDDEN_ATTRIBUTE):  # P1 (d): そのクラス自身の宣言だけを見る
                continue
            class_name = obj.__name__
            if not isinstance(class_name, str) or not is_module_name_segment(class_name):
                raise _BlockRejectedError(f"the class name {class_name!r} is not an identifier")
        except BaseException as e:  # noqa: BLE001 - ユーザーのメタクラス / プロパティの境界
            _reraise_if_interrupt(e)
            message = _safe_text(e) if isinstance(e, _BlockRejectedError) else _exception_text(e)
            errors.append(
                LoadError(
                    source=source_id,
                    path=display_path,
                    line=None,
                    kind="spec",
                    message=_truncate(f"attribute {attr_name!r}: {message}"),
                )
            )
            continue
        seen[id(obj)] = (class_name, obj)
    by_name: dict[str, list[type]] = {}
    for class_name, cls in seen.values():
        by_name.setdefault(class_name, []).append(cls)
    return dict(sorted(by_name.items())), errors


def _collect_blocks(
    module: ModuleType, module_name: str, *, source_id: str, display_path: str | None
) -> tuple[list[UserBlockInfo], list[LoadError]]:
    """モジュールからブロックを集めて検証する (失敗はブロック単位の読み込みエラー)。

    クラスごとの処理 (検証・インスタンス化・メタデータ・定義行の取得) 全体をユーザーコードの
    境界として扱い、中断以外のどんな例外もそのブロックだけの読み込みエラーにする。
    """
    candidates, errors = _block_candidates(
        module, module_name, source_id=source_id, display_path=display_path
    )
    infos: list[UserBlockInfo] = []
    for class_name, classes in candidates.items():
        # 型名は候補を列挙した時点で確定する (L-1: 後からの __module__ / __name__ 書き換え対策)
        type_path = f"{module_name}.{class_name}"
        try:
            if len(classes) > 1:
                raise _BlockRejectedError(
                    f"{len(classes)} different classes named {class_name!r} are defined in this "
                    f"module; none of them is loaded. Give them different names",
                    kind="conflict",
                )
            infos.append(
                _build_info(
                    classes[0],
                    module_name,
                    class_name=class_name,
                    source_id=source_id,
                    path=display_path,
                )
            )
        except BaseException as e:  # noqa: BLE001 - ユーザーコードの境界: ブロック単位に隔離 (P4)
            _reraise_if_interrupt(e)
            kind: LoadErrorKind = e.kind if isinstance(e, _BlockRejectedError) else "spec"
            message = _safe_text(e) if isinstance(e, BlockSpecError) else _exception_text(e)
            errors.append(
                LoadError(
                    source=source_id,
                    path=display_path,
                    line=_class_line(classes[0]),
                    kind=kind,
                    message=_truncate(f"{class_name}: {message}"),
                    type_path=type_path,
                )
            )
    return infos, errors


def _class_line(cls: type) -> int | None:
    """クラス (``@block`` は元の関数 / class) の定義行。分からなければ ``None``。"""
    try:
        target = (
            vars(cls).get("_flode_user_cls")
            or getattr(vars(cls).get("_flode_func"), "__func__", None)
            or cls
        )
        return int(inspect.getsourcelines(target)[1])
    except BaseException as e:  # noqa: BLE001 - ユーザーのクラス属性 / メタクラスの境界
        _reraise_if_interrupt(e)
        return None


def _json_round_trip(cls: type) -> tuple[list[tuple[str, str]], dict[str, object]]:
    """既定値を JSON 往復させる (P2・§10)。戻り値は ``([(名前, 型ラベル)], {名前: 往復後の値})``。"""
    raw_params = read_params(cls)
    labels: list[tuple[str, str]] = []
    values: dict[str, object] = {}
    for param in raw_params:
        if not param.has_default:
            raise _BlockRejectedError(
                f"parameter {param.name!r} has no default value; every parameter needs one"
            )
        try:
            encoded = json.dumps(to_json_value(param.default))
        except Exception as e:  # noqa: BLE001 - ユーザーの値 (__float__ 等) の境界。自己参照は RecursionError
            raise _BlockRejectedError(
                f"the default value of parameter {param.name!r} "
                f"(type {type(param.default).__name__}) cannot be saved to a model file "
                f"({type(e).__name__})"
            ) from e
        labels.append((param.name, param.type_label))
        values[param.name] = json.loads(encoded)
    return labels, values


def _build_info(
    cls: type, module_name: str, *, class_name: str, source_id: str, path: str | None
) -> UserBlockInfo:
    """1 クラスを検証してメタデータを作る (X-1・P2・§10・§7)。"""
    expected_type_path = f"{module_name}.{class_name}"
    if class_name in builtin_class_names():
        raise _BlockRejectedError(
            f"the class name {class_name!r} is the same as a built-in block. Use another "
            f"class name and set the label with display_name={class_name!r}",
            kind="conflict",
        )
    labels, defaults = _json_round_trip(cls)
    try:
        instance = cls(**defaults)
    except BaseException as e:  # noqa: BLE001 - ユーザーコードの境界 (§10)
        _reraise_if_interrupt(e)
        raise _BlockRejectedError(
            f"the default values are not accepted after a save/load round trip: "
            f"{_exception_text(e)}"
        ) from e
    if not isinstance(instance, Block):
        raise _BlockRejectedError("instantiating the class did not return a Block")
    meta = resolve_metadata(cls, defaults, n_inputs=instance.n_inputs, n_outputs=instance.n_outputs)
    params = tuple(
        UserParamSpec(
            name=name,
            type=label,
            default=defaults[name],
            description=meta.param_descriptions.get(name, ""),
            choices=meta.choices.get(name),
        )
        for name, label in labels
    )
    # L-1: インスタンス化やメタデータ参照の間にクラスの __module__ / __name__ が書き換えられて
    # いたら、組み込み等の型名を名乗れてしまうので拒否する
    if block_type_path(cls) != expected_type_path:
        raise _BlockRejectedError(
            f"the class changed its module or name while being loaded "
            f"(expected {expected_type_path!r}); it is not loaded"
        )
    return UserBlockInfo(
        type_path=expected_type_path,
        class_name=class_name,
        source=source_id,
        module=module_name,
        path=path,
        display_name=meta.display_name,
        display_name_i18n=dict(meta.display_name_i18n),
        description=meta.description,
        description_i18n=dict(meta.description_i18n),
        docstring=meta.docstring,
        category=meta.category,
        params=params,
        n_inputs=int(instance.n_inputs),
        n_outputs=int(instance.n_outputs),
        n_states=int(instance.n_states),
        direct_feedthrough=bool(instance.direct_feedthrough),
        port_shapes_in=tuple(tuple(s) for s in instance.port_shapes_in),
        port_shapes_out=tuple(tuple(s) for s in instance.port_shapes_out),
        input_names=meta.input_names,
        output_names=meta.output_names,
        block_class=cls,
    )


def _log_summary(report: BlockLoadReport) -> None:
    for source in report.sources:
        if source.kind == "module":
            continue
        origin = "workspace (from the current directory)" if source.from_cwd else source.id
        _logger.info(
            "user blocks: read %d file(s) from %s %r: %r",
            len(source.files),
            origin,
            source.root,
            [f.path for f in source.files],
        )
    for error in report.errors:
        log = _logger.warning if error.severity == "error" else _logger.info
        log(
            "user blocks: %s %r line %r [%s]: %r",
            error.source,
            error.path,
            error.line,
            error.kind,
            error.message,
        )
    _logger.info(
        "user blocks: %d block(s) loaded, %d error(s)", len(report.blocks), report.error_count
    )
