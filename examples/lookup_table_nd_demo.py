"""SPEC-0018 / ADR-0068 (v5.8.0): LookupTableND (3-D) デモ。

熱機関の典型例として「(回転数, トルク, 吸気温度) → 熱効率」の 3-D マップを
LookupTableND で表現し、3 軸の位相ずらし Sine 入力に対して熱効率を補間する。

LookupTable2D の 2 入力に対し、本 SPEC では n 入力 (= 3 軸) を実現する。
"""

from __future__ import annotations

import logging

import numpy as np

from flode import Simulator
from flode.blocks import Constant, LookupTableND, Scope, Sine, Sum

_logger = logging.getLogger(__name__)


def main() -> None:
    sim = Simulator(t_end=2.0, dt=0.02)

    # 簡略エンジン熱効率マップ:
    #   軸 0 = 回転数 [rpm]      bp = [1000, 4000, 7000]
    #   軸 1 = トルク [Nm]        bp = [50, 150, 250]
    #   軸 2 = 吸気温度 [degC]    bp = [-20, 20, 60]
    # 効率の典型ピークを中央 (4000 rpm, 150 Nm, 20 degC) 付近に置く。
    rpm_bp = [1000.0, 4000.0, 7000.0]
    torque_bp = [50.0, 150.0, 250.0]
    intake_temp_bp = [-20.0, 20.0, 60.0]
    eff_table = [
        [  # rpm = 1000
            [0.15, 0.16, 0.14],
            [0.18, 0.20, 0.16],
            [0.16, 0.18, 0.14],
        ],
        [  # rpm = 4000
            [0.22, 0.26, 0.21],
            [0.30, 0.36, 0.27],  # ピーク 0.36 at (4000, 150, 20)
            [0.25, 0.30, 0.22],
        ],
        [  # rpm = 7000
            [0.16, 0.18, 0.14],
            [0.22, 0.26, 0.20],
            [0.18, 0.22, 0.15],
        ],
    ]

    # 入力 (バイアス + Sine): 中央付近を巡回
    sim.add(Sine(amplitude=2500.0, frequency=0.5, id="rpm_sine"))
    sim.add(Constant(value=4000.0, id="rpm_bias"))
    sim.add(Sum(signs="++", id="rpm"))

    sim.add(Sine(amplitude=80.0, frequency=0.5, phase=np.pi / 2, id="torque_sine"))
    sim.add(Constant(value=150.0, id="torque_bias"))
    sim.add(Sum(signs="++", id="torque"))

    sim.add(Sine(amplitude=30.0, frequency=0.5, phase=np.pi, id="intake_temp_sine"))
    sim.add(Constant(value=20.0, id="intake_temp_bias"))
    sim.add(Sum(signs="++", id="intake_temp"))

    sim.add(
        LookupTableND(
            breakpoints_axes=[rpm_bp, torque_bp, intake_temp_bp],
            table=eff_table,
            interpolation="linear",
            extrapolation="clip",
            id="efficiency_map",
        )
    )
    sim.add(
        Scope(
            n_inputs=4,
            labels=["rpm", "torque", "intake_temp", "efficiency"],
            id="trace",
        )
    )

    # Sum を bias と組合せる結線
    for axis_name in ("rpm", "torque", "intake_temp"):
        sim.connect(f"{axis_name}_sine", axis_name, dst_idx=0)
        sim.connect(f"{axis_name}_bias", axis_name, dst_idx=1)

    sim.connect("rpm", "efficiency_map", dst_idx=0)
    sim.connect("torque", "efficiency_map", dst_idx=1)
    sim.connect("intake_temp", "efficiency_map", dst_idx=2)

    sim.connect("rpm", "trace", dst_idx=0)
    sim.connect("torque", "trace", dst_idx=1)
    sim.connect("intake_temp", "trace", dst_idx=2)
    sim.connect("efficiency_map", "trace", dst_idx=3)

    sim.run()

    trace = sim.get_block("trace")
    values = np.asarray(trace.values)
    _logger.info("samples: %d", len(np.asarray(trace.times)))
    _logger.info("rpm range: [%.0f, %.0f]", values[:, 0].min(), values[:, 0].max())
    _logger.info("torque range: [%.2f, %.2f] Nm", values[:, 1].min(), values[:, 1].max())
    _logger.info(
        "intake_temp range: [%.1f, %.1f] degC",
        values[:, 2].min(),
        values[:, 2].max(),
    )
    _logger.info(
        "efficiency range: [%.3f, %.3f]",
        values[:, 3].min(),
        values[:, 3].max(),
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
