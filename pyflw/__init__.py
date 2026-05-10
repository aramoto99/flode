# v0.21.0 (breaking change): legacy ``/api/v1/models/*`` REST と ``--model-dir``
# CLI を完全削除し、ADR-0041 (JupyterLab 流ローカルファイル直接編集) に統合。
# ``pyflw serve --workspace DIR`` 必須化、移行のため
# ``pyflw serve --migrate-models-to=DIR --legacy-models-dir=OLD`` を 1 リリース
# 限定で提供。frontend は ``selectedModelId`` 経路を全廃し ``selectedFilePath``
# 一本化。詳細は ADR-0038 §Amendments §(3) / ADR-0041。
__version__ = "0.21.0"

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
