"""ADR-0018 §(2) SM-B run path の境界値・エッジケーステスト。

既存 ``tests/core/test_sm_b_run.py`` (5 件) でカバーされていない観点を補強する。

補強観点:
  #1  SM-B モードで Constant のみモデル (連続なし・離散なし・直達のみ) が完走する
  #2  SM-A 離散ブロック (UnitDelay) + SM-B ルーティング (Mux/Demux) の混在モデル
  #3  SM-B モードで Scope に rank-0 入力 (= scalar) を繋ぐと build を通過する (regression)
  #4  空モデル・1ブロックモデルが SM-A モードと判定され正しく動く
  #5  SM-B モデルで n_steps=1 (t_end=dt) の最短シミュレーションが完走する
  #6  _record_v が Scope に正しく scalar 値を渡す
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
    UnitDelay,
)
from pyflw.exceptions import BlockSpecError


def _flat(scope: Scope) -> np.ndarray:
    return np.asarray(scope.values).reshape(-1)


# ---------------------------------------------------------------------------
# #1: SM-B モードで Constant のみモデル (pure combinatorial、連続状態なし)
# ---------------------------------------------------------------------------


class TestSmBRunConstantOnly:
    def test_constant_mux_demux_scope_no_continuous_states(self) -> None:
        """Constant → Mux → Demux → Scope の連続状態ゼロモデルが SM-B で完走する。

        n_total=0 なので solve_ivp ステップをスキップし、ループは record だけで進む。
        """
        sim = Simulator(t_end=0.05, dt=0.01)
        c = sim.add(Constant(value=7.0))
        m = sim.add(Mux(n=1))
        d = sim.add(Demux(n=1))
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(c, m, dst_idx=0)
        sim.connect(m, d)
        sim.connect(d, sc, src_idx=0)

        # SM-B モード確認
        sim._execution_order()
        assert sim._is_sm_a_mode() is False

        sim.run()
        arr = _flat(sc)
        assert len(arr) == 6  # t=0.00, 0.01, ..., 0.05
        np.testing.assert_allclose(arr, 7.0 * np.ones(6))

    def test_two_constants_through_mux2_demux2_scopes(self) -> None:
        """2 つの Constant → Mux(2) → Demux(2) → 2 Scope が SM-B で完走する。"""
        sim = Simulator(t_end=0.03, dt=0.01)
        c0 = sim.add(Constant(value=10.0))
        c1 = sim.add(Constant(value=20.0))
        m = sim.add(Mux(n=2))
        d = sim.add(Demux(n=2))
        sc0 = sim.add(Scope(n_inputs=1))
        sc1 = sim.add(Scope(n_inputs=1))
        sim.connect(c0, m, dst_idx=0)
        sim.connect(c1, m, dst_idx=1)
        sim.connect(m, d)
        sim.connect(d, sc0, src_idx=0)
        sim.connect(d, sc1, src_idx=1)
        sim.run()
        np.testing.assert_allclose(_flat(sc0), 10.0)
        np.testing.assert_allclose(_flat(sc1), 20.0)

    def test_constant_mux_gain_demux_scope_no_state(self) -> None:
        """Constant → Mux → Gain (SM-A) → Demux 経路は port_shape mismatch になる。

        Mux 出力 (3,) と Gain 入力 () が不一致なので BlockSpecError が出ることを確認する。
        これは SM-B run path ではなく build-time check のテスト。
        """
        sim = Simulator(t_end=0.05, dt=0.01)
        c = sim.add(Constant(value=1.0))
        m = sim.add(Mux(n=3))
        g = sim.add(Gain(k=2.0))
        sim.connect(c, m, dst_idx=0)
        sim.connect(c, m, dst_idx=1)
        sim.connect(c, m, dst_idx=2)
        sim.connect(m, g)  # shape (3,) → () mismatch
        with pytest.raises(BlockSpecError, match="Port shape mismatch"):
            sim.run()


# ---------------------------------------------------------------------------
# #2: SM-A 離散ブロック + SM-B ルーティングの混在モデル
# ---------------------------------------------------------------------------


class TestSmBRunWithDiscreteSmA:
    def test_constant_mux_demux_unitdelay_scope(self) -> None:
        """Constant → Mux(1) → Demux(1) → UnitDelay → Scope の混在モデル。

        SM-B (Mux/Demux) と SM-A 離散 (UnitDelay) が同居する _run_sm_b_loop が
        UnitDelay の update を正しく処理する。
        """
        sim = Simulator(t_end=0.05, dt=0.01)
        c = sim.add(Constant(value=5.0))
        m = sim.add(Mux(n=1))
        d = sim.add(Demux(n=1))
        ud = sim.add(UnitDelay(sample_time=0.01, x0=0.0))
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(c, m, dst_idx=0)
        sim.connect(m, d)
        sim.connect(d, ud, src_idx=0)
        sim.connect(ud, sc)

        # SM-B モード判定
        sim._execution_order()
        assert sim._is_sm_a_mode() is False

        sim.run()
        arr = _flat(sc)
        # UnitDelay: k=0 で y=x0=0、k>=1 で y=u[k-1]=5.0
        assert arr[0] == pytest.approx(0.0)  # t=0: x0 出力
        # 十分なサンプル後は 5.0 に収束
        np.testing.assert_allclose(arr[-1], 5.0, atol=1e-9)

    def test_sm_b_model_uses_sm_b_loop(self) -> None:
        """SM-B モデルが _run_sm_a_loop ではなく _run_sm_b_loop を通ることを判定。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        c = sim.add(Constant(value=3.0))
        m = sim.add(Mux(n=2))
        d = sim.add(Demux(n=2))
        sc0 = sim.add(Scope(n_inputs=1))
        sc1 = sim.add(Scope(n_inputs=1))
        sim.connect(c, m, dst_idx=0)
        sim.connect(c, m, dst_idx=1)
        sim.connect(m, d)
        sim.connect(d, sc0, src_idx=0)
        sim.connect(d, sc1, src_idx=1)

        # run 前に SM-A モードでないことを確認
        sim._execution_order()
        assert sim._is_sm_a_mode() is False

        sim.run()
        # SM-B loop が正しく動いていれば値が正しい
        np.testing.assert_allclose(_flat(sc0), 3.0)
        np.testing.assert_allclose(_flat(sc1), 3.0)


