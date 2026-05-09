"""FastAPI アプリケーション factory (ADR-0011 §(3))。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .errors import register_error_handlers
from .library_registry import build_library_registry
from .registry import build_block_registry
from .routes import (
    blocks_router,
    libraries_router,
    models_router,
    simulations_router,
)
from .runtime import SimulationManager
from .settings import Settings


def create_app(
    model_dir: Path | str,
    *,
    settings: Settings | None = None,
) -> FastAPI:
    """``pyflw`` の Web GUI バックエンド ``FastAPI`` アプリを生成する。

    Args:
        model_dir: ``.flw.json`` を置くディレクトリ。``settings`` が渡された場合は
            ``settings.model_dir`` が優先される。
        settings: 詳細設定 (``Settings`` インスタンス)。``None`` のときは ``model_dir``
            のみを使う最小設定で起動。

    Returns:
        起動準備済みの ``FastAPI`` インスタンス。``uvicorn.run(app, host=..., port=...)``
        でサーブできる。
    """
    if settings is None:
        settings = Settings(model_dir=Path(model_dir))
    else:
        settings = Settings(
            model_dir=Path(settings.model_dir),
            workspace_root=(
                Path(settings.workspace_root) if settings.workspace_root is not None else None
            ),
            scope_batch_size=settings.scope_batch_size,
            max_concurrent=settings.max_concurrent,
            allow_origins=list(settings.allow_origins),
            library_paths=[Path(p) for p in settings.library_paths],
            bundle_builtin_libraries=settings.bundle_builtin_libraries,
        )
    settings.model_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        manager = SimulationManager(max_concurrent=settings.max_concurrent)
        app.state.simulation_manager = manager
        # ADR-0019 §1.5: Block class registry を起動時に 1 回 walk して app.state にキャッシュ。
        app.state.block_registry = build_block_registry()
        # ADR-0029: Library registry を起動時に 1 回 build して app.state にキャッシュ。
        app.state.library_registry = build_library_registry(
            settings.library_paths,
            bundle_builtin=settings.bundle_builtin_libraries,
        )
        try:
            yield
        finally:
            manager.shutdown()

    # ``pyflw.__version__`` を SoT として使う (ADR-0013 §V-A、code-reviewer SHOULD)
    from .. import __version__ as _pyflw_version

    app = FastAPI(
        title="pyflw server",
        version=_pyflw_version,
        lifespan=lifespan,
    )
    app.state.settings = settings

    if settings.allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.allow_origins),
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(models_router, prefix="/api/v1")
    app.include_router(simulations_router, prefix="/api/v1")
    app.include_router(blocks_router, prefix="/api/v1")
    app.include_router(libraries_router, prefix="/api/v1")
    register_error_handlers(app)

    # ADR-0012 §(6): frontend ビルド成果物を ``pyflw/server/static/`` から配信。
    # ディレクトリが存在しない (= ``npm run build`` 未実行 / dev mode) 場合は
    # マウントしない。``html=True`` で SPA ルーティングを ``index.html`` に
    # フォールバックする。API ルートは先に登録済みなので static は最後にする。
    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir() and any(static_dir.iterdir()):
        # ADR-0039 v0.14.1 §再発防止: 配信される frontend bundle の version と
        # backend の ``pyflw.__version__`` を起動時に突き合わせ、ズレていれば
        # warning を出す。これで「コードは新しいが bundle が古い」事故を早期検知。
        # mount より先に呼ぶ — WARNING が mount エラーログに埋もれないため。
        _check_frontend_bundle_version(static_dir, _pyflw_version)
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app


def _check_frontend_bundle_version(static_dir: Path, backend_version: str) -> None:
    """配信される frontend bundle の version を backend と比較する。

    deploy script (= ``pyflw/web/frontend/scripts/deploy-to-server-static.mjs``)
    が ``pyflw/server/static/.app-version`` に build 時の ``package.json#version``
    を書き残す。本関数はそれを読んで backend ``pyflw.__version__`` と比較する。

    bundle 内の ``__APP_VERSION__`` は vite の ``define`` で静的置換され、minify で
    変数名が消えるため文字列の grep では拾えない。そのため別ファイルで明示する。

    マーカー file が無い (= release CI 経由の wheel install / 古い deploy script)
    時は silent skip (= 過剰な warning は出さない)。

    Args:
        static_dir: ``pyflw/server/static`` ディレクトリ。
        backend_version: ``pyflw.__version__`` (= source of truth)。
    """
    logger = logging.getLogger("pyflw.server.app")
    marker = static_dir / ".app-version"
    if not marker.is_file():
        return
    try:
        bundle_version = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return
    if not bundle_version:
        return
    if bundle_version != backend_version:
        logger.warning(
            "frontend bundle version mismatch: backend=%s but bundle reports %s. "
            "Run 'npm run build' inside pyflw/web/frontend to refresh the bundle "
            "(ADR-0039 v0.14.1 §再発防止).",
            backend_version,
            bundle_version,
        )
