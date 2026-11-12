"""``.flwlib.json`` の registry build (ADR-0029 / ADR-0080 §A1-5)。

組み込み ``std.flwlib.json``・ユーザーライブラリのディレクトリ・``Settings.library_paths``
を読み込んで :class:`LibraryRegistry` を組み立てる。registry は
:class:`flode.server.library_store.LibraryStore` が保持し、REST `/api/v1/libraries` 系から
参照される。registry は **決して in-place で変更しない** (書き込み後は新しい registry を
組み立てて参照を差し替える、ADR-0080 §A5)。
"""

from __future__ import annotations

import importlib.resources
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..exceptions import LibraryFileError
from ..libraries import Library, load_library

_logger = logging.getLogger("flode.library_registry")

#: ライブラリファイルの探索パターン。
LIBRARY_FILE_GLOB = "*.flwlib.json"

#: GUI からの登録先ライブラリの名前 (予約名)。既定パス以外のファイルは宣言できない。
USER_LIBRARY_NAME = "user"
#: 組み込みライブラリの名前 (予約名)。
BUILTIN_LIBRARY_NAME = "std"
#: 取り込みで宣言できないライブラリ名。
RESERVED_LIBRARY_NAMES: frozenset[str] = frozenset({USER_LIBRARY_NAME, BUILTIN_LIBRARY_NAME})

#: ユーザーライブラリのファイル名 (``<user_library_dir>/user.flwlib.json``)。
USER_LIBRARY_FILENAME = "user.flwlib.json"
#: 取り込みライブラリの置き場 (``<user_library_dir>/imported/``)。
IMPORTED_DIRNAME = "imported"

#: ライブラリの出所 (REST の ``origin``、ADR-0080 §A1-6)。
ORIGIN_BUILTIN = "builtin"
ORIGIN_USER = "user"
ORIGIN_IMPORTED = "imported"
ORIGIN_PATH = "path"

#: ライブラリが持てないエントリ id。REST の ``GET /libraries/{name}/export`` /
#: ``/libraries/user/entries`` と同じ URL になる (``GET /libraries/{lib}/{entry}``)。
#: この id を持つファイルは読み込まず、登録でも生成しない。
RESERVED_ENTRY_IDS: frozenset[str] = frozenset({"export", "entries"})

# 1 ファイルの読み込みで捕まえる失敗 (``load_errors`` に落として続行する)。
_LOAD_FAILURES: tuple[type[BaseException], ...] = (
    LibraryFileError,
    ValueError,
    RecursionError,
    MemoryError,
)

# registry 内の並び順 (読み込み順と同じ: std → user → imported → その他)。
_ORIGIN_ORDER: dict[str, int] = {
    ORIGIN_BUILTIN: 0,
    ORIGIN_USER: 1,
    ORIGIN_IMPORTED: 2,
    ORIGIN_PATH: 3,
}


@dataclass
class LibraryLoadError:
    """Registry build 時に load に失敗した library の記録 (ADR-0029)。"""

    path: str
    message: str


@dataclass
class LibraryRegistry:
    """Server が保持する library registry。

    Attributes:
        libraries: 名前 → :class:`Library` (読み込み順)。同名は先勝ち。
        load_errors: 個別ファイルの load エラー。1 ファイルが壊れていても他の library を
            落とさない (= 部分稼働ポリシー、ADR-0029 §LOC-A)。
        origins: 名前 → 出所 (``"builtin"`` / ``"user"`` / ``"imported"`` / ``"path"``)。
        user_library_problem: ユーザーライブラリのファイルが読めないときのエラーコード
            (``"user_library_corrupt"`` / ``"library_schema_too_new"``)。健全、または
            ファイルがまだ無ければ空文字。
    """

    libraries: dict[str, Library] = field(default_factory=dict)
    load_errors: list[LibraryLoadError] = field(default_factory=list)
    origins: dict[str, str] = field(default_factory=dict)
    user_library_problem: str = ""

    def origin_of(self, name: str) -> str:
        """ライブラリ ``name`` の出所を返す (不明なら ``"path"``)。"""
        return self.origins.get(name, ORIGIN_PATH)


def sort_by_origin(libraries: dict[str, Library], origins: dict[str, str]) -> dict[str, Library]:
    """``libraries`` を出所の順 (std → user → imported → その他) に安定ソートして返す。

    書き込み後に registry を組み直すとき、起動時の読み込み順と同じ並びを保つために使う。
    """
    return dict(
        sorted(
            libraries.items(),
            key=lambda item: _ORIGIN_ORDER[origins.get(item[0], ORIGIN_PATH)],
        )
    )


