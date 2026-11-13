"""E2E fixture: user blocks shown in the palette's workspace section (ADR-0081).

The E2E workspace is a copy of ``tests/e2e/fixtures``; the server reads ``blocks/`` from it
(the spec presses "Reload" so the copy made by the global setup is picked up).
"""

from flode import block


# ``mypy flode`` (strict) also reaches this file; ``block(...)`` with arguments is untyped
@block(  # type: ignore[untyped-decorator]
    category="E2E filters",
    display_name="E2E Scaler",
    choices={"mode": ("fast", "slow")},
)
def e2e_scaler(t: float, u: float, *, k: float = 2.0, mode: str = "fast") -> float:
    """Scale the input (E2E fixture).

    Args:
        k: Gain applied to the input.
        mode: How quickly the output follows the input.
    """
    return k * u


@block
def e2e_offset(t: float, u: float, *, offset: float = 1.0) -> float:
    """Add a constant offset (E2E fixture, no category).

    Args:
        offset: Value added to the input.
    """
    return u + offset
