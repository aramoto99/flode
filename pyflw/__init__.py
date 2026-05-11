# v0.24.0 (minor、後方互換): ADR-0044 採択。Scope 表示 + プロット設定 + floating panel:
# (1) Canvas / Scope エリアを ``react-resizable-panels`` で drag resize 可能に、
# (2) per-Scope プロット設定 (Y/X 軸 auto/manual/log、凡例位置、グリッド、
# per-signal 線色 / 線幅) を gear UI で編集、永続化先は ``.flw.json`` の
# ``scope_settings`` (= モデル単位、git diff で追跡可、schema 0.8 維持)、
# (3) Scope ブロックダブルクリックで ``react-rnd`` の floating panel が開く
# (= Stop 後保持・複数同時・モデル切替で全閉じ・位置サイズは localStorage 永続)。
# 新規依存 ``react-resizable-panels`` / ``react-rnd`` / ``react-colorful``。
# ADR-0023 §Decision §(7) の 8 色固定を「user override 可、未設定時 fallback」に amend。
__version__ = "0.26.6"

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
