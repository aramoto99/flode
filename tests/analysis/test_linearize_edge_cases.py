"""ADR-0026: 線形化のエラーパス / 境界値テスト。"""

from __future__ import annotations

import numpy as np
import pytest

from flode import LinearSystem, Simulator, linearize
from flode.blocks import Constant, Integrator, Scope, UnitDelay
from flode.exceptions import BlockSpecError, SolverError


class TestPureDiscreteRejected:
    """連続状態がゼロのモデル (= 純離散) は ``BlockSpecError`` で拒否される。"""

    def test_pure_discrete_raises(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.1)
        ud = sim.add(UnitDelay(sample_time=0.1))
        sim.connect(ud, sim.add(Scope()))
        with pytest.raises(BlockSpecError, match="continuous states"):
            linearize(sim)


class TestDiscreteWithContinuous:
    """ハイブリッド (連続 + 離散) モデル: warning が出て連続部分のみ線形化。"""

    def test_warning_emitted(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.1)
        i = sim.add(Integrator())
        ud = sim.add(UnitDelay(sample_time=0.1))
        sim.connect(i, ud)
        sim.connect(ud, sim.add(Scope()))
        with pytest.warns(UserWarning, match="discrete blocks are held"):
            ls = linearize(sim)
        # 連続部分 (Integrator 1 状態) のみが線形化対象
        assert ls.A.shape == (1, 1)


