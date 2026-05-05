from __future__ import annotations

import numpy as np

from ..core.block import Block


class Constant(Block):
    def __init__(
        self,
        value: float = 1.0,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        super().__init__(id=id, name=name, n_inputs=0, n_outputs=1)
        self.value = float(value)

    def output(self, t, x, u):
        return np.array([self.value])


class Step(Block):
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

    def output(self, t, x, u):
        return np.array([self.final_value if t >= self.step_time else self.initial_value])


class Sine(Block):
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

    def output(self, t, x, u):
        return np.array(
            [self.amplitude * np.sin(2 * np.pi * self.frequency * t + self.phase)]
        )
