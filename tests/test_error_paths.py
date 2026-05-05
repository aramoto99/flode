"""エラーパス・境界値・回帰の網羅テスト。

補強観点:
1. エラーパス  — 既存テストで未カバーの例外経路
2. 境界値      — ID 長・sample_time 境界
3. マルチレート — 3 レート以上混在、連続+離散+継承の三段組み
4. 回帰        — Block 基底の default 実装、read-only 属性、Scope 記録回数
5. 継承 warning — 混在上流からの継承警告
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from pyflw import (
    BlockSpecError,
    Simulator,
    UnknownBlockIdError,
)
from pyflw.blocks import Constant, Gain, Scope, Sine, UnitDelay
from pyflw.core.block import Block
from pyflw.exceptions import AlgebraicLoopError, SchedulingError

# ---------------------------------------------------------------------------
# 1. エラーパス
# ---------------------------------------------------------------------------


class TestSimulatorAddErrorPaths:
    """Simulator.add のエラーパス。"""

    def test_add_non_block_raises_type_error(self):
        """Block でないオブジェクトを add すると TypeError。"""
        sim = Simulator()
        with pytest.raises(TypeError, match="Expected Block instance"):
            sim.add(42)  # type: ignore[arg-type]

    def test_add_string_raises_type_error(self):
        """文字列を add すると TypeError。"""
        sim = Simulator()
        with pytest.raises(TypeError, match="Expected Block instance"):
            sim.add("Gain_0")  # type: ignore[arg-type]

    def test_add_none_raises_type_error(self):
        """None を add すると TypeError。"""
        sim = Simulator()
        with pytest.raises(TypeError, match="Expected Block instance"):
            sim.add(None)  # type: ignore[arg-type]


class TestConnectIndexOutOfRange:
    """Simulator.connect の src_idx / dst_idx 範囲外エラー。"""

    def test_dst_idx_out_of_range_raises(self):
        """dst_idx が n_inputs 以上なら IndexError。"""
        sim = Simulator()
        src = sim.add(Constant(value=1.0, id="src"))
        g = sim.add(Gain(k=1.0, id="g"))  # n_inputs = 1
        with pytest.raises(IndexError, match="input index 1 out of range"):
            sim.connect(src, g, dst_idx=1)

    def test_src_idx_out_of_range_raises(self):
        """src_idx が n_outputs 以上なら IndexError。"""
        sim = Simulator()
        src = sim.add(Constant(value=1.0, id="src"))  # n_outputs = 1
        g = sim.add(Gain(k=1.0, id="g"))
        with pytest.raises(IndexError, match="output index 1 out of range"):
            sim.connect(src, g, src_idx=1)

    def test_dst_idx_negative_raises(self):
        """負の dst_idx は IndexError として明示的に拒否される。"""
        sim = Simulator()
        src = sim.add(Constant(value=1.0, id="src"))
        g = sim.add(Gain(k=1.0, id="g"))
        with pytest.raises(IndexError, match="input index -1 out of range"):
            sim.connect(src, g, dst_idx=-1)

    def test_src_idx_negative_raises(self):
        """負の src_idx は IndexError として明示的に拒否される。"""
        sim = Simulator()
        src = sim.add(Constant(value=1.0, id="src"))
        g = sim.add(Gain(k=1.0, id="g"))
        with pytest.raises(IndexError, match="output index -1 out of range"):
            sim.connect(src, g, src_idx=-1)


class TestResolveTypeError:
    """Simulator._resolve に Block でも str でもない型を渡す。"""

    def test_resolve_with_int_raises_type_error(self):
        """_resolve に整数を渡すと TypeError。"""
        sim = Simulator()
        sim.add(Constant(value=1.0, id="src"))
        g = sim.add(Gain(k=1.0, id="g"))
        with pytest.raises(TypeError, match="Expected Block or str"):
            sim.connect(123, g)  # type: ignore[arg-type]

    def test_resolve_with_list_raises_type_error(self):
        """_resolve にリストを渡すと TypeError。"""
        sim = Simulator()
        src = sim.add(Constant(value=1.0, id="src"))
        sim.add(Gain(k=1.0, id="g"))
        with pytest.raises(TypeError, match="Expected Block or str"):
            sim.connect(src, ["g"])  # type: ignore[arg-type]


class TestAlgebraicLoopDetection:
    """代数ループ検出: ValueError から AlgebraicLoopError に昇格した確認。"""

    def test_direct_feedthrough_loop_raises_algebraic_loop_error(self):
        """直達フィードスルーだけのループは AlgebraicLoopError (PyflwError)。"""
        sim = Simulator()
        g1 = sim.add(Gain(k=1.0, id="g1"))
        g2 = sim.add(Gain(k=1.0, id="g2"))
        sim.connect(g1, g2)
        sim.connect(g2, g1)
        with pytest.raises(AlgebraicLoopError, match="Algebraic loop"):
            sim.run()

    def test_algebraic_loop_error_is_pyflw_error(self):
        """AlgebraicLoopError は PyflwError を継承する。"""
        from pyflw.exceptions import PyflwError

        assert issubclass(AlgebraicLoopError, PyflwError)

    def test_algebraic_loop_error_message_contains_block_ids(self):
        """AlgebraicLoopError のメッセージに関与ブロック ID が含まれる。"""
        sim = Simulator()
        g1 = sim.add(Gain(k=1.0, id="loop_a"))
        g2 = sim.add(Gain(k=1.0, id="loop_b"))
        sim.connect(g1, g2)
        sim.connect(g2, g1)
        with pytest.raises(AlgebraicLoopError) as exc_info:
            sim.run()
        msg = str(exc_info.value)
        assert "loop_a" in msg or "loop_b" in msg


class TestRunNStepsLessThanOne:
    """Simulator.run で n_steps < 1 になる場合は SchedulingError。"""

    def test_t_end_smaller_than_dt_base_raises_scheduling_error(self):
        """t_end < dt_base で n_steps=0 → SchedulingError。"""
        sim = Simulator(t_end=0.001, dt=1.0)  # n_steps = round(0.001 / 1.0) = 0
        src = sim.add(Constant(value=1.0, id="src"))
        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(src, scope)
        with pytest.raises(SchedulingError, match="n_steps"):
            sim.run()


class TestConnectUnknownIdRaisesUnknownBlockIdError:
    """connect で未登録 ID を dst に使うと UnknownBlockIdError。"""

    def test_connect_with_unknown_dst_id_raises(self):
        """dst に未登録 ID 文字列を渡すと UnknownBlockIdError。"""
        sim = Simulator()
        sim.add(Constant(value=1.0, id="src"))
        with pytest.raises(UnknownBlockIdError):
            sim.connect("src", "nonexistent_dst")


# ---------------------------------------------------------------------------
# 2. 境界値
# ---------------------------------------------------------------------------


class TestBlockIdBoundaryValues:
    """ID 文字列の境界値テスト。"""

    def test_single_underscore_id_is_valid(self):
        """ID = '_' (アンダースコア 1 文字) は有効な識別子。"""
        g = Gain(id="_")
        assert g.id == "_"

    def test_single_uppercase_letter_id_is_valid(self):
        """ID = 'A' (英大文字 1 文字) は有効。"""
        g = Gain(id="A")
        assert g.id == "A"

    def test_single_lowercase_letter_id_is_valid(self):
        """ID = 'a' (英小文字 1 文字) は有効。"""
        g = Gain(id="a")
        assert g.id == "a"

    def test_id_exactly_64_chars_is_valid(self):
        """64 文字ちょうどは有効 (max_length 境界)。"""
        long_id = "a" * 64
        g = Gain(id=long_id)
        assert g.id == long_id

    def test_id_65_chars_raises(self):
        """65 文字は BlockSpecError。"""
        with pytest.raises(BlockSpecError, match="exceeds max length"):
            Gain(id="a" * 65)

    def test_id_with_digits_after_letter_is_valid(self):
        """英字始まり + 数字は有効。"""
        g = Gain(id="x123")
        assert g.id == "x123"

    def test_id_starting_with_digit_raises(self):
        """数字始まりは BlockSpecError。"""
        with pytest.raises(BlockSpecError):
            Gain(id="1abc")

    def test_id_with_underscore_and_digits_is_valid(self):
        """アンダースコア始まり + 英数字は有効。"""
        g = Gain(id="_v1_2")
        assert g.id == "_v1_2"


class TestUnitDelaySampleTimeBoundaryValues:
    """UnitDelay の sample_time 境界値テスト。"""

    def test_unit_delay_sample_time_zero_treated_as_continuous(self):
        """sample_time=0.0 は連続扱い (ADR-0002 §(1) 表より None と等価)。

        UnitDelay は sample_time>0 を期待するが、Block 基底は 0.0 を
        連続として受け入れる。現実装の挙動をドキュメントする。
        """
        # Block.__init__ は sample_time=0.0 を valid として受け入れる
        b = UnitDelay(sample_time=0.0)
        assert b.sample_time == 0.0

    def test_unit_delay_sample_time_negative_minus_one_is_inherited(self):
        """sample_time=-1.0 は継承マーカーとして有効。"""
        b = UnitDelay(sample_time=-1.0)
        assert b.sample_time == -1.0

    def test_unit_delay_sample_time_minus_two_raises(self):
        """sample_time=-2.0 は BlockSpecError (invalid)。"""
        with pytest.raises(BlockSpecError, match="invalid"):
            UnitDelay(sample_time=-2.0)

    def test_unit_delay_very_small_positive_sample_time(self):
        """極小の正の sample_time は受け入れられる。"""
        b = UnitDelay(sample_time=1e-6)
        assert b.sample_time == pytest.approx(1e-6)

    def test_block_sample_time_non_numeric_raises(self):
        """sample_time が数値型でない場合は BlockSpecError。"""
        with pytest.raises(BlockSpecError, match="must be a number"):
            UnitDelay(sample_time="0.01")  # type: ignore[arg-type]


class TestMinimalSimulationOneStep:
    """t_end = dt_base のミニマルケース (n_steps=1)。"""

    def test_one_step_simulation_runs_without_error(self):
        """t_end == dt の 1 ステップだけのシミュレーションが正常完了する。"""
        dt = 0.01
        sim = Simulator(t_end=dt, dt=dt)
        src = sim.add(Constant(value=5.0, id="src"))
        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(src, scope)
        sim.run()
        # n_steps+1 点 (k=0 と k=1) 記録される
        assert len(scope.times) == 2

    def test_one_step_discrete_simulation_records_correct_values(self):
        """t_end == sample_time の 1 ステップ離散シミュレーション。"""
        dt = 0.01
        sim = Simulator(t_end=dt, dt=dt)
        src = sim.add(Constant(value=7.0, id="src"))
        delay = sim.add(UnitDelay(sample_time=dt, x0=3.0, id="d"))
        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(src, delay)
        sim.connect(delay, scope)
        sim.run()
        values = scope.values[:, 0]
        assert values[0] == pytest.approx(3.0)  # 初期状態


# ---------------------------------------------------------------------------
# 3. マルチレート組み合わせ
# ---------------------------------------------------------------------------


class TestMultiRateThreeRates:
    """3 レート (T=0.01, T=0.02, T=0.05) の混在テスト。"""

    def test_three_rates_step_ratios_are_correct(self):
        """3 つの異なる sample_time で step_ratio が正しく計算される。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        src = sim.add(Constant(value=1.0, id="src"))
        fast = sim.add(UnitDelay(sample_time=0.01, x0=0.0, id="fast"))
        mid = sim.add(UnitDelay(sample_time=0.02, x0=0.0, id="mid"))
        slow = sim.add(UnitDelay(sample_time=0.05, x0=0.0, id="slow"))
        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(src, fast)
        sim.connect(src, mid)
        sim.connect(src, slow)
        sim.connect(fast, scope)
        sim.run()

        assert fast._step_ratio == 1
        assert mid._step_ratio == 2
        assert slow._step_ratio == 5

    def test_three_rates_simulation_completes(self):
        """3 レート混在でシミュレーションが完走する (値の正確性は問わない)。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        src = sim.add(Constant(value=1.0, id="src"))
        fast = sim.add(UnitDelay(sample_time=0.01, x0=0.0, id="fast"))
        mid = sim.add(UnitDelay(sample_time=0.02, x0=0.0, id="mid"))
        slow = sim.add(UnitDelay(sample_time=0.05, x0=0.0, id="slow"))
        scope_f = sim.add(Scope(n_inputs=1, id="sf"))
        scope_m = sim.add(Scope(n_inputs=1, id="sm"))
        scope_s = sim.add(Scope(n_inputs=1, id="ss"))
        sim.connect(src, fast)
        sim.connect(src, mid)
        sim.connect(src, slow)
        sim.connect(fast, scope_f)
        sim.connect(mid, scope_m)
        sim.connect(slow, scope_s)
        sim.run()

        # 全 Scope がデータを記録できている
        assert scope_f.values.shape[0] > 0
        assert scope_m.values.shape[0] > 0
        assert scope_s.values.shape[0] > 0

    def test_three_rate_fast_block_update_count(self):
        """最速ブロックは t_end / sample_time 回だけ update される。

        UnitDelay(T=0.01) は t_end=0.1, dt=0.01 で 10 回 update されるはず。
        初期値 0、入力 1 → 1 ステップ後は 1 になる。
        """
        sim = Simulator(t_end=0.1, dt=0.01)
        src = sim.add(Constant(value=1.0, id="src"))
        fast = sim.add(UnitDelay(sample_time=0.01, x0=0.0, id="fast"))
        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(src, fast)
        sim.connect(fast, scope)
        sim.run()

        values = scope.values[:, 0]
        assert values[0] == pytest.approx(0.0)  # k=0: 初期値
        assert values[1] == pytest.approx(1.0)  # k=1: update 後


class TestContinuousPlusDiscreteInheritedThreeTier:
    """連続 + 離散 + 継承の三段組み。"""

    def test_inherited_block_between_continuous_and_discrete(self):
        """
        Sine(連続) → UnitDelay(T=0.05) → Gain(継承) の三段構成。
        Gain の _resolved_sample_time が UnitDelay の sample_time を継承する。
        """
        sim = Simulator(t_end=0.2, dt=0.01)
        src = sim.add(Sine(amplitude=1.0, frequency=1.0, id="sine"))
        delay = sim.add(UnitDelay(sample_time=0.05, x0=0.0, id="delay"))
        g = sim.add(Gain(k=2.0, id="g"))
        g.sample_time = -1.0  # 継承マーカー
        scope = sim.add(Scope(n_inputs=1, id="scope"))

        sim.connect(src, delay)
        sim.connect(delay, g)
        sim.connect(g, scope)
        sim.run()

        assert g._resolved_sample_time == pytest.approx(0.05)
        assert scope.values.shape[0] > 0


# ---------------------------------------------------------------------------
# 4. 回帰テスト
# ---------------------------------------------------------------------------


class TestBlockDefaultImplementations:
    """Block 基底クラスの default 実装の回帰テスト。"""

    def test_block_output_raises_not_implemented(self):
        """Block.output を override しないと NotImplementedError。"""

        class RawBlock(Block):
            pass

        b = RawBlock()
        with pytest.raises(NotImplementedError, match="output not implemented"):
            b.output(0.0, np.zeros(0), np.zeros(0))

    def test_block_derivative_default_returns_zeros(self):
        """Block.derivative の default 実装は np.zeros(n_states) を返す。"""

        class MinimalBlock(Block):
            def output(self, t, x, u):
                return np.zeros(0)

        b = MinimalBlock(n_states=3)
        result = b.derivative(0.0, np.zeros(3), np.zeros(0))
        np.testing.assert_array_equal(result, np.zeros(3))

    def test_block_update_default_returns_x_unchanged(self):
        """Block.update の default 実装は x をそのまま返す ndarray。"""

        class MinimalBlock(Block):
            def output(self, t, x, u):
                return np.zeros(0)

        b = MinimalBlock(n_states=2)
        x = np.array([1.0, 2.0])
        result = b.update(0.0, x, np.zeros(0))
        np.testing.assert_array_equal(result, x)

    def test_block_update_default_returns_ndarray(self):
        """Block.update の戻り値は ndarray (型確認)。"""

        class MinimalBlock(Block):
            def output(self, t, x, u):
                return np.zeros(0)

        b = MinimalBlock(n_states=1)
        x = np.array([5.0])
        result = b.update(0.0, x, np.zeros(0))
        assert isinstance(result, np.ndarray)

    def test_block_derivative_returns_ndarray(self):
        """Block.derivative の default 戻り値は ndarray。"""

        class MinimalBlock(Block):
            def output(self, t, x, u):
                return np.zeros(0)

        b = MinimalBlock(n_states=2)
        result = b.derivative(0.0, np.zeros(2), np.zeros(0))
        assert isinstance(result, np.ndarray)
        assert result.shape == (2,)


class TestBlockNameReadOnly:
    """Block.name は読み出し専用 alias (書き込み不可)。"""

    def test_name_property_returns_id(self):
        """name プロパティは id と同じ値を返す。"""
        g = Gain(id="motor")
        assert g.name == "motor"
        assert g.name == g.id

    def test_name_property_after_id_setter(self):
        """id を変更すると name も追従する。"""
        g = Gain(id="old")
        g.id = "new_id"
        assert g.name == "new_id"

    def test_name_is_read_only_property(self):
        """name への書き込みは AttributeError を起こす。"""
        g = Gain(id="test_block")
        with pytest.raises(AttributeError):
            g.name = "overwrite"  # type: ignore[misc]


class TestScopeRecordCountInHybridRun:
    """Scope の record が全ステップで呼ばれることを確認する。"""

    def test_scope_record_count_matches_n_steps_plus_one(self):
        """連続モデルで Scope の記録数が n_steps+1 になる。"""
        t_end = 0.05
        dt = 0.01
        sim = Simulator(t_end=t_end, dt=dt)
        src = sim.add(Constant(value=1.0, id="src"))
        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(src, scope)
        sim.run()

        expected_n = int(round(t_end / dt)) + 1  # k=0 ... k=n_steps
        assert len(scope.times) == expected_n

    def test_scope_times_start_at_zero(self):
        """Scope.times の最初の時刻は 0.0。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        src = sim.add(Constant(value=1.0, id="src"))
        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(src, scope)
        sim.run()
        assert scope.times[0] == pytest.approx(0.0)

    def test_scope_times_end_at_t_end(self):
        """Scope.times の最後の時刻は t_end。"""
        t_end = 0.05
        dt = 0.01
        sim = Simulator(t_end=t_end, dt=dt)
        src = sim.add(Constant(value=1.0, id="src"))
        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(src, scope)
        sim.run()
        assert scope.times[-1] == pytest.approx(t_end)

    def test_scope_record_count_with_discrete_block(self):
        """離散ブロック混在でも Scope の記録数は全 dt_base ステップ数+1。"""
        t_end = 0.05
        dt = 0.01
        sim = Simulator(t_end=t_end, dt=dt)
        src = sim.add(Constant(value=1.0, id="src"))
        delay = sim.add(UnitDelay(sample_time=0.01, x0=0.0, id="d"))
        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(src, delay)
        sim.connect(delay, scope)
        sim.run()

        expected_n = int(round(t_end / dt)) + 1
        assert len(scope.times) == expected_n

    def test_scope_reset_clears_records(self):
        """Scope.reset() が times と values を空にする。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        src = sim.add(Constant(value=1.0, id="src"))
        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(src, scope)
        sim.run()

        assert len(scope.times) > 0
        scope.reset()
        assert len(scope.times) == 0
        assert scope.values.shape == (0, 1)


# ---------------------------------------------------------------------------
# 5. 継承 sample_time の警告ケース
# ---------------------------------------------------------------------------


class TestInheritedSampleTimeWarnings:
    """継承サンプル時間が warning を出すケース。"""

    def test_inherit_from_mix_of_continuous_and_discrete_warns(self, caplog):
        """連続 + 離散混在の上流から継承すると warning。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        continuous_src = sim.add(Sine(amplitude=1.0, frequency=1.0, id="sine"))
        discrete_src = sim.add(UnitDelay(sample_time=0.05, x0=0.0, id="delay"))

        # Gain を 2 入力に改造して両方から入力を受ける
        # Sum で 2 入力を受けて継承
        from pyflw.blocks.mathops import Sum

        summer = sim.add(Sum(signs="++", id="summer"))
        summer.sample_time = -1.0

        # Constant を delay の入力として接続
        c = sim.add(Constant(value=1.0, id="c"))
        sim.connect(c, discrete_src)

        # summer の 2 入力: continuous_src と discrete_src
        sim.connect(continuous_src, summer, dst_idx=0)
        sim.connect(discrete_src, summer, dst_idx=1)

        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(summer, scope)

        with caplog.at_level(logging.WARNING, logger="pyflw.scheduler"):
            sim.run()

        # 連続 + 離散の混在 warning が出ていること
        assert any(
            "continuous" in r.message.lower() or "mix" in r.message.lower() for r in caplog.records
        )

    def test_inherit_from_different_discrete_periods_warns_and_takes_min(self, caplog):
        """異なる離散値の上流から継承すると warning + min を採用。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        slow = sim.add(UnitDelay(sample_time=0.05, x0=0.0, id="slow"))
        fast = sim.add(UnitDelay(sample_time=0.02, x0=0.0, id="fast"))

        from pyflw.blocks.mathops import Sum

        summer = sim.add(Sum(signs="++", id="summer"))
        summer.sample_time = -1.0

        c1 = sim.add(Constant(value=1.0, id="c1"))
        c2 = sim.add(Constant(value=1.0, id="c2"))
        sim.connect(c1, slow)
        sim.connect(c2, fast)
        sim.connect(slow, summer, dst_idx=0)
        sim.connect(fast, summer, dst_idx=1)

        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(summer, scope)

        with caplog.at_level(logging.WARNING, logger="pyflw.scheduler"):
            sim.run()

        # min を採用 (0.02)
        assert summer._resolved_sample_time == pytest.approx(0.02)
        # 複数 sample_time についての warning
        assert any(r.message for r in caplog.records)

    def test_inherit_from_single_discrete_upstream_no_warning(self, caplog):
        """単一の離散上流から継承する場合、warning は出ない。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        src = sim.add(Constant(value=1.0, id="src"))
        delay = sim.add(UnitDelay(sample_time=0.05, x0=0.0, id="delay"))
        g = sim.add(Gain(k=2.0, id="g"))
        g.sample_time = -1.0

        sim.connect(src, delay)
        sim.connect(delay, g)

        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(g, scope)

        with caplog.at_level(logging.WARNING, logger="pyflw.scheduler"):
            sim.run()

        # 単一離散上流の場合は warning なし
        scheduler_warns = [
            r
            for r in caplog.records
            if r.name == "pyflw.scheduler" and "multiple" in r.message.lower()
        ]
        assert len(scheduler_warns) == 0
        assert g._resolved_sample_time == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# 6. 追加の同値分割 / ID 検証の組み合わせ
