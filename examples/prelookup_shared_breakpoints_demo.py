"""SPEC-0019 / ADR-0067 (v5.7.0): Prelookup 共有による検索コスト分離デモ。

モータ制御の典型例として、トルク [Nm] を入力として 1 つの ``Prelookup`` で
共通 breakpoint 検索を行い、2 つの ``InterpolationUsingPrelookup`` で
「効率カーブ」と「損失カーブ」を同時に補間する。

通常 ``LookupTable1D`` を 2 つ並べると searchsorted が 2 回走るが、本パターンでは
Prelookup の 1 回検索結果 (k, f) を共有することで検索コストが半減する。
"""

from __future__ import annotations

import logging

import numpy as np

from pyflw import Simulator
from pyflw.blocks import (
    InterpolationUsingPrelookup,
    Prelookup,
    Scope,
    Sine,
)

_logger = logging.getLogger(__name__)


def main() -> None:
    sim = Simulator(t_end=2.0, dt=0.01)

    # 共通 breakpoint: トルク [Nm] (動作点スイープ)
    torque_bp = [0.0, 25.0, 50.0, 75.0, 100.0]
    efficiency_table = [0.0, 0.65, 0.85, 0.92, 0.88]  # 効率 [-]
    loss_table = [0.0, 5.0, 12.0, 25.0, 60.0]  # 損失 [W]

    # 入力: 振動するトルク指令 (50 ± 50 Nm)
    sim.add(Sine(amplitude=50.0, frequency=0.5, id="torque_cmd_sine"))

    # 共有 Prelookup: 1 回の searchsorted で (k, f) を得る
    sim.add(Prelookup(breakpoints=torque_bp, id="prelookup"))

    # 後段: 効率 / 損失の 2 本を同じ (k, f) で同時補間
    sim.add(InterpolationUsingPrelookup(table=efficiency_table, id="efficiency_lookup"))
    sim.add(InterpolationUsingPrelookup(table=loss_table, id="loss_lookup"))

    sim.add(Scope(n_inputs=3, labels=["torque", "efficiency", "loss"], id="trace"))

    # Prelookup の (k, f) を Mux 経由ではなく素直に 2 入力ブロックに繋ぐ
    # (output_idx は src の出力 port を指定)
    sim.connect("torque_cmd_sine", "prelookup")

    sim.connect("prelookup", "efficiency_lookup", src_idx=0, dst_idx=0)
    sim.connect("prelookup", "efficiency_lookup", src_idx=1, dst_idx=1)
    sim.connect("prelookup", "loss_lookup", src_idx=0, dst_idx=0)
    sim.connect("prelookup", "loss_lookup", src_idx=1, dst_idx=1)

    sim.connect("torque_cmd_sine", "trace", dst_idx=0)
    sim.connect("efficiency_lookup", "trace", dst_idx=1)
    sim.connect("loss_lookup", "trace", dst_idx=2)

    sim.run()

    trace = sim.get_block("trace")
    times = np.asarray(trace.times)
    values = np.asarray(trace.values)
    torque = values[:, 0]
    efficiency = values[:, 1]
    loss = values[:, 2]

    _logger.info("samples: %d", len(times))
    _logger.info("torque range: [%.2f, %.2f] Nm", torque.min(), torque.max())
    _logger.info("efficiency range: [%.3f, %.3f]", efficiency.min(), efficiency.max())
    _logger.info("loss range: [%.2f, %.2f] W", loss.min(), loss.max())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
