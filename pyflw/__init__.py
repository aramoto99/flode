# v0.23.0 (minor、後方互換): ADR-0043 採択。ワークスペース機能強化:
# (a) 前回 active file の自動復元 (= localStorage)、(b) Recent Files メニュー
# (= workspace 単位、上限 10)、(c) 複数ファイル同時編集 (= TabStrip N タブ +
# Ctrl+Tab / Ctrl+Shift+Tab + middle-click close)、(d) ファイル / 内容検索
# (= rapidfuzz fuzzy path + substring content、Ctrl+P / Ctrl+Shift+F、backend
# `/api/v1/files/search`、`.gitignore` 尊重)。新規 backend endpoint
# `/api/v1/files/workspace_info`、新規依存 `rapidfuzz` / `pathspec`。
__version__ = "0.23.0"

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