# ---------------------------------------------------------------------------


class TestBlockIdEdgeCases:
    """ID の細かい同値分割テスト。"""

    @pytest.mark.parametrize(
        "valid_id",
        [
            "_",
            "A",
            "z",
            "a1",
            "_1",
            "__",
            "CamelCase",
            "snake_case_123",
            "a" * 64,
        ],
    )
    def test_valid_ids_are_accepted(self, valid_id):
        """有効な ID は BlockSpecError を起こさない。"""
        g = Gain(id=valid_id)
        assert g.id == valid_id

    @pytest.mark.parametrize(
        "invalid_id",
        [
            "",
            "1start",
            "has space",
            "has-hyphen",
            "has.dot",
            "has/slash",
            "日本語",
            "a" * 65,
        ],
    )
    def test_invalid_ids_are_rejected(self, invalid_id):
        """無効な ID は BlockSpecError。"""
        with pytest.raises(BlockSpecError):
            Gain(id=invalid_id)

    @pytest.mark.parametrize("keyword_id", ["for", "if", "class", "return", "while"])
    def test_python_keyword_ids_warn(self, keyword_id, caplog):
        """Python キーワードと一致する ID は warning が出るが受け入れられる。"""
        with caplog.at_level(logging.WARNING, logger="pyflw.identifiers"):
            g = Gain(id=keyword_id)
        assert g.id == keyword_id
        assert any("Python keyword" in r.message for r in caplog.records)


