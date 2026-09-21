"""論理・関係演算ブロック。

Phase 1 では ``RelationalOperator`` (比較) と ``LogicalOperator`` (論理) を提供する。
信号は ``float`` のまま扱い、論理値は ``0.0`` / ``1.0`` で表現する
(リファレンスツールの Boolean 信号モード相当は Phase 2 以降)。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from ..core.block import Block
from ..exceptions import BlockSpecError
from ._elementwise import ElementwiseMixin


class RelationalOperator(ElementwiseMixin, Block):
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
        # SM-D Stage 1 (SPEC-0028 §3.6): float() を外し int64 同士の厳密比較を
        # 守る (float64 入力では比較結果不変 = 既存挙動に影響なし)
        a, b = u[0], u[1]
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

    def _kernel(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        # output と同じく float() を経由しない要素ごと比較 (int64 の厳密比較を守る)
        a, b = np.asarray(u[0]), np.asarray(u[1])
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
        return (np.asarray(np.where(r, 1.0, 0.0), dtype=float),)


class LogicalOperator(ElementwiseMixin, Block):
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

    def _kernel(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        op = self.operator
        # 非 0 (nan 含む) = True。共通 shape に揃えて (n, *shape) に積む
        bools = np.stack(np.broadcast_arrays(*[np.asarray(v) != 0 for v in u]))
        if op == "NOT":
            r = ~bools[0]
        elif op == "AND":
            r = np.all(bools, axis=0)
        elif op == "OR":
            r = np.any(bools, axis=0)
        elif op == "XOR":
            r = np.sum(bools, axis=0) % 2 == 1
        elif op == "NAND":
            r = ~np.all(bools, axis=0)
        else:  # "NOR"
            r = ~np.any(bools, axis=0)
        return (np.asarray(np.where(r, 1.0, 0.0), dtype=float),)
