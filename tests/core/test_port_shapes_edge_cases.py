"""ADR-0017 SM-B ベクトルポート: 境界値・エッジケーステスト。

既存 ``tests/core/test_port_shapes.py`` (21 件) の続きとして、以下の観点を補強する。

観点 (要件 ID は指示書の番号に対応):
  #1  output_v default wrapper の n_inputs=0 ケース (Constant 等)
  #2  n_outputs=0 ケース (Scope/Terminator 等)
  #3  port_shapes_out 指定 + port_shapes_in=None (default) 混在
  #4  higher-rank shape (rank 2+) のブロック構築
  #5  空 list [] を渡した場合 (n_inputs=0)
  #6  _check_port_shapes: SM-A only モデルで shape check が常に成功
  #7  _is_sm_a_mode() の境界: 0 個 / 1 個 SM-A / SM-B 混在
  #8  SM-B run() のエラーメッセージ確認
  #9  multi-output ブロックの shape check (SM-A port と SM-B port が混在)
  #10 未接続 port (input_sources[i]=None) の shape check が skip される
  #11 空モデル (blocks=[]) の schema 0.4 round-trip
  #12 Subsystem SM-A 互換で port_shapes_in/out なし + save/load round-trip
  #13 Subsystem に明示的に port_shapes_in/out を渡して構築
  #14 rank-0 ndarray ↔ scalar の双方向変換
  #15 多入力 SM-A ブロック (Sum, Product) の output_v wrapper
  #16 direct_feedthrough=False ブロック (Integrator, UnitDelay) の output_v wrapper
  #17 全 33 ブロックが port_shapes default (全 ()) で構築できる
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from pyflw import Simulator
from pyflw.blocks import (
    Abs,
    Clock,
    Constant,
    Derivative,
    DiscreteIntegrator,
    DiscreteStateSpace,
    DiscreteTransferFunction,
    Divide,
    Gain,
    Integrator,
    LogicalOperator,
    MimoTransferFunction,
    MinMax,
    Product,
    PulseGenerator,
    Ramp,
    RelationalOperator,
    Saturation,
    Scope,
    Sign,
    Sine,
    StateSpace,
    Step,
    Sum,
    Switch,
    Terminator,
    TransferFunction,
    UnitDelay,
    ZeroOrderHold,
    ZeroOrderHoldDirect,
)
from pyflw.core.block import Block, _normalize_port_shapes
from pyflw.exceptions import BlockSpecError
from pyflw.subsystems.ports import Inport, Outport
from pyflw.subsystems.subsystem import Subsystem

# ---------------------------------------------------------------------------
# テスト用ヘルパーブロック
# ---------------------------------------------------------------------------


class _ZeroInputBlock(Block):
    """n_inputs=0 の SM-A ブロック (Constant 類似)。"""

    def __init__(self) -> None:
        super().__init__(n_inputs=0, n_outputs=1)

    def output(self, t, x, u):  # type: ignore[no-untyped-def]
        return np.array([42.0])


class _ZeroOutputBlock(Block):
    """n_outputs=0 の SM-A ブロック (Scope 類似)。"""

    def __init__(self) -> None:
        super().__init__(n_inputs=1, n_outputs=0)

    def output(self, t, x, u):  # type: ignore[no-untyped-def]
        return np.zeros(0)


class _TwoOutputMixedBlock(Block):
    """SM-A と SM-B ポートを持つ 2 出力ブロック (port_shapes_out=[ (), (3,) ])。"""

    def __init__(self) -> None:
        super().__init__(n_inputs=0, n_outputs=2, port_shapes_out=[(), (3,)])

    def output_v(self, t, x, u):  # type: ignore[no-untyped-def]
        return (np.array(1.0), np.array([1.0, 2.0, 3.0]))


class _MatrixPortBlock(Block):
    """rank-2 shape (3, 4) の入力・出力を持つ SM-B ブロック。"""

    def __init__(self) -> None:
        super().__init__(
            n_inputs=1,
            n_outputs=1,
            port_shapes_in=[(3, 4)],
            port_shapes_out=[(3, 4)],
        )

    def output_v(self, t, x, u):  # type: ignore[no-untyped-def]
        return (u[0],)


class _ScalarSrc(Block):
    """SM-A scalar 出力ブロック (テスト用)。"""

    def __init__(self) -> None:
        super().__init__(n_inputs=0, n_outputs=1)

    def output(self, t, x, u):  # type: ignore[no-untyped-def]
        return np.array([1.0])


class _VectorSink(Block):
    """SM-B shape (3,) 入力ブロック (テスト用)。"""

    def __init__(self) -> None:
        super().__init__(n_inputs=1, n_outputs=0, port_shapes_in=[(3,)])

    def output_v(self, t, x, u):  # type: ignore[no-untyped-def]
        return ()


class _VectorSrc(Block):
    """SM-B shape (3,) 出力ブロック (テスト用)。"""

    def __init__(self) -> None:
        super().__init__(n_inputs=0, n_outputs=1, port_shapes_out=[(3,)])

    def output_v(self, t, x, u):  # type: ignore[no-untyped-def]
        return (np.array([1.0, 2.0, 3.0]),)


# ---------------------------------------------------------------------------
# #1: output_v default wrapper の n_inputs=0 ケース
# ---------------------------------------------------------------------------


class TestOutputVWrapperNoInputs:
    def test_zero_input_block_output_v_called_with_empty_tuple(self) -> None:
        """n_inputs=0 ブロックで output_v(t, x, ()) が動作する (Constant 類似)。"""
        block = _ZeroInputBlock()
        x = np.zeros(0)
        y = block.output_v(0.0, x, ())
        assert isinstance(y, tuple)
        assert len(y) == 1
        np.testing.assert_allclose(float(y[0]), 42.0)

    def test_constant_block_output_v_with_empty_tuple(self) -> None:
        """Constant ブロックの output_v が空タプル入力で正しく動く。"""
        c = Constant(value=5.0)
        y = c.output_v(0.0, np.zeros(0), ())
        assert len(y) == 1
        np.testing.assert_allclose(float(y[0]), 5.0)

    def test_clock_block_output_v_with_empty_tuple(self) -> None:
        """Clock ブロックの output_v が空タプル入力で時刻 t を返す。"""
        c = Clock()
        y = c.output_v(3.14, np.zeros(0), ())
        assert len(y) == 1
        np.testing.assert_allclose(float(y[0]), 3.14)


# ---------------------------------------------------------------------------
# #2: n_outputs=0 ケース (Scope/Terminator)
# ---------------------------------------------------------------------------


class TestOutputVWrapperNoOutputs:
    def test_zero_output_block_output_v_returns_empty_tuple(self) -> None:
        """n_outputs=0 ブロックの output_v が空タプル () を返す。"""
        block = _ZeroOutputBlock()
        y = block.output_v(0.0, np.zeros(0), (np.array(1.0),))
        assert isinstance(y, tuple)
        assert len(y) == 0

    def test_scope_block_output_v_returns_empty_tuple(self) -> None:
        """Scope の output_v が空タプルを返す (Scope は n_outputs=0)。"""
        sc = Scope(n_inputs=1)
        y = sc.output_v(0.0, np.zeros(0), (np.array(2.0),))
        assert isinstance(y, tuple)
        assert len(y) == 0

    def test_terminator_block_output_v_returns_empty_tuple(self) -> None:
        """Terminator の output_v が空タプルを返す。"""
        t_block = Terminator(n_inputs=1)
        y = t_block.output_v(0.0, np.zeros(0), (np.array(3.0),))
        assert isinstance(y, tuple)
        assert len(y) == 0


# ---------------------------------------------------------------------------
# #3: port_shapes_out 指定 + port_shapes_in=None (default) 混在
# ---------------------------------------------------------------------------


class TestPortShapesMixedSpecification:
    def test_port_shapes_out_only_port_shapes_in_defaults_to_scalar(self) -> None:
        """port_shapes_out のみ指定し port_shapes_in は default (全 ()) になる。"""
        block = _TwoOutputMixedBlock()
        # 入力ゼロなので port_shapes_in は空タプル
        assert block.port_shapes_in == ()
        # 出力は混在: ((), (3,))
        assert block.port_shapes_out == ((), (3,))

    def test_block_with_out_specified_in_default_construction(self) -> None:
        """port_shapes_out 指定 + port_shapes_in=None (default) でブロックが構築できる。"""

        class _SrcOnly(Block):
            def __init__(self) -> None:
                super().__init__(n_inputs=1, n_outputs=2, port_shapes_out=[(5,), (2, 3)])

            def output_v(self, t, x, u):  # type: ignore[no-untyped-def]
                return (np.zeros(5), np.zeros((2, 3)))

        b = _SrcOnly()
        assert b.port_shapes_in == ((),)  # default → scalar
        assert b.port_shapes_out == ((5,), (2, 3))


# ---------------------------------------------------------------------------
# #4: higher-rank shape (rank 2+)
# ---------------------------------------------------------------------------


class TestHigherRankShapes:
    def test_matrix_port_block_construction_with_rank2_shape(self) -> None:
        """(3, 4) shape のポートを持つブロックが構築できる。"""
        b = _MatrixPortBlock()
        assert b.port_shapes_in == ((3, 4),)
        assert b.port_shapes_out == ((3, 4),)

    def test_normalize_port_shapes_with_rank3(self) -> None:
        """rank-3 shape (2, 3, 4) で _normalize_port_shapes が動く。"""
        result = _normalize_port_shapes([(2, 3, 4)], n_ports=1, side="in")
        assert result == ((2, 3, 4),)

    def test_normalize_port_shapes_mixed_ranks(self) -> None:
        """rank-0 / rank-1 / rank-2 の混在で正規化できる。"""
        result = _normalize_port_shapes([(), (3,), (2, 4)], n_ports=3, side="out")
        assert result == ((), (3,), (2, 4))

    def test_matrix_port_connected_to_matching_matrix_port_passes_shape_check(self) -> None:
        """(3, 4) ↔ (3, 4) 接続で shape check が通る。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        src = sim.add(_MatrixPortBlock())
        # (3,4) 出力→(3,4) 入力: MatrixPortBlock をシンクとして接続
        # src の output[0] (shape (3,4)) → second MatrixPortBlock の input[0]
        dst = sim.add(_MatrixPortBlock())
        sim.connect(src, dst)
        # 例外なく shape check を通過することを確認
        sim._check_port_shapes()

    def test_matrix_port_to_scalar_mismatch_raises(self) -> None:
        """(3, 4) → () の接続は shape mismatch で BlockSpecError。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        src = sim.add(_MatrixPortBlock())
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(src, sc)
        with pytest.raises(BlockSpecError, match="Port shape mismatch"):
            sim._check_port_shapes()


# ---------------------------------------------------------------------------
# #5: 空 list [] を渡した場合 (n_inputs=0)
# ---------------------------------------------------------------------------


class TestEmptyListPortShapes:
    def test_empty_list_for_zero_input_block_is_equivalent_to_none(self) -> None:
        """n_inputs=0 ブロックに空 list [] を渡すと None (全 ()) と同じ結果になる。"""
        result_none = _normalize_port_shapes(None, n_ports=0, side="in")
        result_empty = _normalize_port_shapes([], n_ports=0, side="in")
        assert result_none == result_empty == ()

    def test_block_with_empty_list_port_shapes_in_for_zero_inputs(self) -> None:
        """n_inputs=0 のブロックに port_shapes_in=[] を渡しても BlockSpecError にならない。"""

        class _EmptyInBlock(Block):
            def __init__(self) -> None:
                super().__init__(n_inputs=0, n_outputs=1, port_shapes_in=[])

            def output(self, t, x, u):  # type: ignore[no-untyped-def]
                return np.array([1.0])

        b = _EmptyInBlock()
        assert b.port_shapes_in == ()

    def test_empty_list_port_shapes_out_for_zero_outputs(self) -> None:
        """n_outputs=0 のブロックに port_shapes_out=[] を渡しても BlockSpecError にならない。"""

        class _EmptyOutBlock(Block):
            def __init__(self) -> None:
                super().__init__(n_inputs=1, n_outputs=0, port_shapes_out=[])

            def output(self, t, x, u):  # type: ignore[no-untyped-def]
                return np.zeros(0)

        b = _EmptyOutBlock()
        assert b.port_shapes_out == ()


# ---------------------------------------------------------------------------
# #6: _check_port_shapes: SM-A only モデルで常に成功
# ---------------------------------------------------------------------------


class TestCheckPortShapesSmAOnly:
    def test_sm_a_chain_check_always_passes(self) -> None:
        """SM-A only モデル (全 () shape) で _check_port_shapes が例外を出さない。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        c = sim.add(Constant(value=1.0))
        g = sim.add(Gain(k=2.0))
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(c, g)
        sim.connect(g, sc)
        # 例外なし
        sim._check_port_shapes()

    def test_empty_simulator_check_passes(self) -> None:
        """ブロックなし Simulator でも _check_port_shapes が例外を出さない。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        sim._check_port_shapes()

    def test_disconnected_sm_a_blocks_check_passes(self) -> None:
        """未接続の SM-A ブロックが複数あっても _check_port_shapes が通る。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(Constant(value=1.0))
        sim.add(Gain(k=2.0))
        # 接続なし
        sim._check_port_shapes()


