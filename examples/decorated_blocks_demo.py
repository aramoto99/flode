"""ADR-0003 ``@block`` デコレータ DSL のドッグフード例。

Phase 0 既存ブロック (``Constant`` / ``Gain`` / ``Integrator``) のうち本質的な
3 種を ``@block`` で書き直し、Step 入力に対する 1 次積分系
(``y_dot = k * u``、解析解 ``y(t) = k * t``) で動作確認する。

Phase 0 既存ブロック (``flode/blocks/*``) はそのまま残し、両者は並存する。
本ファイルは API の最小デモであり、既存テスト (``test_phase0_regression``)
を置き換えるものではない。
"""

from __future__ import annotations

import logging

import numpy as np

from flode import Simulator, block
from flode.blocks import Scope

_logger = logging.getLogger(__name__)


@block
def my_constant(t: float, *, value: float = 0.0) -> float:
    """Source ブロック: 定数値 ``value`` を出力する。"""
    return value


@block
def my_gain(t: float, u: float, *, k: float = 1.0) -> float:
    """``y = k * u`` の比例ゲイン。"""
    return k * u


@block(states=1, direct_feedthrough=False)
def my_integrator(
    t: float, x: np.ndarray, u: float, *, x0: float = 0.0
) -> tuple[float, np.ndarray]:
    """連続積分器 ``y = x``、``x_dot = u``。``x0`` は予約パラメータ。"""
    return x[0], np.array([u])


def main() -> None:
    sim = Simulator(t_end=2.0, dt=0.01, rtol=1e-8, atol=1e-10)
    src = sim.add(my_constant(value=1.0, id="src"))
    g = sim.add(my_gain(k=0.5, id="g"))
    integ = sim.add(my_integrator(x0=0.0, id="integ"))
    scope = sim.add(Scope(n_inputs=2, labels=["u_g", "x"], id="scope"))

    sim.connect(src, g)
    sim.connect(g, integ)
    sim.connect(g, scope, dst_idx=0)
    sim.connect(integ, scope, dst_idx=1)

    sim.run()

    final_t = scope.times[-1]
    final_u = scope.values[-1, 0]
    final_x = scope.values[-1, 1]
    expected_x = 0.5 * final_t  # x(t) = k * t
    _logger.info(
        "t=%.4f, u_g=%.4f, x=%.4f (expected %.4f, abs err=%.2e)",
        final_t,
        final_u,
        final_x,
        expected_x,
        abs(final_x - expected_x),
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
