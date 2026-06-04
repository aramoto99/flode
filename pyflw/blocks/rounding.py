"""SPEC-0013 / ADR-0059 (v5.6.0): Rounding ブロック (Wave 2 第 2 弾)。

整数化系の単項関数 (floor / ceil / round / trunc) を ``mode`` enum で
切り替える。``MathFunction`` (SPEC-0002) の enum パターンを踏襲するが、
整数化族と連続関数族は意味的に異なるため独立クラスとする (SPEC-0013 §背景)。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from ..core.block import Block
from ..exceptions import BlockSpecError


class Rounding(Block):
    """整数化単項関数 ``y = round_mode(u)``。

    Args:
        mode: 丸め方式
          - ``"floor"`` — `np.floor`、負方向への切り捨て
          - ``"ceil"`` — `np.ceil`、正方向への切り上げ
          - ``"round"`` (既定) — `np.round`、最近接整数 (banker's rounding)
          - ``"trunc"`` — `np.trunc`、0 方向への切り捨て

    Raises:
        BlockSpecError: ``mode`` が enum 値外。

    Note:
        ``nan`` / ``inf`` 入力は numpy 関数経由で `nan` / `inf` を伝播
        (ADR-0053 寛容方針)。
    """

    _ALLOWED_MODES: tuple[str, ...] = ("floor", "ceil", "round", "trunc")
    _param_enums = {"mode": _ALLOWED_MODES}

    def __init__(
        self,
        mode: str = "round",
        *,
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        if mode not in self._ALLOWED_MODES:
            raise BlockSpecError(
                f"Rounding: mode must be one of {self._ALLOWED_MODES}, got {mode!r}"
            )
        super().__init__(id=id, name=name, n_inputs=1, n_outputs=1)
        self.mode = mode
        self._params = {"mode": mode}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        val = float(np.asarray(u).reshape(-1)[0])
        if self.mode == "floor":
            r = float(np.floor(val))
        elif self.mode == "ceil":
            r = float(np.ceil(val))
        elif self.mode == "round":
            r = float(np.round(val))
        else:  # trunc
            r = float(np.trunc(val))
        return np.array([r])
