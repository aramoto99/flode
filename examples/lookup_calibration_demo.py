"""SPEC-0008 / ADR-0059 (v5.1.0): LookupTable1D デモ。

非線形較正カーブ (電圧 → 物理量) を 1-D Lookup Table で表現し、
Sine 入力に対する変換結果を Scope でプロットする。
"""

from __future__ import annotations

import logging

import numpy as np

from flode import Simulator
from flode.blocks import LookupTable1D, Scope, Sine

_logger = logging.getLogger(__name__)


def main() -> None:
    sim = Simulator(t_end=2.0, dt=0.01)

    # 入力電圧 [V] → 温度 [degC] の非線形較正。-2V〜+2V の Sine 入力に対し、
    # 中央域は緩やか、端は急峻な非対称カーブで変換する。
    calib_breakpoints = [-2.0, -1.0, 0.0, 1.0, 2.0]
    calib_table = [-50.0, -10.0, 0.0, 15.0, 60.0]

    sim.add(Sine(amplitude=2.0, frequency=0.5, id="adc_voltage"))
    sim.add(
        LookupTable1D(
            breakpoints=calib_breakpoints,
            table=calib_table,
            interpolation="linear",
            extrapolation="clip",
            id="calib",
        )
    )
    sim.add(Scope(n_inputs=2, labels=["voltage", "temperature"], id="trace"))

    sim.connect("adc_voltage", "calib")
    sim.connect("adc_voltage", "trace", dst_idx=0)
    sim.connect("calib", "trace", dst_idx=1)

    sim.run()

    trace = sim.get_block("trace")
    times = np.asarray(trace.times)
    values = np.asarray(trace.values)
    voltage = values[:, 0]
    temperature = values[:, 1]

    _logger.info("samples: %d", len(times))
    _logger.info("voltage range: [%.3f, %.3f] V", voltage.min(), voltage.max())
    _logger.info("temperature range: [%.3f, %.3f] degC", temperature.min(), temperature.max())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
