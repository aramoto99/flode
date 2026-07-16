"""Atomic Subsystem (ADR-0009) + Subsystem behavior modifier control blocks
(ADR-0058)。

ADR-0036 で導入された ``TriggeredSubsystem`` クラスは ADR-0058 で
``Subsystem`` + 内部 ``Trigger`` block に一般化され、v0.38.0 で削除された。
旧 schema 0.8 JSON ファイルは ``flode.core.persistence`` の自動 migration
で新形式にロードされる。
"""

from .control_blocks import Enable, Trigger
from .ports import Inport, Outport
from .subsystem import Subsystem

__all__ = [
    "Enable",
    "Inport",
    "Outport",
    "Subsystem",
    "Trigger",
]
