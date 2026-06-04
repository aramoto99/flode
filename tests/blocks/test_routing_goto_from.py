"""SPEC-0003 / ADR-0055 (Amendment 2026-05-19): Goto / From の動作検証。

カバー範囲 (SPEC-0003 §テスト戦略の 11 ケース、Local + Global の 2 visibility):
- 基本 (Local): scalar / vector 透過、複数 From、スコープ独立、跨ぎ未解決
- Global: モデル全体可視、重複
- 解決優先順位: Local > Global
- 共通: dangling 許容、不正 tag、無効 visibility、代数ループ検出、永続化

Note: Scoped + GotoTagVisibility は SPEC-0003 / ADR-0055 Amendment (2026-05-19) で
Phase 2 送り。Phase 2 で `tag_visibility = "scoped"` enum 値と GotoTagVisibility
ブロックを追加方向で後方互換的に復活させる予定。
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from pyflw import Simulator
from pyflw.blocks import (
    Constant,
    From,
    Gain,
    Goto,
    Integrator,
    Mux,
    Scope,
    Sum,
)
from pyflw.exceptions import AlgebraicLoopError, BlockSpecError
from pyflw.subsystems import Inport, Outport, Subsystem


def _flat(scope: Scope) -> np.ndarray:
    return np.asarray(scope.values).reshape(-1)


# ===========================================================================
# 基本 (Local) — 5 件
# ===========================================================================


class TestGotoFromLocal:
    def test_goto_from_scalar_passthrough(self) -> None:
        """scalar 信号が Goto → From で正しく伝わる。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        src = sim.add(Constant(value=3.0))
        goto = sim.add(Goto(tag="signal"))
        sim.connect(src, goto)
        from_blk = sim.add(From(tag="signal"))
        gain = sim.add(Gain(k=2.0))
        scope = sim.add(Scope())
        sim.connect(from_blk, gain)
        sim.connect(gain, scope)
        sim.run()
        np.testing.assert_allclose(_flat(scope), 6.0 * np.ones(6))

    def test_goto_from_vector_passthrough(self) -> None:
        """1D vector (Mux 経由) が Goto → From で透過する (SM-B path)。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        c0 = sim.add(Constant(value=1.0))
        c1 = sim.add(Constant(value=2.0))
        mux = sim.add(Mux(n=2))
        sim.connect(c0, mux, dst_idx=0)
        sim.connect(c1, mux, dst_idx=1)
        goto = sim.add(Goto(tag="bus"))
        sim.connect(mux, goto)
        from_blk = sim.add(From(tag="bus"))
        # vector port を Subsystem 外で扱うため Demux で分解して Scope へ
        from pyflw.blocks import Demux

        demux = sim.add(Demux(n=2))
        scope0 = sim.add(Scope())
        scope1 = sim.add(Scope())
        sim.connect(from_blk, demux)
        sim.connect(demux, scope0, src_idx=0)
        sim.connect(demux, scope1, src_idx=1)
        sim.run()
        np.testing.assert_allclose(_flat(scope0), 1.0 * np.ones(6))
        np.testing.assert_allclose(_flat(scope1), 2.0 * np.ones(6))
        # Goto / From の port_shape が build 後に (2,) で確定していることを確認
        assert goto.port_shapes_in == ((2,),)
        assert from_blk.port_shapes_out == ((2,),)

    def test_multiple_from_for_one_goto(self) -> None:
        """同じ tag の From が複数 OK (1 信号を複数箇所で参照)。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        src = sim.add(Constant(value=5.0))
        goto = sim.add(Goto(tag="x"))
        sim.connect(src, goto)
        scope_a = sim.add(Scope())
        scope_b = sim.add(Scope())
        sim.connect(sim.add(From(tag="x")), scope_a)
        sim.connect(sim.add(From(tag="x")), scope_b)
        sim.run()
        np.testing.assert_allclose(_flat(scope_a), 5.0 * np.ones(6))
        np.testing.assert_allclose(_flat(scope_b), 5.0 * np.ones(6))

    def test_local_scope_isolation(self) -> None:
        """異なる Subsystem 内の同じ Local tag は混ざらない。"""
        # Subsystem A: 内部で Local "x" = 10
        sub_a = Subsystem()
        sub_a.add(Inport(port_idx=0))  # 外部入力なし扱い (dummy)
        out_a = Outport(port_idx=0)
        sub_a.add(out_a)
        c_a = sub_a.add(Constant(value=10.0))
        g_a = sub_a.add(Goto(tag="x", tag_visibility="local"))
        sub_a.connect(c_a, g_a)
        f_a = sub_a.add(From(tag="x"))
        sub_a.connect(f_a, out_a)

        # Subsystem B: 内部で Local "x" = 20 (独立)
        sub_b = Subsystem()
        sub_b.add(Inport(port_idx=0))
        out_b = Outport(port_idx=0)
        sub_b.add(out_b)
        c_b = sub_b.add(Constant(value=20.0))
        g_b = sub_b.add(Goto(tag="x", tag_visibility="local"))
        sub_b.connect(c_b, g_b)
        f_b = sub_b.add(From(tag="x"))
        sub_b.connect(f_b, out_b)

        sim = Simulator(t_end=0.05, dt=0.01)
        dummy = sim.add(Constant(value=0.0))
        sim.add(sub_a)
        sim.add(sub_b)
        sim.connect(dummy, sub_a)
        sim.connect(dummy, sub_b)
        scope_a = sim.add(Scope())
        scope_b = sim.add(Scope())
        sim.connect(sub_a, scope_a)
        sim.connect(sub_b, scope_b)
        sim.run()
        np.testing.assert_allclose(_flat(scope_a), 10.0 * np.ones(6))
        np.testing.assert_allclose(_flat(scope_b), 20.0 * np.ones(6))

    def test_cross_subsystem_local_unresolved(self) -> None:
        """Subsystem 内の Local Goto + 外側 From は BlockSpecError。"""
        sub = Subsystem()
        sub.add(Inport(port_idx=0))
        out = Outport(port_idx=0)
        sub.add(out)
        c = sub.add(Constant(value=1.0))
        g = sub.add(Goto(tag="hidden", tag_visibility="local"))
        sub.connect(c, g)
        sub.connect(c, out)

        sim = Simulator(t_end=0.05, dt=0.01)
        dummy = sim.add(Constant(value=0.0))
        sim.add(sub)
        sim.connect(dummy, sub)
        # 外側に From("hidden") を置く → Local では見えない
        from_blk = sim.add(From(tag="hidden"))
        scope = sim.add(Scope())
        sim.connect(from_blk, scope)
        with pytest.raises(BlockSpecError, match="no matching Goto"):
            sim.run()


