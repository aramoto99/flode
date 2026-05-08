"""ADR-0027 §(11) サンプル: PID 制御モデルの線形化 → Bode 線図 + 安定性。

PI 制御 + 1 次プラント (1/(s+1)) のフィードバックループを構築し、
``pyflw.linearize()`` で線形化、``bode()`` / ``is_stable()`` /
``eigenvalues()`` を呼んで結果を可視化する。

実行:
    python examples/pid_bode.py
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np

from pyflw import Simulator, bode, eigenvalues, is_stable, linearize
from pyflw.blocks import Gain, Integrator, Scope, Sum, TransferFunction


def build_pi_loop(Kp: float = 2.0, Ki: float = 0.5) -> Simulator:
    """PI コントローラ + 1 次プラントのフィードバックループ。

    構成:
        r → Sum(+,-) → e
        e → Gain(Kp) → up
        e → Integrator → Gain(Ki) → ui
        up + ui → Sum → u
        u → Plant (1/(s+1)) → y
        y → Sum (feedback)

    Args:
        Kp: 比例ゲイン。
        Ki: 積分ゲイン。

    Returns:
        建立済みの ``Simulator``。
    """
    sim = Simulator(t_end=10.0, dt=0.01)
    err = sim.add(Sum(signs="+-", id="err"))
    kp = sim.add(Gain(k=Kp, id="kp"))
    integ = sim.add(Integrator(id="integ"))
    ki = sim.add(Gain(k=Ki, id="ki"))
    u_sum = sim.add(Sum(signs="++", id="u_sum"))
    plant = sim.add(
        TransferFunction(numerator=[1.0], denominator=[1.0, 1.0], id="plant")
    )
    sc = sim.add(Scope(id="sc"))

    sim.connect(err, kp, dst_idx=0)
    sim.connect(err, integ, dst_idx=0)
    sim.connect(integ, ki)
    sim.connect(kp, u_sum, dst_idx=0)
    sim.connect(ki, u_sum, dst_idx=1)
    sim.connect(u_sum, plant)
    sim.connect(plant, sc)
    sim.connect(plant, err, dst_idx=1)
    return sim


def main() -> None:
    sim = build_pi_loop(Kp=2.0, Ki=0.5)
    ls = linearize(sim)

    print("=" * 60)
    print("PI + 1st-order plant feedback loop, linearised at (t=0, x=x0, u=0)")
    print("=" * 60)
    print(f"State dimension: {ls.A.shape[0]}")
    print(f"  state names:  {ls.state_names}")
    print(f"  input names:  {ls.input_names}")
    print(f"  output names: {ls.output_names}")
    print()
    print("Closed-loop A matrix:")
    print(ls.A)
    print()
    eigs = eigenvalues(ls)
    print(f"Eigenvalues: {eigs}")
    print(f"Asymptotically stable? {is_stable(ls)}")
    print()

    # Bode line plot
    omega = np.logspace(-2, 2, 200)
    br = bode(ls, omega=omega)

    fig, axes = plt.subplots(2, 1, sharex=True, figsize=(8, 6))
    ax_mag, ax_phase = axes
    ax_mag.semilogx(br.omega, br.magnitude_db()[0, 0, :])
    ax_mag.set_ylabel("magnitude [dB]")
    ax_mag.grid(True, which="both", linestyle=":")
    ax_mag.set_title("Bode plot: r → y (closed loop)")

    ax_phase.semilogx(br.omega, np.degrees(br.phase[0, 0, :]))
    ax_phase.set_xlabel("ω [rad/s]")
    ax_phase.set_ylabel("phase [deg]")
    ax_phase.grid(True, which="both", linestyle=":")

    fig.tight_layout()
    out_path = "pid_bode.png"
    fig.savefig(out_path)
    print(f"Saved {out_path}")


if __name__ == "__main__":
    main()
