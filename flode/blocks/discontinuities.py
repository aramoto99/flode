"""SPEC-0012 / ADR-0059 (v5.5.0): 不連続要素ブロック (Wave 2 第 1 弾)。

業界標準ブロック線図ツールの "Discontinuities" カテゴリ相当の **状態を持つ非線形要素**:

* ``RateLimiter`` — アクチュエータの slew rate (変化率) を制限する
* ``Relay`` — ヒステリシス付き ON / OFF スイッチ

両ブロックは sample_time gated 離散ブロック (`ZeroOrderHoldDirect` 同型の
1-state hold パターン) として実装する (ADR-0014 §(3))。`solve_ivp` 連続系
との見うち互換 (中間時刻は state hold、サンプル境界でのみ state 更新)。

設計の要点 (SPEC-0012 §機能要件):

* **n_states=1**: 前回出力値 (RateLimiter) または relay state (Relay、
  1.0=ON / 0.0=OFF) を hold
* **direct_feedthrough=True**: サンプル時刻で現入力 ``u`` を参照
* **`reset()` lifecycle hook**: Relay の ``x0_state`` 文字列 enum から state
  を再初期化 (SPEC-0010 RandomSource と同パターン、Simulator.run() の
  `if hasattr(b, "reset"): b.reset()` 経路、simulator.py:1004-1006)
* **x0=0 placeholder の代わりに明示的 x0**: RateLimiter は ``x0`` 数値、
  Relay は ``x0_state`` enum で「ユーザー意図の初期状態」を保持。
  Simulator.run() の [A'] update → [A] output 順序 (ADR-0015) でも、
  本ブロックは「現入力が前 state から離れていない限り state を保つ」設計
  のため placeholder ではなく実際の初期状態を持つ
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from ..core.block import Block
from ..exceptions import BlockSpecError


class RateLimiter(Block):
    """アクチュエータの変化率 (slew rate) を制限する離散ブロック。

    サンプル時刻 ``t_k = k * sample_time`` で:

    .. code-block:: text

        max_delta_up   = rising_slew_rate  * sample_time   # > 0
        max_delta_down = falling_slew_rate * sample_time   # < 0
        delta_clipped  = clip(u(t_k) - x_prev, max_delta_down, max_delta_up)
        x_new = x_prev + delta_clipped

    中間時刻 ``t ∈ (t_k, t_{k+1})`` では出力 = 前 sample 値の hold。
    ``solve_ivp`` の可変ステップ再評価でも同一 ``t`` で同一値を返す
    (積分の連続性 + 再現性)。

    Args:
        rising_slew_rate: 立ち上がり最大変化率 [unit/s]、``> 0`` 必須
            (既定 1.0)。
        falling_slew_rate: 立ち下がり最大変化率 [unit/s]、``< 0`` 必須
            (既定 -1.0、対称デフォルト)。
        sample_time: サンプル周期 [s]、``> 0`` 必須。
        x0: 初期出力値 (既定 0.0)。

    Raises:
        BlockSpecError: ``rising_slew_rate <= 0``、``falling_slew_rate >= 0``、
            ``sample_time <= 0``。
    """

    def __init__(
        self,
        *,
        sample_time: float,
        rising_slew_rate: float = 1.0,
        falling_slew_rate: float = -1.0,
        x0: float = 0.0,
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        if not isinstance(sample_time, (int, float)) or isinstance(sample_time, bool):
            raise BlockSpecError(
                f"RateLimiter: sample_time must be a number, got {type(sample_time).__name__}"
            )
        if sample_time <= 0.0:
            raise BlockSpecError(f"RateLimiter: sample_time must be > 0, got {sample_time}")
        if rising_slew_rate <= 0.0:
            raise BlockSpecError(
                f"RateLimiter: rising_slew_rate must be > 0, got {rising_slew_rate}"
            )
        if falling_slew_rate >= 0.0:
            raise BlockSpecError(
                f"RateLimiter: falling_slew_rate must be < 0, got {falling_slew_rate}"
            )

        super().__init__(
            id=id,
            name=name,
            n_inputs=1,
            n_outputs=1,
            n_states=1,
            direct_feedthrough=True,
            sample_time=sample_time,
        )
        self.rising_slew_rate = float(rising_slew_rate)
        self.falling_slew_rate = float(falling_slew_rate)
        self.x0 = np.array([float(x0)])
        self._params: dict[str, Any] = {
            "sample_time": float(sample_time),
            "rising_slew_rate": self.rising_slew_rate,
            "falling_slew_rate": self.falling_slew_rate,
            "x0": float(x0),
        }

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        # state hold: サンプル境界以外でも中間時刻でも state 値を返す。
        return np.array([float(x[0])])

    def update(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        # サンプル境界でのみ Simulator が呼ぶ。slew 制限を適用して新 state を返す。
        # DiscreteIntegrator と同様に _resolved_sample_time が解決済か確認。
        ts = self._resolved_sample_time
        if ts is None or ts <= 0.0:
            raise BlockSpecError(
                f"RateLimiter {self.id!r}: sample_time has not been resolved. "
                "Add this block to a Simulator and call run() (or invoke "
                "_resolve_sample_times) before calling update() directly."
            )
        # rising_slew_rate > 0 / falling_slew_rate < 0 は __init__ で検証済 (= ここでは
        # 不変条件として再検証しない)。direct な attribute 書き換えで反転させた場合
        # は clip 方向が崩れるが、ユーザー設計時のミスとして許容する。
        max_up = self.rising_slew_rate * ts
        max_down = self.falling_slew_rate * ts
        delta = float(u[0]) - float(x[0])
        # clip(delta, max_down, max_up) — max_down は負、max_up は正。
        if delta > max_up:
            delta = max_up
        elif delta < max_down:
            delta = max_down
        return np.array([float(x[0]) + delta])


class Relay(Block):
    """ヒステリシス付き ON / OFF スイッチ。

    サンプル時刻で:

    .. code-block:: text

        if state == OFF and u(t_k) >= switch_on_point:
            state = ON
        elif state == ON  and u(t_k) <= switch_off_point:
            state = OFF
        y = output_on if state == ON else output_off

    内部状態は float ``1.0`` = ON / ``0.0`` = OFF で保持 (state vector に
    float でしか入らないため)。中間時刻は前回 sample 値を hold。

    Args:
        switch_on_point: ON へ遷移する入力しきい値 (既定 0.5)。
        switch_off_point: OFF へ遷移する入力しきい値 (既定 -0.5)。
            ``< switch_on_point`` 必須 (= hysteresis band 形成)。
        output_on: ON 状態での出力値 (既定 1.0)。
        output_off: OFF 状態での出力値 (既定 0.0)。
        sample_time: サンプル周期 [s]、``> 0`` 必須。
        x0_state: 初期状態 ``"on"`` または ``"off"`` (既定 ``"off"``)。

    Raises:
        BlockSpecError: ``switch_off_point >= switch_on_point``、
            ``sample_time <= 0``、``x0_state`` enum 値外。
    """

    _ALLOWED_X0_STATES: tuple[str, ...] = ("on", "off")
    # ADR-0019 / ADR-0039 follow-up: GUI ParameterPanel が enum select を出すヒント
    _param_enums = {"x0_state": _ALLOWED_X0_STATES}

    def __init__(
        self,
        *,
        sample_time: float,
        switch_on_point: float = 0.5,
        switch_off_point: float = -0.5,
        output_on: float = 1.0,
        output_off: float = 0.0,
        x0_state: str = "off",
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        if x0_state not in self._ALLOWED_X0_STATES:
            raise BlockSpecError(
                f"Relay: x0_state must be one of {self._ALLOWED_X0_STATES}, got {x0_state!r}"
            )
        if not isinstance(sample_time, (int, float)) or isinstance(sample_time, bool):
            raise BlockSpecError(
                f"Relay: sample_time must be a number, got {type(sample_time).__name__}"
            )
        if sample_time <= 0.0:
            raise BlockSpecError(f"Relay: sample_time must be > 0, got {sample_time}")
        if not (switch_off_point < switch_on_point):
            raise BlockSpecError(
                f"Relay: switch_off_point ({switch_off_point}) must be "
                f"< switch_on_point ({switch_on_point}) for hysteresis"
            )

        super().__init__(
            id=id,
            name=name,
            n_inputs=1,
            n_outputs=1,
            n_states=1,
            direct_feedthrough=True,
            sample_time=sample_time,
        )
        self.switch_on_point = float(switch_on_point)
        self.switch_off_point = float(switch_off_point)
        self.output_on = float(output_on)
        self.output_off = float(output_off)
        self.x0_state = x0_state
        # 初期 state を enum から float に変換 (RandomSource パターン参照)。
        self.x0 = self._x0_from_state()

        self._params: dict[str, Any] = {
            "sample_time": float(sample_time),
            "switch_on_point": self.switch_on_point,
            "switch_off_point": self.switch_off_point,
            "output_on": self.output_on,
            "output_off": self.output_off,
            "x0_state": x0_state,
        }

    def _x0_from_state(self) -> npt.NDArray[Any]:
        """``x0_state`` enum から float 1-vector を構築する (DRY helper)。

        ``__init__`` と ``reset()`` の両方から呼ばれ、将来 enum 値が増えても
        変更箇所を 1 か所に集約する。
        """
        return np.array([1.0 if self.x0_state == "on" else 0.0])

    def reset(self) -> None:
        """``Simulator.run()`` 開始時の lifecycle hook (simulator.py:1004-1006)。

        ``x0`` を ``x0_state`` enum から再構築する。同一 Simulator で
        ``run()`` を複数回呼んでも、各 run で同一初期 state から開始する
        (= bit-identical 再現性)。
        """
        self.x0 = self._x0_from_state()

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        # state hold: x[0] (= 0.0 or 1.0) を見て output_on / output_off を選ぶ。
        # 0.5 を境にした分岐で float 精度 (機械精度) の境界揺らぎを許容。
        return np.array([self.output_on if x[0] > 0.5 else self.output_off])

    def update(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        # サンプル境界で遷移ロジックを評価する。
        current_on = x[0] > 0.5
        u_val = float(u[0])
        if not current_on and u_val >= self.switch_on_point:
            return np.array([1.0])
        if current_on and u_val <= self.switch_off_point:
            return np.array([0.0])
        # 遷移条件を満たさなければ state 維持。
        return np.array([float(x[0])])
