"""ブロック entry の任意キー ``provenance`` (ライブラリ由来) の永続化テスト (ADR-0080 §A3)。

由来は **情報のみ** で、シミュレーション意味論・承認 digest・信号面解決に影響しない。
ここでは (1) 浅い検証 ``sanitize_provenance``、(2) トップレベルブロックの
``from_dict`` → ``to_dict`` / ``save`` → ``load`` の round-trip、(3) 由来を持たない
モデルの出力が変わらないこと、(4) 意味論非依存、を固定する。Subsystem 内部の
由来は ``tests/subsystems/test_subsystem_provenance.py``。
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

import flode
from flode import Simulator
from flode.blocks import Constant, Gain
from flode.blocks.pythonfunc import DEFAULT_CODE, PythonFunction, compute_python_digest
from flode.core.persistence import CURRENT_SCHEMA_VERSION
from flode.core.provenance import (
    MAX_PROVENANCE_DEPTH,
    MIN_PROVENANCE_REVISION,
    PROVENANCE_KEY,
    sanitize_provenance,
)
from flode.core.signals import resolve_signals

_PROVENANCE_LOGGER = "flode.core.provenance"

_VALID: dict[str, Any] = {
    "library": "user",
    "library_uid": "8c1e2f0a-0000-4000-8000-000000000001",
    "entry": "pid",
    "revision": 3,
}


class _VectorInBlock(flode.Block):
    """``port_shapes_in`` を JSON に出力する最小ブロック (キー順テスト用)。"""

    def output_v(
        self, t: float, x: npt.NDArray[Any], u: tuple[npt.NDArray[Any], ...]
    ) -> tuple[npt.NDArray[Any], ...]:
        return (np.asarray(u[0].sum()),)


def _too_deep() -> dict[str, Any]:
    nested: Any = "leaf"
    for _ in range(MAX_PROVENANCE_DEPTH + 1):
        nested = {"k": nested}
    return {**_VALID, "extra": nested}


#: (ケース名, 壊れた由来) — いずれも WARNING を出して捨てられ、ロードは成功する
_BROKEN_CASES: list[tuple[str, Any]] = [
    ("null", None),
    ("string", "user/pid"),
    ("number", 3),
    ("list", ["user", "pid", 3]),
    ("empty_dict", {}),
    ("missing_library", {"entry": "pid", "revision": 1}),
    ("missing_entry", {"library": "user", "revision": 1}),
    ("missing_revision", {"library": "user", "entry": "pid"}),
    ("library_not_str", {**_VALID, "library": 1}),
    ("library_empty", {**_VALID, "library": ""}),
    ("entry_not_str", {**_VALID, "entry": None}),
    ("entry_empty", {**_VALID, "entry": ""}),
    ("library_uid_not_str", {**_VALID, "library_uid": 5}),
    ("revision_str", {**_VALID, "revision": "3"}),
    ("revision_float", {**_VALID, "revision": 3.0}),
    ("revision_bool", {**_VALID, "revision": True}),
    ("revision_zero", {**_VALID, "revision": MIN_PROVENANCE_REVISION - 1}),
    ("revision_negative", {**_VALID, "revision": -2}),
    ("extra_not_json", {**_VALID, "extra": object()}),
    ("extra_set", {**_VALID, "extra": {1, 2}}),
    ("extra_nan", {**_VALID, "extra": float("nan")}),
    ("extra_inf_nested", {**_VALID, "extra": [1.0, float("inf")]}),
    ("extra_non_str_key", {**_VALID, "extra": {1: "a"}}),
    ("non_str_top_key", {**_VALID, 7: "x"}),
    ("too_deep", _too_deep()),
]


def _model(g_extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Constant(2) → Gain(3) → Scope の最小モデル。``g_extra`` は Gain entry に足すキー。"""
    gain: dict[str, Any] = {"id": "g", "type": "flode.blocks.mathops.Gain", "params": {"k": 3.0}}
    if g_extra:
        gain.update(g_extra)
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
            gain,
            {"id": "sc", "type": "flode.blocks.sinks.Scope", "params": {"n_inputs": 1}},
        ],
        "connections": [
            {"src": "c", "src_idx": 0, "dst": "g", "dst_idx": 0},
            {"src": "g", "src_idx": 0, "dst": "sc", "dst_idx": 0},
        ],
    }


