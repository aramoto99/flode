"""``Cast`` — 値の意味論の型変換ブロック (SPEC-0026 / ADR-0076)。

flode の信号線は全経路 float64 であり dtype を持たない (ADR-0076)。本ブロックの
「型変換」は **値の意味論 (value semantics)** である: 出力の numpy dtype は
float64 のまま、値だけを対象の型で表現可能な形に正規化する。

* ``"float"`` (既定) — 恒等。**置いただけでは何も変換しない** (誤挿入で値が
  変わらない安全側の意図した仕様。変換したい型を ``output_type`` で選ぶ)
* ``"int"`` — 最近接整数 (偶数丸め、``np.round``)。切り捨て / 切り上げ等の
  **丸め方式を選びたい場合は** :class:`~flode.blocks.rounding.Rounding` を使う
  (型変換 = 丸め方式固定、丸め演算 = 方式選択、という棲み分け。SPEC-0026 §1.2)
* ``"bool"`` — ``u != 0`` で ``1.0`` / ``0.0`` に正規化。nan / ±inf も 1.0
  (「0 以外は真」の唯一の規則に例外を作らない。SPEC-0026 §確定事項 3)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from ..core.block import Block
from ..exceptions import BlockSpecError

#: ``output_type`` の許可値 (SPEC-0026 §確定事項 1: float / int / bool の 3 種のみ。
#: 固定幅整数や overflow mode はスコープ外 — 必要になれば enum 拡張で非破壊に足せる)。
OUTPUT_TYPES = ("float", "int", "bool")


def apply_value_semantics(value: float, output_type: str) -> float:
    """値の意味論の変換規則 (SPEC-0026 §1.1)。``Cast`` と ``Constant`` で共有する。

    2 箇所から呼ばれ、両者が食い違うと仕様バグになるため共有が正当 (SPEC §2.3)。

    * ``"float"``: 恒等
    * ``"int"``: ``np.round`` (最近接偶数丸め)。nan / ±inf は伝播
      (ADR-0053 の寛容方針)
    * ``"bool"``: ``value != 0`` で 1.0 / 0.0。nan は ``!= 0`` が真なので **1.0**

    Args:
        value: 入力値。
        output_type: :data:`OUTPUT_TYPES` のいずれか (検証は呼び出し側の責務)。

    Returns:
        変換後の値 (float64 のスカラー)。
    """
    if output_type == "int":
        return float(np.round(value))
    if output_type == "bool":
        return 1.0 if value != 0.0 else 0.0
    return float(value)


class Cast(Block):
    """型変換 ``y = cast(u)`` (値の意味論、SPEC-0026)。

    Args:
        output_type: ``"float"`` (既定、恒等 = 入力をそのまま通す) /
            ``"int"`` (最近接偶数丸め) / ``"bool"`` (``u != 0`` で 0/1)。

    Raises:
        BlockSpecError: ``output_type`` が許可値の外。
    """

    _param_enums = {"output_type": OUTPUT_TYPES}

    def __init__(
        self,
        output_type: str = "float",
        *,
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        if output_type not in OUTPUT_TYPES:
            raise BlockSpecError(
                f"Cast: output_type must be one of {OUTPUT_TYPES}, got {output_type!r}"
            )
        super().__init__(id=id, name=name, n_inputs=1, n_outputs=1)
        self.output_type = output_type
        self._params = {"output_type": self.output_type}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        val = float(np.asarray(u).reshape(-1)[0])
        return np.array([apply_value_semantics(val, self.output_type)])
