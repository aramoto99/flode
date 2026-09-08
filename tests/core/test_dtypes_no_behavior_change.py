"""SPEC-0027 受け入れ条件 (AC-3 / AC-4 / AC-5) の機械検証。

SM-D Stage 0 の鉄則「計算結果を 1 bit も変えない」を、

1. 同一プロセス比較 (``run()`` のみ vs ``resolve_dtypes()`` を挟んだ ``run()``) —
   主防衛線、環境非依存で常に厳密
2. v0.53.7 時点で採取した基準 npz との ``np.array_equal`` 比較 —
   クロスバージョン保証の追加層

の 2 層で固定する。基準モデルは `_dtype_baseline_models.py` (同ディレクトリ) を共有。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from flode import Simulator
from flode.core import dtypes
from flode.core.persistence import CURRENT_SCHEMA_VERSION
from tests.core import _dtype_baseline_models as baseline


class TestBehaviorInvariance:
    @pytest.mark.parametrize("name_builder", baseline.builders(), ids=lambda nb: nb[0])
    def test_run_results_bit_identical_with_and_without_resolve(
        self, name_builder: tuple[str, baseline.Builder]
    ) -> None:
        _name, builder = name_builder
        plain_times, plain_values = baseline.run_and_capture(builder)

        sim, scope = builder()
        res = sim.resolve_dtypes()
        assert res.summary.total_ports > 0  # 解決自体は成功している
        sim.run()
        times = np.asarray(list(scope.times), dtype=np.float64)
        values = np.asarray(scope.values, dtype=np.float64)

        assert np.array_equal(plain_times, times)  # allclose ではなく厳密比較
        assert np.array_equal(plain_values, values)

    def test_resolve_run_resolve_run_stable(self) -> None:
        # _execution_order() の build 副作用が冪等であることへの依存を固定する
        # (SPEC-0027 §3.2 実装上の注意)。同一 Simulator で 4 回交互に呼ぶ。
        sim, scope = baseline.build_continuous()
        first_res = sim.resolve_dtypes()
        sim.run()
        first_values = np.asarray(scope.values, dtype=np.float64)
        second_res = sim.resolve_dtypes()
        sim.run()
        second_values = np.asarray(scope.values, dtype=np.float64)

        assert dict(first_res.ports) == dict(second_res.ports)
        assert np.array_equal(first_values, second_values)

    def test_engine_exception_does_not_break_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # AC-5: エンジンがどんなに壊れていても run は成功する (構造的独立の固定)
        def boom(_sim: Simulator) -> dtypes.DTypeResolution:
            raise RuntimeError("engine is broken")

        monkeypatch.setattr(dtypes, "_resolve_impl", boom)
        sim, scope = baseline.build_discrete()
        res = sim.resolve_dtypes()  # 例外は診断に変換される
        assert [d.code for d in res.diagnostics] == ["dtype.internal_error"]
        sim.run()
        assert len(scope.times) > 0

    def test_save_load_bytes_unchanged(self, tmp_path: Path) -> None:
        # AC-4: resolve_dtypes を挟んでも .flw.json は 1 バイトも変わらない
        sim, _scope = baseline.build_mixed()
        before = tmp_path / "before.flw.json"
        after = tmp_path / "after.flw.json"
        sim.save(before)

        loaded = Simulator.load(before)
        loaded.resolve_dtypes()
        loaded.save(after)

        assert before.read_bytes() == after.read_bytes()

    def test_schema_version_current_pin(self) -> None:
        # Stage 0 (SPEC-0027 AC-4) 時点では 0.10 固定だった。SM-D Stage 1
        # (SPEC-0028) が dtype param 追加で 0.11 へ bump (no-op migration、
        # 旧ファイルは dtype なし = 従来挙動で完全互換)
        assert CURRENT_SCHEMA_VERSION == "0.12"

    def test_baseline_arrays_match_v0_53_7(self) -> None:
        # AC-3: v0.53.7 で採取した基準配列との厳密一致 (クロスバージョン層)
        assert baseline.BASELINE_NPZ.exists(), (
            f"基準 npz が無い: {baseline.BASELINE_NPZ} — "
            "`python src/tests/core/_dtype_baseline_models.py` で採取する"
        )
        with np.load(baseline.BASELINE_NPZ) as npz:
            for name, builder in baseline.builders():
                sim, scope = builder()
                sim.resolve_dtypes()  # 挟んでも一致することが本題
                sim.run()
                times = np.asarray(list(scope.times), dtype=np.float64)
                values = np.asarray(scope.values, dtype=np.float64)
                assert np.array_equal(npz[f"{name}_times"], times), (
                    f"{name}: times が v0.53.7 基準と不一致 "
                    f"(基準採取環境: numpy {npz['numpy_version']}, "
                    f"scipy {npz['scipy_version']})"
                )
                assert np.array_equal(npz[f"{name}_values"], values), (
                    f"{name}: values が v0.53.7 基準と不一致 "
                    f"(基準採取環境: numpy {npz['numpy_version']}, "
                    f"scipy {npz['scipy_version']})"
                )
