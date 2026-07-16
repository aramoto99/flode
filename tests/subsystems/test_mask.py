"""ADR-0021 §(6)(7): Subsystem mask parameters のテスト。

カバレッジ:
  #1 declarative mask_params + default mask_values
  #2 explicit mask_values が default を上書き
  #3 placeholder ``$Kp`` が内部 block params で resolve される
  #4 未宣言の placeholder は ``BlockSpecError``
  #5 mask が port_shape を変える placeholder は拒否 (ADR-0017 整合)
  #6 round-trip: mask 付き Subsystem の save → load で placeholder + values 復元
  #7 mask なし Subsystem は byte-identical (互換性)
  #8 mask_values 更新で再 build → 新値 resolve
  #9 mask_values の不正 key で raise
  #10 不正な mask_params 宣言 (type / name / 重複) で raise
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from flode import Simulator
from flode.blocks import Gain
from flode.exceptions import BlockSpecError
from flode.subsystems import Inport, Outport, Subsystem
from flode.subsystems._mask import (
    collect_placeholder_names,
    extract_placeholder_name,
    is_placeholder,
    normalize_mask_params,
    substitute_placeholders,
)

# ---------------------------------------------------------------------------
# placeholder regex / helpers
# ---------------------------------------------------------------------------


class TestPlaceholderHelpers:
    def test_is_placeholder_true(self) -> None:
        assert is_placeholder("$Kp") is True
        assert is_placeholder("$_x") is True
        assert is_placeholder("$abc123") is True

    def test_is_placeholder_false(self) -> None:
        assert is_placeholder("Kp") is False
        assert is_placeholder("$") is False
        assert is_placeholder("$1abc") is False
        assert is_placeholder("hello $Kp") is False  # 部分マッチ NG (= 完全一致のみ)
        assert is_placeholder(2.0) is False
        assert is_placeholder(None) is False

    def test_extract_placeholder_name(self) -> None:
        assert extract_placeholder_name("$Kp") == "Kp"
        assert extract_placeholder_name("$_priv") == "_priv"
        assert extract_placeholder_name("Kp") is None

    def test_substitute_placeholders_basic(self) -> None:
        out = substitute_placeholders({"k": "$Kp"}, {"Kp": 2.0})
        assert out == {"k": 2.0}

    def test_substitute_placeholders_nested(self) -> None:
        out = substitute_placeholders({"a": [1, "$x"], "b": {"c": "$y"}}, {"x": 10, "y": 20})
        assert out == {"a": [1, 10], "b": {"c": 20}}

    def test_substitute_placeholders_unknown_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="Unresolved mask placeholder"):
            substitute_placeholders({"k": "$NoSuch"}, {})

    def test_collect_placeholder_names(self) -> None:
        names = collect_placeholder_names({"a": "$Kp", "b": [1, "$Ki"], "c": "no placeholder"})
        assert names == {"Kp", "Ki"}


# ---------------------------------------------------------------------------
# normalize_mask_params
# ---------------------------------------------------------------------------


class TestNormalizeMaskParams:
    def test_none_returns_none(self) -> None:
        assert normalize_mask_params(None) is None

    def test_empty_returns_none(self) -> None:
        assert normalize_mask_params([]) is None

    def test_single_entry(self) -> None:
        out = normalize_mask_params([{"name": "Kp", "type": "float", "default": 2.0}])
        assert out == [{"name": "Kp", "type": "float", "default": 2.0, "description": ""}]

    def test_invalid_type_rejected(self) -> None:
        with pytest.raises(BlockSpecError, match="must be 'float'/'int'/'bool'"):
            normalize_mask_params([{"name": "Kp", "type": "ndarray", "default": []}])

    def test_duplicate_name_rejected(self) -> None:
        with pytest.raises(BlockSpecError, match="duplicated"):
            normalize_mask_params(
                [
                    {"name": "Kp", "type": "float", "default": 1.0},
                    {"name": "Kp", "type": "float", "default": 2.0},
                ]
            )

    def test_invalid_identifier_rejected(self) -> None:
        with pytest.raises(BlockSpecError, match="valid identifier"):
            normalize_mask_params([{"name": "1Kp", "type": "float", "default": 1.0}])

    def test_non_list_rejected(self) -> None:
        with pytest.raises(BlockSpecError, match="must be a list"):
            normalize_mask_params({"name": "Kp"})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Subsystem mask integration
# ---------------------------------------------------------------------------


def _build_mask_pi_subsystem_dict(
    *,
    sub_id: str = "pi",
    mask_values: dict[str, float] | None = None,
    inner_kp_param: str = "$Kp",
) -> dict:
    """JSON 形式の Subsystem dict (= ADR-0019 GUI が PUT する形)。テスト用 helper。

    マスク Subsystem の placeholder 機能は **JSON 経路** (= `Subsystem._from_dict`) でのみ
    Phase 3 で正式サポート (ADR-0021 §(6))。プログラム的に ``Gain(k="$Kp")`` で構築する
    のは ``float("$Kp")`` で失敗するため、テストはこの helper の dict 経由で行う。
    """
    return {
        "id": sub_id,
        "type": "flode.subsystems.subsystem.Subsystem",
        "params": {
            "n_inputs": 1,
            "n_outputs": 1,
            "mask_params": [
                {"name": "Kp", "type": "float", "default": 2.0, "description": "Proportional gain"}
            ],
            **({"mask_values": dict(mask_values)} if mask_values is not None else {}),
            "blocks": [
                {
                    "id": "Inport_0",
                    "type": "flode.subsystems.ports.Inport",
                    "params": {"port_idx": 0},
                },
                {
                    "id": "g_kp",
                    "type": "flode.blocks.mathops.Gain",
                    "params": {"k": inner_kp_param},
                },
                {
                    "id": "Outport_0",
                    "type": "flode.subsystems.ports.Outport",
                    "params": {"port_idx": 0},
                },
            ],
            "connections": [
                {"src": "Inport_0", "src_idx": 0, "dst": "g_kp", "dst_idx": 0},
                {"src": "g_kp", "src_idx": 0, "dst": "Outport_0", "dst_idx": 0},
            ],
        },
    }


def _instantiate_mask_subsystem(spec: dict) -> Subsystem:
    """Subsystem._from_dict 経由で mask Subsystem を構築する。"""
    return Subsystem._from_dict(id=spec["id"], **spec["params"])


class TestSubsystemMask:
    def test_default_mask_values_from_declared_defaults(self) -> None:
        sub = _instantiate_mask_subsystem(_build_mask_pi_subsystem_dict())
        assert sub.mask_values == {"Kp": 2.0}
        # 内部 Gain は default Kp で resolve 済
        sub._build()
        assert sub.get_block("g_kp").k == 2.0

    def test_explicit_mask_values_override_defaults(self) -> None:
        sub = _instantiate_mask_subsystem(_build_mask_pi_subsystem_dict(mask_values={"Kp": 5.0}))
        assert sub.mask_values == {"Kp": 5.0}
        sub._build()
        g = sub.get_block("g_kp")
        assert g.k == 5.0
        # placeholder は _unresolved_params に保存されている
        assert g._unresolved_params == {"k": "$Kp"}

    def test_unknown_mask_value_key_raises(self) -> None:
        with pytest.raises(BlockSpecError, match="not declared in mask_params"):
            Subsystem(
                id="sub",
                mask_params=[{"name": "Kp", "type": "float", "default": 1.0}],
                mask_values={"NoSuch": 5.0},
            )

    def test_unresolved_placeholder_raises_at_load(self) -> None:
        spec = _build_mask_pi_subsystem_dict(inner_kp_param="$Ki")
        # ADR-0021 code-reviewer MUST: 未宣言の placeholder は _from_dict 内で
        # collect_placeholder_names 経由の早期 check で raise (declared と reference の
        # set 比較)。``Unresolved mask placeholder`` 文字列の resolve 経路よりこちらが先。
        with pytest.raises(BlockSpecError, match="undefined mask placeholder"):
            _instantiate_mask_subsystem(spec)

    def test_set_mask_value_triggers_rebuild(self) -> None:
        sub = _instantiate_mask_subsystem(_build_mask_pi_subsystem_dict())
        sub._build()
        assert sub.get_block("g_kp").k == 2.0
        sub.set_mask_value("Kp", 10.0)
        sub._build()
        # 再 build 後は新値が反映される
        assert sub.get_block("g_kp").k == 10.0

    def test_port_shape_changing_placeholder_rejected(self) -> None:
        """ADR-0017 静的 port_shape 宣言: マスクで port 数を変える placeholder は拒否。

        まず ``Mux(n=$N)`` + ``mask_values={"N": 2}`` で build (= Mux(n=2) として
        instantiate)、次に ``set_mask_value("N", 3)`` で再 build すると Mux(n=3) は
        port_shapes_out=((3,),) になり旧 Mux((2,),) と不一致 → ``BlockSpecError``。
        """
        spec = {
            "id": "msub",
            "type": "flode.subsystems.subsystem.Subsystem",
            "params": {
                "n_inputs": 2,
                "n_outputs": 1,
                "port_shapes_in": [[], []],
                "port_shapes_out": [[2]],
                "mask_params": [{"name": "N", "type": "int", "default": 2}],
                "mask_values": {"N": 2},
                "blocks": [
                    {
                        "id": "Inport_0",
                        "type": "flode.subsystems.ports.Inport",
                        "params": {"port_idx": 0},
                    },
                    {
                        "id": "Inport_1",
                        "type": "flode.subsystems.ports.Inport",
                        "params": {"port_idx": 1},
                    },
                    {"id": "m", "type": "flode.blocks.routing.Mux", "params": {"n": "$N"}},
                    {
                        "id": "Outport_0",
                        "type": "flode.subsystems.ports.Outport",
                        "params": {"port_idx": 0, "port_shape": [2]},
                    },
                ],
                "connections": [
                    {"src": "Inport_0", "src_idx": 0, "dst": "m", "dst_idx": 0},
                    {"src": "Inport_1", "src_idx": 0, "dst": "m", "dst_idx": 1},
                    {"src": "m", "src_idx": 0, "dst": "Outport_0", "dst_idx": 0},
                ],
            },
        }
        sub = _instantiate_mask_subsystem(spec)
        sub._build()  # 初回 (n=2) は OK
        sub.set_mask_value("N", 3)
        # 再 build で Mux(n=3) port_shapes_out=((3,),) になり旧 ((2,),) と mismatch
        with pytest.raises(BlockSpecError, match="changed port_shape"):
            sub._build()


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------


class TestMaskJsonRoundTrip:
    def _full_model_dict(self, sub_spec: dict, *, model_id: str = "test") -> dict:
        return {
            "schema_version": "0.6",
            "metadata": {"name": model_id, "tool": "flode test"},
            "simulator": {
                "t_end": 0.05,
                "dt": 0.01,
                "solver": "RK45",
                "rtol": 1e-6,
                "atol": 1e-9,
                "dt_base": None,
            },
            "blocks": [sub_spec],
            "connections": [],
        }

    def test_mask_subsystem_json_roundtrip(self, tmp_path: Path) -> None:
        sub_spec = _build_mask_pi_subsystem_dict(mask_values={"Kp": 4.0})
        path = tmp_path / "mask.flw.json"
        path.write_text(json.dumps(self._full_model_dict(sub_spec)), encoding="utf-8")

        sim = Simulator.load(path)
        sub = sim.get_block("pi")
        assert sub.mask_params == [
            {"name": "Kp", "type": "float", "default": 2.0, "description": "Proportional gain"}
        ]
        assert sub.mask_values == {"Kp": 4.0}
        sub._build()
        assert sub.get_block("g_kp").k == 4.0

        # save → 再 load しても placeholder が round-trip する
        out = tmp_path / "rt.flw.json"
        sim.save(out)
        data2 = json.loads(out.read_text(encoding="utf-8"))
        gain_entry = next(b for b in data2["blocks"][0]["params"]["blocks"] if b["id"] == "g_kp")
        assert gain_entry["params"]["k"] == "$Kp"
        assert data2["blocks"][0]["params"]["mask_values"] == {"Kp": 4.0}

    def test_mask_subsystem_simulation(self, tmp_path: Path) -> None:
        """mask 値が反映されてシミュレーション動作する end-to-end。"""
        sub_spec = _build_mask_pi_subsystem_dict(mask_values={"Kp": 3.0})
        sub_spec["id"] = "amp"
        # Constant + Subsystem + Scope の構成
        model = {
            "schema_version": "0.6",
            "simulator": {
                "t_end": 0.05,
                "dt": 0.01,
                "solver": "RK45",
                "rtol": 1e-6,
                "atol": 1e-9,
                "dt_base": None,
            },
            "blocks": [
                {"id": "c", "type": "flode.blocks.sources.Constant", "params": {"value": 1.0}},
                sub_spec,
                {"id": "sc", "type": "flode.blocks.sinks.Scope", "params": {"n_inputs": 1}},
            ],
            "connections": [
                {"src": "c", "src_idx": 0, "dst": "amp", "dst_idx": 0},
                {"src": "amp", "src_idx": 0, "dst": "sc", "dst_idx": 0},
            ],
        }
        path = tmp_path / "sim.flw.json"
        path.write_text(json.dumps(model), encoding="utf-8")
        sim = Simulator.load(path)
        sim.run()
        sc = sim.get_block("sc")
        arr = np.asarray(sc.values).reshape(-1)
        # 1.0 * 3.0 (= mask Kp) = 3.0
        np.testing.assert_allclose(arr, 3.0 * np.ones_like(arr))

    def test_mask_less_subsystem_remains_byte_identical(self, tmp_path: Path) -> None:
        """mask_params なしの Subsystem は JSON に mask キーを出さない。"""
        sub = Subsystem(id="sub")
        sub.add(Inport(port_idx=0))
        sub.add(Gain(k=2.0, id="g"))
        sub.add(Outport(port_idx=0))
        sub.connect("Inport_0", "g")
        sub.connect("g", "Outport_0")
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(sub)
        path = tmp_path / "no_mask.flw.json"
        sim.save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        sub_entry = next(b for b in data["blocks"] if b["id"] == "sub")
        # mask_params / mask_values は JSON に含まれない
        assert "mask_params" not in sub_entry["params"]
        assert "mask_values" not in sub_entry["params"]


# ---------------------------------------------------------------------------
# Schema version migration 0.5 → 0.6
# ---------------------------------------------------------------------------


class TestSchemaMigration:
    def test_load_legacy_0_5_via_migration(self, tmp_path: Path) -> None:
        path = tmp_path / "legacy_0_5.flw.json"
        legacy = {
            "schema_version": "0.5",
            "simulator": {
                "t_end": 0.05,
                "dt": 0.01,
                "solver": "RK45",
                "rtol": 1e-6,
                "atol": 1e-9,
                "dt_base": None,
            },
            "blocks": [
                {
                    "id": "src",
                    "type": "flode.blocks.sources.Constant",
                    "params": {"value": 1.0},
                }
            ],
            "connections": [],
        }
        path.write_text(json.dumps(legacy), encoding="utf-8")
        sim = Simulator.load(path)
        assert len(sim.blocks) == 1