# ---------------------------------------------------------------------------
# #7: _is_sm_a_mode() の境界
# ---------------------------------------------------------------------------


class TestIsSmAModeEdgeCases:
    def test_zero_blocks_is_sm_a_mode(self) -> None:
        """ブロック 0 個の Simulator は SM-A モード (vacuously True)。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        assert sim._is_sm_a_mode() is True

    def test_single_sm_a_block_is_sm_a_mode(self) -> None:
        """SM-A ブロック 1 個の Simulator は SM-A モード。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(Constant(value=1.0))
        assert sim._is_sm_a_mode() is True

    def test_multiple_sm_a_blocks_is_sm_a_mode(self) -> None:
        """複数 SM-A ブロックでも SM-A モード。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(Constant(value=1.0))
        sim.add(Gain(k=2.0))
        sim.add(Scope(n_inputs=1))
        assert sim._is_sm_a_mode() is True

    def test_single_sm_b_block_is_not_sm_a_mode(self) -> None:
        """SM-B ブロック 1 個でも SM-A モードではない。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(_VectorSrc())
        assert sim._is_sm_a_mode() is False

    def test_mixed_sm_a_and_sm_b_is_not_sm_a_mode(self) -> None:
        """SM-A と SM-B の混在は SM-A モードではない。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(Constant(value=1.0))
        sim.add(_VectorSrc())
        assert sim._is_sm_a_mode() is False

    def test_sm_b_only_output_port_is_not_sm_a_mode(self) -> None:
        """SM-B が port_shapes_out のみにある場合も SM-A モードではない。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(_TwoOutputMixedBlock())
        assert sim._is_sm_a_mode() is False

    def test_sm_b_only_input_port_is_not_sm_a_mode(self) -> None:
        """SM-B が port_shapes_in のみにある場合も SM-A モードではない。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(_VectorSink())
        assert sim._is_sm_a_mode() is False


# ---------------------------------------------------------------------------
# #8: SM-B run() のエラーメッセージ確認
# ---------------------------------------------------------------------------


class TestSmBRunErrorMessage:
    def test_sm_b_run_error_contains_expected_phrase(self) -> None:
        """SM-B モードの run() エラーが 'SM-B vector ports detected' を含む。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(_VectorSrc())
        sim.add(_VectorSink())
        sim.connect(sim.blocks[0], sim.blocks[1])
        with pytest.raises(BlockSpecError, match="SM-B vector ports detected"):
            sim.run()

    def test_sm_b_run_error_is_block_spec_error(self) -> None:
        """SM-B モードの run() が BlockSpecError を raise する。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(_VectorSrc())
        sink = sim.add(_VectorSink())
        sim.connect(sim.blocks[0], sink)
        with pytest.raises(BlockSpecError):
            sim.run()


# ---------------------------------------------------------------------------
# #9: multi-output 接続の shape check
# ---------------------------------------------------------------------------


class TestMultiOutputShapeCheck:
    def test_sm_a_port_of_mixed_block_to_scalar_passes(self) -> None:
        """2出力ブロックの port[0] (= SM-A ()) が SM-A 入力に接続 → check 通過。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        src = sim.add(_TwoOutputMixedBlock())
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(src, sc, src_idx=0, dst_idx=0)
        # SM-B ポートが含まれているため _is_sm_a_mode() は False だが、
        # 接続した port[0] は shape () 同士なので shape check だけは通過する
        sim._check_port_shapes()

    def test_sm_b_port_of_mixed_block_to_scalar_raises(self) -> None:
        """2出力ブロックの port[1] (= SM-B (3,)) が SM-A 入力に接続 → mismatch。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        src = sim.add(_TwoOutputMixedBlock())
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(src, sc, src_idx=1, dst_idx=0)
        with pytest.raises(BlockSpecError, match="Port shape mismatch"):
            sim._check_port_shapes()

    def test_sm_b_port_of_mixed_block_to_vector_passes(self) -> None:
        """2出力ブロックの port[1] (= SM-B (3,)) が (3,) 入力に接続 → check 通過。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        src = sim.add(_TwoOutputMixedBlock())
        vsink = sim.add(_VectorSink())
        sim.connect(src, vsink, src_idx=1, dst_idx=0)
        sim._check_port_shapes()


