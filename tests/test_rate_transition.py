"""``RateTransition`` block (ADR-0036 §(1)) のテスト。

- ``mode="zoh"`` (fast-to-slow ラッチ): 出力周期で現入力をラッチして保持
- ``mode="delay"`` (slow-to-fast 1-step 遅延): UnitDelay 風に前回入力を出力
- ``mode="auto"``: input/output sample_time から自動決定
- 不正引数のバリデーション (= 同一レート / 0 以下 / 不正 mode)
- ``Simulator`` 経由でのマルチレート動作確認

ADR-0036 §(8) 数値完全不変ガード: 既存 949 件は本 ADR で書き換えない (= 新規
テストのみ追加)。``examples/spring_mass_damper.py`` の数値も完全不変。
"""

from __future__ import annotations

import numpy as np
import pytest

from pyflw import Simulator
from pyflw.blocks import (
    Clock,
    Constant,
    RateTransition,
    Scope,
    UnitDelay,
)
from pyflw.exceptions import BlockSpecError

# ---------------------------------------------------------------------------
# 単体: コンストラクタ
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_auto_mode_fast_to_slow_resolves_to_zoh(self) -> None:
        rt = RateTransition(input_sample_time=0.01, output_sample_time=0.05)
        assert rt.mode == "zoh"

    def test_auto_mode_slow_to_fast_resolves_to_delay(self) -> None:
        rt = RateTransition(input_sample_time=0.05, output_sample_time=0.01)
        assert rt.mode == "delay"

    def test_explicit_zoh_mode(self) -> None:
        rt = RateTransition(input_sample_time=0.05, output_sample_time=0.01, mode="zoh")
        assert rt.mode == "zoh"

    def test_explicit_delay_mode(self) -> None:
        rt = RateTransition(input_sample_time=0.01, output_sample_time=0.05, mode="delay")
        assert rt.mode == "delay"

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="mode must be one of"):
            RateTransition(input_sample_time=0.01, output_sample_time=0.05, mode="invalid")

    def test_same_sample_time_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="must differ"):
            RateTransition(input_sample_time=0.05, output_sample_time=0.05)

    def test_zero_input_sample_time_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="must be > 0"):
            RateTransition(input_sample_time=0.0, output_sample_time=0.05)

    def test_negative_input_sample_time_raises(self) -> None:
        # -1.0 (継承) 以外の負値は禁止
        with pytest.raises(BlockSpecError, match="must be > 0"):
            RateTransition(input_sample_time=-0.5, output_sample_time=0.05)

    def test_inheritance_with_auto_mode_raises(self) -> None:
        # auto mode は明示的な正値を要求 (継承との組み合わせは BlockSpecError)
        with pytest.raises(BlockSpecError, match="auto.*must both be positive"):
            RateTransition(input_sample_time=-1.0, output_sample_time=0.05, mode="auto")

    def test_inheritance_with_explicit_mode_ok(self) -> None:
        # mode を明示すれば継承 -1.0 を受け付ける (将来 Simulator 統合用)
        rt = RateTransition(input_sample_time=-1.0, output_sample_time=0.05, mode="zoh")
        assert rt.mode == "zoh"

    def test_default_x0_is_zero(self) -> None:
        rt = RateTransition(input_sample_time=0.01, output_sample_time=0.05)
        np.testing.assert_array_equal(rt.x0, np.array([0.0, 0.0]))

    def test_explicit_x0(self) -> None:
        rt = RateTransition(input_sample_time=0.01, output_sample_time=0.05, x0=7.5)
        np.testing.assert_array_equal(rt.x0, np.array([7.5, 7.5]))

    def test_resolved_sample_time_is_output_sample_time(self) -> None:
        # ADR-0036 §(1): 下流レートで fire するため _resolved_sample_time = output_sample_time
        rt = RateTransition(input_sample_time=0.01, output_sample_time=0.05)
        assert rt._params["output_sample_time"] == 0.05
        assert rt.sample_time == 0.05  # = sample_time 引数経由


# ---------------------------------------------------------------------------
# 単体: output / update
# ---------------------------------------------------------------------------


class TestOutputUpdate:
    def test_output_returns_state0(self) -> None:
        rt = RateTransition(input_sample_time=0.01, output_sample_time=0.05)
        x = np.array([3.0, 5.0])
        u = np.array([99.0])  # u は output で参照されない
        np.testing.assert_array_equal(rt.output(0.0, x, u), np.array([3.0]))

    def test_update_rotates_state(self) -> None:
        # ADR-0015 §(2) 同様の 2-state ローテーション: state[0]<-state[1], state[1]<-u
        rt = RateTransition(input_sample_time=0.01, output_sample_time=0.05)
        x = np.array([3.0, 5.0])
        u = np.array([7.0])
        np.testing.assert_array_equal(rt.update(0.0, x, u), np.array([5.0, 7.0]))

    def test_update_zoh_and_delay_use_same_rotation(self) -> None:
        # ADR-0036 §(1): mode は出力フェーズで違わない (= 両モードとも 2-state
        # ローテーション、違いは下流レートで fire することで実効的に zoh / delay
        # に見える)
        rt_zoh = RateTransition(input_sample_time=0.01, output_sample_time=0.05, mode="zoh")
        rt_delay = RateTransition(input_sample_time=0.05, output_sample_time=0.01, mode="delay")
        x = np.array([2.0, 3.0])
        u = np.array([4.0])
        np.testing.assert_array_equal(rt_zoh.update(0.0, x, u), rt_delay.update(0.0, x, u))


