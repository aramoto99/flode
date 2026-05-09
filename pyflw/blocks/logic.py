"""論理・関係演算ブロック。

Phase 1 では ``RelationalOperator`` (比較) と ``LogicalOperator`` (論理) を提供する。
信号は ``float`` のまま扱い、論理値は ``0.0`` / ``1.0`` で表現する
(Simulink の Boolean 信号モードは Phase 2 以降)。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from ..core.block import Block
from ..exceptions import BlockSpecError


class RelationalOperator(Block):
    """2 入力の比較 ``y = u[0] op u[1]``。

    Args:
        operator: ``"<"``, ``"<="``, ``"=="``, ``"!="``, ``">="``, ``">"`` のいずれか。
    """

    _ALLOWED_OPS = ("<", "<=", "==", "!=", ">=", ">")
    # ADR-0039 follow-up (v0.15.0): GUI ParameterPanel が enum select を出すヒント
    _param_enums = {"operator": _ALLOWED_OPS}

    def __init__(
        self,
        operator: str = "<",
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if operator not in self._ALLOWED_OPS:
            raise BlockSpecError(
                f"RelationalOperator: operator must be one of {self._ALLOWED_OPS}, got {operator!r}"
            )
        super().__init__(id=id, name=name, n_inputs=2, n_outputs=1)
        self.operator = operator
        self._params = {"operator": operator}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        a, b = float(u[0]), float(u[1])
        op = self.operator
        if op == "<":
            r = a < b
        elif op == "<=":
            r = a <= b
        elif op == "==":
            r = a == b
        elif op == "!=":
            r = a != b
        elif op == ">=":
            r = a >= b
        else:  # ">"
            r = a > b
        return np.array([1.0 if r else 0.0])


class LogicalOperator(Block):
    """論理演算ブロック。入力は ``0.0`` / 非 0 (= True 扱い) で解釈。

    Args:
        operator: ``"AND"``, ``"OR"``, ``"NOT"``, ``"XOR"``, ``"NAND"``, ``"NOR"``。
        n_inputs: 入力ポート数。``"NOT"`` は ``1`` 固定、その他は 2 以上。
    """

    _BINARY_OPS = ("AND", "OR", "XOR", "NAND", "NOR")
    _UNARY_OPS = ("NOT",)
    # ADR-0039 follow-up (v0.15.0): GUI ParameterPanel が enum select を出すヒント
    _param_enums = {"operator": _UNARY_OPS + _BINARY_OPS}

    def __init__(
        self,
        operator: str = "AND",
        n_inputs: int = 2,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if operator in self._UNARY_OPS:
            if n_inputs != 1:
                raise BlockSpecError(
                    f"LogicalOperator: {operator} requires n_inputs=1, got {n_inputs}"
                )
        elif operator in self._BINARY_OPS:
            if n_inputs < 2:
                raise BlockSpecError(
                    f"LogicalOperator: {operator} requires n_inputs >= 2, got {n_inputs}"
                )
        else:
            raise BlockSpecError(
                f"LogicalOperator: unknown operator {operator!r}; "
                f"allowed: {self._UNARY_OPS + self._BINARY_OPS}"
            )
        super().__init__(id=id, name=name, n_inputs=n_inputs, n_outputs=1)
        self.operator = operator
        self._params = {"operator": operator, "n_inputs": int(n_inputs)}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        op = self.operator
        bools = [bool(v) for v in u]
        if op == "NOT":
            r = not bools[0]
        elif op == "AND":
            r = all(bools)
        elif op == "OR":
            r = any(bools)
        elif op == "XOR":
            r = sum(1 for b in bools if b) % 2 == 1
        elif op == "NAND":
            r = not all(bools)
        else:  # "NOR"
            r = not any(bools)
        return np.array([1.0 if r else 0.0])