def _saved(sim: Simulator, path: Path) -> dict[str, Any]:
    sim.save(path)
    loaded: dict[str, Any] = json.loads(path.read_text("utf-8"))
    return loaded


def _entry(model: dict[str, Any], block_id: str) -> dict[str, Any]:
    found: dict[str, Any] = next(b for b in model["blocks"] if b["id"] == block_id)
    return found


# ---------------------------------------------------------------------------
# sanitize_provenance (浅い検証の単体)
# ---------------------------------------------------------------------------


class TestSanitizeProvenance:
    def test_valid_is_returned_as_equal_copy(self) -> None:
        raw = copy.deepcopy(_VALID)
        out = sanitize_provenance(raw, block_id="g")
        assert out == _VALID
        assert out is not raw

    def test_library_uid_is_optional(self) -> None:
        raw = {"library": "std", "entry": "pid_controller", "revision": 1}
        assert sanitize_provenance(raw, block_id="g") == raw

    def test_unknown_extra_keys_are_kept(self) -> None:
        # ADR-0080 §A3-4 拡張余地: 由来は開いた dict (将来の body_digest 等)
        raw = {**_VALID, "body_digest": "sha256:abc", "meta": {"tags": ["a", 1, None, True, 0.5]}}
        assert sanitize_provenance(raw, block_id="g") == raw

    def test_key_order_is_preserved(self) -> None:
        raw = {"revision": 2, "entry": "pid", "zzz": 1, "library": "user"}
        out = sanitize_provenance(raw, block_id="g")
        assert out is not None
        assert list(out) == ["revision", "entry", "zzz", "library"]

    def test_result_does_not_alias_input(self) -> None:
        raw = {**_VALID, "meta": {"tags": ["a"]}}
        out = sanitize_provenance(raw, block_id="g")
        assert out is not None
        raw["meta"]["tags"].append("mutated")
        assert out["meta"]["tags"] == ["a"]

    @pytest.mark.parametrize(
        "broken", [c[1] for c in _BROKEN_CASES], ids=[c[0] for c in _BROKEN_CASES]
    )
    def test_broken_is_discarded_with_warning(
        self, broken: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger=_PROVENANCE_LOGGER):
            assert sanitize_provenance(broken, block_id="my_block") is None
        warnings = [r for r in caplog.records if r.name == _PROVENANCE_LOGGER]
        assert len(warnings) == 1
        assert warnings[0].levelno == logging.WARNING
        assert "my_block" in warnings[0].getMessage()

    def test_warning_names_parent_subsystem(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger=_PROVENANCE_LOGGER):
            sanitize_provenance("bad", block_id="inner_gain", parent_id="outer_sub")
        message = caplog.records[-1].getMessage()
        assert "inner_gain" in message
        assert "outer_sub" in message

    def test_valid_emits_no_log(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger=_PROVENANCE_LOGGER):
            sanitize_provenance(copy.deepcopy(_VALID), block_id="g")
        assert not caplog.records


# ---------------------------------------------------------------------------
# トップレベルブロックの round-trip
# ---------------------------------------------------------------------------


