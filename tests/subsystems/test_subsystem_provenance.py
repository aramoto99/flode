"""Subsystem とその内部ブロックの ``provenance`` (ライブラリ由来) 永続化テスト (ADR-0080 §A3)。

内部ブロックの出力経路は複数ある (通常の ``_params`` / マスク placeholder の
``_unresolved_params`` / 入れ子 Subsystem の ``to_dict`` / ``_build`` がキャッシュする
``_params["blocks"]`` / ``set_mask_value`` 後の再構築) ので、全経路で由来が落ちない
ことを固定する。トップレベルと浅い検証の単体は ``tests/core/test_provenance.py``。
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from flode import Inport, Outport, Simulator, Subsystem
from flode.blocks import Gain
from flode.blocks.pythonfunc import DEFAULT_CODE, compute_python_digest
from flode.core.persistence import CURRENT_SCHEMA_VERSION
from flode.core.provenance import PROVENANCE_KEY
from flode.core.signals import resolve_signals

_PROVENANCE_LOGGER = "flode.core.provenance"
_SUBSYSTEM_TYPE = "flode.subsystems.subsystem.Subsystem"

_OUTER_PROV: dict[str, Any] = {
    "library": "user",
    "library_uid": "8c1e2f0a-0000-4000-8000-000000000001",
    "entry": "plant",
    "revision": 4,
}
_MID_PROV: dict[str, Any] = {"library": "user", "entry": "stage", "revision": 2}
_GAIN_PROV: dict[str, Any] = {"library": "std", "entry": "gain_block", "revision": 1}


def _with(entry: dict[str, Any], provenance: Any | None) -> dict[str, Any]:
    if provenance is not None:
        entry[PROVENANCE_KEY] = copy.deepcopy(provenance)
    return entry


def _port(kind: str, block_id: str) -> dict[str, Any]:
    return {"id": block_id, "type": f"flode.subsystems.ports.{kind}", "params": {"port_idx": 0}}


def _sub(
    block_id: str,
    middle: dict[str, Any],
    *,
    provenance: Any | None = None,
    mask: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inport → ``middle`` → Outport の Subsystem entry を作る。"""
    params: dict[str, Any] = {}
    if mask is not None:
        params["mask_params"] = [
            {"name": name, "type": "float", "default": 1.0, "description": ""} for name in mask
        ]
        params["mask_values"] = dict(mask)
    params["blocks"] = [_port("Inport", "i"), middle, _port("Outport", "o")]
    params["connections"] = [
        {"src": "i", "src_idx": 0, "dst": middle["id"], "dst_idx": 0},
        {"src": middle["id"], "src_idx": 0, "dst": "o", "dst_idx": 0},
    ]
    return _with({"id": block_id, "type": _SUBSYSTEM_TYPE, "params": params}, provenance)


def _gain(k: Any, provenance: Any | None = None) -> dict[str, Any]:
    return _with({"id": "g", "type": "flode.blocks.mathops.Gain", "params": {"k": k}}, provenance)


def _model(sub_entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "simulator": {
            "t_end": 0.05,
            "dt": 0.01,
            "solver": "RK45",
            "rtol": 1e-6,
            "atol": 1e-9,
            "dt_base": None,
        },
        "blocks": [
            {"id": "c", "type": "flode.blocks.sources.Constant", "params": {"value": 2.0}},
            sub_entry,
            {"id": "sc", "type": "flode.blocks.sinks.Scope", "params": {"n_inputs": 1}},
        ],
        "connections": [
            {"src": "c", "src_idx": 0, "dst": sub_entry["id"], "dst_idx": 0},
            {"src": sub_entry["id"], "src_idx": 0, "dst": "sc", "dst_idx": 0},
        ],
    }


def _strip(value: Any) -> Any:
    """入れ子を含む全 entry から ``provenance`` キーを取り除いたコピーを返す。"""
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k != PROVENANCE_KEY}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _save(sim: Simulator, path: Path) -> dict[str, Any]:
    sim.save(path)
    loaded: dict[str, Any] = json.loads(path.read_text("utf-8"))
    return loaded


