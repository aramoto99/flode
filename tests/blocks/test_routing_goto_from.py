"""SPEC-0003 / ADR-0055: Goto / From / GotoTagVisibility の動作検証。

カバー範囲 (SPEC-0003 §テスト戦略の 18 ケース):
- 基本 (Local): scalar / vector 透過、複数 From、スコープ独立、跨ぎ未解決
- Scoped: 境界内解決、境界外不可視、Visibility 無しの fallback、shadowing、重複
- Global: モデル全体可視、重複
- 解決優先順位: Local > Scoped > Global
- 共通: dangling 許容、不正 tag、無効 visibility、代数ループ検出
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
    GotoTagVisibility,
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
# Scoped — 5 件
# ===========================================================================


class TestGotoFromScoped:
    def test_scoped_goto_resolved_within_boundary(self) -> None:
        """GotoTagVisibility 配下で Scoped Goto / From が解決される。"""
        # ルートに GotoTagVisibility("ref") を置いて境界宣言
        # ルートに Scoped Goto("ref") を置く
        # Subsystem 内の From("ref") から参照
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(GotoTagVisibility(tag="ref"))
        src = sim.add(Constant(value=7.0))
        goto = sim.add(Goto(tag="ref", tag_visibility="scoped"))
        sim.connect(src, goto)

        sub = Subsystem()
        sub.add(Inport(port_idx=0))
        out = Outport(port_idx=0)
        sub.add(out)
        f = sub.add(From(tag="ref"))
        sub.connect(f, out)

        dummy = sim.add(Constant(value=0.0))
        sim.add(sub)
        sim.connect(dummy, sub)
        scope = sim.add(Scope())
        sim.connect(sub, scope)
        sim.run()
        np.testing.assert_allclose(_flat(scope), 7.0 * np.ones(6))

    def test_scoped_goto_not_visible_outside_boundary(self) -> None:
        """境界外の From からは Scoped Goto が見えない (= 解決不能で BlockSpecError)。"""
        # Subsystem 内に GotoTagVisibility と Scoped Goto を置く
        sub = Subsystem()
        sub.add(Inport(port_idx=0))
        out = Outport(port_idx=0)
        sub.add(out)
        sub.add(GotoTagVisibility(tag="secret"))
        c = sub.add(Constant(value=99.0))
        g = sub.add(Goto(tag="secret", tag_visibility="scoped"))
        sub.connect(c, g)
        sub.connect(c, out)

        sim = Simulator(t_end=0.05, dt=0.01)
        dummy = sim.add(Constant(value=0.0))
        sim.add(sub)
        sim.connect(dummy, sub)
        # 外側に From("secret") を置く → 境界外なので見えない
        from_blk = sim.add(From(tag="secret"))
        scope = sim.add(Scope())
        sim.connect(from_blk, scope)
        with pytest.raises(BlockSpecError, match="no matching Goto"):
            sim.run()

    def test_scoped_without_visibility_falls_back(self) -> None:
        """GotoTagVisibility 無しの Scoped Goto は Global なし → 解決不能。

        SPEC §エッジケース: 境界が無ければ Scoped Goto は Local 相当の
        解決にフォールバックするが、本テストでは Local 解決もできないため
        最終的に BlockSpecError。
        """
        sim = Simulator(t_end=0.05, dt=0.01)
        src = sim.add(Constant(value=1.0))
        # GotoTagVisibility 無し
        goto = sim.add(Goto(tag="orphan", tag_visibility="scoped"))
        sim.connect(src, goto)
        # 別 Subsystem から参照
        sub = Subsystem()
        sub.add(Inport(port_idx=0))
        out = Outport(port_idx=0)
        sub.add(out)
        f = sub.add(From(tag="orphan"))
        sub.connect(f, out)

        dummy = sim.add(Constant(value=0.0))
        sim.add(sub)
        sim.connect(dummy, sub)
        scope = sim.add(Scope())
        sim.connect(sub, scope)
        with pytest.raises(BlockSpecError, match="no matching Goto"):
            sim.run()

    def test_nested_visibility_boundary_shadowing(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """親と子の GotoTagVisibility(同 tag) で子の境界が優先 + WARNING ログ。"""
        # 構造:
        #   Sim (root) に GotoTagVisibility("v") + Scoped Goto("v")=100
        #   Sub_outer に GotoTagVisibility("v") + Scoped Goto("v")=200
        #     Sub_inner に From("v") → 子の境界 (Sub_outer の Scoped Goto) が見える
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(GotoTagVisibility(tag="v"))
        c_root = sim.add(Constant(value=100.0))
        g_root = sim.add(Goto(tag="v", tag_visibility="scoped"))
        sim.connect(c_root, g_root)

        sub_inner = Subsystem(id="sub_inner")
        sub_inner.add(Inport(port_idx=0))
        out_inner = Outport(port_idx=0)
        sub_inner.add(out_inner)
        f_inner = sub_inner.add(From(tag="v"))
        sub_inner.connect(f_inner, out_inner)

        sub_outer = Subsystem(id="sub_outer")
        sub_outer.add(Inport(port_idx=0))
        out_outer = Outport(port_idx=0)
        sub_outer.add(out_outer)
        sub_outer.add(GotoTagVisibility(tag="v"))
        c_outer = sub_outer.add(Constant(value=200.0))
        g_outer = sub_outer.add(Goto(tag="v", tag_visibility="scoped"))
        sub_outer.connect(c_outer, g_outer)
        sub_outer.add(sub_inner)
        sub_outer.connect(sub_outer._inner_blocks[0], sub_inner)  # Inport → sub_inner
        sub_outer.connect(sub_inner, out_outer)

        dummy = sim.add(Constant(value=0.0))
        sim.add(sub_outer)
        sim.connect(dummy, sub_outer)
        scope = sim.add(Scope())
        sim.connect(sub_outer, scope)

        with caplog.at_level(logging.WARNING, logger="pyflw.routing.goto"):
            sim.run()
        # 子の境界が優先 = sub_outer の Goto=200 が見える
        np.testing.assert_allclose(_flat(scope), 200.0 * np.ones(6))
        # shadowing WARNING が出ているか
        assert any("shadows ancestor" in r.message for r in caplog.records)

    def test_duplicate_scoped_goto_within_boundary_raises(self) -> None:
        """同一スコープ内の重複 Scoped Goto → BlockSpecError。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(GotoTagVisibility(tag="dup"))
        c1 = sim.add(Constant(value=1.0))
        c2 = sim.add(Constant(value=2.0))
        g1 = sim.add(Goto(tag="dup", tag_visibility="scoped"))
        g2 = sim.add(Goto(tag="dup", tag_visibility="scoped"))
        sim.connect(c1, g1)
        sim.connect(c2, g2)
        f = sim.add(From(tag="dup"))
        scope = sim.add(Scope())
        sim.connect(f, scope)
        with pytest.raises(BlockSpecError, match="duplicate Scoped Goto"):
            sim.run()

    def test_duplicate_scoped_goto_in_different_child_scopes_raises(self) -> None:
        """境界階層内の異なる子スコープに Scoped Goto 2 つ → BlockSpecError。

        SPEC-0003 §3-2: 「同一階層 (境界 Subsystem) 内の Scoped Goto 重複」は
        子スコープ間でも検出されるべき (= dict 順序での非決定的解決を防ぐ)。
        """
        # root に GotoTagVisibility("shared") を置いて境界宣言
        # sub_a に Scoped Goto("shared") = 100、sub_b にも Scoped Goto("shared") = 200
        # → 境界 (= root) 配下に 2 つあるため重複 → BlockSpecError

        sub_a = Subsystem(id="sub_a")
        sub_a.add(Inport(port_idx=0))
        out_a = Outport(port_idx=0)
        sub_a.add(out_a)
        c_a = sub_a.add(Constant(value=100.0))
        g_a = sub_a.add(Goto(tag="shared", tag_visibility="scoped"))
        sub_a.connect(c_a, g_a)
        sub_a.connect(c_a, out_a)

        sub_b = Subsystem(id="sub_b")
        sub_b.add(Inport(port_idx=0))
        out_b = Outport(port_idx=0)
        sub_b.add(out_b)
        c_b = sub_b.add(Constant(value=200.0))
        g_b = sub_b.add(Goto(tag="shared", tag_visibility="scoped"))
        sub_b.connect(c_b, g_b)
        sub_b.connect(c_b, out_b)

        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(GotoTagVisibility(tag="shared"))
        dummy = sim.add(Constant(value=0.0))
        sim.add(sub_a)
        sim.add(sub_b)
        sim.connect(dummy, sub_a)
        sim.connect(dummy, sub_b)
        # 同境界内のどこかに From があると解決が走るので追加
        sim.connect(sub_a, sim.add(Scope()))
        sim.connect(sub_b, sim.add(Scope()))
        f = sim.add(From(tag="shared"))
        sim.connect(f, sim.add(Scope()))
        with pytest.raises(
            BlockSpecError, match="duplicate Scoped Goto.*visibility boundary"
        ):
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
# 解決優先順位 — 2 件
# ===========================================================================