def _expand_paths(paths: Iterable[Path]) -> list[Path]:
    """ファイル / ディレクトリ path を ``*.flwlib.json`` ファイル一覧に展開する。"""
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            # 再帰的に探索 (= ディレクトリ階層でグルーピングしているプロジェクトを許容)
            out.extend(sorted(p.rglob(LIBRARY_FILE_GLOB)))
        else:
            # ファイル直接指定 (拡張子チェックは load 時にバリデート)
            out.append(p)
    return out


def _builtin_std_path() -> Path | None:
    """組み込み ``flode/libraries/std.flwlib.json`` の絶対 path を返す (なければ ``None``)。

    ``importlib.resources`` で取得する (= editable install / wheel install の両対応)。
    """
    try:
        ref = importlib.resources.files("flode.libraries").joinpath("std.flwlib.json")
    except (ModuleNotFoundError, FileNotFoundError):
        return None
    if not ref.is_file():
        return None
    # PackagePath を Path に変換 (zip wheel の場合は as_file context が必要だが、
    # flode は pure python のため editable / regular install のいずれでも file system 上に存在)
    try:
        return Path(str(ref))
    except (TypeError, ValueError):
        return None


def _resolved(path: Path) -> Path:
    """重複除去用に ``path`` を解決する (解決できなければそのまま返す)。"""
    try:
        return path.resolve()
    except (OSError, RuntimeError):
        return path


def _user_directory_files(user_library_dir: Path) -> list[tuple[Path, str]]:
    """ユーザーライブラリのディレクトリ配下の ``(ファイル, 出所)`` を読み込み順で返す。

    順序は ``user.flwlib.json`` → ``imported/**`` → その他 (ADR-0080 §A1-5)。出所
    ``"imported"`` は ``imported/`` の**直下**に実体があるファイルだけに付ける
    (サーバが生成するのは直下のファイルのみ。サブディレクトリや外を指す symlink は
    手で置かれたものなので ``"path"`` 扱い = GUI から削除できない)。
    """
    if not user_library_dir.is_dir():
        return []
    files: list[tuple[Path, str]] = []
    user_file = user_library_dir / USER_LIBRARY_FILENAME
    if user_file.is_file():
        files.append((user_file, ORIGIN_USER))
    imported_dir = user_library_dir / IMPORTED_DIRNAME
    if imported_dir.is_dir():
        for f in sorted(imported_dir.rglob(LIBRARY_FILE_GLOB)):
            direct = _resolved(f).parent == imported_dir
            files.append((f, ORIGIN_IMPORTED if direct else ORIGIN_PATH))
    # user.flwlib.json と imported/** はここにも現れるが、後段の重複除去で落ちる
    files.extend((f, ORIGIN_PATH) for f in sorted(user_library_dir.rglob(LIBRARY_FILE_GLOB)))
    return files


