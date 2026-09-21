"""ADR-0079 Stage 1: 信号面解決器 (`flode.core.signals`) の shape 側テスト。

受け入れ基準 (ADR-0079 §(10)):

- AC-3  全域性: full mode では未確定 shape が残らない
- AC-5  合流規則 (D-4) の許可 / 拒否パターンを具体値でハードコード
- AC-6  opaque island (Subsystem / PythonFunction / Fcn / @block) が fail-closed
- AC-10 全 builtin Block クラスが shape 規則テーブルに載る (registry 走査)

加えて制御ポート `()` 固定、集約例外 `SignalShapeError` の全件性、
`flode.core.dtypes` shim の互換 import、REST payload の `shape` を固定する。
dtype 側は `test_dtypes.py` が担当 (module 改名のみ追随)。
"""

from __future__ import annotations

import textwrap
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from flode import Simulator, block
from flode.blocks import (
    Constant,
    Demux,
    Fcn,
    Gain,
    Integrator,
    Merge,
    MultiportSwitch,
    Mux,
    Scope,
    Sum,
    Switch,
    TransferFunction,
    XYGraph,
)
from flode.blocks.pythonfunc import PythonFunction
from flode.core import signals
from flode.core.block import Block
from flode.core.signals import (
    SCOPE_LARGE_VECTOR_COLUMNS,
    SignalResolution,
    has_shape_source,
    merge_shapes,
    resolve_for_execution,
    resolve_signals,
)
from flode.exceptions import BlockSpecError, SignalShapeError
from flode.subsystems import Inport, Outport, Subsystem


def _sim() -> Simulator:
    return Simulator(t_end=0.05, dt=0.01)


def _codes(res: SignalResolution) -> list[str]:
    return [d.code for d in res.diagnostics]


def _mux3(sim: Simulator, prefix: str = "m") -> Mux:
    """3 つの Constant を Mux(3) に束ねて返す ((3,) の起点)。"""
    m = sim.add(Mux(n=3, id=prefix))
    for i in range(3):
        c = sim.add(Constant(value=float(i + 1), id=f"{prefix}_c{i}"))
        sim.connect(c, m, dst_idx=i)
    return m


class _VectorSrc(Block):
    """(3,) を出力する宣言ブロック (テスト用)。"""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id, n_inputs=0, n_outputs=1, port_shapes_out=[(3,)])

    def output_v(self, t, x, u):  # type: ignore[no-untyped-def]
        return (np.array([1.0, 2.0, 3.0]),)


class _MatrixSrc(Block):
    """(1, 3) を出力する宣言ブロック (テスト用、broadcast 拒否の相手)。"""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id, n_inputs=0, n_outputs=1, port_shapes_out=[(1, 3)])

    def output_v(self, t, x, u):  # type: ignore[no-untyped-def]
        return (np.ones((1, 3)),)


# ---------------------------------------------------------------------------
# AC-5: 合流規則 (D-4)
# ---------------------------------------------------------------------------


class TestMergeShapes:
    @pytest.mark.parametrize(
        ("a", "b", "expected"),
        [
            ((), (), ()),
            ((3,), (3,), (3,)),
            ((), (3,), (3,)),
            ((3,), (), (3,)),
            ((2, 2), (2, 2), (2, 2)),
            ((), (2, 2), (2, 2)),
        ],
    )
    def test_allowed(
        self, a: tuple[int, ...], b: tuple[int, ...], expected: tuple[int, ...]
    ) -> None:
        assert merge_shapes(a, b) == expected

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ((3,), (1, 3)),  # numpy なら broadcast 可能だが flode は拒否
            ((3,), (4,)),
            ((2, 3), (3,)),
            ((1,), (3,)),  # (1,) はスカラ扱いしない
            ((3, 1), (3, 3)),
        ],
    )
    def test_rejected(self, a: tuple[int, ...], b: tuple[int, ...]) -> None:
        assert merge_shapes(a, b) is None

    def test_matmul_shape_rules(self) -> None:
        assert signals._matmul_shape((2, 3), (3,)) == (2,)
        assert signals._matmul_shape((3,), (3,)) == ()
        assert signals._matmul_shape((3,), (3, 2)) == (2,)
        assert signals._matmul_shape((2, 3), (3, 4)) == (2, 4)
        assert signals._matmul_shape((2, 3), (4,)) is None
        assert signals._matmul_shape((), (3,)) is None
        assert signals._matmul_shape((2, 3, 4), (4,)) is None