class TestTopLevelRoundTrip:
    def test_from_dict_to_dict_keeps_provenance(self) -> None:
        sim = Simulator.from_dict(_model({PROVENANCE_KEY: _VALID}))
        assert sim.get_block("g").to_dict()[PROVENANCE_KEY] == _VALID
        assert PROVENANCE_KEY not in sim.get_block("c").to_dict()
        assert PROVENANCE_KEY not in sim.get_block("sc").to_dict()

    def test_save_load_round_trip(self, tmp_path: Path) -> None:
        sim = Simulator.from_dict(_model({PROVENANCE_KEY: _VALID}))
        first = _saved(sim, tmp_path / "a.flw.json")
        assert _entry(first, "g")[PROVENANCE_KEY] == _VALID

        sim2 = Simulator.load(tmp_path / "a.flw.json")
        sim2.save(tmp_path / "b.flw.json")
        assert (tmp_path / "a.flw.json").read_bytes() == (tmp_path / "b.flw.json").read_bytes()

    def test_provenance_is_last_key(self, tmp_path: Path) -> None:
        # port_shapes_* より後 = entry の末尾 (ADR-0080 §A3-2)
        data = _model()
        data["blocks"][1] = {
            "id": "g",
            "type": "flode.blocks.routing.Mux",
            "params": {"n": 1},
            PROVENANCE_KEY: _VALID,
        }
        sim = Simulator.from_dict(data)
        assert list(sim.get_block("g").to_dict())[-1] == PROVENANCE_KEY
        saved = _saved(sim, tmp_path / "m.flw.json")
        assert list(_entry(saved, "g"))[-1] == PROVENANCE_KEY

    def test_provenance_is_last_key_after_port_shapes(self) -> None:
        # ``port_shapes_in`` / ``port_shapes_out`` を出力するブロックでも末尾
        blk = _VectorInBlock(id="b", n_inputs=1, n_outputs=1, port_shapes_in=[(2,)])
        blk._provenance = dict(_VALID)
        out = blk.to_dict()
        assert list(out) == ["id", "type", "params", "port_shapes_in", PROVENANCE_KEY]

    def test_unknown_extra_keys_round_trip(self, tmp_path: Path) -> None:
        prov = {**_VALID, "body_digest": "sha256:abc", "meta": {"n": [1, 2]}}
        sim = Simulator.from_dict(_model({PROVENANCE_KEY: prov}))
        saved = _saved(sim, tmp_path / "x.flw.json")
        assert _entry(saved, "g")[PROVENANCE_KEY] == prov
        assert list(_entry(saved, "g")[PROVENANCE_KEY]) == list(prov)

    def test_python_function_round_trip(self, tmp_path: Path) -> None:
        data = _model()
        data["blocks"][1] = {
            "id": "g",
            "type": "flode.blocks.pythonfunc.PythonFunction",
            "params": {"code": DEFAULT_CODE},
            PROVENANCE_KEY: _VALID,
        }
        sim = Simulator.from_dict(data)
        assert isinstance(sim.get_block("g"), PythonFunction)
        saved = _saved(sim, tmp_path / "py.flw.json")
        assert _entry(saved, "g")[PROVENANCE_KEY] == _VALID
        sim2 = Simulator.load(tmp_path / "py.flw.json")
        assert sim2.get_block("g").provenance == _VALID

    def test_survives_schema_migration(self) -> None:
        # 旧 schema のファイルに由来が付いていても migration 連鎖で落ちない
        data = _model({PROVENANCE_KEY: _VALID})
        data["schema_version"] = "0.6"
        sim = Simulator.from_dict(data)
        assert sim.get_block("g").provenance == _VALID

    def test_stored_provenance_does_not_alias_model_dict(self) -> None:
        data = _model({PROVENANCE_KEY: {**_VALID, "meta": {"tags": ["a"]}}})
        sim = Simulator.from_dict(data)
        data["blocks"][1][PROVENANCE_KEY]["meta"]["tags"].append("mutated")
        assert sim.get_block("g").to_dict()[PROVENANCE_KEY]["meta"]["tags"] == ["a"]

    def test_to_dict_output_does_not_alias_block_state(self) -> None:
        sim = Simulator.from_dict(_model({PROVENANCE_KEY: _VALID}))
        out = sim.get_block("g").to_dict()
        out[PROVENANCE_KEY]["revision"] = 999
        assert sim.get_block("g").to_dict()[PROVENANCE_KEY] == _VALID


