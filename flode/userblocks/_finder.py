"""予約ルート (``flode_ws`` / ``flode_dirs``) 専用の meta path finder とソース専用 loader。

ADR-0081 §1-A (A3): ``sys.meta_path`` の先頭に置き、予約ルート配下の名前**だけ**を引き受ける。
それ以外の名前には ``None`` を返して一切関与しない。

- ``flode_ws`` = ワークスペースの ``blocks/``、``flode_dirs.<name>`` = config ``dirs`` の各フォルダ。
  これらのルートパッケージは合成で、フォルダ直下の ``__init__.py`` は実行しない (§1-C)。
- サブパッケージは ``__init__.py`` を持つフォルダだけ (namespace package は解決しない、
  ADR-0080 Am.8 と一致)。見つからない名前は ``ModuleNotFoundError`` にして、後段の
  標準 finder に namespace package や bytecode を拾わせない。
- loader は bytecode を読み書きせず、常にソースから compile する (``__pycache__`` を作らない、
  同じ秒内・同じサイズの書き換えでも最新のソースで動く、PEP 552 の timestamp 方式を避ける)。
- 名前の大文字小文字はディレクトリ一覧と完全一致で照合する (大文字小文字を区別しない
  ファイルシステムでも型名が 1 通りに決まる)。
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import importlib.util
import keyword
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import CodeType, ModuleType
from typing import Any

from ..core.persistence import RESERVED_USER_BLOCK_ROOTS

WORKSPACE_ROOT_NAME, DIRS_ROOT_NAME = RESERVED_USER_BLOCK_ROOTS
PACKAGE_INIT = "__init__.py"
SOURCE_SUFFIX = ".py"
_INIT_STEM = "__init__"


class SourceOnlyLoader(importlib.machinery.SourceFileLoader):
    """bytecode キャッシュを使わない ``SourceFileLoader`` (ADR-0081 §1-A)。

    ``get_code`` は常にソースを読んで compile する。``set_data`` (pyc の書き込み) は
    呼ばれない。``get_source`` / ``inspect.getsource`` / traceback の行表示は標準どおり。
    """

    def get_code(self, fullname: str) -> CodeType:
        """``fullname`` のソースを読み、bytecode を経由せずに compile する。

        Args:
            fullname: モジュールの完全名。

        Returns:
            compile 済みの code object。
        """
        path = self.get_filename(fullname)
        return self.source_to_code(self.get_data(path), path)


class SyntheticPackageLoader(importlib.abc.Loader):
    """予約ルートの合成パッケージ用 loader (中身を実行しない)。"""

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType | None:
        """既定のモジュール生成に任せる。"""
        return None

    def exec_module(self, module: ModuleType) -> None:
        """何も実行しない (フォルダ直下の ``__init__.py`` は実行しない、§1-C)。"""


@dataclass(frozen=True)
class FinderRoots:
    """finder が引き受けるルートの設定 (差し替えは新しいオブジェクトの代入で行う)。

    Attributes:
        workspace: ``flode_ws`` に対応するフォルダ (``None`` = ``flode_ws`` を引き受けない)。
        dirs: ``flode_dirs.<name>`` に対応するフォルダ。
        dirs_enabled: ``flode_dirs`` を引き受けるか (予約名の衝突時は ``False``)。
    """

    workspace: Path | None = None
    dirs: Mapping[str, Path] = field(default_factory=dict)
    dirs_enabled: bool = False


def has_exact_entry(directory: Path, entry: str) -> bool:
    """``directory`` の直下に名前が ``entry`` と完全一致するエントリがあるか。"""
    try:
        return entry in os.listdir(directory)
    except OSError:
        return False


def is_module_name_segment(name: str) -> bool:
    """モジュール名の 1 区切りとして使える名前か (識別子かつ非キーワード)。"""
    return name.isidentifier() and not keyword.iskeyword(name)


def is_within_root(path: Path, root: Path) -> bool:
    """``path`` のリンクを辿った実体が ``root`` (の実体) の配下にあるか (symlink / junction 対策)。"""
    real_root = os.path.normcase(os.path.realpath(root))
    real = os.path.normcase(os.path.realpath(path))
    return real == real_root or real.startswith(real_root.rstrip(os.sep) + os.sep)


def _not_found(fullname: str) -> ModuleNotFoundError:
    return ModuleNotFoundError(f"No module named {fullname!r}", name=fullname)


def _synthetic_spec(
    fullname: str, locations: Sequence[Path], origin: str
) -> importlib.machinery.ModuleSpec:
    spec = importlib.machinery.ModuleSpec(
        fullname, SyntheticPackageLoader(), origin=origin, is_package=True
    )
    spec.submodule_search_locations = [str(p) for p in locations]
    return spec


def _file_spec(fullname: str, root: Path, parts: Sequence[str]) -> importlib.machinery.ModuleSpec:
    """``root`` からの相対モジュールパス ``parts`` の spec を作る (無ければ例外)。"""
    base = root
    for part in parts[:-1]:
        if not is_module_name_segment(part) or not has_exact_entry(base, part):
            raise _not_found(fullname)
        base = base / part
        if not has_exact_entry(base, PACKAGE_INIT):
            raise _not_found(fullname)
    last = parts[-1]
    if not is_module_name_segment(last) or last == _INIT_STEM:
        raise _not_found(fullname)
    package_dir = base / last
    if (
        has_exact_entry(base, last)
        and package_dir.is_dir()
        and has_exact_entry(package_dir, PACKAGE_INIT)
        and (package_dir / PACKAGE_INIT).is_file()
    ):
        init_path = package_dir / PACKAGE_INIT
        spec = importlib.util.spec_from_file_location(
            fullname,
            init_path,
            loader=SourceOnlyLoader(fullname, str(init_path)),
            submodule_search_locations=[str(package_dir)],
        )
    else:
        file_path = base / f"{last}{SOURCE_SUFFIX}"
        if not (has_exact_entry(base, file_path.name) and file_path.is_file()):
            raise _not_found(fullname)
        spec = importlib.util.spec_from_file_location(
            fullname, file_path, loader=SourceOnlyLoader(fullname, str(file_path))
        )
    if spec is None:  # pragma: no cover - loader を渡しているので起きない
        raise _not_found(fullname)
    # ルートの外を指すリンク (symlink / junction) は辿らない
    if spec.origin is None or not is_within_root(Path(spec.origin), root):
        raise _not_found(fullname)
    return spec


class ReservedRootFinder(importlib.abc.MetaPathFinder):
    """予約ルート配下の名前だけを解決する meta path finder (ADR-0081 §1-A)。"""

    def __init__(self) -> None:
        self.roots = FinderRoots()

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None = None,
        target: ModuleType | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        """予約ルート配下なら spec を返し、それ以外は ``None`` (関与しない)。

        Args:
            fullname: import しようとしているモジュールの完全名。
            path: 親パッケージの ``__path__`` (使わない。ルートの設定から決める)。
            target: reload 対象 (使わない)。

        Returns:
            予約ルート配下の spec。予約ルート外、または引き受けていないルートなら ``None``。

        Raises:
            ModuleNotFoundError: 引き受けているルートの配下で該当するモジュールが無い。
        """
        roots = self.roots  # 1 度だけ参照を取る (差し替えと並行しても一貫させる)
        top, _, rest = fullname.partition(".")
        if top == WORKSPACE_ROOT_NAME and roots.workspace is not None:
            if not rest:
                return _synthetic_spec(fullname, [roots.workspace], str(roots.workspace))
            return _file_spec(fullname, roots.workspace, rest.split("."))
        if top == DIRS_ROOT_NAME and roots.dirs_enabled:
            if not rest:
                return _synthetic_spec(fullname, [], DIRS_ROOT_NAME)
            name, _, sub = rest.partition(".")
            directory = roots.dirs.get(name)
            if directory is None:
                raise _not_found(fullname)
            if not sub:
                return _synthetic_spec(fullname, [directory], str(directory))
            return _file_spec(fullname, directory, sub.split("."))
        return None

    def invalidate_caches(self) -> None:
        """キャッシュを持たないので何もしない (``importlib.invalidate_caches`` から呼ばれる)。"""


def is_our_module(module: Any) -> bool:
    """``module`` がこの finder の loader で作られたものか。"""
    spec = getattr(module, "__spec__", None)
    loader = getattr(spec, "loader", None)
    return isinstance(loader, SourceOnlyLoader | SyntheticPackageLoader)
