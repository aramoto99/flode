"""ADR-0017 (信号モデル SM-B、ベクトルポート) の動作検証。

SM-A (全ポート shape = ``()``) で既存ブロックが不変動作することと、SM-B
(任意 shape ndarray) でブロックを定義できること、宣言 shape の不一致が build 時に
信号面解決器 (ADR-0079) の ``SignalShapeError`` で検出されることを検証する。

Phase 3 #3 (本 ADR) では Block 拡張・shape check・``output_v`` wrapper まで実装。
SM-B モードでの ``run()`` 実行は Phase 3 #4 (Mux/Demux + run path 統合) で完成。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from flode import Simulator
from flode.blocks import Constant, Gain, Scope, TransferFunction
from flode.core.block import Block, _normalize_port_shapes
from flode.core.signals import resolve_for_execution
from flode.exceptions import BlockSpecError, SignalShapeError

# ---------------------------------------------------------------------------
# _normalize_port_shapes ヘルパー
# ---------------------------------------------------------------------------


class TestNormalizePortShapes:
    def test_none_returns_all_scalar_shapes(self) -> None:
        """``None`` -> 全 ``()`` (= SM-A 互換)。"""
        result = _normalize_port_shapes(None, n_ports=3, side="in")
        assert result == ((), (), ())

    def test_explicit_scalar_shapes(self) -> None:
        result = _normalize_port_shapes([(), (), ()], n_ports=3, side="in")
        assert result == ((), (), ())

    def test_vector_shapes(self) -> None:
        result = _normalize_port_shapes([(3,), (5,)], n_ports=2, side="in")
        assert result == ((3,), (5,))

    def test_higher_rank_shapes(self) -> None:
        result = _normalize_port_shapes([(3, 4), ()], n_ports=2, side="in")
        assert result == ((3, 4), ())

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="length 2 does not match"):
            _normalize_port_shapes([(), ()], n_ports=3, side="in")

    def test_negative_dim_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="must be non-negative"):
            _normalize_port_shapes([(-1,)], n_ports=1, side="out")

    def test_non_int_dim_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="must be an int"):
            _normalize_port_shapes([(3.5,)], n_ports=1, side="in")

    def test_non_sequence_input_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="must be a sequence of shapes"):
            _normalize_port_shapes("not_a_list", n_ports=1, side="in")

    def test_non_sequence_shape_element_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="must be a tuple of ints"):
            _normalize_port_shapes(["not_a_tuple"], n_ports=1, side="out")


# ---------------------------------------------------------------------------
# Block 既存サブクラスの SM-A 互換性
# ---------------------------------------------------------------------------


class TestSmACompat:
    def test_default_block_has_scalar_port_shapes(self) -> None:
        """``Constant`` 等の既存ブロックは default で全 ``()``。"""
        c = Constant(value=1.0)
        assert c.port_shapes_in == ()
        assert c.port_shapes_out == ((),)

    def test_existing_chain_works_unchanged(self) -> None:
        """SM-A only モデルでは ``run()`` の既存挙動を維持。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        c = sim.add(Constant(value=2.0))
        g = sim.add(Gain(k=3.0))
        sc = sim.add(Scope(n_inputs=1))
        sim.connect(c, g)
        sim.connect(g, sc)
        sim.run()
        arr = np.asarray(sc.values).reshape(-1)
        np.testing.assert_allclose(arr, 6.0 * np.ones_like(arr))


# ---------------------------------------------------------------------------
# Build-time port shape check (ADR-0017 §(4))
# ---------------------------------------------------------------------------


class _ScalarSrc(Block):
    """SM-A: scalar 出力ブロック (テスト用)。"""

    def __init__(self) -> None:
        super().__init__(n_inputs=0, n_outputs=1)

    def output(self, t, x, u):  # type: ignore[no-untyped-def]
        return np.array([1.0])


class _VectorSink(Block):
    """SM-B: shape (3,) の入力を受け取るブロック (テスト用)。"""

    def __init__(self) -> None:
        super().__init__(
            n_inputs=1,
            n_outputs=0,
            port_shapes_in=[(3,)],
        )

    def output_v(self, t, x, u):  # type: ignore[no-untyped-def]
        return ()


class _VectorSrc(Block):
    """SM-B: shape (3,) の出力を生成するブロック (テスト用)。"""

    def __init__(self) -> None:
        super().__init__(
            n_inputs=0,
            n_outputs=1,
            port_shapes_out=[(3,)],
        )

    def output_v(self, t, x, u):  # type: ignore[no-untyped-def]
        return (np.array([1.0, 2.0, 3.0]),)


