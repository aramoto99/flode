from __future__ import annotations

import numpy as np

from ..core.block import Block


class Integrator(Block):
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
