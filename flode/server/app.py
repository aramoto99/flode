"""FastAPI アプリケーション factory (ADR-0011 §(3)、v0.21.0 で legacy
``models_router`` / deprecation middleware を削除済)。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ..blocks.pythonfunc import set_python_block_policy
from .errors import register_error_handlers
from .library_registry import build_library_registry
from .registry import build_block_registry
from .routes import (
    blocks_router,
    files_router,
    libraries_router,
    simulations_router,
)
from .runtime import SimulationManager
from .security.origin import check_state_changing_request
from .settings import Settings


def create_app(*, settings: Settings) -> FastAPI:
    """``flode`` の Web GUI バックエンド ``FastAPI`` アプリを生成する。

    Args:
        settings: 詳細設定 (``Settings`` インスタンス、``workspace_root`` 必須)。

    Returns:
        起動準備済みの ``FastAPI`` インスタンス。``uvicorn.run(app, host=..., port=...)``
        でサーブできる。

    Note:
        v0.21.0 (ADR-0041): ``model_dir`` 引数 + legacy ``--model-dir`` モードを
        削除。``settings`` は必須キーワード引数で、``Settings.workspace_root`` を
        必ず指定すること。
    """
    # 防御的コピー (= 呼び出し側が後から settings を変更しても影響しない)
    settings = Settings(
        workspace_root=Path(settings.workspace_root),
        scope_batch_size=settings.scope_batch_size,
        max_concurrent=settings.max_concurrent,
        allow_origins=list(settings.allow_origins),
        library_paths=[Path(p) for p in settings.library_paths],
        bundle_builtin_libraries=settings.bundle_builtin_libraries,
        python_blocks_allowed=settings.python_blocks_allowed,
        python_blocks_reason=settings.python_blocks_reason,
    )
    # SPEC-0023 / ADR-0073 §論点 4 (H): PythonFunction の hard gate をプロセス policy に
    # 適用する唯一の場所。CLI は bind host から決めた値を Settings に入れて渡す。
    # 判定点は ``PythonFunction._build()`` (= exec 直前) の 1 箇所で、REST / WS /
    # Python API のどの経路でも同じ policy を通る。
    set_python_block_policy(
        allowed=settings.python_blocks_allowed, reason=settings.python_blocks_reason
    )

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

    # ``flode.__version__`` を SoT として使う (ADR-0013 §V-A、code-reviewer SHOULD)
    from .. import __version__ as _flode_version

    app = FastAPI(
        title="flode server",
        version=_flode_version,
        lifespan=lifespan,
    )
    app.state.settings = settings

    # CSRF guard (security/origin.py): 書き込み要求は application/json 必須 + Origin 検証。
    # ブラウザ経由の cross-site 要求 (simple request) で loopback サーバーを叩かせない。
    # CORS ミドルウェアより内側に置く (= preflight OPTIONS は CORS が先に処理する)。
    @app.middleware("http")
    async def _csrf_guard(request: Request, call_next: object) -> Response:
        headers = request.headers
        content_length = headers.get("content-length") or "0"
        has_body = headers.get("transfer-encoding") is not None or (
            content_length.isdigit() and int(content_length) > 0
        )
        rejection = check_state_changing_request(
            method=request.method,
            origin=headers.get("origin"),
            host=headers.get("host"),
            content_type=headers.get("content-type"),
            has_body=has_body,
            allow_origins=settings.allow_origins,
        )
        if rejection is not None:
            logging.getLogger("flode.server.app").warning(
                "Rejected %s %s: %s", request.method, request.url.path, rejection.detail
            )
            return JSONResponse(
                status_code=rejection.status_code, content={"detail": rejection.detail}
            )
        return await call_next(request)  # type: ignore[operator, no-any-return]

    if settings.allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.allow_origins),
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(simulations_router, prefix="/api/v1")
    app.include_router(blocks_router, prefix="/api/v1")
    app.include_router(libraries_router, prefix="/api/v1")
    app.include_router(files_router, prefix="/api/v1")
    register_error_handlers(app)

    # ADR-0012 §(6): frontend ビルド成果物を ``flode/server/static/`` から配信。
    # ディレクトリが存在しない (= ``npm run build`` 未実行 / dev mode) 場合は
    # マウントしない。``html=True`` で SPA ルーティングを ``index.html`` に
    # フォールバックする。API ルートは先に登録済みなので static は最後にする。
    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir() and any(static_dir.iterdir()):
        # ADR-0039 v0.14.1 §再発防止: 配信される frontend bundle の version と
        # backend の ``flode.__version__`` を起動時に突き合わせ、ズレていれば
        # warning を出す。これで「コードは新しいが bundle が古い」事故を早期検知。
        # mount より先に呼ぶ — WARNING が mount エラーログに埋もれないため。
        _check_frontend_bundle_version(static_dir, _flode_version)
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app


def _check_frontend_bundle_version(static_dir: Path, backend_version: str) -> None:
    """配信される frontend bundle の version を backend と比較する。

    deploy script (= ``flode/web/frontend/scripts/deploy-to-server-static.mjs``)
    が ``flode/server/static/.app-version`` に build 時の ``package.json#version``
    を書き残す。本関数はそれを読んで backend ``flode.__version__`` と比較する。

    bundle 内の ``__APP_VERSION__`` は vite の ``define`` で静的置換され、minify で
    変数名が消えるため文字列の grep では拾えない。そのため別ファイルで明示する。

    マーカー file が無い (= release CI 経由の wheel install / 古い deploy script)
    時は silent skip (= 過剰な warning は出さない)。

    Args:
        static_dir: ``flode/server/static`` ディレクトリ。
        backend_version: ``flode.__version__`` (= source of truth)。
    """
    logger = logging.getLogger("flode.server.app")
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
            "Run 'npm run build' inside flode/web/frontend to refresh the bundle "
            "(ADR-0039 v0.14.1 §再発防止).",
            backend_version,
            bundle_version,
        )
