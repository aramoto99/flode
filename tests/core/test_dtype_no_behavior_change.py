"""SPEC-0028 AC-1: dtype 未宣言モデルの完全不変 (Stage 1 追加分)。

Stage 0 の `test_dtypes_no_behavior_change.py` (無変更で共存) を補強する:
経路 assert (SM-A path 維持 / 解決器不呼び出し) と
「全 float64 宣言の SM-B 実行 == SM-A 実行」の同値性。
"""

from __future__ import annotations

from unittest import mock

import numpy as np

from flode import Simulator
from flode.blocks.cast import Cast
from flode.core import signals as dtypes
from tests.core import _dtype_baseline_models as baseline


class TestSmAPathPreservation:
    def test_undeclared_model_uses_sm_a_step_not_step_vector(self) -> None:
        # AC-1 ②: dtype 未宣言モデルは SM-A path (_step) を通り、
        # _step_vector は一度も呼ばれない
        sim, _scope = baseline.build_mixed()
        called = {"step": 0, "step_vector": 0}
        orig_step = Simulator._step
        orig_step_v = Simulator._step_vector

        def spy_step(self, *a, **k):  # type: ignore[no-untyped-def]
            called["step"] += 1
            return orig_step(self, *a, **k)

        def spy_step_v(self, *a, **k):  # type: ignore[no-untyped-def]
            called["step_vector"] += 1
            return orig_step_v(self, *a, **k)

        with (
            mock.patch.object(Simulator, "_step", spy_step),
            mock.patch.object(Simulator, "_step_vector", spy_step_v),
        ):
            sim.run()
        assert called["step"] > 0
        assert called["step_vector"] == 0

    def test_undeclared_model_never_calls_resolver(self) -> None:
        # AC-1 ①: pre-filter (has_declared_dtype) が False なら解決器は呼ばれない
        sim, scope = baseline.build_continuous()
        with mock.patch.object(
            dtypes,
            "resolve_for_execution",
            side_effect=AssertionError("must not resolve"),
        ):
            sim.run()
        assert len(scope.times) > 0

    def test_dtype_plan_stays_none_for_undeclared_model(self) -> None:
        sim, _scope = baseline.build_discrete()
        sim.run()
        assert sim._signal_plan is None


class TestAllFloat64Declared:
    def test_sm_b_dtype_run_equals_sm_a_run(self) -> None:
        # 「Cast(dtype='float64') のみ宣言」モデル: SM-B path で走るが
        # 結果は SM-A と完全一致する (エッジケース表)
        def build(declare: bool):  # type: ignore[no-untyped-def]
            sim, scope = baseline.build_continuous()
            if declare:
                # 既存モデルの末尾に恒等の float64 Cast を挟んでも数値は不変
                # (ここでは並列に置くだけで SM-B へ振り分ける)
                sim.add(Cast(dtype="float64", id="marker_cast"))
            return sim, scope

        sim_a, scope_a = build(declare=False)
        sim_a.run()
        vals_a = np.asarray(scope_a.values)

        sim_b, scope_b = build(declare=True)
        assert dtypes.has_declared_dtype(sim_b) is True
        sim_b.run()
        assert sim_b._signal_plan is not None  # SM-B + plan で走った
        vals_b = np.asarray(scope_b.values)

        assert np.array_equal(vals_a, vals_b)  # bit-identical
