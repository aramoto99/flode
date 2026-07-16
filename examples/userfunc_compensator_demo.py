"""SPEC-0009 / ADR-0059 (v5.2.0): Fcn (User-Defined Function) デモ。

Sine 入力に対し、3 次の非線形補償項 ``u(1 + 0.1*u^2)`` を Fcn 1 ブロックで
評価して Scope に表示する。多段合成 (Gain + Product + Sum) を 1 行式で
置き換えるユースケース。
"""

from __future__ import annotations

import logging

import numpy as np

from flode import Simulator
from flode.blocks import Fcn, Scope, Sine

_logger = logging.getLogger(__name__)


def main() -> None:
    sim = Simulator(t_end=2.0, dt=0.01)

    sim.add(Sine(amplitude=1.0, frequency=1.0, id="src"))
    sim.add(
        Fcn(
            expression="u[0] * (1 + 0.1 * u[0]**2)",
            n_inputs=1,
            id="compensator",
        )
    )
    sim.add(Scope(n_inputs=2, labels=["src", "compensated"], id="trace"))

    sim.connect("src", "compensator")
    sim.connect("src", "trace", dst_idx=0)
    sim.connect("compensator", "trace", dst_idx=1)

    sim.run()

    trace = sim.get_block("trace")
    values = np.asarray(trace.values)
    src = values[:, 0]
    comp = values[:, 1]

    _logger.info("samples: %d", len(values))
    _logger.info("src range: [%.3f, %.3f]", src.min(), src.max())
    _logger.info("compensated range: [%.3f, %.3f]", comp.min(), comp.max())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