class TestSimulatorStateManagement:
    """Simulator の内部状態管理テスト。"""

    def test_blocks_by_id_updated_after_add(self):
        """add 後に _blocks_by_id に登録されている。"""
        sim = Simulator()
        g = sim.add(Gain(id="myblock"))
        assert "myblock" in sim._blocks_by_id
        assert sim._blocks_by_id["myblock"] is g

    def test_blocks_list_order_matches_add_order(self):
        """blocks リストは add 順を保持する。"""
        sim = Simulator()
        a = sim.add(Constant(value=1.0, id="a"))
        b = sim.add(Gain(k=2.0, id="b"))
        c = sim.add(Gain(k=3.0, id="c"))
        assert sim.blocks[0] is a
        assert sim.blocks[1] is b
        assert sim.blocks[2] is c

    def test_get_block_returns_same_object_as_add(self):
        """get_block は add で返したのと同じオブジェクトを返す。"""
        sim = Simulator()
        g = sim.add(Gain(id="g"))
        assert sim.get_block("g") is g

    def test_rename_updates_both_dict_and_block_id(self):
        """rename 後は _blocks_by_id のキーと block.id が両方更新される。"""
        sim = Simulator()
        sim.add(Gain(id="old"))
        sim.rename("old", "new_name")
        assert "old" not in sim._blocks_by_id
        assert "new_name" in sim._blocks_by_id
        assert sim._blocks_by_id["new_name"].id == "new_name"


