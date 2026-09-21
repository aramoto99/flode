"""SPEC-0027 受け入れ条件 (AC-3 / AC-4 / AC-5) の機械検証。

SM-D Stage 0 の鉄則「計算結果を 1 bit も変えない」を、

1. 同一プロセス比較 (``run()`` のみ vs ``resolve_dtypes()`` を挟んだ ``run()``) —
   主防衛線、環境非依存で常に厳密 (bit 一致)
2. v0.53.7 時点で採取した基準 npz との比較 — クロスバージョン保証の追加層。
   基準は特定環境 (Windows / numpy 2.5.1 / scipy 1.18.0) で採取したもので、
   別プラットフォーム・別ビルドの numpy/scipy は ODE 積分に ULP レベルの差を
   生むため、values は bit 一致ではなく極小許容誤差で比較する
   (CI ubuntu 3.11/3.12 で実際に最終 bit のみ不一致になった実績あり)

の 2 層で固定する。基準モデルは `_dtype_baseline_models.py` (同ディレクトリ) を共有。
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import numpy as np
import pytest
from pytest_mock import MockerFixture

from flode import Simulator
from flode.core import signals as dtypes
from flode.core.persistence import CURRENT_SCHEMA_VERSION
from tests.core import _dtype_baseline_models as baseline

_T0 = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)


def _freeze_save_clock(mocker: MockerFixture, instants: list[datetime.datetime]) -> None:
    """``Simulator.save`` が metadata.created_at に使う時計を固定する。"""
    fake = mocker.patch("flode.core.simulator.datetime")
    fake.UTC = datetime.UTC
    fake.datetime.now.side_effect = list(instants)


# npz 基準比較 (クロス環境層) で ODE 積分を含む continuous 系列にのみ適用する
# 許容誤差。観測された環境差は最終 bit (相対 ~1e-16) のみで、ソルバ自身の精度
# (RTOL=1e-6 / ATOL=1e-9、_dtype_baseline_models.py) より 3 桁厳しい値に設定する
# = ソルバ精度未満のビルド差ノイズだけを許容し、それ以上の差は全て退行として検出。
_CROSS_ENV_VALUES_RTOL = 1e-9
_CROSS_ENV_VALUES_ATOL = 1e-12


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

    def test_engine_exception_does_not_break_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # AC-5: エンジンがどんなに壊れていても run は成功する (構造的独立の固定)
        def boom(_sim: Simulator) -> dtypes.DTypeResolution:
            raise RuntimeError("engine is broken")

        monkeypatch.setattr(dtypes, "_resolve_impl", boom)
        sim, scope = baseline.build_discrete()
        res = sim.resolve_dtypes()  # 例外は診断に変換される
        assert [d.code for d in res.diagnostics] == ["dtype.internal_error"]
        sim.run()
        assert len(scope.times) > 0

    def test_save_load_bytes_unchanged(self, tmp_path: Path, mocker: MockerFixture) -> None:
        # AC-4: resolve_dtypes を挟んでも .flw.json は 1 バイトも変わらない。
        # bug-fix 2026-09-21: metadata.created_at は save 時刻 (秒精度) なので、2 回の
        # save が秒境界をまたぐと本テストが flaky に落ちていた → 時計を固定する
        _freeze_save_clock(mocker, [_T0, _T0])
        sim, _scope = baseline.build_mixed()
        before = tmp_path / "before.flw.json"
        after = tmp_path / "after.flw.json"
        sim.save(before)

        loaded = Simulator.load(before)
        loaded.resolve_dtypes()
        loaded.save(after)

        assert before.read_bytes() == after.read_bytes()

    def test_save_load_across_second_boundary_changes_only_created_at(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        """秒境界をまたいでも変わるのは metadata.created_at だけ (flaky の原因の固定)。"""
        _freeze_save_clock(mocker, [_T0, _T0 + datetime.timedelta(seconds=1)])
        sim, _scope = baseline.build_mixed()
        before = tmp_path / "before.flw.json"
        after = tmp_path / "after.flw.json"
        sim.save(before)
        loaded = Simulator.load(before)
        loaded.resolve_dtypes()
        loaded.save(after)

        a = json.loads(before.read_text(encoding="utf-8"))
        b = json.loads(after.read_text(encoding="utf-8"))
        assert a["metadata"]["created_at"] != b["metadata"]["created_at"]
        assert a["metadata"]["created_at"] == "2026-01-01T00:00:00Z"
        del a["metadata"]["created_at"]
        del b["metadata"]["created_at"]
        assert a == b

    def test_schema_version_current_pin(self) -> None:
        # Stage 0 (SPEC-0027 AC-4) 時点では 0.10 固定だった。SM-D Stage 1
        # (SPEC-0028) が dtype param 追加で 0.11 へ bump (no-op migration、
        # 旧ファイルは dtype なし = 従来挙動で完全互換)
        assert CURRENT_SCHEMA_VERSION == "0.15"

    def test_baseline_arrays_match_v0_53_7(self) -> None:
        # AC-3: v0.53.7 で採取した基準配列との一致 (クロスバージョン層)。
        # NOTE (ADR-0078, v0.61.0): discrete モデル (UnitDelay 累積ループ) の系列は
        # BUG-001 の是正で 1 fire ごとに 1 増える正しい値に変わったため、discrete の
        # 配列だけ v0.61.0 で再採取した (continuous / mixed は bit 一致のまま)。
        # times はサンプリング格子の決定的算術なので全系列で厳密一致を要求する。
        # values は ODE 積分 (solve_ivp) を含む continuous のみ、numpy/scipy の
        # ビルド差 (プラットフォーム・Python バージョンごとの wheel) で最終 bit が
        # 揺れるため _CROSS_ENV_VALUES_* の許容誤差で比較する (選定根拠は定数定義
        # のコメント参照)。加算・比較のみの discrete / mixed は bit 一致を維持。
        # bit 一致そのものの保証は同一プロセス比較
        # (test_run_results_bit_identical_with_and_without_resolve) が担う。
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
                ref_values = npz[f"{name}_values"]
                assert ref_values.shape == values.shape, (
                    f"{name}: values の形状が v0.53.7 基準と不一致 "
                    f"({ref_values.shape} != {values.shape})"
                )
                if name == "continuous":
                    # ODE 積分 (solve_ivp) を含む系列のみ、ビルド差の ULP 揺れを許容
                    assert np.allclose(
                        ref_values,
                        values,
                        rtol=_CROSS_ENV_VALUES_RTOL,
                        atol=_CROSS_ENV_VALUES_ATOL,
                    ), (
                        f"{name}: values が v0.53.7 基準と許容誤差を超えて不一致 "
                        f"(基準採取環境: numpy {npz['numpy_version']}, "
                        f"scipy {npz['scipy_version']})"
                    )
                else:
                    # 純粋な加算・比較のみの系列は環境間でも決定的 = bit 一致を維持
                    assert np.array_equal(ref_values, values), (
                        f"{name}: values が v0.53.7 基準と不一致 "
                        f"(基準採取環境: numpy {npz['numpy_version']}, "
                        f"scipy {npz['scipy_version']})"
                    )