# ---------------------------------------------------------------------------
# 統合: Simulator 経由でマルチレート動作
# ---------------------------------------------------------------------------


class TestSimulatorIntegration:
    def test_fast_to_slow_zoh_in_simulator(self) -> None:
        """fast (0.01) clock → RateTransition(zoh) → slow (0.05) Scope。

        Scope (= 連続 sink で dt_base=0.01 ごとに記録) で出力を観測。
        RateTransition は output_sample_time=0.05 で fire するので、その出力は
        サンプル境界 (k=0, 5, 10, ...) で更新され、間は前回値を保持する
        (= 階段状)。ADR-0015 §(2) の 2-state ローテーションで 1-output-period 遅延、
        つまり t=0.10 での出力 (= idx 10) で初めて clock(0.05)=0.05 が見える。
        """
        sim = Simulator(t_end=0.25, dt=0.01)
        clk = sim.add(Clock(id="clk"))
        rt = sim.add(
            RateTransition(input_sample_time=0.01, output_sample_time=0.05, x0=0.0, id="rt")
        )
        sc = sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect(clk, rt)
        sim.connect(rt, sc)
        sim.run()

        # Scope は dt_base=0.01 で 26 sample (t=0..0.25)。
        values = np.asarray(sc.values).reshape(-1)
        assert len(values) == 26
        # idx 0..4 (t=0..0.04): x0=0 で初期化
        assert all(v == pytest.approx(0.0) for v in values[0:5])
        # idx 5..9 (t=0.05..0.09): 第 1 fire 後、まだ x[0] 側は 0
        assert all(v == pytest.approx(0.0) for v in values[5:10])
        # idx 10..14 (t=0.10..0.14): 第 2 fire 後、x[0] = clock(0.05) = 0.05
        assert all(v == pytest.approx(0.05, abs=1e-9) for v in values[10:15])
        # idx 15..19: x[0] = clock(0.10) = 0.10
        assert all(v == pytest.approx(0.10, abs=1e-9) for v in values[15:20])
        # idx 20..24: x[0] = clock(0.15) = 0.15
        assert all(v == pytest.approx(0.15, abs=1e-9) for v in values[20:25])

    def test_rate_transition_equivalent_to_unit_delay_at_same_rate(self) -> None:
        """RateTransition と UnitDelay が同じ output_sample_time で同じ挙動。

        RateTransition の動作は ADR-0015 §(2) の 2-state ローテーションと同一
        なので、同じ sample_time なら UnitDelay と一致する (= Simulink の
        rate-matched RateTransition は実効 UnitDelay)。
        """
        sim = Simulator(t_end=0.1, dt=0.01)
        clk = sim.add(Clock(id="clk"))
        rt = sim.add(
            RateTransition(
                input_sample_time=0.005,
                output_sample_time=0.01,
                x0=99.0,
                id="rt",
            )
        )
        ud = sim.add(UnitDelay(sample_time=0.01, x0=99.0, id="ud"))
        rt_sc = sim.add(Scope(n_inputs=1, id="rt_sc"))
        ud_sc = sim.add(Scope(n_inputs=1, id="ud_sc"))
        sim.connect(clk, rt)
        sim.connect(clk, ud)
        sim.connect(rt, rt_sc)
        sim.connect(ud, ud_sc)
        sim.run()

        rt_vals = np.asarray(rt_sc.values).reshape(-1)
        ud_vals = np.asarray(ud_sc.values).reshape(-1)
        np.testing.assert_array_equal(rt_vals, ud_vals)

    def test_constant_through_rate_transition(self) -> None:
        """定数入力 → RateTransition → 2 サンプル後 (= 2-state ローテーション完了) で 42 になる。"""
        sim = Simulator(t_end=0.25, dt=0.01)
        c = sim.add(Constant(value=42.0, id="c"))
        rt = sim.add(
            RateTransition(input_sample_time=0.01, output_sample_time=0.05, x0=0.0, id="rt")
        )
        sc = sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect(c, rt)
        sim.connect(rt, sc)
        sim.run()

        values = np.asarray(sc.values).reshape(-1)
        # idx 0..4: x0=0 (= 第 1 fire 後 state[0]=0 のまま、Constant は t=0 で
        # 既に 42 を吐いているので state[1]=42 に上書きされる)
        assert all(v == pytest.approx(0.0) for v in values[0:5])
        # idx 5 以降: 第 2 fire (k=5) で state[0]=42 にローテートされる
        assert all(v == pytest.approx(42.0) for v in values[5:])


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_save_load_round_trip_zoh(self, tmp_path) -> None:
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(
            RateTransition(
                input_sample_time=0.01,
                output_sample_time=0.05,
                mode="zoh",
                x0=1.5,
                id="rt",
            )
        )
        path = tmp_path / "rt.flw.json"
        sim.save(path)

        sim2 = Simulator.load(path)
        rt2 = sim2.get_block("rt")
        assert isinstance(rt2, RateTransition)
        assert rt2.mode == "zoh"
        assert rt2.input_sample_time == 0.01
        assert rt2.output_sample_time == 0.05
        np.testing.assert_array_equal(rt2.x0, np.array([1.5, 1.5]))

    def test_save_load_round_trip_delay(self, tmp_path) -> None:
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(
            RateTransition(
                input_sample_time=0.05,
                output_sample_time=0.01,
                mode="delay",
                id="rt",
            )
        )
        path = tmp_path / "rt.flw.json"
        sim.save(path)

        sim2 = Simulator.load(path)
        rt2 = sim2.get_block("rt")
        assert isinstance(rt2, RateTransition)
        assert rt2.mode == "delay"
