"""``flode`` コマンドのエントリポイント (ADR-0013 §(2) / ADR-0041 §3 / SPEC-0004)。

``pip install flode[gui]`` 後、コマンドラインから::

    flode

だけで FastAPI サーバが起動しブラウザで UI が開く (``--workspace`` / ``--port``
等で上書き可)。``flode`` は互換 alias として同じエントリポイントを指す
(SPEC-0021)。``flode[gui]`` extras が無い場合は
``flode.server`` の import 時点で ``FlodeError`` が出るので、ユーザーが extras を
インストールするよう誘導される。

SPEC-0004 (v3.17.0~): ``~/.flode/config.toml`` をサポート。優先順位は
``CLI 引数 > 設定ファイル > default``。設定ファイル不在時は warning なしで default
起動 (リファレンス Web IDE 準拠)。

v0.21.0 (ADR-0041 §論点 4-A): legacy ``--model-dir`` を削除。旧 ``models/``
ディレクトリから workspace への移行は ``flode --migrate-models-to=DIR``
で実行する (= サーバ起動せず migrate のみ)。

SPEC-0021 (v0.41.0~): 一発起動の UX。起動後にデフォルトブラウザで
UI を開き (``--no-browser`` / ``[server] open_browser`` で無効化)、要求ポートが
使用中なら +1 ずつ自動フォールバックする (``[server] port_retries``、``0`` で無効)。
"""

from __future__ import annotations

import argparse
import errno
import json
import logging
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

from ..exceptions import FlodeError
from .app import create_app
from .config import (
    SettingsResolver,
    default_user_config_path,
    generate_config_template,
    load_config_file,
    resolve_config_path,
)
from .migrations import migrate_models_to
from .settings import Settings

_logger = logging.getLogger("flode.server.cli")

# SPEC-0021 / ADR-0069 論点 2-b: ブラウザ自動オープンは listen 確立を TCP 接続で
# 確認してから行う (固定 sleep より堅牢)。0.1s x 100 回 = 最大約 10 秒待って
# best-effort で開く。
_BROWSER_POLL_INTERVAL_S = 0.1
_BROWSER_POLL_MAX_TRIES = 100

# Windows では使用中ポートへの bind が WSAEACCES (winerror 10013) になるケースがある
# (SO_EXCLUSIVEADDRUSE 済みポート・Hyper-V 等の予約ポート範囲)。リファレンス Web IDE と同様に
# 「使用中」扱いで次ポートへフォールバックする。真の権限エラーと区別できない既知の
# トレードオフだが、Windows は Unix と違い特権ポート (<1024) の bind 制限がなく、
# WSAEACCES の実質的な発生源は予約範囲のため「使用中」扱いが妥当 (code-reviewer SHOULD)。
_WINERROR_WSAEACCES = 10013

# TCP ポート番号の上限。port_retries の誤設定 (極端に大きい値) で 65535 超のポートを
# 探索しないよう find_free_port で範囲を打ち切る (code-reviewer SHOULD)。
_MAX_TCP_PORT = 65535


# ---------------------------------------------------------------------------
# ポート自動フォールバック (SPEC-0021 §4 / ADR-0069 論点 1-a)
# ---------------------------------------------------------------------------


