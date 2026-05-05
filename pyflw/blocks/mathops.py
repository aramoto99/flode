from __future__ import annotations

import numpy as np

from ..core.block import Block


class Gain(Block):
    def __init__(
        self,
        k: float = 1.0,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        super().__init__(id=id, name=name, n_inputs=1, n_outputs=1)
        self.k = float(k)

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.array([self.k * u[0]])


class Sum(Block):
    def __init__(
        self,
        signs: str = "++",
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        super().__init__(id=id, name=name, n_inputs=len(signs), n_outputs=1)
        self.signs = np.array([1.0 if s == "+" else -1.0 for s in signs])

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.array([float(np.dot(self.signs, u))])


class Product(Block):
    def __init__(
        self,
        n_inputs: int = 2,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        super().__init__(id=id, name=name, n_inputs=n_inputs, n_outputs=1)

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.array([float(np.prod(u))])
