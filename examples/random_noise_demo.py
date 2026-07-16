"""SPEC-0010 / ADR-0059 (v5.3.0): RandomSource デモ。

gaussian noise (mean=0, std=0.1) を Sine 波に重畳し、ノイズ印加の挙動を Scope に
表示する。seed 指定で run 間 bit-identical な再現性を確認できる。
"""

from __future__ import annotations

import logging

import numpy as np

from flode import Simulator
from flode.blocks import RandomSource, Scope, Sine, Sum

_logger = logging.getLogger(__name__)


def main() -> None:
    sim = Simulator(t_end=2.0, dt=0.01)

    sim.add(Sine(amplitude=1.0, frequency=1.0, id="signal"))
    sim.add(
        RandomSource(
            sample_time=0.01,
            distribution="gaussian",
            mean=0.0,
            std=0.1,
            seed=42,
            id="noise",
        )
    )
    sim.add(Sum(signs="++", id="mix"))
    sim.add(Scope(n_inputs=3, labels=["signal", "noise", "noisy"], id="trace"))

    sim.connect("signal", "mix", dst_idx=0)
    sim.connect("noise", "mix", dst_idx=1)
    sim.connect("signal", "trace", dst_idx=0)
    sim.connect("noise", "trace", dst_idx=1)
    sim.connect("mix", "trace", dst_idx=2)

    sim.run()

    trace = sim.get_block("trace")
    values = np.asarray(trace.values)
    signal = values[:, 0]
    noise = values[:, 1]
    noisy = values[:, 2]

    _logger.info("samples: %d", len(values))
    _logger.info("signal range: [%.3f, %.3f]", signal.min(), signal.max())
    _logger.info("noise mean / std: %.4f / %.4f (target 0.0 / 0.1)", noise.mean(), noise.std())
    _logger.info("noisy range: [%.3f, %.3f]", noisy.min(), noisy.max())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