class TestPortShapeMismatch:
    """ADR-0079 D-11: 宣言 shape と上流 shape の不一致は信号面解決器が build 時
    (``run()`` / ``resolve_for_execution``) に ``SignalShapeError`` (BlockSpecError の
    サブクラス、code ``shape.mismatch``) で拒否する。"""

    def test_scalar_to_vector_mismatch_raises(self) -> None:
        sim = Simulator(t_end=0.1, dt=0.01)
        src = sim.add(_ScalarSrc())
        sink = sim.add(_VectorSink())
        sim.connect(src, sink)
        with pytest.raises(SignalShapeError, match="shape.mismatch") as ei:
            sim.run()
        assert ei.value.expected_shape == (3,)
        assert ei.value.actual_shape == ()

    def test_error_message_suggests_mux_demux(self) -> None:
        sim = Simulator(t_end=0.1, dt=0.01)
        src = sim.add(_ScalarSrc())
        sink = sim.add(_VectorSink())
        sim.connect(src, sink)
        with pytest.raises(BlockSpecError, match="Mux/Demux"):
            sim.run()

    def test_vector_to_scalar_mismatch_raises(self) -> None:
        sim = Simulator(t_end=0.1, dt=0.01)
        vsrc = sim.add(_VectorSrc())
        # TransferFunction は SISO のまま scalar 入力を宣言 (ADR-0079 D-10)
        integ = sim.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0]))
        sim.connect(vsrc, integ)
        with pytest.raises(SignalShapeError, match="shape.mismatch"):
            sim.run()

    def test_matching_vector_to_vector_passes(self) -> None:
        """SM-B 同 shape 接続では shape check が通る。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        vsrc = sim.add(_VectorSrc())
        vsink = sim.add(_VectorSink())
        sim.connect(vsrc, vsink)
        # 例外を出さずに完走することを確認
        resolve_for_execution(sim)


# ---------------------------------------------------------------------------
# output_v default wrapper (ADR-0017 §(8) U1)
# ---------------------------------------------------------------------------


class TestOutputVWrapper:
    def test_sm_a_block_output_v_via_default_wrapper(self) -> None:
        """SM-A ブロックの ``output_v`` default 実装が ``output`` を正しく wrap する。"""
        g = Gain(k=2.0)
        # SM-A: u は rank-0 ndarray のタプル、戻り値も rank-0 ndarray のタプル
        u_tuple = (np.array(3.0),)
        x = np.zeros(0)
        y = g.output_v(0.0, x, u_tuple)
        assert isinstance(y, tuple)
        assert len(y) == 1
        np.testing.assert_allclose(y[0], 6.0)

    def test_dual_implementation_is_rejected(self) -> None:
        """``output`` と ``output_v`` 両方を override するクラスは ``__init__`` で拒否。"""

        class _BothOutputs(Block):
            def __init__(self) -> None:
                super().__init__(n_inputs=1, n_outputs=1)

            def output(self, t, x, u):  # type: ignore[no-untyped-def]
                return np.array([0.0])

            def output_v(self, t, x, u):  # type: ignore[no-untyped-def]
                return (np.array(0.0),)

        with pytest.raises(BlockSpecError, match="must override either"):
            _BothOutputs()


# ---------------------------------------------------------------------------
# SM-B run path (ADR-0018 で解禁、test_sm_b_run.py で end-to-end 検証)
# ---------------------------------------------------------------------------


class TestSmBRunEnabled:
    def test_sm_b_run_completes_without_error(self) -> None:
        """ADR-0018 §(2) で SM-B run path が解禁された (Phase 3 #4 完了)。

        VectorSrc → VectorSink の最小 SM-B モデルが ``run()`` を例外なく完走する。
        詳細な end-to-end 動作は ``tests/core/test_sm_b_run.py`` でカバー。
        """
        sim = Simulator(t_end=0.05, dt=0.01)
        vsrc = sim.add(_VectorSrc())
        vsink = sim.add(_VectorSink())
        sim.connect(vsrc, vsink)
        sim.run()  # 例外を投げず完走することのみ検証


# ---------------------------------------------------------------------------
# JSON schema 0.3 → 0.4 migration (ADR-0017 §(7))
# ---------------------------------------------------------------------------


class TestSchema04Migration:
    def test_save_uses_current_schema(self, tmp_path) -> None:
        # ADR-0036: schema bump 0.6 → 0.7 (RateTransition 追加)
        from flode.core.persistence import CURRENT_SCHEMA_VERSION

        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(Constant(value=1.0, id="src"))
        path = tmp_path / "sm_a.flw.json"
        sim.save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == CURRENT_SCHEMA_VERSION

    def test_load_legacy_0_3_via_migration(self, tmp_path) -> None:
        """0.3 で保存されたファイルが migration 経由で読める (port_shapes 未設定でも SM-A 互換)。"""
        path = tmp_path / "legacy_0_3.flw.json"
        legacy = {
            "schema_version": "0.3",
            "metadata": {"created_at": "2026-05-06T00:00:00Z", "tool": "flode 0.3.0"},
            "simulator": {
                "t_end": 0.05,
                "dt": 0.01,
                "solver": "RK45",
                "rtol": 1e-6,
                "atol": 1e-9,
                "dt_base": None,
            },
            "blocks": [
                {"id": "src", "type": "flode.blocks.sources.Constant", "params": {"value": 5.0}},
                {"id": "g", "type": "flode.blocks.mathops.Gain", "params": {"k": 2.0}},
                {"id": "sc", "type": "flode.blocks.sinks.Scope", "params": {"n_inputs": 1}},
            ],
            "connections": [
                {"src": "src", "src_idx": 0, "dst": "g", "dst_idx": 0},
                {"src": "g", "src_idx": 0, "dst": "sc", "dst_idx": 0},
            ],
        }
        path.write_text(json.dumps(legacy), encoding="utf-8")
        sim = Simulator.load(path)
        sim.run()
        sc = sim.get_block("sc")
        arr = np.asarray(sc.values).reshape(-1)
        np.testing.assert_allclose(arr, 10.0 * np.ones_like(arr))

    def test_load_legacy_0_2_chains_through_0_3_to_0_4(self, tmp_path) -> None:
        """0.2 → 0.3 → 0.4 の chain migration が動く。"""
        path = tmp_path / "legacy_0_2.flw.json"
        legacy = {
            "schema_version": "0.2",
            "simulator": {
                "t_end": 0.05,
                "dt": 0.01,
                "solver": "RK45",
                "rtol": 1e-6,
                "atol": 1e-9,
                "dt_base": None,
            },
            "blocks": [
                {"id": "src", "type": "flode.blocks.sources.Constant", "params": {"value": 1.0}},
            ],
            "connections": [],
        }
        path.write_text(json.dumps(legacy), encoding="utf-8")
        sim = Simulator.load(path)
        # 例外なく load できれば OK
        assert sim.get_block("src") is not None
