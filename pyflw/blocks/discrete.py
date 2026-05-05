"""離散時間ブロック。

Phase 1 で実装するブロック:

* ``UnitDelay`` — 1 サンプル遅延 (ADR-0002 §(3))
* ``DiscreteIntegrator`` — 前進 Euler 積分 ``x[k+1] = x[k] + T*gain*u[k]``
* ``ZeroOrderHold`` — 連続入力を離散周期でサンプリング保持

``Memory`` は ``UnitDelay`` と意味論が同一のため Phase 1 では別実装しない。
``FirstOrderHold`` / 高次離散ブロックは Phase 2 以降。
"""

from __future__ import annotations

import numpy as np

from ..core.block import Block
from ..exceptions import BlockSpecError


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


class DiscreteIntegrator(Block):
    """前進 Euler 離散積分 ``x[k+1] = x[k] + sample_time * gain * u[k]``、出力 ``y[k] = x[k]``。

    ``direct_feedthrough=False`` (出力は前ステップ確定状態のみ参照) なので
    閉ループ内の代数ループ切断にも使える。

    Args:
        sample_time: サンプル周期 [s]。``> 0`` 必須 (継承 ``-1.0`` も可)。
        gain: 入力に掛けるゲイン (積分定数)。
        x0: 初期状態。
    """

    def __init__(
        self,
        *,
        sample_time: float,
        gain: float = 1.0,
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
        self.gain = float(gain)
        self.x0 = np.array([float(x0)])

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.array([x[0]])

    def update(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        # ステップ幅は **解決後の sample_time** を使う (継承時の動的解決に対応)。
        # Simulator 経由なら ``_resolve_sample_times`` で必ず確定する。直接呼びだ
        # された場合や未登録の状態では `BlockSpecError` で明示する (silent zero-step
        # を返さない: 無音バグ防止)。
        ts = self._resolved_sample_time
        if ts is None or ts <= 0.0:
            raise BlockSpecError(
                f"DiscreteIntegrator {self.id!r}: sample_time has not been resolved. "
                "Add this block to a Simulator and call `run()` (or invoke "
                "`_resolve_sample_times`) before calling update() directly."
            )
        return np.array([x[0] + ts * self.gain * u[0]])


class ZeroOrderHold(Block):
    """連続入力をサンプル点で取り込み、次サンプルまで状態として保持する。

    実装は state-based: ``y[k] = x[k]``、``x[k+1] = u(t_k)``。
    ``direct_feedthrough=False`` のため閉ループ内の代数ループ切断にも使える。

    Args:
        sample_time: サンプル周期 [s]。``> 0`` 必須 (継承 ``-1.0`` も可)。
        x0: 初回サンプル前 (``t=0`` 時点) の出力値。

    Note:
        Simulink の Zero Order Hold (``direct_feedthrough=True``、サンプル点で
        即座に出力反映) とは挙動が異なり、本実装は ``UnitDelay`` と等価
        (1 サンプル分遅延する)。真の ZOH (``direct_feedthrough=True`` 版) は
        Phase 2 で追加予定。命名変更も Phase 2 の破壊的変更候補。
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