# ---------------------------------------------------------------------------
# 伝播 (要素ごと / 選択 / 透過 / 宣言) と AC-3 (全域性)
# ---------------------------------------------------------------------------


class TestPropagation:
    def test_elementwise_chain_propagates_vector(self) -> None:
        sim = _sim()
        m = _mux3(sim)
        g = sim.add(Gain(k=2.0, id="g"))
        s = sim.add(Sum(signs="+-", id="s"))
        c = sim.add(Constant(value=1.0, id="c"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(m, g)
        sim.connect(g, s, dst_idx=0)
        sim.connect(c, s, dst_idx=1)  # スカラ拡張
        sim.connect(s, sc)
        res = resolve_signals(sim)
        assert res.out_shape("m", 0) == (3,)
        assert res.in_shape("g", 0) == (3,)
        assert res.out_shape("g", 0) == (3,)
        assert res.in_shape("s", 1) == ()
        assert res.out_shape("s", 0) == (3,)
        assert res.in_shape("sc", 0) == (3,)
        assert res.summary.vector_ports == 6
        assert res.summary.max_rank == 1
        # AC-3: 全ポート確定
        assert all(s is not None for s in res.shapes.values())
        assert "shape.mismatch" not in _codes(res)

    def test_all_scalar_model_resolves_to_scalars_without_diagnostics(self) -> None:
        sim = _sim()
        c = sim.add(Constant(value=1.0, id="c"))
        g = sim.add(Gain(k=2.0, id="g"))
        sc = sim.add(Scope(id="sc"))
        sim.connect(c, g)
        sim.connect(g, sc)
        res = resolve_signals(sim)
        assert set(res.shapes.values()) == {()}
        assert res.summary.vector_ports == 0
        assert not [c for c in _codes(res) if c.startswith("shape.")]

    def test_demux_splits_vector(self) -> None:
        sim = _sim()
        m = _mux3(sim)
        d = sim.add(Demux(n=3, id="d"))
        sim.connect(m, d)
        res = resolve_signals(sim)
        assert res.in_shape("d", 0) == (3,)
        assert all(res.out_shape("d", j) == () for j in range(3))

    def test_goto_from_passthrough_via_plan_only(self) -> None:
        from flode.blocks import From, Goto

        sim = _sim()
        m = _mux3(sim)
        gt = sim.add(Goto(tag="bus", id="gt"))
        fr = sim.add(From(tag="bus", id="fr"))
        sim.connect(m, gt)
        res = resolve_signals(sim)
        assert res.in_shape("gt", 0) == (3,)
        assert res.out_shape("fr", 0) == (3,)
        # D-2: 宣言には書き戻さない
        assert gt.port_shapes_in == ((),)
        assert fr.port_shapes_out == ((),)

    def test_unconnected_elementwise_output_defaults_to_scalar(self) -> None:
        sim = _sim()
        sim.add(_VectorSrc(id="v"))  # 起点だけあって Sum は未接続
        sim.add(Sum(signs="++", id="s"))
        res = resolve_signals(sim)
        assert res.out_shape("s", 0) == ()
        assert "shape.defaulted_to_scalar" in _codes(res)
        assert all(s is not None for s in res.shapes.values())

    def test_switch_passes_vector_data_ports(self) -> None:
        sim = _sim()
        m = _mux3(sim, "a")
        m2 = _mux3(sim, "b")
        ctl = sim.add(Constant(value=1.0, id="ctl"))
        sw = sim.add(Switch(id="sw"))
        sim.connect(m, sw, dst_idx=0)
        sim.connect(ctl, sw, dst_idx=1)
        sim.connect(m2, sw, dst_idx=2)
        res = resolve_signals(sim)
        assert res.out_shape("sw", 0) == (3,)
        assert res.in_shape("sw", 1) == ()

    def test_select_with_one_unconnected_data_port_uses_uniform_shape(self) -> None:
        sim = _sim()
        m = _mux3(sim)
        ctl = sim.add(Constant(value=0.0, id="ctl"))
        sw = sim.add(Switch(id="sw"))
        sim.connect(m, sw, dst_idx=0)
        sim.connect(ctl, sw, dst_idx=1)  # in[2] 未接続
        res = resolve_signals(sim)
        assert res.in_shape("sw", 2) == (3,)  # ゼロ埋めも (3,) で行われる


# ---------------------------------------------------------------------------
# 拒否 (error 級) と集約例外
# ---------------------------------------------------------------------------


class TestRejections:
    def test_broadcast_rejected(self) -> None:
        sim = _sim()
        v = sim.add(_VectorSrc(id="v"))
        mtx = sim.add(_MatrixSrc(id="mtx"))
        s = sim.add(Sum(signs="++", id="s"))
        sim.connect(v, s, dst_idx=0)
        sim.connect(mtx, s, dst_idx=1)
        res = resolve_signals(sim)
        rejected = [d for d in res.diagnostics if d.code == "shape.broadcast_rejected"]
        assert len(rejected) == 1
        assert rejected[0].block_id == "s"
        assert rejected[0].expected_shape == (3,)
        assert rejected[0].actual_shape == (1, 3)
        with pytest.raises(SignalShapeError, match="shape.broadcast_rejected"):
            resolve_for_execution(sim)

    def test_control_port_not_scalar(self) -> None:
        sim = _sim()
        m = _mux3(sim)
        a = sim.add(Constant(value=1.0, id="a"))
        b = sim.add(Constant(value=2.0, id="b"))
        sw = sim.add(Switch(id="sw"))
        sim.connect(a, sw, dst_idx=0)
        sim.connect(m, sw, dst_idx=1)  # 制御ポートにベクトル
        sim.connect(b, sw, dst_idx=2)
        with pytest.raises(SignalShapeError, match="shape.control_port_not_scalar") as ei:
            resolve_for_execution(sim)
        assert ei.value.block_id == "sw"
        assert ei.value.port == "in[1]"
        assert ei.value.expected_shape == ()
        assert ei.value.actual_shape == (3,)

    def test_multiport_switch_selector_not_scalar(self) -> None:
        sim = _sim()
        m = _mux3(sim)
        a = sim.add(Constant(value=1.0, id="a"))
        b = sim.add(Constant(value=2.0, id="b"))
        ms = sim.add(MultiportSwitch(n_choices=2, id="ms"))
        sim.connect(m, ms, dst_idx=0)
        sim.connect(a, ms, dst_idx=1)
        sim.connect(b, ms, dst_idx=2)
        with pytest.raises(SignalShapeError, match="shape.control_port_not_scalar"):
            resolve_for_execution(sim)

    def test_select_data_ports_must_share_shape(self) -> None:
        sim = _sim()
        m = _mux3(sim)
        a = sim.add(Constant(value=1.0, id="a"))
        mg = sim.add(Merge(n_inputs=2, id="mg"))
        sim.connect(m, mg, dst_idx=0)
        sim.connect(a, mg, dst_idx=1)  # () と (3,) の混在 (select はスカラ拡張しない)
        with pytest.raises(SignalShapeError, match="shape.mismatch"):
            resolve_for_execution(sim)

    def test_scalar_only_state_block_rejects_vector(self) -> None:
        sim = _sim()
        m = _mux3(sim)
        integ = sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0], id="integ"))
        sim.connect(m, integ)
        with pytest.raises(SignalShapeError, match="Demux") as ei:
            resolve_for_execution(sim)
        assert ei.value.diagnostics[0].code == "shape.mismatch"  # type: ignore[attr-defined]

    def test_xygraph_rejects_vector(self) -> None:
        sim = _sim()
        m = _mux3(sim)
        xy = sim.add(XYGraph(id="xy"))
        sim.connect(m, xy, dst_idx=0)
        with pytest.raises(SignalShapeError, match="shape.mismatch"):
            resolve_for_execution(sim)

    def test_all_errors_are_collected_before_raising(self) -> None:
        """D-11: error 級を全件集めてから 1 回だけ raise する。"""
        sim = _sim()
        m = _mux3(sim)
        integ = sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0], id="integ"))
        xy = sim.add(XYGraph(id="xy"))
        sim.connect(m, integ)
        sim.connect(m, xy, dst_idx=0)
        with pytest.raises(SignalShapeError) as ei:
            resolve_for_execution(sim)
        codes = [d.code for d in ei.value.diagnostics]  # type: ignore[attr-defined]
        block_ids = sorted({d.block_id for d in ei.value.diagnostics})  # type: ignore[attr-defined]
        assert codes == ["shape.mismatch", "shape.mismatch"]
        assert block_ids == ["integ", "xy"]
        assert "2 error(s)" in str(ei.value)

    def test_signal_shape_error_is_block_spec_error(self) -> None:
        assert issubclass(SignalShapeError, BlockSpecError)

    def test_run_raises_the_same_error(self) -> None:
        sim = _sim()
        m = _mux3(sim)
        integ = sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0], id="integ"))
        sim.connect(m, integ)
        with pytest.raises(SignalShapeError, match="shape.mismatch"):
            sim.run()

    def test_algebraic_loop_is_reported_before_shape_mismatch(self) -> None:
        """D-11 / 差分 D-c: 代数ループ検出が shape 解決より先。"""
        from flode.exceptions import AlgebraicLoopError

        sim = _sim()
        m = _mux3(sim)
        g1 = sim.add(Gain(k=1.0, id="g1"))
        g2 = sim.add(Gain(k=1.0, id="g2"))
        integ = sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0], id="integ"))
        sim.connect(g1, g2)
        sim.connect(g2, g1)  # 代数ループ
        sim.connect(m, integ)  # shape 不一致
        with pytest.raises(AlgebraicLoopError):
            sim.run()


