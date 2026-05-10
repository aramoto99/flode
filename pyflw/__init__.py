# v0.22.0 (minor、後方互換): ADR-0042 採択。``simulator.t_end`` を ``number | "inf"``
# Union 化し、Toolbar Stop Time フィールドに ``"inf"`` (case-insensitive) を入力する
# と Stop ボタンを押すまで実行する Simulink 互換 unbounded run を実現。
# ``Simulator.run`` の SM-A / SM-B ループを ``while True`` に refactor、各ステップ
# は ``solve_ivp`` を有限 ``(t, t+dt_base)`` 区間で呼び続けるため SciPy
# ``t_bound=inf`` 仕様未対応問題は構造的に回避。Scope は ``buffer_mode``
# (``"ring"`` default / ``"bounded"`` / ``"unbounded"``) と ``buffer_capacity=100_000``
# を獲得、frontend ``scopeBuffer`` も ``MAX_SAMPLES=100_000`` で ring 化、長時間
# 実行で OOM を防ぐ。ADR-0023 §Decision §(2) を部分 amend。
__version__ = "0.22.0"

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
