"""FastAPI ルート (ADR-0011 §(1)(2)、ADR-0019 §(1) で blocks 追加、ADR-0029 で
libraries 追加、ADR-0041 §1 で files 追加。v0.21.0 で legacy models 削除)。"""

from .blocks import router as blocks_router
from .files import router as files_router
from .libraries import router as libraries_router
from .models import router as models_router
from .simulations import router as simulations_router

__all__ = [
    "blocks_router",
    "files_router",
    "libraries_router",
    "models_router",
    "simulations_router",
]
