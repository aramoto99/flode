"""離散時間ブロック。

Phase 1 では動作確認用の `UnitDelay` のみ実装する。
`Memory`, `DiscreteIntegrator`, `ZeroOrderHold` 等は後続 PR で追加予定。
"""

from __future__ import annotations

import numpy as np

from ..core.block import Block


class UnitDelay(Block):
    """1 サンプル遅延 ``y[k] = x[k] = u[k-1]``。

    出力は現状態 (= 前ステップの入力)、状態更新は現入力をそのまま保持。
    ``direct_feedthrough=False`` なので閉ループ内で代数ループを切る用途にも使える。

    Args:
        sample_time: サンプル周期 [s]。``> 0`` 必須 (継承 ``-1.0`` も可)。
        x0: 初期状態 (= t=0 での出力値)。
    """

    def __init__(
        self,
        *,
        sample_time: float,
        x0: float = 0.0,
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(
            id=id,
            name=name,
            n_inputs=1,
            n_outputs=1,
            n_states=1,
            direct_feedthrough=False,
            sample_time=sample_time,
        )
        self.x0 = np.array([float(x0)])

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.array([x[0]])

    def update(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.array([u[0]])