# ---------------------------------------------------------------------------
# #10: 未接続 port (input_sources[i]=None) の shape check が skip される
# ---------------------------------------------------------------------------


class TestUnconnectedPortShapeCheckSkipped:
    def test_unconnected_input_port_is_skipped(self) -> None:
        """未接続ポートの shape check は skip され BlockSpecError が出ない。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(Gain(k=2.0))  # input[0] は未接続
        # input_sources[0] is None なので shape check は skip される
        sim._check_port_shapes()

    def test_unconnected_sm_b_input_is_skipped(self) -> None:
        """SM-B port でも未接続なら skip される。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(_VectorSink())  # SM-B (3,) 入力ポートが未接続
        sim._check_port_shapes()

    def test_partially_connected_block_skips_only_unconnected(self) -> None:
        """接続済みポートのみ shape check し、未接続は skip される。"""

        class _TwoInputBlock(Block):
            def __init__(self) -> None:
                super().__init__(n_inputs=2, n_outputs=1)

            def output(self, t, x, u):  # type: ignore[no-untyped-def]
                return np.array([u[0]])

        sim = Simulator(t_end=0.1, dt=0.01)
        c = sim.add(Constant(value=1.0))
        b = sim.add(_TwoInputBlock())
        sim.connect(c, b, dst_idx=0)
        # input[1] は未接続: skip される
        sim._check_port_shapes()


