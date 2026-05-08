"""``.flwlib.json`` の registry build (ADR-0029)。

サーバ起動時に ``Settings.library_paths`` + 組み込み ``std.flwlib.json`` を読み込み、
``app.state.library_registry`` にキャッシュする。:func:`build_library_registry` の出力は
:class:`LibraryRegistry` で、REST `/api/v1/libraries` 系から参照される。
"""

from __future__ import annotations

import importlib.resources
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from ..exceptions import LibraryFileError
from ..libraries import Library, load_library

_logger = logging.getLogger("pyflw.library_registry")


@dataclass
class LibraryLoadError:
    """Registry build 時に load に失敗した library の記録 (ADR-0029)。"""

    path: str
    message: str


@dataclass
class LibraryRegistry:
    """Server lifespan に保持する library registry。

    Attributes:
        libraries: 名前 → :class:`Library` (= load 順を保ちつつ衝突は ``LibraryFileError``
            に昇格)。
        load_errors: 個別ファイルの load エラー。1 ファイルが壊れていても他の library を
            落とさない (= 部分稼働ポリシー、ADR-0029 §LOC-A)。
    """

    libraries: dict[str, Library] = field(default_factory=dict)
    load_errors: list[LibraryLoadError] = field(default_factory=list)


def _expand_paths(paths: Iterable[Path]) -> list[Path]:
    """ファイル / ディレクトリ path を ``*.flwlib.json`` ファイル一覧に展開する。"""
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            # 再帰的に探索 (= ディレクトリ階層でグルーピングしているプロジェクトを許容)
            out.extend(sorted(p.rglob("*.flwlib.json")))
        else:
            # ファイル直接指定 (拡張子チェックは load 時にバリデート)
            out.append(p)
    return out


def _builtin_std_path() -> Path | None:
    """組み込み ``pyflw/libraries/std.flwlib.json`` の絶対 path を返す (なければ ``None``)。

    ``importlib.resources`` で取得する (= editable install / wheel install の両対応)。
    """
    try:
        ref = importlib.resources.files("pyflw.libraries").joinpath("std.flwlib.json")
    except (ModuleNotFoundError, FileNotFoundError):
        return None
    if not ref.is_file():
        return None
    # PackagePath を Path に変換 (zip wheel の場合は as_file context が必要だが、
    # pyflw は pure python のため editable / regular install のいずれでも file system 上に存在)
    try:
        return Path(str(ref))
    except (TypeError, ValueError):
        return None


def build_library_registry(
    library_paths: Iterable[Path] = (),
    *,
    bundle_builtin: bool = True,
) -> LibraryRegistry:
    """``.flwlib.json`` 群を読み込んで :class:`LibraryRegistry` を返す。

    Args:
        library_paths: ロード対象。ファイル / ディレクトリどちらも受け付ける
            (ディレクトリは再帰的に ``*.flwlib.json`` を検索)。
        bundle_builtin: 組み込み ``std`` library を先頭に追加するか (default True)。

    Returns:
        :class:`LibraryRegistry`。エラー耐性ポリシー: 個別 file の load 失敗は
        ``load_errors`` に記録し、それ以外は読み込みを続行する。

    .. note::

        library 名の衝突 (= 同名 ``name`` を持つ ``.flwlib.json`` が複数) は警告ログ
        + load_errors に記録した上で、**先勝ち** で解決する (= 後発を捨てる)。
    """
    registry = LibraryRegistry()
    files: list[Path] = []
    if bundle_builtin:
        builtin = _builtin_std_path()
        if builtin is not None:
            files.append(builtin)
        else:
            _logger.warning(
                "library_registry: built-in std.flwlib.json not found in package data"
            )
    files.extend(_expand_paths(library_paths))

    for f in files:
        try:
            lib = load_library(f)
        except LibraryFileError as e:
            _logger.warning(
                "library_registry: skipping %s (load failed: %s)", f, e
            )
            registry.load_errors.append(
                LibraryLoadError(path=str(f), message=str(e))
            )
            continue
        if lib.name in registry.libraries:
            msg = (
                f"duplicate library name {lib.name!r}; first definition kept "
                f"({registry.libraries[lib.name].source_path}), "
                f"new one rejected ({f})"
            )
            _logger.warning("library_registry: %s", msg)
            registry.load_errors.append(LibraryLoadError(path=str(f), message=msg))
            continue
        registry.libraries[lib.name] = lib
    return registry
