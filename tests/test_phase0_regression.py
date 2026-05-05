"""Phase 0 互換回帰テスト。

`spring_mass_damper.py` モデルの数値挙動が、解析モデル
(`scipy.solve_ivp` を直接使った 2nd-order ODE) と十分一致することを確認する。

ADR-0002 で `Simulator.run()` がハイブリッドループに書き換わるが、
連続のみのモデルでは Phase 0 と数値的に同等であるべき。
"""

from __future__ import annotations

import numpy as np
from scipy.integrate import solve_ivp

from pyflw import Simulator
from pyflw.blocks import Gain, Integrator, Scope, Step, Sum


def test_spring_mass_damper_matches_analytical():
    m, c, k = 1.0, 0.5, 4.0
    t_end = 20.0
    dt = 0.01

    sim = Simulator(t_end=t_end, dt=dt, rtol=1e-8, atol=1e-10)
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

    def f(t, y):
        x, xd = y
        return [xd, (1.0 - c * xd - k * x) / m]

    sol = solve_ivp(
        f, (0.0, t_end), [0.0, 0.0],
        t_eval=np.array(scope.times),
        method="RK45", rtol=1e-8, atol=1e-10,
    )
    expected_x = sol.y[0]
    expected_xd = sol.y[1]

    actual = scope.values
    assert actual.shape[0] == len(scope.times)
    np.testing.assert_allclose(actual[:, 0], expected_x, rtol=1e-3, atol=1e-4)
    np.testing.assert_allclose(actual[:, 1], expected_xd, rtol=1e-3, atol=1e-4)
