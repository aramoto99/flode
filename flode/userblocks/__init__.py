"""Python で書いたブロックの読み込み (ADR-0081 / SPEC-0033)。

ワークスペースの ``blocks/`` (仮想パッケージ ``flode_ws``)、名前付きフォルダ ``dirs``
(``flode_dirs.<名前>``)、インストール済みモジュール ``modules`` から ``Block`` サブクラスを読み込み、
``flode.core.persistence`` の管理型表に登録する。以後 ``Simulator.load`` / ``from_dict`` は
型名 (``flode_ws.filters.MovingAverage`` 等) をこの表から解決する。

Python API は ``load_blocks`` / ``unload_blocks``。server は ``load_sources`` (``LoadRequest`` で
cwd 由来のワークスペースかどうかを伝える) / ``reload_sources`` / ``current_report`` を使う。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from ..exceptions import BlockLoadError
from ._config import BlocksConfig, build_request, parse_blocks_config, read_blocks_config
from ._loader import (
    current_report,
    load_sources,
    reload_sources,
    unload_sources,
)
from ._model import (
    BlockLoadReport,
    LoadError,
    LoadRequest,
    SourceFile,
    SourceInfo,
    UserBlockInfo,
    UserParamSpec,
)

#: ``BlockLoadError`` のメッセージに並べるエラーの最大件数。
_ERRORS_IN_MESSAGE = 3


def load_blocks(
    workspace: str | Path | None = None,
    *,
    dirs: Mapping[str, str | Path] | None = None,
    modules: Sequence[str] | None = None,
    use_config: bool = False,
    strict: bool = True,
) -> BlockLoadReport:
    """ユーザーブロックを読み込み、``Simulator.load`` で型名を解決できるようにする。

    呼ぶたびに管理ソース全体を置き換える (別ワークスペースへの切り替えは 2 回目の呼び出し)。
    GUI と同じ規則 (走査・除外・既定値の検査・型名) で読む。信頼境界の判定は無い。

    Args:
        workspace: ワークスペースのフォルダ。``<workspace>/blocks/`` を ``flode_ws`` として読む。
            ``None`` ならワークスペースは読まない (カレントフォルダを暗黙には読まない)。
        dirs: ``{名前: フォルダ}``。``flode_dirs.<名前>`` として読む。相対パスはカレントフォルダ基準。
        modules: インストール済みモジュール名 (そのモジュール自身で定義されたブロックだけ読む)。
        use_config: ``True`` なら ``~/.flode/config.toml`` の ``[blocks]`` の ``dirs`` /
            ``modules`` を引数の後ろに足す。
        strict: ``True`` なら全部読み終えた後、エラーが 1 件でもあれば ``BlockLoadError``。
            読み込めたブロックは登録されたまま残る。

    Returns:
        読み込み結果。

    Raises:
        BlockLoadError: ``strict=True`` で読み込みエラーがあった (``.report`` に結果)。
        BlockSourceConfigError: 引数や config の型違反 (``dirs`` の名前が識別子でない等)。
        BlockReloadInProgressError: 別の読み込みが進行中。
    """
    config = read_blocks_config() if use_config else None
    request = build_request(workspace, dirs=dirs, modules=modules, config=config)
    report = load_sources(request)
    if strict and report.error_count:
        errors = [e for e in report.errors if e.severity == "error"]
        summary = "; ".join(
            f"{e.path or e.source}"
            + (f" line {e.line}" if e.line is not None else "")
            + f": {e.message}"
            for e in errors[:_ERRORS_IN_MESSAGE]
        )
        more = len(errors) - _ERRORS_IN_MESSAGE
        suffix = f" (and {more} more)" if more > 0 else ""
        raise BlockLoadError(
            f"{len(errors)} error(s) while loading user blocks: {summary}{suffix}",
            report=report,
        )
    return report


def unload_blocks() -> None:
    """読み込んだユーザーブロックをすべて外す (管理型表・``sys.modules``・import フック)。

    Raises:
        BlockReloadInProgressError: 別の読み込みが進行中。
    """
    unload_sources()


__all__ = [
    "BlockLoadReport",
    "BlocksConfig",
    "LoadError",
    "LoadRequest",
    "SourceFile",
    "SourceInfo",
    "UserBlockInfo",
    "UserParamSpec",
    "current_report",
    "load_blocks",
    "load_sources",
    "parse_blocks_config",
    "read_blocks_config",
    "reload_sources",
    "unload_blocks",
]
