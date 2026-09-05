# v0.27.0 (minor、後方互換): ADR-0045 採択。Workspace convergence Stage 1 =
# multi-pane split。`<main>` 内 Diagram + Scope を ``react-resizable-panels``
# のネスト split で任意配置可能に、SplitTree state は localStorage に
# ``flode.workspace_layout.<hash>.<b64url(path)>`` キーで永続化。DiagramCanvas
# は React Portal で投影することで SplitTree 再構造でも viewport を保持
# (= v0.26.12 規律継承)。既存 ``ScopePanelContainer`` (react-rnd float、
# ADR-0044) は docked split と並存。Phase 6c (Workspace
# convergence) Stage 1 として ADR-0040 §Amendments §(1) で位置付け、Stage 2 /
# 3 (= activity bar + Launcher、drag-to-split-tab) は後続 ADR で順次着手。
__version__ = "0.53.5"

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
    FlodeError,
    LibraryEntryNotFoundError,
    LibraryFileError,
    ModelLoadError,
    ModelSerializationError,
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
from .subsystems import Enable, Inport, Outport, Subsystem, Trigger

__all__ = [
    "AlgebraicLoopError",
    "Block",
    "BlockSpecError",
    "BodeResponse",
    "Enable",
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
    "FlodeError",
    "RootLocus",
    "SchedulingError",
    "SchemaVersionError",
    "SimulationStillRunningError",
    "Simulator",
    "SolverError",
    "Subsystem",
    "Trigger",
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