class TestUnitDelayInitialConditions:
    """UnitDelay の初期条件テスト。"""

    def test_unit_delay_nonzero_x0_appears_at_first_output(self):
        """x0 != 0 の UnitDelay の t=0 での出力は x0 に等しい。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        src = sim.add(Constant(value=0.0, id="src"))
        delay = sim.add(UnitDelay(sample_time=0.01, x0=42.0, id="d"))
        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(src, delay)
        sim.connect(delay, scope)
        sim.run()

        assert scope.values[0, 0] == pytest.approx(42.0)

    def test_unit_delay_x0_stored_in_x0_array(self):
        """x0 は ndarray として保持される。"""
        b = UnitDelay(sample_time=0.01, x0=7.5)
        assert isinstance(b.x0, np.ndarray)
        assert b.x0[0] == pytest.approx(7.5)


class TestExceptionHierarchy:
    """例外クラスの継承関係テスト。"""

    def test_block_spec_error_is_pyflw_error(self):
        from pyflw.exceptions import PyflwError

        assert issubclass(BlockSpecError, PyflwError)

    def test_unknown_block_id_error_is_pyflw_error(self):
        from pyflw.exceptions import PyflwError

        assert issubclass(UnknownBlockIdError, PyflwError)

    def test_unknown_block_id_error_is_key_error(self):
        """UnknownBlockIdError は KeyError を継承する (dict 互換)。"""
        assert issubclass(UnknownBlockIdError, KeyError)

    def test_scheduling_error_is_pyflw_error(self):
        from pyflw.exceptions import PyflwError

        assert issubclass(SchedulingError, PyflwError)

    def test_algebraic_loop_error_is_pyflw_error(self):
        from pyflw.exceptions import PyflwError

        assert issubclass(AlgebraicLoopError, PyflwError)
