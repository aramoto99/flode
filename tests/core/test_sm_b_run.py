"""ADR-0018 §(2) SM-B run path 統合の end-to-end 検証。

Mux/Demux を含むモデルが ``Simulator.run()`` で動作し、Scope に SM-B 信号を直接
繋いだ場合に build 時 ``BlockSpecError`` で拒否されることを検証する。
"""

from __future__ import annotations

import numpy as np
import pytest

from pyflw import Simulator
from pyflw.blocks import (
    Constant,
    Demux,
    Gain,
    Integrator,
    Mux,
    Scope,
)
from pyflw.exceptions import BlockSpecError


def _flat(scope: Scope) -> np.ndarray:
    return np.asarray(scope.values).reshape(-1)


# ---------------------------------------------------------------------------
# Mux → Demux end-to-end 動作
# ---------------------------------------------------------------------------


class TestSmBRunBasic:
    def test_three_constants_through_mux_demux(self) -> None:
        """3 つの Constant → Mux(3) → Demux(3) → Scope×3 が SM-B run で完走。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        c0 = sim.add(Constant(value=1.0))
        c1 = sim.add(Constant(value=2.0))
        c2 = sim.add(Constant(value=3.0))
        m = sim.add(Mux(n=3))
        d = sim.add(Demux(n=3))
        sc0 = sim.add(Scope(n_inputs=1))
        sc1 = sim.add(Scope(n_inputs=1))
        sc2 = sim.add(Scope(n_inputs=1))
        sim.connect(c0, m, dst_idx=0)
        sim.connect(c1, m, dst_idx=1)
        sim.connect(c2, m, dst_idx=2)
        sim.connect(m, d)
        sim.connect(d, sc0, src_idx=0)
        sim.connect(d, sc1, src_idx=1)
        sim.connect(d, sc2, src_idx=2)

        # SM-B モード判定
        sim._execution_order()  # build を発火
        assert sim._is_sm_a_mode() is False

        sim.run()
        np.testing.assert_allclose(_flat(sc0), 1.0)
        np.testing.assert_allclose(_flat(sc1), 2.0)
        np.testing.assert_allclose(_flat(sc2), 3.0)


# ---------------------------------------------------------------------------
# 連続ブロックを SM-B run path で動かす (互換 wrapper 経由)
# ---------------------------------------------------------------------------


class TestSmBRunWithContinuous:
    def test_constant_mux_demux_integrator_chain(self) -> None:
        """SM-B run path 内の f_continuous_vector 互換 wrapper が動く。

        Constant → Mux(2) → Demux(2) → Integrator → Scope の構成で、Mux/Demux で
        SM-B モード判定が走る。Integrator は SM-A の derivative を持つが、
        f_continuous_vector が tuple → 1D ndarray 変換 wrapper を介して呼ぶ。
        """
        sim = Simulator(t_end=0.1, dt=0.01)
        c0 = sim.add(Constant(value=1.0))
        c1 = sim.add(Constant(value=0.0))
        m = sim.add(Mux(n=2))
        d = sim.add(Demux(n=2))
        integ = sim.add(Integrator(x0=0.0))
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(c0, m, dst_idx=0)
        sim.connect(c1, m, dst_idx=1)
        sim.connect(m, d)
        sim.connect(d, integ, src_idx=0)  # Demux 出力 0 = u(0) = 1.0
        sim.connect(integ, sc)
        sim.run()

        # SM-B モードでも Integrator(u=1) は y=t を返す
        arr = _flat(sc)
        times = np.array(sc.times)
        for i in range(len(arr)):
            assert arr[i] == pytest.approx(times[i], abs=1e-6)


# ---------------------------------------------------------------------------
# Scope に SM-B 信号を直接繋ぐと build 時拒否
# ---------------------------------------------------------------------------


class TestScopeRejectsSmB:
    def test_mux_to_scope_direct_raises(self) -> None:
        """Mux の出力 (vector) を Scope に直接繋ぐと build 時 ``BlockSpecError``。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        c0 = sim.add(Constant(value=1.0))
        c1 = sim.add(Constant(value=2.0))
        m = sim.add(Mux(n=2))
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(c0, m, dst_idx=0)
        sim.connect(c1, m, dst_idx=1)
        # Scope.port_shapes_in = ((),) なので shape mismatch (Mux out = (2,))
        sim.connect(m, sc)
        with pytest.raises(BlockSpecError, match="Port shape mismatch"):
            sim.run()

    def test_scope_only_accepts_scalar_message(self) -> None:
        """SM-B モードで build 時 Scope check が走り、Demux 誘導メッセージが出る。

        ここでは Scope の port_shapes_in を直接 vector に書き換えて build を呼ぶ
        (= 通常の `connect` だと先に shape mismatch エラーが出るため)。
        """

        # port_shapes_in を直接 SM-B にしたカスタム Scope (テスト用)
        # 通常ユーザーはこの状況に陥らないが、Simulator._check_scope_inputs_are_scalar の
        # メッセージを直接検証する。
        class _BadScope(Scope):
            _serialize_port_shapes = False

            def __init__(self, n_inputs: int = 1, *, id: str | None = None) -> None:
                super().__init__(n_inputs=n_inputs, id=id)
                # 強制的に SM-B 入力に書き換え (= テスト目的)
                self.port_shapes_in = ((3,),)

        sim = Simulator(t_end=0.05, dt=0.01)
        # SM-B モード判定が true になるよう Mux を 1 つ含める
        c = sim.add(Constant(value=1.0))
        m = sim.add(Mux(n=3))
        sim.add(_BadScope(id="bad"))
        # Mux の出力 (3,) を _BadScope.in[0] (3,) に繋ぐ → shape は一致
        sim.connect(c, m, dst_idx=0)
        sim.connect(c, m, dst_idx=1)
        sim.connect(c, m, dst_idx=2)
        sim.connect(m, "bad")
        with pytest.raises(BlockSpecError, match="Scope only accepts scalar"):
            sim.run()


# ---------------------------------------------------------------------------
# SM-A only モデルは SM-A hot path で動く (回帰防止)
# ---------------------------------------------------------------------------


class TestSmAUnchanged:
    def test_pure_sm_a_uses_hot_path(self) -> None:
        sim = Simulator(t_end=0.05, dt=0.01)
        c = sim.add(Constant(value=2.0))
        g = sim.add(Gain(k=3.0))
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(c, g)
        sim.connect(g, sc)
        sim._execution_order()
        assert sim._is_sm_a_mode() is True
        sim.run()
        np.testing.assert_allclose(_flat(sc), 6.0 * np.ones(6))
