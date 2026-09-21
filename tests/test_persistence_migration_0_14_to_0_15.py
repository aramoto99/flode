"""v0.64.0 (ADR-0079 Stage 3、D-9): schema 0.14 → 0.15 migration の単体テスト。

``StateSpace`` 系のポートがベクトル 1 本になったため、m ≥ 2 / p ≥ 2 のブロックに
``Mux`` / ``Demux`` を挿入して結線を付け替える。受け入れ基準 (ADR-0079 §(10) Stage 3):
migration 前後の数値等価 (v0.63.0 で採取した基準 npz)、挿入 ID の決定性、SISO は
対象外、レイアウト非破壊、冪等。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import numpy as np

from flode import Simulator
from flode.core.identifiers import validate_block_id
from flode.core.persistence import (
    CURRENT_SCHEMA_VERSION,
    LTI_MIGRATION_PORT_BLOCK_OFFSET,
    _builtin_migrate_0_14_to_0_15,
    _migration_block_id,
    migrate_to_current,
)
from tests.core._lti_baseline_models import BASELINE_NPZ, FIXTURE_JSON, fixture_0_14, run_model

_SS = "flode.blocks.continuous.StateSpace"
_MUX = "flode.blocks.routing.Mux"
_DEMUX = "flode.blocks.routing.Demux"


def test_current_schema_version_is_0_15() -> None:
    assert CURRENT_SCHEMA_VERSION == "0.15"


def _blocks_by_id(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {b["id"]: b for b in data["blocks"]}


def _conns(data: dict[str, Any]) -> set[tuple[str, int, str, int]]:
    return {(c["src"], c["src_idx"], c["dst"], c["dst_idx"]) for c in data["connections"]}


class TestFixtureIsFrozen:
    """fixture JSON と Python 側の辞書が一致している (採取元が動いていない)。"""

    def test_fixture_file_matches_builder(self) -> None:
        on_disk = json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))
        assert on_disk == fixture_0_14()


class TestRewiring:
    def test_mux_demux_inserted_for_2x2(self) -> None:
        out = _builtin_migrate_0_14_to_0_15(fixture_0_14())
        assert out["schema_version"] == "0.15"
        blocks = _blocks_by_id(out)
        assert blocks["ss__in_mux"] == {"id": "ss__in_mux", "type": _MUX, "params": {"n": 2}}
        assert blocks["ss__out_demux"] == {
            "id": "ss__out_demux",
            "type": _DEMUX,
            "params": {"n": 2},
        }
        conns = _conns(out)
        # 入力側: 旧 dst=ss (dst_idx 0/1) が Mux へ、Mux → ss:0 が追加
        assert ("step", 0, "ss__in_mux", 0) in conns
        assert ("sine", 0, "ss__in_mux", 1) in conns
        assert ("ss__in_mux", 0, "ss", 0) in conns
        # 出力側: 旧 src=ss (src_idx 0/1) が Demux へ、ss:0 → Demux が追加
        assert ("ss__out_demux", 0, "scope", 0) in conns
        assert ("ss__out_demux", 1, "scope", 1) in conns
        assert ("ss", 0, "ss__out_demux", 0) in conns
        assert not any(c[2] == "ss" and c[0] != "ss__in_mux" for c in conns)
        assert not any(c[0] == "ss" and c[2] != "ss__out_demux" for c in conns)

    def test_all_three_types_and_nested(self) -> None:
        out = _builtin_migrate_0_14_to_0_15(fixture_0_14())
        ids = set(_blocks_by_id(out))
        for base in ("ss", "dss", "mimo"):
            assert f"{base}__in_mux" in ids and f"{base}__out_demux" in ids
        inner = _blocks_by_id({"blocks": _blocks_by_id(out)["sub"]["params"]["blocks"]})
        assert "ss_in__in_mux" in inner and "ss_in__out_demux" in inner
        inner_conns = {
            (c["src"], c["src_idx"], c["dst"], c["dst_idx"])
            for c in _blocks_by_id(out)["sub"]["params"]["connections"]
        }
        assert ("in0", 0, "ss_in__in_mux", 0) in inner_conns
        assert ("ss_in__out_demux", 1, "out1", 0) in inner_conns

    def test_siso_untouched(self) -> None:
        before = fixture_0_14()
        out = _builtin_migrate_0_14_to_0_15(copy.deepcopy(before))
        assert _blocks_by_id(out)["siso"] == _blocks_by_id(before)["siso"]
        assert ("step", 0, "siso", 0) in _conns(out)
        assert ("siso", 0, "scope", 6) in _conns(out)
        assert "siso__in_mux" not in _blocks_by_id(out)
        assert "siso__out_demux" not in _blocks_by_id(out)

    def test_block_order_keeps_mux_before_and_demux_after(self) -> None:
        out = _builtin_migrate_0_14_to_0_15(fixture_0_14())
        order = [b["id"] for b in out["blocks"]]
        assert order.index("ss__in_mux") == order.index("ss") - 1
        assert order.index("ss__out_demux") == order.index("ss") + 1

    def test_input_is_not_mutated(self) -> None:
        data = fixture_0_14()
        snapshot = copy.deepcopy(data)
        _builtin_migrate_0_14_to_0_15(data)
        # 浅いコピー慣例 (list / dict は in-place) — 少なくとも version は不変
        assert data["schema_version"] == "0.14"
        assert snapshot["schema_version"] == "0.14"

    def test_unconnected_inputs_become_unconnected_mux_inputs(self) -> None:
        data = fixture_0_14()
        data["connections"] = [
            c for c in data["connections"] if not (c["dst"] == "ss" and c["dst_idx"] == 1)
        ]
        out = _builtin_migrate_0_14_to_0_15(data)
        conns = _conns(out)
        assert ("step", 0, "ss__in_mux", 0) in conns
        assert not any(c[2] == "ss__in_mux" and c[3] == 1 for c in conns)


class TestLayoutAndWaypoints:
    def test_existing_coordinates_unchanged_and_inserted_offset(self) -> None:
        before = fixture_0_14()
        out = _builtin_migrate_0_14_to_0_15(copy.deepcopy(before))
        for bid, pos in before["layout"].items():
            assert out["layout"][bid] == pos
        ss = before["layout"]["ss"]
        assert out["layout"]["ss__in_mux"] == {
            "x": ss["x"] - LTI_MIGRATION_PORT_BLOCK_OFFSET,
            "y": ss["y"],
        }
        assert out["layout"]["ss__out_demux"] == {
            "x": ss["x"] + LTI_MIGRATION_PORT_BLOCK_OFFSET,
            "y": ss["y"],
        }

    def test_model_without_layout_gets_no_coordinates(self) -> None:
        data = fixture_0_14()
        del data["layout"]
        del data["branch_waypoints"]
        out = _builtin_migrate_0_14_to_0_15(data)
        assert "layout" not in out
        assert "ss__in_mux" in _blocks_by_id(out)

    def test_branch_waypoints_follow_demux(self) -> None:
        out = _builtin_migrate_0_14_to_0_15(fixture_0_14())
        wp = out["branch_waypoints"]
        assert "ss:1" not in wp and "mimo:0" not in wp
        assert wp["ss__out_demux:1"] == [{"x": 500.0, "y": 60.0}]
        assert wp["mimo__out_demux:0"] == [{"x": 500.0, "y": 250.0}]


class TestIdDeterminism:
    def test_same_input_same_ids(self) -> None:
        a = _builtin_migrate_0_14_to_0_15(fixture_0_14())
        b = _builtin_migrate_0_14_to_0_15(fixture_0_14())
        assert [x["id"] for x in a["blocks"]] == [x["id"] for x in b["blocks"]]

    def test_collision_gets_numeric_suffix(self) -> None:
        data = fixture_0_14()
        data["blocks"].append(
            {"id": "ss__in_mux", "type": "flode.blocks.sources.Clock", "params": {}}
        )
        out = _builtin_migrate_0_14_to_0_15(data)
        ids = _blocks_by_id(out)
        assert ids["ss__in_mux"]["type"] == "flode.blocks.sources.Clock"
        assert ids["ss__in_mux_1"]["type"] == _MUX
        assert ("ss__in_mux_1", 0, "ss", 0) in _conns(out)

    def test_long_id_is_truncated_to_valid_length(self) -> None:
        base = "x" * 64
        new_id = _migration_block_id(base, "__in_mux", set())
        assert new_id.endswith("__in_mux")
        assert len(new_id) <= 64

    def test_many_collisions_still_yield_valid_length(self) -> None:
        """bug-fix 2026-09-21: 同一 base で 1000 件超衝突しても 64 code point に収まる。"""
        base = "x" * 64
        existing: set[str] = set()
        ids = [_migration_block_id(base, "__in_mux", existing) for _ in range(1002)]
        assert len(set(ids)) == 1002  # 全て一意
        for new_id in ids:
            assert len(new_id) <= 64
            validate_block_id(new_id)
        assert ids[0].endswith("__in_mux")
        assert ids[1].endswith("__in_mux_1")
        assert ids[1001].endswith("__in_mux_1001")

    def test_invalid_base_falls_back(self) -> None:
        assert _migration_block_id("bad id!", "__out_demux", set()) == "lti__out_demux"
        assert _migration_block_id(None, "__out_demux", set()) == "lti__out_demux"

    def test_nfc_normalized(self) -> None:
        decomposed = "ガ"  # カ + 結合濁点 (NFD)
        new_id = _migration_block_id(decomposed, "__in_mux", set())
        assert new_id == "ガ__in_mux"  # ガ (NFC)


class TestChainAndIdempotence:
    def test_chain_from_0_14_reaches_current(self) -> None:
        out = migrate_to_current(fixture_0_14())
        assert out["schema_version"] == "0.15"
        assert out["_migrated_from"] == "0.14"

    def test_resaved_model_is_not_migrated_again(self, tmp_path: Path) -> None:
        first = tmp_path / "first.flw.json"
        second = tmp_path / "second.flw.json"
        first.write_text(json.dumps(fixture_0_14()), encoding="utf-8")
        sim = Simulator.load(first)
        sim.save(second)
        saved = json.loads(second.read_text(encoding="utf-8"))
        assert saved["schema_version"] == "0.15"
        assert "ss__in_mux" in {b["id"] for b in saved["blocks"]}
        assert "ss__in_mux__in_mux" not in {b["id"] for b in saved["blocks"]}
        # 0.15 ファイルは migration が走らない
        again = migrate_to_current(json.loads(second.read_text(encoding="utf-8")))
        assert "_migrated_from" not in again
        sim2 = Simulator.load(second)
        assert {b.id for b in sim2.blocks} == {b.id for b in sim.blocks}


class TestNumericalEquivalence:
    """ADR-0079 §(10) Stage 3: migration 前後の数値等価を基準 npz で固定する。"""

    def test_migrated_fixture_matches_v0_63_0_baseline(self) -> None:
        baseline = np.load(BASELINE_NPZ)
        times, values = run_model(migrate_to_current(fixture_0_14()))
        # times はサンプリング格子の決定的算術なので厳密一致
        assert np.array_equal(times, baseline["times"])
        # values: Mux は np.stack で同じ float64 値を束ねるだけなので、採取環境
        # (Windows、v0.63.0) では bit-identical だった。ただし A @ x の行列積と
        # solve_ivp を含むため、BLAS の違う環境 (CI の ubuntu) では最終ビットが
        # 変わりうる (test_dtypes_no_behavior_change の continuous と同じ扱い) —
        # 厳密一致ではなく極めて厳しい allclose で固定する
        np.testing.assert_allclose(
            values,
            baseline["values"],
            rtol=1e-9,
            atol=1e-12,
            err_msg=(
                f"migrated model differs from the v0.63.0 baseline (captured with numpy "
                f"{baseline['numpy_version']}, scipy {baseline['scipy_version']})"
            ),
        )

    def test_fixture_file_runs_after_load(self) -> None:
        sim = Simulator.load(FIXTURE_JSON)
        sim.run()
        assert np.asarray(sim.get_block("scope").values).shape[1] == 9
