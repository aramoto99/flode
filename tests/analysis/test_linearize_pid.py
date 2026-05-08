"""ADR-0026: PID 制御モデルの線形化検証 (4 状態抽出)。

PI(D) コントローラを Sum / Gain / Integrator / Derivative + プラントとして
組み立て、状態数と (A, B, C, D) のサイズが期待と一致することを確認する。
"""

from __future__ import annotations

import numpy as np

from pyflw import Simulator, linearize
from pyflw.blocks import (
    Derivative,
    Gain,
    Integrator,
    Scope,
    Sum,
    TransferFunction,
)


class TestPIDControl:
    """PI 制御 + 1 次プラントで合計 2 状態 (Integrator + Plant)。"""

    def test_pi_plant_state_count(self) -> None:
        # 構成:
        #   r → Sum(+,-) → e
        #   e → Gain(Kp) → up
        #   e → Integrator → Gain(Ki) → ui
        #   up + ui → Sum → u
        #   u → Plant (1/(s+1)) → y
        #   y → Sum (feedback)
        Kp = 2.0
        Ki = 0.5

        sim = Simulator(t_end=1.0, dt=0.01)
        err = sim.add(Sum(signs="+-", id="err"))
        kp = sim.add(Gain(k=Kp, id="kp"))
        integ = sim.add(Integrator(id="integ"))
        ki = sim.add(Gain(k=Ki, id="ki"))
        u_sum = sim.add(Sum(signs="++", id="u_sum"))
        plant = sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0], id="plant"))
        sc = sim.add(Scope(id="sc"))

        # err の入力 0 = r (未結線、外部入力)、入力 1 = y (フィードバック)
        sim.connect(err, kp, dst_idx=0)
        sim.connect(err, integ, dst_idx=0)
        sim.connect(integ, ki)
        sim.connect(kp, u_sum, dst_idx=0)
        sim.connect(ki, u_sum, dst_idx=1)
        sim.connect(u_sum, plant)
        sim.connect(plant, sc)
        sim.connect(plant, err, dst_idx=1)

        ls = linearize(sim)
        # 連続状態 = Integrator + Plant = 2
        assert ls.A.shape == (2, 2)
        # 外部入力 = err.in[0] (reference) のみ = 1
        assert ls.B.shape == (2, 1)
        # 外部出力 = plant.out[0] (Scope を駆動 + err にも繋がるが、Scope を駆動するので
        # 「外部出力」として認定される)
        assert ls.C.shape[0] == 1
        # state_names は Integrator + Plant 順
        assert ls.state_names[0] == "integ.x[0]"
        assert ls.state_names[1].startswith("plant.x[")


class TestStateNamesOrdering:
    """state_names が連続ブロックの **登録順** を反映する。"""

    def test_register_order(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        # 登録順: Integrator → TransferFunction
        i1 = sim.add(Integrator(id="i1"))
        tf = sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 2.0, 1.0], id="tf2"))
        i2 = sim.add(Integrator(id="i2"))
        # 結線: i1 → tf → i2 → Scope
        sim.connect(i1, tf)
        sim.connect(tf, i2)
        sim.connect(i2, sim.add(Scope()))
        ls = linearize(sim)
        # 状態は登録順: i1 (1 state) + tf (2 states) + i2 (1 state) = 4
        assert ls.state_names == [
            "i1.x[0]",
            "tf2.x[0]",
            "tf2.x[1]",
            "i2.x[0]",
        ]
        assert ls.A.shape == (4, 4)


class TestDerivative:
    """``Derivative`` ブロック (1 状態) を含むモデルで線形化が動く。"""

    def test_derivative_block_in_loop(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        d = sim.add(Derivative(id="d"))
        sim.connect(d, sim.add(Scope()))
        ls = linearize(sim)
        # Derivative は内部に 1 状態 (high-pass filter approximation)
        assert ls.A.shape[0] >= 1
        # 数値が finite
        assert np.all(np.isfinite(ls.A))
        assert np.all(np.isfinite(ls.B))
        assert np.all(np.isfinite(ls.C))
        assert np.all(np.isfinite(ls.D))