def build_library_registry(
    library_paths: Iterable[Path] = (),
    *,
    bundle_builtin: bool = True,
    user_library_dir: Path | None = None,
) -> LibraryRegistry:
    """``.flwlib.json`` 群を読み込んで :class:`LibraryRegistry` を返す。

    読み込み順は 組み込み ``std`` → ``<user_library_dir>/user.flwlib.json`` →
    ``<user_library_dir>/imported/**`` → ``<user_library_dir>`` のその他 →
    ``library_paths`` (ADR-0080 §A1-5)。同じファイル (解決後の絶対 path が同じ) は
    1 回だけ読む。

    Args:
        library_paths: ロード対象。ファイル / ディレクトリどちらも受け付ける
            (ディレクトリは再帰的に ``*.flwlib.json`` を検索)。
        bundle_builtin: 組み込み ``std`` library を先頭に追加するか (default True)。
        user_library_dir: ユーザーライブラリのディレクトリ (解決済みの絶対 path)。
            ``None`` ならユーザーライブラリ無効で、このディレクトリには触れない。

    Returns:
        :class:`LibraryRegistry`。エラー耐性ポリシー: 個別 file の load 失敗は
        ``load_errors`` に記録し、それ以外は読み込みを続行する。

    .. note::

        * library 名の衝突は警告ログ + ``load_errors`` に記録した上で **先勝ち** で解決する。
        * 予約エントリ id (:data:`RESERVED_ENTRY_IDS`) を持つファイルは読み込まず、
          ``load_errors`` に記録する (REST の ``/{name}/export`` と URL が重なるため)。
        * ``uid`` は registry 内で一意: 先に読んだライブラリと同じ ``uid`` を持つ後発は、
          ``uid`` を持たないライブラリとして読み込み、``load_errors`` に記録する
          (ライブラリ自体は使える。由来の突合で先発に化けないようにする)。
        * 名前 ``user`` は予約名: 既定パス (``<user_library_dir>/user.flwlib.json``) 以外の
          ファイルが宣言したら拒否する (ユーザーライブラリが無効・未作成でも予約する)。
          既定パスのファイルが ``user`` 以外を宣言していたら壊れたファイルとして拒否する。
    """
    registry = LibraryRegistry()
    files: list[tuple[Path, str]] = []
    if bundle_builtin:
        builtin = _builtin_std_path()
        if builtin is not None:
            files.append((builtin, ORIGIN_BUILTIN))
        else:
            _logger.warning("library_registry: built-in std.flwlib.json not found in package data")
    if user_library_dir is not None:
        files.extend(_user_directory_files(user_library_dir))
    files.extend((f, ORIGIN_PATH) for f in _expand_paths(library_paths))

    seen: set[Path] = set()
    uid_owners: dict[str, str] = {}
    for f, origin in files:
        key = _resolved(f)
        if key in seen:
            continue
        seen.add(key)
        try:
            lib = load_library(f)
        except _LOAD_FAILURES as e:
            # ``load_library`` は読めないファイルを ``LibraryFileError`` に包む。それ以外は
            # 包み損ねた失敗への最後の砦で、1 ファイルが registry 全体 (= サーバ起動) を
            # 止めないようにする
            message = str(e) if isinstance(e, LibraryFileError) else f"{type(e).__name__}: {e}"
            # ファイル由来の文字列は %r で出す (改行でログ行を偽造させない)
            _logger.warning("library_registry: skipping %r (load failed: %r)", str(f), message)
            registry.load_errors.append(LibraryLoadError(path=str(f), message=message))
            continue
        rejection = _reserved_name_rejection(lib.name, origin) or reserved_entry_id_rejection(lib)
        if rejection is None and lib.name in registry.libraries:
            rejection = (
                f"duplicate library name {lib.name!r}; first definition kept "
                f"({registry.libraries[lib.name].source_path}), "
                f"new one rejected ({f})"
            )
        if rejection is not None:
            _logger.warning("library_registry: %r (%r)", rejection, str(f))
            registry.load_errors.append(LibraryLoadError(path=str(f), message=rejection))
            continue
        if lib.uid is not None:
            owner = uid_owners.setdefault(lib.uid, lib.name)
            if owner != lib.name:
                # uid は由来の突合キー。後発が先発と同じ uid を名乗ると、先発由来の
                # ブロックの差し替え先に化けられるので、後発を uid 無しとして読み込む
                note = (
                    f"library {lib.name!r} declares the same uid as {owner!r}, which was "
                    f"loaded first; the uid of {lib.name!r} is ignored"
                )
                _logger.warning("library_registry: %r (%r)", note, str(f))
                registry.load_errors.append(LibraryLoadError(path=str(f), message=note))
                lib = replace(lib, uid=None)
        registry.libraries[lib.name] = lib
        registry.origins[lib.name] = origin
    return registry


def reserved_entry_id_rejection(library: Library) -> str | None:
    """ライブラリが予約エントリ id を持っていれば拒否理由を返す。

    ``GET /libraries/{name}/export`` (ライブラリのダウンロード) と
    ``GET /libraries/{lib}/{entry}`` (エントリ詳細) は、エントリ id が ``export`` だと
    同じ URL になる。どちらを返すかが内容次第で変わらないよう、予約 id を持つファイルは
    出所を問わず読み込まない (組み込み・ユーザー・取り込み・手置きのすべて)。
    """
    reserved = sorted(e.id for e in library.entries if e.id in RESERVED_ENTRY_IDS)
    if not reserved:
        return None
    return (
        f"library {library.name!r} has entry id(s) reserved by the REST API: "
        f"{', '.join(reserved)}; rename the entries to load this library"
    )


def _reserved_name_rejection(name: str, origin: str) -> str | None:
    """予約名 ``user`` の規則に反していれば拒否理由を返す (ADR-0080 §A1-5)。"""
    if origin == ORIGIN_USER and name != USER_LIBRARY_NAME:
        return (
            f"the user library file must declare name {USER_LIBRARY_NAME!r}, "
            f"got {name!r}; the file is treated as corrupt"
        )
    if origin != ORIGIN_USER and name == USER_LIBRARY_NAME:
        return (
            f"library name {USER_LIBRARY_NAME!r} is reserved for "
            f"<user_library_dir>/{USER_LIBRARY_FILENAME}"
        )
    return None
