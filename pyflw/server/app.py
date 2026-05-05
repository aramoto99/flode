"""FastAPI アプリケーション factory (ADR-0011 §(3))。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .errors import register_error_handlers
from .routes import models_router, simulations_router
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
        )
    settings.model_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        manager = SimulationManager(max_concurrent=settings.max_concurrent)
        app.state.simulation_manager = manager
        try:
            yield
        finally:
            manager.shutdown()

    app = FastAPI(
        title="pyflw server",
        version="0.2.0.dev0",
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
    register_error_handlers(app)
    return app