# ---------------------------------------------------------------------------
# AC-6: opaque island (ユーザーコード境界) は fail-closed
# ---------------------------------------------------------------------------


class TestOpaqueIsland:
    def test_subsystem_passes_vector_through_and_resolves_inner(self) -> None:
        """ADR-0079 §(6): Subsystem 境界はベクトルを透過し、内部が再帰解決される。"""
        sim = _sim()
        m = _mux3(sim)
        sub = Subsystem(
            blocks=[
                Inport(port_idx=0, id="ip"),
                Gain(k=1.0, id="ig"),
                Outport(port_idx=0, id="op"),
            ],
            connections=[
                {"src": "ip", "src_port": 0, "dst": "ig", "dst_port": 0},
                {"src": "ig", "src_port": 0, "dst": "op", "dst_port": 0},
            ],
            id="sub",
        )
        sim.add(sub)
        sim.connect(m, "sub")
        res = resolve_for_execution(sim)
        assert res.in_shape("sub", 0) == (3,)
        assert res.out_shape("sub", 0) == (3,)
        inner = res.inner["sub"]
        assert inner.out_shape("ip", 0) == (3,)
        assert inner.out_shape("ig", 0) == (3,)
        assert inner.in_shape("op", 0) == (3,)
        # dtype island (SPEC-0028 Q6): 内部は全ポート float64
        assert set(inner.ports.values()) == {"float64"}

    def test_fcn_rejects_vector_input(self) -> None:
        sim = _sim()
        m = _mux3(sim)
        f = sim.add(Fcn(expression="u[0]", id="f"))
        sim.connect(m, f)
        with pytest.raises(SignalShapeError, match="shape.opaque_scalar_island"):
            resolve_for_execution(sim)

    def test_decorator_block_rejects_vector_input(self) -> None:
        @block
        def double(t: float, u: float) -> float:
            return 2.0 * u

        sim = _sim()
        m = _mux3(sim)
        d = sim.add(double(id="d"))
        sim.connect(m, d)
        with pytest.raises(SignalShapeError, match="shape.opaque_scalar_island"):
            resolve_for_execution(sim)

    def test_python_function_rejects_vector_input(self) -> None:
        code = textwrap.dedent(
            """
            from flode import block

            @block
            def twice(t: float, u: float) -> float:
                return 2.0 * u
            """
        )
        sim = _sim()
        m = _mux3(sim)
        pf = sim.add(PythonFunction(code=code, id="pf"))
        sim.connect(m, pf)
        # run 経路 (full mode) で拒否
        with pytest.raises(SignalShapeError, match="shape.opaque_scalar_island"):
            resolve_for_execution(sim)

    def test_default_output_v_wrapper_is_fail_closed(self) -> None:
        """ADR-0018 §2.3 の防御的 flatten は無い: 非 () 入力で明示エラー。"""
        g = Integrator(x0=0.0, id="integ")
        with pytest.raises(BlockSpecError, match="scalar `output` API"):
            Block.output_v(g, 0.0, np.zeros(1), (np.array([1.0, 2.0, 3.0]),))

    def test_declared_inport_shape_mismatch_is_rejected(self) -> None:
        """明示 ``port_shape`` は宣言: 外側 shape と違えば shape.mismatch。"""
        sim = _sim()
        m = _mux3(sim)
        sub = Subsystem(id="sub")
        sub.add(Inport(port_idx=0, port_shape=(2,), id="ip"))
        sub.add(Outport(port_idx=0, id="op"))
        sub.connect("ip", "op")
        sim.add(sub)
        sim.connect(m, "sub")
        with pytest.raises(SignalShapeError, match="shape.mismatch") as ei:
            resolve_for_execution(sim)
        assert ei.value.expected_shape == (2,)
        assert ei.value.actual_shape == (3,)

    def test_inner_error_is_reported_with_subsystem_context(self) -> None:
        """内部の error 級診断も集約例外に含まれる (Subsystem 名付き)。"""
        sim = _sim()
        m = _mux3(sim)
        sub = Subsystem(id="sub")
        sub.add(Inport(port_idx=0, id="ip"))
        sub.add(XYGraph(id="xy"))
        sub.connect("ip", "xy", 0, 0)
        sim.add(sub)
        sim.connect(m, "sub")
        with pytest.raises(SignalShapeError, match="inside Subsystem 'sub'"):
            resolve_for_execution(sim)


