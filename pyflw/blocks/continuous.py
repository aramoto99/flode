from __future__ import annotations

import numpy as np

from ..core.block import Block


class Integrator(Block):
    """連続時間積分器 ``y = x``、``x_dot = u``。

    ``direct_feedthrough=False`` (出力は状態 ``x`` のみ参照) なので、閉ループ内
    の代数ループを切る用途に使える。

    Args:
        x0: 初期状態 ``x(0)``。
    """

    def __init__(
        self,
        x0: float = 0.0,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        super().__init__(
            id=id,
            name=name,
            n_inputs=1,
            n_outputs=1,
            n_states=1,
            direct_feedthrough=False,
        )
        self.x0 = np.array([float(x0)])

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.array([x[0]])

    def derivative(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.array([u[0]])