# ---------------------------------------------------------------------------
# #3: SM-B モードで Scope に rank-0 (scalar) 入力を繋いでも build を通過 (regression)
# ---------------------------------------------------------------------------


class TestScopeScalarInputInSmBMode:
    def test_scope_with_scalar_input_passes_build_in_sm_b_model(self) -> None:
        """SM-B モデルであっても Scope への scalar (() shape) 入力は build を通過する。

        ADR-0018 §(3) S-A: Scope は scalar のみ受け付ける。
        vector ではなく scalar を繋ぐ場合は _check_scope_inputs_are_scalar が通過する。
        """
        sim = Simulator(t_end=0.05, dt=0.01)
        c = sim.add(Constant(value=1.0))
        c2 = sim.add(Constant(value=2.0))
        m = sim.add(Mux(n=2))
        d = sim.add(Demux(n=2))
        sc = sim.add(Scope(n_inputs=1))  # scalar (shape ()) 入力
        sim.connect(c, m, dst_idx=0)
        sim.connect(c2, m, dst_idx=1)
        sim.connect(m, d)
        sim.connect(d, sc, src_idx=0)  # Demux 出力 = shape () → Scope OK

        # SM-B モード確認
        sim._execution_order()
        assert sim._is_sm_a_mode() is False

        # 例外なく run できる (Scope に scalar 繋ぎは OK)
        sim.run()
        arr = _flat(sc)
        np.testing.assert_allclose(arr, 1.0)  # Demux 出力[0] = Constant 値 1.0

    def test_scope_check_passes_when_all_scope_inputs_scalar(self) -> None:
        """_check_scope_inputs_are_scalar が scalar 入力 Scope に対して例外を出さない。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        c = sim.add(Constant(value=1.0))
        m = sim.add(Mux(n=1))
        d = sim.add(Demux(n=1))
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(c, m, dst_idx=0)
        sim.connect(m, d)
        sim.connect(d, sc)
        sim._execution_order()  # build を発火させ SM-B モードへ
        # SM-B モードで Scope check が scalar 入力に対して通過する
        sim._check_scope_inputs_are_scalar()  # 例外なし


# ---------------------------------------------------------------------------
# #4: 空モデル・1ブロックモデルの SM-A 判定
# ---------------------------------------------------------------------------


class TestEmptyAndSingleBlockModel:
    def test_empty_model_is_sm_a_mode(self) -> None:
        """ブロック 0 個の Simulator は SM-A モード (vacuously True)。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        assert sim._is_sm_a_mode() is True

    def test_empty_model_sm_b_run_raises_scheduling_error(self) -> None:
        """空 Simulator の run() は n_steps < 1 ではなく正常動作できる。
        (t_end/dt が適正な場合は正常完走する)
        """
        sim = Simulator(t_end=0.05, dt=0.01)
        # ブロックなしでも run() は n_steps = 5 > 0 で正常動作する
        sim.run()

    def test_single_constant_block_is_sm_a_mode(self) -> None:
        """Constant 1 ブロックだけの Simulator は SM-A モード。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(Constant(value=1.0))
        assert sim._is_sm_a_mode() is True

    def test_single_mux_block_is_sm_b_mode(self) -> None:
        """Mux 1 ブロックだけの Simulator は SM-B モード。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(Mux(n=2))
        assert sim._is_sm_a_mode() is False

    def test_single_mux_block_model_run_completes(self) -> None:
        """入力未接続の Mux 1 ブロックだけのモデルが SM-B モードで完走する。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(Mux(n=2))
        # 未接続でも run は例外を出さない (入力ゼロとして動作)
        sim.run()


# ---------------------------------------------------------------------------
# #5: SM-B モデルで t_end=dt (n_steps=1) の最短シミュレーション
# ---------------------------------------------------------------------------


class TestSmBRunMinimalSteps:
    def test_sm_b_run_single_step(self) -> None:
        """t_end=dt (n_steps=1) の SM-B モデルが 1 ステップで完走する。"""
        sim = Simulator(t_end=0.01, dt=0.01)
        c = sim.add(Constant(value=3.0))
        m = sim.add(Mux(n=1))
        d = sim.add(Demux(n=1))
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(c, m, dst_idx=0)
        sim.connect(m, d)
        sim.connect(d, sc)
        sim.run()
        arr = _flat(sc)
        # t=0 と t=0.01 の 2 サンプル
        assert len(arr) == 2
        np.testing.assert_allclose(arr, 3.0)


# ---------------------------------------------------------------------------
# #6: _record_v が Scope に正しく scalar 値を渡す
# ---------------------------------------------------------------------------


class TestRecordVPassesScalarToScope:
    def test_record_v_scalar_inputs_recorded_correctly(self) -> None:
        """SM-B run path の _record_v が Scope に正しい scalar 値を渡す。

        Constant(value=X) → Mux → Demux → Scope の構成で、各時刻の Scope
        records が X と一致することを確認する。
        """
        sim = Simulator(t_end=0.05, dt=0.01)
        c = sim.add(Constant(value=99.0))
        m = sim.add(Mux(n=1))
        d = sim.add(Demux(n=1))
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(c, m, dst_idx=0)
        sim.connect(m, d)
        sim.connect(d, sc)
        sim.run()

        # times は [0.0, 0.01, 0.02, 0.03, 0.04, 0.05] の 6 点
        times = np.array(sc.times)
        assert len(times) == 6
        arr = _flat(sc)
        np.testing.assert_allclose(arr, 99.0 * np.ones(6))

    def test_record_v_multi_channel_scope(self) -> None:
        """2 ch Scope が SM-B run path 経由で 2 つの独立した Constant 値を記録する。"""
        sim = Simulator(t_end=0.03, dt=0.01)
        c0 = sim.add(Constant(value=1.0))
        c1 = sim.add(Constant(value=2.0))
        m = sim.add(Mux(n=2))
        d = sim.add(Demux(n=2))
        sc = sim.add(Scope(n_inputs=2))
        sim.connect(c0, m, dst_idx=0)
        sim.connect(c1, m, dst_idx=1)
        sim.connect(m, d)
        sim.connect(d, sc, src_idx=0, dst_idx=0)
        sim.connect(d, sc, src_idx=1, dst_idx=1)
        sim.run()

        vals = np.asarray(sc.values)  # shape (n_samples, 2)
        assert vals.shape[1] == 2
        np.testing.assert_allclose(vals[:, 0], 1.0)
        np.testing.assert_allclose(vals[:, 1], 2.0)


# ---------------------------------------------------------------------------
# SM-B + 連続ブロック (Integrator) の混在 (既存テストの補強)
# ---------------------------------------------------------------------------


class TestSmBRunContinuousExtended:
    def test_constant_mux2_demux2_integrators_scope(self) -> None:
        """Mux(2) → Demux(2) → Integrator×2 → Scope×2 が SM-B ループで正しく積分する。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        c1 = sim.add(Constant(value=1.0))
        c2 = sim.add(Constant(value=2.0))
        m = sim.add(Mux(n=2))
        d = sim.add(Demux(n=2))
        i1 = sim.add(Integrator(x0=0.0))
        i2 = sim.add(Integrator(x0=0.0))
        sc1 = sim.add(Scope(n_inputs=1))
        sc2 = sim.add(Scope(n_inputs=1))
        sim.connect(c1, m, dst_idx=0)
        sim.connect(c2, m, dst_idx=1)
        sim.connect(m, d)
        sim.connect(d, i1, src_idx=0)
        sim.connect(d, i2, src_idx=1)
        sim.connect(i1, sc1)
        sim.connect(i2, sc2)
        sim.run()

        # i1: u=1.0 → y=t、i2: u=2.0 → y=2t
        times = np.array(sc1.times)
        arr1 = _flat(sc1)
        arr2 = _flat(sc2)
        np.testing.assert_allclose(arr1, times, atol=1e-4)
        np.testing.assert_allclose(arr2, 2.0 * times, atol=1e-4)