# ---------------------------------------------------------------------------
# シンク (Scope labels / large_vector)
# ---------------------------------------------------------------------------


class TestSinkDiagnostics:
    def test_scope_per_port_labels_are_accepted(self) -> None:
        sim = _sim()
        m = _mux3(sim)
        sc = sim.add(Scope(n_inputs=1, labels=["v"], id="sc"))
        sim.connect(m, sc)
        res = resolve_for_execution(sim)
        assert "shape.mismatch" not in _codes(res)

    def test_scope_per_column_labels_are_accepted(self) -> None:
        sim = _sim()
        m = _mux3(sim)
        sc = sim.add(Scope(n_inputs=1, labels=["a", "b", "c"], id="sc"))
        sim.connect(m, sc)
        resolve_for_execution(sim)

    def test_scope_label_count_mismatch(self) -> None:
        sim = _sim()
        m = _mux3(sim)
        sc = sim.add(Scope(n_inputs=1, labels=["a", "b"], id="sc"))
        sim.connect(m, sc)
        with pytest.raises(SignalShapeError, match="label"):
            resolve_for_execution(sim)

    def test_large_vector_is_info_only(self) -> None:
        n = SCOPE_LARGE_VECTOR_COLUMNS + 1
        sim = _sim()
        m = sim.add(Mux(n=n, id="m"))
        c = sim.add(Constant(value=1.0, id="c"))
        for i in range(n):
            sim.connect(c, m, dst_idx=i)
        sc = sim.add(Scope(id="sc"))
        sim.connect(m, sc)
        res = resolve_for_execution(sim)  # error にならない
        large = [d for d in res.diagnostics if d.code == "shape.large_vector"]
        assert len(large) == 1 and large[0].severity == "info"


