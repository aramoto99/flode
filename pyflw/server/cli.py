"""``pyflw-server`` コマンドのエントリポイント (ADR-0013 §(2) / ADR-0041 §3)。

``pip install pyflw[gui]`` 後、コマンドラインから::

    # v0.15.0+ 推奨形式 (ADR-0041)
    pyflw-server --workspace ./project --port 8770

    # legacy (v3.0 で削除予告)
    pyflw-server --model-dir ./models --port 8770

で FastAPI サーバを起動する。``pyflw[gui]`` extras が無い場合は
``pyflw.server`` の import 時点で ``PyflwError`` が出るので、ユーザーが extras を
インストールするよう誘導される。
"""

from __future__ import annotations

import argparse
import logging
import warnings
from pathlib import Path

from ..exceptions import PyflwError
from .app import create_app
from .settings import Settings

_logger = logging.getLogger("pyflw.server.cli")

_DEPRECATION_MODEL_DIR_MSG = (
    "--model-dir is deprecated; use --workspace=PATH instead. "
    "/api/v1/models/* and --model-dir will be removed in v3.0 "
    "(see ADR-0041 for migration guide)."
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyflw-server",
        description="Run the pyflw FastAPI server.",
    )
    # ``--workspace`` (新) と ``--model-dir`` (legacy) は相互排他
    # (ADR-0041 §論点 3-A)。両方未指定なら default は CWD (= ``--workspace`` 扱い)。
    workspace_group = parser.add_mutually_exclusive_group()
    workspace_group.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help=(
            "Workspace root directory for File API (/api/v1/files/*). "
            "Defaults to the current working directory. ADR-0041 §3."
        ),
    )
    workspace_group.add_argument(
        "--model-dir",
        type=Path,
        default=None,
        help=(
            "DEPRECATED (v0.15.0+, removed in v3.0): legacy directory for "
            ".flw.json model files served via /api/v1/models/*. "
            "Use --workspace instead."
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
    return parser


def _build_settings(
    *,
    workspace: Path | None,
    model_dir: Path | None,
    allow_origins: list[str],
    scope_batch_size: int,
) -> Settings:
    """Parsed CLI arguments から ``Settings`` を構築する (ADR-0041 §3)。

    分岐:
        * ``workspace`` が指定された → ``workspace_root`` を絶対 path で設定。
          ``model_dir`` も同じディレクトリに設定 (= legacy ``/api/v1/models/*``
          も workspace 配下を flat に見る、v2.x 並存期間)
        * ``model_dir`` のみ指定された → ``DeprecationWarning``、``model_dir``
          のみ設定 (``workspace_root`` は ``None``、File API は無効化)
        * 両方 ``None`` → default ``--workspace=Path.cwd()``

    Raises:
        PyflwError: ``--workspace`` 指定時にディレクトリが存在しない場合。

    Returns:
        ``Settings`` インスタンス。
    """
    # argparse の mutually exclusive group は両指定を弾くため、ここでは
    # workspace と model_dir が同時に non-None になることはない。
    if workspace is not None:
        workspace_resolved = workspace.resolve()
        # 不在 / ファイル / 通常 dir を 2 分岐で区別 — 利用者向けエラーメッセージで
        # 何をすればよいか (= mkdir vs --workspace の path 修正) を明確化する。
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
            model_dir=workspace_resolved,
            workspace_root=workspace_resolved,
            scope_batch_size=scope_batch_size,
            allow_origins=list(allow_origins),
        )

    if model_dir is not None:
        # legacy --model-dir モード: deprecation warning + File API 無効。
        # ``stacklevel=2`` は ``main() → _build_settings`` の呼び出しを想定して
        # おり、利用者には main の行 (= CLI 入口) が表示される。テストから
        # ``_build_settings`` を直接呼んだ場合は呼び出し元 (= テスト) が表示
        # されるが、production path では正しい挙動なので維持。
        warnings.warn(_DEPRECATION_MODEL_DIR_MSG, DeprecationWarning, stacklevel=2)
        return Settings(
            model_dir=model_dir,
            workspace_root=None,
            scope_batch_size=scope_batch_size,
            allow_origins=list(allow_origins),
        )

    # default: workspace = CWD
    cwd = Path.cwd().resolve()
    return Settings(
        model_dir=cwd,
        workspace_root=cwd,
        scope_batch_size=scope_batch_size,
        allow_origins=list(allow_origins),
    )


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
    settings = _build_settings(
        workspace=args.workspace,
        model_dir=args.model_dir,
        allow_origins=list(args.allow_origin),
        scope_batch_size=args.scope_batch_size,
    )
    app = create_app(settings.model_dir, settings=settings)
    # ``uvicorn`` を遅延 import: extras 未インストール時にユーザーへ明確に誘導するため
    # (code-reviewer MUST 修正)。
    try:
        import uvicorn
    except ImportError as e:
        raise PyflwError(
            "pyflw-server requires uvicorn. Install with: pip install pyflw[gui]"
        ) from e
    if settings.workspace_root is not None:
        _logger.info(
            "Starting pyflw-server on http://%s:%d (workspace=%s)",
            args.host,
            args.port,
            settings.workspace_root,
        )
    else:
        _logger.info(
            "Starting pyflw-server on http://%s:%d (legacy model_dir=%s)",
            args.host,
            args.port,
            settings.model_dir,
        )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
