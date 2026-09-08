"""``Cast`` — 型変換ブロック (SPEC-0026 値の意味論 / SPEC-0028 実 dtype)。

2 系統の「型」param を持つ (併用は不可、SPEC-0028 Q2):

* **`output_type`** (SPEC-0026 / ADR-0076、値の意味論): 出力の numpy dtype は
  float64 のまま、値だけを対象の型で表現可能な形に正規化する。

  - ``"float"`` (既定) — 恒等。**置いただけでは何も変換しない** (誤挿入で値が
    変わらない安全側の意図した仕様)
  - ``"int"`` — 最近接整数 (偶数丸め、``np.round``)。丸め方式を選びたい場合は
    :class:`~flode.blocks.rounding.Rounding` を使う (SPEC-0026 §1.2)
  - ``"bool"`` — ``u != 0`` で ``1.0`` / ``0.0`` に正規化

* **`dtype`** (SPEC-0028 / ADR-0077 SM-D、実 dtype): 出力が**実際にその numpy
  dtype** になる。``dtype="float64"`` は恒等ではなく**実変換** (``astype``)。
  float → 整数は**ゼロ方向切り捨て** (``output_type="int"`` の偶数丸めとは別物)、
  nan → 0 / ±inf → 飽和は決定的 (規則の SSOT は
  :func:`flode.core.dtypes.cast_value`)。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from ..core.block import Block
from ..core.dtypes import DTYPE_PARAM_VALUES, cast_value
from ..exceptions import BlockSpecError

#: ``output_type`` の許可値 (SPEC-0026 §確定事項 1: float / int / bool の 3 種のみ。
#: 実 dtype が必要な場合は SPEC-0028 の ``dtype`` param を使う)。
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


def validate_dtype_params(
    class_name: str, output_type: str, dtype: str
) -> None:
    """``output_type`` × ``dtype`` の検証 (SPEC-0028 Q2、Cast / Constant 共有)。

    - 各 param の語彙検証 (語彙外は ``BlockSpecError``)
    - 併用禁止: ``dtype != "auto"`` かつ ``output_type != "float"`` は拒否
      (``output_type="float"`` は既定値 = 未指定と同義なので許す)

    Raises:
        BlockSpecError: 語彙外、または併用。
    """
    if output_type not in OUTPUT_TYPES:
        raise BlockSpecError(
            f"{class_name}: output_type must be one of {OUTPUT_TYPES}, "
            f"got {output_type!r}"
        )
    if dtype not in DTYPE_PARAM_VALUES:
        raise BlockSpecError(
            f"{class_name}: dtype must be one of {DTYPE_PARAM_VALUES}, "
            f"got {dtype!r}"
        )
    if dtype != "auto" and output_type != "float":
        raise BlockSpecError(
            f"{class_name}: 'dtype' (numpy dtype semantics, SM-D / SPEC-0028) and "
            "'output_type' (value semantics, ADR-0076) cannot be combined. "
            "Use one of them."
        )


class Cast(Block):
    """型変換 ``y = cast(u)``。

    Args:
        output_type: 値の意味論 (SPEC-0026)。``"float"`` (既定、恒等) /
            ``"int"`` (最近接偶数丸め) / ``"bool"`` (``u != 0`` で 0/1)。
        dtype: 実 dtype (SPEC-0028)。``"auto"`` (既定、宣言しない) /
            ``"float64"`` / ``"bool"`` / ``"int32"`` / ``"int64"`` / ``"uint8"``。
            ``"auto"`` 以外を選ぶと出力が実際にその dtype になる
            (``float64`` も恒等ではなく実変換)。``output_type`` とは併用不可。

    Raises:
        BlockSpecError: param が許可値の外、または ``output_type`` と ``dtype``
            の併用 (Q2)。
    """

    _param_enums = {"output_type": OUTPUT_TYPES, "dtype": DTYPE_PARAM_VALUES}

    def __init__(
        self,
        output_type: str = "float",
        dtype: str = "auto",
        *,
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        validate_dtype_params("Cast", output_type, dtype)
        super().__init__(id=id, name=name, n_inputs=1, n_outputs=1)
        self.output_type = output_type
        self.dtype = dtype
        self._params = {"output_type": self.output_type}
        # Q1: "auto" は保存 JSON に出さない (= 既存モデルの diff が最小)
        if dtype != "auto":
            self._params["dtype"] = dtype

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        if self.dtype != "auto":
            # 実 dtype 変換 (SPEC-0028 §2.2)。float() を経由しないことで
            # int64 の精度 (> 2^53) を守る。
            return cast_value(np.asarray(u).reshape(-1)[:1], self.dtype)
        val = float(np.asarray(u).reshape(-1)[0])
        return np.array([apply_value_semantics(val, self.output_type)])
