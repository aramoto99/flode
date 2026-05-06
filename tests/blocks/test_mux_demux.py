"""ADR-0018 §(1) Mux / Demux ブロックの動作検証。

SM-B (vector ports) の最初のユーザー向けブロックとして、scalar n 個 → 1D vector
(n,) 変換、およびその逆変換が正しく動作することを検証する。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from pyflw import Simulator
from pyflw.blocks import Constant, Demux, Mux, Scope, Step
from pyflw.exceptions import BlockSpecError


def _flat(scope: Scope) -> np.ndarray:
    return np.asarray(scope.values).reshape(-1)


# ---------------------------------------------------------------------------
# Mux / Demux 単体動作 (output_v 直接呼び出し)
# ---------------------------------------------------------------------------


class TestMuxStandalone:
    def test_mux_n2_output_shape(self) -> None:
        m = Mux(n=2)
        assert m.port_shapes_in == ((), ())
        assert m.port_shapes_out == ((2,),)
        y = m.output_v(0.0, np.zeros(0), (np.array(1.0), np.array(2.0)))
        assert len(y) == 1
        np.testing.assert_allclose(y[0], np.array([1.0, 2.0]))

    def test_mux_n5_concatenates_in_order(self) -> None:
        m = Mux(n=5)
        u = tuple(np.array(float(i)) for i in range(5))
        y = m.output_v(0.0, np.zeros(0), u)
        np.testing.assert_allclose(y[0], np.array([0.0, 1.0, 2.0, 3.0, 4.0]))

    def test_mux_n1_degenerate(self) -> None:
        """n=1 で 1 scalar → length-1 vector。退化ケース。"""
        m = Mux(n=1)
        assert m.port_shapes_in == ((),)
        assert m.port_shapes_out == ((1,),)
        y = m.output_v(0.0, np.zeros(0), (np.array(7.0),))
        np.testing.assert_allclose(y[0], np.array([7.0]))


class TestDemuxStandalone:
    def test_demux_n2_split(self) -> None:
        d = Demux(n=2)
        assert d.port_shapes_in == ((2,),)
        assert d.port_shapes_out == ((), ())
        ys = d.output_v(0.0, np.zeros(0), (np.array([10.0, 20.0]),))
        assert len(ys) == 2
        np.testing.assert_allclose(ys[0], 10.0)
        np.testing.assert_allclose(ys[1], 20.0)

    def test_demux_n5_split_in_order(self) -> None:
        d = Demux(n=5)
        ys = d.output_v(
            0.0, np.zeros(0), (np.array([0.0, 1.0, 2.0, 3.0, 4.0]),)
        )
        for i, yi in enumerate(ys):
            np.testing.assert_allclose(yi, float(i))


# ---------------------------------------------------------------------------
# Mux → Demux round-trip (end-to-end run via SM-B path)
# ---------------------------------------------------------------------------


class TestMuxDemuxRoundTrip:
    def test_three_scalars_through_mux_demux(self) -> None:
        """Constant×3 → Mux(3) → Demux(3) → Scope×3 で値が保たれる。"""
        sim = Simulator(t_end=0.05, dt=0.01)
        c0 = sim.add(Constant(value=1.0))
        c1 = sim.add(Constant(value=2.0))
        c2 = sim.add(Constant(value=3.0))
        m = sim.add(Mux(n=3))
        d = sim.add(Demux(n=3))
        sc0 = sim.add(Scope(n_inputs=1))
        sc1 = sim.add(Scope(n_inputs=1))
        sc2 = sim.add(Scope(n_inputs=1))
        sim.connect(c0, m, dst_idx=0)
        sim.connect(c1, m, dst_idx=1)
        sim.connect(c2, m, dst_idx=2)
        sim.connect(m, d)
        sim.connect(d, sc0, src_idx=0)
        sim.connect(d, sc1, src_idx=1)
        sim.connect(d, sc2, src_idx=2)
        sim.run()
        np.testing.assert_allclose(_flat(sc0), 1.0 * np.ones(6))
        np.testing.assert_allclose(_flat(sc1), 2.0 * np.ones(6))
        np.testing.assert_allclose(_flat(sc2), 3.0 * np.ones(6))

    def test_time_varying_inputs(self) -> None:
        """Step 入力 ×2 → Mux → Demux → Scope ×2 で時間変化が保たれる。"""
        sim = Simulator(t_end=0.1, dt=0.01)
        s0 = sim.add(Step(initial_value=0.0, final_value=1.0, step_time=0.05))
        s1 = sim.add(Step(initial_value=10.0, final_value=20.0, step_time=0.05))
        m = sim.add(Mux(n=2))
        d = sim.add(Demux(n=2))
        sc0 = sim.add(Scope(n_inputs=1))
        sc1 = sim.add(Scope(n_inputs=1))
        sim.connect(s0, m, dst_idx=0)
        sim.connect(s1, m, dst_idx=1)
        sim.connect(m, d)
        sim.connect(d, sc0, src_idx=0)
        sim.connect(d, sc1, src_idx=1)
        sim.run()
        # Step 出力: t<0.05 は initial_value、t>=0.05 は final_value
        arr0 = _flat(sc0)
        arr1 = _flat(sc1)
        # 一連の time series で前半 / 後半が区別できる
        # (具体時刻インデックスは Step semantics 依存)
        assert arr0[0] == pytest.approx(0.0)  # t=0
        assert arr1[0] == pytest.approx(10.0)
        assert arr0[-1] == pytest.approx(1.0)  # t=0.1 (>step_time)
        assert arr1[-1] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# エラーパス
# ---------------------------------------------------------------------------


class TestMuxDemuxErrors:
    @pytest.mark.parametrize("invalid_n", [0, -1, -100])
    def test_mux_invalid_n_raises(self, invalid_n: int) -> None:
        with pytest.raises(BlockSpecError, match="n must be >= 1"):
            Mux(n=invalid_n)

    @pytest.mark.parametrize("invalid_n", [0, -1, -100])
    def test_demux_invalid_n_raises(self, invalid_n: int) -> None:
        with pytest.raises(BlockSpecError, match="n must be >= 1"):
            Demux(n=invalid_n)

    def test_mux_non_int_n_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="n must be an int"):
            Mux(n=2.5)  # type: ignore[arg-type]

    def test_demux_non_int_n_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="n must be an int"):
            Demux(n="3")  # type: ignore[arg-type]

    def test_mux_bool_n_raises(self) -> None:
        """``True`` は ``int`` のサブクラスだが Mux/Demux では拒否する。"""
        with pytest.raises(BlockSpecError, match="n must be an int"):
            Mux(n=True)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# JSON save / load round-trip
# ---------------------------------------------------------------------------


class TestMuxDemuxPersistence:
    def test_mux_json_roundtrip(self, tmp_path) -> None:
        sim = Simulator(t_end=0.05, dt=0.01)
        for i in range(3):
            sim.add(Constant(value=float(i + 1), id=f"c{i}"))
        sim.add(Mux(n=3, id="mux"))
        sim.connect("c0", "mux", dst_idx=0)
        sim.connect("c1", "mux", dst_idx=1)
        sim.connect("c2", "mux", dst_idx=2)

        path = tmp_path / "mux.flw.json"
        sim.save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        mux_entry = next(b for b in data["blocks"] if b["id"] == "mux")
        assert mux_entry["type"] == "pyflw.blocks.routing.Mux"
        assert mux_entry["params"] == {"n": 3}
        # ADR-0018 §(1): Mux は port_shapes を ``n`` から一意に決めるため JSON に
        # 出力しない (= load 時の二重持ちを回避)
        assert "port_shapes_in" not in mux_entry
        assert "port_shapes_out" not in mux_entry

        # load して動作も検証
        sim2 = Simulator.load(path)
        m2 = sim2.get_block("mux")
        assert m2.n == 3
        assert m2.port_shapes_in == ((), (), ())
        assert m2.port_shapes_out == ((3,),)

    def test_demux_json_roundtrip(self, tmp_path) -> None:
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(Demux(n=4, id="demux"))
        path = tmp_path / "demux.flw.json"
        sim.save(path)
        sim2 = Simulator.load(path)
        d2 = sim2.get_block("demux")
        assert d2.n == 4
        assert d2.port_shapes_in == ((4,),)
        assert d2.port_shapes_out == ((), (), (), ())
