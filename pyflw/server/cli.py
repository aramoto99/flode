"""``pyflw-server`` コマンドのエントリポイント (ADR-0013 §(2))。

``pip install pyflw[gui]`` 後、コマンドラインから::

    pyflw-server --model-dir ./models --port 8765

で FastAPI サーバを起動する。``pyflw[gui]`` extras が無い場合は
``pyflw.server`` の import 時点で ``PyflwError`` が出るので、ユーザーが extras を
インストールするよう誘導される。
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ..exceptions import PyflwError
from .app import create_app
from .settings import Settings

_logger = logging.getLogger("pyflw.server.cli")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyflw-server",
        description="Run the pyflw FastAPI server.",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path.cwd() / "models",
        help="Directory holding .flw.json model files (default: ./models).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765).")
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


def main(argv: list[str] | None = None) -> None:
    """``pyflw-server`` のエントリポイント。

    Args:
        argv: テスト用に明示的な argv を渡せる。``None`` で ``sys.argv[1:]`` を使う。

    Raises:
        PyflwError: ``uvicorn`` (= ``pyflw[gui]`` extras) がインストールされていない
            場合。``ImportError`` をラップして ``pip install pyflw[gui]`` を案内する。
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _build_parser().parse_args(argv)
    settings = Settings(
        model_dir=args.model_dir,
        scope_batch_size=args.scope_batch_size,
        allow_origins=list(args.allow_origin),
    )
    app = create_app(args.model_dir, settings=settings)
    # ``uvicorn`` を遅延 import: extras 未インストール時にユーザーへ明確に誘導するため
    # (code-reviewer MUST 修正)。
    try:
        import uvicorn
    except ImportError as e:
        raise PyflwError(
            "pyflw-server requires uvicorn. Install with: pip install pyflw[gui]"
        ) from e
    _logger.info(
        "Starting pyflw-server on http://%s:%d (model_dir=%s)",
        args.host,
        args.port,
        args.model_dir,
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
