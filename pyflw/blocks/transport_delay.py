"""SPEC-0015 / ADR-0065 (v5.8.0): Transport Delay ブロック (むだ時間)。

連続時間モデルの ``y(t) = u(t - delay_time)`` を sample_time-based discrete
approximation で実装する (ADR-0065 §Decision)。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import numpy.typing as npt

from ..core.block import Block
from ..exceptions import BlockSpecError


class TransportDelay(Block):
    """むだ時間 (dead time) ``y(t) ≈ u(t - delay_time)`` の sample-based 近似。

    過去 ``N = max(1, ceil(delay_time / sample_time))`` サンプルを state vector
    で保持し、サンプル境界で左シフトする (UnitDelay の n-step 一般化)。

    Args:
        delay_time: 遅延時間 [s]、``> 0`` 必須。
        sample_time: サンプル周期 [s]、``> 0`` 必須。
        initial_output: 初期出力値 (delay_time 経過前)、既定 0.0。

    Raises:
        BlockSpecError: ``delay_time <= 0`` / ``sample_time <= 0``。

    Note:
        ``delay_time`` が ``sample_time`` の整数倍でない場合は ceil で近似する
        (誤差 < sample_time、ADR-0065 §Consequences)。
        ``direct_feedthrough=False`` のため代数ループの切断に貢献する。
    """

    def __init__(
        self,
        *,
        delay_time: float,
        sample_time: float,
        initial_output: float = 0.0,
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        if not isinstance(delay_time, (int, float)) or isinstance(delay_time, bool):
            raise BlockSpecError(
                f"TransportDelay: delay_time must be a number, "
                f"got {type(delay_time).__name__}"
            )
        if delay_time <= 0.0:
            raise BlockSpecError(
                f"TransportDelay: delay_time must be > 0, got {delay_time}"
            )
        if not isinstance(sample_time, (int, float)) or isinstance(sample_time, bool):
            raise BlockSpecError(
                f"TransportDelay: sample_time must be a number, "
                f"got {type(sample_time).__name__}"
            )
        if sample_time <= 0.0:
            raise BlockSpecError(
                f"TransportDelay: sample_time must be > 0, got {sample_time}"
            )

        # N = ceil(delay/sample) + 1。+1 は Simulator の update-before-output 順序
        # (ADR-0015) を補正するため (左シフトで失われる 1 サンプル分を吸収)。
        # 結果として「観測される delay = N - 1 サンプル ≥ delay_time / sample_time」となる。
        n_buffer = max(1, int(math.ceil(delay_time / sample_time))) + 1

        super().__init__(
            id=id,
            name=name,
            n_inputs=1,
            n_outputs=1,
            n_states=n_buffer,
            direct_feedthrough=False,
            sample_time=sample_time,
        )
        self.delay_time = float(delay_time)
        self.initial_output = float(initial_output)
        self._n_buffer = n_buffer
        # initial buffer = [initial_output] * N
        self.x0 = np.full(n_buffer, float(initial_output))
        self._params: dict[str, Any] = {
            "delay_time": float(delay_time),
            "sample_time": float(sample_time),
            "initial_output": float(initial_output),
        }

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        # x[0] が最古 = delay_time 前の入力 (= 出力する値)。
        return np.array([float(x[0])])

    def update(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        # 左シフト: [x[1], ..., x[N-1], u[0]]
        return np.concatenate([x[1:], np.array([float(u[0])])])
