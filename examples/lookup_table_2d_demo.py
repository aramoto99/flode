"""SPEC-0017 / ADR-0064 (v5.6.0): LookupTable2D デモ。

エンジン制御の典型例として「(回転数, スロットル開度) → トルク」マップを
2-D Lookup で表現し、位相ずれ Sine 入力 (= 周期的運転点スキャン) に対する
出力トルクを Scope で取得する。
"""

from __future__ import annotations

import logging

import numpy as np

from flode import Simulator
from flode.blocks import Constant, LookupTable2D, Scope, Sine, Sum

_logger = logging.getLogger(__name__)


def main() -> None:
    sim = Simulator(t_end=2.0, dt=0.01)

    # 簡略エンジンマップ: (回転数 [rpm], スロットル開度 [-]) → トルク [Nm]
    rpm_breakpoints = [1000.0, 3000.0, 6000.0]
    throttle_breakpoints = [0.0, 0.5, 1.0]
    torque_table = [
        [10.0, 50.0, 80.0],  # 1000 rpm
        [30.0, 120.0, 200.0],  # 3000 rpm
        [40.0, 100.0, 180.0],  # 6000 rpm (高回転で頭打ち)
    ]

    # 位相ずれ Sine + Constant で運転点を 2-D 平面上で巡回させる
    # (中心 3500 rpm + 0.5 throttle、振幅 2500 rpm + 0.5)。
    sim.add(Sine(amplitude=2500.0, frequency=0.5, id="rpm_sine"))
    sim.add(Constant(value=3500.0, id="rpm_bias"))
    sim.add(Sum(signs="++", id="rpm"))
    sim.add(Sine(amplitude=0.5, frequency=0.5, phase=np.pi / 2, id="throttle_sine"))
    sim.add(Constant(value=0.5, id="throttle_bias"))
    sim.add(Sum(signs="++", id="throttle"))
    sim.add(
        LookupTable2D(
            breakpoints_row=rpm_breakpoints,
            breakpoints_col=throttle_breakpoints,
            table=torque_table,
            interpolation="linear",
            extrapolation="clip",
            id="engine_map",
        )
    )
    sim.add(Scope(n_inputs=3, labels=["rpm", "throttle", "torque"], id="trace"))

    sim.connect("rpm_sine", "rpm", dst_idx=0)
    sim.connect("rpm_bias", "rpm", dst_idx=1)
    sim.connect("throttle_sine", "throttle", dst_idx=0)
    sim.connect("throttle_bias", "throttle", dst_idx=1)
    sim.connect("rpm", "engine_map", dst_idx=0)
    sim.connect("throttle", "engine_map", dst_idx=1)
    sim.connect("rpm", "trace", dst_idx=0)
    sim.connect("throttle", "trace", dst_idx=1)
    sim.connect("engine_map", "trace", dst_idx=2)

    sim.run()

    trace = sim.get_block("trace")
    times = np.asarray(trace.times)
    values = np.asarray(trace.values)
    rpm = values[:, 0]
    throttle = values[:, 1]
    torque = values[:, 2]

    _logger.info("samples: %d", len(times))
    _logger.info("rpm range: [%.0f, %.0f]", rpm.min(), rpm.max())
    _logger.info("throttle range: [%.3f, %.3f]", throttle.min(), throttle.max())
    _logger.info("torque range: [%.2f, %.2f] Nm", torque.min(), torque.max())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
