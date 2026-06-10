"""Synthetic scaling benchmark for the pyflw Simulator.

Builds a chain of N integrators driven by a Step source, runs the simulation
end-to-end, and reports build / run wall time plus the realtime ratio
(sim_time / wall_time; >1 means the simulator runs faster than realtime).

Usage:
    python -m benchmarks.scaling

The chain is intentionally minimal so the result reflects core Simulator
overhead (graph build, topological sort, solve_ivp dispatch, per-step output
recomputation) rather than block-specific costs.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from pyflw import Simulator
from pyflw.blocks import Integrator, Scope, Step

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BenchResult:
    n_blocks: int
    build_s: float
    run_s: float
    sim_time: float
    realtime_ratio: float


def build_chain(n_integrators: int, t_end: float, dt: float) -> Simulator:
    sim = Simulator(t_end=t_end, dt=dt)
    src = sim.add(Step(step_time=0.0, final_value=1.0, id="src"))
    prev = src
    for i in range(n_integrators):
        nxt = sim.add(Integrator(x0=0.0, id=f"int_{i}"))
        sim.connect(prev, nxt)
        prev = nxt
    sink = sim.add(Scope(n_inputs=1, id="sink"))
    sim.connect(prev, sink)
    return sim


def bench_one(n: int, t_end: float, dt: float) -> BenchResult:
    t0 = time.perf_counter()
    sim = build_chain(n, t_end=t_end, dt=dt)
    t1 = time.perf_counter()
    sim.run()
    t2 = time.perf_counter()
    build_s = t1 - t0
    run_s = t2 - t1
    return BenchResult(
        n_blocks=n,
        build_s=build_s,
        run_s=run_s,
        sim_time=t_end,
        realtime_ratio=(t_end / run_s) if run_s > 0 else float("inf"),
    )


def main() -> None:
    t_end = 10.0
    dt = 0.01
    ns = (1, 5, 10, 50, 100, 500)

    _logger.info(
        "pyflw scaling benchmark — integrator chain, t_end=%.1fs, dt=%.3fs",
        t_end,
        dt,
    )
    header = f"{'N':>5} | {'build [ms]':>12} | {'run [s]':>10} | {'sim/wall':>10}"
    _logger.info(header)
    _logger.info("-" * len(header))
    for n in ns:
        r = bench_one(n, t_end=t_end, dt=dt)
        _logger.info(
            "%5d | %12.2f | %10.3f | %9.2fx",
            r.n_blocks,
            r.build_s * 1e3,
            r.run_s,
            r.realtime_ratio,
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
