"""SPEC-0028 AC-2 / AC-3 の検証ヘルパ: instrumented run。

``Simulator._step_vector`` を spy し、run 中に各ポートを実際に流れた ndarray の
``.dtype`` を全ステップ収集して、``resolve_dtypes()`` の予測と
``(block_id, direction, port_index)`` ごとに突合する。

「予測 == 実行」(AC-2) が破れると Stage 0 の GUI 表示が嘘になるため、
これが Stage 1 の中核の受け入れ条件である。
"""

from __future__ import annotations

from unittest import mock

import numpy as np

from flode import Simulator
from flode.core.dtypes import PortKey
from flode.core.dtypes import resolve_dtypes as _resolve_dtypes


def run_with_dtype_trace(sim: Simulator) -> dict[PortKey, set[np.dtype]]:
    """run() 中に全ポートを流れた実 dtype の集合を収集する。"""
    observed: dict[PortKey, set[np.dtype]] = {}
    orig = Simulator._step_vector

    def spy(self, t, x_cont, discrete_state, order, layout):  # type: ignore[no-untyped-def]
        outputs, inputs = orig(self, t, x_cont, discrete_state, order, layout)
        for b, tup in outputs.items():
            for j, arr in enumerate(tup):
                observed.setdefault((b.id, "out", j), set()).add(arr.dtype)
        for b, tup in inputs.items():
            for i, arr in enumerate(tup):
                observed.setdefault((b.id, "in", i), set()).add(arr.dtype)
        return outputs, inputs

    with mock.patch.object(Simulator, "_step_vector", spy):
        sim.run()
    return observed


def assert_dtype_prediction_matches_execution(sim: Simulator) -> None:
    """AC-2: 全ポートで「予測 dtype == 実行時 dtype (全ステップ)」を機械検証する。"""
    # 実行と同じ full mode で解決する (PythonFunction 入りモデルでも
    # run 経路は full。REST の static とは別)
    res = _resolve_dtypes(sim, mode="full")
    # AC-3 (全域性): full mode では unknown が残らない
    assert res.summary.unresolved == 0, "unresolved ports must be 0 (AC-3)"
    observed = run_with_dtype_trace(sim)
    assert observed, "SM-B path が使われていない (dtype 宣言モデルのはず)"
    for key, dts in sorted(observed.items()):
        expected = np.dtype(res.ports[key])
        assert dts == {expected}, (
            f"AC-2 violation at {key}: observed {sorted(str(d) for d in dts)} "
            f"!= predicted {expected}"
        )