# ===========================================================================
# Global — 2 件
# ===========================================================================


class TestGotoFromGlobal:
    def test_global_goto_resolved_anywhere(self) -> None:
        """任意の Subsystem 内 From から Global Goto が見える。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        src = sim.add(Constant(value=42.0))
        goto = sim.add(Goto(tag="clock", tag_visibility="global"))
        sim.connect(src, goto)

        sub = Subsystem()
        sub.add(Inport(port_idx=0))
        out = Outport(port_idx=0)
        sub.add(out)
        f = sub.add(From(tag="clock"))
        sub.connect(f, out)

        dummy = sim.add(Constant(value=0.0))
        sim.add(sub)
        sim.connect(dummy, sub)
        scope = sim.add(Scope())
        sim.connect(sub, scope)
        sim.run()
        np.testing.assert_allclose(_flat(scope), 42.0 * np.ones(6))

    def test_duplicate_global_goto_raises(self) -> None:
        """モデル全体で同じ tag の Global Goto が複数 → BlockSpecError。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        c1 = sim.add(Constant(value=1.0))
        c2 = sim.add(Constant(value=2.0))
        g1 = sim.add(Goto(tag="dup_g", tag_visibility="global"))
        g2 = sim.add(Goto(tag="dup_g", tag_visibility="global"))
        sim.connect(c1, g1)
        sim.connect(c2, g2)
        f = sim.add(From(tag="dup_g"))
        sim.connect(f, sim.add(Scope()))
        with pytest.raises(BlockSpecError, match="duplicate Global Goto"):
            sim.run()


# ===========================================================================
# 解決優先順位 — 1 件
# ===========================================================================


