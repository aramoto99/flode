__version__ = "0.7.0"  # ADR-0019 GUI palette + drag-drop + Block registry (2026-05-06)

from .core.block import Block
from .core.decorator import block
from .core.simulator import Simulator
from .exceptions import (
    AlgebraicLoopError,
    BlockSpecError,
    ModelLoadError,
    ModelSerializationError,
    PyflwError,
    SchedulingError,
    SchemaVersionError,
    SimulationStillRunningError,
    SolverError,
    UnknownBlockIdError,
    UnknownBlockTypeError,
)
from .subsystems import Inport, Outport, Subsystem

__all__ = [
    "AlgebraicLoopError",
    "Block",
    "BlockSpecError",
    "Inport",
    "ModelLoadError",
    "ModelSerializationError",
    "Outport",
    "PyflwError",
    "SchedulingError",
    "SchemaVersionError",
    "SimulationStillRunningError",
    "Simulator",
    "SolverError",
    "Subsystem",
    "UnknownBlockIdError",
    "UnknownBlockTypeError",
    "block",
]
