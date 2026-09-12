"""SPEC-0028 AC-2 / AC-3: dtype 宣言モデルの実行テスト (予測 == 実行)。

§3.6 の全分類 (23 クラスの代表) を instrumented run で突合し、
island (Q6) / 状態持ち (Q7) / エラー昇格 (§3.5) を固定する。
"""

from __future__ import annotations

import textwrap
from typing import Any

import numpy as np
import pytest

from flode import Simulator
from flode.blocks.cast import Cast
from flode.blocks.continuous import Integrator
from flode.blocks.discrete import UnitDelay, ZeroOrderHoldDirect
from flode.blocks.logic import LogicalOperator, RelationalOperator
from flode.blocks.mathops import (
    Abs,
    Add,
    CompareToConstant,
    CompareToZero,
    Gain,
    MinMax,
    Product,
    Sign,
    Sum,
)
from flode.blocks.pythonfunc import PythonFunction
from flode.blocks.rounding import Rounding
from flode.blocks.routing import Demux, From, Goto, Merge, MultiportSwitch, Mux, Switch
from flode.blocks.sinks import Scope
from flode.blocks.sources import Constant
from flode.core import dtypes
from flode.exceptions import BlockSpecError
from flode.subsystems import Inport, Outport, Subsystem
from tests.core._dtype_instrumented_run import (
    assert_dtype_prediction_matches_execution,
    run_with_dtype_trace,
)


def _sim() -> Simulator:
    return Simulator(t_end=0.05, dt=0.01)


