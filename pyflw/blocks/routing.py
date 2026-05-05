"""信号ルーティング系ブロック。

Phase 1 では ``Switch`` のみ実装する。``Mux`` / ``Demux`` は信号モデル
(各ポートがスカラーかベクトルか) の設計が絡むため Phase 2 で再設計予定。
"""

from __future__ import annotations

import numpy as np

from ..core.block import Block
from ..exceptions import BlockSpecError


class Switch(Block):
    """3 入力スイッチ ``y = u[0] if control op threshold else u[2]``。

    入力ポート: ``[input_true, control, input_false]`` の 3 つ。
    ``control`` (= ``u[1]``) が閾値判定をパスすれば ``input_true``、
    そうでなければ ``input_false`` を出力する。

    Args:
        threshold: 比較しきい値。
        criterion: 比較演算子。``">="`` (default) / ``">"`` / ``"!="``。
            Simulink Switch の "u2 >= Threshold" / "u2 > Threshold" / "u2 ~= 0" 相当。

    Note:
        ``control`` が ``NaN`` のときは Python の比較規則 (NaN との比較は常に
        ``False``、ただし ``!=`` は ``True``) に従い ``input_false`` 側 (``"!="``
        は ``input_true`` 側) が選ばれる。NaN が伝播してきた場合の挙動として
        意図的にこの仕様のまま据え置く (デバッグ時の追跡しやすさは Phase 2 で
        検討)。
    """

    _ALLOWED_CRITERIA = (">=", ">", "!=")

    def __init__(
        self,
        threshold: float = 0.0,
        criterion: str = ">=",
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if criterion not in self._ALLOWED_CRITERIA:
            raise BlockSpecError(
                f"Switch: criterion must be one of {self._ALLOWED_CRITERIA}, got {criterion!r}"
            )
        super().__init__(id=id, name=name, n_inputs=3, n_outputs=1)
        self.threshold = float(threshold)
        self.criterion = criterion
        self._params = {"threshold": self.threshold, "criterion": criterion}

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        control = float(u[1])
        if self.criterion == ">=":
            select_true = control >= self.threshold
        elif self.criterion == ">":
            select_true = control > self.threshold
        else:  # "!="
            select_true = control != self.threshold
        return np.array([float(u[0]) if select_true else float(u[2])])
