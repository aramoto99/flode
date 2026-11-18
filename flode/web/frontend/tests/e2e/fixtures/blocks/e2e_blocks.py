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


@block(  # type: ignore[untyped-decorator]
    display_name="E2E Pair",
    output_names=("alpha", "beta"),
)
def e2e_pair(t: float) -> tuple[float, float]:
    """Two constant outputs with named ports (E2E fixture for signal names, ADR-0087)."""
    return 1.0, 2.0


#: Parts the E2E catalog search can find: (part, kind, stock).
_E2E_PARTS: tuple[tuple[str, str, int], ...] = (
    ("resistor", "passive", 120),
    ("capacitor", "passive", 80),
    ("inductor", "passive", 12),
    ("relay", "electromechanical", 5),
)


_E2E_STOCK: dict[str, int] = {part: stock for part, _kind, stock in _E2E_PARTS}


def _port_name(line: str) -> str:
    """The port name of one ``parts`` line (``"name: part"`` -> ``"name"``)."""
    return line.split(":", 1)[0].strip()


def _line_parts(line: str) -> list[str] | None:
    """The parts of one line (``"name: a+b"`` -> ``["a", "b"]``), or ``None`` if malformed."""
    name, sep, spec = line.partition(":")
    if not sep or not name.strip() or not spec.strip():
        return None
    return [p.strip() for p in spec.split("+")]


def _free_name(base: str, rows: list[str], index: int | None) -> str:
    """``base``, or ``base_2`` / ``base_3`` ... so that it does not clash with other rows."""
    taken = {_port_name(line) for i, line in enumerate(rows) if i != index}
    name = base
    suffix = 2
    while name in taken:
        name = f"{base}_{suffix}"
        suffix += 1
    return name


class E2ePartsBin(Block):
    """Sum one input per part (E2E fixture for parameter value search).

    ``E2ePartsTable`` below adds the row editor; this class keeps only the search so that
    the search button stays visible for the search E2E (the row editor hides it).

    Args:
        parts: One line per input port, ``"name: part"`` (a kit is ``"name: part+part"``).
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

    @classmethod
    def edit_parts(cls, action: str, params: dict[str, Any], **kw: Any) -> Any:
        """Row editor of ``parts``: one row per input port (ADR-0086, experimental)."""
        match action:
            case "describe":
                return cls._describe(kw["rows"])
            case "form":
                return cls._form(kw["row"])
            case "compose":
                return cls._compose(kw["variant"], kw["values"], kw["rows"], kw["index"])
            case "search":
                # The "parts" pick field of a kit: the value is the part name itself
                query = str(kw["query"]).lower()
                return {
                    "columns": ["part", "kind", "stock"],
                    "rows": [
                        {"cells": [part, kind, stock], "value": part}
                        for part, kind, stock in _E2E_PARTS
                        if query in f"{part} {kind}"
                    ],
                }
            case _:
                return NotImplemented

    @staticmethod
    def _describe(rows: list[str]) -> dict[str, Any]:
        described: list[dict[str, Any]] = []
        for line in rows:
            parts = _line_parts(line)
            if parts is None:
                described.append(
                    {"cells": [line, None, None], "error": "write the line as 'name: part'"}
                )
                continue
            unknown = [p for p in parts if p not in _E2E_STOCK]
            described.append(
                {
                    "cells": [
                        _port_name(line),
                        "+".join(parts),
                        None if unknown else min(_E2E_STOCK[p] for p in parts),
                    ],
                    "error": f"unknown part: {', '.join(unknown)}" if unknown else None,
                }
            )
        return {"columns": ["name", "part", "stock"], "rows": described, "ports": "input"}

    @staticmethod
    def _form(row: str | None) -> dict[str, Any]:
        variants = [
            {
                "id": "part",
                "label": "Catalog part",
                "fields": [
                    {"key": "name", "label": "Name", "kind": "text"},
                    {
                        "key": "part",
                        "label": "Part",
                        "kind": "choice",
                        "options": [{"value": p, "label": p} for p in _E2E_STOCK],
                    },
                ],
            },
            {
                "id": "kit",
                "label": "Kit of parts",
                "fields": [
                    {"key": "name", "label": "Name", "kind": "text"},
                    {"key": "parts", "label": "Parts", "kind": "pick"},
                ],
            },
            {
                "id": "raw",
                "label": "Write the line",
                "fields": [{"key": "line", "label": "Line", "kind": "text"}],
            },
        ]
        parts = _line_parts(row) if row is not None else None
        values: dict[str, Any]
        if row is None:
            variant, values = "part", {}
        elif parts is not None and len(parts) == 1 and parts[0] in _E2E_STOCK:
            variant, values = "part", {"name": _port_name(row), "part": parts[0]}
        elif parts is not None and all(p in _E2E_STOCK for p in parts):
            variant, values = "kit", {"name": _port_name(row), "parts": parts}
        else:
            variant, values = "raw", {"line": row}
        return {"variants": variants, "variant": variant, "values": values}

    @staticmethod
    def _compose(
        variant: str, values: dict[str, Any], rows: list[str], index: int | None
    ) -> dict[str, str]:
        if variant == "raw":
            line = str(values.get("line", "")).strip()
            if not line:
                raise ValueError("write the line")
            return {"row": line}
        if variant == "kit":
            parts = [str(p) for p in values.get("parts", [])]
            if not parts:
                raise ValueError("pick at least one part")
            base = "kit"
        elif variant == "part":
            parts = [str(values.get("part", ""))]
            if parts[0] not in _E2E_STOCK:
                raise ValueError(f"unknown part: {parts[0]}")
            base = parts[0]
        else:
            raise ValueError(f"unknown kind of row: {variant}")
        name = str(values.get("name", "")).strip() or _free_name(base, rows, index)
        return {"row": f"{name}: {'+'.join(parts)}"}

    def output(self, t: float, x: Any, u: Any) -> Any:
        return np.array([float(np.sum(u))])


class E2ePartsTable(E2ePartsBin):
    """``E2ePartsBin`` edited as a table with an edit dialog (E2E fixture for the row editor).

    Args:
        parts: One line per input port, ``"name: part"`` (a kit is ``"name: part+part"``).
    """

    block_param_rows = {"parts": "edit_parts"}  # noqa: RUF012 - read as a class declaration
