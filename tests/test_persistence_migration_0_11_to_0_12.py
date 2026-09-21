"""v0.56.0 (output_type 撤去、ADR-0077 D-5 撤回): schema 0.11 → 0.12 migration。

``Cast`` / ``Constant`` の ``output_type`` (値の意味論、旧 SPEC-0026) を
**数値等価な新語彙**へ自動変換する:

* Constant: 実効値を ``value`` にベイク (int = 偶数丸め / bool = 0 or 1)
* Cast("float") → ``Cast(dtype="float64")``
* Cast("int") → ``Rounding(mode="round")``
* Cast("bool") → ``CompareToZero(op="!=")``
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from flode import Simulator
from flode.core.persistence import (
    _builtin_migrate_0_11_to_0_12,
    migrate_to_current,
)

# CURRENT_SCHEMA_VERSION の pin は最新の migration テストファイル
# (test_persistence_migration_0_12_to_0_13.py) に集約


def _model_0_11(
    blocks: list[dict[str, Any]], connections: list[Any] | None = None
) -> dict[str, Any]:
    return {
        "schema_version": "0.11",
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


def _migrated_block(data: dict[str, Any], block_id: str) -> dict[str, Any]:
    out = _builtin_migrate_0_11_to_0_12(data)
    assert out["schema_version"] == "0.12"
    by_id = {b["id"]: b for b in out["blocks"]}
    return by_id[block_id]


class TestConstantBake:
    @pytest.mark.parametrize(
        ("raw", "baked"),
        [
            (2.7, 3.0),
            (2.5, 2.0),  # 旧 output_type="int" は偶数丸め (trunc ではない)
            (-2.5, -2.0),
        ],
    )
    def test_int_bakes_round_half_even(self, raw: float, baked: float) -> None:
        data = _model_0_11(
            [
                {
                    "id": "c",
                    "type": "flode.blocks.sources.Constant",
                    "params": {"value": raw, "output_type": "int"},
                }
            ]
        )
        b = _migrated_block(data, "c")
        assert b["params"] == {"value": baked}

    @pytest.mark.parametrize(("raw", "baked"), [(0.4, 1.0), (-3.2, 1.0), (0.0, 0.0)])
    def test_bool_bakes_zero_one(self, raw: float, baked: float) -> None:
        data = _model_0_11(
            [
                {
                    "id": "c",
                    "type": "flode.blocks.sources.Constant",
                    "params": {"value": raw, "output_type": "bool"},
                }
            ]
        )
        b = _migrated_block(data, "c")
        assert b["params"] == {"value": baked}

    def test_float_only_drops_the_key(self) -> None:
        data = _model_0_11(
            [
                {
                    "id": "c",
                    "type": "flode.blocks.sources.Constant",
                    "params": {"value": 1.5, "output_type": "float"},
                }
            ]
        )
        b = _migrated_block(data, "c")
        assert b["params"] == {"value": 1.5}

    def test_constant_with_declared_dtype_is_kept(self) -> None:
        # 0.11 で dtype 宣言済み (旧 Q2 排他: output_type は "float" のはず)
        data = _model_0_11(
            [
                {
                    "id": "c",
                    "type": "flode.blocks.sources.Constant",
                    "params": {"value": 2.7, "output_type": "float", "dtype": "int32"},
                }
            ]
        )
        b = _migrated_block(data, "c")
        assert b["params"] == {"value": 2.7, "dtype": "int32"}


class TestCastConversion:
    def test_float_becomes_dtype_float64(self) -> None:
        data = _model_0_11(
            [
                {
                    "id": "k",
                    "type": "flode.blocks.cast.Cast",
                    "params": {"output_type": "float"},
                }
            ]
        )
        b = _migrated_block(data, "k")
        assert b["type"] == "flode.blocks.cast.Cast"
        assert b["params"] == {"dtype": "float64"}

    def test_cast_without_output_type_key_gets_default_dtype(self) -> None:
        data = _model_0_11([{"id": "k", "type": "flode.blocks.cast.Cast", "params": {}}])
        b = _migrated_block(data, "k")
        assert b["params"] == {"dtype": "float64"}

    def test_cast_with_declared_dtype_is_kept(self) -> None:
        data = _model_0_11(
            [
                {
                    "id": "k",
                    "type": "flode.blocks.cast.Cast",
                    "params": {"output_type": "float", "dtype": "int32"},
                }
            ]
        )
        b = _migrated_block(data, "k")
        assert b["type"] == "flode.blocks.cast.Cast"
        assert b["params"] == {"dtype": "int32"}

    def test_int_becomes_rounding_round(self) -> None:
        data = _model_0_11(
            [
                {
                    "id": "k",
                    "type": "flode.blocks.cast.Cast",
                    "params": {"output_type": "int"},
                }
            ]
        )
        b = _migrated_block(data, "k")
        assert b["type"] == "flode.blocks.rounding.Rounding"
        assert b["params"] == {"mode": "round"}

    def test_bool_becomes_compare_to_zero_ne(self) -> None:
        data = _model_0_11(
            [
                {
                    "id": "k",
                    "type": "flode.blocks.cast.Cast",
                    "params": {"output_type": "bool"},
                }
            ]
        )
        b = _migrated_block(data, "k")
        assert b["type"] == "flode.blocks.mathops.CompareToZero"
        assert b["params"] == {"op": "!="}

    def test_id_and_extra_entry_fields_survive_type_swap(self) -> None:
        data = _model_0_11(
            [
                {
                    "id": "k",
                    "name": "my cast",
                    "type": "flode.blocks.cast.Cast",
                    "params": {"output_type": "bool"},
                }
            ]
        )
        b = _migrated_block(data, "k")
        assert b["id"] == "k"
        assert b["name"] == "my cast"


class TestIdentityCastDeletion:
    """dtype 宣言があるモデルでは恒等 Cast を削除 + 直結する (security MUST-1)。

    0.11 の恒等 Cast は dtype も素通しだったため、Cast(dtype="float64") 化すると
    宣言 dtype 経路上で float64 強制点になり結果が変わる。削除が唯一の完全等価。
    """

    @staticmethod
    def _declared_model_with_identity_cast() -> dict[str, Any]:
        return _model_0_11(
            [
                {
                    "id": "c1",
                    "type": "flode.blocks.sources.Constant",
                    "params": {"value": 200.0, "dtype": "uint8"},
                },
                {
                    "id": "c2",
                    "type": "flode.blocks.sources.Constant",
                    "params": {"value": 200.0, "dtype": "uint8"},
                },
                {
                    "id": "k",
                    "type": "flode.blocks.cast.Cast",
                    "params": {"output_type": "float"},
                },
                {
                    "id": "s",
                    "type": "flode.blocks.mathops.Sum",
                    "params": {"signs": "++"},
                },
                {
                    "id": "sc",
                    "type": "flode.blocks.sinks.Scope",
                    "params": {"n_inputs": 1},
                },
            ],
            connections=[
                {"src": "c1", "src_idx": 0, "dst": "k", "dst_idx": 0},
                {"src": "k", "src_idx": 0, "dst": "s", "dst_idx": 0},
                {"src": "c2", "src_idx": 0, "dst": "s", "dst_idx": 1},
                {"src": "s", "src_idx": 0, "dst": "sc", "dst_idx": 0},
            ],
        )

    def test_identity_cast_is_deleted_and_rewired(self) -> None:
        data = self._declared_model_with_identity_cast()
        data["layout"] = {"k": {"x": 1.0, "y": 2.0}, "s": {"x": 3.0, "y": 4.0}}
        out = _builtin_migrate_0_11_to_0_12(data)
        ids = [b["id"] for b in out["blocks"]]
        assert "k" not in ids
        assert {(c["src"], c["dst"]) for c in out["connections"]} == {
            ("c1", "s"),
            ("c2", "s"),
            ("s", "sc"),
        }
        rewired = next(c for c in out["connections"] if c["src"] == "c1")
        assert rewired["dst_idx"] == 0  # 下流ポートは維持
        assert "k" not in out["layout"]
        assert out["layout"]["s"] == {"x": 3.0, "y": 4.0}

    def test_uint8_wrap_semantics_preserved(self, tmp_path: Path) -> None:
        """security MUST-1 の実測ケース: 0.11 (dtype 素通し) では uint8 の
        200+200 = 144 (wrap)。migration 後も 400 ではなく 144 のまま。"""
        path = tmp_path / "old.flw.json"
        path.write_text(json.dumps(self._declared_model_with_identity_cast()), encoding="utf-8")
        sim = Simulator.load(path)
        sim.run()
        vals = np.asarray(sim.get_block("sc").values)[:, 0]
        assert np.all(vals == 144.0)

    def test_identity_cast_chain_resolves_transitively(self) -> None:
        data = _model_0_11(
            [
                {
                    "id": "c",
                    "type": "flode.blocks.sources.Constant",
                    "params": {"value": 1.0, "dtype": "int32"},
                },
                {
                    "id": "k1",
                    "type": "flode.blocks.cast.Cast",
                    "params": {"output_type": "float"},
                },
                {
                    "id": "k2",
                    "type": "flode.blocks.cast.Cast",
                    "params": {"output_type": "float"},
                },
                {
                    "id": "sc",
                    "type": "flode.blocks.sinks.Scope",
                    "params": {"n_inputs": 1},
                },
            ],
            connections=[
                {"src": "c", "src_idx": 0, "dst": "k1", "dst_idx": 0},
                {"src": "k1", "src_idx": 0, "dst": "k2", "dst_idx": 0},
                {"src": "k2", "src_idx": 0, "dst": "sc", "dst_idx": 0},
            ],
        )
        out = _builtin_migrate_0_11_to_0_12(data)
        ids = [b["id"] for b in out["blocks"]]
        assert "k1" not in ids and "k2" not in ids
        assert [(c["src"], c["dst"]) for c in out["connections"]] == [("c", "sc")]

    def test_unconnected_identity_cast_drops_downstream_edge(self) -> None:
        # 上流を持たない恒等 Cast: 未接続入力 = float64 の 0.0 (0.11 と同じ) に
        # なるよう、下流への接続ごと削除する
        data = _model_0_11(
            [
                {
                    "id": "d",
                    "type": "flode.blocks.sources.Constant",
                    "params": {"value": 1.0, "dtype": "int32"},
                },
                {
                    "id": "k",
                    "type": "flode.blocks.cast.Cast",
                    "params": {"output_type": "float"},
                },
                {
                    "id": "sc",
                    "type": "flode.blocks.sinks.Scope",
                    "params": {"n_inputs": 1},
                },
            ],
            connections=[
                {"src": "k", "src_idx": 0, "dst": "sc", "dst_idx": 0},
            ],
        )
        out = _builtin_migrate_0_11_to_0_12(data)
        assert [b["id"] for b in out["blocks"]] == ["d", "sc"]
        assert out["connections"] == []

    def test_unhashable_ids_and_endpoints_do_not_crash(self) -> None:
        """security SHOULD-4: 削除対象の恒等 Cast と同スコープに unhashable な
        id / 結線端点 (JSON の object / array) があっても例外にしない。"""
        data = _model_0_11(
            [
                {
                    "id": "c",
                    "type": "flode.blocks.sources.Constant",
                    "params": {"value": 1.0, "dtype": "int32"},
                },
                {
                    "id": "k",
                    "type": "flode.blocks.cast.Cast",
                    "params": {"output_type": "float"},
                },
                {
                    "id": ["bad"],  # unhashable な id
                    "type": "flode.blocks.mathops.Gain",
                    "params": {"k": 2.0},
                },
            ],
            connections=[
                {"src": "c", "src_idx": 0, "dst": "k", "dst_idx": 0},
                {"src": "k", "src_idx": 0, "dst": {"evil": 1}, "dst_idx": 0},
                {"src": {"evil": 2}, "src_idx": 0, "dst": "c", "dst_idx": 0},
            ],
        )
        out = _builtin_migrate_0_11_to_0_12(data)  # 例外にならないこと
        assert out["schema_version"] == "0.12"
        ids = [b["id"] for b in out["blocks"]]
        assert "k" not in ids
        assert ["bad"] in ids  # 無関係な壊れ entry は温存 (load 側で検証される)

    def test_branch_waypoints_of_deleted_cast_are_cleaned(self) -> None:
        data = self._declared_model_with_identity_cast()
        data["branch_waypoints"] = {
            "k:0": [{"x": 1.0, "y": 2.0}],
            "s:0": [{"x": 3.0, "y": 4.0}],
        }
        out = _builtin_migrate_0_11_to_0_12(data)
        assert "k:0" not in out["branch_waypoints"]
        assert "s:0" in out["branch_waypoints"]

    def test_without_declarations_identity_cast_is_converted_not_deleted(self) -> None:
        # dtype 宣言ゼロのモデルは視覚的な互換を優先し Cast(dtype="float64") 化
        # (全 float64 での bit-identical は test_migrated_identity_cast_model_
        # is_bit_identical で固定)
        data = _model_0_11(
            [
                {
                    "id": "k",
                    "type": "flode.blocks.cast.Cast",
                    "params": {"output_type": "float"},
                }
            ]
        )
        b = _migrated_block(data, "k")
        assert b["params"] == {"dtype": "float64"}


class TestUnbakeableConstants:
    """ベイク不能な Constant 値は生値のまま WARNING (security SHOULD-1/2)。"""

    def test_mask_placeholder_value_is_kept_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        data = _model_0_11(
            [
                {
                    "id": "c",
                    "type": "flode.blocks.sources.Constant",
                    "params": {"value": "$Kp", "output_type": "int"},
                }
            ]
        )
        with caplog.at_level(logging.WARNING, logger="flode.persistence.migrate_0_11_to_0_12"):
            b = _migrated_block(data, "c")
        assert b["params"] == {"value": "$Kp"}
        assert any("without baking" in r.message for r in caplog.records)

    def test_huge_integer_value_does_not_crash(self, caplog: pytest.LogCaptureFixture) -> None:
        # JSON は任意精度整数を許す → float() の OverflowError を握って生値温存
        huge = int("9" * 400)
        data = _model_0_11(
            [
                {
                    "id": "c",
                    "type": "flode.blocks.sources.Constant",
                    "params": {"value": huge, "output_type": "int"},
                }
            ]
        )
        with caplog.at_level(logging.WARNING, logger="flode.persistence.migrate_0_11_to_0_12"):
            b = _migrated_block(data, "c")
        assert b["params"] == {"value": huge}
        assert any("overflow" in r.message for r in caplog.records)


class TestRecursionAndScope:
    def test_nested_subsystem_blocks_are_migrated(self) -> None:
        data = _model_0_11(
            [
                {
                    "id": "sub",
                    "type": "flode.subsystems.subsystem.Subsystem",
                    "params": {
                        "blocks": [
                            {
                                "id": "inner_c",
                                "type": "flode.blocks.sources.Constant",
                                "params": {"value": 2.7, "output_type": "int"},
                            },
                            {
                                "id": "inner_k",
                                "type": "flode.blocks.cast.Cast",
                                "params": {"output_type": "bool"},
                            },
                        ],
                        "connections": [],
                    },
                }
            ]
        )
        out = _builtin_migrate_0_11_to_0_12(data)
        inner = {b["id"]: b for b in out["blocks"][0]["params"]["blocks"]}
        assert inner["inner_c"]["params"] == {"value": 3.0}
        assert inner["inner_k"]["type"] == "flode.blocks.mathops.CompareToZero"

    def test_third_party_and_other_builtin_blocks_untouched(self) -> None:
        gain = {
            "id": "g",
            "type": "flode.blocks.mathops.Gain",
            "params": {"k": 2.0},
        }
        third = {
            "id": "x",
            "type": "myapp.blocks.Custom",
            "params": {"output_type": "int"},  # 同名 param でも触らない
        }
        data = _model_0_11([dict(gain), dict(third)])
        out = _builtin_migrate_0_11_to_0_12(data)
        assert out["blocks"][0] == gain
        assert out["blocks"][1] == third

    def test_top_level_input_version_not_mutated(self) -> None:
        data = _model_0_11([])
        _builtin_migrate_0_11_to_0_12(data)
        assert data["schema_version"] == "0.11"


class TestChainAndEquivalence:
    def test_chain_from_0_11_reaches_current(self) -> None:
        data = _model_0_11([])
        out = migrate_to_current(data)
        assert out["schema_version"] == "0.15"
        assert out["_migrated_from"] == "0.11"

    def test_migrated_model_runs_with_identical_values(self, tmp_path: Path) -> None:
        """数値等価の実測固定 (ADR-0077 Amendment 申し送り (1))。

        旧 output_type チェーン (Constant int → Cast bool → Scope) を 0.11 の
        JSON から load し、変換後モデルが旧経路と同じ値を出すことを固定する。
        """
        model = _model_0_11(
            [
                {
                    "id": "c",
                    "type": "flode.blocks.sources.Constant",
                    "params": {"value": 2.7, "output_type": "int"},
                },
                {
                    "id": "k",
                    "type": "flode.blocks.cast.Cast",
                    "params": {"output_type": "bool"},
                },
                {
                    "id": "sc",
                    "type": "flode.blocks.sinks.Scope",
                    "params": {"n_inputs": 1},
                },
            ],
            connections=[
                {"src": "c", "src_idx": 0, "dst": "k", "dst_idx": 0},
                {"src": "k", "src_idx": 0, "dst": "sc", "dst_idx": 0},
            ],
        )
        path = tmp_path / "old.flw.json"
        path.write_text(json.dumps(model), encoding="utf-8")
        sim = Simulator.load(path)
        sim.run()
        vals = np.asarray(sim.get_block("sc").values)[:, 0]
        # 旧経路: Constant(2.7, int) → 3.0、Cast(bool) → 1.0 (全時刻)
        assert np.all(vals == 1.0)

    def test_nested_identity_cast_in_subsystem_still_runs(self, tmp_path: Path) -> None:
        """Subsystem 内の旧 Cast("float") は Cast(dtype="float64") になるが、
        island 内の float64 宣言は許可されるため旧モデルはそのまま動く
        (v0.56.0 の reject_nested_dtype_declarations 緩和の回帰テスト)。"""
        model = _model_0_11(
            [
                {
                    "id": "c",
                    "type": "flode.blocks.sources.Constant",
                    "params": {"value": 1.5, "output_type": "float"},
                },
                {
                    "id": "sub",
                    "type": "flode.subsystems.subsystem.Subsystem",
                    "params": {
                        "blocks": [
                            {
                                "id": "ip",
                                "type": "flode.subsystems.ports.Inport",
                                "params": {"port_idx": 0},
                            },
                            {
                                "id": "k",
                                "type": "flode.blocks.cast.Cast",
                                "params": {"output_type": "float"},
                            },
                            {
                                "id": "op",
                                "type": "flode.subsystems.ports.Outport",
                                "params": {"port_idx": 0},
                            },
                        ],
                        "connections": [
                            {"src": "ip", "src_idx": 0, "dst": "k", "dst_idx": 0},
                            {"src": "k", "src_idx": 0, "dst": "op", "dst_idx": 0},
                        ],
                    },
                },
                {
                    "id": "sc",
                    "type": "flode.blocks.sinks.Scope",
                    "params": {"n_inputs": 1},
                },
            ],
            connections=[
                {"src": "c", "src_idx": 0, "dst": "sub", "dst_idx": 0},
                {"src": "sub", "src_idx": 0, "dst": "sc", "dst_idx": 0},
            ],
        )
        path = tmp_path / "old.flw.json"
        path.write_text(json.dumps(model), encoding="utf-8")
        sim = Simulator.load(path)
        sim.run()
        vals = np.asarray(sim.get_block("sc").values)[:, 0]
        assert np.all(vals == 1.5)

    def test_migrated_identity_cast_model_is_bit_identical(self, tmp_path: Path) -> None:
        """Cast("float") → Cast(dtype="float64") は SM-A → SM-B の経路切替を
        起こすが、全 float64 モデルでは bit-identical (実測固定)。"""
        model = _model_0_11(
            [
                {
                    "id": "c",
                    "type": "flode.blocks.sources.Constant",
                    "params": {"value": 1.5, "output_type": "float"},
                },
                {
                    "id": "k",
                    "type": "flode.blocks.cast.Cast",
                    "params": {"output_type": "float"},
                },
                {
                    "id": "sc",
                    "type": "flode.blocks.sinks.Scope",
                    "params": {"n_inputs": 1},
                },
            ],
            connections=[
                {"src": "c", "src_idx": 0, "dst": "k", "dst_idx": 0},
                {"src": "k", "src_idx": 0, "dst": "sc", "dst_idx": 0},
            ],
        )
        path = tmp_path / "old.flw.json"
        path.write_text(json.dumps(model), encoding="utf-8")
        sim = Simulator.load(path)
        sim.run()
        vals = np.asarray(sim.get_block("sc").values)[:, 0]
        assert np.all(vals == 1.5)  # bit 表現も同一 (1.5 は二進で正確)