def _probe_bind(host: str, port: int) -> bool:
    """``host:port`` に bind できるか判定する。

    ``SO_REUSEADDR`` は付けない (Windows では使用中ポートへの bind が通ってしまい
    誤判定するため。ADR-0069 実装メモ 1)。

    注意: address family は ``getaddrinfo`` の先頭要素で決めるため、dual-stack な
    hostname (例: ``localhost``) では probe した family と uvicorn が実際に bind する
    family がずれる可能性がある (既定 host ``127.0.0.1`` は単一 family のため影響なし)。

    Args:
        host: bind host。
        port: 試行するポート。

    Returns:
        bind 成功 (= 空きポート) で ``True``、使用中で ``False``。

    Raises:
        FlodeError: host の解決失敗、または使用中以外の理由での bind 失敗。
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as e:
        raise FlodeError(f"Cannot resolve bind host {host!r}: {e}") from e
    family, socktype, proto, _, sockaddr = infos[0]
    sock = socket.socket(family, socktype, proto)
    try:
        sock.bind(sockaddr)
    except OSError as e:
        if e.errno == errno.EADDRINUSE or getattr(e, "winerror", None) == _WINERROR_WSAEACCES:
            return False
        raise FlodeError(f"Failed to bind {_display_host(host)}:{port}: {e}") from e
    finally:
        sock.close()
    return True


def find_free_port(host: str, port0: int, retries: int) -> int:
    """``port0`` から ``port0 + retries`` まで順に試し、最初の空きポートを返す。

    事前 bind プローブ方式のため probe close 〜 uvicorn の実 bind 間に微小な
    TOCTOU 窓があるが、奪われた場合は uvicorn が従来どおり起動失敗として
    表面化する (ADR-0069 で許容済み)。

    Args:
        host: bind host。
        port0: 最初に試すポート。
        retries: フォールバック試行回数 (``0`` で port0 のみ = フォールバック無効)。

    Returns:
        bind 可能だった最初のポート。

    Raises:
        FlodeError: ``port0`` がポート番号上限 (65535) を超えている、範囲内に
            空きポートがない、または bind 失敗が使用中以外の理由。
    """
    if port0 > _MAX_TCP_PORT:
        raise FlodeError(f"Invalid port {port0}: TCP port numbers must be <= {_MAX_TCP_PORT}.")
    # port_retries の誤設定 (例: 100000) で 65535 超を探索しないよう上限で打ち切る
    port_end = min(port0 + retries, _MAX_TCP_PORT)
    for port in range(port0, port_end + 1):
        if _probe_bind(host, port):
            return port
    raise FlodeError(
        f"No free port found in range {port0}-{port_end} "
        f"(tried {port_end - port0 + 1} port(s)). Stop other servers, or adjust "
        f"[server].port / [server].port_retries in ~/.flode/config.toml."
    )


# ---------------------------------------------------------------------------
# ブラウザ自動オープン (SPEC-0021 §1 / ADR-0069 論点 2-b)
# ---------------------------------------------------------------------------


def _display_host(host: str) -> str:
    """URL / ログ表示用の host 文字列を返す (IPv6 literal は角括弧で囲む)。

    Args:
        host: bind または接続先 host。

    Returns:
        URL に埋め込める host 表記 (例: ``::1`` → ``[::1]``、IPv4 はそのまま)。
    """
    return f"[{host}]" if ":" in host else host


def normalize_browser_host(bind_host: str) -> str:
    """bind host からブラウザ接続先 host を導く (SPEC-0021 §4-D)。

    ワイルドカードバインド (``0.0.0.0`` / ``::``) はそのまま接続先にできないため
    loopback へ正規化する。具体 IP / hostname はそのまま返す。

    Args:
        bind_host: サーバの bind host。

    Returns:
        ブラウザ / 接続確認から到達可能な host (角括弧なし)。
    """
    if bind_host in ("0.0.0.0", "localhost"):
        return "127.0.0.1"
    if bind_host == "::":
        return "::1"
    return bind_host


def _browser_url(host: str, port: int) -> str:
    """ブラウザで開く URL を組み立てる。

    Args:
        host: 正規化済みの接続先 host (角括弧なし)。
        port: 実際に bind したポート。

    Returns:
        ``http://<host>:<port>`` 形式の URL (IPv6 literal は角括弧で囲む)。
    """
    return f"http://{_display_host(host)}:{port}"


def _open_browser_when_ready(host: str, port: int, url: str) -> None:
    """listen 確立を TCP 接続で確認してからデフォルトブラウザで ``url`` を開く。

    daemon スレッドで実行される。接続確認が上限試行に達した場合も best-effort で
    1 回開く。ブラウザが開けなくても WARNING に URL を出すだけで、サーバ起動は
    止めない (SPEC-0021 非機能要件)。

    Args:
        host: 接続確認先 host (正規化済み、IPv6 は角括弧なし)。
        port: 接続確認先ポート (= 実際に bind したポート)。
        url: ブラウザで開く URL。
    """
    for _ in range(_BROWSER_POLL_MAX_TRIES):
        try:
            with socket.create_connection((host, port), timeout=_BROWSER_POLL_INTERVAL_S):
                break
        except OSError:
            time.sleep(_BROWSER_POLL_INTERVAL_S)
    try:
        opened = webbrowser.open(url, new=2)
    except (webbrowser.Error, OSError) as e:
        _logger.warning("Could not open a web browser (%s). Open %s manually.", e, url)
        return
    if not opened:
        _logger.warning("No web browser available. Open %s manually.", url)


def _launch_browser_thread(bind_host: str, port: int) -> None:
    """ブラウザ自動オープン用の daemon スレッドを起動する (SPEC-0021 §1)。

    daemon=True のためプロセス終了時に置き去りにならない (ADR-0069 実装メモ 9)。
    """
    connect_host = normalize_browser_host(bind_host)
    url = _browser_url(connect_host, port)
    threading.Thread(
        target=_open_browser_when_ready,
        args=(connect_host, port, url),
        daemon=True,
        name="flode-browser-open",
    ).start()


def _build_parser() -> argparse.ArgumentParser:
    # prog は主コマンド名に固定 (alias の flode で呼ばれても help は flode を案内)
    parser = argparse.ArgumentParser(
        prog="flode",
        description="Run the flode server and open the UI in your browser.",
    )
    # SPEC-0004: 「CLI 明示指定」と「未指定 (= file or default にフォールバック)」を
    # 区別するため、設定ファイルから上書きされうるフラグは default=None にする。
    # argparse.SUPPRESS を使う案もあるが、Namespace を dict 化して Resolver に渡す
    # 都合上、None sentinel の方が直感的。
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help=(
            "Workspace root directory for File API (/api/v1/files/*). "
            "Defaults to the current working directory. ADR-0041 §3."
        ),
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Bind host (default: 127.0.0.1; can be set in ~/.flode/config.toml).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Bind port (default: 8770; can be set in ~/.flode/config.toml).",
    )
    parser.add_argument(
        "--allow-origin",
        action="append",
        default=None,
        help="Add a CORS allowed origin (repeat for multiple, e.g. for a Vite dev server).",
    )
    parser.add_argument(
        "--scope-batch-size",
        type=int,
        default=None,
        help="Scope batch size sent over WebSocket (default: 100).",
    )
    # SPEC-0021: ブラウザ自動オープンは既定 ON。恒久無効化は
    # ~/.flode/config.toml の [server] open_browser = false。
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help=(
            "Do not open the web browser after startup (for headless / CI / "
            "background use). Default is to open it. SPEC-0021."
        ),
    )
    # SPEC-0004: 設定ファイル機能
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help=("Path to TOML config file. If omitted, ~/.flode/config.toml is searched. SPEC-0004."),
    )
    parser.add_argument(
        "--generate-config",
        action="store_true",
        help=(
            "Write a commented config template to ~/.flode/config.toml and exit. "
            "Use --force to overwrite an existing file. SPEC-0004."
        ),
    )
    # v0.21.0 (ADR-0041 §論点 6-A): legacy ``models/`` から workspace への
    # 一括移行 CLI。指定されるとサーバは起動せず migrate のみ実行して終了。
    parser.add_argument(
        "--migrate-models-to",
        type=Path,
        default=None,
        metavar="DST_DIR",
        help=(
            "Migrate .flw.json files from a legacy models/ directory to a "
            "workspace directory and exit (do not start the server). "
            "Use with --legacy-models-dir to specify the source. ADR-0041 §6-A."
        ),
    )
    parser.add_argument(
        "--legacy-models-dir",
        type=Path,
        default=None,
        metavar="SRC_DIR",
        help=(
            "Source directory for --migrate-models-to (= the old --model-dir "
            "you used before v0.21.0). Required when --migrate-models-to is set."
        ),
    )
    # SPEC-0004: --force は --generate-config / --migrate-models-to の両者で使う
    # (destructive 操作の確認 bypass、意味が一致)。
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Force destructive operations: with --generate-config, overwrite existing "
            "config file; with --migrate-models-to, overwrite existing destination files."
        ),
    )
    return parser


def _build_settings_from_args(
    args: argparse.Namespace,
) -> tuple[Settings, str, int, bool, int]:
    """argparse Namespace から ``(Settings, host, port, open_browser, port_retries)``
    を構築する (SPEC-0004 / SPEC-0021)。

    SPEC-0004 §4: ``CLI > 設定ファイル > default`` の優先順位で解決する。

    Returns:
        ``(Settings, host, port, open_browser, port_retries)`` のタプル。
        ``Settings`` は ``create_app`` に、``host``/``port`` は ``uvicorn.run`` に、
        ``open_browser``/``port_retries`` は起動シーケンス (SPEC-0021) に渡す。

    Raises:
        FlodeError: 設定ファイルのパースエラー、型違反、workspace path 不在など。
    """
    config_path = resolve_config_path(explicit=args.config)
    if config_path is not None:
        _logger.info("Loaded config from %s", config_path)
        file_cfg = load_config_file(config_path)
    else:
        file_cfg = {}

    cli_dict: dict[str, Any] = {
        "workspace": args.workspace,
        "host": args.host,
        "port": args.port,
        "scope_batch_size": args.scope_batch_size,
    }
    # --allow-origin は append action: 1 回以上指定で list、未指定なら None。
    # None は「CLI 未指定 → file or default にフォールバック」、空 list は
    # 「ユーザーが明示的にゼロ個指定した」を意味する (現状ありえないが、防御的に)。
    if args.allow_origin is not None:
        cli_dict["allow_origins"] = args.allow_origin
    # SPEC-0021: --no-browser は CLI 最優先で open_browser を False に上書き。
    # 未指定時はキーを渡さない (= file or default にフォールバック)。
    if args.no_browser:
        cli_dict["open_browser"] = False

    resolver = SettingsResolver(cli=cli_dict, file_config=file_cfg)
    settings = resolver.build_settings(default_workspace=Path.cwd().resolve())
    host, port = resolver.build_server_bind()
    open_browser, port_retries = resolver.build_launch_options()
    return settings, host, port, open_browser, port_retries


def _run_migration(src: Path | None, dst: Path, *, force: bool) -> int:
    """``--migrate-models-to`` の本体 (= main から呼ばれる、サーバは起動しない)。

    Returns:
        終了コード (0 = 全成功、1 = skip / error あり)。
    """
    if src is None:
        sys.stderr.write(
            "ERROR: --migrate-models-to requires --legacy-models-dir to specify "
            "the source directory.\n"
        )
        return 2

    report = migrate_models_to(src, dst, force=force)

    # JSON で結果を stdout に出力 (= cron / CI で自動化しやすい形式)
    output = {
        "migrated": [str(p) for p in report.migrated],
        "skipped": [str(p) for p in report.skipped],
        "errors": [{"path": str(p), "message": msg} for p, msg in report.errors],
    }
    sys.stdout.write(json.dumps(output, indent=2, ensure_ascii=False) + "\n")

    if report.has_errors:
        return 1
    if report.skipped:
        return 1  # skip があれば warning 扱いで非ゼロ
    return 0


def main(argv: list[str] | None = None) -> None:
    """``flode`` (alias: ``flode``) のエントリポイント。

    Args:
        argv: テスト用に明示的な argv を渡せる。``None`` で ``sys.argv[1:]`` を使う。

    Raises:
        FlodeError: 設定ファイル不正、``--workspace`` 指定 path が不在、または
            ``uvicorn`` (= ``flode[gui]`` extras) がインストールされていない場合。
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _build_parser().parse_args(argv)

    # SPEC-0004: --generate-config が指定されたら雛形を書き出して終了
    if args.generate_config:
        generate_config_template(default_user_config_path(), force=args.force)
        sys.exit(0)

    # v0.21.0: --migrate-models-to が指定されたらサーバ起動せず migrate のみ実行
    if args.migrate_models_to is not None:
        exit_code = _run_migration(
            args.legacy_models_dir,
            args.migrate_models_to,
            force=args.force,
        )
        sys.exit(exit_code)

    settings, host, port0, open_browser, port_retries = _build_settings_from_args(args)
    app = create_app(settings=settings)
    # ``uvicorn`` を遅延 import: extras 未インストール時にユーザーへ明確に誘導するため
    # (code-reviewer MUST 修正)。
    try:
        import uvicorn
    except ImportError as e:
        raise FlodeError(
            "flode requires uvicorn to run the server. Install with: pip install flode[gui]"
        ) from e
    # SPEC-0021 §4: ポート自動フォールバック。実際に bind するポートを確定する。
    port = find_free_port(host, port0, port_retries)
    if port != port0:
        _logger.warning("Port %d is in use, using %d instead.", port0, port)
    _logger.info(
        "Starting flode on http://%s:%d (workspace=%s)",
        _display_host(host),
        port,
        settings.workspace_root,
    )
    # SPEC-0021 §1: ブラウザ自動オープン (listen 確立を確認してから開く)
    if open_browser:
        _launch_browser_thread(host, port)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
