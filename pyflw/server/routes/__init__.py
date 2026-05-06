"""FastAPI ルート (ADR-0011 §(1)(2)、ADR-0019 §(1) で blocks 追加)。"""

from .blocks import router as blocks_router
from .models import router as models_router
from .simulations import router as simulations_router

__all__ = ["blocks_router", "models_router", "simulations_router"]