def _assert_stable_round_trip(model: dict[str, Any], tmp_path: Path) -> dict[str, Any]:
    """load → save → load → save が byte 一致し、Subsystem entry が入力と同じであること。"""
    sim = Simulator.from_dict(copy.deepcopy(model))
    first = _save(sim, tmp_path / "a.flw.json")
    Simulator.load(tmp_path / "a.flw.json").save(tmp_path / "b.flw.json")
    assert (tmp_path / "a.flw.json").read_bytes() == (tmp_path / "b.flw.json").read_bytes()
    # index 1 = 検査対象の Subsystem (前後の Constant / Scope は既定 params が展開される)
    assert first["blocks"][1] == model["blocks"][1]
    return first


# ---------------------------------------------------------------------------
# round-trip (全出力経路)
# ---------------------------------------------------------------------------


class TestSubsystemRoundTrip:
    def test_inner_block_provenance(self, tmp_path: Path) -> None:
        _assert_stable_round_trip(_model(_sub("outer", _gain(3.0, _GAIN_PROV))), tmp_path)

    def test_subsystem_itself_and_inner(self, tmp_path: Path) -> None:
        model = _model(_sub("outer", _gain(3.0, _GAIN_PROV), provenance=_OUTER_PROV))
        saved = _assert_stable_round_trip(model, tmp_path)
        outer = saved["blocks"][1]
        assert list(outer) == ["id", "type", "params", PROVENANCE_KEY]
        assert list(outer["params"]["blocks"][1])[-1] == PROVENANCE_KEY

    def test_two_level_nesting(self, tmp_path: Path) -> None:
        mid = _sub("mid", _gain(3.0, _GAIN_PROV), provenance=_MID_PROV)
        model = _model(_sub("outer", mid, provenance=_OUTER_PROV))
        saved = _assert_stable_round_trip(model, tmp_path)
        outer = saved["blocks"][1]
        mid_out = outer["params"]["blocks"][1]
        assert outer[PROVENANCE_KEY] == _OUTER_PROV
        assert mid_out[PROVENANCE_KEY] == _MID_PROV
        assert mid_out["params"]["blocks"][1][PROVENANCE_KEY] == _GAIN_PROV

    def test_only_deepest_block_has_provenance(self, tmp_path: Path) -> None:
        model = _model(_sub("outer", _sub("mid", _gain(3.0, _GAIN_PROV))))
        saved = _assert_stable_round_trip(model, tmp_path)
        outer = saved["blocks"][1]
        assert PROVENANCE_KEY not in outer
        assert PROVENANCE_KEY not in outer["params"]["blocks"][1]

    def test_masked_subsystem_inner_placeholder_block(self, tmp_path: Path) -> None:
        # ``_unresolved_params`` 経路: placeholder と由来の両方が残る
        model = _model(
            _sub("outer", _gain("$Kp", _GAIN_PROV), provenance=_OUTER_PROV, mask={"Kp": 3.0})
        )
        saved = _assert_stable_round_trip(model, tmp_path)
        inner = saved["blocks"][1]["params"]["blocks"][1]
        assert inner["params"] == {"k": "$Kp"}
        assert inner[PROVENANCE_KEY] == _GAIN_PROV

    def test_masked_subsystem_inner_block_without_placeholder(self, tmp_path: Path) -> None:
        model = _model(_sub("outer", _gain(3.0, _GAIN_PROV), mask={"Kp": 3.0}))
        # mask_params 未参照の WARNING は出るがロードは通る (既存仕様)
        _assert_stable_round_trip(model, tmp_path)

    def test_python_function_inside_subsystem(self, tmp_path: Path) -> None:
        py = _with(
            {
                "id": "g",
                "type": "flode.blocks.pythonfunc.PythonFunction",
                "params": {"code": DEFAULT_CODE, "user_params": {}},
            },
            _GAIN_PROV,
        )
        _assert_stable_round_trip(_model(_sub("outer", py, provenance=_OUTER_PROV)), tmp_path)

    def test_round_trip_after_run(self, tmp_path: Path) -> None:
        # 実行時 build (``_params["blocks"]`` のキャッシュ確定) の後でも同じ出力
        mid = _sub("mid", _gain(3.0, _GAIN_PROV), provenance=_MID_PROV)
        model = _model(_sub("outer", mid, provenance=_OUTER_PROV))
        sim = Simulator.from_dict(copy.deepcopy(model))
        sim.run()
        np.testing.assert_allclose(sim.get_block("sc").values[:, 0], 6.0)
        assert _save(sim, tmp_path / "run.flw.json")["blocks"][1] == model["blocks"][1]

    def test_legacy_schema_file_keeps_inner_provenance(self) -> None:
        # 旧 schema → migration 連鎖を通っても内側の由来が落ちない
        mid = _sub("mid", _gain(3.0, _GAIN_PROV), provenance=_MID_PROV)
        model = _model(_sub("outer", mid, provenance=_OUTER_PROV))
        model["schema_version"] = "0.8"
        outer = Simulator.from_dict(model).get_block("outer")
        assert outer.to_dict() == model["blocks"][1]