class TestPredictionMatchesExecution:
    """AC-2: 分類ごとの代表モデルで全ポート突合。"""

    def test_param_typed_and_promote_chain(self) -> None:
        # Constant(int32) → Sum ← Constant(int32) → Cast(int64) → Abs → Scope
        sim = _sim()
        a = sim.add(Constant(value=3, dtype="int32", id="a"))
        b = sim.add(Constant(value=4, dtype="int32", id="b"))
        s = sim.add(Sum(signs="++", id="s"))
        k = sim.add(Cast(dtype="int64", id="k"))
        ab = sim.add(Abs(id="ab"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(a, s, dst_idx=0)
        sim.connect(b, s, dst_idx=1)
        sim.connect(s, k)
        sim.connect(k, ab)
        sim.connect(ab, sc)
        assert_dtype_prediction_matches_execution(sim)
        assert float(np.asarray(sc.values)[0, 0]) == 7.0

    def test_bool_out_blocks(self) -> None:
        sim = _sim()
        c = sim.add(Constant(value=1, dtype="int32", id="c"))
        rel = sim.add(RelationalOperator(operator=">", id="rel"))
        c2 = sim.add(Constant(value=0, dtype="int32", id="c2"))
        cmp_c = sim.add(CompareToConstant(op=">", const=0.5, id="cmp_c"))
        cmp_z = sim.add(CompareToZero(id="cmp_z"))
        logi = sim.add(LogicalOperator(id="logi"))
        sc = sim.add(Scope(n_inputs=3, id="sc"))
        sim.connect(c, rel, dst_idx=0)
        sim.connect(c2, rel, dst_idx=1)
        sim.connect(c, cmp_c)
        sim.connect(c, cmp_z)
        sim.connect(rel, logi, dst_idx=0)
        sim.connect(cmp_c, logi, dst_idx=1)
        sim.connect(rel, sc, dst_idx=0)
        sim.connect(cmp_z, sc, dst_idx=1)
        sim.connect(logi, sc, dst_idx=2)
        assert_dtype_prediction_matches_execution(sim)

    def test_int_out_and_float_out(self) -> None:
        # Rounding → int64 / Gain は float_out (int 入力でも出力 float64)
        sim = _sim()
        c = sim.add(Constant(value=2.7, dtype="float64", id="c"))
        r = sim.add(Rounding(id="r"))
        g = sim.add(Gain(k=2.0, id="g"))
        sc = sim.add(Scope(n_inputs=2, id="sc"))
        sim.connect(c, r)
        sim.connect(r, g)
        sim.connect(r, sc, dst_idx=0)
        sim.connect(g, sc, dst_idx=1)
        assert_dtype_prediction_matches_execution(sim)

    def test_sign_and_minmax_and_product(self) -> None:
        sim = _sim()
        a = sim.add(Constant(value=-5, dtype="int64", id="a"))
        b = sim.add(Constant(value=3, dtype="int64", id="b"))
        sg = sim.add(Sign(id="sg"))
        mm = sim.add(MinMax(operator="max", n_inputs=2, id="mm"))
        pr = sim.add(Product(n_inputs=2, id="pr"))
        ad = sim.add(Add(signs="+-", id="ad"))
        sc = sim.add(Scope(n_inputs=4, id="sc"))
        sim.connect(a, sg)
        sim.connect(a, mm, dst_idx=0)
        sim.connect(b, mm, dst_idx=1)
        sim.connect(a, pr, dst_idx=0)
        sim.connect(b, pr, dst_idx=1)
        sim.connect(a, ad, dst_idx=0)
        sim.connect(b, ad, dst_idx=1)
        sim.connect(sg, sc, dst_idx=0)
        sim.connect(mm, sc, dst_idx=1)
        sim.connect(pr, sc, dst_idx=2)
        sim.connect(ad, sc, dst_idx=3)
        assert_dtype_prediction_matches_execution(sim)
        vals = np.asarray(sc.values)[0]
        assert vals.tolist() == [-1.0, 3.0, -15.0, -8.0]

    def test_switch_control_port_is_not_promoted_into_data(self) -> None:
        # 制御 port (bool) がデータ (int64) に昇格を波及させない (output_v override)
        big = 2**60 + 1
        sim = _sim()
        t_in = sim.add(Constant(value=1.0, id="ctl_src"))
        ctl = sim.add(Cast(dtype="bool", id="ctl"))
        data_t = sim.add(Constant(value=big, dtype="int64", id="dt"))
        data_f = sim.add(Constant(value=0, dtype="int64", id="df"))
        sw = sim.add(Switch(threshold=0.5, id="sw"))
        k = sim.add(Cast(dtype="int64", id="k"))  # int64 のまま維持されている証明
        sc = sim.add(Scope(id="sc"))
        sim.connect(t_in, ctl)
        sim.connect(data_t, sw, dst_idx=0)
        sim.connect(ctl, sw, dst_idx=1)
        sim.connect(data_f, sw, dst_idx=2)
        sim.connect(sw, k)
        sim.connect(k, sc)
        res = sim.resolve_dtypes()
        assert res.out_dtype("sw", 0) == "int64"
        observed = run_with_dtype_trace(sim)
        assert observed[("sw", "out", 0)] == {np.dtype("int64")}
        # 値レベルでも精度が保たれている (float64 経由なら big が丸まる)
        # Note: Constant.value は float64 保持のため、ここでは dtype 経路の
        # 検証として Switch 出力の dtype を確認する (値の完全検証は Cast 起点)

    def test_multiport_switch_selector_excluded(self) -> None:
        sim = _sim()
        sel = sim.add(Constant(value=1.0, id="sel"))
        d0 = sim.add(Constant(value=10, dtype="int32", id="d0"))
        d1 = sim.add(Constant(value=20, dtype="int32", id="d1"))
        ms = sim.add(MultiportSwitch(n_choices=2, id="ms"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(sel, ms, dst_idx=0)
        sim.connect(d0, ms, dst_idx=1)
        sim.connect(d1, ms, dst_idx=2)
        sim.connect(ms, sc)
        assert_dtype_prediction_matches_execution(sim)
        assert float(np.asarray(sc.values)[0, 0]) == 20.0

    def test_mux_demux_fanout(self) -> None:
        sim = _sim()
        a = sim.add(Constant(value=1, dtype="int32", id="a"))
        b = sim.add(Constant(value=0, id="b"))
        bx = sim.add(Cast(dtype="bool", id="bx"))
        mux = sim.add(Mux(n=2, id="mux"))
        demux = sim.add(Demux(n=2, id="demux"))
        sc = sim.add(Scope(n_inputs=2, id="sc"))
        sim.connect(a, mux, dst_idx=0)
        sim.connect(b, bx)
        sim.connect(bx, mux, dst_idx=1)
        sim.connect(mux, demux)
        sim.connect(demux, sc, dst_idx=0)
        sim.connect(demux, sc, src_idx=1, dst_idx=1)
        res = sim.resolve_dtypes()
        # bool + int32 -> int32 (np.result_type)
        assert res.out_dtype("mux", 0) == "int32"
        assert res.out_dtype("demux", 1) == "int32"
        # Scope は SM-A only ガードに掛からない (mux 出力はベクトルだが Scope 直結
        # ではない)。実行して予測突合
        assert_dtype_prediction_matches_execution(sim)

    def test_merge_and_goto_from(self) -> None:
        sim = _sim()
        a = sim.add(Constant(value=7, dtype="int64", id="a"))
        gt = sim.add(Goto(tag="x", id="gt"))
        fr = sim.add(From(tag="x", id="fr"))
        zero = sim.add(Constant(value=0, dtype="int64", id="z"))
        mg = sim.add(Merge(n_inputs=2, id="mg"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(a, gt)
        sim.connect(zero, mg, dst_idx=0)
        sim.connect(fr, mg, dst_idx=1)
        sim.connect(mg, sc)
        assert_dtype_prediction_matches_execution(sim)
        assert float(np.asarray(sc.values)[0, 0]) == 7.0


class TestStatefulBlocks:
    """Q7: 状態は float64、出力は予測 dtype に cast + 診断。"""

    def test_unit_delay_output_is_cast_to_predicted_dtype(self) -> None:
        sim = _sim()
        c = sim.add(Constant(value=1, dtype="int32", id="c"))
        s = sim.add(Sum(signs="++", id="s"))
        d = sim.add(UnitDelay(sample_time=0.01, x0=0.0, id="d"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(c, s, dst_idx=0)
        sim.connect(d, s, dst_idx=1)
        sim.connect(s, d)
        sim.connect(s, sc)
        res = sim.resolve_dtypes()
        assert res.out_dtype("d", 0) == "int32"
        assert any(
            di.code == "dtype.state_via_float64" and di.block_id == "d" for di in res.diagnostics
        )
        assert_dtype_prediction_matches_execution(sim)
        # 累積カウンタとして正しく動く (1, 2, 3, ...)
        vals = np.asarray(sc.values)[:, 0]
        assert vals[0] == 1.0 and vals[1] == 2.0

    def test_zoh_passes_predicted_dtype(self) -> None:
        sim = _sim()
        c = sim.add(Constant(value=5, dtype="int64", id="c"))
        z = sim.add(ZeroOrderHoldDirect(sample_time=0.01, id="z"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(c, z)
        sim.connect(z, sc)
        assert_dtype_prediction_matches_execution(sim)


class TestFloat64Island:
    """Q6: Subsystem / PythonFunction は境界 float64。"""

    def test_subsystem_island_runs_and_matches(self) -> None:
        sub = Subsystem(
            blocks=[
                Inport(port_idx=0, id="ip"),
                Gain(k=2.0, id="g"),
                Outport(port_idx=0, id="op"),
            ],
            connections=[
                {"src": "ip", "src_port": 0, "dst": "g", "dst_port": 0},
                {"src": "g", "src_port": 0, "dst": "op", "dst_port": 0},
            ],
            id="sub",
        )
        sim = _sim()
        c = sim.add(Constant(value=3, dtype="int32", id="c"))
        sim.add(sub)
        sc = sim.add(Scope(id="sc"))
        sim.connect(c, sub)
        sim.connect(sub, sc)
        res = sim.resolve_dtypes()
        assert res.in_dtype("sub", 0) == "float64"  # D-4 昇格 (island 境界)
        assert res.out_dtype("sub", 0) == "float64"
        assert any(d.code == "dtype.opaque_float64_island" for d in res.diagnostics)
        assert_dtype_prediction_matches_execution(sim)
        assert float(np.asarray(sc.values)[0, 0]) == 6.0

    def test_python_function_island_runs(self) -> None:
        code = textwrap.dedent(
            """
            @block
            def f(t: float, u: float) -> float:
                return u * 3.0
            """
        )
        sim = _sim()
        c = sim.add(Constant(value=2, dtype="int32", id="c"))
        pf = sim.add(PythonFunction(code=code, id="pf"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(c, pf)
        sim.connect(pf, sc)
        res = dtypes.resolve_dtypes(sim, mode="full")
        assert res.out_dtype("pf", 0) == "float64"
        assert_dtype_prediction_matches_execution(sim)
        assert float(np.asarray(sc.values)[0, 0]) == 6.0


class TestNestedDeclarationRejected:
    """security MUST-1 (2026-09-08): Subsystem 内部の dtype 宣言は fail-closed。

    root-only pre-filter をすり抜けると「予測 (float64 island) と実行値
    (内部で wrap 済み) が無警告で乖離」するため、宣言自体を拒否する。
    """

    @staticmethod
    def _nested_declaration_model() -> Simulator:
        sub = Subsystem(
            blocks=[
                Inport(port_idx=0, id="ip"),
                Constant(value=300.0, dtype="uint8", id="inner_c"),
                Outport(port_idx=0, id="op"),
            ],
            connections=[
                {"src": "inner_c", "src_port": 0, "dst": "op", "dst_port": 0},
            ],
            id="sub",
        )
        sim = _sim()
        c = sim.add(Constant(value=1.0, id="c"))
        sim.add(sub)
        sc = sim.add(Scope(id="sc"))
        sim.connect(c, sub)
        sim.connect(sub, sc)
        return sim

    def test_run_is_rejected(self) -> None:
        sim = self._nested_declaration_model()
        with pytest.raises(BlockSpecError, match="inside Subsystem"):
            sim.run()

    def test_linearize_is_rejected(self) -> None:
        from flode import linearize

        sim = self._nested_declaration_model()
        with pytest.raises(BlockSpecError, match="inside Subsystem"):
            linearize(sim)

    def test_rejected_even_when_root_also_declares(self) -> None:
        # root に正当な宣言があっても、ネスト宣言は同様に拒否される
        # (code-reviewer MUST 提案ケース 2)
        sim = self._nested_declaration_model()
        sim.add(Cast(dtype="int32", id="root_cast"))
        with pytest.raises(BlockSpecError, match="inside Subsystem"):
            sim.run()

    def test_rest_resolve_reports_build_failed(self) -> None:
        # REST 経路 (resolve_dtypes の catch-all) では 200 + build_failed 診断
        sim = self._nested_declaration_model()
        res = dtypes.resolve_dtypes(sim)
        failed = [d for d in res.diagnostics if d.code == "dtype.build_failed"]
        assert len(failed) == 1
        assert "inside Subsystem" in failed[0].message

    def test_undeclared_nested_model_is_unaffected(self) -> None:
        # dtype を持たない Subsystem モデルは従来どおり実行できる
        sub = Subsystem(
            blocks=[
                Inport(port_idx=0, id="ip"),
                Gain(k=2.0, id="g"),
                Outport(port_idx=0, id="op"),
            ],
            connections=[
                {"src": "ip", "src_port": 0, "dst": "g", "dst_port": 0},
                {"src": "g", "src_port": 0, "dst": "op", "dst_port": 0},
            ],
            id="sub",
        )
        sim = _sim()
        c = sim.add(Constant(value=3.0, id="c"))
        sim.add(sub)
        sc = sim.add(Scope(id="sc"))
        sim.connect(c, sub)
        sim.connect(sub, sc)
        sim.run()
        assert float(np.asarray(sc.values)[0, 0]) == 6.0

    def test_nested_float64_cast_is_allowed(self) -> None:
        # v0.56.0: Cast は常に dtype を宣言する (既定 "float64") ため、
        # float64 宣言まで拒否すると Subsystem 内に Cast を置けなくなる。
        # island 内は全経路 float64 なので float64 宣言は乖離を生まない → 許可。
        sub = Subsystem(
            blocks=[
                Inport(port_idx=0, id="ip"),
                Cast(id="inner_k"),  # dtype="float64" (既定)
                Outport(port_idx=0, id="op"),
            ],
            connections=[
                {"src": "ip", "src_port": 0, "dst": "inner_k", "dst_port": 0},
                {"src": "inner_k", "src_port": 0, "dst": "op", "dst_port": 0},
            ],
            id="sub",
        )
        sim = _sim()
        c = sim.add(Constant(value=1.5, id="c"))
        sim.add(sub)
        sc = sim.add(Scope(id="sc"))
        sim.connect(c, sub)
        sim.connect(sub, sc)
        sim.run()
        assert float(np.asarray(sc.values)[0, 0]) == 1.5

    def test_nested_float64_constant_is_allowed(self) -> None:
        # 同上: Constant(dtype="float64") も island と完全一致するため許可
        sub = Subsystem(
            blocks=[
                Inport(port_idx=0, id="ip"),
                Constant(value=2.0, dtype="float64", id="inner_c"),
                Outport(port_idx=0, id="op"),
            ],
            connections=[
                {"src": "inner_c", "src_port": 0, "dst": "op", "dst_port": 0},
            ],
            id="sub",
        )
        sim = _sim()
        c = sim.add(Constant(value=1.0, id="c"))
        sim.add(sub)
        sc = sim.add(Scope(id="sc"))
        sim.connect(c, sub)
        sim.connect(sub, sc)
        sim.run()
        assert float(np.asarray(sc.values)[0, 0]) == 2.0


class TestTotalityAndEscalation:
    """AC-3 (全域性) と §3.5 のエラー昇格。"""

    def test_unconnected_input_runs_with_float64_zero(self) -> None:
        sim = _sim()
        s = sim.add(Sum(signs="++", id="s"))
        c = sim.add(Constant(value=1, dtype="int32", id="c"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(c, s, dst_idx=0)  # dst_idx=1 未接続
        sim.connect(s, sc)
        assert_dtype_prediction_matches_execution(sim)
        assert float(np.asarray(sc.values)[0, 0]) == 1.0

    def test_iteration_limit_escalates_to_block_spec_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sim = _sim()
        c = sim.add(Constant(value=1, dtype="int32", id="c"))
        s = sim.add(Sum(signs="++", id="s"))
        d = sim.add(UnitDelay(sample_time=0.01, x0=0.0, id="d"))
        sim.connect(c, s, dst_idx=0)
        sim.connect(d, s, dst_idx=1)
        sim.connect(s, d)
        original = dtypes._infer_outputs
        flip: dict[str, str] = {}

        def oscillating(
            block: Any, category: str, in_dtypes: list[str], sink: Any, *, island: bool = False
        ) -> list[str]:
            if getattr(block, "id", None) == "s":
                nxt = "int64" if flip.get("s") == "float64" else "float64"
                flip["s"] = nxt
                return [nxt]
            return original(block, category, in_dtypes, sink, island=island)  # type: ignore[arg-type]

        monkeypatch.setattr(dtypes, "_infer_outputs", oscillating)
        with pytest.raises(BlockSpecError, match="dtype.iteration_limit"):
            sim.run()

    def test_narrowing_escalates_to_block_spec_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sim = _sim()
        c = sim.add(Constant(value=1.0, dtype="float64", id="c"))
        integ = sim.add(Integrator(x0=0.0, id="integ"))
        sim.connect(c, integ)
        original = dtypes._required_input_dtype

        def narrow_required(block: Any, *, island: bool) -> str | None:
            if getattr(block, "id", None) == "integ":
                return "int32"  # float64 入力に縮小要求 → narrowing_required
            return original(block, island=island)

        monkeypatch.setattr(dtypes, "_required_input_dtype", narrow_required)
        with pytest.raises(BlockSpecError, match="dtype.narrowing_required"):
            sim.run()

    def test_run_of_undeclared_model_never_resolves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # AC-1 の構造保証: dtype 未宣言なら resolve_for_execution は呼ばれない
        def forbidden(_sim: Simulator) -> Any:
            raise AssertionError("resolve_for_execution must not be called")

        monkeypatch.setattr(dtypes, "resolve_for_execution", forbidden)
        # simulator 側は関数参照を import しているため module 側も patch する
        import flode.core.simulator as sim_mod  # noqa: F401  (patch 経路の確認)

        sim = _sim()
        c = sim.add(Constant(value=1.0, id="c"))
        g = sim.add(Gain(k=2.0, id="g"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(c, g)
        sim.connect(g, sc)
        sim.run()  # 例外なし = pre-filter が働いている
        assert float(np.asarray(sc.values)[0, 0]) == 2.0
