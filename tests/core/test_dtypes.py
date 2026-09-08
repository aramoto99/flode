"""SPEC-0027 / ADR-0077: SM-D Stage 0 影の型伝播エンジン (`flode.core.dtypes`) のテスト。

語彙 / 昇格閉包 / 分類規則 / D-4 自動昇格 / 不動点反復 / unknown 伝播 /
突合キー / 診断 / 集計 / 網羅ガード / 性能 / static mode (PythonFunction 非実行)
をカバーする。挙動不変性 (AC-1〜AC-6) は `test_dtypes_no_behavior_change.py` が担当。
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from flode import Simulator
from flode.blocks.cast import Cast
from flode.blocks.continuous import Derivative, Integrator, TransferFunction
from flode.blocks.discrete import DiscreteIntegrator, UnitDelay
from flode.blocks.mathops import (
    Abs,
    CompareToConstant,
    CompareToZero,
    Gain,
    Sum,
)
from flode.blocks.pythonfunc import PythonFunction
from flode.blocks.rounding import Rounding
from flode.blocks.routing import Demux, From, Goto, Mux, Switch
from flode.blocks.sinks import Scope
from flode.blocks.sources import Constant
from flode.core import dtypes
from flode.core.block import Block
from flode.core.dtypes import (
    DTYPE_VOCABULARY,
    UNKNOWN,
    DTypeDiagnostic,
    DTypeResolution,
    promote,
    resolve_dtypes,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _sim() -> Simulator:
    return Simulator(t_end=0.1, dt=0.01)


def _codes(res: DTypeResolution) -> list[str]:
    return [d.code for d in res.diagnostics]


def _find(res: DTypeResolution, code: str) -> list[DTypeDiagnostic]:
    return [d for d in res.diagnostics if d.code == code]


class _UnclassifiedBlock(Block):
    """分類テーブルに無いクラス (dtype.rule_missing のテスト用)。"""

    _skip_dual_api_check = True

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id, n_inputs=1, n_outputs=1)

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.array([float(u[0])])


# ---------------------------------------------------------------------------
# 語彙 (D-1)
# ---------------------------------------------------------------------------


class TestVocabulary:
    def test_vocabulary_is_the_five_agreed_dtypes(self) -> None:
        assert DTYPE_VOCABULARY == ("bool", "uint8", "int32", "int64", "float64")

    def test_unknown_is_not_part_of_the_vocabulary(self) -> None:
        assert UNKNOWN == "unknown"
        assert UNKNOWN not in DTYPE_VOCABULARY

    def test_unknown_is_an_absorbing_free_bottom(self) -> None:
        for d in DTYPE_VOCABULARY:
            assert promote(UNKNOWN, d) == d
            assert promote(d, UNKNOWN) == d
        assert promote(UNKNOWN, UNKNOWN) == UNKNOWN

    def test_names_round_trip_through_np_dtype(self) -> None:
        for name in DTYPE_VOCABULARY:
            assert np.dtype(name).name == name


# ---------------------------------------------------------------------------
# 昇格の閉包性 (SPEC-0027 §1)
# ---------------------------------------------------------------------------


class TestPromotionClosure:
    def test_all_25_pairs_stay_inside_the_vocabulary(self) -> None:
        for a in DTYPE_VOCABULARY:
            for b in DTYPE_VOCABULARY:
                result = promote(a, b)
                assert result in DTYPE_VOCABULARY, f"{a} + {b} -> {result}"

    def test_uint64_is_deliberately_outside_the_vocabulary(self) -> None:
        # uint64 + int64 は NEP 50 で float64 に落ちる「驚き」ケース。
        # 語彙から外すことで Stage 0 では発生させない (SPEC-0027 §1)。
        assert "uint64" not in DTYPE_VOCABULARY


# ---------------------------------------------------------------------------
# 分類規則 (SPEC-0027 §3.5、Q1)
# ---------------------------------------------------------------------------


class TestClassificationRules:
    def test_bool_out_blocks_emit_bool(self) -> None:
        sim = _sim()
        c = sim.add(Constant(value=1.0, id="c"))
        cmp_c = sim.add(CompareToConstant(op=">", const=0.0, id="cmp_c"))
        cmp_z = sim.add(CompareToZero(id="cmp_z"))
        sim.connect(c, cmp_c)
        sim.connect(c, cmp_z)
        res = resolve_dtypes(sim)
        assert res.out_dtype("cmp_c", 0) == "bool"
        assert res.out_dtype("cmp_z", 0) == "bool"

    @pytest.mark.parametrize(
        ("output_type", "expected"),
        [("float", "float64"), ("int", "int64"), ("bool", "bool")],
    )
    def test_constant_output_type_maps_to_dtype(
        self, output_type: str, expected: str
    ) -> None:
        sim = _sim()
        sim.add(Constant(value=2.7, output_type=output_type, id="c"))
        res = resolve_dtypes(sim)
        assert res.out_dtype("c", 0) == expected

    @pytest.mark.parametrize(
        ("output_type", "expected"), [("int", "int64"), ("bool", "bool")]
    )
    def test_cast_maps_output_type(self, output_type: str, expected: str) -> None:
        sim = _sim()
        c = sim.add(Constant(value=1.5, id="c"))
        cast = sim.add(Cast(output_type=output_type, id="cast"))
        sim.connect(c, cast)
        res = resolve_dtypes(sim)
        assert res.out_dtype("cast", 0) == expected

    def test_cast_float_is_input_pass_through(self) -> None:
        # Cast("float") は恒等 (SPEC-0026) → 入力の dtype をそのまま通す
        sim = _sim()
        c = sim.add(Constant(value=1.0, output_type="int", id="c"))
        cast = sim.add(Cast(output_type="float", id="cast"))
        sim.connect(c, cast)
        res = resolve_dtypes(sim)
        assert res.out_dtype("cast", 0) == "int64"

    def test_cast_chain_int_then_bool(self) -> None:
        sim = _sim()
        c = sim.add(Constant(value=2.7, id="c"))
        c_int = sim.add(Cast(output_type="int", id="c_int"))
        c_bool = sim.add(Cast(output_type="bool", id="c_bool"))
        sim.connect(c, c_int)
        sim.connect(c_int, c_bool)
        res = resolve_dtypes(sim)
        assert res.out_dtype("c_int", 0) == "int64"
        assert res.out_dtype("c_bool", 0) == "bool"

    def test_rounding_is_int64(self) -> None:
        sim = _sim()
        c = sim.add(Constant(value=1.5, id="c"))
        r = sim.add(Rounding(id="r"))
        sim.connect(c, r)
        res = resolve_dtypes(sim)
        assert res.out_dtype("r", 0) == "int64"

    def test_float_out_blocks_emit_float64_regardless_of_input(self) -> None:
        sim = _sim()
        c = sim.add(Constant(value=1.0, output_type="int", id="c"))
        g = sim.add(Gain(k=2.0, id="g"))
        sim.connect(c, g)
        res = resolve_dtypes(sim)
        assert res.out_dtype("g", 0) == "float64"

    def test_promote_rule_takes_result_type_of_inputs(self) -> None:
        sim = _sim()
        ci = sim.add(Constant(value=1.0, output_type="int", id="ci"))
        cb = sim.add(Constant(value=1.0, output_type="bool", id="cb"))
        s = sim.add(Sum(signs="++", id="s"))
        sim.connect(ci, s, dst_idx=0)
        sim.connect(cb, s, dst_idx=1)
        res = resolve_dtypes(sim)
        # bool + int64 -> int64 (np.result_type)
        assert res.out_dtype("s", 0) == "int64"

    def test_abs_preserves_int_via_promote(self) -> None:
        sim = _sim()
        c = sim.add(Constant(value=-2.0, output_type="int", id="c"))
        a = sim.add(Abs(id="a"))
        sim.connect(c, a)
        res = resolve_dtypes(sim)
        assert res.out_dtype("a", 0) == "int64"

    def test_switch_control_port_does_not_contribute(self) -> None:
        sim = _sim()
        ci = sim.add(Constant(value=1.0, output_type="int", id="ci"))
        cb = sim.add(Constant(value=1.0, output_type="bool", id="cb"))
        ci2 = sim.add(Constant(value=2.0, output_type="int", id="ci2"))
        sw = sim.add(Switch(threshold=0.5, id="sw"))
        sim.connect(ci, sw, dst_idx=0)
        sim.connect(cb, sw, dst_idx=1)  # control (u[1]) — 出力 dtype に寄与しない
        sim.connect(ci2, sw, dst_idx=2)
        res = resolve_dtypes(sim)
        assert res.out_dtype("sw", 0) == "int64"

    def test_mux_promotes_and_demux_fans_out(self) -> None:
        sim = _sim()
        ci = sim.add(Constant(value=1.0, output_type="int", id="ci"))
        cb = sim.add(Constant(value=0.0, output_type="bool", id="cb"))
        mux = sim.add(Mux(n=2, id="mux"))
        demux = sim.add(Demux(n=2, id="demux"))
        sim.connect(ci, mux, dst_idx=0)
        sim.connect(cb, mux, dst_idx=1)
        sim.connect(mux, demux)
        res = resolve_dtypes(sim)
        assert res.out_dtype("mux", 0) == "int64"
        assert res.out_dtype("demux", 0) == "int64"
        assert res.out_dtype("demux", 1) == "int64"

    def test_sink_blocks_have_no_output_entries(self) -> None:
        sim = _sim()
        c = sim.add(Constant(value=1.0, id="c"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(c, sc)
        res = resolve_dtypes(sim)
        assert ("sc", "out", 0) not in res.ports
        assert res.in_dtype("sc", 0) == "float64"

    def test_goto_from_carries_dtype_through_the_tag(self) -> None:
        sim = _sim()
        c = sim.add(Constant(value=3.0, output_type="int", id="c"))
        gt = sim.add(Goto(tag="a", id="gt"))
        fr = sim.add(From(tag="a", id="fr"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(c, gt)
        sim.connect(fr, sc)
        res = resolve_dtypes(sim)
        assert res.out_dtype("fr", 0) == "int64"

    def test_python_function_is_opaque_unknown(self) -> None:
        code = textwrap.dedent(
            """
            @block
            def f(t: float, u: float) -> float:
                return u
            """
        )
        sim = _sim()
        c = sim.add(Constant(value=1.0, id="c"))
        pf = sim.add(PythonFunction(code=code, id="pf"))
        sim.connect(c, pf)
        res = resolve_dtypes(sim)
        assert res.out_dtype("pf", 0) == UNKNOWN
        assert "dtype.unresolved" in _codes(res)


# ---------------------------------------------------------------------------
# D-4: 連続系 / 離散 LTI の float64 要求と自動昇格
# ---------------------------------------------------------------------------


class TestContinuousWidening:
    @pytest.mark.parametrize("output_type", ["int", "bool"])
    def test_integrator_widens_int_and_bool_inputs(self, output_type: str) -> None:
        sim = _sim()
        c = sim.add(Constant(value=1.0, output_type=output_type, id="c"))
        integ = sim.add(Integrator(x0=0.0, id="integ"))
        sim.connect(c, integ)
        res = resolve_dtypes(sim)
        assert res.in_dtype("integ", 0) == "float64"
        assert res.out_dtype("integ", 0) == "float64"
        widening = _find(res, "dtype.implicit_widening")
        assert len(widening) == 1
        assert widening[0].block_id == "integ"
        assert widening[0].from_dtype == ("int64" if output_type == "int" else "bool")
        assert widening[0].to_dtype == "float64"

    def test_unit_level_widening_for_uint8_and_int32(self) -> None:
        # uint8 / int32 を出力する builtin は Stage 0 に無いため、
        # D-4 の適用関数を直接検証する (SPEC-0027 §3.5)。
        integ = Integrator(x0=0.0, id="integ")
        diags: list[DTypeDiagnostic] = []
        applied = dtypes._apply_input_requirement(
            integ, ["uint8", "int32"], diags.append, "float64"
        )
        assert applied == ["float64", "float64"]
        assert [d.from_dtype for d in diags] == ["uint8", "int32"]

    def test_discrete_lti_blocks_also_require_float64(self) -> None:
        sim = _sim()
        c = sim.add(Constant(value=1.0, output_type="int", id="c"))
        di = sim.add(DiscreteIntegrator(sample_time=0.01, id="di"))
        sim.connect(c, di)
        res = resolve_dtypes(sim)
        assert res.in_dtype("di", 0) == "float64"
        assert _find(res, "dtype.implicit_widening")[0].block_id == "di"

    def test_derivative_and_transfer_function_require_float64(self) -> None:
        sim = _sim()
        c = sim.add(Constant(value=1.0, output_type="bool", id="c"))
        d = sim.add(Derivative(id="d"))
        tf = sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0], id="tf"))
        sim.connect(c, d)
        sim.connect(c, tf)
        res = resolve_dtypes(sim)
        assert res.in_dtype("d", 0) == "float64"
        assert res.in_dtype("tf", 0) == "float64"

    def test_narrowing_path_is_defensive_and_reports_error(self) -> None:
        # 現語彙では縮小は発生しないため、要求 dtype を直接与えて防御経路を固定する
        integ = Integrator(x0=0.0, id="integ")
        diags: list[DTypeDiagnostic] = []
        applied = dtypes._apply_input_requirement(
            integ, ["float64"], diags.append, "int32"
        )
        assert applied == ["float64"]  # 実際の縮小は行わない
        assert [d.code for d in diags] == ["dtype.narrowing_required"]
        assert diags[0].severity == "error"


# ---------------------------------------------------------------------------
# 不動点反復 (SPEC-0027 §3.3)
# ---------------------------------------------------------------------------


class TestFixedPoint:
    def _feedback_model(self) -> Simulator:
        sim = _sim()
        c = sim.add(Constant(value=1.0, output_type="int", id="c"))
        s = sim.add(Sum(signs="++", id="s"))
        d = sim.add(UnitDelay(sample_time=0.01, x0=0.0, id="d"))
        sim.connect(c, s, dst_idx=0)
        sim.connect(d, s, dst_idx=1)
        sim.connect(s, d)
        return sim

    def test_unit_delay_feedback_converges_to_int64(self) -> None:
        res = resolve_dtypes(self._feedback_model())
        assert res.out_dtype("s", 0) == "int64"
        assert res.out_dtype("d", 0) == "int64"
        assert "dtype.iteration_limit" not in _codes(res)

    def test_second_resolution_is_identical(self) -> None:
        sim = self._feedback_model()
        first = resolve_dtypes(sim)
        second = resolve_dtypes(sim)
        assert dict(first.ports) == dict(second.ports)

    def test_monotone_growth_bool_into_int_loop(self) -> None:
        # bool 定数 + int 定数の合流ループ: unknown → bool → int64 と広がる方向のみ
        sim = _sim()
        cb = sim.add(Constant(value=1.0, output_type="bool", id="cb"))
        ci = sim.add(Constant(value=1.0, output_type="int", id="ci"))
        s = sim.add(Sum(signs="+++", id="s"))
        d = sim.add(UnitDelay(sample_time=0.01, x0=0.0, id="d"))
        sim.connect(cb, s, dst_idx=0)
        sim.connect(ci, s, dst_idx=1)
        sim.connect(d, s, dst_idx=2)
        sim.connect(s, d)
        res = resolve_dtypes(sim)
        assert res.out_dtype("s", 0) == "int64"

    def test_iteration_limit_diagnostic_on_forced_oscillation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sim = self._feedback_model()
        original = dtypes._infer_outputs
        flip: dict[str, str] = {}

        def oscillating(
            block: Block,
            category: str,
            in_dtypes: list[str],
            sink: Any,
            *,
            island: bool = False,
        ) -> list[str]:
            if block.id == "s":
                nxt = "int64" if flip.get("s") == "float64" else "float64"
                flip["s"] = nxt
                return [nxt]
            return original(  # type: ignore[arg-type]
                block, category, in_dtypes, sink, island=island
            )

        monkeypatch.setattr(dtypes, "_infer_outputs", oscillating)
        res = resolve_dtypes(sim)
        assert "dtype.iteration_limit" in _codes(res)
        # 打ち切り後もその時点の結果を返す (例外は投げない)
        assert res.summary.total_ports > 0

    def test_empty_model_resolves_to_empty_result(self) -> None:
        res = resolve_dtypes(_sim())
        assert dict(res.ports) == {}
        assert res.summary.total_ports == 0
        assert res.diagnostics == ()


# ---------------------------------------------------------------------------
# unknown の伝播 (Q4)
# ---------------------------------------------------------------------------


class TestUnknownPropagation:
    def test_subsystem_outputs_are_unknown_with_diagnostic(self) -> None:
        from flode.subsystems import Inport, Outport, Subsystem

        inner_in = Inport(port_idx=0, id="in0")
        inner_out = Outport(port_idx=0, id="out0")
        sub = Subsystem(
            blocks=[inner_in, inner_out],
            connections=[
                {"src": "in0", "src_port": 0, "dst": "out0", "dst_port": 0}
            ],
            id="sub",
        )
        sim = _sim()
        c = sim.add(Constant(value=1.0, id="c"))
        sim.add(sub)
        sc = sim.add(Scope(id="sc"))
        sim.connect(c, sub)
        sim.connect(sub, sc)
        res = resolve_dtypes(sim)
        # Stage 1 (SPEC-0028 Q6): full mode では Subsystem は float64 island
        assert res.out_dtype("sub", 0) == "float64"
        assert any(
            d.code == "dtype.opaque_float64_island" and d.block_id == "sub"
            for d in res.diagnostics
        )

    def test_unconnected_input_materializes_to_float64(self) -> None:
        # Stage 1 (SPEC-0028 Q5): 未接続入力は unresolved 警告を残しつつ
        # float64 へ materialize される (全域性 AC-3)
        sim = _sim()
        sim.add(Sum(signs="++", id="s"))
        res = resolve_dtypes(sim)
        assert res.in_dtype("s", 0) == "float64"
        assert res.out_dtype("s", 0) == "float64"
        unresolved = _find(res, "dtype.unresolved")
        assert {(d.direction, d.port_index) for d in unresolved} == {("in", 0), ("in", 1)}
        assert _find(res, "dtype.defaulted_to_float64")  # out の materialize 記録

    def test_unknown_is_absorbed_by_a_concrete_sibling_input(self) -> None:
        sim = _sim()
        c = sim.add(Constant(value=1.0, output_type="int", id="c"))
        s = sim.add(Sum(signs="++", id="s"))
        sim.connect(c, s, dst_idx=0)  # dst_idx=1 は未接続 (unknown)
        res = resolve_dtypes(sim)
        assert res.out_dtype("s", 0) == "int64"

    def test_summary_has_no_unresolved_after_materialize(self) -> None:
        # Stage 1 (Q5): full mode では materialize により unresolved は常に 0
        sim = _sim()
        sim.add(Sum(signs="++", id="s"))
        res = resolve_dtypes(sim)
        assert res.summary.unresolved == 0
        assert res.summary.total_ports == 3
        assert dict(res.summary.by_dtype) == {"float64": 3}


# ---------------------------------------------------------------------------
# 突合キー (ADR-0077 §データ整合性 2)
# ---------------------------------------------------------------------------


class TestKeying:
    @staticmethod
    def _model(order_reversed: bool) -> Simulator:
        sim = _sim()
        blocks: list[Block] = [
            Constant(value=1.0, output_type="int", id="c"),
            Gain(k=2.0, id="g"),
            Scope(id="sc"),
        ]
        if order_reversed:
            blocks = list(reversed(blocks))
        for b in blocks:
            sim.add(b)
        sim.connect(sim.get_block("c"), sim.get_block("g"))
        sim.connect(sim.get_block("g"), sim.get_block("sc"))
        return sim

    def test_result_is_identical_regardless_of_add_order(self) -> None:
        res_a = resolve_dtypes(self._model(order_reversed=False))
        res_b = resolve_dtypes(self._model(order_reversed=True))
        assert dict(res_a.ports) == dict(res_b.ports)

    def test_keys_are_block_id_direction_port_index(self) -> None:
        res = resolve_dtypes(self._model(order_reversed=False))
        assert ("c", "out", 0) in res.ports
        assert ("g", "in", 0) in res.ports
        assert ("sc", "in", 0) in res.ports

    def test_keys_are_unique_and_cover_all_ports(self) -> None:
        res = resolve_dtypes(self._model(order_reversed=False))
        # c: out1 / g: in1+out1 / sc: in1 = 4 ポート
        assert res.summary.total_ports == 4
        assert len(res.ports) == 4


# ---------------------------------------------------------------------------
# 診断 (SPEC-0027 §3.6)
# ---------------------------------------------------------------------------


class TestDiagnostics:
    def test_non_float_signal_is_reported_per_output_port(self) -> None:
        sim = _sim()
        sim.add(Constant(value=1.0, output_type="int", id="c"))
        res = resolve_dtypes(sim)
        diags = _find(res, "dtype.non_float_signal")
        assert len(diags) == 1
        assert diags[0].block_id == "c"
        assert diags[0].to_dtype == "int64"
        assert diags[0].severity == "info"

    def test_all_float_model_has_no_non_float_diagnostics(self) -> None:
        sim = _sim()
        c = sim.add(Constant(value=1.0, id="c"))
        g = sim.add(Gain(k=2.0, id="g"))
        sim.connect(c, g)
        res = resolve_dtypes(sim)
        assert "dtype.non_float_signal" not in _codes(res)
        assert "dtype.implicit_widening" not in _codes(res)

    def test_rule_missing_falls_back_to_promote(self) -> None:
        sim = _sim()
        c = sim.add(Constant(value=1.0, output_type="int", id="c"))
        w = sim.add(_UnclassifiedBlock(id="w"))
        sim.connect(c, w)
        res = resolve_dtypes(sim)
        assert res.out_dtype("w", 0) == "int64"  # フォールバック promote
        missing = _find(res, "dtype.rule_missing")
        assert len(missing) == 1
        assert missing[0].block_id == "w"
        assert missing[0].severity == "info"

    def test_algebraic_loop_becomes_build_failed(self) -> None:
        sim = _sim()
        g1 = sim.add(Gain(k=1.0, id="g1"))
        g2 = sim.add(Gain(k=1.0, id="g2"))
        sim.connect(g1, g2)
        sim.connect(g2, g1)
        res = resolve_dtypes(sim)
        failed = _find(res, "dtype.build_failed")
        assert len(failed) == 1
        assert failed[0].severity == "error"
        assert dict(res.ports) == {}
        assert res.summary.total_ports == 0

    def test_internal_error_is_converted_not_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(_sim: Simulator, **_kw: Any) -> DTypeResolution:
            raise RuntimeError("boom")

        monkeypatch.setattr(dtypes, "_resolve_impl", boom)
        res = resolve_dtypes(_sim())
        err = _find(res, "dtype.internal_error")
        assert len(err) == 1
        assert "RuntimeError" in err[0].message

    def test_severity_table_is_complete_for_all_codes(self) -> None:
        expected = {
            "dtype.implicit_widening": "info",
            "dtype.non_float_signal": "info",
            "dtype.unresolved": "warning",
            "dtype.rule_missing": "info",
            "dtype.narrowing_required": "error",
            "dtype.out_of_vocabulary": "warning",
            "dtype.iteration_limit": "warning",
            "dtype.build_failed": "error",
            "dtype.internal_error": "error",
            "dtype.static_fallback": "info",
            # Stage 1 (SPEC-0028)
            "dtype.opaque_float64_island": "info",
            "dtype.defaulted_to_float64": "info",
            "dtype.state_via_float64": "info",
        }
        assert dict(dtypes._SEVERITY_BY_CODE) == expected


# ---------------------------------------------------------------------------
# 集計 (summary)
# ---------------------------------------------------------------------------


class TestSummary:
    def test_by_dtype_counts_all_ports_excluding_unknown(self) -> None:
        sim = _sim()
        c = sim.add(Constant(value=1.0, output_type="int", id="c"))
        g = sim.add(Gain(k=2.0, id="g"))
        sim.connect(c, g)
        res = resolve_dtypes(sim)
        # c.out=int64 / g.in=int64 / g.out=float64
        assert dict(res.summary.by_dtype) == {"int64": 2, "float64": 1}
        assert res.summary.non_float_ports == 2
        assert res.summary.unresolved == 0

    def test_payload_shape_matches_spec(self) -> None:
        sim = _sim()
        sim.add(Constant(value=1.0, output_type="bool", id="c"))
        payload = resolve_dtypes(sim).to_payload()
        assert payload["schema_version"] == "dtypes.v1"
        assert payload["ports"] == [
            {"block_id": "c", "direction": "out", "port_index": 0, "dtype": "bool"}
        ]
        assert payload["summary"]["total_ports"] == 1
        assert payload["summary"]["by_dtype"] == {"bool": 1}
        assert payload["summary"]["non_float_ports"] == 1
        assert isinstance(payload["diagnostics"], list)

    def test_ports_payload_is_deterministically_sorted(self) -> None:
        sim = _sim()
        c = sim.add(Constant(value=1.0, id="c"))
        g = sim.add(Gain(k=2.0, id="g"))
        a = sim.add(Abs(id="a"))
        sim.connect(c, g)
        sim.connect(g, a)
        payload = resolve_dtypes(sim).to_payload()
        keys = [(p["block_id"], p["direction"], p["port_index"]) for p in payload["ports"]]
        assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# 網羅ガード (実装計画 §3.1 のトレードオフに対する CI ガード)
# ---------------------------------------------------------------------------


class TestCoverageGuard:
    def test_all_builtin_block_classes_resolve_without_rule_missing(self) -> None:
        from flode.server.registry import _walk_block_classes

        classification = dtypes._CLASSIFICATION
        unmatched: list[str] = []
        for cls in _walk_block_classes():
            names = [c.__name__ for c in cls.__mro__]
            if not any(n in classification for n in names):
                unmatched.append(cls.__name__)
        assert unmatched == [], (
            "分類テーブルに無い builtin ブロックがある (dtypes.py の "
            f"_CLASSIFICATION に追加すること): {unmatched}"
        )

    def test_builtin_class_names_are_unique(self) -> None:
        # クラス名 key の前提不変条件: builtin 内で __name__ が重複しない
        from flode.server.registry import _walk_block_classes

        names = [cls.__name__ for cls in _walk_block_classes()]
        assert len(names) == len(set(names))

    def test_opaque_list_is_exactly_subsystem_and_python_function(self) -> None:
        opaque = sorted(
            name
            for name, cat in dtypes._CLASSIFICATION.items()
            if cat == "opaque"
        )
        assert opaque == ["PythonFunction", "Subsystem"]


# ---------------------------------------------------------------------------
# static mode (実装計画「矛盾 1」: PythonFunction 非実行の構造保証)
# ---------------------------------------------------------------------------


class TestStaticMode:
    @staticmethod
    def _pf_code(marker: Path) -> str:
        # module レベルの副作用 (marker ファイル書き込み) を sentinel にする。
        # exec されたら marker が生成される = テスト失敗。
        return textwrap.dedent(
            f"""
            open({str(marker)!r}, "w").write("executed")

            @block
            def f(t: float, u: float) -> float:
                return u
            """
        )

    def test_user_code_is_never_executed(self, tmp_path: Path) -> None:
        marker = tmp_path / "executed.txt"
        sim = _sim()
        c = sim.add(Constant(value=1.0, id="c"))
        pf = sim.add(PythonFunction(code=self._pf_code(marker), id="pf"))
        sim.connect(c, pf)
        res = resolve_dtypes(sim)
        assert not marker.exists(), "static mode で PythonFunction が exec された"
        assert res.summary.total_ports > 0

    def test_static_fallback_diagnostic_and_from_degrades_to_unknown(
        self, tmp_path: Path
    ) -> None:
        marker = tmp_path / "executed.txt"
        sim = _sim()
        c = sim.add(Constant(value=1.0, output_type="int", id="c"))
        gt = sim.add(Goto(tag="a", id="gt"))
        fr = sim.add(From(tag="a", id="fr"))
        sc = sim.add(Scope(id="sc"))
        sim.add(PythonFunction(code=self._pf_code(marker), id="pf"))
        sim.connect(c, gt)
        sim.connect(fr, sc)
        res = resolve_dtypes(sim)
        assert not marker.exists()
        assert "dtype.static_fallback" in _codes(res)
        # Goto/From は build されないため tag 対応が解決できず unknown に縮退
        assert res.out_dtype("fr", 0) == UNKNOWN

    def test_exec_block_source_is_never_called(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # AC-7 (SPEC-0027): exec 到達の有無をスパイで直接検証する
        # (marker 方式より強い構造保証。呼ばれたら calls に記録される)。
        import flode.blocks.pythonfunc as pf_mod

        calls: list[object] = []
        monkeypatch.setattr(
            pf_mod,
            "exec_block_source",
            lambda *a, **k: calls.append((a, k)),
        )
        marker = tmp_path / "executed.txt"
        sim = _sim()
        c = sim.add(Constant(value=1.0, id="c"))
        pf = sim.add(PythonFunction(code=self._pf_code(marker), id="pf"))
        sim.connect(c, pf)
        res = resolve_dtypes(sim)
        assert calls == [], "resolve_dtypes が exec_block_source に到達した"
        assert "dtype.internal_error" not in _codes(res)
        assert res.summary.total_ports > 0

    def test_other_blocks_still_resolve_in_static_mode(self, tmp_path: Path) -> None:
        marker = tmp_path / "executed.txt"
        sim = _sim()
        c = sim.add(Constant(value=2.7, output_type="int", id="c"))
        cast = sim.add(Cast(output_type="bool", id="cast"))
        sim.add(PythonFunction(code=self._pf_code(marker), id="pf"))
        sim.connect(c, cast)
        res = resolve_dtypes(sim)
        assert not marker.exists()
        assert res.out_dtype("c", 0) == "int64"
        assert res.out_dtype("cast", 0) == "bool"

    def _nested_subsystem(self, marker: Path) -> Any:
        from flode.subsystems import Inport, Outport, Subsystem

        return Subsystem(
            blocks=[
                Inport(port_idx=0, id="ip"),
                PythonFunction(code=self._pf_code(marker), id="pf"),
                Outport(port_idx=0, id="op"),
            ],
            connections=[
                {"src": "ip", "src_port": 0, "dst": "pf", "dst_port": 0},
                {"src": "pf", "src_port": 0, "dst": "op", "dst_port": 0},
            ],
            id="sub",
        )

    def test_user_code_inside_nested_subsystem_is_never_executed(
        self, tmp_path: Path
    ) -> None:
        # MUST-1 (security-reviewer): _contains_python_function の再帰
        # (_inner_blocks duck-typing) を固定する。これが壊れると full mode に
        # 落ちて Subsystem._build() 経由で exec に到達する (唯一の門番)。
        marker = tmp_path / "executed.txt"
        sim = _sim()
        c = sim.add(Constant(value=1.0, id="c"))
        sub = sim.add(self._nested_subsystem(marker))
        sim.connect(c, sub)
        res = resolve_dtypes(sim)
        assert not marker.exists(), "ネスト Subsystem 内の PythonFunction が exec された"
        assert "dtype.static_fallback" in _codes(res)
        assert res.out_dtype("sub", 0) == UNKNOWN

    def test_nested_exec_block_source_is_never_called(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # ネスト構成でも exec 到達ゼロをスパイで構造的に固定する
        import flode.blocks.pythonfunc as pf_mod

        calls: list[object] = []
        monkeypatch.setattr(
            pf_mod, "exec_block_source", lambda *a, **k: calls.append((a, k))
        )
        marker = tmp_path / "executed.txt"
        sim = _sim()
        sim.add(self._nested_subsystem(marker))
        res = resolve_dtypes(sim)
        assert calls == []
        assert "dtype.internal_error" not in _codes(res)

    def test_detection_survives_json_roundtrip(self, tmp_path: Path) -> None:
        # 検出の前提「Subsystem の JSON 復元は _inner_blocks を eager 構築する」を
        # 不変条件としてテスト化する。遅延化されるとここが落ち、fail-open
        # (検出漏れ → full mode → exec) をリリース前に検知できる。
        marker = tmp_path / "executed.txt"
        sim = _sim()
        sim.add(self._nested_subsystem(marker))
        path = tmp_path / "m.flw.json"
        # 既知の別バグ (v0.53.7 以前から): Simulator.save() はネスト
        # PythonFunction を exec する (Subsystem serialize が _build を呼ぶ)。
        # 本テストの対象は load 側なので、save の副作用 marker は除去する。
        sim.save(path)
        if marker.exists():
            marker.unlink()
        loaded = Simulator.load(path)
        # load / _from_dict は exec しない (= endpoint の入口が安全な根拠)
        assert not marker.exists()
        assert dtypes._contains_python_function(loaded.blocks) is True


# ---------------------------------------------------------------------------
# 性能 (SPEC-0027 §非機能要件)
# ---------------------------------------------------------------------------


class TestPerformance:
    def test_thousand_block_chain_resolves_quickly(self) -> None:
        sim = Simulator(t_end=0.1, dt=0.01)
        prev: Block = sim.add(Constant(value=1.0, id="c0"))
        for i in range(999):
            g = sim.add(Gain(k=1.0, id=f"g{i}"))
            sim.connect(prev, g)
            prev = g
        start = time.perf_counter()
        res = resolve_dtypes(sim)
        elapsed = time.perf_counter() - start
        assert res.summary.total_ports == 1 + 999 * 2
        # SPEC 目標は 100ms。CI のばらつきを見込んで上限は 5 倍で固定する
        # (test_linearize_basic.py の緩い上限アサーション流儀)。
        assert elapsed < 0.5, f"resolve_dtypes took {elapsed:.3f}s for 1000 blocks"

    def test_static_mode_worst_case_resolves_quickly(self) -> None:
        # SHOULD-2 (security-reviewer): 逆順登録 + promote 連鎖 + PythonFunction
        # (= static mode)。擬似トポロジ順 (_static_order) 導入前は O(V²) で
        # 1000 ブロック ≈ 1.6s かかっていた最悪ケースを固定する。
        code = textwrap.dedent(
            """
            @block
            def f(t: float, u: float) -> float:
                return u
            """
        )
        sim = Simulator(t_end=0.1, dt=0.01)
        chain: list[Block] = [Constant(value=1.0, output_type="int", id="c0")]
        for i in range(998):
            chain.append(Sum(signs="+", id=f"s{i}"))
        for b in reversed(chain):
            sim.add(b)
        sim.add(PythonFunction(code=code, id="pf"))
        for up, down in zip(chain, chain[1:], strict=False):
            sim.connect(up, down)
        start = time.perf_counter()
        res = resolve_dtypes(sim)
        elapsed = time.perf_counter() - start
        assert res.out_dtype("s997", 0) == "int64"  # 連鎖の末端まで伝播
        assert elapsed < 0.5, f"static mode took {elapsed:.3f}s for 1000 blocks"
