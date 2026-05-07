__version__ = "0.7.2"  # GUI polish: desktop shell, sinks (Display/XYGraph), dynamic ports, resize, multi-select, shift-disconnect (2026-05-07)

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
