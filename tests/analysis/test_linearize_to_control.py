"""ADR-0026 §(2): ``LinearSystem.to_control_ss()`` の python-control 連携テスト。

``python-control`` 未インストール時は ``ImportError`` で誘導、インストール済み
環境では ``control.StateSpace`` インスタンスを返すことを確認する。
"""

from __future__ import annotations

import numpy as np
import pytest

from pyflw import Simulator, linearize
from pyflw.blocks import Integrator, Scope


class TestToControlSs:
    def test_returns_control_state_space(self) -> None:
        # python-control 未インストール環境では skip
        control = pytest.importorskip("control")

        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls = linearize(sim)
        ss = ls.to_control_ss()
        # control.StateSpace インスタンス
        assert isinstance(ss, control.StateSpace)
        # 行列が一致 (control 内部で float 配列に変換される)
        np.testing.assert_allclose(np.asarray(ss.A), ls.A)
        np.testing.assert_allclose(np.asarray(ss.B), ls.B)
        np.testing.assert_allclose(np.asarray(ss.C), ls.C)
        np.testing.assert_allclose(np.asarray(ss.D), ls.D)
