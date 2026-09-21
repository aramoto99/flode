"""互換 re-export: ``flode.core.dtypes`` → :mod:`flode.core.signals` (ADR-0079 D-1)。

v0.62.0 で dtype 解決器は shape 解決と統合され ``flode.core.signals`` に移った。
SPEC-0027 / SPEC-0028 以来の公開名 (``resolve_dtypes`` / ``cast_value`` /
``DTypeResolution`` 等) はここから引き続き import できる (ADR-0038 の互換配慮)。
新規コードは ``flode.core.signals`` を直接 import すること。
"""

from __future__ import annotations

from .signals import (
    DTYPE_PARAM_VALUES,
    DTYPE_VOCABULARY,
    ISLAND_DTYPE,
    SCHEMA_VERSION,
    UNKNOWN,
    DTypeDiagnostic,
    DTypeResolution,
    DTypeSummary,
    PortKey,
    ResolveMode,
    SignalDiagnostic,
    SignalResolution,
    SignalSummary,
    cast_value,
    has_declared_dtype,
    has_shape_source,
    in_static_dtype_resolution,
    promote,
    reject_nested_dtype_declarations,
    resolve_dtypes,
    resolve_for_execution,
    resolve_signals,
)

__all__ = [
    "DTYPE_PARAM_VALUES",
    "DTYPE_VOCABULARY",
    "ISLAND_DTYPE",
    "SCHEMA_VERSION",
    "UNKNOWN",
    "DTypeDiagnostic",
    "DTypeResolution",
    "DTypeSummary",
    "PortKey",
    "ResolveMode",
    "SignalDiagnostic",
    "SignalResolution",
    "SignalSummary",
    "cast_value",
    "has_declared_dtype",
    "has_shape_source",
    "in_static_dtype_resolution",
    "promote",
    "reject_nested_dtype_declarations",
    "resolve_dtypes",
    "resolve_for_execution",
    "resolve_signals",
]
