"""ADR-0026 §(8): Subsystem を含むモデルの線形化。

Subsystem は外側 Block 契約 (``Subsystem.output`` / ``Subsystem.derivative``) に
対する Jacobian を取るだけで自動展開される。内部状態が flat A 行列に正しく
対応するかを検証する。
"""

from __future__ import annotations

import numpy as np

from pyflw import Inport, Outport, Simulator, Subsystem, linearize
from pyflw.blocks import Gain, Integrator, Scope


class TestPlainSubsystem:
    """Inport → Gain → Integrator → Outport を Subsystem 化。"""

    def test_inner_state_flattens_to_subsystem(self) -> None:
        # Subsystem 内部: in → Gain(2) → Integrator → out
        sub = Subsystem(id="sub")
        ip = Inport(port_idx=0)
        op = Outport(port_idx=0)
        g = Gain(k=2.0, id="g_inner")
        i = Integrator(id="i_inner")
        sub.add(ip)
        sub.add(g)
        sub.add(i)
        sub.add(op)
        sub.connect(ip, g)
        sub.connect(g, i)
        sub.connect(i, op)

        # 外側: 単独 Subsystem (入力未結線、出力 Scope へ)
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(sub)
        sim.connect(sub, sim.add(Scope()))

        ls = linearize(sim)
        # Subsystem 内部の連続状態 = Integrator 1 状態
        assert ls.A.shape == (1, 1)
        # 入力 = sub.in[0] (1 dim、Inport 1 つ)
        assert ls.B.shape == (1, 1)
        # 出力 = sub.out[0] (1 dim、Scope 駆動)
        assert ls.C.shape[0] == 1
        # 解析解: x_dot = 2*u (Gain → Integrator)、y = x
        np.testing.assert_allclose(ls.A, [[0.0]], atol=1e-7)
        np.testing.assert_allclose(ls.B, [[2.0]], rtol=1e-4)
        np.testing.assert_allclose(ls.C, [[1.0]], atol=1e-7)
        np.testing.assert_allclose(ls.D, [[0.0]], atol=1e-7)
        # state_names は外側 Subsystem 視点 (= ADR-0026 §(8))
        assert ls.state_names == ["sub.x[0]"]


class TestNestedSubsystem:
    """Subsystem の中に Subsystem を含む 2 階層モデル。"""

    def test_two_levels_flatten(self) -> None:
        # inner: in → Integrator → out
        inner = Subsystem(id="inner")
        inner.add(Inport(port_idx=0))
        inner.add(Integrator(id="i_in"))
        inner.add(Outport(port_idx=0))
        inner.connect("Inport_0", "i_in")
        inner.connect("i_in", "Outport_0")

        # outer: in → Gain → inner → out
        outer = Subsystem(id="outer")
        outer.add(Inport(port_idx=0))
        outer.add(Gain(k=3.0, id="g_out"))
        outer.add(inner)
        outer.add(Outport(port_idx=0))
        outer.connect("Inport_0", "g_out")
        outer.connect("g_out", "inner")
        outer.connect("inner", "Outport_0")

        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(outer)
        sim.connect(outer, sim.add(Scope()))

        ls = linearize(sim)
        # 内部状態は Integrator 1 つだけだが、外側 Subsystem 視点では outer の n_states
        assert ls.A.shape[0] >= 1
        # 解析解: x_dot = 3*u
        np.testing.assert_allclose(ls.B[0, 0], 3.0, rtol=1e-4)
