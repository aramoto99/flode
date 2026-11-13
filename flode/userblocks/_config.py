"""読み込み元指定の検証と config ``[blocks]`` 節の解釈 (SPEC-0033 P3、ADR-0081 §論点 9)。

型違反 (``dirs`` がテーブルでない、名前が識別子でない等) は ``BlockSourceConfigError`` を送出する
(SPEC-0004 と同じく起動エラー扱い)。パスの不在・モジュールが無いことは読み込み時の読み込みエラーで、
ここでは検査しない。
"""

from __future__ import annotations

import logging
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..exceptions import BlockSourceConfigError
from ._finder import is_module_name_segment
from ._model import LoadRequest

_logger = logging.getLogger("flode.userblocks")

#: config ファイル中の節名とキー (SPEC-0033 P3)。
BLOCKS_SECTION = "blocks"
_KEY_DIRS = "dirs"
_KEY_MODULES = "modules"
_KEY_ALLOW_NON_LOOPBACK = "allow_non_loopback"
_KNOWN_KEYS: frozenset[str] = frozenset({_KEY_DIRS, _KEY_MODULES, _KEY_ALLOW_NON_LOOPBACK})
_HOME_PREFIXES = ("~/", "~\\")


@dataclass(frozen=True)
class BlocksConfig:
    """config ``[blocks]`` 節の内容。

    Attributes:
        dirs: ``(名前, 絶対フォルダ)`` の列 (記述順)。
        modules: モジュール名の列 (記述順)。
        allow_non_loopback: 非 loopback bind でも管理ソースを読む専用許可 (判定は server、U3)。
    """

    dirs: tuple[tuple[str, Path], ...] = ()
    modules: tuple[str, ...] = ()
    allow_non_loopback: bool = False


def _expand_path(raw: str | Path, base_dir: Path) -> Path:
    """``~`` を ``Path.home()`` で展開し、相対パスは ``base_dir`` 基準の絶対パスにする。"""
    text = str(raw)
    if text == "~":
        path = Path.home()
    elif text.startswith(_HOME_PREFIXES):
        path = Path.home() / text[2:]
    else:
        path = Path(text)
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def validate_dir_name(name: Any) -> str:
    """``dirs`` の名前を検証する (Python 識別子・非キーワード・先頭 ``_`` 不可)。

    Raises:
        BlockSourceConfigError: 名前が条件を満たさない。
    """
    if not isinstance(name, str) or not is_module_name_segment(name) or name.startswith("_"):
        raise BlockSourceConfigError(
            f"blocks dirs name {name!r} must be a Python identifier that is not a keyword "
            f"and does not start with '_'"
        )
    return name


def normalize_dirs(dirs: Any, *, base_dir: Path) -> tuple[tuple[str, Path], ...]:
    """``{名前: フォルダ}`` を検証して ``(名前, 絶対フォルダ)`` の列にする。

    Args:
        dirs: ``Mapping[str, str | Path]`` (``None`` は空)。
        base_dir: 相対パスの基準。

    Raises:
        BlockSourceConfigError: ``Mapping`` でない、名前・パスの型違反。
    """
    if dirs is None:
        return ()
    if not isinstance(dirs, Mapping):
        raise BlockSourceConfigError(f"blocks dirs must be a table / mapping, got {dirs!r}")
    out: list[tuple[str, Path]] = []
    for name, raw in dirs.items():
        validate_dir_name(name)
        if not isinstance(raw, str | Path) or not str(raw):
            raise BlockSourceConfigError(f"blocks dirs[{name!r}] must be a non-empty path string")
        out.append((name, _expand_path(raw, base_dir)))
    return tuple(out)


def normalize_modules(modules: Any) -> tuple[str, ...]:
    """モジュール名の列を検証する (値の中身は読み込み時に検査して読み込みエラーにする)。

    Raises:
        BlockSourceConfigError: 文字列の列でない (単独の文字列も拒否)。
    """
    if modules is None:
        return ()
    if isinstance(modules, str) or not isinstance(modules, Sequence):
        raise BlockSourceConfigError(
            f"blocks modules must be a list of module names, got {modules!r}"
        )
    if not all(isinstance(m, str) for m in modules):
        raise BlockSourceConfigError(f"blocks modules must contain only strings, got {modules!r}")
    return tuple(modules)


