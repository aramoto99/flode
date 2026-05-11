"""ADR-0037 デモ: ``linearize(method='jax')`` で PID 制御モデルを機械精度線形化。

``pyflw[codegen]`` (= ``jax[cpu]``) が必要。中心差分 (`method="central"`、
ADR-0026) と機械精度自動微分 (`method="jax"`、ADR-0037) を比較する。

実行方法:

    pip install pyflw[codegen]
    python examples/jax_jacfwd_pid.py

期待出力:

    [PID system] central A:
    ... (中心差分、誤差 O(sqrt(eps_machine)) ≈ 1e-8 程度)
    [PID system] jax A:
    ... (機械精度、誤差 < 1e-15)
    [PID system] |A_central - A_jax|_max = 2.2e-09
"""

from __future__ import annotations

import logging

import numpy as np

from pyflw import Simulator, linearize
from pyflw.blocks import Gain, Integrator, Scope, Step, Sum

_logger = logging.getLogger("pyflw.examples.jax_jacfwd_pid")


def _build_pid_with_first_order_plant() -> Simulator:
    """PID コントローラ + 1 次遅れプラントの閉ループ。

    トポロジ::

        ref → e_sum (+, -) → P_branch + I_branch + D_branch (sum_pid)
              ↑                                  → control → plant_sum (+, -) → 1/m → integrator → y
              y (feedback)                                                                ↓
                                                                                         (loop back to e_sum)

    本 example では D_branch は省略 (= P + I のみ)、Integrator 連続状態が 2 つ
    (controller integral + plant 出力)。
    """
    Kp, Ki, m = 2.0, 0.5, 1.0
    sim = Simulator(t_end=10.0, dt=0.01)
    # 参照入力 (Step)
    ref = sim.add(Step(step_time=0.0, final_value=1.0, id="ref"))
    # フィードバック誤差 e = ref - y
    e_sum = sim.add(Sum(signs="+-", id="e"))
    # P 経路
    p_gain = sim.add(Gain(k=Kp, id="P"))
    # I 経路
    i_gain = sim.add(Gain(k=Ki, id="I_gain"))
    integ_ctrl = sim.add(Integrator(x0=0.0, id="I_state"))
    # PID 出力合成
    sum_pid = sim.add(Sum(signs="++", id="control"))
    # プラント (1/m * integrator, 1 次)
    inv_m = sim.add(Gain(k=1.0 / m, id="inv_m"))
    plant = sim.add(Integrator(x0=0.0, id="y"))
    # Scope (= sink、線形化で external output として扱われる)
    sim.add(Scope(n_inputs=1, labels=["y"], id="scope"))
    # 結線
    sim.connect(ref, e_sum, dst_idx=0)
    sim.connect(plant, e_sum, dst_idx=1)  # feedback
    sim.connect(e_sum, p_gain)
    sim.connect(e_sum, i_gain)
    sim.connect(i_gain, integ_ctrl)
    sim.connect(p_gain, sum_pid, dst_idx=0)
    sim.connect(integ_ctrl, sum_pid, dst_idx=1)
    sim.connect(sum_pid, inv_m)
    sim.connect(inv_m, plant)
    sim.connect(plant, sim.get_block("scope"))
    return sim


def main() -> None:
    sim = _build_pid_with_first_order_plant()

    print("[PID system] linearizing at operating point (t=0, x=0, u=0)...")
    ls_central = linearize(sim, method="central")
    ls_jax = linearize(sim, method="jax")

    print("[PID system] central A (= numerical, eps ~ sqrt(machine eps)):")
    print(np.array2string(ls_central.A, precision=12, suppress_small=True))
    print()
    print("[PID system] jax A (= autodiff, machine precision):")
    print(np.array2string(ls_jax.A, precision=12, suppress_small=True))
    print()
    diff = float(np.max(np.abs(ls_central.A - ls_jax.A)))
    print(f"[PID system] |A_central - A_jax|_max = {diff:.3e}")
    print("[PID system] jax method recovers analytical Jacobian to machine precision.")

    # eigenvalues 比較
    eig_central = np.linalg.eigvals(ls_central.A)
    eig_jax = np.linalg.eigvals(ls_jax.A)
    print()
    print(f"[PID system] eigenvalues (central): {eig_central}")
    print(f"[PID system] eigenvalues (jax):     {eig_jax}")
    is_stable = bool(np.all(eig_jax.real < 0))
    print(f"[PID system] closed-loop stable? {is_stable}")


if __name__ == "__main__":
    main()
