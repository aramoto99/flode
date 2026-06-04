"""``pyflw-server`` コマンドのエントリポイント (ADR-0013 §(2) / ADR-0041 §3 / SPEC-0004)。

``pip install pyflw[gui]`` 後、コマンドラインから::

    pyflw-server --workspace ./project --port 8770

で FastAPI サーバを起動する。``pyflw[gui]`` extras が無い場合は
``pyflw.server`` の import 時点で ``PyflwError`` が出るので、ユーザーが extras を
インストールするよう誘導される。

SPEC-0004 (v3.17.0~): ``~/.pyflw/config.toml`` をサポート。優先順位は
``CLI 引数 > 設定ファイル > default``。設定ファイル不在時は warning なしで default
起動 (Jupyter Lab 準拠)。

v0.21.0 (ADR-0041 §論点 4-A): legacy ``--model-dir`` を削除。旧 ``models/``
ディレクトリから workspace への移行は ``pyflw-server --migrate-models-to=DIR``
で実行する (= サーバ起動せず migrate のみ)。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from ..exceptions import PyflwError
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

_logger = logging.getLogger("pyflw.server.cli")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyflw-server",
        description="Run the pyflw FastAPI server.",
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
        help="Bind host (default: 127.0.0.1; can be set in ~/.pyflw/config.toml).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Bind port (default: 8770; can be set in ~/.pyflw/config.toml).",
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
    # SPEC-0004: 設定ファイル機能
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help=("Path to TOML config file. If omitted, ~/.pyflw/config.toml is searched. SPEC-0004."),
    )
    parser.add_argument(
        "--generate-config",
        action="store_true",
        help=(
            "Write a commented config template to ~/.pyflw/config.toml and exit. "
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


def _build_settings_from_args(args: argparse.Namespace) -> tuple[Settings, str, int]:
    """argparse Namespace から ``(Settings, host, port)`` を構築する (SPEC-0004)。

    SPEC-0004 §4: ``CLI > 設定ファイル > default`` の優先順位で解決する。

    Returns:
        ``(Settings, host, port)`` のタプル。``Settings`` は ``create_app`` に、
        ``host``/``port`` は ``uvicorn.run`` に渡す。

    Raises:
        PyflwError: 設定ファイルのパースエラー、型違反、workspace path 不在など。
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

    resolver = SettingsResolver(cli=cli_dict, file_config=file_cfg)
    settings = resolver.build_settings(default_workspace=Path.cwd().resolve())
    host, port = resolver.build_server_bind()
    return settings, host, port


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
    """``pyflw-server`` のエントリポイント。

    Args:
        argv: テスト用に明示的な argv を渡せる。``None`` で ``sys.argv[1:]`` を使う。

    Raises:
        PyflwError: 設定ファイル不正、``--workspace`` 指定 path が不在、または
            ``uvicorn`` (= ``pyflw[gui]`` extras) がインストールされていない場合。
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

    settings, host, port = _build_settings_from_args(args)
    app = create_app(settings=settings)
    # ``uvicorn`` を遅延 import: extras 未インストール時にユーザーへ明確に誘導するため
    # (code-reviewer MUST 修正)。
    try:
        import uvicorn
    except ImportError as e:
        raise PyflwError(
            "pyflw-server requires uvicorn. Install with: pip install pyflw[gui]"
        ) from e
    _logger.info(
        "Starting pyflw-server on http://%s:%d (workspace=%s)",
        host,
        port,
        settings.workspace_root,
    )
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
