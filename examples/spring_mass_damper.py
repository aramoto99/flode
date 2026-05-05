"""Spring-mass-damper system.

Equation of motion: m*x_ddot + c*x_dot + k*x = F
Rearranged:         x_ddot = (F - c*x_dot - k*x) / m

Block diagram:
    F ---->[+]
            |     [+] - c*xd - k*x
            v
          [1/m] --> [Integrator: x_ddot -> x_dot]
                       |
                       +--> [Integrator: x_dot -> x] -> Scope (x)
                       +--> Scope (x_dot)
                       +--> [c] --> sum(-)
              [k] <----+
                       |
                       v
                     sum(-)
"""

from __future__ import annotations

import logging

import matplotlib.pyplot as plt

from pyflw import Simulator
from pyflw.blocks import Gain, Integrator, Scope, Step, Sum

_logger = logging.getLogger(__name__)


def main() -> None:
    m, c, k = 1.0, 0.5, 4.0

    sim = Simulator(t_end=20.0, dt=0.01)

    F = sim.add(Step(step_time=0.0, final_value=1.0, id="F"))
    sum_block = sim.add(Sum(signs="+--", id="sum"))
    inv_m = sim.add(Gain(k=1.0 / m, id="inv_m"))
    i_xd = sim.add(Integrator(x0=0.0, id="x_dot"))
    i_x = sim.add(Integrator(x0=0.0, id="x"))
    gain_c = sim.add(Gain(k=c, id="c"))
    gain_k = sim.add(Gain(k=k, id="k"))
    scope = sim.add(Scope(n_inputs=2, labels=["x", "x_dot"], id="response"))

    sim.connect(F, sum_block, dst_idx=0)
    sim.connect(gain_c, sum_block, dst_idx=1)
    sim.connect(gain_k, sum_block, dst_idx=2)
    sim.connect(sum_block, inv_m)
    sim.connect(inv_m, i_xd)
    sim.connect(i_xd, i_x)
    sim.connect(i_xd, gain_c)
    sim.connect(i_x, gain_k)
    sim.connect(i_x, scope, dst_idx=0)
    sim.connect(i_xd, scope, dst_idx=1)

    sim.run()
    scope.plot(show=False)
    plt.savefig("spring_mass_damper.png", dpi=120)
    _logger.info(
        "Final x=%.4f, x_dot=%.4f", scope.values[-1, 0], scope.values[-1, 1]
    )
    _logger.info("Saved spring_mass_damper.png")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