# ---------------------------------------------------------------------------
# #11: 空モデル (blocks=[]) の schema 0.4 round-trip
# ---------------------------------------------------------------------------


class TestEmptyModelSchema04RoundTrip:
    def test_empty_simulator_save_produces_schema_0_4(self, tmp_path: Path) -> None:
        """ブロックなし Simulator を保存すると schema_version=0.4 のファイルになる。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        path = tmp_path / "empty.flw.json"
        sim.save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == "0.4"

    def test_empty_simulator_save_has_empty_blocks_and_connections(self, tmp_path: Path) -> None:
        """ブロックなし Simulator の保存データは blocks/connections が空リスト。"""
        sim = Simulator(t_end=1.0, dt=0.01)
        path = tmp_path / "empty.flw.json"
        sim.save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["blocks"] == []
        assert data["connections"] == []

    def test_empty_model_load_back_produces_empty_simulator(self, tmp_path: Path) -> None:
        """ブロックなし Simulator を save → load するとブロックなし Simulator が復元される。"""
        sim = Simulator(t_end=0.5, dt=0.05)
        path = tmp_path / "empty.flw.json"
        sim.save(path)
        loaded = Simulator.load(path)
        assert len(loaded.blocks) == 0

    def test_empty_model_legacy_0_3_migration(self, tmp_path: Path) -> None:
        """空モデルの 0.3 → 0.4 migration が正常に動作する。"""
        path = tmp_path / "empty_legacy.flw.json"
        legacy = {
            "schema_version": "0.3",
            "metadata": {"created_at": "2026-05-06T00:00:00Z", "tool": "pyflw 0.3.0"},
            "simulator": {
                "t_end": 0.1,
                "dt": 0.01,
                "solver": "RK45",
                "rtol": 1e-6,
                "atol": 1e-9,
                "dt_base": None,
            },
            "blocks": [],
            "connections": [],
        }
        path.write_text(json.dumps(legacy), encoding="utf-8")
        loaded = Simulator.load(path)
        assert len(loaded.blocks) == 0


# ---------------------------------------------------------------------------
# #12: Subsystem SM-A 互換で port_shapes_in/out なし + save/load round-trip
# ---------------------------------------------------------------------------


class TestSubsystemSmACompatRoundTrip:
    def _make_simple_subsystem(self) -> Subsystem:
        """Constant → Gain → Outport の最小 Subsystem を作る。"""
        sub = Subsystem(n_inputs=1, n_outputs=1, id="sub")
        inp = Inport(port_idx=0, id="in0")
        g = Gain(k=3.0, id="g")
        out = Outport(port_idx=0, id="out0")
        sub.add(inp)
        sub.add(g)
        sub.add(out)
        sub.connect(inp, g)
        sub.connect(g, out)
        return sub

    def test_subsystem_without_port_shapes_has_scalar_defaults(self) -> None:
        """port_shapes_in/out なしで構築した Subsystem は全 () の default 値を持つ。"""
        sub = self._make_simple_subsystem()
        assert sub.port_shapes_in == ((),)
        assert sub.port_shapes_out == ((),)

    def test_subsystem_sm_a_save_loads_correctly(self, tmp_path: Path) -> None:
        """SM-A 互換 Subsystem の save → load round-trip が動く。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        sub = sim.add(self._make_simple_subsystem())
        c = sim.add(Constant(value=2.0))
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(c, sub)
        sim.connect(sub, sc)

        path = tmp_path / "sub_sm_a.flw.json"
        sim.save(path)
        loaded = Simulator.load(path)
        loaded.run()

        sc_loaded = loaded.get_block("Scope_0")
        arr = np.asarray(sc_loaded.values).reshape(-1)
        # Constant(2.0) * Gain(3.0) = 6.0
        np.testing.assert_allclose(arr, 6.0 * np.ones_like(arr))


