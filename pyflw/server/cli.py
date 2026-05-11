"""``pyflw-server`` コマンドのエントリポイント (ADR-0013 §(2) / ADR-0041 §3)。

``pip install pyflw[gui]`` 後、コマンドラインから::

    pyflw-server --workspace ./project --port 8770

で FastAPI サーバを起動する。``pyflw[gui]`` extras が無い場合は
``pyflw.server`` の import 時点で ``PyflwError`` が出るので、ユーザーが extras を
インストールするよう誘導される。

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

from ..exceptions import PyflwError
from .app import create_app
from .migrations import migrate_models_to
from .settings import Settings

_logger = logging.getLogger("pyflw.server.cli")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyflw-server",
        description="Run the pyflw FastAPI server.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help=(
            "Workspace root directory for File API (/api/v1/files/*). "
            "Defaults to the current working directory. ADR-0041 §3."
        ),
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8770, help="Bind port (default: 8770).")
    parser.add_argument(
        "--allow-origin",
        action="append",
        default=[],
        help="Add a CORS allowed origin (repeat for multiple, e.g. for a Vite dev server).",
    )
    parser.add_argument(
        "--scope-batch-size",
        type=int,
        default=100,
        help="Scope batch size sent over WebSocket (default: 100).",
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
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "When used with --migrate-models-to, overwrite existing files in "
            "the destination directory (default: skip)."
        ),
    )
    return parser


def _build_settings(
    *,
    workspace: Path | None,
    allow_origins: list[str],
    scope_batch_size: int,
) -> Settings:
    """Parsed CLI arguments から ``Settings`` を構築する (ADR-0041 §3)。

    v0.21.0: legacy ``--model-dir`` 削除済。``workspace`` が ``None`` なら
    default で ``Path.cwd()`` を使う。

    Raises:
        PyflwError: ``--workspace`` 指定時にディレクトリが存在しない場合。
    """
    if workspace is not None:
        workspace_resolved = workspace.resolve()
        if not workspace_resolved.exists():
            raise PyflwError(
                f"Workspace root does not exist: {workspace_resolved}. "
                f"Create the directory first (mkdir -p) or specify a different "
                f"--workspace path."
            )
        if not workspace_resolved.is_dir():
            raise PyflwError(
                f"Workspace root is not a directory: {workspace_resolved}. "
                f"--workspace must point to a directory, not a file."
            )
        return Settings(
            workspace_root=workspace_resolved,
            scope_batch_size=scope_batch_size,
            allow_origins=list(allow_origins),
        )

    # default: workspace = CWD
    cwd = Path.cwd().resolve()
    return Settings(
        workspace_root=cwd,
        scope_batch_size=scope_batch_size,
        allow_origins=list(allow_origins),
    )


def _run_migration(src: Path | None, dst: Path, *, force: bool) -> int:
    """``--migrate-models-to`` の本体 (= main から呼ばれる、サーバは起動しない)。

    Returns:
        終了コード (0 = 全成功、1 = skip / error あり)。
    """
    if src is None:
        print(
            "ERROR: --migrate-models-to requires --legacy-models-dir to specify "
            "the source directory.",
            file=sys.stderr,
        )
        return 2

    report = migrate_models_to(src, dst, force=force)

    # JSON で結果を stdout に出力 (= cron / CI で自動化しやすい形式)
    output = {
        "migrated": [str(p) for p in report.migrated],
        "skipped": [str(p) for p in report.skipped],
        "errors": [{"path": str(p), "message": msg} for p, msg in report.errors],
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))

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
        PyflwError: ``--workspace`` 指定 path が不在、または ``uvicorn``
            (= ``pyflw[gui]`` extras) がインストールされていない場合。
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _build_parser().parse_args(argv)

    # v0.21.0: --migrate-models-to が指定されたらサーバ起動せず migrate のみ実行
    if args.migrate_models_to is not None:
        exit_code = _run_migration(
            args.legacy_models_dir,
            args.migrate_models_to,
            force=args.force,
        )
        sys.exit(exit_code)

    settings = _build_settings(
        workspace=args.workspace,
        allow_origins=list(args.allow_origin),
        scope_batch_size=args.scope_batch_size,
    )
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
        args.host,
        args.port,
        settings.workspace_root,
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
