from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from ..core.block import Block
from ..core.dtypes import DTYPE_PARAM_VALUES, cast_value
from ..exceptions import BlockSpecError


class Constant(Block):
    """定数値ソース ``y(t) = value``。

    Args:
        value: 出力する定数値。生値のまま保持され、``dtype`` の変換は出力時に
            適用される (型を戻すと元の値が復活する)。float64 で保持するため、
            2^53 を超える整数を正確に表現したい場合は上流での表現に注意
            (SPEC-0028)。
        dtype: 実 dtype (SPEC-0028)。``"auto"`` (既定、宣言しない = ただの
            float64 定数) 以外を選ぶと出力が実際にその numpy dtype になる。
            float → 整数はゼロ方向切り捨て。

    Raises:
        BlockSpecError: ``dtype`` が許可値の外。
    """

    _param_enums = {"dtype": DTYPE_PARAM_VALUES}

    def __init__(
        self,
        value: float = 1.0,
        dtype: str = "auto",
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if dtype not in DTYPE_PARAM_VALUES:
            raise BlockSpecError(
                f"Constant: dtype must be one of {DTYPE_PARAM_VALUES}, got {dtype!r}"
            )
        super().__init__(id=id, name=name, n_inputs=0, n_outputs=1)
        self.value = float(value)
        self.dtype = dtype
        self._params = {"value": self.value}
        # Q1: "auto" は保存 JSON に出さない
        if dtype != "auto":
            self._params["dtype"] = dtype

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        if self.dtype != "auto":
            return cast_value(np.asarray([self.value]), self.dtype)
        return np.array([self.value])


class Step(Block):
    """ステップ信号 ``y(t) = final_value if t >= step_time else initial_value``。

    Args:
        step_time: 値が切り替わる時刻。
        initial_value: ``t < step_time`` での値。
        final_value: ``t >= step_time`` での値。
    """

    def __init__(
        self,
        step_time: float = 1.0,
        initial_value: float = 0.0,
        final_value: float = 1.0,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        super().__init__(id=id, name=name, n_inputs=0, n_outputs=1)
        self.step_time = float(step_time)
        self.initial_value = float(initial_value)
        self.final_value = float(final_value)
        self._params = {
            "step_time": self.step_time,
            "initial_value": self.initial_value,
            "final_value": self.final_value,
        }

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.array([self.final_value if t >= self.step_time else self.initial_value])


class Sine(Block):
    """正弦波 ``y(t) = amplitude * sin(2π * frequency * t + phase)``。

    Args:
        amplitude: 振幅。
        frequency: 周波数 [Hz]。
        phase: 位相 [rad]。
    """

    def __init__(
        self,
        amplitude: float = 1.0,
        frequency: float = 1.0,
        phase: float = 0.0,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        super().__init__(id=id, name=name, n_inputs=0, n_outputs=1)
        self.amplitude = float(amplitude)
        self.frequency = float(frequency)
        self.phase = float(phase)
        self._params = {
            "amplitude": self.amplitude,
            "frequency": self.frequency,
            "phase": self.phase,
        }

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.array([self.amplitude * np.sin(2 * np.pi * self.frequency * t + self.phase)])


class Ramp(Block):
    """線形ランプ ``y(t) = initial_output + slope * max(0, t - start_time)``。

    Args:
        slope: 単位時間あたりの増加量。
        start_time: ランプ開始時刻。これ以前は ``initial_output`` を保持。
        initial_output: ``t < start_time`` での出力値。
    """

    def __init__(
        self,
        slope: float = 1.0,
        start_time: float = 0.0,
        initial_output: float = 0.0,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        super().__init__(id=id, name=name, n_inputs=0, n_outputs=1)
        self.slope = float(slope)
        self.start_time = float(start_time)
        self.initial_output = float(initial_output)
        self._params = {
            "slope": self.slope,
            "start_time": self.start_time,
            "initial_output": self.initial_output,
        }

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        if t < self.start_time:
            return np.array([self.initial_output])
        return np.array([self.initial_output + self.slope * (t - self.start_time)])


class Clock(Block):
    """シミュレーション時刻をそのまま出力する ``y(t) = t``。"""

    def __init__(
        self,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        super().__init__(id=id, name=name, n_inputs=0, n_outputs=1)
        self._params = {}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.array([t])


class PulseGenerator(Block):
    """矩形波パルスを生成する。

    位相 ``φ = (t - phase_delay) mod period`` を計算し、
    ``φ < period * pulse_width / 100`` の区間で ``amplitude``、それ以外で 0 を出力する。

    Args:
        amplitude: パルス高。
        period: 周期 [s]。``> 0``。
        pulse_width: デューティ比 [%] (0〜100)。
        phase_delay: 位相遅延 [s]。
    """

    def __init__(
        self,
        amplitude: float = 1.0,
        period: float = 1.0,
        pulse_width: float = 50.0,
        phase_delay: float = 0.0,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if period <= 0.0:
            raise BlockSpecError(f"PulseGenerator: period must be > 0, got {period}")
        if not 0.0 <= pulse_width <= 100.0:
            raise BlockSpecError(
                f"PulseGenerator: pulse_width must be in [0, 100], got {pulse_width}"
            )
        super().__init__(id=id, name=name, n_inputs=0, n_outputs=1)
        self.amplitude = float(amplitude)
        self.period = float(period)
        self.pulse_width = float(pulse_width)
        self.phase_delay = float(phase_delay)
        self._params = {
            "amplitude": self.amplitude,
            "period": self.period,
            "pulse_width": self.pulse_width,
            "phase_delay": self.phase_delay,
        }

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        phi = (t - self.phase_delay) % self.period
        threshold = self.period * self.pulse_width / 100.0
        return np.array([self.amplitude if phi < threshold else 0.0])
