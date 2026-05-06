__version__ = "0.6.0"  # ADR-0017 Phase 3 #3 (SM-B vector ports, BREAKING, 2026-05-06)

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