class TestMaskPlaceholderDoesNotTouchProvenance:
    """由来はマスク placeholder (``"$name"``) の置換・参照検査の対象外。

    マスク付き Subsystem の内側に入れ子 Subsystem があると、その ``params.blocks`` の
    entry 群は外側マスクの置換走査を通る。由来の文字列がたまたま placeholder の形を
    していても、値を書き換えたりロードを失敗させたりしてはならない。
    """

    @pytest.mark.parametrize("text", ["$Kp", "$Undeclared"], ids=["declared", "undeclared"])
    @pytest.mark.parametrize("depth", [1, 2], ids=["direct_inner", "nested"])
    def test_placeholder_like_strings_survive_verbatim(
        self, text: str, depth: int, tmp_path: Path
    ) -> None:
        prov = {"library": text, "entry": text, "revision": 1, "note": [text]}
        middle = _gain("$Kp", prov)
        if depth == 2:
            # 入れ子側の params は具象値にする: 入れ子 Subsystem 内の placeholder は保存時に
            # 具象値へ展開される (由来とは無関係の既存挙動) ため、由来だけを比較対象にする
            middle = _sub("mid", _gain(3.0, prov), provenance=prov)
        model = _model(_sub("outer", middle, provenance=prov, mask={"Kp": 3.0}))
        _assert_stable_round_trip(model, tmp_path)

    def test_provenance_does_not_count_as_mask_reference(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # 由来の中の "$Kp" は「マスク宣言が参照されている」根拠にならない
        prov = {"library": "$Kp", "entry": "e", "revision": 1}
        model = _model(_sub("outer", _sub("mid", _gain(3.0, prov)), mask={"Kp": 3.0}))
        with caplog.at_level(logging.WARNING, logger="flode.subsystem"):
            Simulator.from_dict(model)
        assert any("not referenced" in r.getMessage() for r in caplog.records)

    def test_rebuild_after_mask_change_keeps_placeholder_like_provenance(self) -> None:
        prov = {"library": "$Kp", "entry": "$Undeclared", "revision": 1}
        mid = _sub("mid", _gain("$Kp", prov), provenance=prov)
        sim = Simulator.from_dict(_model(_sub("outer", mid, mask={"Kp": 3.0})))
        outer = sim.get_block("outer")
        assert isinstance(outer, Subsystem)
        outer.set_mask_value("Kp", 5.0)
        sim.run()
        np.testing.assert_allclose(sim.get_block("sc").values[:, 0], 10.0)
        mid_out = outer.to_dict()["params"]["blocks"][1]
        assert mid_out[PROVENANCE_KEY] == prov
        assert mid_out["params"]["blocks"][1][PROVENANCE_KEY] == prov


class TestMaskRebuildKeepsProvenance:
    """``set_mask_value`` 後の ``_resolve_mask_placeholders`` はブロックを作り直す。"""

    def test_rebuilt_leaf_block(self, tmp_path: Path) -> None:
        model = _model(
            _sub("outer", _gain("$Kp", _GAIN_PROV), provenance=_OUTER_PROV, mask={"Kp": 3.0})
        )
        sim = Simulator.from_dict(copy.deepcopy(model))
        outer = sim.get_block("outer")
        assert isinstance(outer, Subsystem)
        outer.set_mask_value("Kp", 5.0)
        sim.run()
        np.testing.assert_allclose(sim.get_block("sc").values[:, 0], 10.0)

        saved = _save(sim, tmp_path / "rebuilt.flw.json")["blocks"][1]
        assert saved[PROVENANCE_KEY] == _OUTER_PROV
        assert saved["params"]["mask_values"] == {"Kp": 5.0}
        inner = saved["params"]["blocks"][1]
        assert inner == _gain("$Kp", _GAIN_PROV)

    def test_rebuilt_nested_subsystem(self) -> None:
        mid = _sub("mid", _gain("$Kp", _GAIN_PROV), provenance=_MID_PROV)
        model = _model(_sub("outer", mid, provenance=_OUTER_PROV, mask={"Kp": 3.0}))
        sim = Simulator.from_dict(copy.deepcopy(model))
        outer = sim.get_block("outer")
        assert isinstance(outer, Subsystem)
        outer.set_mask_value("Kp", 5.0)
        sim.run()
        np.testing.assert_allclose(sim.get_block("sc").values[:, 0], 10.0)

        out = outer.to_dict()
        assert out[PROVENANCE_KEY] == _OUTER_PROV
        mid_out = out["params"]["blocks"][1]
        assert mid_out[PROVENANCE_KEY] == _MID_PROV
        assert mid_out["params"]["blocks"][1][PROVENANCE_KEY] == _GAIN_PROV


# ---------------------------------------------------------------------------
# 壊れた由来 / 由来なし
# ---------------------------------------------------------------------------


class TestBrokenInnerProvenance:
    @pytest.mark.parametrize(
        "broken",
        [
            "user/pid",
            ["user"],
            {},
            {"library": "user", "entry": "pid"},
            {"library": "user", "entry": "pid", "revision": True},
            {"library": "user", "entry": "pid", "revision": 0},
            {"library": 1, "entry": "pid", "revision": 1},
        ],
        ids=[
            "string",
            "list",
            "empty",
            "missing_revision",
            "revision_bool",
            "revision_zero",
            "library_not_str",
        ],
    )
    def test_inner_broken_is_dropped_with_warning(
        self, broken: Any, caplog: pytest.LogCaptureFixture, tmp_path: Path
    ) -> None:
        model = _model(_sub("outer", _sub("mid", _gain(3.0, broken)), provenance=_OUTER_PROV))
        with caplog.at_level(logging.WARNING, logger=_PROVENANCE_LOGGER):
            sim = Simulator.from_dict(copy.deepcopy(model))
        warnings = [r for r in caplog.records if r.name == _PROVENANCE_LOGGER]
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        assert "'g'" in message  # 壊れた由来を持つブロック
        assert "'mid'" in message  # それを内包する Subsystem

        saved = _save(sim, tmp_path / "broken.flw.json")
        outer = saved["blocks"][1]
        assert outer[PROVENANCE_KEY] == _OUTER_PROV  # 健全な由来は巻き添えにしない
        assert PROVENANCE_KEY not in outer["params"]["blocks"][1]["params"]["blocks"][1]
        sim.run()
        np.testing.assert_allclose(sim.get_block("sc").values[:, 0], 6.0)

    def test_broken_on_subsystem_entry_itself(
        self, caplog: pytest.LogCaptureFixture, tmp_path: Path
    ) -> None:
        model = _model(_sub("outer", _sub("mid", _gain(3.0), provenance=42)))
        with caplog.at_level(logging.WARNING, logger=_PROVENANCE_LOGGER):
            sim = Simulator.from_dict(copy.deepcopy(model))
        warnings = [r for r in caplog.records if r.name == _PROVENANCE_LOGGER]
        assert len(warnings) == 1
        assert "'mid'" in warnings[0].getMessage()
        assert "'outer'" in warnings[0].getMessage()
        saved = _save(sim, tmp_path / "broken.flw.json")
        assert saved["blocks"][1] == _strip(model["blocks"][1])


class TestNoProvenanceUnchanged:
    def test_python_api_subsystem_keys(self) -> None:
        sub = Subsystem(id="s")
        sub.add(Inport(port_idx=0, id="i"))
        sub.add(Gain(k=2.0, id="g"))
        sub.add(Outport(port_idx=0, id="o"))
        sub.connect("i", "g")
        sub.connect("g", "o")
        out = sub.to_dict()
        assert list(out) == ["id", "type", "params"]
        assert PROVENANCE_KEY not in json.dumps(out)
        assert sub.provenance is None

    def test_tagged_output_minus_provenance_equals_plain(self, tmp_path: Path) -> None:
        def build(tagged: bool) -> dict[str, Any]:
            mid = _sub(
                "mid",
                _gain("$Kp", _GAIN_PROV if tagged else None),
                provenance=_MID_PROV if tagged else None,
            )
            return _model(
                _sub("outer", mid, provenance=_OUTER_PROV if tagged else None, mask={"Kp": 3.0})
            )

        plain = _save(Simulator.from_dict(build(False)), tmp_path / "plain.flw.json")
        tagged = _save(Simulator.from_dict(build(True)), tmp_path / "tagged.flw.json")
        assert PROVENANCE_KEY not in (tmp_path / "plain.flw.json").read_text("utf-8")
        assert _strip(tagged) == plain
        assert tagged != plain


# ---------------------------------------------------------------------------
# 意味論非依存
# ---------------------------------------------------------------------------


class TestSemanticsIndependent:
    @staticmethod
    def _build(tagged: bool) -> Simulator:
        py = _with(
            {
                "id": "g",
                "type": "flode.blocks.pythonfunc.PythonFunction",
                "params": {"code": DEFAULT_CODE},
            },
            _GAIN_PROV if tagged else None,
        )
        mid = _sub("mid", py, provenance=_MID_PROV if tagged else None)
        model = _model(_sub("outer", mid, provenance=_OUTER_PROV if tagged else None))
        model["blocks"][0]["params"]["value"] = [1.0, 2.0, 3.0]
        return Simulator.from_dict(model)

    def test_python_digest_is_identical(self) -> None:
        plain = compute_python_digest(self._build(False))
        assert plain is not None
        assert plain == compute_python_digest(self._build(True))

    def test_signal_resolution_is_identical(self) -> None:
        plain = resolve_signals(self._build(False))
        tagged = resolve_signals(self._build(True))
        assert plain.to_payload() == tagged.to_payload()
        assert "outer" in plain.inner
        assert set(plain.inner) == set(tagged.inner)
        for key in plain.inner:
            assert plain.inner[key].to_payload() == tagged.inner[key].to_payload()

    def test_run_result_is_identical(self) -> None:
        def run(tagged: bool) -> Any:
            mid = _sub(
                "mid",
                _gain("$Kp", _GAIN_PROV if tagged else None),
                provenance=_MID_PROV if tagged else None,
            )
            sim = Simulator.from_dict(
                _model(
                    _sub("outer", mid, provenance=_OUTER_PROV if tagged else None, mask={"Kp": 3.0})
                )
            )
            sim.run()
            return sim.get_block("sc").values

        np.testing.assert_array_equal(run(False), run(True))


class TestPythonApiComposition:
    def test_block_instance_with_provenance_added_to_subsystem(self) -> None:
        # from_dict で由来を得たブロックを Python API で別の Subsystem に入れても出力される
        src = Simulator.from_dict(_model(_sub("outer", _gain(3.0, _GAIN_PROV))))
        loaded_outer = src.get_block("outer")
        assert isinstance(loaded_outer, Subsystem)

        wrap = Subsystem(id="wrap")
        wrap.add(Inport(port_idx=0, id="i"))
        wrap.add(loaded_outer)
        wrap.add(Outport(port_idx=0, id="o"))
        wrap.connect("i", "outer")
        wrap.connect("outer", "o")
        inner_gain = wrap.to_dict()["params"]["blocks"][1]["params"]["blocks"][1]
        assert inner_gain[PROVENANCE_KEY] == _GAIN_PROV
