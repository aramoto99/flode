"""v0.58.0 (SPEC-0030): schema 0.12 → 0.13 migration の単体テスト。

``sample_time`` の語彙に ``"dt"`` (基準クロック同期) が追加され、``-1``
(上流に同期) は解決不能時にエラーへ変わった。migration は離散専用ブロックの
旧 ``-1`` のうち**上流に離散レート源がないもの**だけを ``"dt"`` に書き換える
(v0.57.0 の dt フォールバックの実行挙動と数値同一)。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from flode import Simulator
from flode.core.persistence import (
    CURRENT_SCHEMA_VERSION,
    _builtin_migrate_0_12_to_0_13,
    migrate_to_current,
)

_UNIT_DELAY = "flode.blocks.discrete.UnitDelay"


def test_current_schema_version_is_0_13() -> None:
    assert CURRENT_SCHEMA_VERSION == "0.13"


def _model_0_12(
    blocks: list[dict[str, Any]], connections: list[Any] | None = None
) -> dict[str, Any]:
    return {
        "schema_version": "0.12",
        "simulator": {
            "t_end": 0.05,
            "dt": 0.01,
            "solver": "RK45",
            "rtol": 1e-6,
            "atol": 1e-9,
            "dt_base": None,
        },
        "blocks": blocks,
        "connections": connections or [],
    }


def _const(bid: str) -> dict[str, Any]:
    return {
        "id": bid,
        "type": "flode.blocks.sources.Constant",
        "params": {"value": 1.0},
    }


def _delay(bid: str, sample_time: Any) -> dict[str, Any]:
    return {
        "id": bid,
        "type": _UNIT_DELAY,
        "params": {"sample_time": sample_time, "x0": 0.0},
    }


def _conn(src: str, dst: str) -> dict[str, Any]:
    return {"src": src, "src_idx": 0, "dst": dst, "dst_idx": 0}


class TestRewrite:
    def test_unresolvable_minus_one_becomes_dt(self) -> None:
        data = _model_0_12(
            [_const("c"), _delay("d", -1.0)],
            connections=[_conn("c", "d")],
        )
        out = _builtin_migrate_0_12_to_0_13(data)
        assert out["schema_version"] == "0.13"
        by_id = {b["id"]: b for b in out["blocks"]}
        assert by_id["d"]["params"]["sample_time"] == "dt"

    def test_minus_one_with_upstream_rate_is_kept(self) -> None:
        data = _model_0_12(
            [_const("c"), _delay("d1", 0.03), _delay("d2", -1.0)],
            connections=[_conn("c", "d1"), _conn("d1", "d2")],
        )
        out = _builtin_migrate_0_12_to_0_13(data)
        by_id = {b["id"]: b for b in out["blocks"]}
        assert by_id["d2"]["params"]["sample_time"] == -1.0  # 継承は温存

    def test_transitive_upstream_rate_is_found(self) -> None:
        # d1(0.03) → Gain → d2(-1): 中間に無レートブロックを挟んでも辿れる
        gain = {
            "id": "g",
            "type": "flode.blocks.mathops.Gain",
            "params": {"k": 2.0},
        }
        data = _model_0_12(
            [_const("c"), _delay("d1", 0.03), gain, _delay("d2", -1.0)],
            connections=[_conn("c", "d1"), _conn("d1", "g"), _conn("g", "d2")],
        )
        out = _builtin_migrate_0_12_to_0_13(data)
        by_id = {b["id"]: b for b in out["blocks"]}
        assert by_id["d2"]["params"]["sample_time"] == -1.0

    def test_upstream_dt_block_counts_as_rate_source(self) -> None:
        data = _model_0_12(
            [_const("c"), _delay("d1", "dt"), _delay("d2", -1.0)],
            connections=[_conn("c", "d1"), _conn("d1", "d2")],
        )
        out = _builtin_migrate_0_12_to_0_13(data)
        by_id = {b["id"]: b for b in out["blocks"]}
        assert by_id["d2"]["params"]["sample_time"] == -1.0

    def test_upstream_subsystem_with_inner_rate_counts(self) -> None:
        # Subsystem は build 時に内部最小周期を派生 sample_time として外に見せる
        # ため、静的 walk も内部を見る必要がある
        sub = {
            "id": "sub",
            "type": "flode.subsystems.subsystem.Subsystem",
            "params": {
                "blocks": [_delay("inner", 0.02)],
                "connections": [],
            },
        }
        data = _model_0_12(
            [sub, _delay("d", -1.0)],
            connections=[_conn("sub", "d")],
        )
        out = _builtin_migrate_0_12_to_0_13(data)
        by_id = {b["id"]: b for b in out["blocks"]}
        assert by_id["d"]["params"]["sample_time"] == -1.0

    def test_stateless_minus_one_is_not_rewritten(self) -> None:
        # 無状態ブロックの -1 (→ 連続) は意図された機能なので触らない
        gain = {
            "id": "g",
            "type": "flode.blocks.mathops.Gain",
            "params": {"k": 2.0, "sample_time": -1.0},
        }
        data = _model_0_12(
            [_const("c"), dict(gain)],
            connections=[_conn("c", "g")],
        )
        out = _builtin_migrate_0_12_to_0_13(data)
        assert out["blocks"][1]["params"]["sample_time"] == -1.0

    def test_cycle_of_minus_one_is_rewritten(self) -> None:
        # -1 同士の循環 (レート源なし) は両方 "dt" へ (v0.57.0 実行挙動と同一)
        data = _model_0_12(
            [_delay("a", -1.0), _delay("b", -1.0)],
            connections=[_conn("a", "b"), _conn("b", "a")],
        )
        out = _builtin_migrate_0_12_to_0_13(data)
        by_id = {b["id"]: b for b in out["blocks"]}
        assert by_id["a"]["params"]["sample_time"] == "dt"
        assert by_id["b"]["params"]["sample_time"] == "dt"

    def test_broken_entries_do_not_crash(self) -> None:
        data = _model_0_12(
            [_delay("d", -1.0), {"id": ["bad"], "type": 42}, "not-a-dict"],
            connections=[
                {"src": {"evil": 1}, "dst": "d"},
                "not-a-dict",
            ],
        )
        out = _builtin_migrate_0_12_to_0_13(data)  # 例外にならない
        assert out["schema_version"] == "0.13"
        assert out["blocks"][0]["params"]["sample_time"] == "dt"


class TestChainAndBehaviour:
    def test_chain_from_0_12_reaches_current(self) -> None:
        data = _model_0_12([])
        out = migrate_to_current(data)
        assert out["schema_version"] == "0.13"
        assert out["_migrated_from"] == "0.12"

    def test_migrated_v057_model_runs_identically(self, tmp_path: Path) -> None:
        """v0.57.0 で dt フォールバック実行されていたモデル (0.12 の -1、上流
        レートなし) が、migration 後も同じ値列で動く (dt=0.01 で 6 tick)。"""
        add = {
            "id": "add",
            "type": "flode.blocks.mathops.Add",
            "params": {"signs": "++"},
        }
        scope = {
            "id": "sc",
            "type": "flode.blocks.sinks.Scope",
            "params": {"n_inputs": 1},
        }
        data = _model_0_12(
            [_const("c"), add, _delay("d", -1.0), scope],
            connections=[
                {"src": "c", "src_idx": 0, "dst": "add", "dst_idx": 0},
                {"src": "d", "src_idx": 0, "dst": "add", "dst_idx": 1},
                _conn("add", "d"),
                _conn("add", "sc"),
            ],
        )
        path = tmp_path / "old.flw.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        sim = Simulator.load(path)
        sim.run()
        values = np.asarray(sim.get_block("sc").values)[:, 0]
        # x[k+1] = x[k] + 1 の加算ループ: 1 fire ごとに 1 増える (ADR-0078 で
        # v0.57.0 の半速系列 1,2,2,3,3,4 (BUG-001) を是正)
        assert values.tolist() == pytest.approx([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])

    def test_top_level_schema_version_key_not_overwritten(self) -> None:
        # NOTE: migration は既存群と同じ「浅コピー + ネスト in-place」流儀。
        # 非破壊なのはトップレベルのキーのみで、blocks の中身は共有される
        data = _model_0_12([])
        _builtin_migrate_0_12_to_0_13(data)
        assert data["schema_version"] == "0.12"

    def test_nested_subsystem_inner_minus_one_is_not_rewritten(self) -> None:
        """Subsystem 内部の -1 は書き換え対象外 (build 時ガードの案内エラーに
        任せる — どちらに書き換えてもエラーになるため元の値を保存する)。"""
        sub = {
            "id": "sub",
            "type": "flode.subsystems.subsystem.Subsystem",
            "params": {
                "blocks": [_delay("inner", -1.0)],
                "connections": [],
            },
        }
        data = _model_0_12([sub])
        out = _builtin_migrate_0_12_to_0_13(data)
        inner = out["blocks"][0]["params"]["blocks"][0]
        assert inner["params"]["sample_time"] == -1.0
