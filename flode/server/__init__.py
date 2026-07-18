"""flode Web GUI バックエンド (ADR-0011)。

GUI サーバー依存 (fastapi 等) は core 依存に含まれる (v0.44.0 で旧 ``[gui]``
extras から統合)。``fastapi`` が無い場合 (壊れた環境) は ``FlodeError`` で誘導する。

主公開 API:
    * ``create_app(model_dir)`` -> FastAPI インスタンス
    * ``Settings`` -> サーバ設定 dataclass
"""

from __future__ import annotations

try:
    import fastapi  # noqa: F401
except ImportError as e:
    from ..exceptions import FlodeError

    raise FlodeError("flode.server requires FastAPI. Reinstall with: pip install flode") from e

from .app import create_app
from .settings import Settings

__all__ = ["Settings", "create_app"]
