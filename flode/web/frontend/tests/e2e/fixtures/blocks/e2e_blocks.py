"""E2E fixture: user blocks shown in the palette's workspace section (ADR-0081).

The E2E workspace is a copy of ``tests/e2e/fixtures``; the server reads ``blocks/`` from it
(the spec presses "Reload" so the copy made by the global setup is picked up).
"""

from typing import Any

import numpy as np

from flode import Block, block


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


#: Parts the E2E catalog search can find: (part, kind, stock).
_E2E_PARTS: tuple[tuple[str, str, int], ...] = (
    ("resistor", "passive", 120),
    ("capacitor", "passive", 80),
    ("inductor", "passive", 12),
    ("relay", "electromechanical", 5),
)


def _port_name(line: str) -> str:
    """The port name of one ``parts`` line (``"name: part"`` -> ``"name"``)."""
    return line.split(":", 1)[0].strip()


class E2ePartsBin(Block):
    """Sum one input per part (E2E fixture for parameter value search).

    Args:
        parts: One line per input port, ``"name: part"``.
    """

    block_dynamic_ports = True
    block_param_search = {"parts": "find_parts"}  # noqa: RUF012 - read as a class declaration

    def __init__(self, parts: list[str] = [], **kwargs: Any) -> None:  # noqa: B006
        super().__init__(n_inputs=len(parts), n_outputs=1, **kwargs)
        self.input_names = tuple(_port_name(line) for line in parts)
        self._params = {"parts": list(parts)}

    @classmethod
    def find_parts(cls, query: str, limit: int, current: list[str], **_: Any) -> dict[str, Any]:
        """Parts whose name or kind contains ``query``; names never clash with ``current``."""
        taken = {_port_name(line) for line in current}
        rows: list[dict[str, Any]] = []
        for part, kind, stock in _E2E_PARTS:
            if query.lower() not in f"{part} {kind}":
                continue
            name = part
            suffix = 2
            while name in taken:
                name = f"{part}_{suffix}"
                suffix += 1
            rows.append({"cells": [part, kind, stock], "value": f"{name}: {part}"})
        return {"columns": ["part", "kind", "stock"], "rows": rows}

    def output(self, t: float, x: Any, u: Any) -> Any:
        return np.array([float(np.sum(u))])
