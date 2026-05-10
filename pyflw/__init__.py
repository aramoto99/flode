# v0.20.6 (機能追加): Simulink 流の「配線をクリック → ドラッグ → ブロックに
# ドロップ」で分岐配線を作る機能。Custom Edge (BranchableEdge) で edge 上の
# pointerdown を捕捉、window mousemove で追従線を描画、mouseup の hit testing
# で着地点ブロックの input port[0] へ枝分かれ edge を追加。
__version__ = "0.20.6"

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
    LibraryEntryNotFoundError,
    LibraryFileError,
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
from .libraries import (
    Library,
    LibraryEntry,
    export_subsystem_to_library,
    load_library,
    validate_library,
)
from .subsystems import Inport, Outport, Subsystem, TriggeredSubsystem

__all__ = [
    "AlgebraicLoopError",
    "Block",
    "BlockSpecError",
    "BodeResponse",
    "Inport",
    "Library",
    "LibraryEntry",
    "LibraryEntryNotFoundError",
    "LibraryFileError",
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
    "TriggeredSubsystem",
    "UnknownBlockIdError",
    "UnknownBlockTypeError",
    "block",
    "bode",
    "eigenvalues",
    "export_subsystem_to_library",
    "is_stable",
    "linearize",
    "load_library",
    "nyquist",
    "root_locus",
    "validate_library",
]
