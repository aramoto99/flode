"""ADR-0026 §(7): SM-B (vector ports) の Jacobian で port shape を C-order flatten。

``Mux`` / ``Demux`` を使ったベクトル port のモデルで、B 列 / C 行の順序が
``port_idx`` 順 + 内部 ravel 順になることを確認する。
"""

from __future__ import annotations

import numpy as np

from pyflw import Simulator, linearize
from pyflw.blocks import Demux, Integrator, Mux, Scope


class TestMuxDemuxRoundtrip:
    """Mux → 3 つの Integrator → Demux → 3 つの Scope。

    SM-B モードで線形化が動作することを確認 (port_shape = (3,))。
    """

    def test_3vec_smb_basic(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        # 3 つの未結線 Integrator → ... → Scope (n=3)
        i1 = sim.add(Integrator(id="i1"))
        i2 = sim.add(Integrator(id="i2"))
        i3 = sim.add(Integrator(id="i3"))
        mux = sim.add(Mux(n=3, id="mx"))
        demux = sim.add(Demux(n=3, id="dx"))
        s1 = sim.add(Scope(id="s1"))
        s2 = sim.add(Scope(id="s2"))
        s3 = sim.add(Scope(id="s3"))
        sim.connect(i1, mux, dst_idx=0)
        sim.connect(i2, mux, dst_idx=1)
        sim.connect(i3, mux, dst_idx=2)
        sim.connect(mux, demux)
        sim.connect(demux, s1, src_idx=0)
        sim.connect(demux, s2, src_idx=1)
        sim.connect(demux, s3, src_idx=2)

        ls = linearize(sim)
        # 連続状態 = 3 つの Integrator
        assert ls.A.shape == (3, 3)
        # 入力 = 3 つの Integrator のスカラー入力 (各 1 次元)
        assert ls.B.shape == (3, 3)
        # 出力 = Demux の 3 出力 (Scope 駆動)
        assert ls.C.shape[0] == 3
        # B は対角 (各 Integrator が独立)
        np.testing.assert_allclose(ls.B, np.eye(3), rtol=1e-4)


class TestVectorPortFlatten:
    """Demux の出力ポート shape は scalar `()` だが、Mux の入力 / 出力で vector port が
    使われる。SM-B 検出が走り、_step_vector パスを通る。"""

    def test_smb_mode_detected(self) -> None:
        sim = Simulator(t_end=1.0, dt=0.01)
        i1 = sim.add(Integrator())
        i2 = sim.add(Integrator())
        mux = sim.add(Mux(n=2))
        demux = sim.add(Demux(n=2))
        s1 = sim.add(Scope())
        s2 = sim.add(Scope())
        sim.connect(i1, mux, dst_idx=0)
        sim.connect(i2, mux, dst_idx=1)
        sim.connect(mux, demux)
        sim.connect(demux, s1, src_idx=0)
        sim.connect(demux, s2, src_idx=1)

        # SM-B モードで動くことを確認 (例外なし、結果が finite)
        ls = linearize(sim)
        assert np.all(np.isfinite(ls.A))
        assert np.all(np.isfinite(ls.B))
        assert np.all(np.isfinite(ls.C))
        assert np.all(np.isfinite(ls.D))
        # 2 状態 (Integrator x2)、2 入力、2 出力
        assert ls.A.shape == (2, 2)
        assert ls.B.shape == (2, 2)
        assert ls.C.shape == (2, 2)