class TestProvenanceProperty:
    def test_default_is_none(self) -> None:
        assert Gain(k=1.0, id="g").provenance is None

    def test_returns_copy(self) -> None:
        sim = Simulator.from_dict(_model({PROVENANCE_KEY: _VALID}))
        got = sim.get_block("g").provenance
        assert got == _VALID
        assert got is not None
        got["revision"] = 999
        assert sim.get_block("g").provenance == _VALID

    def test_is_read_only(self) -> None:
        blk = Gain(k=1.0, id="g")
        with pytest.raises(AttributeError):
            blk.provenance = dict(_VALID)  # type: ignore[misc]

    def test_rename_keeps_provenance(self) -> None:
        # id 変更で由来は切れない (ADR-0080 §A3-1: 3A の利点)
        sim = Simulator.from_dict(_model({PROVENANCE_KEY: _VALID}))
        sim.rename("g", "g2")
        assert sim.get_block("g2").to_dict()[PROVENANCE_KEY] == _VALID

    def test_deepcopy_inherits_provenance(self) -> None:
        # コピーは由来を引き継ぐ (ADR-0080 §A3-4)
        blk = Simulator.from_dict(_model({PROVENANCE_KEY: _VALID})).get_block("g")
        blk.input_sources = [None]
        assert copy.deepcopy(blk).provenance == _VALID


# ---------------------------------------------------------------------------
# 壊れた由来はロードを妨げない
# ---------------------------------------------------------------------------


class TestBrokenProvenanceDoesNotBlockLoad:
    @pytest.mark.parametrize(
        "broken", [c[1] for c in _BROKEN_CASES], ids=[c[0] for c in _BROKEN_CASES]
    )
    def test_load_succeeds_and_provenance_is_dropped(
        self, broken: Any, caplog: pytest.LogCaptureFixture, tmp_path: Path
    ) -> None:
        with caplog.at_level(logging.WARNING, logger=_PROVENANCE_LOGGER):
            sim = Simulator.from_dict(_model({PROVENANCE_KEY: broken}))
        warnings = [r for r in caplog.records if r.name == _PROVENANCE_LOGGER]
        assert len(warnings) == 1
        assert "'g'" in warnings[0].getMessage()

        assert sim.get_block("g").provenance is None
        saved = _saved(sim, tmp_path / "broken.flw.json")
        assert PROVENANCE_KEY not in _entry(saved, "g")
        # 由来の無いモデルと同じ出力。metadata.created_at は保存時刻 (秒精度) なので、
        # 2 回の save が秒の境目をまたぐと食い違う。比較から外す
        clean = _saved(Simulator.from_dict(_model()), tmp_path / "clean.flw.json")
        saved.pop("metadata", None)
        clean.pop("metadata", None)
        assert saved == clean
        sim.run()
        np.testing.assert_allclose(sim.get_block("sc").values[:, 0], 6.0)

    def test_warning_does_not_echo_raw_value(self, caplog: pytest.LogCaptureFixture) -> None:
        # 壊れた値そのもの (任意長・任意内容) をログへ増幅しない
        secret = "x" * 5000
        with caplog.at_level(logging.WARNING, logger=_PROVENANCE_LOGGER):
            Simulator.from_dict(_model({PROVENANCE_KEY: {**_VALID, "library": [secret]}}))
        assert secret not in caplog.text


# ---------------------------------------------------------------------------
# 由来なしモデルは 1 バイトも変わらない
# ---------------------------------------------------------------------------


