"""FastAPI ルート (ADR-0011 §(1)(2))。"""

from .models import router as models_router
from .simulations import router as simulations_router

__all__ = ["models_router", "simulations_router"]
