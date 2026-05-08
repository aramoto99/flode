__version__ = "0.11.0"  # ADR-0028: Block registry i18n (display_name_i18n / docstring_summary_i18n, Phase 4 #3, 2026-05-08)

from .analysis import (
    BodeResponse,
    LinearSystem,
    NyquistResponse,
    RootLocus,
    bode,
    eigenvalues,
    is_stable,
    linearize,
    nyquist,
    root_locus,
)
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
    "BodeResponse",
    "Inport",
    "LinearSystem",
    "ModelLoadError",
    "ModelSerializationError",
    "NyquistResponse",
    "Outport",
    "PyflwError",
    "RootLocus",
    "SchedulingError",
    "SchemaVersionError",
    "SimulationStillRunningError",
    "Simulator",
    "SolverError",
    "Subsystem",
    "UnknownBlockIdError",
    "UnknownBlockTypeError",
    "block",
    "bode",
    "eigenvalues",
    "is_stable",
    "linearize",
    "nyquist",
    "root_locus",
]
