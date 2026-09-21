"""SPEC-0028 AC-2 / AC-3 と ADR-0079 AC-2 の検証ヘルパ: instrumented run。

``Simulator._step_vector`` を spy し、run 中に各ポートを実際に流れた ndarray の
``.dtype`` と ``.shape`` を全ステップ収集して、``resolve_signals()`` の予測と
``(block_id, direction, port_index)`` ごとに突合する。

「予測 == 実行」(AC-2) が破れると GUI 表示が嘘になるため、
これが Stage 1 の中核の受け入れ条件である。
"""

from __future__ import annotations

from unittest import mock

import numpy as np

from flode import Simulator
from flode.core.signals import PortKey
from flode.core.signals import resolve_signals as _resolve_signals


def run_with_signal_trace(
    sim: Simulator,
) -> tuple[dict[PortKey, set[np.dtype]], dict[PortKey, set[tuple[int, ...]]]]:
    """run() 中に全ポートを流れた実 dtype / 実 shape の集合を収集する。"""
    observed_dtypes: dict[PortKey, set[np.dtype]] = {}
    observed_shapes: dict[PortKey, set[tuple[int, ...]]] = {}
    orig = Simulator._step_vector

    def spy(self, t, x_cont, discrete_state, order, layout, **kwargs):  # type: ignore[no-untyped-def]
        # ADR-0078: fresh / cache (出力キャッシュ制御) を素通し
        outputs, inputs = orig(self, t, x_cont, discrete_state, order, layout, **kwargs)
        for b, tup in outputs.items():
            for j, arr in enumerate(tup):
                observed_dtypes.setdefault((b.id, "out", j), set()).add(arr.dtype)
                observed_shapes.setdefault((b.id, "out", j), set()).add(tuple(arr.shape))
        for b, tup in inputs.items():
            for i, arr in enumerate(tup):
                observed_dtypes.setdefault((b.id, "in", i), set()).add(arr.dtype)
                observed_shapes.setdefault((b.id, "in", i), set()).add(tuple(arr.shape))
        return outputs, inputs

    with mock.patch.object(Simulator, "_step_vector", spy):
        sim.run()
    return observed_dtypes, observed_shapes


def run_with_dtype_trace(sim: Simulator) -> dict[PortKey, set[np.dtype]]:
    """run() 中に全ポートを流れた実 dtype の集合を収集する (SPEC-0028 互換名)。"""
    return run_with_signal_trace(sim)[0]


def assert_dtype_prediction_matches_execution(sim: Simulator) -> None:
    """AC-2: 全ポートで「予測 dtype == 実行時 dtype (全ステップ)」を機械検証する。"""
    # 実行と同じ full mode で解決する (PythonFunction 入りモデルでも
    # run 経路は full。REST の static とは別)
    res = _resolve_signals(sim, mode="full")
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


def assert_signal_prediction_matches_execution(sim: Simulator) -> None:
    """ADR-0079 AC-2 / AC-3: 全ポートで「予測 (shape, dtype) == 実行時 (全ステップ)」。"""
    res = _resolve_signals(sim, mode="full")
    assert res.summary.unresolved == 0, "unresolved dtypes must be 0 (AC-3)"
    assert all(s is not None for s in res.shapes.values()), "unresolved shapes must be 0 (AC-3)"
    observed_dtypes, observed_shapes = run_with_signal_trace(sim)
    assert observed_shapes, "SM-T path が使われていない (shape 起点モデルのはず)"
    for key, shapes in sorted(observed_shapes.items()):
        expected_shape = res.shapes[key]
        assert shapes == {expected_shape}, (
            f"AC-2 violation (shape) at {key}: observed {sorted(shapes)} "
            f"!= predicted {expected_shape}"
        )
    for key, dts in sorted(observed_dtypes.items()):
        expected = np.dtype(res.ports[key])
        assert dts == {expected}, (
            f"AC-2 violation (dtype) at {key}: observed {sorted(str(d) for d in dts)} "
            f"!= predicted {expected}"
        )
