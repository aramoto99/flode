"""SPEC-0019 / ADR-0067 (v5.7.0): Prelookup 共有による検索コスト分離デモ。

エンジン制御の典型例として、回転数 [rpm] を入力として 1 つの ``Prelookup`` で
共通 breakpoint 検索を行い、3 つの ``InterpolationUsingPrelookup`` で
「効率」「最大トルク」「燃費率」を同時に補間する。

通常 ``LookupTable1D`` を 3 つ並べると searchsorted が 3 回走るが、本パターン
では Prelookup の 1 回検索結果 (k, f) を 3 後段で共有することで検索コストが
**1/3 に分離** される。M 個の table が同じ breakpoints を共有するシナリオで
本質的に有利になる設計。
"""

from __future__ import annotations

import logging

import numpy as np

from flode import Simulator
from flode.blocks import (
    InterpolationUsingPrelookup,
    Prelookup,
    Scope,
    Sine,
)

_logger = logging.getLogger(__name__)


def main() -> None:
    sim = Simulator(t_end=2.0, dt=0.01)

    # 共通 breakpoint: 回転数 [rpm] (動作点スイープ)
    rpm_bp = [1000.0, 2500.0, 4000.0, 5500.0, 7000.0]
    efficiency_table = [0.20, 0.32, 0.36, 0.30, 0.22]  # 効率 [-]
    max_torque_table = [80.0, 180.0, 240.0, 220.0, 160.0]  # 最大トルク [Nm]
    bsfc_table = [350.0, 240.0, 220.0, 250.0, 320.0]  # 燃費率 [g/kWh]

    # 入力: 振動する回転数 (4000 ± 3000 rpm)
    sim.add(Sine(amplitude=3000.0, frequency=0.5, id="rpm_sine"))

    # 共有 Prelookup: 1 回の searchsorted で (k, f) を得る
    sim.add(Prelookup(breakpoints=rpm_bp, id="prelookup"))

    # 後段: 効率 / 最大トルク / 燃費率の 3 本を同じ (k, f) で同時補間
    sim.add(InterpolationUsingPrelookup(table=efficiency_table, id="efficiency_lookup"))
    sim.add(InterpolationUsingPrelookup(table=max_torque_table, id="max_torque_lookup"))
    sim.add(InterpolationUsingPrelookup(table=bsfc_table, id="bsfc_lookup"))

    sim.add(
        Scope(
            n_inputs=4,
            labels=["rpm", "efficiency", "max_torque", "bsfc"],
            id="trace",
        )
    )

    # Prelookup の 2 出力 (k, f) を 3 つの後段に fan-out 結線
    sim.connect("rpm_sine", "prelookup")
    for dst in ("efficiency_lookup", "max_torque_lookup", "bsfc_lookup"):
        sim.connect("prelookup", dst, src_idx=0, dst_idx=0)
        sim.connect("prelookup", dst, src_idx=1, dst_idx=1)

    sim.connect("rpm_sine", "trace", dst_idx=0)
    sim.connect("efficiency_lookup", "trace", dst_idx=1)
    sim.connect("max_torque_lookup", "trace", dst_idx=2)
    sim.connect("bsfc_lookup", "trace", dst_idx=3)

    sim.run()

    trace = sim.get_block("trace")
    times = np.asarray(trace.times)
    values = np.asarray(trace.values)

    _logger.info("samples: %d", len(times))
    _logger.info("rpm range: [%.0f, %.0f]", values[:, 0].min(), values[:, 0].max())
    _logger.info("efficiency range: [%.3f, %.3f]", values[:, 1].min(), values[:, 1].max())
    _logger.info("max_torque range: [%.2f, %.2f] Nm", values[:, 2].min(), values[:, 2].max())
    _logger.info("bsfc range: [%.1f, %.1f] g/kWh", values[:, 3].min(), values[:, 3].max())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
