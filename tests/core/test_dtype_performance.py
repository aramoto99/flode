"""SPEC-0028 Q13 / 非機能要件: dtype モデルの解決・実行性能。

SM-A / SM-B の性能比は **計測してログに出すのみで assert しない** (Q13 —
CI ゲートにするとマシン差でフレークするため。記録は ADR-0077 Amendment へ)。
"""

from __future__ import annotations

import logging
import time

from flode import Simulator
from flode.blocks.cast import Cast
from flode.blocks.mathops import Gain, Sum
from flode.blocks.sources import Constant
from flode.core.dtypes import resolve_dtypes

logger = logging.getLogger(__name__)


def _chain_model(n_blocks: int, *, declare: bool) -> Simulator:
    sim = Simulator(t_end=0.05, dt=0.01)
    prev = sim.add(
        Constant(value=1, dtype="int64", id="c0")
        if declare
        else Constant(value=1.0, id="c0")
    )
    for i in range(n_blocks - 1):
        s = sim.add(Sum(signs="+", id=f"s{i}"))
        sim.connect(prev, s)
        prev = s
    return sim


class TestResolvePerformance:
    def test_1000_block_dtype_model_resolves_within_budget(self) -> None:
        sim = _chain_model(1000, declare=True)
        start = time.perf_counter()
        res = resolve_dtypes(sim, mode="full")
        elapsed = time.perf_counter() - start
        assert res.summary.unresolved == 0
        # SPEC-0027 の 100ms 目標を維持 (CI ばらつき込みで 5 倍の上限)
        assert elapsed < 0.5, f"resolve took {elapsed:.3f}s"

    def test_sm_a_vs_sm_b_ratio_is_measured_and_logged_only(self) -> None:
        # Q13: 同一規模のモデルを SM-A (未宣言) / SM-B (宣言) で走らせて比を記録
        n = 200
        sim_a = _chain_model(n, declare=False)
        start = time.perf_counter()
        sim_a.run()
        t_a = time.perf_counter() - start

        sim_b = _chain_model(n, declare=True)
        sim_b.add(Cast(dtype="float64", id="marker"))
        start = time.perf_counter()
        sim_b.run()
        t_b = time.perf_counter() - start

        ratio = t_b / t_a if t_a > 0 else float("inf")
        logger.info(
            "SM-D Q13 measurement: n=%d sm_a=%.4fs sm_b(dtype)=%.4fs ratio=%.2f",
            n,
            t_a,
            t_b,
            ratio,
        )
        # assert しない (Q13)。走り切ることだけ確認
        assert t_a > 0 and t_b > 0

    def test_gain_chain_undeclared_still_fast(self) -> None:
        # 参考: 未宣言 1000 ブロック (SM-A) の解決は呼ばれもしない
        sim = Simulator(t_end=0.05, dt=0.01)
        prev = sim.add(Constant(value=1.0, id="c0"))
        for i in range(999):
            g = sim.add(Gain(k=1.0, id=f"g{i}"))
            sim.connect(prev, g)
            prev = g
        start = time.perf_counter()
        sim.run()
        elapsed = time.perf_counter() - start
        assert elapsed < 5.0
