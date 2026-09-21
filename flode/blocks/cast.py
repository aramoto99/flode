"""``Cast`` — 実 dtype 変換ブロック (SPEC-0028 / ADR-0077 SM-D)。

v0.56.0 で ``output_type`` (値の意味論、旧 SPEC-0026) は撤去され、型概念は
``dtype`` に一本化された。``Cast`` は**常に実変換する**ブロックであり、恒等
パススルー (旧 ``dtype="auto"``) は存在しない — 「置いたのに何も変わらない」
Cast を許さないため。

旧 ``output_type`` の等価機能は既存ブロックで表現する (schema 0.12 migration が
自動変換する対応):

* ``output_type="int"`` (偶数丸め) → :class:`~flode.blocks.rounding.Rounding`
  (``mode="round"``)
* ``output_type="bool"`` (``u != 0`` → 0/1) →
  :class:`~flode.blocks.mathops.CompareToZero` (``op="!="``)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from ..core.block import Block
from ..core.signals import DTYPE_VOCABULARY, cast_value
from ..exceptions import BlockSpecError
from ._elementwise import ElementwiseMixin


class Cast(ElementwiseMixin, Block):
    """実 dtype 変換 ``y = cast(u, dtype)``。

    出力は**実際にその numpy dtype** になる (SPEC-0028)。``dtype="float64"``
    (既定) も恒等ではなく実変換 (``astype``)。float → 整数は**ゼロ方向切り捨て**、
    nan → 0 / ±inf → 飽和は決定的 (規則の SSOT は
    :func:`flode.core.signals.cast_value`)。

    Cast を含むモデルは常に dtype 宣言モデルとして実行される
    (:func:`flode.core.signals.has_declared_dtype`)。

    Args:
        dtype: 出力 dtype。``"float64"`` (既定) / ``"bool"`` / ``"uint8"`` /
            ``"int32"`` / ``"int64"``。``"auto"`` は存在しない (Cast は常に変換)。

    Raises:
        BlockSpecError: ``dtype`` が語彙外。
    """

    _param_enums = {"dtype": DTYPE_VOCABULARY}

    def __init__(
        self,
        dtype: str = "float64",
        *,
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        if dtype not in DTYPE_VOCABULARY:
            raise BlockSpecError(f"Cast: dtype must be one of {DTYPE_VOCABULARY}, got {dtype!r}")
        super().__init__(id=id, name=name, n_inputs=1, n_outputs=1)
        self.dtype = dtype
        self._params = {"dtype": dtype}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        # 実 dtype 変換 (SPEC-0028 §2.2)。float() を経由しないことで
        # int64 の精度 (> 2^53) を守る。
        return cast_value(np.asarray(u).reshape(-1)[:1], self.dtype)

    def _kernel(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        # cast_value は shape 保存なのでテンソルでもそのまま動く
        return (cast_value(np.asarray(u[0]), self.dtype),)