# ---------------------------------------------------------------------------
# pre-filter (has_shape_source)
# ---------------------------------------------------------------------------


class TestShapeSource:
    def test_scalar_model_has_no_source(self) -> None:
        sim = _sim()
        c = sim.add(Constant(value=1.0))
        g = sim.add(Gain(k=2.0))
        sim.connect(c, g)
        assert has_shape_source(sim) is False
        assert sim._is_sm_a_mode() is True

    def test_mux_is_a_source(self) -> None:
        sim = _sim()
        sim.add(Mux(n=2))
        assert has_shape_source(sim) is True

    def test_array_gain_is_a_source(self) -> None:
        sim = _sim()
        sim.add(Gain(k=[1.0, 2.0]))
        assert has_shape_source(sim) is True
        sim2 = _sim()
        sim2.add(Gain(k=[[1.0, 2.0], [3.0, 4.0]], multiplication="matrix-Ku"))
        assert has_shape_source(sim2) is True

    def test_custom_declared_vector_port_is_a_source(self) -> None:
        sim = _sim()
        sim.add(_VectorSrc())
        assert has_shape_source(sim) is True


# ---------------------------------------------------------------------------
# AC-10: 網羅ガード (全 builtin Block クラスが shape 規則表に載る)
# ---------------------------------------------------------------------------