class TestNoProvenanceOutputUnchanged:
    def test_block_to_dict_has_no_provenance_key(self) -> None:
        assert Gain(k=2.0, id="g").to_dict() == {
            "id": "g",
            "type": "flode.blocks.mathops.Gain",
            "params": {"k": 2.0},
        }

    def test_loaded_model_without_provenance_has_no_key(self, tmp_path: Path) -> None:
        saved = _saved(Simulator.from_dict(_model()), tmp_path / "plain.flw.json")
        assert all(PROVENANCE_KEY not in b for b in saved["blocks"])
        assert PROVENANCE_KEY not in (tmp_path / "plain.flw.json").read_text("utf-8")

    def test_only_difference_is_the_provenance_key(self, tmp_path: Path) -> None:
        plain = _saved(Simulator.from_dict(_model()), tmp_path / "plain.flw.json")
        tagged = _saved(
            Simulator.from_dict(_model({PROVENANCE_KEY: _VALID})), tmp_path / "tagged.flw.json"
        )
        del _entry(tagged, "g")[PROVENANCE_KEY]
        assert tagged == plain

    def test_python_api_blocks_have_no_provenance(self) -> None:
        # from_dict を経ない Python API 構築では由来は付かない
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(Constant(value=1.0, id="c"))
        assert sim.get_block("c").provenance is None


# ---------------------------------------------------------------------------
# 意味論非依存 (実行結果 / 承認 digest / 信号面解決)
# ---------------------------------------------------------------------------


def _python_model(with_provenance: bool) -> dict[str, Any]:
    data = _model()
    py: dict[str, Any] = {
        "id": "g",
        "type": "flode.blocks.pythonfunc.PythonFunction",
        "params": {"code": DEFAULT_CODE},
    }
    if with_provenance:
        py[PROVENANCE_KEY] = dict(_VALID)
        data["blocks"][0][PROVENANCE_KEY] = {"library": "std", "entry": "const", "revision": 1}
    data["blocks"][1] = py
    return data


class TestSemanticsIndependent:
    def test_run_result_is_identical(self) -> None:
        plain = Simulator.from_dict(_python_model(False))
        tagged = Simulator.from_dict(_python_model(True))
        plain.run()
        tagged.run()
        np.testing.assert_array_equal(
            np.asarray(plain.get_block("sc").times), np.asarray(tagged.get_block("sc").times)
        )
        np.testing.assert_array_equal(plain.get_block("sc").values, tagged.get_block("sc").values)

    def test_python_digest_is_identical(self) -> None:
        plain = compute_python_digest(Simulator.from_dict(_python_model(False)))
        tagged = compute_python_digest(Simulator.from_dict(_python_model(True)))
        assert plain is not None
        assert plain == tagged

    def test_python_digest_ignores_revision_change(self) -> None:
        a = _python_model(True)
        b = _python_model(True)
        b["blocks"][1][PROVENANCE_KEY]["revision"] = 99
        b["blocks"][1][PROVENANCE_KEY]["library"] = "other"
        assert compute_python_digest(Simulator.from_dict(a)) == compute_python_digest(
            Simulator.from_dict(b)
        )

    def test_signal_resolution_is_identical(self) -> None:
        data_plain = _model()
        data_tagged = _model({PROVENANCE_KEY: _VALID})
        for data in (data_plain, data_tagged):
            data["blocks"][0]["params"]["value"] = [1.0, 2.0, 3.0]  # ベクトル信号を流す
        plain = resolve_signals(Simulator.from_dict(data_plain))
        tagged = resolve_signals(Simulator.from_dict(data_tagged))
        assert dict(plain.shapes) == dict(tagged.shapes)
        assert dict(plain.ports) == dict(tagged.ports)
        assert plain.to_payload() == tagged.to_payload()
        assert plain.out_shape("g", 0) == (3,)

    @pytest.mark.parametrize(
        "module_path",
        [
            "blocks/pythonfunc.py",
            "blocks/pythonfunc_source.py",
            "core/signals.py",
            "core/dtypes.py",
            "core/decorator.py",
        ],
    )
    def test_semantic_modules_never_mention_provenance(self, module_path: str) -> None:
        # digest 計算・信号面解決・@block 生成は由来を一切参照しない (ADR-0080 §A3-2)
        source = (Path(flode.__file__).parent / module_path).read_text("utf-8")
        assert "provenance" not in source