# ---------------------------------------------------------------------------
# #13: Subsystem に明示的に port_shapes_in/out を渡して構築
# ---------------------------------------------------------------------------


class TestSubsystemWithExplicitPortShapes:
    def test_subsystem_with_explicit_scalar_port_shapes_constructs(self) -> None:
        """port_shapes_in=[()] / port_shapes_out=[()] を明示しても構築できる。"""
        sub = Subsystem(
            n_inputs=1,
            n_outputs=1,
            id="sub_explicit",
            port_shapes_in=[()],
            port_shapes_out=[()],
        )
        assert sub.port_shapes_in == ((),)
        assert sub.port_shapes_out == ((),)

    def test_subsystem_with_vector_port_shapes_scaffolding(self) -> None:
        """SM-B 用の port_shapes_in / port_shapes_out を渡しても構築自体は成功する。

        Phase 3 #4 で run path / 内部整合性チェックが完成するまでは、
        構築と属性設定だけを検証する (build 呼び出し前の scaffolding)。
        """
        sub = Subsystem(
            n_inputs=1,
            n_outputs=1,
            id="sub_vector",
            port_shapes_in=[(3,)],
            port_shapes_out=[(3,)],
        )
        assert sub.port_shapes_in == ((3,),)
        assert sub.port_shapes_out == ((3,),)

    def test_subsystem_is_sm_b_when_vector_port_shapes_set(self) -> None:
        """vector port_shapes を持つ Subsystem を含む Simulator は SM-B モードと判定される。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        sub = Subsystem(
            n_inputs=1,
            n_outputs=1,
            port_shapes_in=[(3,)],
            port_shapes_out=[(3,)],
        )
        sim.add(sub)
        assert sim._is_sm_a_mode() is False


# ---------------------------------------------------------------------------
# #14: rank-0 ndarray ↔ scalar の双方向変換
# ---------------------------------------------------------------------------


class TestRankZeroArrayScalarConversion:
    def test_rank0_ndarray_as_input_to_output_v_wrapper(self) -> None:
        """rank-0 ndarray (np.array(3.0)) を u として渡すと正しく計算される。"""
        g = Gain(k=4.0)
        u = (np.array(3.0),)  # rank-0 ndarray
        y = g.output_v(0.0, np.zeros(0), u)
        assert len(y) == 1
        np.testing.assert_allclose(float(y[0]), 12.0)

    def test_python_float_as_input_to_output_v_wrapper(self) -> None:
        """Python float (非 ndarray) を u として渡しても正しく計算される。"""

        class _FloatInputBlock(Block):
            """float を u として受け取ることを想定する SM-A ブロック。"""

            def __init__(self) -> None:
                super().__init__(n_inputs=1, n_outputs=1)

            def output(self, t, x, u):  # type: ignore[no-untyped-def]
                return np.array([u[0] * 2.0])

        block = _FloatInputBlock()
        # output_v の wrapper は u[i] を np.asarray(ui).item() で float 化する設計
        y = block.output_v(0.0, np.zeros(0), (np.array(5.0),))
        assert len(y) == 1
        np.testing.assert_allclose(float(y[0]), 10.0)

    def test_output_v_returns_rank0_ndarrays(self) -> None:
        """output_v の戻り値は rank-0 ndarray (shape ()) である。"""
        g = Gain(k=1.0)
        y = g.output_v(0.0, np.zeros(0), (np.array(7.0),))
        assert len(y) == 1
        assert y[0].shape == ()

    def test_rank0_ndarray_value_preserved(self) -> None:
        """rank-0 ndarray の値が float 変換を経ても保持される。"""
        g = Gain(k=1.0)
        input_val = np.array(np.pi)  # rank-0 ndarray with specific value
        y = g.output_v(0.0, np.zeros(0), (input_val,))
        np.testing.assert_allclose(float(y[0]), np.pi)

    def test_scalar_vs_rank0_ndarray_produce_same_output(self) -> None:
        """``np.asarray(4.0)`` (Python float 由来) と ``np.array(4.0)`` (明示 rank-0)
        で output_v の結果が一致する (= wrapper 内の rank-0 → float 変換が等価)。"""
        g = Gain(k=2.5)
        y_via_asarray = g.output_v(0.0, np.zeros(0), (np.asarray(4.0),))
        y_via_array = g.output_v(0.0, np.zeros(0), (np.array(4.0),))
        np.testing.assert_allclose(float(y_via_asarray[0]), 10.0)
        np.testing.assert_allclose(float(y_via_array[0]), float(y_via_asarray[0]))


# ---------------------------------------------------------------------------
# #15: 多入力 SM-A ブロック (Sum, Product) の output_v wrapper
# ---------------------------------------------------------------------------


class TestMultiInputSmABlockOutputV:
    def test_sum_two_inputs_via_output_v_wrapper(self) -> None:
        """Sum(2入力) の output_v が正しく 2 入力の和を計算する。"""
        s = Sum(signs="++")
        u = (np.array(3.0), np.array(4.0))
        y = s.output_v(0.0, np.zeros(0), u)
        assert len(y) == 1
        np.testing.assert_allclose(float(y[0]), 7.0)

    def test_sum_subtract_via_output_v_wrapper(self) -> None:
        """Sum(signs='+-') の output_v が u[0] - u[1] を計算する。"""
        s = Sum(signs="+-")
        u = (np.array(10.0), np.array(3.0))
        y = s.output_v(0.0, np.zeros(0), u)
        assert len(y) == 1
        np.testing.assert_allclose(float(y[0]), 7.0)

    def test_product_two_inputs_via_output_v_wrapper(self) -> None:
        """Product(2入力) の output_v が u[0] * u[1] を計算する。"""
        p = Product(n_inputs=2)
        u = (np.array(3.0), np.array(5.0))
        y = p.output_v(0.0, np.zeros(0), u)
        assert len(y) == 1
        np.testing.assert_allclose(float(y[0]), 15.0)

    def test_product_three_inputs_via_output_v_wrapper(self) -> None:
        """Product(3入力) の output_v が 3 入力積を計算する。"""
        p = Product(n_inputs=3)
        u = (np.array(2.0), np.array(3.0), np.array(4.0))
        y = p.output_v(0.0, np.zeros(0), u)
        assert len(y) == 1
        np.testing.assert_allclose(float(y[0]), 24.0)

    def test_sum_three_inputs_via_output_v_wrapper(self) -> None:
        """Sum(3入力) の output_v が正しく 3 入力を処理する。"""
        s = Sum(signs="++-")
        u = (np.array(1.0), np.array(2.0), np.array(0.5))
        y = s.output_v(0.0, np.zeros(0), u)
        assert len(y) == 1
        np.testing.assert_allclose(float(y[0]), 2.5)


# ---------------------------------------------------------------------------
# #16: direct_feedthrough=False ブロック (Integrator, UnitDelay) の output_v wrapper
# ---------------------------------------------------------------------------


class TestDirectFeedthroughFalseBlockOutputV:
    def test_integrator_output_v_returns_state(self) -> None:
        """Integrator (direct_feedthrough=False) の output_v が状態を返す。"""
        integ = Integrator(x0=5.0)
        x = np.array([5.0])
        u = (np.array(0.0),)  # 入力はゼロ (direct_feedthrough=False なので無視される)
        y = integ.output_v(0.0, x, u)
        assert len(y) == 1
        np.testing.assert_allclose(float(y[0]), 5.0)

    def test_integrator_output_v_ignores_input_for_output(self) -> None:
        """Integrator の output は入力 u に依存しない (direct_feedthrough=False)。"""
        integ = Integrator(x0=3.0)
        x = np.array([3.0])
        # u の値が違っても output は同じ (state x[0] のみ返す)
        y1 = integ.output_v(0.0, x, (np.array(0.0),))
        y2 = integ.output_v(0.0, x, (np.array(100.0),))
        np.testing.assert_allclose(float(y1[0]), float(y2[0]))

    def test_unit_delay_output_v_returns_state(self) -> None:
        """UnitDelay (direct_feedthrough=False) の output_v が現サンプル出力を返す。"""
        ud = UnitDelay(sample_time=0.1, x0=7.0)
        # state[0]=output_curr, state[1]=output_next
        x = np.array([7.0, 7.0])
        u = (np.array(0.0),)
        y = ud.output_v(0.0, x, u)
        assert len(y) == 1
        np.testing.assert_allclose(float(y[0]), 7.0)

    def test_integrator_output_v_with_zero_state(self) -> None:
        """Integrator x0=0 で output_v が 0 を返す。"""
        integ = Integrator(x0=0.0)
        x = np.array([0.0])
        y = integ.output_v(0.0, x, (np.array(1.0),))
        assert len(y) == 1
        np.testing.assert_allclose(float(y[0]), 0.0)


# ---------------------------------------------------------------------------
# #17: 全 33 ブロックが port_shapes default (全 ()) で構築できる
# ---------------------------------------------------------------------------


class TestAllBlocksDefaultPortShapes:
    """全ブロックが port_shapes_in/out を省略したまま (= default 全 ()) で構築できる。

    各ブロックに最低限の引数のみを渡し、BlockSpecError 等の例外が出ないことを確認する。
    さらに全ての SM-A default port shapes が () であることを確認する。
    """

    @pytest.mark.parametrize(
        "block,expected_in,expected_out",
        [
            # Sources (n_inputs=0)
            (Constant(value=1.0), (), ((),)),
            (Step(step_time=1.0), (), ((),)),
            (Sine(amplitude=1.0, frequency=1.0), (), ((),)),
            (Ramp(slope=1.0), (), ((),)),
            (Clock(), (), ((),)),
            (PulseGenerator(period=1.0), (), ((),)),
            # Sinks
            (Scope(n_inputs=1), ((),), ()),
            (Terminator(n_inputs=1), ((),), ()),
            # Continuous
            (Integrator(x0=0.0), ((),), ((),)),
            (
                StateSpace(
                    A=np.array([[-1.0]]),
                    B=np.array([[1.0]]),
                    C=np.array([[1.0]]),
                    D=np.array([[0.0]]),
                ),
                ((),),
                ((),),
            ),
            (TransferFunction(numerator=[1.0], denominator=[1.0, 1.0]), ((),), ((),)),
            (
                MimoTransferFunction(
                    numerators=[[[1.0]]],
                    denominator=[1.0, 1.0],
                ),
                ((),),
                ((),),
            ),
            (Derivative(), ((),), ((),)),
            # Discrete
            (UnitDelay(sample_time=0.1, x0=0.0), ((),), ((),)),
            (
                DiscreteIntegrator(sample_time=0.1, gain=1.0),
                ((),),
                ((),),
            ),
            (ZeroOrderHold(sample_time=0.1), ((),), ((),)),
            (ZeroOrderHoldDirect(sample_time=0.1), ((),), ((),)),
            (
                DiscreteStateSpace(
                    A=np.array([[0.9]]),
                    B=np.array([[0.1]]),
                    C=np.array([[1.0]]),
                    D=np.array([[0.0]]),
                    sample_time=0.1,
                ),
                ((),),
                ((),),
            ),
            (
                DiscreteTransferFunction(
                    numerator=[1.0],
                    denominator=[1.0, -0.9],
                    sample_time=0.1,
                ),
                ((),),
                ((),),
            ),
            # Mathops
            (Gain(k=1.0), ((),), ((),)),
            (Sum(signs="++"), ((), ()), ((),)),
            (Product(n_inputs=2), ((), ()), ((),)),
            (Saturation(lower=-1.0, upper=1.0), ((),), ((),)),
            (Abs(), ((),), ((),)),
            (Sign(), ((),), ((),)),
            (MinMax(operator="min", n_inputs=2), ((), ()), ((),)),
            (Divide(signs="*/"), ((), ()), ((),)),
            # Logic
            (RelationalOperator(operator="<"), ((), ()), ((),)),
            (LogicalOperator(operator="AND"), ((), ()), ((),)),
            # Routing
            (Switch(), ((), (), ()), ((),)),
        ],
    )
    def test_block_has_scalar_default_port_shapes(
        self,
        block: Block,
        expected_in: tuple,
        expected_out: tuple,
    ) -> None:
        """各ブロックが期待どおりの SM-A default port_shapes を持つ。"""
        assert block.port_shapes_in == expected_in, (
            f"{type(block).__name__}.port_shapes_in: "
            f"expected {expected_in}, got {block.port_shapes_in}"
        )
        assert block.port_shapes_out == expected_out, (
            f"{type(block).__name__}.port_shapes_out: "
            f"expected {expected_out}, got {block.port_shapes_out}"
        )

    def test_subsystem_default_port_shapes(self) -> None:
        """Subsystem も port_shapes を省略すると全 () の default になる。"""
        sub = Subsystem(n_inputs=2, n_outputs=1)
        assert sub.port_shapes_in == ((), ())
        assert sub.port_shapes_out == ((),)

    def test_inport_default_port_shapes(self) -> None:
        """Inport (n_inputs=0, n_outputs=1) の default port_shapes。"""
        ip = Inport(port_idx=0)
        assert ip.port_shapes_in == ()
        assert ip.port_shapes_out == ((),)

    def test_outport_default_port_shapes(self) -> None:
        """Outport (n_inputs=1, n_outputs=0) の default port_shapes。"""
        op = Outport(port_idx=0)
        assert op.port_shapes_in == ((),)
        assert op.port_shapes_out == ()

    def test_all_blocks_are_sm_a_in_simulation(self) -> None:
        """全ブロックを SM-A default で組んだ Simulator は SM-A モード判定になる。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(Constant(value=1.0))
        sim.add(Gain(k=2.0))
        sim.add(Sum(signs="++"))
        sim.add(Scope(n_inputs=1))
        assert sim._is_sm_a_mode() is True


