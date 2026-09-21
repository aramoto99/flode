"""ADR-0018 §(2) SM-B run path 統合の end-to-end 検証。

Mux/Demux を含むモデルが ``Simulator.run()`` で動作し、Scope に SM-B 信号を直接
繋いだ場合に列展開して記録されること (ADR-0079 §(4)、AC-7) を検証する。
"""

from __future__ import annotations

import numpy as np
import pytest

from flode import Simulator
from flode.blocks import (
    Constant,
    Demux,
    Gain,
    Integrator,
    Mux,
    Scope,
)
from flode.exceptions import BlockSpecError


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
# Scope に SM-B 信号を直接繋ぐと列展開して記録 (ADR-0079 §(4)、AC-7)
# ---------------------------------------------------------------------------


class TestScopeAcceptsVector:
    def test_mux_to_scope_direct_records_n_columns(self) -> None:
        """Mux(3) の出力 (3,) を Scope 1 ポートに直接繋ぐと 3 列 3 ラベルで記録される。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        c0 = sim.add(Constant(value=1.0))
        c1 = sim.add(Constant(value=2.0))
        c2 = sim.add(Constant(value=3.0))
        m = sim.add(Mux(n=3))
        sc = sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect(c0, m, dst_idx=0)
        sim.connect(c1, m, dst_idx=1)
        sim.connect(c2, m, dst_idx=2)
        sim.connect(m, sc)
        sim.run()
        values = np.asarray(sc.values)
        assert values.shape == (6, 3)
        np.testing.assert_allclose(values[:, 0], 1.0)
        np.testing.assert_allclose(values[:, 1], 2.0)
        np.testing.assert_allclose(values[:, 2], 3.0)
        assert sc.column_labels == ["in0[0]", "in0[1]", "in0[2]"]

    def test_scope_label_count_mismatch_is_build_error(self) -> None:
        """明示ラベル数がポート数とも列数とも合わないと build エラー (shape.mismatch)。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        c = sim.add(Constant(value=1.0))
        m = sim.add(Mux(n=3))
        sc = sim.add(Scope(n_inputs=1, labels=["a", "b"], id="sc"))
        sim.connect(c, m, dst_idx=0)
        sim.connect(c, m, dst_idx=1)
        sim.connect(c, m, dst_idx=2)
        sim.connect(m, sc)
        with pytest.raises(BlockSpecError, match="label"):
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