class TestResolutionPriority:
    def test_resolution_priority_local_over_global(self, caplog: pytest.LogCaptureFixture) -> None:
        """同一 tag で Local と Global 並存 → Local が優先 + WARNING ログ。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        c_local = sim.add(Constant(value=100.0))
        c_global = sim.add(Constant(value=200.0))
        g_local = sim.add(Goto(tag="t", tag_visibility="local"))
        g_global = sim.add(Goto(tag="t", tag_visibility="global"))
        sim.connect(c_local, g_local)
        sim.connect(c_global, g_global)
        f = sim.add(From(tag="t"))
        scope = sim.add(Scope())
        sim.connect(f, scope)
        with caplog.at_level(logging.WARNING, logger="pyflw.routing.goto"):
            sim.run()
        np.testing.assert_allclose(_flat(scope), 100.0 * np.ones(6))
        assert any("Local and Global" in r.message for r in caplog.records)


# ===========================================================================
# 共通 — 残り
# ===========================================================================


class TestGotoFromCommon:
    def test_dangling_goto_is_allowed(self, caplog: pytest.LogCaptureFixture) -> None:
        """対応する From が無くてもエラーにならない (INFO ログのみ)。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        src = sim.add(Constant(value=1.0))
        sim.connect(src, sim.add(Goto(tag="orphan_g")))
        # 何も From を置かない
        sim.connect(src, sim.add(Scope()))
        with caplog.at_level(logging.INFO, logger="pyflw.routing.goto"):
            sim.run()
        assert any("dangling Goto" in r.message for r in caplog.records)

    def test_unresolved_from_raises(self) -> None:
        """どこからも解決できない From → BlockSpecError。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        f = sim.add(From(tag="missing"))
        sim.connect(f, sim.add(Scope()))
        with pytest.raises(BlockSpecError, match="no matching Goto"):
            sim.run()

    @pytest.mark.parametrize(
        "bad_tag",
        [
            "",  # 空文字
            "日本語",  # 非 ASCII
            "x" * 65,  # 65 文字 (上限超)
            "with space",  # 空白
            "tag.name",  # ドット (許容外)
            "tag/name",  # スラッシュ
            "tag$",  # 記号
        ],
    )
    def test_invalid_tag_chars(self, bad_tag: str) -> None:
        """不正な tag 文字 → BlockSpecError (Goto / From 両方)。"""
        with pytest.raises(BlockSpecError, match="invalid tag name"):
            Goto(tag=bad_tag)
        with pytest.raises(BlockSpecError, match="invalid tag name"):
            From(tag=bad_tag)

    def test_invalid_tag_visibility_raises(self) -> None:
        """tag_visibility が 2 値以外 → BlockSpecError (Scoped も含めて拒否)。"""
        with pytest.raises(BlockSpecError, match="invalid tag_visibility"):
            Goto(tag="x", tag_visibility="invalid")
        # SPEC-0003 / ADR-0055 Amendment: "scoped" は Phase 2 送り。
        # MVP では拒否する (= Phase 2 で復活時に "scoped" が有効になる)。
        with pytest.raises(BlockSpecError, match="invalid tag_visibility"):
            Goto(tag="x", tag_visibility="scoped")

    def test_algebraic_loop_via_goto_from(self) -> None:
        """Goto → 同 tag From → 同期ブロック → Goto の代数ループを検出。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        # ループ: Sum → Goto("loop") → From("loop") → Gain → Sum (代数ループ)
        sum_blk = sim.add(Sum())
        goto = sim.add(Goto(tag="loop"))
        sim.connect(sum_blk, goto)
        from_blk = sim.add(From(tag="loop"))
        gain = sim.add(Gain(k=0.5))
        sim.connect(from_blk, gain)
        sim.connect(gain, sum_blk, dst_idx=0)
        # Sum の dst_idx=1 にも何か接続が必要
        src = sim.add(Constant(value=1.0))
        sim.connect(src, sum_blk, dst_idx=1)
        with pytest.raises(AlgebraicLoopError):
            sim.run()

    def test_algebraic_loop_across_subsystem_via_global(self) -> None:
        """Subsystem 跨ぎの Global Goto/From 代数ループも検出。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        # 外側: Sum → Goto(global) → ... → From(global) (内部) → Outport → Sum (loop)
        sum_blk = sim.add(Sum())
        goto = sim.add(Goto(tag="g_loop", tag_visibility="global"))
        sim.connect(sum_blk, goto)

        sub = Subsystem()
        sub.add(Inport(port_idx=0))
        out = Outport(port_idx=0)
        sub.add(out)
        f = sub.add(From(tag="g_loop"))
        # 内部で direct_feedthrough チェーンを作る
        gain = sub.add(Gain(k=0.5))
        sub.connect(f, gain)
        sub.connect(gain, out)

        dummy = sim.add(Constant(value=0.0))
        sim.add(sub)
        sim.connect(dummy, sub)
        sim.connect(sub, sum_blk, dst_idx=0)
        src = sim.add(Constant(value=1.0))
        sim.connect(src, sum_blk, dst_idx=1)
        with pytest.raises(AlgebraicLoopError):
            sim.run()

    def test_no_goto_from_numerical_invariance(self) -> None:
        """Goto/From を含まないモデルは found_any 早期 return → 数値不変。

        振る舞いは「解析解と一致 (= 既存パスと同じ数値結果)」で十分検証できる。
        ``_virtual_deps_top`` 等の内部実装 attr への assertion は脆弱なので避ける
        (code-reviewer SHOULD 2026-05-19)。
        """
        # spring_mass_damper を簡略再現 (Constant → Integrator → Scope)
        sim = Simulator(t_end=0.05, dt=0.01)
        src = sim.add(Constant(value=1.0))
        integ = sim.add(Integrator())
        scope = sim.add(Scope())
        sim.connect(src, integ)
        sim.connect(integ, scope)
        sim.run()
        # 解析解: y = t (積分結果)、t = 0, 0.01, ..., 0.05 で値 0, 0.01, ..., 0.05
        expected = np.arange(6) * 0.01
        np.testing.assert_allclose(_flat(scope), expected, atol=1e-7)


# ===========================================================================
# 永続化 (JSON round-trip) — SPEC-0003 §6
# ===========================================================================


class TestGotoFromPersistence:
    def test_save_load_round_trip(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Goto / From を含むモデルが save/load で再現する。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        src = sim.add(Constant(value=4.0))
        goto = sim.add(Goto(tag="rt", tag_visibility="global"))
        sim.connect(src, goto)
        f = sim.add(From(tag="rt"))
        scope = sim.add(Scope())
        sim.connect(f, scope)

        path = tmp_path / "goto_from.flw.json"
        sim.save(path)

        sim2 = Simulator.load(path)
        # 復元したモデルで run、Goto/From の解決が再度走る
        sim2.run()
        scope2 = next(b for b in sim2.blocks if isinstance(b, Scope))
        np.testing.assert_allclose(_flat(scope2), 4.0 * np.ones(6))
