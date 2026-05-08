"""FastAPI アプリケーション factory (ADR-0011 §(3))。"""

from __future__ import annotations

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
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app
