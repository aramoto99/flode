"""SPEC-0012 / ADR-0059 (v5.5.0): Rate Limiter + Relay デモ。

Sine 入力に対し、RateLimiter (slew rate 制限) と Relay (hysteresis 遷移) の
挙動を Scope に表示する。
"""

from __future__ import annotations

import logging

import numpy as np

from flode import Simulator
from flode.blocks import RateLimiter, Relay, Scope, Sine

_logger = logging.getLogger(__name__)


def main() -> None:
    sim = Simulator(t_end=2.0, dt=0.01)

    sim.add(Sine(amplitude=1.0, frequency=1.0, id="src"))
    sim.add(
        RateLimiter(
            sample_time=0.01,
            rising_slew_rate=2.0,
            falling_slew_rate=-2.0,
            id="rl",
        )
    )
    sim.add(
        Relay(
            sample_time=0.01,
            switch_on_point=0.5,
            switch_off_point=-0.5,
            x0_state="off",
            id="re",
        )
    )
    sim.add(Scope(n_inputs=3, labels=["sine", "rate_limited", "relay"], id="trace"))

    sim.connect("src", "rl")
    sim.connect("src", "re")
    sim.connect("src", "trace", dst_idx=0)
    sim.connect("rl", "trace", dst_idx=1)
    sim.connect("re", "trace", dst_idx=2)

    sim.run()

    values = np.asarray(sim.get_block("trace").values)
    src = values[:, 0]
    rate_limited = values[:, 1]
    relay = values[:, 2]

    _logger.info("samples: %d", len(values))
    _logger.info("sine range: [%.3f, %.3f] (target [-1, 1])", src.min(), src.max())
    _logger.info(
        "rate-limited range: [%.3f, %.3f] (slew=±2/s → 振幅 < 1)",
        rate_limited.min(),
        rate_limited.max(),
    )
    relay_levels = sorted(set(np.round(relay, 6).tolist()))
    _logger.info("relay levels: %s (expect {0.0, 1.0})", relay_levels)
    transitions = int(np.sum(np.abs(np.diff(relay)) > 0.5))
    _logger.info("relay transitions in 2s: %d (Sine 1Hz で ON/OFF が交互発生)", transitions)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