class TestInvalidShapes:
    """``x`` / ``u`` の shape 不整合で ``BlockSpecError``。"""

    def test_x_wrong_shape(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        with pytest.raises(BlockSpecError, match=r"x must have shape"):
            linearize(sim, x=np.array([1.0, 2.0]))  # 期待 (1,)

    def test_u_wrong_shape(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        with pytest.raises(BlockSpecError, match=r"u must have shape"):
            linearize(sim, u=np.array([1.0, 2.0, 3.0]))  # 期待 (1,)


class TestMethodValidation:
    """``method`` 引数の validation。"""

    def test_jax_method_works_with_supported_blocks(self) -> None:
        """ADR-0037 (v0.17.0): ``method="jax"`` は ``flode[codegen]`` で動く。

        Integrator は ``_SUPPORTED_BLOCK_TYPES`` に含まれるため、本テストでは
        ``BlockSpecError`` ではなく機械精度結果が返る (中心差分との一致は
        ``tests/test_linearize_jax_consistency.py`` で別途検証)。
        """
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls = linearize(sim, method="jax")
        assert ls.A.shape == (1, 1)

    def test_invalid_method(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        with pytest.raises(ValueError, match="method must be"):
            linearize(sim, method="bogus")  # type: ignore[arg-type]

    def test_invalid_epsilon(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        with pytest.raises(ValueError, match="epsilon must be"):
            linearize(sim, epsilon=0.0)
        with pytest.raises(ValueError, match="epsilon must be"):
            linearize(sim, epsilon=-1e-6)


class TestEpsilonOverride:
    """``epsilon`` の override が反映される (= 異なる step で異なる精度)。"""

    def test_small_epsilon_still_works(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        # 過剰小 epsilon でも数値が finite (桁落ちで精度落ちるが panic しない)
        ls = linearize(sim, epsilon=1e-12)
        assert np.all(np.isfinite(ls.A))

    def test_large_epsilon(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        # 大きすぎる epsilon は許容されるが、精度は default より悪い
        ls = linearize(sim, epsilon=1e-3)
        # Integrator は線形なので epsilon に依存せず正解
        np.testing.assert_allclose(ls.A, [[0.0]], atol=1e-9)
        np.testing.assert_allclose(ls.B, [[1.0]], atol=1e-9)


class TestConstantSourceConnected:
    """Constant 入力 (定数 source) が結線済みなら external input から外される。"""

    def test_constant_input_not_external(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        c = sim.add(Constant(value=2.5))
        i = sim.add(Integrator())
        sim.connect(c, i)
        sim.connect(i, sim.add(Scope()))
        ls = linearize(sim)
        # Integrator の入力は Constant に結線済み → external input ではない
        assert ls.B.shape == (1, 0)
        # Constant は state を持たず、derivative にも寄与しない
        assert ls.A.shape == (1, 1)


class TestForwardDifferenceLessAccurate:
    """``method="forward"`` は中心差分より精度が悪い (= 確認のみ)。"""

    def test_forward_vs_central_for_nonlinear_block(self) -> None:
        # Constant + Integrator は線形なので forward でも正確。差を見るために
        # ここでは forward 結果が中心差分結果と概ね一致することのみ確認。
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Integrator())
        sim.connect(sim.blocks[0], sim.add(Scope()))
        ls_central = linearize(sim, method="central")
        ls_forward = linearize(sim, method="forward")
        np.testing.assert_allclose(ls_central.A, ls_forward.A, atol=1e-6)
        np.testing.assert_allclose(ls_central.B, ls_forward.B, atol=1e-6)
        np.testing.assert_allclose(ls_central.C, ls_forward.C, atol=1e-6)


class TestNanInfOperatingPoint:
    """動作点 (x, u) に NaN/Inf が含まれると ``SolverError`` が発生する。"""

    def test_nan_x_raises_solver_error(self) -> None:
        """x に NaN を渡すと derivative が NaN を返し SolverError。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator())
        sim.connect(i, sim.add(Scope()))
        with pytest.raises(SolverError, match="NaN/Inf"):
            linearize(sim, x=np.array([float("nan")]))

    def test_inf_u_raises_solver_error(self) -> None:
        """u に Inf を渡すと derivative が Inf を返し SolverError。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator())
        sim.connect(i, sim.add(Scope()))
        with pytest.raises(SolverError, match="NaN/Inf"):
            linearize(sim, u=np.array([float("inf")]))


class TestEpsilonPrecisionGradient:
    """epsilon の大小で精度が変わる境界値を検証する。

    中心差分の最適 epsilon は ``sqrt(eps_machine)`` (~1.5e-8) 付近。
    ``epsilon=1e-2`` は打ち切り誤差大、``epsilon=1e-6`` は最適域、
    ``epsilon=1e-14`` は桁落ち誤差大、となることを数値で確認する。
    モデルは ``Integrator → Saturation(wide) → Scope`` (x=1.0 で線形域にある)。
    """

    def _make_sim(self) -> Simulator:
        from flode.blocks import Saturation

        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator(id="i"))
        sat = sim.add(Saturation(lower=-10.0, upper=10.0, id="sat"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(i, sat)
        sim.connect(sat, sc)
        return sim

    def test_epsilon_1e2_and_1e6_both_pass_spec(self) -> None:
        """epsilon=1e-2 / 1e-6 はどちらも rtol=1e-3 の仕様内に収まる。"""
        sim = self._make_sim()
        for eps in [1e-2, 1e-6]:
            ls = linearize(sim, x=np.array([1.0]), epsilon=eps)
            np.testing.assert_allclose(ls.C, [[1.0]], rtol=1e-3, err_msg=f"eps={eps}")

    def test_epsilon_1e14_degrades_accuracy(self) -> None:
        """epsilon=1e-14 (桁落ち域) は最適 epsilon より精度が落ちる。"""
        import math

        sim = self._make_sim()
        eps_opt = float(np.sqrt(np.finfo(np.float64).eps))
        ls_opt = linearize(sim, x=np.array([1.0]), epsilon=eps_opt)
        ls_tiny = linearize(sim, x=np.array([1.0]), epsilon=1e-14)
        err_opt = abs(float(ls_opt.C[0, 0]) - 1.0)
        err_tiny = abs(float(ls_tiny.C[0, 0]) - 1.0)
        # 両者とも有限値
        assert math.isfinite(float(ls_tiny.C[0, 0]))
        # 過小 epsilon は最適 epsilon より誤差が大きい
        assert err_tiny > err_opt


class TestCentralVsForwardNonlinear:
    """非線形入力写像 (cubic: xdot = u^3) で中心差分が前進差分より精度が高い。

    解析解: B = d(u^3)/du|_{u=1} = 3.0。
    epsilon = default (sqrt(eps)) で中心差分の誤差 < 前進差分の誤差 を確認。
    """

    def test_central_more_accurate_than_forward_for_cubic_nonlinearity(
        self,
    ) -> None:
        from flode import block

        @block(states=1)  # type: ignore[untyped-decorator]
        def cubic_integrator(t: float, x: np.ndarray, u: float) -> tuple[float, np.ndarray]:
            """y = x, xdot = u^3 (cubic nonlinearity)."""
            return float(x[0]), np.array([u**3])

        sim = Simulator(t_end=1.0, dt=0.01)
        ci = sim.add(cubic_integrator(id="ci"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(ci, sc)

        ls_c = linearize(sim, x=np.array([0.0]), u=np.array([1.0]), method="central")
        ls_f = linearize(sim, x=np.array([0.0]), u=np.array([1.0]), method="forward")
        err_c = abs(float(ls_c.B[0, 0]) - 3.0)
        err_f = abs(float(ls_f.B[0, 0]) - 3.0)
        assert err_c < err_f, (
            f"central error {err_c:.2e} should be smaller than forward error {err_f:.2e}"
        )


class TestNonlinearOperatingPointDependence:
    """非線形ブロック (Saturation) は動作点によって線形化結果が変わる。"""

    def _make_sat_sim(self) -> Simulator:
        from flode.blocks import Saturation

        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator(id="i"))
        sat = sim.add(Saturation(lower=-1.0, upper=1.0, id="sat"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(i, sat)
        sim.connect(sat, sc)
        return sim

    def test_linear_regime_c_equals_one(self) -> None:
        """動作点 x=0 (線形域): C = [[1]] (Saturation が透明)。"""
        sim = self._make_sat_sim()
        ls = linearize(sim, x=np.array([0.0]))
        np.testing.assert_allclose(ls.C, [[1.0]], atol=1e-5)

    def test_saturated_regime_c_equals_zero(self) -> None:
        """動作点 x=2.0 (飽和域): C = [[0]] (出力が状態に依存しなくなる)。"""
        sim = self._make_sat_sim()
        ls = linearize(sim, x=np.array([2.0]))
        np.testing.assert_allclose(ls.C, [[0.0]], atol=1e-5)

    def test_b_invariant_across_saturation_state(self) -> None:
        """B (= ∂xdot/∂u) は Saturation に依らず [[1]] (Integrator の入力は外部から)。

        注意: Integrator の入力は Saturation ではなく外部 u から来ている。
        Saturation は Integrator の「後段」なので B は変わらない。
        """
        sim = self._make_sat_sim()
        for x_val in [0.0, 2.0]:
            ls = linearize(sim, x=np.array([x_val]))
            np.testing.assert_allclose(ls.B, [[1.0]], atol=1e-5, err_msg=f"x={x_val}")


class TestTerminatorIsNotSink:
    """Terminator は ``_is_sink`` に認識されない (``record`` メソッドを持たないため)。

    ADR-0026 §: ``_is_sink = n_outputs==0 and hasattr(block, 'record')``。
    Terminator は n_outputs==0 だが record を持たないので sink 扱いにならない。
    その結果、Terminator への入力は外部出力としてカウントされず C.shape[0] == 0。
    """

    def test_terminator_does_not_expose_output_dimension(self) -> None:
        """Terminator のみに接続した Integrator は外部出力を持たない。"""
        from flode.blocks import Terminator

        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator(id="i"))
        term = sim.add(Terminator(id="term"))
        sim.connect(i, term)
        ls = linearize(sim)
        # Terminator は sink でないため Integrator 出力は外部出力に露出しない
        assert ls.C.shape[0] == 0
        assert ls.D.shape[0] == 0
        assert ls.output_names == []


class TestIsSinkDuckType:
    """``_is_sink`` の duck-type 判定ロジックを直接検証する。"""

    def test_scope_is_sink(self) -> None:
        """Scope: n_outputs=0 かつ record → sink True。"""
        from flode.analysis.linearize import _is_sink
        from flode.blocks import Scope

        assert _is_sink(Scope())

    def test_display_is_sink(self) -> None:
        """Display: n_outputs=0 かつ record → sink True。"""
        from flode.analysis.linearize import _is_sink
        from flode.blocks import Display

        assert _is_sink(Display())

    def test_xygraph_is_sink(self) -> None:
        """XYGraph: n_outputs=0 かつ record → sink True。"""
        from flode.analysis.linearize import _is_sink
        from flode.blocks import XYGraph

        assert _is_sink(XYGraph())

    def test_terminator_is_not_sink(self) -> None:
        """Terminator: n_outputs=0 だが record なし → sink False。"""
        from flode.analysis.linearize import _is_sink
        from flode.blocks import Terminator

        assert not _is_sink(Terminator())

    def test_custom_sink_with_record_is_sink(self) -> None:
        """n_outputs=0 かつ record を持つカスタムブロック → sink True (duck-type)。"""
        from flode import Block
        from flode.analysis.linearize import _is_sink

        class CustomSink(Block):
            """テスト用カスタム sink。"""

            def __init__(self) -> None:
                super().__init__(n_inputs=1, n_outputs=0)

            def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
                return np.zeros(0)

            def record(self, t: float, u: np.ndarray) -> None:
                pass

        assert _is_sink(CustomSink())

    def test_block_with_record_but_outputs_is_not_sink(self) -> None:
        """n_outputs > 0 で record を持つブロックは sink でない (出力側は sink 扱い不可)。"""
        from flode import Block
        from flode.analysis.linearize import _is_sink

        class FakeBlock(Block):
            """record を持つが n_outputs=1 → sink でない。"""

            def __init__(self) -> None:
                super().__init__(n_inputs=1, n_outputs=1)

            def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
                return np.array([u[0]])

            def record(self, t: float, u: np.ndarray) -> None:
                pass

        assert not _is_sink(FakeBlock())


class TestDisplayXYGraphAsSink:
    """Display / XYGraph を sink として使った場合に線形化が正しく動く。"""

    def test_display_sink_gives_correct_abcd(self) -> None:
        """Display を sink として Integrator の出力を観察 → ABCD は Scope と同等。"""
        from flode.blocks import Display

        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator(id="i"))
        disp = sim.add(Display(id="disp"))
        sim.connect(i, disp)
        ls = linearize(sim)
        # Integrator: A=0, B=1, C=1, D=0
        np.testing.assert_allclose(ls.A, [[0.0]], atol=1e-12)
        np.testing.assert_allclose(ls.B, [[1.0]], atol=1e-12)
        np.testing.assert_allclose(ls.C, [[1.0]], atol=1e-12)
        np.testing.assert_allclose(ls.D, [[0.0]], atol=1e-12)
        assert ls.output_names == [f"{i.id}.out[0][0]"]

    def test_xygraph_sink_gives_two_outputs(self) -> None:
        """XYGraph を sink として 2 つの Integrator を観察 → 2 出力。"""
        from flode.blocks import XYGraph

        sim = Simulator(t_end=1.0, dt=0.01)
        i1 = sim.add(Integrator(id="i1"))
        i2 = sim.add(Integrator(id="i2"))
        xy = sim.add(XYGraph(id="xy"))
        sim.connect(i1, xy, dst_idx=0)
        sim.connect(i2, xy, dst_idx=1)
        ls = linearize(sim)
        assert ls.A.shape == (2, 2)
        assert ls.C.shape[0] == 2
        assert len(ls.output_names) == 2


class TestLinearSystemDataclass:
    """LinearSystem dataclass の frozen / eq=False / operating_point 仕様。"""

    def _make_ls(self) -> LinearSystem:
        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator())
        sim.connect(i, sim.add(Scope()))
        return linearize(sim)

    def test_frozen_raises_on_assignment(self) -> None:
        """frozen=True: ``ls.A = ...`` で FrozenInstanceError。"""
        from dataclasses import FrozenInstanceError

        ls = self._make_ls()
        with pytest.raises(FrozenInstanceError):
            ls.A = np.zeros((1, 1))  # type: ignore[misc]

    def test_eq_false_different_instances_are_not_equal(self) -> None:
        """eq=False: 2 回 linearize して得た別インスタンスは ``==`` で False (id 比較)。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        i = sim.add(Integrator())
        sim.connect(i, sim.add(Scope()))
        ls1 = linearize(sim)
        ls2 = linearize(sim)
        assert ls1 is not ls2
        assert ls1 != ls2

    def test_operating_point_keys_and_types(self) -> None:
        """operating_point は keys={'t','x','u'}, t が float, x/u が ndarray。"""
        ls = self._make_ls()
        op = ls.operating_point
        assert set(op.keys()) == {"t", "x", "u"}
        assert isinstance(op["t"], float)
        assert isinstance(op["x"], np.ndarray)
        assert isinstance(op["u"], np.ndarray)

    def test_to_control_ss_returns_new_instance_each_call(self) -> None:
        """``to_control_ss()`` を 2 回呼んでも毎回新しいインスタンスを返す。"""
        control = pytest.importorskip("control")
        ls = self._make_ls()
        ss1 = ls.to_control_ss()
        ss2 = ls.to_control_ss()
        assert isinstance(ss1, control.StateSpace)
        assert ss1 is not ss2
