from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from ..core.block import Block

if TYPE_CHECKING:
    from matplotlib.axes import Axes


class Scope(Block):
    def __init__(
        self,
        n_inputs: int = 1,
        labels: list[str] | None = None,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        super().__init__(id=id, name=name, n_inputs=n_inputs, n_outputs=0)
        self.labels = labels or [f"in{i}" for i in range(n_inputs)]
        self.times: list[float] = []
        self._values: list[np.ndarray] = []

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.zeros(0)

    def reset(self) -> None:
        self.times = []
        self._values = []

    def record(self, t: float, u: np.ndarray) -> None:
        self.times.append(float(t))
        self._values.append(np.asarray(u, dtype=float).copy())

    @property
    def values(self) -> np.ndarray:
        if not self._values:
            return np.empty((0, self.n_inputs))
        return np.array(self._values)

    def plot(self, ax: Axes | None = None, show: bool = False) -> Any:
        import matplotlib.pyplot as plt

        created = ax is None
        if created:
            _, ax = plt.subplots()
        assert ax is not None
        t = np.array(self.times)
        v = self.values
        for i in range(v.shape[1]):
            ax.plot(t, v[:, i], label=self.labels[i])
        ax.set_xlabel("t")
        ax.legend()
        ax.grid(True)
        ax.set_title(self.id or "Scope")
        if show:
            plt.show()
        return ax