class TestResolutionPriority:
    def test_resolution_priority_local_over_global(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
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
        assert any(
            "Local and Global" in r.message for r in caplog.records
        )

    def test_resolution_priority_scoped_over_global(self) -> None:
        """Scoped が Global より優先される。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        # Global
        c_g = sim.add(Constant(value=999.0))
        g_g = sim.add(Goto(tag="p", tag_visibility="global"))
        sim.connect(c_g, g_g)
        # Scoped + GotoTagVisibility (root スコープ)
        sim.add(GotoTagVisibility(tag="p"))
        c_s = sim.add(Constant(value=77.0))
        g_s = sim.add(Goto(tag="p", tag_visibility="scoped"))
        sim.connect(c_s, g_s)
        f = sim.add(From(tag="p"))
        scope = sim.add(Scope())
        sim.connect(f, scope)
        sim.run()
        np.testing.assert_allclose(_flat(scope), 77.0 * np.ones(6))


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

    def test_dangling_visibility_is_allowed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """対応する Scoped Goto が無い GotoTagVisibility も許容。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(GotoTagVisibility(tag="unused_v"))
        src = sim.add(Constant(value=1.0))
        sim.connect(src, sim.add(Scope()))
        with caplog.at_level(logging.INFO, logger="pyflw.routing.goto"):
            sim.run()
        assert any(
            "dangling GotoTagVisibility" in r.message for r in caplog.records
        )

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
        """不正な tag 文字 → BlockSpecError (Goto/From/Visibility 全部)。"""
        with pytest.raises(BlockSpecError, match="invalid tag name"):
            Goto(tag=bad_tag)
        with pytest.raises(BlockSpecError, match="invalid tag name"):
            From(tag=bad_tag)
        with pytest.raises(BlockSpecError, match="invalid tag name"):
            GotoTagVisibility(tag=bad_tag)

    def test_invalid_tag_visibility_raises(self) -> None:
        """tag_visibility が 3 値以外 → BlockSpecError。"""
        with pytest.raises(BlockSpecError, match="invalid tag_visibility"):
            Goto(tag="x", tag_visibility="invalid")

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
        """Goto/From を含まないモデルは _has_goto_from() で early return → 数値不変。"""
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
        # _virtual_deps_top も空のまま
        assert sim._virtual_deps_top == set()


# ===========================================================================
# 永続化 (JSON round-trip) — SPEC-0003 §6
# ===========================================================================


class TestGotoFromPersistence:
    def test_save_load_round_trip(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Goto/From/GotoTagVisibility を含むモデルが save/load で再現する。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        src = sim.add(Constant(value=4.0))
        goto = sim.add(Goto(tag="rt", tag_visibility="global"))
        sim.connect(src, goto)
        f = sim.add(From(tag="rt"))
        sim.add(GotoTagVisibility(tag="v_rt"))
        scope = sim.add(Scope())
        sim.connect(f, scope)

        path = tmp_path / "goto_from.flw.json"
        sim.save(path)

        sim2 = Simulator.load(path)
        # 復元したモデルで run、Goto/From の解決が再度走る
        sim2.run()
        scope2 = next(b for b in sim2.blocks if isinstance(b, Scope))
        np.testing.assert_allclose(_flat(scope2), 4.0 * np.ones(6))
