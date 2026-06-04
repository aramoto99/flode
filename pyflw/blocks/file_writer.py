"""SPEC-0016 / ADR-0066 (v0.39.0): FileWriter sink ブロック (データエクスポート)。

Scope と同じ ``record`` / ``times`` / ``values`` / ``labels`` インタフェースを
持ち、加えて ``save_npz`` / ``save_csv`` でファイル書き出し API を提供する。
ユーザーは ``sim.run()`` 後に明示的に save を呼ぶ。
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from ..core.block import Block
from ..exceptions import BlockSpecError


class FileWriter(Block):
    """シミュレーション結果をファイル (npz / csv) に出力する sink ブロック。

    Args:
        n_inputs: 入力ポート数 (>= 1)。
        labels: 各信号の列名 (省略時は ``in0``, ``in1`` ...)。長さは ``n_inputs`` と一致必須。

    Raises:
        BlockSpecError: ``n_inputs < 1`` または ``labels`` の長さ不一致。

    Example:
        >>> sim = Simulator(t_end=1.0, dt=0.01)
        >>> sim.add(Sine(amplitude=1.0, id="src"))
        >>> sim.add(FileWriter(n_inputs=1, labels=["sine"], id="fw"))
        >>> sim.connect("src", "fw")
        >>> sim.run()
        >>> sim.get_block("fw").save_npz("output.npz")
        >>> sim.get_block("fw").save_csv("output.csv")
    """

    def __init__(
        self,
        n_inputs: int = 1,
        labels: list[str] | None = None,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if n_inputs < 1:
            raise BlockSpecError(f"FileWriter: n_inputs must be >= 1, got {n_inputs}")
        if labels is not None and len(labels) != n_inputs:
            raise BlockSpecError(
                f"FileWriter: len(labels)={len(labels)} must equal n_inputs={n_inputs}"
            )
        super().__init__(id=id, name=name, n_inputs=n_inputs, n_outputs=0)
        self.labels: list[str] = labels or [f"in{i}" for i in range(n_inputs)]
        self.times: list[float] = []
        self._values: list[npt.NDArray[Any]] = []
        self._params: dict[str, Any] = {
            "n_inputs": int(n_inputs),
            "labels": self.labels,
        }

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.zeros(0)

    def reset(self) -> None:
        """``Simulator.run()`` 開始時の lifecycle hook。バッファをクリア。"""
        self.times = []
        self._values = []

    def record(self, t: float, u: npt.NDArray[Any]) -> None:
        """Simulator が各 step で呼ぶ (Scope と同型インタフェース)。"""
        self.times.append(float(t))
        self._values.append(np.asarray(u, dtype=float).copy())

    @property
    def values(self) -> npt.NDArray[Any]:
        if not self._values:
            return np.empty((0, self.n_inputs))
        return np.array(self._values)

    def save_npz(self, path: str | Path) -> None:
        """numpy ``.npz`` 形式で保存。``time`` と labels-named array を含む。"""
        path = Path(path)
        v = self.values
        arrays: dict[str, npt.NDArray[Any]] = {"time": np.array(self.times)}
        for i, lbl in enumerate(self.labels):
            arrays[lbl] = v[:, i] if v.size else np.empty(0)
        np.savez(path, **arrays)  # type: ignore[arg-type]

    def save_csv(self, path: str | Path) -> None:
        """CSV 形式で保存。1 列目=``time``、残り=labels 列。"""
        path = Path(path)
        v = self.values
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["time", *self.labels])
            for i, t in enumerate(self.times):
                row = [t, *v[i].tolist()] if v.size else [t]
                writer.writerow(row)
