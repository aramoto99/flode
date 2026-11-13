"""``@block`` の出力 0 本 (sink) と source のテスト (ADR-0081 §論点 5 / SPEC-0033 機能要件 3)。

* 書き方: ``outputs=0`` と戻り値注釈 ``-> None`` の両方 (関数形・class 形)
* 拒否: 注釈との矛盾 / ``states>0`` (R-3) / ``direct_feedthrough=False``
* 呼び出し時刻: 記録経路で基準グリッド 1 ステップに最大 1 回、離散なら自分の周期
  (ソルバの中間段では呼ばれない)
* 戻り値は捨てて、ブロックごとに 1 回だけ警告
* 信号面 (shape 宣言の有無) と実行順は既存の sink と同じ扱い
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pytest

from flode import Inport, Outport, Simulator, Subsystem, block
from flode.blocks import Constant, Gain, Integrator, Ramp, Scope, Sine, UnitDelay
from flode.exceptions import BlockSpecError, SignalShapeError

_T_END = 0.05
_DT = 0.01
_GRID = [0.0, 0.01, 0.02, 0.03, 0.04, 0.05]


def _make_logger_sink(calls: list[tuple[float, Any]], **deco: Any) -> type:
    """``calls`` に ``(t, u)`` を積む関数形の sink を作る。"""

    @block(outputs=0, **deco)
    def logger_sink(t: float, u: float):  # noqa: ANN202 - outputs=0 で宣言する形を確かめる
        calls.append((t, u))

    return logger_sink


def _run_ramp_into(sink_obj: Any, *, t_end: float = _T_END, dt: float = _DT, **sim_kw: Any) -> None:
    sim = Simulator(t_end=t_end, dt=dt, **sim_kw)
    sim.add(Ramp(slope=1.0, id="src"))
    sim.add(sink_obj)
    sim.connect("src", sink_obj.id)
    sim.run()


# ---------------------------------------------------------------------------
# 宣言
# ---------------------------------------------------------------------------


class TestSinkDeclaration:
    def test_outputs_zero_function_form(self) -> None:
        cls = _make_logger_sink([])
        assert cls._flode_structure.n_outputs == 0
        assert cls._flode_structure.n_inputs == 1
        assert cls._flode_structure.direct_feedthrough is True
        assert cls.record_on_sample_hits is True
        assert cls(id="s").n_outputs == 0

    def test_none_return_annotation_function_form(self) -> None:
        @block
        def log(t: float, u: float) -> None:
            return None

        assert log._flode_structure.n_outputs == 0
        assert log.record_on_sample_hits is True

    def test_outputs_zero_class_form(self) -> None:
        @block(outputs=0)
        class Writer:
            def output(self, t: float, u: float):  # noqa: ANN202
                pass

        assert Writer._flode_structure.n_outputs == 0
        assert Writer.record_on_sample_hits is True

    def test_none_return_annotation_class_form(self) -> None:
        @block
        class Writer:
            def output(self, t: float, u: float) -> None:
                pass

        assert Writer._flode_structure.n_outputs == 0

    def test_ordinary_blocks_do_not_record_on_sample_hits(self) -> None:
        @block
        def gain(t: float, u: float) -> float:
            return u

        assert gain.record_on_sample_hits is False
        assert Scope.record_on_sample_hits is False

    def test_outputs_zero_with_value_annotation_is_contradiction(self) -> None:
        with pytest.raises(BlockSpecError, match="contradict"):

            @block(outputs=0)
            def bad(t: float, u: float) -> float:
                return u

    def test_none_annotation_with_positive_outputs_is_contradiction(self) -> None:
        with pytest.raises(BlockSpecError, match="contradict"):

            @block(outputs=1)
            def bad(t: float, u: float) -> None:
                return None

    def test_class_form_contradiction(self) -> None:
        with pytest.raises(BlockSpecError, match="contradict"):

            @block(outputs=0)
            class Bad:
                def output(self, t: float, u: float) -> float:
                    return u

    @pytest.mark.parametrize("bad", [-1, True, 1.0])
    def test_outputs_must_be_non_negative_int(self, bad) -> None:
        with pytest.raises(BlockSpecError, match="non-negative int"):

            @block(outputs=bad)
            def f(t: float, u: float) -> None:
                return None

    def test_contradiction_is_reported_before_the_state_rule(self) -> None:
        """注釈と ``outputs`` の矛盾は、状態つき sink の規則より先に報告する。"""
        with pytest.raises(BlockSpecError, match="contradict"):

            @block(states=1, outputs=1)
            def bad(t: float, x: np.ndarray, u: float) -> None:
                return None

    def test_stateful_sink_function_form_is_rejected(self) -> None:
        with pytest.raises(BlockSpecError, match="Block subclass"):

            @block(states=1, outputs=0)
            def bad(t: float, x: np.ndarray, u: float):  # noqa: ANN202
                return None, x

    def test_stateful_sink_none_annotation_is_rejected(self) -> None:
        with pytest.raises(BlockSpecError, match="Block subclass"):

            @block(states=1)
            def bad(t: float, x: np.ndarray, u: float) -> None:
                return None

    def test_stateful_sink_class_form_is_rejected(self) -> None:
        with pytest.raises(BlockSpecError, match="Block subclass"):

            @block(states=1)
            class Bad:
                def output(self, t: float, x: np.ndarray, u: float) -> None:
                    pass

                def derivative(self, t: float, x: np.ndarray, u: float) -> np.ndarray:
                    return x

    def test_sink_with_direct_feedthrough_false_is_rejected(self) -> None:
        with pytest.raises(BlockSpecError, match="direct_feedthrough"):

            @block(outputs=0, direct_feedthrough=False)
            def bad(t: float, u: float):  # noqa: ANN202
                pass

    def test_sink_output_names_must_be_empty(self) -> None:
        with pytest.raises(BlockSpecError, match="output_names"):

            @block(output_names=("y",))
            def bad(t: float, u: float) -> None:
                pass

    def test_class_form_sink_cannot_define_record(self) -> None:
        with pytest.raises(BlockSpecError, match="record"):

            @block
            class Bad:
                def output(self, t: float, u: float) -> None:
                    pass

                def record(self, t: float, u: Any) -> None:
                    pass

    def test_output_does_not_call_the_function(self) -> None:
        calls: list[tuple[float, Any]] = []
        b = _make_logger_sink(calls)(id="s")
        y = b.output(0.0, np.zeros(0), np.array([1.0]))
        y_v = b.output_v(0.0, np.zeros(0), (np.asarray(1.0),))
        assert y.shape == (0,)
        assert y_v == ()
        assert calls == []


# ---------------------------------------------------------------------------
# 呼び出し時刻と入力値
# ---------------------------------------------------------------------------


class TestSinkCallTiming:
    def test_continuous_sink_is_called_once_per_grid_step(self) -> None:
        calls: list[tuple[float, Any]] = []
        _run_ramp_into(_make_logger_sink(calls)(id="s"))
        assert [t for t, _ in calls] == pytest.approx(_GRID)
        assert [u for _, u in calls] == pytest.approx(_GRID)
        assert all(isinstance(u, float) for _, u in calls)

    @pytest.mark.parametrize("solver", ["RK45", "RK23", "DOP853", "Radau"])
    def test_not_called_at_solver_stages(self, solver: str) -> None:
        """連続状態のあるモデル (ソルバが 1 ステップに何度も output を評価する) でも
        sink の関数は基準グリッドの時刻にだけ、1 回ずつ呼ばれる。"""
        calls: list[tuple[float, Any]] = []
        sim = Simulator(t_end=_T_END, dt=_DT, solver=solver)
        sim.add(Sine(frequency=3.0, id="sine"))
        sim.add(Integrator(id="int"))
        sim.add(_make_logger_sink(calls)(id="s"))
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("sine", "int")
        sim.connect("int", "s")
        sim.connect("int", "sc")
        sim.run()
        assert [t for t, _ in calls] == pytest.approx(_GRID)
        scope = sim.get_block("sc")
        np.testing.assert_allclose([u for _, u in calls], scope.values[:, 0])

    def test_discrete_sink_is_called_on_its_own_period(self) -> None:
        calls: list[tuple[float, Any]] = []
        _run_ramp_into(_make_logger_sink(calls, sample_time=0.02)(id="s"))
        assert [t for t, _ in calls] == pytest.approx([0.0, 0.02, 0.04])
        assert [u for _, u in calls] == pytest.approx([0.0, 0.02, 0.04])

    def test_base_clock_sink_is_called_every_base_step(self) -> None:
        calls: list[tuple[float, Any]] = []
        _run_ramp_into(_make_logger_sink(calls, sample_time="dt")(id="s"))
        assert [t for t, _ in calls] == pytest.approx(_GRID)

    def test_inherited_sink_follows_discrete_upstream(self) -> None:
        calls: list[tuple[float, Any]] = []
        sim = Simulator(t_end=0.06, dt=_DT)
        sim.add(Ramp(slope=1.0, id="src"))
        sim.add(UnitDelay(sample_time=0.03, id="ud"))
        sim.add(_make_logger_sink(calls, sample_time=-1.0)(id="s"))
        sim.connect("src", "ud")
        sim.connect("ud", "s")
        sim.run()
        assert [t for t, _ in calls] == pytest.approx([0.0, 0.03, 0.06])
        assert [u for _, u in calls] == pytest.approx([0.0, 0.0, 0.03])

    def test_non_integer_period_is_rounded_to_base_steps(self, caplog) -> None:
        """周期が基準刻みの整数倍でない sink は、Simulator の既存規則 (比を丸めて警告)
        どおりの刻みで呼ばれる (0.015 / 0.01 = 1.5 → 2 基準ステップごと)。"""
        calls: list[tuple[float, Any]] = []
        sim = Simulator(t_end=_T_END, dt=_DT)
        sim.add(Ramp(slope=1.0, id="src"))
        sim.add(UnitDelay(sample_time=0.01, id="ud"))
        sim.add(_make_logger_sink(calls, sample_time=0.015)(id="s"))
        sim.connect("src", "ud")
        sim.connect("src", "s")
        with caplog.at_level(logging.WARNING, logger="flode.scheduler"):
            sim.run()
        assert sim.get_block("s")._step_ratio == 2
        assert [t for t, _ in calls] == pytest.approx([0.0, 0.02, 0.04])
        assert any("not integer multiples" in r.getMessage() for r in caplog.records)

    def test_explicit_base_step_sets_the_ratio(self) -> None:
        """``dt_base`` を明示すると、離散 sink はその刻みに対する自分の周期で呼ばれ、
        連続の sink は細かい刻みの毎ステップで呼ばれる。"""
        disc: list[tuple[float, Any]] = []
        cont: list[tuple[float, Any]] = []
        sim = Simulator(t_end=0.02, dt=_DT, dt_base=0.005)
        sim.add(Ramp(slope=1.0, id="src"))
        sim.add(_make_logger_sink(disc, sample_time=0.01)(id="d"))
        sim.add(_make_logger_sink(cont)(id="c"))
        sim.connect("src", "d")
        sim.connect("src", "c")
        sim.run()
        assert [t for t, _ in disc] == pytest.approx([0.0, 0.01, 0.02])
        assert [t for t, _ in cont] == pytest.approx([0.0, 0.005, 0.01, 0.015, 0.02])

    def test_inherited_sink_with_continuous_upstream_is_called_every_step(self) -> None:
        calls: list[tuple[float, Any]] = []
        _run_ramp_into(_make_logger_sink(calls, sample_time=-1.0)(id="s"))
        assert [t for t, _ in calls] == pytest.approx(_GRID)

    def test_multi_input_sink_receives_each_port(self) -> None:
        calls: list[tuple[float, Any]] = []

        @block
        def pair(t: float, u: tuple[float, float]) -> None:
            calls.append((t, u))

        sim = Simulator(t_end=0.02, dt=_DT)
        sim.add(Ramp(slope=1.0, id="r"))
        sim.add(Constant(value=5.0, id="c"))
        sim.add(pair(id="s"))
        sim.connect("r", "s", dst_idx=0)
        sim.connect("c", "s", dst_idx=1)
        sim.run()
        assert [u for _, u in calls] == [(0.0, 5.0), pytest.approx((0.01, 5.0)), (0.02, 5.0)]

    def test_vector_sink_receives_declared_shape(self) -> None:
        """``port_shapes_in`` を宣言した sink はベクトルの値を宣言 shape のまま受け取る
        (信号面 plan がある実行経路)。"""
        calls: list[tuple[float, Any]] = []

        @block(port_shapes_in=((3,),))
        def vec_log(t: float, u: float) -> None:
            calls.append((t, np.array(u, copy=True)))

        sim = Simulator(t_end=0.02, dt=_DT)
        sim.add(Constant(value=[1.0, 2.0, 3.0], id="c"))
        sim.add(vec_log(id="s"))
        sim.connect("c", "s")
        sim.run()
        assert len(calls) == 3
        for _, u in calls:
            assert u.shape == (3,)
            np.testing.assert_allclose(u, [1.0, 2.0, 3.0])

    def test_vector_discrete_sink_is_called_on_its_own_period(self) -> None:
        calls: list[float] = []

        @block(port_shapes_in=((2,),), sample_time=0.02)
        def vec_log(t: float, u: float) -> None:
            calls.append(t)

        sim = Simulator(t_end=_T_END, dt=_DT)
        sim.add(Constant(value=[1.0, 2.0], id="c"))
        sim.add(vec_log(id="s"))
        sim.connect("c", "s")
        sim.run()
        assert calls == pytest.approx([0.0, 0.02, 0.04])

    def test_sink_without_inputs_is_called_every_step(self) -> None:
        calls: list[float] = []

        @block
        def tick(t: float) -> None:
            calls.append(t)

        sim = Simulator(t_end=_T_END, dt=_DT)
        sim.add(tick(id="s"))
        sim.run()
        assert calls == pytest.approx(_GRID)

    def test_class_form_sink_reads_its_fields(self) -> None:
        calls: list[float] = []

        @block
        class Scaled:
            k: float = 2.0

            def output(self, t: float, u: float) -> None:
                calls.append(self.k * u)

        _run_ramp_into(Scaled(id="s", k=10.0))
        assert calls == pytest.approx([10.0 * t for t in _GRID])

    def test_sink_parameters_are_passed(self) -> None:
        calls: list[str] = []

        @block
        def tagged(t: float, u: float, *, tag: str = "a") -> None:
            calls.append(tag)

        _run_ramp_into(tagged(id="s", tag="z"))
        assert set(calls) == {"z"}

    def test_sink_is_called_after_its_source_regardless_of_add_order(self) -> None:
        """出力が無いので依存元を持たず、追加順に関係なく同時刻の上流の値を受け取る。"""
        calls: list[tuple[float, Any]] = []
        sim = Simulator(t_end=_T_END, dt=_DT)
        sim.add(_make_logger_sink(calls)(id="s"))
        sim.add(Gain(k=3.0, id="g"))
        sim.add(Ramp(slope=1.0, id="src"))
        sim.connect("src", "g")
        sim.connect("g", "s")
        sim.run()
        assert [u for _, u in calls] == pytest.approx([3.0 * t for t in _GRID])

    @pytest.mark.parametrize("vector", [False, True], ids=["scalar-path", "plan-path"])
    def test_exception_in_sink_identifies_the_block(self, vector: bool) -> None:
        """sink の関数の例外は、失敗ブロックとして sink を指したまま伝わる (ADR-0056 §C-3)。
        スカラ経路 (``_record``) と信号面 plan のある経路 (``_record_v``) の両方。"""
        deco = {"port_shapes_in": ((2,),)} if vector else {}

        @block(**deco)
        def broken(t: float, u: float) -> None:
            raise ValueError("disk full")

        sim = Simulator(t_end=0.02, dt=_DT)
        sim.add(Constant(value=[1.0, 2.0] if vector else 1.0, id="src"))
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.add(broken(id="s"))
        sim.connect("src", "s")
        sim.connect("src", "sc")
        assert sim._is_sm_a_mode() is not vector
        with pytest.raises(ValueError, match="disk full"):
            sim.run()
        assert sim._current_block is sim.get_block("s")

    def test_rerun_calls_again(self) -> None:
        calls: list[tuple[float, Any]] = []
        sim = Simulator(t_end=0.02, dt=_DT)
        sim.add(Ramp(slope=1.0, id="src"))
        sim.add(_make_logger_sink(calls)(id="s"))
        sim.connect("src", "s")
        sim.run()
        sim.run()
        assert len(calls) == 6


# ---------------------------------------------------------------------------
# 戻り値の警告
# ---------------------------------------------------------------------------


class TestSinkReturnValue:
    def test_returned_value_is_discarded_with_one_warning(self, caplog) -> None:
        calls: list[float] = []

        @block(outputs=0)
        def writes(t: float, u: float):  # noqa: ANN202
            calls.append(t)
            return 42  # 例: f.write() の戻り値をうっかり返す

        with caplog.at_level(logging.WARNING, logger="flode.decorator"):
            _run_ramp_into(writes(id="s"))
        assert len(calls) == len(_GRID)
        warnings = [r for r in caplog.records if "returned" in r.getMessage()]
        assert len(warnings) == 1
        assert "'s'" in warnings[0].getMessage()

    def test_warning_is_per_block(self, caplog) -> None:
        @block(outputs=0)
        def writes(t: float, u: float):  # noqa: ANN202
            return 1

        sim = Simulator(t_end=_T_END, dt=_DT)
        sim.add(Ramp(slope=1.0, id="src"))
        sim.add(writes(id="a"))
        sim.add(writes(id="b"))
        sim.connect("src", "a")
        sim.connect("src", "b")
        with caplog.at_level(logging.WARNING, logger="flode.decorator"):
            sim.run()
        warnings = [r for r in caplog.records if "returned" in r.getMessage()]
        assert len(warnings) == 2

    def test_warning_is_once_per_instance_across_runs(self, caplog) -> None:
        """警告はブロックのインスタンスごとに 1 回 (同じインスタンスで再実行しても再警告
        しない)。新しいインスタンスは改めて 1 回警告する。"""

        @block(outputs=0)
        def writes(t: float, u: float):  # noqa: ANN202
            return 1

        sim = Simulator(t_end=_T_END, dt=_DT)
        sim.add(Ramp(slope=1.0, id="src"))
        sim.add(writes(id="s"))
        sim.connect("src", "s")
        with caplog.at_level(logging.WARNING, logger="flode.decorator"):
            sim.run()
            sim.run()
        assert len([r for r in caplog.records if "returned" in r.getMessage()]) == 1
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="flode.decorator"):
            _run_ramp_into(writes(id="s"))
        assert len([r for r in caplog.records if "returned" in r.getMessage()]) == 1

    def test_none_return_does_not_warn(self, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="flode.decorator"):
            _run_ramp_into(_make_logger_sink([])(id="s"))
        assert not [r for r in caplog.records if "returned" in r.getMessage()]


# ---------------------------------------------------------------------------
# 信号面・Subsystem
# ---------------------------------------------------------------------------


class TestSinkSignalPlane:
    def test_undeclared_sink_rejects_vector_with_port_shapes_hint(self) -> None:
        sim = Simulator(t_end=0.02, dt=_DT)
        sim.add(Constant(value=[1.0, 2.0], id="c"))
        sim.add(_make_logger_sink([])(id="s"))
        sim.connect("c", "s")
        with pytest.raises(SignalShapeError, match="port_shapes_in"):
            sim.run()

    def test_sink_is_not_collected_as_scope_result(self) -> None:
        """生成 sink は ``times`` / ``values`` を持たない (Scope の結果収集に乗らない)。"""
        b = _make_logger_sink([])(id="s")
        assert not hasattr(b, "times")
        assert not hasattr(b, "values")

    def test_sink_inside_subsystem_is_not_called_and_warns(self, caplog) -> None:
        """Subsystem 内部の sink は (Scope と同じく) 記録経路に乗らない。黙って
        呼ばれないままにせず、実行開始時に WARNING を残す。"""
        calls: list[tuple[float, Any]] = []
        sub = Subsystem(id="sub")
        sub.add(Inport(port_idx=0, id="i"))
        sub.add(Outport(port_idx=0, id="o"))
        sub.add(_make_logger_sink(calls)(id="inner_sink"))
        sub.connect("i", "o")
        sub.connect("i", "inner_sink")
        sim = Simulator(t_end=0.02, dt=_DT)
        sim.add(Ramp(slope=1.0, id="src"))
        sim.add(sub)
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("src", "sub")
        sim.connect("sub", "sc")
        with caplog.at_level(logging.WARNING, logger="flode.scheduler"):
            sim.run()
        assert calls == []
        messages = [r.getMessage() for r in caplog.records]
        assert any("inner_sink" in m and "Subsystem" in m for m in messages)


# ---------------------------------------------------------------------------
# source (入力 0 本) は従来どおり
# ---------------------------------------------------------------------------


class TestSourceRegression:
    def test_function_source_runs(self) -> None:
        @block
        def ramp2(t: float, *, slope: float = 2.0) -> float:
            return slope * t

        assert ramp2._flode_structure.n_inputs == 0
        sim = Simulator(t_end=_T_END, dt=_DT)
        sim.add(ramp2(id="r"))
        sim.add(Scope(n_inputs=1, id="sc"))
        sim.connect("r", "sc")
        sim.run()
        np.testing.assert_allclose(sim.get_block("sc").values[:, 0], [2.0 * t for t in _GRID])

    def test_class_source_into_user_sink(self) -> None:
        calls: list[float] = []

        @block
        class Level:
            value: float = 4.0

            def output(self, t: float) -> float:
                return self.value

        @block
        def collect(t: float, u: float) -> None:
            calls.append(u)

        assert Level._flode_structure.n_inputs == 0
        sim = Simulator(t_end=0.02, dt=_DT)
        sim.add(Level(id="lv"))
        sim.add(collect(id="s"))
        sim.connect("lv", "s")
        sim.run()
        assert calls == [4.0, 4.0, 4.0]