class TestShapeCoverageGuard:
    def test_all_builtin_block_classes_have_a_shape_rule(self) -> None:
        from flode.server.registry import _walk_block_classes

        rules = signals._SHAPE_RULES
        unmatched: list[str] = []
        for cls in _walk_block_classes():
            names = [c.__name__ for c in cls.__mro__]
            if not any(n in rules for n in names):
                unmatched.append(cls.__name__)
        assert unmatched == [], (
            "shape 規則テーブルに無い builtin ブロックがある (signals.py の "
            f"_SHAPE_RULES に追加すること): {unmatched}"
        )

    def test_dtype_and_shape_tables_cover_the_same_builtin_names(self) -> None:
        dtype_names = set(signals._CLASSIFICATION)
        shape_names = set(signals._SHAPE_RULES) - {"ElementwiseMixin", "VectorStateMixin"}
        assert dtype_names == shape_names

    def test_elementwise_rule_is_inherited_via_mixin(self) -> None:
        from flode.blocks._elementwise import ElementwiseMixin

        class _Ext(ElementwiseMixin, Block):
            def __init__(self) -> None:
                super().__init__(n_inputs=1, n_outputs=1)

            def output(
                self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]
            ) -> npt.NDArray[Any]:
                return np.array([u[0]])

            def _kernel(self, t, x, u):  # type: ignore[no-untyped-def]
                return (np.asarray(u[0]),)

        assert signals._classify_shape(_Ext()) == "elementwise"

    def test_unknown_custom_block_defaults_to_declared(self) -> None:
        assert signals._classify_shape(_VectorSrc()) == "declared"

    def test_decorator_block_is_opaque(self) -> None:
        @block
        def ident(t: float, u: float) -> float:
            return u

        assert signals._classify_shape(ident()) == "opaque"


# ---------------------------------------------------------------------------
# REST payload / 互換 shim
# ---------------------------------------------------------------------------


class TestPayloadAndCompat:
    def test_payload_carries_shape_and_signals_schema(self) -> None:
        sim = _sim()
        m = _mux3(sim)
        sc = sim.add(Scope(id="sc"))
        sim.connect(m, sc)
        payload = sim.resolve_signals().to_payload()
        assert payload["schema_version"] == "signals.v1"
        by_key = {(p["block_id"], p["direction"], p["port_index"]): p for p in payload["ports"]}
        assert by_key[("m", "out", 0)]["shape"] == [3]
        assert by_key[("m", "in", 0)]["shape"] == []
        assert payload["summary"]["vector_ports"] == 2
        assert payload["summary"]["max_rank"] == 1
        for d in payload["diagnostics"]:
            assert "expected_shape" in d and "actual_shape" in d

    def test_dtypes_shim_reexports_public_names(self) -> None:
        from flode.core import dtypes

        assert dtypes.resolve_dtypes is signals.resolve_dtypes
        assert dtypes.DTypeResolution is signals.SignalResolution
        assert dtypes.cast_value is signals.cast_value
        assert dtypes.SCHEMA_VERSION == "signals.v1"

    def test_simulator_resolve_dtypes_delegates_to_resolve_signals(self) -> None:
        sim = _sim()
        sim.add(Constant(value=1.0, id="c"))
        res = sim.resolve_dtypes()
        assert isinstance(res, SignalResolution)
        assert res.out_dtype("c", 0) == "float64"
        assert res.out_shape("c", 0) == ()
        assert res.signal(("c", "out", 0)) == ((), "float64")
