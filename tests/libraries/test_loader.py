"""``.flwlib.json`` loader / validator のテスト (ADR-0029 / ADR-0080)。"""

from __future__ import annotations

import copy
import json
import logging
import warnings
from pathlib import Path
from typing import Any

import pytest

from flode import LibraryFileError, load_library, validate_library
from flode.core.persistence import CURRENT_SCHEMA_VERSION
from flode.libraries import LibraryEntry, canonicalize_entry_block, utc_timestamp
from flode.libraries._loader import (
    _LIBRARY_MIGRATIONS,
    CURRENT_LIBRARY_SCHEMA_VERSION,
    ENTRY_KIND_PYTHON_FUNCTION,
    ENTRY_KIND_SUBSYSTEM,
    MAX_ENTRY_BLOCK_DEPTH,
    SUPPORTED_LIBRARY_SCHEMA_VERSIONS,
    analyze_entry_block,
)

SUBSYSTEM_TYPE = "flode.subsystems.subsystem.Subsystem"
PYTHON_FUNCTION_TYPE = "flode.blocks.pythonfunc.PythonFunction"
INPORT_TYPE = "flode.subsystems.ports.Inport"
OUTPORT_TYPE = "flode.subsystems.ports.Outport"

PASSTHROUGH_CODE = "@block\ndef passthrough(t: float, u: float) -> float:\n    return u\n"


def _inport(block_id: str = "Inport_0") -> dict[str, Any]:
    return {"id": block_id, "type": INPORT_TYPE, "params": {"port_idx": 0}}


def _outport(block_id: str = "Outport_0") -> dict[str, Any]:
    return {"id": block_id, "type": OUTPORT_TYPE, "params": {"port_idx": 0}}


def _wire(src: str, dst: str, *, src_idx: int = 0, dst_idx: int = 0) -> dict[str, Any]:
    return {"src": src, "src_idx": src_idx, "dst": dst, "dst_idx": dst_idx}


def _subsystem_body(
    inner: list[dict[str, Any]] | None = None, *, block_id: str | None = None
) -> dict[str, Any]:
    """``Inport → (inner の直列) → Outport`` の Subsystem body を返す。"""
    chain = [_inport(), *(inner or []), _outport()]
    connections = [_wire(a["id"], b["id"]) for a, b in zip(chain, chain[1:], strict=False)]
    return {
        "id": block_id,
        "type": SUBSYSTEM_TYPE,
        "params": {"blocks": chain, "connections": connections},
    }


def _python_function_body(
    code: str = PASSTHROUGH_CODE, *, block_id: str | None = "pf"
) -> dict[str, Any]:
    return {
        "id": block_id,
        "type": PYTHON_FUNCTION_TYPE,
        "params": {"code": code, "user_params": {}},
    }


def _library_dict(body: dict[str, Any] | None = None, **overrides: Any) -> dict[str, Any]:
    """テスト用に最小の有効 v4 ``.flwlib.json`` dict を返す。"""
    base: dict[str, Any] = {
        "schema_version": CURRENT_LIBRARY_SCHEMA_VERSION,
        "name": "test",
        "display_name": "Test Library",
        "entries": [
            {
                "id": "trivial",
                "display_name": "Trivial",
                "block": body if body is not None else _subsystem_body(),
            }
        ],
    }
    base.update(overrides)
    return base


def _legacy_library_dict(schema_version: str, body: dict[str, Any]) -> dict[str, Any]:
    """v1〜v3 形式 (本体フィールドが ``subsystem``) の dict を返す。"""
    return {
        "schema_version": schema_version,
        "name": "legacy",
        "display_name": "Legacy",
        "entries": [{"id": "e1", "display_name": "Legacy", "subsystem": body}],
    }


# ----------------------------------------------------------------------------
# 基本の読み込み
# ----------------------------------------------------------------------------