def parse_blocks_config(section: Any, *, base_dir: Path) -> BlocksConfig:
    """config の ``[blocks]`` 節を解釈する (U3 の server config もこれを使う)。

    Args:
        section: TOML から読んだ ``[blocks]`` 節 (``None`` は空)。
        base_dir: ``dirs`` の相対パスの基準 (通常は config ファイルのフォルダ)。

    Returns:
        解釈結果。未知のキーは WARNING ログを出して無視する (SPEC-0004 と同じ)。

    Raises:
        BlockSourceConfigError: 型違反。
    """
    if section is None:
        return BlocksConfig()
    if not isinstance(section, Mapping):
        raise BlockSourceConfigError(f"[{BLOCKS_SECTION}] must be a table, got {section!r}")
    for key in section:
        if key not in _KNOWN_KEYS:
            _logger.warning("config: unknown key %r in [%s]; ignored", key, BLOCKS_SECTION)
    allow = section.get(_KEY_ALLOW_NON_LOOPBACK, False)
    if not isinstance(allow, bool):
        raise BlockSourceConfigError(
            f"[{BLOCKS_SECTION}] {_KEY_ALLOW_NON_LOOPBACK} must be true or false, got {allow!r}"
        )
    return BlocksConfig(
        dirs=normalize_dirs(section.get(_KEY_DIRS), base_dir=base_dir),
        modules=normalize_modules(section.get(_KEY_MODULES)),
        allow_non_loopback=allow,
    )


def default_config_path() -> Path:
    """``~/.flode/config.toml`` (server の ``default_user_config_path`` と同じ場所)。"""
    return Path.home() / ".flode" / "config.toml"


def read_blocks_config(path: Path | None = None) -> BlocksConfig:
    """config ファイルの ``[blocks]`` 節を読む (``flode.load_blocks(use_config=True)`` 用)。

    Args:
        path: config ファイル (``None`` なら ``~/.flode/config.toml``)。

    Returns:
        解釈結果。ファイルが無ければ空。

    Raises:
        BlockSourceConfigError: ファイルが読めない・TOML として不正・``[blocks]`` の型違反。
    """
    config_path = path if path is not None else default_config_path()
    if not config_path.is_file():
        return BlocksConfig()
    try:
        with config_path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise BlockSourceConfigError(f"cannot read config {str(config_path)!r}: {e}") from e
    return parse_blocks_config(data.get(BLOCKS_SECTION), base_dir=config_path.parent)


def build_request(
    workspace: str | Path | None,
    *,
    dirs: Any,
    modules: Any,
    config: BlocksConfig | None = None,
) -> LoadRequest:
    """``flode.load_blocks`` の引数 (と config) から ``LoadRequest`` を作る。

    ``dirs`` の相対パスは現在の作業フォルダ基準。config を足す場合は引数の後ろに続け、
    同じ名前の ``dirs`` は型違反として拒否する。

    Raises:
        BlockSourceConfigError: 引数の型違反、または ``dirs`` の名前の重複。
    """
    if workspace is not None and not isinstance(workspace, str | Path):
        raise BlockSourceConfigError(f"workspace must be a path, got {workspace!r}")
    dir_items = list(normalize_dirs(dirs, base_dir=Path.cwd()))
    module_items = list(normalize_modules(modules))
    if config is not None:
        dir_items += config.dirs
        module_items += config.modules
    names = [name for name, _ in dir_items]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise BlockSourceConfigError(f"blocks dirs names are duplicated: {duplicates!r}")
    return LoadRequest(
        workspace=Path(workspace).resolve() if workspace is not None else None,
        dirs=tuple(dir_items),
        modules=tuple(module_items),
    )
