from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from ..core.block import Block
from ..exceptions import BlockSpecError

if TYPE_CHECKING:
    from matplotlib.axes import Axes


class Scope(Block):
    """シミュレーション中の信号値を時系列で記録し、``plot()`` で可視化する。

    各時刻 ``t`` の入力 ``u`` を ``record(t, u)`` で蓄積する。``values`` プロパティ
    で形状 ``(n_samples, n_inputs)`` の ndarray を取得できる。

    Args:
        n_inputs: 記録する信号数 (= 入力ポート数)。
        labels: 各信号のラベル (省略時は ``in0``, ``in1`` ...)。``plot`` で凡例に使う。
    """

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
        self._params = {
            "n_inputs": int(n_inputs),
            "labels": self.labels,
        }

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


class Terminator(Block):
    """入力を消費するだけで何もしない終端ブロック。

    Simulink の Terminator 相当。使われない出力ポートを終端させて未接続警告を
    避ける用途で使う。

    Args:
        n_inputs: 入力ポート数 (>= 1)。
    """

    def __init__(
        self,
        n_inputs: int = 1,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if n_inputs < 1:
            raise BlockSpecError(f"Terminator: n_inputs must be >= 1, got {n_inputs}")
        super().__init__(id=id, name=name, n_inputs=n_inputs, n_outputs=0)
        self._params = {"n_inputs": int(n_inputs)}

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.zeros(0)