def test_load_valid_library(tmp_path: Path) -> None:
    """最小限の有効な .flwlib.json が pass する。"""
    p = tmp_path / "test.flwlib.json"
    p.write_text(json.dumps(_library_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    lib = load_library(p)
    assert lib.name == "test"
    assert len(lib.entries) == 1
    assert lib.entries[0].id == "trivial"
    assert lib.source_path == p.resolve()


def test_load_does_not_rewrite_file(tmp_path: Path) -> None:
    """読み込み (migration を含む) だけではファイルを書き換えない (ADR-0080 §A1-3)。"""
    p = tmp_path / "old.flwlib.json"
    p.write_text(
        json.dumps(_legacy_library_dict("libraries.v3", _subsystem_body())), encoding="utf-8"
    )
    before = p.read_bytes()
    load_library(p)
    assert p.read_bytes() == before
    assert sorted(f.name for f in tmp_path.iterdir()) == ["old.flwlib.json"]


def test_load_invalid_schema_version(tmp_path: Path) -> None:
    """``schema_version`` が未対応値だと ``LibraryFileError`` を raise する。"""
    p = tmp_path / "bad.flwlib.json"
    p.write_text(json.dumps(_library_dict(schema_version="libraries.v999")), encoding="utf-8")
    with pytest.raises(LibraryFileError, match="Unsupported library schema_version"):
        load_library(p)


def test_load_missing_required_field(tmp_path: Path) -> None:
    """``name`` 欠落で ``LibraryFileError`` を raise する。"""
    data = _library_dict()
    del data["name"]
    p = tmp_path / "no_name.flwlib.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(LibraryFileError, match="Missing required key 'name'"):
        load_library(p)


def test_validate_library_in_memory() -> None:
    """``validate_library`` が dict を受け取り ``Library`` を返すパスを検証。"""
    lib = validate_library(_library_dict())
    assert lib.name == "test"
    assert lib.source_path is None


def test_load_duplicate_entry_id(tmp_path: Path) -> None:
    """同じ library 内で ``entry.id`` が重複したら ``LibraryFileError``。"""
    data = _library_dict()
    data["entries"].append(copy.deepcopy(data["entries"][0]))
    p = tmp_path / "dup.flwlib.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(LibraryFileError, match="duplicate entry id"):
        load_library(p)


def test_v4_entry_requires_block() -> None:
    """v4 では本体フィールドは ``block`` (``subsystem`` は v3 以前の名前)。"""
    data = _library_dict()
    data["entries"][0]["subsystem"] = data["entries"][0].pop("block")
    with pytest.raises(LibraryFileError, match="Missing required key 'block'"):
        validate_library(data)


# ----------------------------------------------------------------------------
# v4 の新フィールド
# ----------------------------------------------------------------------------


def test_v4_new_fields_are_loaded() -> None:
    """``uid`` / ``model_schema_version`` / ``revision`` / ``updated_at`` を読む。"""
    data = _library_dict(uid="8c1e2f0a-0000-4000-8000-000000000001")
    data["model_schema_version"] = CURRENT_SCHEMA_VERSION
    data["entries"][0]["revision"] = 3
    data["entries"][0]["updated_at"] = "2026-11-12T10:00:00Z"
    lib = validate_library(data)
    assert lib.uid == "8c1e2f0a-0000-4000-8000-000000000001"
    assert lib.model_schema_version == CURRENT_SCHEMA_VERSION
    assert lib.entries[0].revision == 3
    assert lib.entries[0].updated_at == "2026-11-12T10:00:00Z"


def test_v4_new_fields_defaults() -> None:
    """新フィールドはすべて任意。``revision`` の既定は 1、ボディは現行 schema とみなす。"""
    lib = validate_library(_library_dict())
    assert lib.uid is None
    assert lib.model_schema_version == CURRENT_SCHEMA_VERSION
    assert lib.entries[0].revision == 1
    assert lib.entries[0].updated_at is None


def test_v4_unknown_keys_are_ignored() -> None:
    """未知キーは無視する (段階 3 の ``appearance`` 等を v4 のまま足せる、ADR-0080 §A1-6)。"""
    data = _library_dict(future_library_key={"x": 1})
    data["entries"][0]["appearance"] = {"color": "#fff"}
    lib = validate_library(data)
    assert lib.entries[0].id == "trivial"


@pytest.mark.parametrize("revision", [0, -1, True, False, 1.0, "2", None])
def test_v4_invalid_revision_rejected(revision: Any) -> None:
    """``revision`` は整数 >= 1 (bool 不可)。"""
    data = _library_dict()
    data["entries"][0]["revision"] = revision
    with pytest.raises(LibraryFileError, match="revision"):
        validate_library(data)


@pytest.mark.parametrize(
    "updated_at",
    [
        "2026-11-12T10:00:00+00:00",  # "Z" 表記でない
        "2026-11-12T10:00:00.123Z",  # 秒精度でない
        "2026-11-12 10:00:00Z",
        "2026-13-40T10:00:00Z",  # 形は合うが実在しない日時
        "",
        20261112,
        None,
    ],
)
def test_v4_invalid_updated_at_rejected(updated_at: Any) -> None:
    """``updated_at`` は UTC 秒精度の "Z" 表記のみ。"""
    data = _library_dict()
    data["entries"][0]["updated_at"] = updated_at
    with pytest.raises(LibraryFileError, match="updated_at"):
        validate_library(data)


def test_utc_timestamp_format_is_accepted_by_loader() -> None:
    """``utc_timestamp()`` の出力は ``updated_at`` の検証を通る (秒精度・"Z"・UTC 換算)。"""
    import datetime

    jst = datetime.timezone(datetime.timedelta(hours=9))
    moment = datetime.datetime(2026, 11, 12, 19, 0, 0, 987654, tzinfo=jst)
    assert utc_timestamp(moment) == "2026-11-12T10:00:00Z"
    data = _library_dict()
    data["entries"][0]["updated_at"] = utc_timestamp()
    assert validate_library(data).entries[0].updated_at == data["entries"][0]["updated_at"]


@pytest.mark.parametrize("uid", ["", 123, None])
def test_v4_invalid_uid_rejected(uid: Any) -> None:
    """``uid`` は (あれば) 空でない文字列。"""
    with pytest.raises(LibraryFileError, match="uid"):
        validate_library(_library_dict(uid=uid))


@pytest.mark.parametrize("version", [15, None, ""])
def test_v4_invalid_model_schema_version_type_rejected(version: Any) -> None:
    """``model_schema_version`` は (あれば) 空でない文字列。"""
    with pytest.raises(LibraryFileError, match="model_schema_version"):
        validate_library(_library_dict(model_schema_version=version))


def test_v4_unknown_model_schema_version_rejected() -> None:
    """現行より新しい / 未知の ``model_schema_version`` は読み込みを拒否する。"""
    with pytest.raises(LibraryFileError, match="model_schema_version"):
        validate_library(_library_dict(model_schema_version="999.0"))


# ----------------------------------------------------------------------------
# migration (v1 / v2 / v3 → v4)
# ----------------------------------------------------------------------------


def test_migration_registry_chain() -> None:
    """migration チェーンが v1 → v4 まで登録されている。"""
    assert ("libraries.v1", "libraries.v2") in _LIBRARY_MIGRATIONS
    assert ("libraries.v2", "libraries.v3") in _LIBRARY_MIGRATIONS
    assert ("libraries.v3", "libraries.v4") in _LIBRARY_MIGRATIONS
    assert CURRENT_LIBRARY_SCHEMA_VERSION == "libraries.v4"
    # 旧バージョンも SUPPORTED に含めて「migration 経由で受け入れ可能」を明示
    for version in ("libraries.v4", "libraries.v3", "libraries.v2", "libraries.v1"):
        assert version in SUPPORTED_LIBRARY_SCHEMA_VERSIONS


def test_v3_to_v4_migration_fields() -> None:
    """v3 → v4: ``subsystem`` → ``block``、``revision=1``、``updated_at`` / ``uid`` は付けない。"""
    migrated = _LIBRARY_MIGRATIONS[("libraries.v3", "libraries.v4")](
        _legacy_library_dict("libraries.v3", _subsystem_body())
    )
    assert migrated["schema_version"] == "libraries.v4"
    # migration は凍結された過去仕様の再現 = CURRENT_SCHEMA_VERSION ではなくリテラル
    assert migrated["model_schema_version"] == "0.15"
    assert "uid" not in migrated
    entry = migrated["entries"][0]
    assert "subsystem" not in entry
    assert entry["block"]["type"] == SUBSYSTEM_TYPE
    assert entry["revision"] == 1
    assert "updated_at" not in entry


def test_v3_to_v4_migration_does_not_mutate_input() -> None:
    """migration は入力 dict を書き換えない (呼び出し側が持つ JSON を壊さない)。"""
    data = _legacy_library_dict("libraries.v3", _subsystem_body())
    snapshot = copy.deepcopy(data)
    validate_library(data)
    assert data == snapshot


@pytest.mark.parametrize("schema_version", ["libraries.v1", "libraries.v2", "libraries.v3"])
def test_legacy_versions_load_through_migration_chain(schema_version: str) -> None:
    """v1 / v2 / v3 のファイルが migration 連鎖を経て v4 相当として読める。"""
    lib = validate_library(_legacy_library_dict(schema_version, _subsystem_body()))
    entry = lib.entries[0]
    assert entry.block["type"] == SUBSYSTEM_TYPE
    assert entry.revision == 1
    assert entry.updated_at is None
    assert lib.uid is None
    assert lib.model_schema_version == CURRENT_SCHEMA_VERSION


@pytest.mark.parametrize("schema_version", ["libraries.v1", "libraries.v2"])
def test_legacy_migrations_do_not_mutate_input(schema_version: str) -> None:
    """v1 / v2 の migration も呼び出し側の dict を書き換えない。"""
    body = _subsystem_body(
        [{"id": "k", "type": "flode.blocks.cast.Cast", "params": {"output_type": "int"}}]
    )
    data = _legacy_library_dict(schema_version, body)
    snapshot = copy.deepcopy(data)
    validate_library(data)
    assert data == snapshot


def test_v2_library_with_output_type_is_migrated() -> None:
    """v0.55.0 でエクスポートした Cast(output_type) 入りライブラリが読める
    (security MUST-2 回帰テスト: 素の TypeError で壊れない)。"""
    from flode.subsystems import Subsystem

    body = {
        "id": "sub",
        "type": SUBSYSTEM_TYPE,
        "params": {
            "blocks": [
                _inport("ip"),
                {"id": "k", "type": "flode.blocks.cast.Cast", "params": {"output_type": "int"}},
                {
                    "id": "c",
                    "type": "flode.blocks.sources.Constant",
                    "params": {"value": 2.7, "output_type": "int"},
                },
                _outport("op"),
            ],
            "connections": [_wire("ip", "k"), _wire("k", "op")],
        },
    }
    result = validate_library(_legacy_library_dict("libraries.v2", body))
    sub_dict = result.entries[0].block
    inner = {b["id"]: b for b in sub_dict["params"]["blocks"]}
    assert inner["k"]["type"] == "flode.blocks.rounding.Rounding"
    assert inner["k"]["params"] == {"mode": "round"}
    assert inner["c"]["params"] == {"value": 3.0}
    # migration 後の dict から実際に Subsystem を再構築できる (TypeError なし)
    rebuilt = Subsystem._from_dict(**sub_dict["params"])
    assert rebuilt is not None


# ----------------------------------------------------------------------------
# F-21: v0.64.0 以前に書き出された StateSpace(m>=2) 入りエントリの発見的警告
# ----------------------------------------------------------------------------

STATE_SPACE_TYPE = "flode.blocks.continuous.StateSpace"


def _two_input_state_space_body(*, stale_wiring: bool) -> dict[str, Any]:
    """m=2 の StateSpace を含む Subsystem body。

    ``stale_wiring=True`` は 0.14 以前の形 (StateSpace の ``dst_idx=1`` へ直接結線)、
    ``False`` は 0.15 の形 (Mux で 1 本にまとめてから ``dst_idx=0`` へ)。
    """
    state_space = {
        "id": "ss",
        "type": STATE_SPACE_TYPE,
        "params": {"A": [[-1.0]], "B": [[1.0, 1.0]], "C": [[1.0]], "D": [[0.0, 0.0]]},
    }
    in0 = {"id": "in0", "type": INPORT_TYPE, "params": {"port_idx": 0}}
    in1 = {"id": "in1", "type": INPORT_TYPE, "params": {"port_idx": 1}}
    out = _outport("out")
    if stale_wiring:
        blocks = [in0, in1, state_space, out]
        connections = [_wire("in0", "ss"), _wire("in1", "ss", dst_idx=1), _wire("ss", "out")]
    else:
        mux = {"id": "mux", "type": "flode.blocks.routing.Mux", "params": {"n": 2}}
        blocks = [in0, in1, mux, state_space, out]
        connections = [
            _wire("in0", "mux"),
            _wire("in1", "mux", dst_idx=1),
            _wire("mux", "ss"),
            _wire("ss", "out"),
        ]
    return {
        "id": None,
        "type": SUBSYSTEM_TYPE,
        "params": {"blocks": blocks, "connections": connections},
    }


def test_v3_stale_lti_wiring_warns_with_entry_id(caplog: pytest.LogCaptureFixture) -> None:
    """StateSpace(m>=2) の ``dst_idx>=1`` 結線が残る v3 エントリは WARNING (自動修復しない)。"""
    body = _two_input_state_space_body(stale_wiring=True)
    with caplog.at_level(logging.WARNING, logger="flode.libraries"):
        lib = validate_library(_legacy_library_dict("libraries.v3", body))
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("'e1'" in m and "0.64.0" in m for m in messages)
    # 自動修復はしない (0.14→0.15 は非冪等): 結線はそのまま
    connections = lib.entries[0].block["params"]["connections"]
    assert _wire("in1", "ss", dst_idx=1) in connections


def test_v3_stale_lti_wiring_detected_in_nested_subsystem(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """入れ子の Subsystem 内に残っている場合も検出する。"""
    inner = _two_input_state_space_body(stale_wiring=True)
    inner["id"] = "inner"
    outer = {"id": None, "type": SUBSYSTEM_TYPE, "params": {"blocks": [inner], "connections": []}}
    with caplog.at_level(logging.WARNING, logger="flode.libraries"):
        validate_library(_legacy_library_dict("libraries.v3", outer))
    assert any("0.64.0" in r.getMessage() for r in caplog.records)


def test_v3_migrated_lti_wiring_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    """0.15 の形 (Mux 経由) で書かれた v3 エントリには警告しない。"""
    body = _two_input_state_space_body(stale_wiring=False)
    with caplog.at_level(logging.WARNING, logger="flode.libraries"):
        validate_library(_legacy_library_dict("libraries.v3", body))
    assert not [r for r in caplog.records if "0.64.0" in r.getMessage()]


# ----------------------------------------------------------------------------
# §A1-4 (4B): 古い model_schema_version のボディをモデル migration に通す
# ----------------------------------------------------------------------------


def test_old_model_schema_version_body_is_migrated() -> None:
    """``model_schema_version: "0.14"`` のボディはモデル側 0.14→0.15 migration を通る。

    m=2 の StateSpace への直接結線が ``Mux`` 経由に付け替わる (ADR-0079 §(7))。
    """
    from flode.subsystems import Subsystem

    data = _library_dict(
        _two_input_state_space_body(stale_wiring=True), model_schema_version="0.14"
    )
    snapshot = copy.deepcopy(data)
    lib = validate_library(data)
    assert data == snapshot  # 入力は書き換えない
    assert lib.model_schema_version == CURRENT_SCHEMA_VERSION
    params = lib.entries[0].block["params"]
    types = [b["type"] for b in params["blocks"]]
    assert "flode.blocks.routing.Mux" in types
    assert not [c for c in params["connections"] if c["dst"] == "ss" and c["dst_idx"] >= 1]
    # migration 後のボディは現行 schema として構築できる
    rebuilt = Subsystem._from_dict(**params)
    assert rebuilt.n_inputs == 2


def test_current_model_schema_version_body_is_untouched() -> None:
    """現行 ``model_schema_version`` のボディは migration を通さずそのまま保持する。"""
    body = _two_input_state_space_body(stale_wiring=True)
    lib = validate_library(_library_dict(body, model_schema_version=CURRENT_SCHEMA_VERSION))
    assert lib.entries[0].block == body


# ----------------------------------------------------------------------------
# §A2: エントリ種別の判定と浅い検証
# ----------------------------------------------------------------------------


def test_entry_kind_subsystem() -> None:
    entry = validate_library(_library_dict()).entries[0]
    assert entry.kind == ENTRY_KIND_SUBSYSTEM == "subsystem"
    assert entry.contains_python is False
    assert entry.python_block_paths == ()
    assert entry.unknown_types == ()


def test_entry_kind_python_function_standalone() -> None:
    """PythonFunction 単体のエントリは ``python_function`` (パスは本体自身 = 空文字)。"""
    entry = validate_library(_library_dict(_python_function_body())).entries[0]
    assert entry.kind == ENTRY_KIND_PYTHON_FUNCTION == "python_function"
    assert entry.contains_python is True
    assert entry.python_block_paths == ("",)


def test_entry_kind_resolves_reexported_alias_path() -> None:
    """再 export 経由の別名パスでも種別を取りこぼさない (文字列終端一致ではない、§A2 2B)。"""
    body = _python_function_body()
    body["type"] = "flode.blocks.PythonFunction"
    entry = validate_library(_library_dict(body)).entries[0]
    assert entry.kind == ENTRY_KIND_PYTHON_FUNCTION
    assert entry.contains_python is True


def test_nested_python_function_is_detected() -> None:
    """入れ子 Subsystem の中の PythonFunction を再帰で検出し、部分木内パスを返す。"""
    inner_sub = _subsystem_body([_python_function_body(block_id="deep")], block_id="inner")
    body = _subsystem_body([_python_function_body(block_id="shallow"), inner_sub])
    entry = validate_library(_library_dict(body)).entries[0]
    assert entry.kind == ENTRY_KIND_SUBSYSTEM
    assert entry.contains_python is True
    assert entry.python_block_paths == ("shallow", "inner/deep")


@pytest.mark.parametrize(
    "type_path",
    ["flode.blocks.mathops.Gain", "flode.subsystems.ports.Inport"],
)
def test_disallowed_entry_type_rejected(type_path: str) -> None:
    """Subsystem / PythonFunction 派生以外の型はエントリ本体にできない。"""
    data = _library_dict()
    data["entries"][0]["block"]["type"] = type_path
    with pytest.raises(LibraryFileError, match="must be a Subsystem or PythonFunction"):
        validate_library(data)


@pytest.mark.parametrize(
    "type_path",
    ["flode.blocks.nonexistent.Nope", "os.system", "NoDots", 42, None],
)
def test_unresolvable_top_level_type_rejected(type_path: Any) -> None:
    """トップレベルの型が解決できないファイルは読み込みを拒否する (allowlist 外は import しない)。"""
    data = _library_dict()
    data["entries"][0]["block"]["type"] = type_path
    with pytest.raises(LibraryFileError, match="block.type"):
        validate_library(data)


def test_entry_params_must_be_dict() -> None:
    data = _library_dict()
    data["entries"][0]["block"]["params"] = []
    with pytest.raises(LibraryFileError, match="block.params must be a dict"):
        validate_library(data)


def test_unknown_inner_types_are_collected() -> None:
    """本体内部の未解決型は拒否せず ``unknown_types`` に積む (浅い検証、§A2)。"""
    unknown_a = {"id": "a", "type": "flode.blocks.nonexistent.Nope", "params": {}}
    unknown_b = {"id": "b", "type": "thirdparty.plugin.Block", "params": {}}
    duplicate = {"id": "c", "type": "thirdparty.plugin.Block", "params": {}}
    inner_sub = _subsystem_body([unknown_b], block_id="inner")
    entry = validate_library(
        _library_dict(_subsystem_body([unknown_a, inner_sub, duplicate]))
    ).entries[0]
    assert entry.unknown_types == ("flode.blocks.nonexistent.Nope", "thirdparty.plugin.Block")
    assert entry.contains_python is False


def test_library_entry_derives_attributes_on_construction() -> None:
    """導出属性は本体から算出する (保存しない = ``type`` と食い違う状態を作れない)。"""
    entry = LibraryEntry(
        id="x",
        display_name="X",
        description="",
        category_suffix="",
        block=_python_function_body(),
    )
    assert entry.kind == ENTRY_KIND_PYTHON_FUNCTION
    assert entry.contains_python is True
    with pytest.raises(TypeError):
        LibraryEntry(  # type: ignore[call-arg]
            id="x",
            display_name="X",
            description="",
            category_suffix="",
            block=_python_function_body(),
            kind="subsystem",
        )


def test_stored_kind_key_is_ignored() -> None:
    """ファイルに ``kind`` が書かれていても読まない (導出値が正、ADR-0080 §A1-2)。"""
    data = _library_dict(_python_function_body())
    data["entries"][0]["kind"] = "subsystem"
    assert validate_library(data).entries[0].kind == ENTRY_KIND_PYTHON_FUNCTION


# ----------------------------------------------------------------------------
# 非推奨 alias ``LibraryEntry.subsystem``
# ----------------------------------------------------------------------------


def test_subsystem_alias_warns_and_returns_block() -> None:
    entry = validate_library(_library_dict()).entries[0]
    with pytest.warns(DeprecationWarning, match="LibraryEntry.subsystem"):
        aliased = entry.subsystem
    assert aliased is entry.block


def test_subsystem_alias_is_read_only() -> None:
    entry = validate_library(_library_dict()).entries[0]
    with pytest.raises(AttributeError):
        entry.subsystem = {}  # type: ignore[misc]


def test_block_attribute_does_not_warn() -> None:
    entry = validate_library(_library_dict()).entries[0]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert entry.block["type"] == SUBSYSTEM_TYPE


# ----------------------------------------------------------------------------
# §A2 深い検証 (canonicalize_entry_block)
# ----------------------------------------------------------------------------


def _sentinel_code(sentinel: Path) -> str:
    """モジュールレベルに副作用 (センチネルファイル作成) を持つ PythonFunction ソース。"""
    return (
        "import pathlib\n"
        f"pathlib.Path({str(sentinel)!r}).write_text('executed')\n"
        "@block\n"
        "def leaky(t: float, u: float) -> float:\n"
        "    return u\n"
    )


def test_deep_validation_returns_canonical_form() -> None:
    """構築 → ``to_dict()`` の正規形を返す (既定値の補完を含む)。"""
    from flode.subsystems import Subsystem

    body = _subsystem_body(
        [{"id": "int", "type": "flode.blocks.continuous.Integrator", "params": {}}]
    )
    canonical = canonicalize_entry_block(body)
    assert canonical == Subsystem._from_dict(**body["params"]).to_dict()
    inner = {b["id"]: b for b in canonical["params"]["blocks"]}
    assert "x0" in inner["int"]["params"]
    # 正規形は不動点 (もう一度通しても変わらない)
    assert canonicalize_entry_block(canonical) == canonical


def test_deep_validation_does_not_mutate_input() -> None:
    body = _subsystem_body()
    snapshot = copy.deepcopy(body)
    canonicalize_entry_block(body)
    assert body == snapshot


def test_deep_validation_python_function_standalone() -> None:
    body = _python_function_body()
    canonical = canonicalize_entry_block(body)
    assert canonical["type"] == PYTHON_FUNCTION_TYPE
    assert canonical["params"]["code"] == PASSTHROUGH_CODE


@pytest.mark.parametrize("nested", [False, True], ids=["standalone", "nested"])
def test_deep_validation_never_execs_user_code(tmp_path: Path, nested: bool) -> None:
    """深い検証はユーザーコードを exec しない (ADR-0080 §A4-5、F-17 / F-18)。"""
    sentinel = tmp_path / "sentinel.txt"
    python_block = _python_function_body(_sentinel_code(sentinel), block_id="leaky")
    body = _subsystem_body([python_block]) if nested else python_block
    canonical = canonicalize_entry_block(body)
    assert canonical["type"] == body["type"]
    assert not sentinel.exists()


def test_shallow_validation_never_execs_user_code(tmp_path: Path) -> None:
    """読み込み (浅い検証) もユーザーコードを exec しない。"""
    sentinel = tmp_path / "sentinel.txt"
    python_block = _python_function_body(_sentinel_code(sentinel), block_id="leaky")
    entry = validate_library(_library_dict(_subsystem_body([python_block]))).entries[0]
    assert entry.python_block_paths == ("leaky",)
    assert not sentinel.exists()


def test_sentinel_code_really_has_side_effect(tmp_path: Path) -> None:
    """上 2 件の対照: 同じソースは実行時 build では実際にセンチネルを作る。"""
    from flode.blocks.pythonfunc import PythonFunction

    sentinel = tmp_path / "sentinel.txt"
    PythonFunction(code=_sentinel_code(sentinel), id="leaky")._build()
    assert sentinel.exists()


def test_deep_validation_rejects_unbuildable_body() -> None:
    """構築できない本体 (存在しない結線先) は ``LibraryFileError``。"""
    body = _subsystem_body()
    body["params"]["connections"].append(_wire("Inport_0", "missing"))
    with pytest.raises(LibraryFileError, match="cannot be built"):
        canonicalize_entry_block(body)


def test_deep_validation_rejects_invalid_python_source() -> None:
    body = _python_function_body("def not_a_block(:\n")
    with pytest.raises(LibraryFileError, match="cannot be built"):
        canonicalize_entry_block(body)


def test_deep_validation_rejects_unknown_types() -> None:
    """未知のブロック型は型名を列挙して拒否する (SPEC-0032 §1.8)。"""
    body = _subsystem_body([{"id": "a", "type": "thirdparty.plugin.Block", "params": {}}])
    with pytest.raises(LibraryFileError, match="thirdparty.plugin.Block"):
        canonicalize_entry_block(body)


def test_deep_validation_rejects_disallowed_kind() -> None:
    body = {"id": "g", "type": "flode.blocks.mathops.Gain", "params": {"k": 2.0}}
    with pytest.raises(LibraryFileError, match="must be a Subsystem or PythonFunction"):
        canonicalize_entry_block(body)


@pytest.mark.parametrize(
    "broken_params",
    [
        pytest.param({"blocks": [42], "connections": []}, id="non-dict-inner-block"),
        pytest.param({"blocks": [], "connections": [None]}, id="non-dict-connection"),
        pytest.param({"blocks": "abc", "connections": []}, id="blocks-not-a-list"),
        pytest.param({"blocks": [{"id": "a"}], "connections": []}, id="inner-block-without-type"),
    ],
)
def test_deep_validation_wraps_errors_from_malformed_body(broken_params: dict[str, Any]) -> None:
    """壊れた本体はどんな例外型で失敗しても ``LibraryFileError`` に揃う。

    本体は外部から持ち込まれる。構築中の ``AttributeError`` 等が素通しになると、
    書き込み API が 500 になる。
    """
    body = {"id": "s", "type": SUBSYSTEM_TYPE, "params": broken_params}
    with pytest.raises(LibraryFileError):
        canonicalize_entry_block(body)


def _nested_subsystem_body(depth: int) -> dict[str, Any]:
    """Subsystem を ``depth`` 段入れ子にした本体を返す (最内は空の Subsystem)。"""
    body: dict[str, Any] = {
        "id": "leaf",
        "type": SUBSYSTEM_TYPE,
        "params": {"blocks": [], "connections": []},
    }
    for level in range(depth):
        body = {
            "id": f"level_{level}",
            "type": SUBSYSTEM_TYPE,
            "params": {"blocks": [body], "connections": []},
        }
    return body


def test_shallow_validation_rejects_excessive_nesting() -> None:
    """際限なく深い入れ子は ``RecursionError`` になる前に ``LibraryFileError`` で拒否する。"""
    with pytest.raises(LibraryFileError, match="deeper than"):
        analyze_entry_block(_nested_subsystem_body(MAX_ENTRY_BLOCK_DEPTH + 1))


def test_shallow_validation_accepts_nesting_at_limit() -> None:
    info = analyze_entry_block(_nested_subsystem_body(MAX_ENTRY_BLOCK_DEPTH - 1))
    assert info.kind == ENTRY_KIND_SUBSYSTEM


def test_load_library_reports_too_deeply_nested_json(tmp_path: Path) -> None:
    """JSON パーサの再帰上限を超えるファイルも ``LibraryFileError`` になる。"""
    path = tmp_path / "deep.flwlib.json"
    depth = 100_000
    path.write_text("[" * depth + "]" * depth, encoding="utf-8")
    with pytest.raises(LibraryFileError, match="nested too deeply"):
        load_library(path)


def test_load_library_reports_non_utf8_file(tmp_path: Path) -> None:
    path = tmp_path / "binary.flwlib.json"
    path.write_bytes(b"\xff\xfe\x00{")
    with pytest.raises(LibraryFileError, match="Cannot read library file"):
        load_library(path)


# ----------------------------------------------------------------------------
# 組み込み std bundle
# ----------------------------------------------------------------------------


def _std_bundle_path() -> Path:
    import flode.libraries

    return Path(flode.libraries.__file__).parent / "std.flwlib.json"


def test_load_std_bundle() -> None:
    """組み込み ``flode/libraries/std.flwlib.json`` の 3 entry が load 可能。"""
    from flode.subsystems import Subsystem

    lib = load_library(_std_bundle_path())
    assert lib.name == "std"
    ids = [e.id for e in lib.entries]
    assert ids == ["pid_controller", "first_order_plant", "second_order_plant"]
    for entry in lib.entries:
        assert entry.kind == ENTRY_KIND_SUBSYSTEM
        assert entry.contains_python is False
        assert entry.unknown_types == ()
        sub = Subsystem._from_dict(**entry.block["params"])
        assert sub.n_inputs >= 1
        assert sub.n_outputs >= 1


def test_std_bundle_is_current_schema() -> None:
    """同梱ファイル自体が v4 で書かれている (migration に頼らない)。"""
    raw = json.loads(_std_bundle_path().read_text(encoding="utf-8"))
    assert raw["schema_version"] == CURRENT_LIBRARY_SCHEMA_VERSION
    assert raw["model_schema_version"] == CURRENT_SCHEMA_VERSION
    for entry in raw["entries"]:
        assert "block" in entry
        assert "subsystem" not in entry
        assert entry["revision"] == 1


def test_std_bundle_resource_resolves_via_importlib() -> None:
    """``importlib.resources`` 経由で std.flwlib.json が見える (= wheel package_data 設定)。

    `pyproject.toml` の ``[tool.setuptools.package-data]`` で
    ``"flode.libraries" = ["*.json"]`` が抜けると wheel に bundle されず
    `LibraryRegistry` の `bundle_builtin=True` がサイレントに失敗する。本テストは
    `editable install` でも `wheel install` でも同じ resource lookup が成功する
    ことを確認するゲート。
    """
    import importlib.resources

    ref = importlib.resources.files("flode.libraries").joinpath("std.flwlib.json")
    assert ref.is_file(), (
        "flode/libraries/std.flwlib.json must be discoverable via "
        "importlib.resources (check pyproject.toml package-data)"
    )


def test_std_bundle_identical_to_generator() -> None:
    """``tools/build_std_library.py`` が生成する dict と bundle ファイルが一致する
    (= ジェネレータ更新後の commit 忘れ検出)。

    ``Subsystem.to_dict()`` の出力は決定的なので、本 generator を毎回実行しても
    同じ JSON が得られる前提。差分が出るのは ``Subsystem.to_dict()`` の挙動が
    変わった or ジェネレータが変わったが checked-in ファイルが追従していないとき。
    """
    import sys

    repo_root = Path(__file__).parent.parent.parent
    tools_path = repo_root / "tools"
    sys.path.insert(0, str(tools_path))
    try:
        import build_std_library  # type: ignore[import-not-found]
    finally:
        sys.path.remove(str(tools_path))

    bundle = json.loads(_std_bundle_path().read_text(encoding="utf-8"))
    assert bundle == build_std_library.build_library_dict(), (
        "std.flwlib.json drifted from generator output. "
        "Re-run `python tools/build_std_library.py` and commit the result."
    )