# ---------------------------------------------------------------------------
# _normalize_port_shapes の追加境界値テスト
# ---------------------------------------------------------------------------


class TestNormalizePortShapesBoundary:
    def test_zero_dim_is_allowed(self) -> None:
        """dim=0 は非負なので許容される (shape (0,) = 空配列軸)。"""
        result = _normalize_port_shapes([(0,)], n_ports=1, side="in")
        assert result == ((0,),)

    def test_numpy_integer_dim_is_accepted(self) -> None:
        """numpy integer (np.int64 等) の dim も受け入れる。"""
        result = _normalize_port_shapes([(np.int64(3), np.int32(4))], n_ports=1, side="out")
        assert result == ((3, 4),)

    def test_bool_dim_raises(self) -> None:
        """bool は int のサブクラスだが dim として拒否される。"""
        with pytest.raises(BlockSpecError, match="must be an int"):
            _normalize_port_shapes([(True,)], n_ports=1, side="in")

    def test_single_port_scalar_list(self) -> None:
        """ポート数 1 の scalar shape [()] が正しく正規化される。"""
        result = _normalize_port_shapes([()], n_ports=1, side="in")
        assert result == ((),)

    def test_length_mismatch_error_message_contains_side(self) -> None:
        """エラーメッセージに side 情報が含まれる。"""
        with pytest.raises(BlockSpecError, match="out"):
            _normalize_port_shapes([(), ()], n_ports=3, side="out")
