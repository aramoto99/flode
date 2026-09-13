"""時刻グリッド ``t = k * dt`` の丸め誤差でソースの境界が 1 サンプル遅れない回帰テスト。

2026-09-13 発見: ``Simulator`` は ``t = k * dt_base`` を float 乗算で作るため、
``dt=0.3`` の ``k=3`` は ``0.8999999999999999`` になる。``Step(step_time=0.9)`` /
``PulseGenerator(period=0.9)`` は生の float 比較なので t=0.9 の境界で切り替わらず、
次のサンプル (t=1.2) まで遅れていた。
"""

from __future__ import annotations

import numpy as np
import pytest

from flode import Simulator
from flode.blocks import PulseGenerator, Scope, Step


@pytest.mark.parametrize(
    ("dt", "boundary"),
    [(0.3, 0.9), (0.7, 2.1), (0.7, 4.9), (0.1, 0.3), (0.05, 0.35)],
)
def test_step_switches_exactly_on_grid_boundary(dt: float, boundary: float) -> None:
    k_true = round(boundary / dt)
    sim = Simulator(t_end=dt * (k_true + 2), dt=dt)
    sim.add(Step(step_time=boundary, initial_value=0.0, final_value=1.0, id="step"))
    sim.add(Scope(n_inputs=1, id="sc"))
    sim.connect("step", "sc")
    sim.run()
    y = sim.get_block("sc").values[:, 0]
    expected = (np.arange(k_true + 3) >= k_true).astype(float)
    np.testing.assert_array_equal(y, expected)


@pytest.mark.parametrize(("dt", "period"), [(0.3, 0.6), (0.3, 0.9), (0.7, 1.4), (0.7, 2.1)])
def test_pulse_restarts_exactly_on_period_boundary(dt: float, period: float) -> None:
    n_per = round(period / dt)
    sim = Simulator(t_end=dt * (2 * n_per + 1), dt=dt)
    sim.add(PulseGenerator(period=period, pulse_width=50.0, id="pulse"))
    sim.add(Scope(n_inputs=1, id="sc"))
    sim.connect("pulse", "sc")
    sim.run()
    y = sim.get_block("sc").values[:, 0]
    k = np.arange(2 * n_per + 2)
    expected = ((k % n_per) * dt < period / 2 - 1e-12).astype(float)
    np.testing.assert_array_equal(y, expected)


def test_extremely_small_dt_base_is_rejected() -> None:
    """code-reviewer SHOULD: 格子時刻の丸め桁 (12) より細かい基準ステップは明示拒否。"""
    from flode.exceptions import SchedulingError

    sim = Simulator(t_end=1e-8, dt=1e-10)
    sim.add(Step(step_time=5e-9, id="step"))
    sim.add(Scope(n_inputs=1, id="sc"))
    sim.connect("step", "sc")
    with pytest.raises(SchedulingError, match="below the supported minimum"):
        sim.run()


def test_scope_times_are_clean_grid_multiples() -> None:
    sim = Simulator(t_end=3.0, dt=0.3)
    sim.add(Step(step_time=0.9, id="step"))
    sim.add(Scope(n_inputs=1, id="sc"))
    sim.connect("step", "sc")
    sim.run()
    assert list(sim.get_block("sc").times) == [round(0.3 * k, 12) for k in range(11)]
