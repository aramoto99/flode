"""ADR-0003 ``@block`` デコレータ DSL のテスト。

関数版 (Option A) と class 版 (Option C) の両方を網羅する。両形式は
``isinstance(target, type)`` で内部分岐し、生成される ``Block`` サブクラスの
振る舞いは Simulator から見て同等であることを検証する。
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from flode import BlockSpecError, Simulator, block
from flode.blocks import Scope

# ---------------------------------------------------------------
# 状態なし combinational
# ---------------------------------------------------------------


def test_combinational_scalar_in_scalar_out():
    @block
    def gain(t: float, u: float, *, k: float = 1.0) -> float:
        return k * u

    assert gain.__name__ == "Gain"
    instance = gain(k=2.0)
    assert instance.n_inputs == 1
    assert instance.n_outputs == 1
    assert instance.n_states == 0
    assert instance.direct_feedthrough is True
    assert instance.sample_time is None

    y = instance.output(0.0, np.zeros(0), np.array([3.0]))
    np.testing.assert_allclose(y, [6.0])


def test_combinational_no_args_decorator_form():
    """``@block()`` (引数あり形式の空呼び出し) も ``@block`` と同じ動作。"""

    @block()
    def double(t: float, u: float) -> float:
        return 2.0 * u

    instance = double()
    np.testing.assert_allclose(instance.output(0.0, np.zeros(0), np.array([5.0])), [10.0])


def test_combinational_default_param_value():
    @block
    def gain(t: float, u: float, *, k: float = 4.0) -> float:
        return k * u

    instance = gain()
    np.testing.assert_allclose(instance.output(0.0, np.zeros(0), np.array([1.0])), [4.0])


# ---------------------------------------------------------------
# MIMO (固定長 tuple 注釈)
# ---------------------------------------------------------------


def test_mimo_tuple_annotation_2_in_2_out():
    @block
    def splitter(t: float, u: tuple[float, float]) -> tuple[float, float]:
        a, b = u
        return a + b, a - b

    instance = splitter()
    assert instance.n_inputs == 2
    assert instance.n_outputs == 2
    y = instance.output(0.0, np.zeros(0), np.array([3.0, 1.0]))
    np.testing.assert_allclose(y, [4.0, 2.0])


def test_mimo_tuple_3_inputs():
    @block
    def sum3(t: float, u: tuple[float, float, float]) -> float:
        a, b, c = u
        return a + b + c

    instance = sum3()
    assert instance.n_inputs == 3
    assert instance.n_outputs == 1
    np.testing.assert_allclose(instance.output(0.0, np.zeros(0), np.array([1.0, 2.0, 3.0])), [6.0])


# ---------------------------------------------------------------
# Source (u 引数なし)
# ---------------------------------------------------------------


def test_source_no_u_argument():
    @block
    def constant(t: float, *, value: float = 0.0) -> float:
        return value

    instance = constant(value=2.5)
    assert instance.n_inputs == 0
    assert instance.n_outputs == 1
    np.testing.assert_allclose(instance.output(0.0, np.zeros(0), np.zeros(0)), [2.5])


def test_source_uses_t():
    @block
    def ramp(t: float, *, slope: float = 1.0) -> float:
        return slope * t

    instance = ramp(slope=2.0)
    np.testing.assert_allclose(instance.output(3.0, np.zeros(0), np.zeros(0)), [6.0])


# ---------------------------------------------------------------
# 連続状態
# ---------------------------------------------------------------


def test_continuous_state_integrator_like():
    @block(states=1)
    def integrator(
        t: float, x: np.ndarray, u: float, *, x0: float = 0.0
    ) -> tuple[float, np.ndarray]:
        return x[0], np.array([u])

    instance = integrator(x0=1.5)
    assert instance.n_states == 1
    assert instance.direct_feedthrough is False  # states>0 のデフォルト推論
    assert instance.sample_time is None
    np.testing.assert_allclose(instance.x0, [1.5])

    y = instance.output(0.0, np.array([2.0]), np.array([3.0]))
    np.testing.assert_allclose(y, [2.0])
    xd = instance.derivative(0.0, np.array([2.0]), np.array([3.0]))
    np.testing.assert_allclose(xd, [3.0])
    # 連続なので update は no-op (x をそのまま返す)
    np.testing.assert_allclose(instance.update(0.0, np.array([2.0]), np.array([3.0])), [2.0])


def test_continuous_state_explicit_direct_feedthrough_true():
    """states>0 でも ``direct_feedthrough=True`` を明示できる。"""

    @block(states=1, direct_feedthrough=True)
    def stateful_passthrough(
        t: float, x: np.ndarray, u: float, *, x0: float = 0.0
    ) -> tuple[float, np.ndarray]:
        return x[0] + u, np.array([0.0])

    instance = stateful_passthrough()
    assert instance.direct_feedthrough is True


# ---------------------------------------------------------------
# 離散状態
# ---------------------------------------------------------------


def test_discrete_state_unit_delay_like():
    @block(states=1, sample_time=0.01)
    def my_delay(t: float, x: np.ndarray, u: float, *, x0: float = 0.0) -> tuple[float, np.ndarray]:
        return x[0], np.array([u])

    instance = my_delay(x0=1.0)
    assert instance.sample_time == 0.01
    assert instance.direct_feedthrough is False

    # 離散ブロックは update が動作、derivative は no-op
    xn = instance.update(0.0, np.array([5.0]), np.array([7.0]))
    np.testing.assert_allclose(xn, [7.0])
    xd = instance.derivative(0.0, np.array([5.0]), np.array([7.0]))
    np.testing.assert_allclose(xd, np.zeros(1))


# ---------------------------------------------------------------
# パラメータ束縛・複数インスタンス独立性 (ADR-0003 §(5))
# ---------------------------------------------------------------


def test_multiple_instances_have_independent_params():
    @block
    def gain(t: float, u: float, *, k: float = 1.0) -> float:
        return k * u

    g1 = gain(k=2.0)
    g2 = gain(k=3.0)
    np.testing.assert_allclose(g1.output(0.0, np.zeros(0), np.array([1.0])), [2.0])
    np.testing.assert_allclose(g2.output(0.0, np.zeros(0), np.array([1.0])), [3.0])
    assert g1._params == {"k": 2.0}
    assert g2._params == {"k": 3.0}


def test_required_parameter_missing_raises():
    @block
    def gain(t: float, u: float, *, k: float) -> float:
        return k * u

    with pytest.raises(BlockSpecError, match="missing required"):
        gain()


def test_unknown_parameter_raises():
    @block
    def gain(t: float, u: float, *, k: float = 1.0) -> float:
        return k * u

    with pytest.raises(BlockSpecError, match="unexpected"):
        gain(unknown=1.0)


# ---------------------------------------------------------------
# パラメータ型検証 (ADR-0003 §(7))
# ---------------------------------------------------------------


def test_param_type_validation_float_accepts_int():
    """numbers.Real で受けるので int も float 注釈で OK (ADR-0003 Risk 5)。"""

    @block
    def gain(t: float, u: float, *, k: float = 1.0) -> float:
        return k * u

    instance = gain(k=2)  # int
    np.testing.assert_allclose(instance.output(0.0, np.zeros(0), np.array([3.0])), [6.0])


def test_param_type_validation_rejects_str_for_float():
    @block
    def gain(t: float, u: float, *, k: float = 1.0) -> float:
        return k * u

    with pytest.raises(BlockSpecError, match="real number"):
        gain(k="hello")


def test_param_type_validation_rejects_bool_for_float():
    """bool は numbers.Real のサブクラスだが、float 注釈では拒否する。"""

    @block
    def gain(t: float, u: float, *, k: float = 1.0) -> float:
        return k * u

    with pytest.raises(BlockSpecError, match="real number"):
        gain(k=True)


# ---------------------------------------------------------------
# 推論失敗エラー (ADR-0003 §(2))
# ---------------------------------------------------------------


def test_inputs_inference_fails_on_ndarray_annotation():
    with pytest.raises(BlockSpecError, match="ndarray"):

        @block
        def bad(t: float, u: np.ndarray) -> float:
            return float(u[0])


def test_inputs_inference_fails_on_no_annotation():
    with pytest.raises(BlockSpecError, match="cannot infer"):

        @block
        def bad(t, u):
            return u


def test_outputs_inference_fails_on_ndarray_annotation():
    with pytest.raises(BlockSpecError, match="ndarray"):

        @block(inputs=2)
        def bad(t: float, u) -> np.ndarray:
            return np.array([u[0], u[1]])


def test_inputs_override_with_unannotated_u():
    """``inputs=N`` 明示で型注釈なしの ``u`` を ndarray 受けにできる。"""

    @block(inputs=3, outputs=1)
    def sum3(t: float, u) -> float:
        return float(u[0] + u[1] + u[2])

    instance = sum3()
    assert instance.n_inputs == 3
    np.testing.assert_allclose(instance.output(0.0, np.zeros(0), np.array([1.0, 2.0, 3.0])), [6.0])


def test_outputs_inference_warns_when_no_return_annotation(caplog):
    with caplog.at_level(logging.WARNING, logger="flode.decorator"):

        @block
        def gain(t: float, u: float, *, k: float = 1.0):
            return k * u

    assert any("no return type annotation" in r.message for r in caplog.records)
    assert gain().n_outputs == 1


def test_no_args_or_kwargs_in_function():
    with pytest.raises(BlockSpecError, match=r"\*args"):

        @block
        def bad(t: float, *args) -> float:
            return 0.0


def test_no_kwargs_in_function():
    with pytest.raises(BlockSpecError, match=r"\*\*kwargs"):

        @block
        def bad(t: float, u: float, **kwargs) -> float:
            return u


def test_states_must_be_non_negative():
    with pytest.raises(BlockSpecError, match="states"):

        @block(states=-1)
        def bad(t: float, u: float) -> float:
            return u


def test_variadic_tuple_annotation_rejected():
    with pytest.raises(BlockSpecError, match="variadic|inputs=N"):

        @block
        def bad(t: float, u: tuple[float, ...]) -> float:
            return float(u[0])


# ---------------------------------------------------------------
# class 版は後送り (ADR-0003 §(9))
# ---------------------------------------------------------------


# ---------------------------------------------------------------
# class 版 @block (Option C、ADR-0003 §(9) Phase 1 後半で追加)
# ---------------------------------------------------------------


class TestClassFormCombinational:
    def test_scalar_in_scalar_out(self):
        @block
        class Gain:
            k: float = 1.0

            def output(self, t: float, u: float) -> float:
                return self.k * u

        assert Gain.__name__ == "Gain"
        instance = Gain(k=3.0)
        assert instance.n_inputs == 1
        assert instance.n_outputs == 1
        assert instance.n_states == 0
        assert instance.direct_feedthrough is True
        np.testing.assert_allclose(instance.output(0.0, np.zeros(0), np.array([2.0])), [6.0])

    def test_source_no_u(self):
        @block
        class MyConst:
            value: float = 0.0

            def output(self, t: float) -> float:
                return self.value

        instance = MyConst(value=2.5)
        assert instance.n_inputs == 0
        np.testing.assert_allclose(instance.output(0.0, np.zeros(0), np.zeros(0)), [2.5])

    def test_mimo_tuple(self):
        @block
        class Splitter:
            def output(self, t: float, u: tuple[float, float]) -> tuple[float, float]:
                a, b = u
                return a + b, a - b

        instance = Splitter()
        assert instance.n_inputs == 2
        assert instance.n_outputs == 2
        np.testing.assert_allclose(
            instance.output(0.0, np.zeros(0), np.array([3.0, 1.0])),
            [4.0, 2.0],
        )


class TestClassFormStateful:
    def test_continuous_integrator(self):
        @block(states=1, direct_feedthrough=False)
        class MyIntegrator:
            x0: float = 0.0

            def output(self, t: float, x: np.ndarray, u: float) -> float:
                return x[0]

            def derivative(self, t: float, x: np.ndarray, u: float) -> np.ndarray:
                return np.array([u])

        instance = MyIntegrator(x0=1.5)
        assert instance.n_states == 1
        assert instance.direct_feedthrough is False
        np.testing.assert_allclose(instance.x0, [1.5])
        np.testing.assert_allclose(instance.output(0.0, np.array([2.0]), np.array([3.0])), [2.0])
        np.testing.assert_allclose(
            instance.derivative(0.0, np.array([2.0]), np.array([3.0])), [3.0]
        )

    def test_discrete_unitdelay(self):
        @block(states=1, sample_time=0.01, direct_feedthrough=False)
        class MyDelay:
            x0: float = 0.0

            def output(self, t: float, x: np.ndarray, u: float) -> float:
                return x[0]

            def update(self, t: float, x: np.ndarray, u: float) -> np.ndarray:
                return np.array([u])

        instance = MyDelay(x0=1.0)
        assert instance.sample_time == 0.01
        np.testing.assert_allclose(instance.update(0.0, np.array([5.0]), np.array([7.0])), [7.0])
        # 離散ブロックでは derivative は no-op
        np.testing.assert_allclose(
            instance.derivative(0.0, np.array([5.0]), np.array([7.0])), np.zeros(1)
        )


class TestClassFormErrors:
    def test_class_without_output_raises(self):
        with pytest.raises(BlockSpecError, match="output"):

            @block
            class NoOutput:
                pass

    def test_class_stateful_without_derivative_or_update_raises(self):
        with pytest.raises(BlockSpecError, match="derivative|update"):

            @block(states=1)
            class NoDerivative:
                def output(self, t: float, x: np.ndarray, u: float) -> float:
                    return x[0]

    def test_param_field_without_default_is_required(self):
        @block
        class Gain:
            k: float

            def output(self, t: float, u: float) -> float:
                return self.k * u

        with pytest.raises(BlockSpecError, match="missing required"):
            Gain()
        instance = Gain(k=2.0)
        np.testing.assert_allclose(instance.output(0.0, np.zeros(0), np.array([3.0])), [6.0])


class TestClassFormSimulatorIntegration:
    def test_runs_in_simulator(self):
        @block
        class MyConst:
            value: float = 1.0

            def output(self, t: float) -> float:
                return self.value

        @block
        class MyGain:
            k: float = 1.0

            def output(self, t: float, u: float) -> float:
                return self.k * u

        @block(states=1, direct_feedthrough=False)
        class MyIntegrator:
            x0: float = 0.0

            def output(self, t: float, x: np.ndarray, u: float) -> float:
                return x[0]

            def derivative(self, t: float, x: np.ndarray, u: float) -> np.ndarray:
                return np.array([u])

        sim = Simulator(t_end=1.0, dt=0.01, rtol=1e-8, atol=1e-10)
        src = sim.add(MyConst(value=1.0, id="src"))
        g = sim.add(MyGain(k=2.0, id="g"))
        integ = sim.add(MyIntegrator(x0=0.0, id="integ"))
        scope = sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect(src, g)
        sim.connect(g, integ)
        sim.connect(integ, scope)
        sim.run()
        # x_dot = 2、x(1) = 2
        assert scope.values[-1, 0] == pytest.approx(2.0, rel=1e-3)


class TestClassFormNaming:
    def test_explicit_name_overrides(self):
        @block(name="CustomGain")
        class Whatever:
            def output(self, t: float, u: float) -> float:
                return u

        assert Whatever.__name__ == "CustomGain"


class TestClassFormBlockBaseGuards:
    def test_user_method_does_not_override_block_base(self, caplog):
        """User class が Block 基底のメソッドと同名のメソッドを定義しても
        基底のメソッドを上書きしない (code-reviewer MUST 修正)。"""

        with caplog.at_level(logging.WARNING, logger="flode.decorator"):

            @block
            class CustomBlock:
                def output(self, t: float, u: float) -> float:
                    return u

                def __repr__(self) -> str:  # noqa: D401
                    return "user repr"

        # __repr__ は dunder なので除外され、Block 基底の repr が使われる
        instance = CustomBlock(id="b1")
        assert "<CustomBlock 'b1'>" == repr(instance)

    def test_extra_method_is_copied(self):
        """Sink 系の ``record`` のような追加メソッドは継承される。"""

        @block(inputs=1, outputs=1)
        class WithRecorder:
            def output(self, t: float, u) -> float:
                return float(u[0])

            def custom_helper(self) -> str:
                return "ok"

        instance = WithRecorder()
        assert instance.custom_helper() == "ok"


# ---------------------------------------------------------------
# 命名 (ADR-0003 §(6))
# ---------------------------------------------------------------


def test_class_name_default_pascal_case_from_snake_case():
    @block
    def unit_delay_demo(t: float, u: float) -> float:
        return u

    assert unit_delay_demo.__name__ == "UnitDelayDemo"


def test_class_name_default_for_single_word_lowercase():
    @block
    def gain(t: float, u: float) -> float:
        return u

    assert gain.__name__ == "Gain"


def test_class_name_explicit_override():
    @block(name="CustomName")
    def whatever(t: float, u: float) -> float:
        return u

    assert whatever.__name__ == "CustomName"


# ---------------------------------------------------------------
# Simulator 統合 (ADR-0003 §(5) の最終チェック)
# ---------------------------------------------------------------


def test_simulator_run_with_decorated_blocks():
    """Constant → Gain → Integrator (全て @block) で run() が成立し
    数値結果が解析解 (x(t) = 2t) と一致する。"""

    @block
    def my_constant(t: float, *, value: float = 0.0) -> float:
        return value

    @block
    def my_gain(t: float, u: float, *, k: float = 1.0) -> float:
        return k * u

    @block(states=1, direct_feedthrough=False)
    def my_integrator(
        t: float, x: np.ndarray, u: float, *, x0: float = 0.0
    ) -> tuple[float, np.ndarray]:
        return x[0], np.array([u])

    sim = Simulator(t_end=1.0, dt=0.01, rtol=1e-8, atol=1e-10)
    src = sim.add(my_constant(value=1.0, id="src"))
    g = sim.add(my_gain(k=2.0, id="g"))
    integ = sim.add(my_integrator(x0=0.0, id="integ"))
    scope = sim.add(Scope(n_inputs=1, id="scope"))

    sim.connect(src, g)
    sim.connect(g, integ)
    sim.connect(integ, scope)

    sim.run()

    # x(t) = 2t なので t=1.0 で 2.0
    assert scope.values[-1, 0] == pytest.approx(2.0, rel=1e-3)


def test_inherited_sample_time_resolves_to_continuous():
    """``sample_time=-1.0`` で上流が連続のとき、生成 Block は連続として動く。

    MUST 修正 (ADR-0003 Risk 4) の回帰テスト: ``_resolved_sample_time`` を見て
    ``derivative`` / ``update`` を分岐する実装が機能することを確認する。
    """

    @block(states=1, sample_time=-1.0, direct_feedthrough=False)
    def inh_integrator(
        t: float, x: np.ndarray, u: float, *, x0: float = 0.0
    ) -> tuple[float, np.ndarray]:
        return x[0], np.array([u])

    from flode.blocks import Constant

    sim = Simulator(t_end=0.1, dt=0.01, rtol=1e-8, atol=1e-10)
    src = sim.add(Constant(value=1.0, id="src"))
    integ = sim.add(inh_integrator(x0=0.0, id="integ"))
    scope = sim.add(Scope(n_inputs=1, id="scope"))
    sim.connect(src, integ)
    sim.connect(integ, scope)
    sim.run()

    # 上流 (Constant) は連続なので integ も連続として解決される
    assert integ._resolved_sample_time is None
    # 連続積分: x(0.1) ≈ 0.1
    assert scope.values[-1, 0] == pytest.approx(0.1, rel=1e-3, abs=1e-4)


def test_inherited_sample_time_resolves_to_discrete():
    """``sample_time=-1.0`` で上流が離散のとき、生成 Block は離散として動く。

    MUST 修正の中核回帰テスト: 継承解決後に離散と判明したブロックの ``update``
    が呼ばれること、``derivative`` が no-op になることを確認する。
    """
    from flode.blocks import Constant, UnitDelay

    @block(states=1, sample_time=-1.0, direct_feedthrough=False)
    def inh_passthrough(
        t: float, x: np.ndarray, u: float, *, x0: float = 0.0
    ) -> tuple[float, np.ndarray]:
        # y = x、x_next = u (UnitDelay 相当)
        return x[0], np.array([u])

    sim = Simulator(t_end=0.05, dt=0.01)
    src = sim.add(Constant(value=2.0, id="src"))
    delay = sim.add(UnitDelay(sample_time=0.01, x0=0.0, id="delay"))
    inh = sim.add(inh_passthrough(x0=0.0, id="inh"))
    scope = sim.add(Scope(n_inputs=1, id="scope"))
    sim.connect(src, delay)
    sim.connect(delay, inh)
    sim.connect(inh, scope)
    sim.run()

    assert inh._resolved_sample_time == pytest.approx(0.01)
    # delay が 1 ステップ遅延 (t=0 で 0、以降 2.0)
    # inh も 1 ステップ遅延 → t=0,0.01 で 0、以降 2.0
    values = scope.values[:, 0]
    assert values[0] == pytest.approx(0.0)
    assert values[1] == pytest.approx(0.0)
    assert values[-1] == pytest.approx(2.0)


def test_states_greater_than_one_with_vector_x0():
    """``states>1`` でベクトル ``x0`` を受けられる (調和振動子)。"""

    @block(states=2, direct_feedthrough=False)
    def harmonic(t: float, x: np.ndarray, u: float, *, x0: np.ndarray) -> tuple[float, np.ndarray]:
        # x[0] = position, x[1] = velocity
        # x_dot = (velocity, -position) → simple harmonic oscillator
        return x[0], np.array([x[1], -x[0]])

    instance = harmonic(x0=np.array([1.0, 0.0]))
    assert instance.n_states == 2
    np.testing.assert_allclose(instance.x0, [1.0, 0.0])

    y = instance.output(0.0, np.array([0.5, 0.7]), np.array([0.0]))
    np.testing.assert_allclose(y, [0.5])
    xd = instance.derivative(0.0, np.array([0.5, 0.7]), np.array([0.0]))
    np.testing.assert_allclose(xd, [0.7, -0.5])


def test_states_x0_shape_mismatch_raises():
    @block(states=2, direct_feedthrough=False)
    def two_state(t: float, x: np.ndarray, u: float, *, x0: np.ndarray) -> tuple[float, np.ndarray]:
        return x[0], np.zeros(2)

    with pytest.raises(BlockSpecError, match="x0 has shape"):
        two_state(x0=np.array([1.0]))  # shape (1,) != (2,)


def test_inputs_override_rejects_bool():
    """``inputs=True`` を ``inputs=1`` として通さない (MUST 修正)。"""
    with pytest.raises(BlockSpecError, match="non-negative int"):

        @block(inputs=True)
        def bad(t: float, u) -> float:
            return 0.0


def test_outputs_override_rejects_bool():
    with pytest.raises(BlockSpecError, match="positive int"):

        @block(inputs=1, outputs=True)
        def bad(t: float, u) -> float:
            return 0.0


def test_outputs_zero_message_mentions_sink_alternative():
    """``outputs=0`` のエラーメッセージが Sink 代替手段を案内する (SHOULD 修正)。"""
    with pytest.raises(BlockSpecError, match="Sink|Block inheritance"):

        @block(inputs=1, outputs=0)
        def bad(t: float, u) -> float:
            return 0.0


def test_states_return_tuple_second_element_must_be_ndarray():
    """``tuple[float, float]`` を ``states>0`` の戻り値型注釈で渡すとエラー (SHOULD 修正)。"""
    with pytest.raises(BlockSpecError, match="np.ndarray"):

        @block(states=1)
        def bad(t: float, x: np.ndarray, u: float) -> tuple[float, float]:
            return x[0], 0.0  # type: ignore[return-value]


def test_simulator_run_two_independent_decorated_gains():
    """同一 ``@block`` 関数から作った 2 つのインスタンスが独立に動く。"""

    @block
    def my_gain(t: float, u: float, *, k: float = 1.0) -> float:
        return k * u

    sim = Simulator(t_end=0.05, dt=0.01)
    from flode.blocks import Constant

    src = sim.add(Constant(value=1.0, id="src"))
    g1 = sim.add(my_gain(k=2.0, id="g1"))
    g2 = sim.add(my_gain(k=3.0, id="g2"))
    scope = sim.add(Scope(n_inputs=2, id="scope"))

    sim.connect(src, g1)
    sim.connect(src, g2)
    sim.connect(g1, scope, dst_idx=0)
    sim.connect(g2, scope, dst_idx=1)

    sim.run()
    np.testing.assert_allclose(scope.values[:, 0], 2.0)
    np.testing.assert_allclose(scope.values[:, 1], 3.0)


# ---------------------------------------------------------------
# ADR-0073 §論点 2-D: ``_flode_structure`` (インスタンス化せずに構造を読む)
# ---------------------------------------------------------------


class TestFlodeStructure:
    """生成 class の ``_flode_structure`` が推論結果と一致し、インスタンス化不要で読める。"""

    def test_function_form_exposes_structure(self):
        @block(states=1, sample_time=0.1)
        def delay2(
            t: float, x: np.ndarray, u: tuple[float, float], *, k: float
        ) -> tuple[tuple[float, float], np.ndarray]:
            return (k * u[0], k * u[1]), np.array([u[0]])

        s = delay2._flode_structure
        assert (s.n_inputs, s.n_outputs, s.n_states) == (2, 2, 1)
        assert s.direct_feedthrough is False
        assert s.sample_time == 0.1
        # 必須パラメータ ``k`` を渡さずに構造が読めている (= インスタンス化不要)
        with pytest.raises(BlockSpecError, match="missing required parameter"):
            delay2()

    def test_class_form_exposes_structure(self):
        @block(states=1, direct_feedthrough=True)
        class Leaky:
            x0: float = 0.0

            def output(self, t: float, x: np.ndarray, u: float) -> float:
                return x[0] + u

            def derivative(self, t: float, x: np.ndarray, u: float) -> np.ndarray:
                return np.array([-x[0] + u])

        s = Leaky._flode_structure
        assert (s.n_inputs, s.n_outputs, s.n_states) == (1, 1, 1)
        assert s.direct_feedthrough is True
        assert s.sample_time is None

    def test_npt_ndarray_alias_accepted_for_state_return(self):
        """numpy 2.x の ``npt.NDArray`` (TypeAliasType) を戻り値 2 番目として受理する。"""

        @block(states=1)
        def integ(t: float, x: np.ndarray, u: float) -> tuple[float, npt.NDArray[Any]]:
            return x[0], np.array([u])

        assert integ._flode_structure.n_states == 1
        inst = integ()
        np.testing.assert_allclose(inst.derivative(0.0, np.zeros(1), np.array([2.0])), [2.0])

    def test_npt_ndarray_alias_rejected_as_input_annotation(self):
        """``npt.NDArray[Any]`` を ``u`` の注釈にするとサイズ不明として拒否 (bare ndarray と同じ)。"""
        with pytest.raises(BlockSpecError, match="ndarray annotation"):

            @block
            def f(t: float, u: npt.NDArray[Any]) -> float:
                return float(u[0])

    def test_structure_matches_instance_attributes(self):
        @block
        def src(t: float) -> tuple[float, float, float]:
            return t, 2 * t, 3 * t

        inst = src()
        s = src._flode_structure
        assert s.n_inputs == inst.n_inputs == 0
        assert s.n_outputs == inst.n_outputs == 3
        assert s.n_states == inst.n_states == 0
        assert s.direct_feedthrough == inst.direct_feedthrough
        assert s.sample_time == inst.sample_time


# ---------------------------------------------------------------
# SPEC-0024 / ADR-0074: input_names / output_names (N1〜N8)
# ---------------------------------------------------------------


class TestPortNames:
    def test_names_stored_in_structure_function_form(self):
        @block(input_names=("速度指令", "負荷トルク"), output_names=("トルク",))
        def controller(t: float, u: tuple[float, float], *, kp: float = 1.0) -> float:
            return kp * (u[0] - u[1])

        s = controller._flode_structure
        assert s.input_names == ("速度指令", "負荷トルク")
        assert s.output_names == ("トルク",)
        assert s.has_u_arg is True

    def test_default_is_empty_and_has_u_arg_false_for_source(self):
        @block
        def src(t: float) -> float:
            return t

        s = src._flode_structure
        assert s.input_names == ()
        assert s.output_names == ()
        assert s.has_u_arg is False

    def test_names_class_form(self):
        @block(input_names=("in",), output_names=("out",))
        class Pass:
            def output(self, t: float, u: float) -> float:
                return u

        s = Pass._flode_structure
        assert s.input_names == ("in",)
        assert s.output_names == ("out",)
        assert s.has_u_arg is True

    def test_length_mismatch_raises(self):
        with pytest.raises(BlockSpecError, match="must match exactly"):

            @block(input_names=("a", "b", "c"))
            def f(t: float, u: tuple[float, float]) -> float:
                return u[0]

    def test_non_str_element_raises(self):
        with pytest.raises(BlockSpecError, match="must be a str"):

            @block(input_names=(1,))  # type: ignore[arg-type]
            def f(t: float, u: float) -> float:
                return u

    def test_bare_string_rejected(self):
        with pytest.raises(BlockSpecError, match="sequence of str"):

            @block(input_names="ab")  # type: ignore[arg-type]
            def f(t: float, u: tuple[float, float]) -> float:
                return u[0]

    def test_control_char_rejected(self):
        with pytest.raises(BlockSpecError, match="control/format"):

            @block(input_names=("a\nb",))
            def f(t: float, u: float) -> float:
                return u

    def test_over_32_codepoints_rejected(self):
        with pytest.raises(BlockSpecError, match="32 code points"):

            @block(input_names=("x" * 33,))
            def f(t: float, u: float) -> float:
                return u

    def test_caption_semantics_allowed(self):
        """空白・絵文字・重複・空文字 (無名)・正規化なし = キャプション扱い (N6〜N8)。"""
        nfd = "ガ"  # NFD (カ + 濁点) のまま保持されること

        @block(input_names=("a b 🚀", "a b 🚀", "", nfd))
        def f(t: float, u: tuple[float, float, float, float]) -> float:
            return u[0]

        assert f._flode_structure.input_names == ("a b 🚀", "a b 🚀", "", nfd)
        assert f._flode_structure.input_names[3] == nfd  # NFC 化されていない
