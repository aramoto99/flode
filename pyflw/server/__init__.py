"""pyflw Web GUI バックエンド (ADR-0011)。

``pip install pyflw[gui]`` でオプトイン。``fastapi`` が無い場合は ``PyflwError``
で誘導する。

主公開 API:
    * ``create_app(model_dir)`` -> FastAPI インスタンス
    * ``Settings`` -> サーバ設定 dataclass
"""

from __future__ import annotations

try:
    import fastapi  # noqa: F401
except ImportError as e:
    from ..exceptions import PyflwError

    raise PyflwError("pyflw.server requires FastAPI. Install with: pip install pyflw[gui]") from e

from .app import create_app
from .settings import Settings

__all__ = ["Settings", "create_app"]
