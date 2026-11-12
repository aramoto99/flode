"""ライブラリ書き込み API (`/api/v1/libraries` の登録・編集・削除・取り込み・再読込・書き出し) のテスト。

ADR-0080 §A4〜§A6 / SPEC-0032 段階 1。すべて ``tmp_path`` 配下を ``user_library_dir`` に
使い、実ホーム (``~/.flode``) には触れない。
"""

from __future__ import annotations

import copy
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from flode.core.persistence import CURRENT_SCHEMA_VERSION
from flode.libraries import (
    CURRENT_LIBRARY_SCHEMA_VERSION,
    _atomic,
    load_library,
    validate_library,
)
from flode.server import library_store
from flode.server.app import create_app
from flode.server.routes import libraries as libraries_routes
from flode.server.settings import Settings
from tests.server._library_models import (
    FROM_TYPE,
    GOTO_TYPE,
    PASSTHROUGH_CODE,
    gain_block,
    legacy_v3_library_dict,
    library_dict,
    python_function_body,
    sentinel_code,
    subsystem_body,
)
from tests.server._library_models import wire as _wire

API = "/api/v1/libraries"
ENTRIES = f"{API}/user/entries"
BASE_URL = "http://127.0.0.1"
USER_FILE = "user.flwlib.json"
PROVENANCE = {"library": "user", "library_uid": "u-1", "entry": "old", "revision": 7}


def _open_client(
    tmp_path: Path,
    *,
    user_library_dir: Path | None,
    write_allowed: bool = True,
    library_paths: list[Path] | None = None,
) -> TestClient:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    settings = Settings(
        workspace_root=workspace,
        library_paths=library_paths or [],
        user_library_dir=user_library_dir,
        library_write_allowed=write_allowed,
        library_write_reason="" if write_allowed else "server is bound to non-loopback address",
    )
    return TestClient(create_app(settings=settings), base_url=BASE_URL)


@pytest.fixture
def user_dir(tmp_path: Path) -> Path:
    """ユーザーライブラリのディレクトリ (作らない: 初回書き込みで作られることも確かめる)。"""
    return tmp_path / "libraries"


@pytest.fixture
def client(tmp_path: Path, user_dir: Path) -> Iterator[TestClient]:
    with _open_client(tmp_path, user_library_dir=user_dir) as c:
        yield c


def _register(client: TestClient, name: str = "PID", **fields: Any) -> Any:
    body = {"block": subsystem_body([gain_block()]), "display_name": name, **fields}
    return client.post(ENTRIES, json=body)


def _error(response: Any, status: int, code: str) -> dict[str, Any]:
    """構造化エラー (ADR-0056 形式) を検証して ``template_args`` を返す。"""
    assert response.status_code == status, response.text
    detail = response.json()["detail"]
    assert detail["category"] == "library"
    assert detail["code"] == code
    assert detail["template_key"] == f"error.library.{code}"
    assert isinstance(detail["raw_message"], str) and detail["raw_message"]
    assert isinstance(detail["template_args"], dict)
    return detail["template_args"]  # type: ignore[no-any-return]


def _libraries(client: TestClient) -> dict[str, dict[str, Any]]:
    return {lib["name"]: lib for lib in client.get(API).json()["libraries"]}


def _read_user_file(user_dir: Path) -> dict[str, Any]:
    return json.loads((user_dir / USER_FILE).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _names(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _import(client: TestClient, data: Any, *, dry_run: bool = False, **extra: Any) -> Any:
    content = data if isinstance(data, str) else json.dumps(data)
    return client.post(f"{API}/import", json={"content": content, "dry_run": dry_run, **extra})


# ----------------------------------------------------------------------------
# 書き込みの可否 (ADR-0080 §A4-1)
# ----------------------------------------------------------------------------

# (method, path, JSON 本文) — 全書き込みルート
WRITE_REQUESTS: list[tuple[str, str, dict[str, Any] | None]] = [
    ("POST", ENTRIES, {"block": subsystem_body(), "display_name": "X"}),
    ("PATCH", f"{ENTRIES}/x", {"description": "d"}),
    ("DELETE", f"{ENTRIES}/x?expected_revision=1", None),
    ("POST", f"{API}/import", {"content": "{}", "dry_run": True}),
    ("POST", f"{API}/import", {"content": "{}", "dry_run": False}),
    ("DELETE", f"{API}/some_library", None),
    ("POST", f"{API}/reload", None),
]
WRITE_IDS = ["register", "patch", "delete-entry", "import-dry", "import", "delete-lib", "reload"]


@pytest.mark.parametrize(("method", "path", "body"), WRITE_REQUESTS, ids=WRITE_IDS)
def test_write_routes_are_forbidden_when_writes_are_not_allowed(
    tmp_path: Path, user_dir: Path, method: str, path: str, body: dict[str, Any] | None
) -> None:
    with _open_client(tmp_path, user_library_dir=user_dir, write_allowed=False) as client:
        args = _error(client.request(method, path, json=body), 403, "library_write_forbidden")
    assert "non-loopback" in args["reason"]
    assert not user_dir.exists()


# 再読み込みはユーザーライブラリに書き込まないので、無効でも通す (別テスト)
@pytest.mark.parametrize(("method", "path", "body"), WRITE_REQUESTS[:-1], ids=WRITE_IDS[:-1])
def test_write_routes_are_forbidden_when_user_library_is_disabled(
    tmp_path: Path, method: str, path: str, body: dict[str, Any] | None
) -> None:
    with _open_client(tmp_path, user_library_dir=None) as client:
        _error(client.request(method, path, json=body), 403, "user_library_disabled")


def test_reload_only_requires_write_permission_not_a_user_library(tmp_path: Path) -> None:
    """再読み込みの要件は loopback 判定だけ: ユーザーライブラリ無効でも ``library_paths`` を読み直せる。"""
    extra_dir = tmp_path / "extra"
    extra_dir.mkdir()
    with _open_client(tmp_path, user_library_dir=None, library_paths=[extra_dir]) as client:
        _write_json(extra_dir / "late.flwlib.json", library_dict("late", {"e": subsystem_body()}))
        assert "late" not in _libraries(client)
        r = client.post(f"{API}/reload")
        assert r.status_code == 200, r.text
        assert [lib["name"] for lib in r.json()["libraries"]] == ["std", "late"]
        assert r.json()["user_library"]["enabled"] is False
        assert r.json()["user_library"]["write_disabled_reason"] == "user_library_disabled"


def test_reads_stay_available_when_writes_are_not_allowed(tmp_path: Path, user_dir: Path) -> None:
    _write_json(
        user_dir / USER_FILE, library_dict("user", {"pid": subsystem_body()}, uid="abcdef0123")
    )
    with _open_client(tmp_path, user_library_dir=user_dir, write_allowed=False) as client:
        listing = client.get(API).json()
        assert client.get(f"{API}/user/pid").status_code == 200
        assert client.get(f"{API}/user/export").status_code == 200
        assert client.get(f"{API}/std/export").status_code == 200
    user = next(lib for lib in listing["libraries"] if lib["name"] == "user")
    assert user["origin"] == "user"
    assert user["writable"] is False
    assert user["write_disabled_reason"] == "library_write_forbidden"
    assert listing["user_library"] == {
        "name": "user",
        "enabled": True,
        "exists": True,
        "writable": False,
        "write_disabled_reason": "library_write_forbidden",
    }


def test_create_app_default_settings_are_fail_closed(tmp_path: Path) -> None:
    """``create_app`` を直接使う既定では、書き込みは 403 でユーザーライブラリも読まない。"""
    with TestClient(create_app(settings=Settings(workspace_root=tmp_path)), base_url=BASE_URL) as c:
        _error(_register(c), 403, "library_write_forbidden")
        listing = c.get(API).json()
    assert [lib["name"] for lib in listing["libraries"]] == ["std"]
    assert listing["user_library"]["enabled"] is False
    assert listing["user_library"]["writable"] is False
    std = listing["libraries"][0]
    assert (std["origin"], std["writable"], std["write_disabled_reason"]) == (
        "builtin",
        False,
        "library_read_only",
    )


def test_create_app_copies_library_settings(tmp_path: Path, user_dir: Path) -> None:
    """防御コピーに 3 フィールドが含まれる (漏れると CLI の設定が既定値に戻る)。"""
    settings = Settings(
        workspace_root=tmp_path,
        user_library_dir=user_dir,
        library_write_allowed=True,
        library_write_reason="because",
    )
    copied = create_app(settings=settings).state.settings
    assert copied is not settings
    assert copied.user_library_dir == user_dir
    assert copied.library_write_allowed is True
    assert copied.library_write_reason == "because"


# ----------------------------------------------------------------------------
# CSRF guard / サイズ・深さの上限 (ADR-0080 §A4-2 / §A4-4)
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", ENTRIES), ("PATCH", f"{ENTRIES}/x"), ("POST", f"{API}/import")],
)
def test_non_json_body_is_415(client: TestClient, user_dir: Path, method: str, path: str) -> None:
    body = json.dumps({"block": subsystem_body(), "display_name": "X", "content": "{}"})
    r = client.request(method, path, content=body, headers={"Content-Type": "text/plain"})
    assert r.status_code == 415
    assert not user_dir.exists()


@pytest.mark.parametrize(("method", "path", "body"), WRITE_REQUESTS, ids=WRITE_IDS)
def test_cross_origin_write_is_rejected(
    client: TestClient, user_dir: Path, method: str, path: str, body: dict[str, Any] | None
) -> None:
    r = client.request(method, path, json=body, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert "Cross-origin" in r.json()["detail"]
    assert not user_dir.exists()


def test_same_origin_write_passes_the_guard(client: TestClient) -> None:
    r = client.post(
        ENTRIES,
        json={"block": subsystem_body(), "display_name": "X"},
        headers={"Origin": BASE_URL},
    )
    assert r.status_code == 200


def test_oversized_body_is_413(client: TestClient, user_dir: Path, mocker: MockerFixture) -> None:
    mocker.patch.object(libraries_routes, "MAX_LIBRARY_REQUEST_BYTES", 64)
    r = client.post(ENTRIES, json={"block": subsystem_body(), "display_name": "X"})
    assert r.status_code == 413
    assert not user_dir.exists()


def test_request_size_limit_is_16_mib() -> None:
    assert libraries_routes.MAX_LIBRARY_REQUEST_BYTES == 16 * 1024 * 1024
    assert library_store.MAX_LIBRARY_JSON_DEPTH == 128


def test_chunked_body_is_411(client: TestClient, user_dir: Path) -> None:
    payload = json.dumps({"block": subsystem_body(), "display_name": "X"}).encode()

    def chunks() -> Iterator[bytes]:
        yield payload

    r = client.post(ENTRIES, content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 411
    assert not user_dir.exists()


def test_transfer_encoding_is_411_even_with_content_length(
    client: TestClient, user_dir: Path
) -> None:
    """``Content-Length`` を併記しても、``Transfer-Encoding`` 付きの本文は受け付けない。"""
    r = client.post(
        ENTRIES,
        json={"block": subsystem_body(), "display_name": "X"},
        headers={"Transfer-Encoding": "chunked"},
    )
    assert r.status_code == 411
    assert not user_dir.exists()


def test_declared_oversize_is_rejected_before_reading(client: TestClient, user_dir: Path) -> None:
    """宣言された長さが上限を超えていれば、本文を読む前に 413 にする。"""
    too_big = str(libraries_routes.MAX_LIBRARY_REQUEST_BYTES + 1)
    r = client.post(
        ENTRIES,
        content=b"{}",
        headers={"Content-Type": "application/json", "Content-Length": too_big},
    )
    assert r.status_code == 413
    assert not user_dir.exists()


def test_body_longer_than_declared_is_still_bounded(
    client: TestClient, user_dir: Path, mocker: MockerFixture
) -> None:
    """``Content-Length`` を偽っても、実際に受け取ったバイト数で上限を掛ける。"""
    mocker.patch.object(libraries_routes, "MAX_LIBRARY_REQUEST_BYTES", 64)
    body = json.dumps({"block": subsystem_body(), "display_name": "X"}).encode()
    assert len(body) > 64
    r = client.post(
        ENTRIES,
        content=body,
        headers={"Content-Type": "application/json", "Content-Length": "10"},
    )
    assert r.status_code == 413
    assert not user_dir.exists()


def _nested(depth: int) -> Any:
    value: Any = 0
    for _ in range(depth):
        value = [value]
    return value


def test_request_json_deeper_than_limit_is_422(client: TestClient, user_dir: Path) -> None:
    # 本文の object が深さ 1、``x`` の値が深さ 2 から始まる
    ok_depth = library_store.MAX_LIBRARY_JSON_DEPTH - 1
    r = client.post(
        ENTRIES, json={"block": subsystem_body(), "display_name": "X", "x": _nested(ok_depth)}
    )
    assert r.status_code == 422  # 深さは通るが未知フィールドで拒否される
    assert "Unknown field" in r.json()["detail"]
    r = client.post(ENTRIES, json={"x": _nested(ok_depth + 1)})
    assert r.status_code == 422
    assert "nested deeper" in r.json()["detail"]
    assert not user_dir.exists()


def test_absurdly_deep_request_json_is_422_not_500(client: TestClient) -> None:
    body = b"[" * 200_000 + b"]" * 200_000
    r = client.post(ENTRIES, content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[1, 2]",
        json.dumps({"display_name": "X"}).encode(),
        json.dumps({"block": subsystem_body()}).encode(),
        json.dumps({"block": subsystem_body(), "display_name": 3}).encode(),
        json.dumps({"block": subsystem_body(), "display_name": "X", "save_as_new": "yes"}).encode(),
        json.dumps(
            {"block": subsystem_body(), "display_name": "X", "expected_revision": True}
        ).encode(),
        json.dumps({"block": subsystem_body(), "display_name": "X", "path": "C:/evil"}).encode(),
    ],
    ids=[
        "not-json",
        "array",
        "no-block",
        "no-name",
        "name-type",
        "flag-type",
        "bool-revision",
        "extra",
    ],
)
def test_malformed_register_body_is_422(client: TestClient, user_dir: Path, body: bytes) -> None:
    r = client.post(ENTRIES, content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str)
    assert not user_dir.exists()


# ----------------------------------------------------------------------------
# 登録 (新規)
# ----------------------------------------------------------------------------


def test_register_creates_user_library_and_entry(client: TestClient, user_dir: Path) -> None:
    assert not user_dir.exists()
    r = _register(client, "PID", description=" a controller ", category_suffix="controllers")
    assert r.status_code == 200, r.text
    data = r.json()
    entry = data["entry"]
    assert data["library"] == "user"
    assert entry["id"] == "pid"
    assert entry["display_name"] == "PID"
    assert entry["description"] == "a controller"
    assert entry["category_suffix"] == "controllers"
    assert entry["kind"] == "subsystem"
    assert entry["revision"] == 1
    assert entry["updated_at"].endswith("Z")
    assert entry["contains_python"] is False

    # ファイル: libraries.v4 で人間可読、uid とボディのモデル schema 版を持つ
    assert _names(user_dir) == [USER_FILE]
    text = (user_dir / USER_FILE).read_text(encoding="utf-8")
    assert text.endswith("}\n") and "\n  " in text
    stored = json.loads(text)
    assert stored["schema_version"] == CURRENT_LIBRARY_SCHEMA_VERSION == "libraries.v4"
    assert stored["name"] == "user"
    assert stored["uid"] == data["library_uid"]
    assert len(stored["uid"]) == 36
    assert stored["model_schema_version"] == CURRENT_SCHEMA_VERSION
    assert stored["display_name_i18n"]["ja"] == "マイブロック"
    assert "kind" not in stored["entries"][0]
    assert stored["entries"][0]["block"]["type"].endswith(".Subsystem")

    # 一覧: サーバ再起動なしで反映、std の次に並ぶ
    listing = client.get(API).json()
    assert [lib["name"] for lib in listing["libraries"]] == ["std", "user"]
    user = listing["libraries"][1]
    assert (user["origin"], user["writable"], user["write_disabled_reason"]) == ("user", True, "")
    assert user["uid"] == data["library_uid"]
    assert listing["user_library"]["exists"] is True
    assert listing["user_library"]["writable"] is True

    # 詳細: revision / library_uid が登録応答と一致する
    detail = client.get(f"{API}/user/pid").json()
    assert detail["revision"] == entry["revision"]
    assert detail["library_uid"] == data["library_uid"]
    assert detail["block"] == stored["entries"][0]["block"]


def test_user_library_status_before_first_write(client: TestClient) -> None:
    listing = client.get(API).json()
    assert listing["user_library"] == {
        "name": "user",
        "enabled": True,
        "exists": False,
        "writable": True,
        "write_disabled_reason": "",
    }


def test_register_stores_canonical_form(client: TestClient) -> None:
    """保存するのは構築後に ``to_dict()`` を取り直した正規形 (既定値の補完を含む)。"""
    body = subsystem_body(
        [{"id": "int", "type": "flode.blocks.continuous.Integrator", "params": {}}]
    )
    assert client.post(ENTRIES, json={"block": body, "display_name": "I"}).status_code == 200
    stored = client.get(f"{API}/user/i").json()["block"]
    inner = {b["id"]: b for b in stored["params"]["blocks"]}
    assert "x0" in inner["int"]["params"]


def test_register_strips_only_top_level_provenance(client: TestClient) -> None:
    """再登録で外すのはトップレベルの由来だけ。内部ブロックの由来は残す (ADR-0080 §A3-4)。"""
    inner = subsystem_body([gain_block()], block_id="inner")
    inner["provenance"] = {**PROVENANCE, "entry": "inner_entry"}
    body = subsystem_body([inner], block_id="outer")
    body["provenance"] = dict(PROVENANCE)
    assert client.post(ENTRIES, json={"block": body, "display_name": "Nested"}).status_code == 200
    stored = client.get(f"{API}/user/nested").json()["block"]
    assert "provenance" not in stored
    stored_inner = next(b for b in stored["params"]["blocks"] if b["id"] == "inner")
    assert stored_inner["provenance"] == {**PROVENANCE, "entry": "inner_entry"}


def test_register_python_function_entry(client: TestClient) -> None:
    r = client.post(ENTRIES, json={"block": python_function_body(), "display_name": "Friction"})
    assert r.status_code == 200, r.text
    entry = r.json()["entry"]
    assert entry["kind"] == "python_function"
    assert entry["contains_python"] is True
    assert entry["python_block_paths"] == [""]
    detail = client.get(f"{API}/user/friction").json()
    assert detail["block"]["type"].endswith(".PythonFunction")
    assert detail["block"]["params"]["code"] == PASSTHROUGH_CODE


@pytest.mark.parametrize(
    ("display_name", "expected_id"),
    [
        ("PID", "pid"),
        ("  My  Fancy-Block!  ", "my_fancy_block"),
        ("摩擦モデル", "摩擦モデル"),
        ("ＰＩＤ（改）", "pid_改"),
        ("🚀🚀", "entry"),
        ("Export", "export_2"),
        ("entries", "entries_2"),
        ("x" * 64, "x" * 40),
    ],
)
def test_entry_id_is_generated_from_display_name(
    client: TestClient, display_name: str, expected_id: str
) -> None:
    r = _register(client, display_name)
    assert r.status_code == 200, r.text
    assert r.json()["entry"]["id"] == expected_id
    assert r.json()["entry"]["display_name"] == display_name.strip()
    assert client.get(f"{API}/user/{expected_id}").status_code == 200


def test_entry_id_collision_gets_numbered(client: TestClient) -> None:
    """表示名が違っても slug が同じなら ``_2``, ``_3`` を付ける。"""
    assert _register(client, "My Block").json()["entry"]["id"] == "my_block"
    assert _register(client, "my-block").json()["entry"]["id"] == "my_block_2"
    assert _register(client, "MY_BLOCK").json()["entry"]["id"] == "my_block_3"


@pytest.mark.parametrize(
    ("fields", "field"),
    [
        ({"display_name": "   "}, "display_name"),
        ({"display_name": "x" * 65}, "display_name"),
        ({"display_name": "ok", "description": "d" * 1001}, "description"),
        ({"display_name": "ok", "category_suffix": "c" * 65}, "category_suffix"),
    ],
)
def test_register_rejects_invalid_metadata(
    client: TestClient, user_dir: Path, fields: dict[str, str], field: str
) -> None:
    r = client.post(ENTRIES, json={"block": subsystem_body(), **fields})
    args = _error(r, 422, "library_entry_invalid")
    assert args["reason"] == "invalid_metadata"
    assert args["field"] == field
    assert not user_dir.exists()


def test_register_accepts_longest_allowed_metadata(client: TestClient) -> None:
    r = _register(client, "n" * 64, description="d" * 1000, category_suffix="c" * 64)
    assert r.status_code == 200


# ----------------------------------------------------------------------------
# 登録の検証 (深い検証 / Goto・From の閉包、ADR-0080 §A2 / §A4-5)
# ----------------------------------------------------------------------------


def _goto(tag: str, visibility: str = "local") -> dict[str, Any]:
    return {
        "id": f"goto_{tag}",
        "type": GOTO_TYPE,
        "params": {"tag": tag, "tag_visibility": visibility},
    }


def _from(tag: str) -> dict[str, Any]:
    return {"id": f"from_{tag}", "type": FROM_TYPE, "params": {"tag": tag}}


def test_register_accepts_closed_local_goto_from(client: TestClient) -> None:
    body = subsystem_body()
    body["params"]["blocks"].extend([_goto("A"), _from("A")])
    body["params"]["connections"] = [_wire("Inport_0", "goto_A"), _wire("from_A", "Outport_0")]
    r = client.post(ENTRIES, json={"block": body, "display_name": "Routed"})
    assert r.status_code == 200, r.text


def test_register_rejects_from_resolved_outside_the_block(
    client: TestClient, user_dir: Path
) -> None:
    body = subsystem_body()
    body["params"]["blocks"].append(_from("OUTER"))
    body["params"]["connections"] = [_wire("from_OUTER", "Outport_0")]
    args = _error(
        client.post(ENTRIES, json={"block": body, "display_name": "Leaky"}),
        422,
        "library_entry_invalid",
    )
    assert args["reason"] == "goto_from_not_closed"
    assert args["violations"] == [
        {"path": "from_OUTER", "tag": "OUTER", "reason": "unresolved_from"}
    ]
    assert not user_dir.exists()


def test_register_rejects_global_goto_with_nested_path(client: TestClient) -> None:
    inner = subsystem_body(block_id="inner")
    inner["params"]["blocks"].append(_goto("G", "global"))
    inner["params"]["connections"].append(_wire("Inport_0", "goto_G"))
    args = _error(
        client.post(ENTRIES, json={"block": subsystem_body([inner]), "display_name": "Global"}),
        422,
        "library_entry_invalid",
    )
    assert args["violations"] == [{"path": "inner/goto_G", "tag": "G", "reason": "global_goto"}]


@pytest.mark.parametrize(
    ("block", "reason"),
    [
        (gain_block(), "invalid_block"),  # 種別外 (Subsystem でも PythonFunction でもない)
        ("not an object", "invalid_block"),
        ({"id": "x", "type": "os.system", "params": {}}, "invalid_block"),
        ({"id": "x", "type": "flode.subsystems.subsystem.Subsystem"}, "invalid_block"),
        (
            subsystem_body(
                [{"id": "g", "type": "flode.blocks.mathops.Gain", "params": {"nope": 1}}]
            ),
            "invalid_block",
        ),
        (python_function_body("this is not python"), "invalid_block"),
    ],
    ids=["kind", "not-dict", "disallowed-module", "no-params", "bad-inner-params", "bad-code"],
)
def test_register_rejects_invalid_block(
    client: TestClient, user_dir: Path, block: Any, reason: str
) -> None:
    args = _error(
        client.post(ENTRIES, json={"block": block, "display_name": "Bad"}),
        422,
        "library_entry_invalid",
    )
    assert args["reason"] == reason
    assert not user_dir.exists()


def test_register_rejects_unbuildable_wiring(client: TestClient) -> None:
    body = subsystem_body()
    body["params"]["connections"].append(_wire("Inport_0", "missing"))
    args = _error(
        client.post(ENTRIES, json={"block": body, "display_name": "Bad"}),
        422,
        "library_entry_invalid",
    )
    assert args["reason"] == "invalid_block"


def test_register_lists_unknown_inner_types(client: TestClient) -> None:
    body = subsystem_body([{"id": "p", "type": "flode.blocks.nope.Missing", "params": {}}])
    args = _error(
        client.post(ENTRIES, json={"block": body, "display_name": "Bad"}),
        422,
        "library_entry_invalid",
    )
    assert args["reason"] == "unknown_types"
    assert args["unknown_types"] == ["flode.blocks.nope.Missing"]


# ----------------------------------------------------------------------------
# 同名検出・上書き・別名保存 (ADR-0080 §A5)
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("second_name", ["PID", "  pid ", "Pid"])
def test_same_name_is_detected_by_server(
    client: TestClient, user_dir: Path, second_name: str
) -> None:
    """同名判定はサーバが最終権威: 前後 trim + NFC + casefold で比べる。"""
    first = _register(client, "PID").json()["entry"]
    before = (user_dir / USER_FILE).read_bytes()
    args = _error(_register(client, second_name), 409, "library_entry_name_conflict")
    assert args["entry_id"] == first["id"]
    assert args["revision"] == 1
    assert args["display_name"] == "PID"
    assert (user_dir / USER_FILE).read_bytes() == before


def test_same_name_detection_uses_nfc_not_nfkc(client: TestClient) -> None:
    assert _register(client, "Caf\u00e9").status_code == 200
    _error(_register(client, "Cafe\u0301"), 409, "library_entry_name_conflict")
    # \u5168\u89d2\u306f NFC \u3067\u306f\u5225\u306e\u540d\u524d (id \u306e slug \u3060\u3051\u304c\u885d\u7a81\u3057\u3066\u63a1\u756a\u3055\u308c\u308b)
    assert _register(client, "PID").json()["entry"]["id"] == "pid"
    assert _register(client, "\uff30\uff29\uff24").json()["entry"]["id"] == "pid_2"


def test_save_as_new_keeps_both_entries_with_distinct_names(client: TestClient) -> None:
    _register(client, "PID")
    r = _register(client, "PID", save_as_new=True)
    assert r.status_code == 200, r.text
    assert (r.json()["entry"]["id"], r.json()["entry"]["display_name"]) == ("pid_2", "PID (2)")
    r = _register(client, "pid", save_as_new=True)
    assert (r.json()["entry"]["id"], r.json()["entry"]["display_name"]) == ("pid_3", "pid (3)")
    names = [e["display_name"] for e in _libraries(client)["user"]["entries"]]
    assert names == ["PID", "PID (2)", "pid (3)"]


def test_save_as_new_without_conflict_keeps_the_name(client: TestClient) -> None:
    r = _register(client, "Fresh", save_as_new=True)
    assert r.json()["entry"]["display_name"] == "Fresh"


def test_save_as_new_respects_name_length_limit(client: TestClient) -> None:
    long_name = "n" * 64
    _register(client, long_name)
    r = _register(client, long_name, save_as_new=True)
    assert r.json()["entry"]["display_name"] == "n" * 60 + " (2)"


def test_overwrite_increments_revision_and_updates_timestamp(
    client: TestClient, user_dir: Path, mocker: MockerFixture
) -> None:
    mocker.patch.object(
        library_store, "utc_timestamp", side_effect=["2026-11-13T10:00:00Z", "2026-11-13T11:00:00Z"]
    )
    first = _register(client, "PID").json()
    assert first["entry"]["updated_at"] == "2026-11-13T10:00:00Z"
    r = client.post(
        ENTRIES,
        json={
            "block": subsystem_body([gain_block(k=5.0)]),
            "display_name": "PID",
            "description": "improved",
            "overwrite_entry_id": "pid",
            "expected_revision": 1,
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["entry"]["id"] == "pid"
    assert data["entry"]["revision"] == 2
    assert data["entry"]["updated_at"] == "2026-11-13T11:00:00Z"
    assert data["entry"]["description"] == "improved"
    assert data["library_uid"] == first["library_uid"]  # uid は初回書き込みで決まり、変わらない
    detail = client.get(f"{API}/user/pid").json()
    assert detail["revision"] == 2
    gain = next(b for b in detail["block"]["params"]["blocks"] if b["id"] == "gain")
    assert gain["params"]["k"] == 5.0
    assert len(_read_user_file(user_dir)["entries"]) == 1


def test_overwrite_may_rename_but_not_onto_another_entry(client: TestClient) -> None:
    _register(client, "PID")
    _register(client, "Other")
    renamed = client.post(
        ENTRIES,
        json={
            "block": subsystem_body(),
            "display_name": "PID v2",
            "overwrite_entry_id": "pid",
            "expected_revision": 1,
        },
    )
    assert renamed.status_code == 200
    assert renamed.json()["entry"]["id"] == "pid"  # id は変わらない (由来の突合キー)
    clash = client.post(
        ENTRIES,
        json={
            "block": subsystem_body(),
            "display_name": "other",
            "overwrite_entry_id": "pid",
            "expected_revision": 2,
        },
    )
    assert _error(clash, 409, "library_entry_name_conflict")["entry_id"] == "other"


def test_overwrite_with_stale_revision_is_conflict(client: TestClient, user_dir: Path) -> None:
    _register(client, "PID")
    before = (user_dir / USER_FILE).read_bytes()
    r = client.post(
        ENTRIES,
        json={
            "block": subsystem_body(),
            "display_name": "PID",
            "overwrite_entry_id": "pid",
            "expected_revision": 5,
        },
    )
    args = _error(r, 409, "library_entry_conflict")
    assert (args["entry_id"], args["expected_revision"], args["current_revision"]) == ("pid", 5, 1)
    assert (user_dir / USER_FILE).read_bytes() == before


def test_overwrite_requires_expected_revision_and_excludes_save_as_new(client: TestClient) -> None:
    _register(client, "PID")
    base = {"block": subsystem_body(), "display_name": "PID", "overwrite_entry_id": "pid"}
    assert _error(client.post(ENTRIES, json=base), 422, "library_entry_invalid")["field"] == (
        "overwrite_entry_id"
    )
    both = {**base, "expected_revision": 1, "save_as_new": True}
    _error(client.post(ENTRIES, json=both), 422, "library_entry_invalid")


def test_overwrite_missing_entry_is_404(client: TestClient) -> None:
    r = client.post(
        ENTRIES,
        json={
            "block": subsystem_body(),
            "display_name": "X",
            "overwrite_entry_id": "ghost",
            "expected_revision": 1,
        },
    )
    assert _error(r, 404, "library_entry_not_found")["entry_id"] == "ghost"


# ----------------------------------------------------------------------------
# メタデータ編集 (PATCH) / エントリ削除
# ----------------------------------------------------------------------------


def test_patch_updates_only_sent_fields_and_keeps_revision(client: TestClient) -> None:
    created = _register(client, "PID", description="old", category_suffix="controllers").json()[
        "entry"
    ]
    r = client.patch(f"{ENTRIES}/pid", json={"description": " new text "})
    assert r.status_code == 200, r.text
    entry = r.json()["entry"]
    assert entry["description"] == "new text"
    assert entry["display_name"] == "PID"
    assert entry["category_suffix"] == "controllers"
    assert entry["revision"] == 1  # 本体が変わらないので上げない
    assert entry["updated_at"] == created["updated_at"]
    assert r.json()["library"] == "user"
    detail = client.get(f"{API}/user/pid").json()
    assert (detail["description"], detail["revision"]) == ("new text", 1)


def test_patch_can_rename_and_clear_fields(client: TestClient) -> None:
    _register(client, "PID", description="old", category_suffix="controllers")
    r = client.patch(
        f"{ENTRIES}/pid", json={"display_name": "PID 2", "description": "", "category_suffix": ""}
    )
    entry = r.json()["entry"]
    assert (entry["id"], entry["display_name"], entry["description"], entry["category_suffix"]) == (
        "pid",
        "PID 2",
        "",
        "",
    )


def test_patch_to_own_name_is_not_a_conflict(client: TestClient) -> None:
    _register(client, "PID")
    assert client.patch(f"{ENTRIES}/pid", json={"display_name": "pid"}).status_code == 200


def test_patch_rejects_name_of_another_entry(client: TestClient) -> None:
    _register(client, "PID")
    _register(client, "Other")
    args = _error(
        client.patch(f"{ENTRIES}/other", json={"display_name": " pid "}),
        409,
        "library_entry_name_conflict",
    )
    assert args["entry_id"] == "pid"


def test_patch_validates_values_and_fields(client: TestClient) -> None:
    _register(client, "PID")
    _error(client.patch(f"{ENTRIES}/pid", json={"display_name": " "}), 422, "library_entry_invalid")
    assert client.patch(f"{ENTRIES}/pid", json={"block": subsystem_body()}).status_code == 422
    assert client.patch(f"{ENTRIES}/pid", json={"revision": 9}).status_code == 422
    assert client.patch(f"{ENTRIES}/pid", json={"description": 3}).status_code == 422


def test_patch_missing_entry_is_404(client: TestClient) -> None:
    _error(
        client.patch(f"{ENTRIES}/ghost", json={"description": "x"}), 404, "library_entry_not_found"
    )
    _register(client, "PID")
    _error(
        client.patch(f"{ENTRIES}/ghost", json={"description": "x"}), 404, "library_entry_not_found"
    )


def test_empty_patch_does_not_rewrite_the_file(client: TestClient, user_dir: Path) -> None:
    _register(client, "PID")
    r = client.patch(f"{ENTRIES}/pid", json={})
    assert r.status_code == 200
    assert r.json()["entry"]["id"] == "pid"
    assert _names(user_dir) == [USER_FILE]  # 書いていないので .bak もできない
    _error(client.patch(f"{ENTRIES}/ghost", json={}), 404, "library_entry_not_found")


def test_delete_entry(client: TestClient, user_dir: Path) -> None:
    uid = _register(client, "PID").json()["library_uid"]
    _register(client, "Other")
    r = client.delete(f"{ENTRIES}/pid", params={"expected_revision": 1})
    assert r.status_code == 200, r.text
    assert r.json() == {"library": "user", "library_uid": uid, "deleted": "pid"}
    assert client.get(f"{API}/user/pid").status_code == 404
    assert [e["id"] for e in _read_user_file(user_dir)["entries"]] == ["other"]
    # 最後の 1 件を消してもファイルと uid は残る
    assert client.delete(f"{ENTRIES}/other", params={"expected_revision": 1}).status_code == 200
    stored = _read_user_file(user_dir)
    assert (stored["entries"], stored["uid"]) == ([], uid)
    assert _libraries(client)["user"]["entries"] == []


def test_delete_entry_requires_matching_revision(client: TestClient) -> None:
    _register(client, "PID")
    assert client.delete(f"{ENTRIES}/pid").status_code == 422
    assert client.delete(f"{ENTRIES}/pid", params={"expected_revision": "x"}).status_code == 422
    args = _error(
        client.delete(f"{ENTRIES}/pid", params={"expected_revision": 2}),
        409,
        "library_entry_conflict",
    )
    assert args["current_revision"] == 1
    assert client.get(f"{API}/user/pid").status_code == 200
    _error(
        client.delete(f"{ENTRIES}/ghost", params={"expected_revision": 1}),
        404,
        "library_entry_not_found",
    )


# ----------------------------------------------------------------------------
# ファイルの耐久性 (ADR-0080 §A6)
# ----------------------------------------------------------------------------


def test_write_keeps_one_backup_generation_and_no_temp_files(
    client: TestClient, user_dir: Path
) -> None:
    _register(client, "A")
    first = (user_dir / USER_FILE).read_bytes()
    assert _names(user_dir) == [USER_FILE]
    _register(client, "B")
    second = (user_dir / USER_FILE).read_bytes()
    assert _names(user_dir) == [USER_FILE, USER_FILE + ".bak"]
    assert (user_dir / (USER_FILE + ".bak")).read_bytes() == first
    _register(client, "C")
    assert _names(user_dir) == [USER_FILE, USER_FILE + ".bak"]
    assert (user_dir / (USER_FILE + ".bak")).read_bytes() == second
    # 書き込んだファイルはそのまま正規のローダで読める
    assert [e.id for e in load_library(user_dir / USER_FILE).entries] == ["a", "b", "c"]


def test_first_write_to_legacy_file_keeps_pre_v4_backup(tmp_path: Path, user_dir: Path) -> None:
    _write_json(user_dir / USER_FILE, legacy_v3_library_dict("user", {"old": subsystem_body()}))
    original = (user_dir / USER_FILE).read_bytes()
    with _open_client(tmp_path, user_library_dir=user_dir) as client:
        assert _libraries(client)["user"]["uid"] is None
        assert _register(client, "New").status_code == 200
        pre_v4 = user_dir / (USER_FILE + ".pre-v4.bak")
        assert pre_v4.read_bytes() == original
        assert _names(user_dir) == [USER_FILE, USER_FILE + ".bak", USER_FILE + ".pre-v4.bak"]
        stored = _read_user_file(user_dir)
        assert stored["schema_version"] == "libraries.v4"
        assert [e["id"] for e in stored["entries"]] == ["old", "new"]
        assert stored["entries"][0]["revision"] == 1 and "block" in stored["entries"][0]
        assert len(stored["uid"]) == 36  # GUI の初回書き込みで uid が付く
        # 2 回目以降は作り直さない
        assert _register(client, "Newer").status_code == 200
        assert pre_v4.read_bytes() == original


def test_existing_pre_v4_backup_is_never_overwritten(tmp_path: Path, user_dir: Path) -> None:
    _write_json(user_dir / USER_FILE, legacy_v3_library_dict("user", {"old": subsystem_body()}))
    pre_v4 = user_dir / (USER_FILE + ".pre-v4.bak")
    pre_v4.write_bytes(b"precious")
    with _open_client(tmp_path, user_library_dir=user_dir) as client:
        assert _register(client, "New").status_code == 200
    assert pre_v4.read_bytes() == b"precious"


def _corrupt_cases() -> list[tuple[str, str]]:
    wrong_name = json.dumps(library_dict("not_user", {"pid": subsystem_body()}))
    bad_entry = json.dumps(library_dict("user", {"pid": gain_block()}))
    return [("{not json", "json"), (wrong_name, "name"), (bad_entry, "schema"), ("[]", "array")]


@pytest.mark.parametrize(
    "content", [c for c, _ in _corrupt_cases()], ids=[i for _, i in _corrupt_cases()]
)
def test_corrupt_user_library_is_never_overwritten(
    tmp_path: Path, user_dir: Path, content: str
) -> None:
    user_dir.mkdir()
    (user_dir / USER_FILE).write_text(content, encoding="utf-8")
    (user_dir / (USER_FILE + ".bak")).write_text("backup", encoding="utf-8")
    with _open_client(tmp_path, user_library_dir=user_dir) as client:
        listing = client.get(API).json()
        assert "user" not in [lib["name"] for lib in listing["libraries"]]
        assert any(USER_FILE in e["path"] for e in listing["load_errors"])
        assert listing["user_library"]["exists"] is False
        assert listing["user_library"]["writable"] is False
        assert listing["user_library"]["write_disabled_reason"] == "user_library_corrupt"
        for response in (
            _register(client),
            client.patch(f"{ENTRIES}/pid", json={"description": "x"}),
            client.delete(f"{ENTRIES}/pid", params={"expected_revision": 1}),
        ):
            args = _error(response, 409, "user_library_corrupt")
            assert args["path"].endswith(USER_FILE)
            assert args["has_backup"] is True
            assert args["reason"]
    assert (user_dir / USER_FILE).read_text(encoding="utf-8") == content
    assert (user_dir / (USER_FILE + ".bak")).read_text(encoding="utf-8") == "backup"
    assert _names(user_dir) == [USER_FILE, USER_FILE + ".bak"]


def test_corrupt_error_reports_missing_backup(tmp_path: Path, user_dir: Path) -> None:
    user_dir.mkdir()
    (user_dir / USER_FILE).write_text("{", encoding="utf-8")
    with _open_client(tmp_path, user_library_dir=user_dir) as client:
        assert _error(_register(client), 409, "user_library_corrupt")["has_backup"] is False


def test_user_library_from_newer_flode_is_never_downgraded(tmp_path: Path, user_dir: Path) -> None:
    data = library_dict("user", {"pid": subsystem_body()})
    data["schema_version"] = "libraries.v5"
    _write_json(user_dir / USER_FILE, data)
    before = (user_dir / USER_FILE).read_bytes()
    with _open_client(tmp_path, user_library_dir=user_dir) as client:
        assert client.get(API).json()["user_library"]["write_disabled_reason"] == (
            "library_schema_too_new"
        )
        args = _error(_register(client), 409, "library_schema_too_new")
    assert args["schema_version"] == "libraries.v5"
    assert args["supported"] == "libraries.v4"
    assert (user_dir / USER_FILE).read_bytes() == before
    assert _names(user_dir) == [USER_FILE]


def test_external_change_on_disk_is_detected(client: TestClient, user_dir: Path) -> None:
    _register(client, "PID")
    # 別プロセス (エディタ等) がエントリを足して保存した状況
    edited = _read_user_file(user_dir)
    edited["entries"].append({"id": "manual", "display_name": "Manual", "block": subsystem_body()})
    (user_dir / USER_FILE).write_text(json.dumps(edited, indent=2), encoding="utf-8")
    on_disk = (user_dir / USER_FILE).read_bytes()
    for response in (
        _register(client, "Another"),
        client.patch(f"{ENTRIES}/pid", json={"description": "x"}),
        client.delete(f"{ENTRIES}/pid", params={"expected_revision": 1}),
    ):
        _error(response, 409, "library_changed_on_disk")
    assert (user_dir / USER_FILE).read_bytes() == on_disk  # 外部の編集を上書きしない
    # 再読み込みすれば外部の編集を取り込んだうえで書ける
    assert client.post(f"{API}/reload").status_code == 200
    assert _register(client, "Another").status_code == 200
    assert [e["id"] for e in _read_user_file(user_dir)["entries"]] == ["pid", "manual", "another"]


def test_file_created_externally_after_startup_is_detected(
    client: TestClient, user_dir: Path
) -> None:
    """起動時に無かったファイルが外部で作られていたら、黙って上書きしない。"""
    _write_json(user_dir / USER_FILE, library_dict("user", {"mine": subsystem_body()}))
    _error(_register(client), 409, "library_changed_on_disk")
    assert [e["id"] for e in _read_user_file(user_dir)["entries"]] == ["mine"]


def test_file_deleted_externally_is_detected(client: TestClient, user_dir: Path) -> None:
    _register(client, "PID")
    (user_dir / USER_FILE).unlink()
    _error(_register(client, "Another"), 409, "library_changed_on_disk")
    assert not (user_dir / USER_FILE).exists()


def test_replace_blocked_by_another_process_is_503(
    client: TestClient, user_dir: Path, mocker: MockerFixture
) -> None:
    """Windows で置換が他プロセスに阻まれ続けたら 503。ファイルは変わらない。"""
    _register(client, "PID")
    before = (user_dir / USER_FILE).read_bytes()
    mocker.patch.object(_atomic, "_RETRY_PERMISSION_ERRORS", True)
    sleep = mocker.patch.object(_atomic.time, "sleep")
    replace = mocker.patch.object(_atomic.os, "replace", side_effect=PermissionError("locked"))
    _error(_register(client, "Another"), 503, "library_write_busy")
    assert replace.call_count == _atomic.REPLACE_MAX_ATTEMPTS
    assert sleep.call_count == _atomic.REPLACE_MAX_ATTEMPTS - 1
    mocker.stopall()
    assert (user_dir / USER_FILE).read_bytes() == before
    assert _names(user_dir) == [USER_FILE]
    # 失敗後も registry とファイルは整合したままで、次の書き込みは通る
    assert _register(client, "Another").status_code == 200


def test_unwritable_directory_is_500(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where a directory is needed", encoding="utf-8")
    with _open_client(tmp_path, user_library_dir=blocker / "libraries") as client:
        args = _error(_register(client), 500, "library_write_failed")
        assert "message" in args
        assert _error(
            _import(client, library_dict("lib", {"e": subsystem_body()})),
            500,
            "library_write_failed",
        )
    assert blocker.read_text(encoding="utf-8").startswith("a file")


# ----------------------------------------------------------------------------
# パスの安全性 (ADR-0080 §A4-3)
# ----------------------------------------------------------------------------


def _link_directory_or_skip(link: Path, target: Path) -> None:
    """ディレクトリへのリンクを作る。symlink が無理なら Windows の junction を試す。"""
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except (OSError, NotImplementedError) as e:
        if sys.platform != "win32":
            pytest.skip(f"cannot create symlinks in this environment: {e}")
    import _winapi

    try:
        _winapi.CreateJunction(str(target), str(link))
    except OSError as e:
        pytest.skip(f"cannot create a symlink or junction in this environment: {e}")


@pytest.mark.parametrize("entry_id", ["../../outside", "..%2F..%2Foutside", "C:%5Cevil", "%2e%2e"])
def test_client_supplied_ids_are_only_lookup_keys(
    client: TestClient, tmp_path: Path, user_dir: Path, entry_id: str
) -> None:
    """URL の id はエントリの検索にしか使わない (path にならない)。"""
    _register(client, "PID")
    before = (user_dir / USER_FILE).read_bytes()
    tree_before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    assert client.patch(f"{ENTRIES}/{entry_id}", json={"description": "x"}).status_code in (
        404,
        405,
    )
    assert client.delete(f"{ENTRIES}/{entry_id}", params={"expected_revision": 1}).status_code in (
        404,
        405,
    )
    assert client.delete(f"{API}/{entry_id}").status_code in (404, 405)
    assert client.get(f"{API}/{entry_id}/export").status_code == 404
    assert (user_dir / USER_FILE).read_bytes() == before
    assert sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")) == tree_before


def test_import_never_uses_client_filename_or_library_name_as_path(
    client: TestClient, tmp_path: Path, user_dir: Path
) -> None:
    data = library_dict("CON", {"e": subsystem_body()})
    r = _import(client, data, filename="..\\..\\evil.flwlib.json")
    assert r.status_code == 200, r.text
    (saved,) = _names(user_dir / "imported")
    assert saved.startswith("lib-con-") and saved.endswith(".flwlib.json")
    assert len(saved) == len("lib-con-") + 8 + len(".flwlib.json")
    assert not list(tmp_path.rglob("evil*"))


@pytest.mark.parametrize("name", ["a/b", "a\\b", "..", "x" * 65, "tab\tname"])
def test_import_rejects_unroutable_library_names(
    client: TestClient, user_dir: Path, name: str
) -> None:
    args = _error(
        _import(client, library_dict(name, {"e": subsystem_body()})), 422, "library_file_invalid"
    )
    assert args["reason"] == "invalid_name"
    assert not (user_dir / "imported").exists()


def test_write_through_escaping_user_file_link_is_refused(tmp_path: Path, user_dir: Path) -> None:
    outside = tmp_path / "outside.flwlib.json"
    _write_json(outside, library_dict("user", {"pid": subsystem_body()}))
    before = outside.read_bytes()
    user_dir.mkdir()
    try:
        (user_dir / USER_FILE).symlink_to(outside)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"cannot create symlinks in this environment: {e}")
    with _open_client(tmp_path, user_library_dir=user_dir) as client:
        _error(_register(client), 403, "library_path_unsafe")
    assert outside.read_bytes() == before


def test_import_into_escaping_imported_directory_is_refused(tmp_path: Path, user_dir: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    user_dir.mkdir()
    _link_directory_or_skip(user_dir / "imported", elsewhere)
    with _open_client(tmp_path, user_library_dir=user_dir) as client:
        args = _error(
            _import(client, library_dict("lib", {"e": subsystem_body()})),
            403,
            "library_path_unsafe",
        )
    assert "path" not in args  # 解決先の path は応答に出さない
    assert _names(elsewhere) == []


def test_delete_refuses_file_that_no_longer_sits_in_imported(
    client: TestClient, user_dir: Path, mocker: MockerFixture
) -> None:
    """削除の直前にも包含確認を行う (symlink を作れない環境向けに確認関数を差し替える)。"""
    from flode.exceptions import PathTraversalError

    assert _import(client, library_dict("lib", {"e": subsystem_body()})).status_code == 200
    (saved,) = _names(user_dir / "imported")
    mocker.patch.object(
        library_store, "ensure_direct_child", side_effect=PathTraversalError("escapes")
    )
    _error(client.delete(f"{API}/lib"), 403, "library_path_unsafe")
    assert _names(user_dir / "imported") == [saved]
    assert "lib" in _libraries(client)


# ----------------------------------------------------------------------------
# 取り込み (ADR-0080 §A4-4 / §A6-4)
# ----------------------------------------------------------------------------


def _shared_library() -> dict[str, Any]:
    return library_dict(
        "Shared Lib",
        {
            "plain": subsystem_body([gain_block()]),
            "code": python_function_body(),
            "wrapped": subsystem_body([python_function_body(block_id="inner_pf")]),
        },
        display_name="Shared",
    )


def test_import_dry_run_reports_without_writing(client: TestClient, user_dir: Path) -> None:
    r = _import(client, _shared_library(), dry_run=True, filename="shared.flwlib.json")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["dry_run"] is True
    assert data["library"]["name"] == "Shared Lib"
    assert data["library"]["display_name"] == "Shared"
    assert data["library"]["entry_count"] == 3
    assert data["python_entries"] == [
        {"id": "code", "display_name": "Code", "python_block_paths": [""]},
        {"id": "wrapped", "display_name": "Wrapped", "python_block_paths": ["inner_pf"]},
    ]
    assert data["unknown_types"] == []
    assert data["conflict"] is None
    assert not user_dir.exists()
    assert "Shared Lib" not in _libraries(client)


def test_import_saves_normalized_read_only_library(client: TestClient, user_dir: Path) -> None:
    r = _import(client, _shared_library())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["dry_run"] is False
    assert (data["unknown_types"], data["conflict"]) == ([], None)
    (saved,) = _names(user_dir / "imported")
    assert saved.startswith("shared-lib-") and saved.endswith(".flwlib.json")
    stored = json.loads((user_dir / "imported" / saved).read_text(encoding="utf-8"))
    assert stored["schema_version"] == "libraries.v4"
    assert stored["model_schema_version"] == CURRENT_SCHEMA_VERSION
    assert stored["name"] == "Shared Lib"
    assert stored["uid"] == data["library"]["uid"] and len(stored["uid"]) == 36
    # 一覧: read-only の別ライブラリとして user と path の間に並ぶ
    lib = _libraries(client)["Shared Lib"]
    assert (lib["origin"], lib["writable"], lib["write_disabled_reason"]) == (
        "imported",
        False,
        "library_read_only",
    )
    assert [e["id"] for e in lib["entries"]] == ["plain", "code", "wrapped"]
    assert [e["contains_python"] for e in lib["entries"]] == [False, True, True]
    detail = client.get(f"{API}/Shared Lib/plain").json()
    assert detail["library_uid"] == stored["uid"]
    # マイブロックは作られない (マージしない)
    assert not (user_dir / USER_FILE).exists()


def test_import_keeps_existing_uid_and_canonicalizes_bodies(
    client: TestClient, user_dir: Path
) -> None:
    body = subsystem_body(
        [{"id": "int", "type": "flode.blocks.continuous.Integrator", "params": {}}]
    )
    body["provenance"] = dict(PROVENANCE)
    data = library_dict("lib", {"e": body}, uid="fixed-uid-123")
    assert _import(client, data).status_code == 200
    (saved,) = _names(user_dir / "imported")
    stored = json.loads((user_dir / "imported" / saved).read_text(encoding="utf-8"))
    assert stored["uid"] == "fixed-uid-123"
    stored_body = stored["entries"][0]["block"]
    assert "provenance" not in stored_body
    assert "x0" in next(b for b in stored_body["params"]["blocks"] if b["id"] == "int")["params"]


def test_import_migrates_legacy_file_to_v4(client: TestClient, user_dir: Path) -> None:
    r = _import(client, legacy_v3_library_dict("legacy", {"old": subsystem_body([gain_block()])}))
    assert r.status_code == 200, r.text
    (saved,) = _names(user_dir / "imported")
    stored = json.loads((user_dir / "imported" / saved).read_text(encoding="utf-8"))
    assert stored["schema_version"] == "libraries.v4"
    assert "subsystem" not in stored["entries"][0]
    assert stored["entries"][0]["revision"] == 1
    assert client.get(f"{API}/legacy/old").json()["kind"] == "subsystem"


@pytest.mark.parametrize(
    ("name", "reason"), [("user", "reserved"), ("std", "reserved"), ("dup", "exists")]
)
def test_import_name_conflict(tmp_path: Path, user_dir: Path, name: str, reason: str) -> None:
    existing = tmp_path / "dup.flwlib.json"
    _write_json(existing, library_dict("dup", {"e": subsystem_body()}))
    data = library_dict(name, {"e": subsystem_body()})
    with _open_client(tmp_path, user_library_dir=user_dir, library_paths=[existing]) as client:
        dry = _import(client, data, dry_run=True)
        assert dry.status_code == 200
        assert dry.json()["conflict"] == {"name": name, "reason": reason}
        args = _error(_import(client, data), 409, "library_name_conflict")
    assert (args["library"], args["reason"]) == (name, reason)
    assert not user_dir.exists()


def test_reimport_of_same_library_is_rejected_until_deleted(
    client: TestClient, user_dir: Path
) -> None:
    data = library_dict("lib", {"e": subsystem_body()})
    assert _import(client, data).status_code == 200
    _error(_import(client, data), 409, "library_name_conflict")
    assert len(_names(user_dir / "imported")) == 1
    assert client.delete(f"{API}/lib").status_code == 200
    assert _import(client, data).status_code == 200


def test_import_unknown_types_are_listed_then_rejected(client: TestClient, user_dir: Path) -> None:
    data = library_dict(
        "lib",
        {
            "a": subsystem_body([{"id": "p", "type": "flode.blocks.zzz.Plugin", "params": {}}]),
            "b": subsystem_body([{"id": "q", "type": "other_pkg.blocks.Thing", "params": {}}]),
        },
    )
    dry = _import(client, data, dry_run=True)
    assert dry.status_code == 200
    assert dry.json()["unknown_types"] == ["flode.blocks.zzz.Plugin", "other_pkg.blocks.Thing"]
    args = _error(_import(client, data), 422, "library_entry_invalid")
    assert args["reason"] == "unknown_types"
    assert args["unknown_types"] == ["flode.blocks.zzz.Plugin", "other_pkg.blocks.Thing"]
    assert not user_dir.exists()


@pytest.mark.parametrize("dry_run", [True, False])
def test_import_runs_deep_validation_on_every_entry(
    client: TestClient, user_dir: Path, dry_run: bool
) -> None:
    leaky = subsystem_body()
    leaky["params"]["blocks"].append(_from("OUTER"))
    leaky["params"]["connections"] = [_wire("from_OUTER", "Outport_0")]
    data = library_dict("lib", {"good": subsystem_body(), "leaky": leaky})
    args = _error(_import(client, data, dry_run=dry_run), 422, "library_entry_invalid")
    assert args["entry_id"] == "leaky"
    assert args["reason"] == "goto_from_not_closed"
    assert not user_dir.exists()


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("{not json", "invalid_json"),
        ("[]", "invalid_library"),
        (
            json.dumps({"schema_version": "libraries.v9", "name": "x", "entries": []}),
            "invalid_library",
        ),
        (json.dumps(library_dict("lib", {"e": gain_block()})), "invalid_library"),
        (json.dumps({"x": _nested(200)}), "too_deep"),
        ("[" * 200_000, "too_deep"),
    ],
    ids=["json", "array", "too-new", "kind", "deep", "absurdly-deep"],
)
def test_import_rejects_unreadable_content(
    client: TestClient, user_dir: Path, content: str, reason: str
) -> None:
    for dry_run in (True, False):
        args = _error(_import(client, content, dry_run=dry_run), 422, "library_file_invalid")
        assert args["reason"] == reason
    assert not user_dir.exists()


@pytest.mark.parametrize(
    "body",
    [
        {"dry_run": True},
        {"content": {"a": 1}},
        {"content": "{}", "dry_run": "no"},
        {"content": "{}", "path": "x"},
    ],
)
def test_malformed_import_body_is_422(client: TestClient, body: dict[str, Any]) -> None:
    r = client.post(f"{API}/import", json=body)
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str)


# ----------------------------------------------------------------------------
# 取り込みライブラリの削除 / 再読み込み
# ----------------------------------------------------------------------------


def test_delete_imported_library_renames_file_to_bak(client: TestClient, user_dir: Path) -> None:
    assert _import(client, library_dict("lib", {"e": subsystem_body()})).status_code == 200
    (saved,) = _names(user_dir / "imported")
    r = client.delete(f"{API}/lib")
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": "lib"}
    assert _names(user_dir / "imported") == [saved + ".bak"]
    assert "lib" not in _libraries(client)
    assert client.get(f"{API}/lib/e").status_code == 404
    # .bak は再読み込みでも拾われない
    assert client.post(f"{API}/reload").status_code == 200
    assert "lib" not in _libraries(client)


def test_only_imported_libraries_can_be_deleted(tmp_path: Path, user_dir: Path) -> None:
    by_path = tmp_path / "bypath.flwlib.json"
    _write_json(by_path, library_dict("bypath", {"e": subsystem_body()}))
    _write_json(user_dir / "manual.flwlib.json", library_dict("manual", {"e": subsystem_body()}))
    _write_json(
        user_dir / "imported" / "nested" / "deep.flwlib.json",
        library_dict("deep", {"e": subsystem_body()}),
    )
    with _open_client(tmp_path, user_library_dir=user_dir, library_paths=[by_path]) as client:
        _register(client, "PID")
        for name, origin in [
            ("std", "builtin"),
            ("user", "user"),
            ("bypath", "path"),
            ("manual", "path"),
            ("deep", "path"),
        ]:
            args = _error(client.delete(f"{API}/{name}"), 403, "library_read_only")
            assert (args["library"], args["origin"]) == (name, origin)
        assert _error(client.delete(f"{API}/ghost"), 404, "library_not_found")["library"] == "ghost"
        assert set(_libraries(client)) == {"std", "user", "bypath", "manual", "deep"}
    assert by_path.exists()
    assert (user_dir / USER_FILE).exists()
    assert (user_dir / "manual.flwlib.json").exists()


def test_reload_picks_up_hand_placed_files(client: TestClient, user_dir: Path) -> None:
    _register(client, "PID")
    _write_json(
        user_dir / "handmade.flwlib.json", library_dict("handmade", {"e": subsystem_body()})
    )
    _write_json(user_dir / "broken.flwlib.json", {"schema_version": "nope"})
    assert "handmade" not in _libraries(client)  # ファイル監視はしない
    r = client.post(f"{API}/reload")
    assert r.status_code == 200, r.text
    data = r.json()
    assert [lib["name"] for lib in data["libraries"]] == ["std", "user", "handmade"]
    assert data["libraries"][2]["origin"] == "path"
    assert data["libraries"][2]["writable"] is False
    assert any("broken.flwlib.json" in e["path"] for e in data["load_errors"])
    assert data["schema_version"] == "libraries.v4"
    assert data == client.get(API).json()
    # 再読み込み後も続けて書ける (ファイルの状態を取り直している)
    assert _register(client, "Another").status_code == 200


def test_reload_drops_files_removed_from_disk(client: TestClient, user_dir: Path) -> None:
    assert _import(client, library_dict("lib", {"e": subsystem_body()})).status_code == 200
    for f in (user_dir / "imported").iterdir():
        f.unlink()
    assert "lib" in _libraries(client)
    client.post(f"{API}/reload")
    assert "lib" not in _libraries(client)


# ----------------------------------------------------------------------------
# 書き出し (ADR-0080 §A4-6)
# ----------------------------------------------------------------------------


def test_export_user_library_is_renamed_and_importable_elsewhere(
    tmp_path: Path, client: TestClient, user_dir: Path
) -> None:
    uid = _register(client, "PID", description="controller").json()["library_uid"]
    client.post(ENTRIES, json={"block": python_function_body(), "display_name": "Friction"})
    r = client.get(f"{API}/user/export")
    assert r.status_code == 200, r.text
    exported_name = f"user-{uid[:8]}"
    assert r.headers["content-type"].startswith("application/json")
    assert r.headers["content-disposition"] == f'attachment; filename="{exported_name}.flwlib.json"'
    exported = r.json()
    assert exported["name"] == exported_name
    assert exported["uid"] == uid
    assert exported["display_name"] == "My Blocks"
    assert exported["schema_version"] == "libraries.v4"
    assert [e["id"] for e in exported["entries"]] == ["pid", "friction"]
    # 書き出しはファイルにも registry にも触れない
    assert _read_user_file(user_dir)["name"] == "user"
    assert set(_libraries(client)) == {"std", "user"}

    # 同じ環境へは取り込めない: uid が自分の user ライブラリと重なる (uid は registry 内で一意)
    dry = _import(client, r.text, dry_run=True)
    assert dry.status_code == 200
    assert dry.json()["conflict"] == {"name": "user", "reason": "uid_exists"}
    args = _error(_import(client, r.text), 409, "library_name_conflict")
    assert (args["library"], args["reason"], args["conflicts_with"]) == (
        exported_name,
        "uid_exists",
        "user",
    )
    assert not (user_dir / "imported").exists()

    # 別環境 (別の user_library_dir) で取り込める。uid は保たれ、由来を追跡できる
    other_root = tmp_path / "other"
    other_root.mkdir()
    other_dir = other_root / "libraries"
    with _open_client(other_root, user_library_dir=other_dir) as other:
        _register(other, "Mine")  # 取り込み先にも自分の user ライブラリがある
        dry = _import(other, r.text, dry_run=True).json()
        assert dry["conflict"] is None
        assert [e["id"] for e in dry["python_entries"]] == ["friction"]
        assert _import(other, r.text).status_code == 200
        libs = _libraries(other)
        assert libs[exported_name]["uid"] == uid
        assert libs[exported_name]["origin"] == "imported"
        assert libs["user"]["uid"] != uid
        detail = other.get(f"{API}/{exported_name}/pid").json()
        assert (detail["library_uid"], detail["revision"], detail["description"]) == (
            uid,
            1,
            "controller",
        )


def test_export_other_library_keeps_its_name(client: TestClient) -> None:
    r = client.get(f"{API}/std/export")
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="std.flwlib.json"'
    assert r.json()["name"] == "std"
    assert validate_library(r.json()).entries[0].id == "pid_controller"


def test_export_filename_is_a_server_made_slug(tmp_path: Path, user_dir: Path) -> None:
    weird = tmp_path / "weird.flwlib.json"
    _write_json(weird, library_dict('We"ird Näme', {"e": subsystem_body()}))
    with _open_client(tmp_path, user_library_dir=user_dir, library_paths=[weird]) as client:
        r = client.get(f'{API}/We"ird Näme/export')
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="we-ird-n-me.flwlib.json"'


def test_export_user_library_without_uid_gets_one_in_the_copy(
    tmp_path: Path, user_dir: Path
) -> None:
    _write_json(user_dir / USER_FILE, library_dict("user", {"pid": subsystem_body()}))
    before = (user_dir / USER_FILE).read_bytes()
    with _open_client(tmp_path, user_library_dir=user_dir) as client:
        exported = client.get(f"{API}/user/export").json()
    assert exported["name"] == f"user-{exported['uid'][:8]}"
    assert (user_dir / USER_FILE).read_bytes() == before


def test_export_unknown_library_is_404(client: TestClient) -> None:
    _error(client.get(f"{API}/ghost/export"), 404, "library_not_found")


# ----------------------------------------------------------------------------
# ルーティングの衝突 (固定パスとパラメータ付きパス)
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("entry_id", ["export", "entries"])
def test_hand_placed_library_with_reserved_entry_id_is_not_loaded(
    tmp_path: Path, user_dir: Path, entry_id: str
) -> None:
    """``/{name}/export`` がエントリ詳細に化けないよう、予約 id を持つファイルは読み込まない。"""
    path = tmp_path / "clash.flwlib.json"
    _write_json(path, library_dict("clash", {"ok": subsystem_body(), entry_id: subsystem_body()}))
    with _open_client(tmp_path, user_library_dir=user_dir, library_paths=[path]) as client:
        listing = client.get(API).json()
        assert "clash" not in [lib["name"] for lib in listing["libraries"]]
        (error,) = listing["load_errors"]
        assert Path(error["path"]).name == "clash.flwlib.json"
        assert entry_id in error["message"] and "reserved" in error["message"]
        _error(client.get(f"{API}/clash/export"), 404, "library_not_found")
        assert client.get(f"{API}/clash/{entry_id}").status_code == 404


def test_user_library_with_reserved_entry_id_is_treated_as_corrupt(
    tmp_path: Path, user_dir: Path
) -> None:
    """手で編集されたユーザーライブラリも同じ規則: 読み込まず、上書きもしない。"""
    _write_json(user_dir / USER_FILE, library_dict("user", {"export": subsystem_body()}))
    before = (user_dir / USER_FILE).read_bytes()
    with _open_client(tmp_path, user_library_dir=user_dir) as client:
        listing = client.get(API).json()
        assert listing["user_library"]["exists"] is False
        assert listing["user_library"]["write_disabled_reason"] == "user_library_corrupt"
        _error(_register(client), 409, "user_library_corrupt")
    assert (user_dir / USER_FILE).read_bytes() == before


def test_fixed_and_parameterized_routes_do_not_shadow_each_other(
    tmp_path: Path, user_dir: Path
) -> None:
    """``import`` / ``reload`` という名前のライブラリがあっても、固定パスと紛れない。"""
    files = []
    for name in ("import", "reload"):
        path = tmp_path / f"{name}.flwlib.json"
        _write_json(path, library_dict(name, {"e": subsystem_body()}))
        files.append(path)
    with _open_client(tmp_path, user_library_dir=user_dir, library_paths=files) as client:
        # GET /{lib}/{entry}: 固定パスと同じ綴りのライブラリ名も引ける
        assert client.get(f"{API}/import/e").json()["id"] == "e"
        assert client.get(f"{API}/reload/e").json()["id"] == "e"
        # GET /{name}/export は常にライブラリファイルのダウンロード
        for name in ("import", "reload"):
            exported = client.get(f"{API}/{name}/export")
            assert exported.headers["content-disposition"].startswith("attachment;")
            assert exported.json()["name"] == name
        # POST の固定パスはライブラリ名に化けない
        assert client.post(f"{API}/reload").status_code == 200
        assert (
            _import(client, library_dict("lib", {"e": subsystem_body()}), dry_run=True).status_code
            == 200
        )
        # GET /user/entries はエントリ id "entries" の検索 (ユーザーライブラリには無い)
        assert client.get(ENTRIES).status_code == 404
        _register(client, "PID")
        assert client.get(ENTRIES).status_code == 404
        assert client.get(f"{ENTRIES}/pid").status_code == 404
        # DELETE /{name} は 1 区間だけ: 固定パスの綴りでもライブラリ名として扱う
        _error(client.delete(f"{API}/import"), 403, "library_read_only")
        _error(client.delete(f"{API}/user"), 403, "library_read_only")
        # 書き込みメソッドは決められたパスにしか無い
        assert client.post(f"{API}/user/pid", json={}).status_code == 405
        assert client.patch(f"{API}/user", json={}).status_code == 405
        assert client.post(f"{API}/import/entries", json={}).status_code == 405
        assert client.delete(ENTRIES).status_code == 405
        assert set(_libraries(client)) == {"std", "user", "import", "reload"}


# ----------------------------------------------------------------------------
# ユーザーコードを exec しない保証 (ADR-0080 §A4-5、全経路)
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("nested", [False, True], ids=["standalone", "nested"])
def test_no_route_ever_executes_python_function_code(
    tmp_path: Path, user_dir: Path, nested: bool
) -> None:
    sentinel = tmp_path / "sentinel.txt"
    python_block = python_function_body(sentinel_code(sentinel), block_id="leaky")
    body = subsystem_body([python_block]) if nested else python_block
    expected_paths = ["leaky"] if nested else [""]
    shared = library_dict("shared", {"code": copy.deepcopy(body)})

    with _open_client(tmp_path, user_library_dir=user_dir) as client:
        # 登録 (新規)
        r = client.post(ENTRIES, json={"block": body, "display_name": "Leaky"})
        assert r.status_code == 200, r.text
        assert r.json()["entry"]["python_block_paths"] == expected_paths
        # 同名検出 → 別名保存 → 上書き
        _error(
            client.post(ENTRIES, json={"block": body, "display_name": "Leaky"}),
            409,
            "library_entry_name_conflict",
        )
        assert (
            client.post(
                ENTRIES, json={"block": body, "display_name": "Leaky", "save_as_new": True}
            ).status_code
            == 200
        )
        overwrite = {
            "block": body,
            "display_name": "Leaky",
            "overwrite_entry_id": "leaky",
            "expected_revision": 1,
        }
        assert client.post(ENTRIES, json=overwrite).json()["entry"]["revision"] == 2
        # メタデータ編集
        assert (
            client.patch(f"{ENTRIES}/leaky", json={"description": "still inert"}).status_code == 200
        )
        # 一覧・詳細
        assert client.get(API).status_code == 200
        assert client.get(f"{API}/user/leaky").json()["block"]["type"] == body["type"]
        # 書き出し
        exported = client.get(f"{API}/user/export")
        assert exported.status_code == 200
        # 取り込み (dry-run / 本番): 他人のライブラリと、自分の書き出し物の両方。
        # 自分の書き出し物は uid が重なるので本番は拒否されるが、検証までは通る
        for content, imported_status in ((shared, 200), (exported.text, 409)):
            dry = _import(client, content, dry_run=True)
            assert dry.status_code == 200, dry.text
            assert dry.json()["python_entries"][0]["python_block_paths"] == expected_paths
            assert _import(client, content).status_code == imported_status
        # 再読み込み (起動時と同じ読み込み経路)
        assert client.post(f"{API}/reload").status_code == 200
        assert client.get(f"{API}/shared/code").status_code == 200
        assert client.get(f"{API}/shared/export").status_code == 200
        # 削除 (エントリ / 取り込みライブラリ)
        assert client.delete(f"{ENTRIES}/leaky", params={"expected_revision": 2}).status_code == 200
        assert client.delete(f"{API}/shared").status_code == 200

    # サーバを起動し直しても (= 起動時の読み込みでも) 実行されない
    with _open_client(tmp_path, user_library_dir=user_dir) as client:
        assert client.get(API).json()["load_errors"] == []
        assert client.get(f"{API}/user/leaky_2").status_code == 200
    assert not sentinel.exists()


def test_sentinel_code_really_has_a_side_effect(tmp_path: Path) -> None:
    """上の対照: 同じソースは実行時の build では実際にセンチネルを作る。"""
    from flode.blocks.pythonfunc import PythonFunction

    sentinel = tmp_path / "sentinel.txt"
    PythonFunction(code=sentinel_code(sentinel), id="leaky")._build()
    assert sentinel.exists()


# ----------------------------------------------------------------------------
# 読めないファイルがサーバを止めない (巨大整数・不正な UTF-8)
# ----------------------------------------------------------------------------

# Python の int 変換の桁数上限 (既定 4300 桁) を超える整数。``json.loads`` が
# ``JSONDecodeError`` ではない素の ``ValueError`` を出す
HUGE_INT_LIBRARY = (
    '{"schema_version": "libraries.v4", "name": "big", "display_name": "Big", '
    '"entries": [], "n": ' + "9" * 5000 + "}"
)
UNREADABLE_FILES = [
    HUGE_INT_LIBRARY.encode(),
    b'{"schema_version": "libraries.v4", "name": "\xff"}',
]
UNREADABLE_IDS = ["huge-int", "bad-utf8"]


@pytest.mark.parametrize("content", UNREADABLE_FILES, ids=UNREADABLE_IDS)
def test_unreadable_file_is_a_load_error_at_startup_and_reload(
    tmp_path: Path, user_dir: Path, content: bytes
) -> None:
    by_path = tmp_path / "bypath.flwlib.json"
    by_path.write_bytes(content)
    with _open_client(tmp_path, user_library_dir=user_dir, library_paths=[by_path]) as client:
        listing = client.get(API).json()
        assert [lib["name"] for lib in listing["libraries"]] == ["std"]
        assert [Path(e["path"]).name for e in listing["load_errors"]] == ["bypath.flwlib.json"]
        # 起動後に置かれた場合も、再読み込みが落ちない
        user_dir.mkdir()
        (user_dir / "late.flwlib.json").write_bytes(content)
        r = client.post(f"{API}/reload")
        assert r.status_code == 200, r.text
        assert sorted(Path(e["path"]).name for e in r.json()["load_errors"]) == [
            "bypath.flwlib.json",
            "late.flwlib.json",
        ]
        assert _register(client).status_code == 200


@pytest.mark.parametrize("content", UNREADABLE_FILES, ids=UNREADABLE_IDS)
def test_unreadable_user_library_is_reported_as_corrupt(
    tmp_path: Path, user_dir: Path, content: bytes
) -> None:
    user_dir.mkdir()
    (user_dir / USER_FILE).write_bytes(content)
    with _open_client(tmp_path, user_library_dir=user_dir) as client:
        assert client.get(API).json()["user_library"]["write_disabled_reason"] == (
            "user_library_corrupt"
        )
        _error(_register(client), 409, "user_library_corrupt")
    assert (user_dir / USER_FILE).read_bytes() == content


@pytest.mark.parametrize("dry_run", [True, False])
def test_import_of_huge_integer_is_422_not_500(
    client: TestClient, user_dir: Path, dry_run: bool
) -> None:
    args = _error(_import(client, HUGE_INT_LIBRARY, dry_run=dry_run), 422, "library_file_invalid")
    assert args["reason"] == "invalid_json"
    assert not user_dir.exists()


@pytest.mark.parametrize("dry_run", [True, False])
def test_import_of_unencodable_text_is_422_not_500(
    client: TestClient, user_dir: Path, dry_run: bool
) -> None:
    """孤立サロゲートは UTF-8 で保存できない。書き込みの段階で 500 にせず入口で拒否する。"""
    data = library_dict("lib", {"e": python_function_body(PASSTHROUGH_CODE + "# \ud800\n")})
    args = _error(_import(client, data, dry_run=dry_run), 422, "library_file_invalid")
    assert args["reason"] == "invalid_json"
    assert not user_dir.exists()


@pytest.mark.parametrize("where", ["code", "inner-provenance"])
def test_register_of_unencodable_text_is_422_not_500(
    client: TestClient, user_dir: Path, where: str
) -> None:
    if where == "code":
        body = python_function_body(PASSTHROUGH_CODE + "# \ud800\n")
    else:
        # 構築を素通りして正規形に残る文字列 (内部ブロックの由来) に孤立サロゲートがある場合
        inner = gain_block()
        inner["provenance"] = {**PROVENANCE, "library": "lib\ud800"}
        body = subsystem_body([inner])
    # json.dumps は孤立サロゲートを \ud800 と escape する (ブラウザの JSON.stringify と同じ)
    payload = json.dumps({"block": body, "display_name": "X"})
    args = _error(
        client.post(ENTRIES, content=payload, headers={"Content-Type": "application/json"}),
        422,
        "library_entry_invalid",
    )
    assert args["reason"] == "invalid_block"
    assert not user_dir.exists()


def test_request_body_with_huge_integer_is_422(client: TestClient) -> None:
    body = b'{"display_name": "X", "block": ' + b"9" * 5000 + b"}"
    r = client.post(ENTRIES, content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str)


def test_non_ascii_digit_content_length_is_400() -> None:
    """``"²".isdigit()`` は真だが ``int()`` できない。ASCII の数字だけを受け付ける。

    TestClient はヘッダを UTF-8 で符号化し直すので、この値をサーバまで届けられない。
    本文読み取りの dependency に、ASGI サーバが渡す形 (latin-1 のバイト列) で直接渡す。
    """
    import asyncio

    from fastapi import HTTPException
    from starlette.requests import Request

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"{}", "more_body": False}

    scope = {"type": "http", "method": "POST", "headers": [(b"content-length", b"\xb2")]}
    request = Request(scope, receive)
    assert request.headers["content-length"].isdigit()  # 前提: isdigit だけでは通ってしまう
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(libraries_routes._json_object_body(request, None))
    assert excinfo.value.status_code == 400


# ----------------------------------------------------------------------------
# uid は registry 内で一意 (なりすまし防止)
# ----------------------------------------------------------------------------


def test_import_with_uid_of_an_existing_library_is_rejected(tmp_path: Path, user_dir: Path) -> None:
    trusted = tmp_path / "trusted.flwlib.json"
    _write_json(trusted, library_dict("trusted", {"e": subsystem_body()}, uid="uid-trusted"))
    impostor = library_dict("looks_new", {"e": subsystem_body([gain_block()])}, uid="uid-trusted")
    with _open_client(tmp_path, user_library_dir=user_dir, library_paths=[trusted]) as client:
        dry = _import(client, impostor, dry_run=True)
        assert dry.status_code == 200
        assert dry.json()["conflict"] == {"name": "trusted", "reason": "uid_exists"}
        args = _error(_import(client, impostor), 409, "library_name_conflict")
        assert (args["library"], args["reason"], args["conflicts_with"]) == (
            "looks_new",
            "uid_exists",
            "trusted",
        )
        assert set(_libraries(client)) == {"std", "trusted"}
    assert not user_dir.exists()


def test_name_conflict_is_reported_before_uid_conflict(client: TestClient) -> None:
    data = library_dict("lib", {"e": subsystem_body()}, uid="uid-1")
    assert _import(client, data).status_code == 200
    assert _import(client, data, dry_run=True).json()["conflict"] == {
        "name": "lib",
        "reason": "exists",
    }


def test_dry_run_reports_uid_from_file_only(client: TestClient) -> None:
    """dry-run の ``uid`` はファイル由来の値。乱数の付与は本番で書く直前だけ。"""
    without = library_dict("no_uid", {"e": subsystem_body()})
    assert _import(client, without, dry_run=True).json()["library"]["uid"] is None
    with_uid = library_dict("has_uid", {"e": subsystem_body()}, uid="uid-from-file")
    assert _import(client, with_uid, dry_run=True).json()["library"]["uid"] == "uid-from-file"
    assert len(_import(client, without).json()["library"]["uid"]) == 36


# ----------------------------------------------------------------------------
# 読み戻し失敗時の後始末
# ----------------------------------------------------------------------------


def test_import_rolls_back_file_when_read_back_fails(
    client: TestClient, user_dir: Path, mocker: MockerFixture
) -> None:
    from flode.exceptions import LibraryFileError

    mocker.patch.object(library_store, "load_library", side_effect=LibraryFileError("boom"))
    _error(
        _import(client, library_dict("lib", {"e": subsystem_body()})), 500, "library_write_failed"
    )
    mocker.stopall()
    assert _names(user_dir / "imported") == []  # 孤児ファイルを残さない
    assert "lib" not in _libraries(client)
    client.post(f"{API}/reload")
    assert "lib" not in _libraries(client)
    assert _import(client, library_dict("lib", {"e": subsystem_body()})).status_code == 200


def test_user_library_state_follows_disk_when_read_back_fails(
    client: TestClient, user_dir: Path, mocker: MockerFixture
) -> None:
    """書き込みは済んだが読み戻しに失敗した場合、registry と変更検知をディスクに揃える。"""
    from flode.exceptions import LibraryFileError

    _register(client, "First")
    mocker.patch.object(library_store, "load_library", side_effect=LibraryFileError("boom"))
    _error(_register(client, "Second"), 500, "library_write_failed")
    mocker.stopall()
    # ファイルには書かれているので、registry もそれを映す (次の書き込みが 409 にならない)
    assert [e["id"] for e in _read_user_file(user_dir)["entries"]] == ["first", "second"]
    assert [e["id"] for e in _libraries(client)["user"]["entries"]] == ["first", "second"]
    assert _register(client, "Third").status_code == 200


def test_corrupt_user_library_fixed_by_hand_becomes_writable_after_reload(
    tmp_path: Path, user_dir: Path
) -> None:
    user_dir.mkdir()
    (user_dir / USER_FILE).write_text("{ broken", encoding="utf-8")
    with _open_client(tmp_path, user_library_dir=user_dir) as client:
        _error(_register(client), 409, "user_library_corrupt")
        # 手で直す (.bak からの復元に相当)
        _write_json(user_dir / USER_FILE, library_dict("user", {"kept": subsystem_body()}))
        # 再読み込みするまでは、読み込み時点から変わったファイルとして扱う
        _error(_register(client), 409, "library_changed_on_disk")
        reloaded = client.post(f"{API}/reload").json()
        assert reloaded["user_library"] == {
            "name": "user",
            "enabled": True,
            "exists": True,
            "writable": True,
            "write_disabled_reason": "",
        }
        assert not any(USER_FILE in e["path"] for e in reloaded["load_errors"])
        assert _register(client).status_code == 200
    assert [e["id"] for e in _read_user_file(user_dir)["entries"]] == ["kept", "pid"]


# ----------------------------------------------------------------------------
# 表示用文字列の制御文字・書式文字 / 取り込み時の長さ制約
# ----------------------------------------------------------------------------

RLO = "‮"  # RIGHT-TO-LEFT OVERRIDE (書式文字: 表示上の文字順を偽装できる)


@pytest.mark.parametrize(
    ("fields", "field"),
    [
        ({"display_name": f"safe{RLO}gpj.exe"}, "display_name"),
        ({"display_name": "two\nlines"}, "display_name"),
        ({"display_name": "tab\there"}, "display_name"),
        ({"display_name": "nul\x00"}, "display_name"),
        ({"display_name": "ok", "description": f"x{RLO}y"}, "description"),
        ({"display_name": "ok", "description": "bell\x07"}, "description"),
        ({"display_name": "ok", "category_suffix": "a\nb"}, "category_suffix"),
        ({"display_name": "ok", "category_suffix": f"a{RLO}"}, "category_suffix"),
    ],
)
def test_register_rejects_control_and_format_characters(
    client: TestClient, user_dir: Path, fields: dict[str, str], field: str
) -> None:
    args = _error(
        client.post(ENTRIES, json={"block": subsystem_body(), **fields}),
        422,
        "library_entry_invalid",
    )
    assert (args["reason"], args["field"]) == ("invalid_metadata", field)
    assert not user_dir.exists()


def test_description_may_span_lines(client: TestClient) -> None:
    r = _register(client, "PID", description="line 1\nline 2\r\n\tindented")
    assert r.status_code == 200, r.text
    assert r.json()["entry"]["description"] == "line 1\nline 2\r\n\tindented"


def test_patch_rejects_control_and_format_characters(client: TestClient) -> None:
    _register(client, "PID")
    for changes in ({"display_name": f"a{RLO}b"}, {"category_suffix": "a\x1bb"}):
        args = _error(client.patch(f"{ENTRIES}/pid", json=changes), 422, "library_entry_invalid")
        assert args["reason"] == "invalid_metadata"


def _entry_with(**overrides: Any) -> dict[str, Any]:
    return {"id": "e", "display_name": "E", "block": subsystem_body(), **overrides}


@pytest.mark.parametrize(
    ("entry", "field"),
    [
        (_entry_with(display_name=f"a{RLO}b"), "display_name"),
        (_entry_with(display_name="x" * 65), "display_name"),
        (_entry_with(display_name="  "), "display_name"),
        (_entry_with(description="d" * 1001), "description"),
        (_entry_with(description="bell\x07"), "description"),
        (_entry_with(category_suffix="c" * 65), "category_suffix"),
        (_entry_with(category_suffix="a\nb"), "category_suffix"),
        (_entry_with(id="a\nb"), "id"),
        (_entry_with(id="a/b"), "id"),
        (_entry_with(id="i" * 65), "id"),
        (_entry_with(id=""), "id"),
        (_entry_with(display_name_i18n={"ja": f"あ{RLO}"}), "display_name_i18n"),
        (_entry_with(description_i18n={"ja": "d" * 1001}), "description_i18n"),
    ],
)
@pytest.mark.parametrize("dry_run", [True, False])
def test_import_applies_registration_limits_to_every_entry(
    client: TestClient, user_dir: Path, entry: dict[str, Any], field: str, dry_run: bool
) -> None:
    data = library_dict("lib", {"good": subsystem_body()})
    data["entries"].append(entry)
    args = _error(_import(client, data, dry_run=dry_run), 422, "library_entry_invalid")
    assert (args["reason"], args["field"]) == ("invalid_metadata", field)
    assert not user_dir.exists()


@pytest.mark.parametrize(
    ("overrides", "reason", "field"),
    [
        ({"name": f"lib{RLO}"}, "invalid_name", None),
        ({"name": "zero​width"}, "invalid_name", None),
        ({"display_name": f"Lib{RLO}"}, "invalid_metadata", "display_name"),
        ({"display_name": "L" * 65}, "invalid_metadata", "display_name"),
        ({"description": "bell\x07"}, "invalid_metadata", "description"),
        ({"description": "d" * 1001}, "invalid_metadata", "description"),
        ({"display_name_i18n": {"ja": "a\nb"}}, "invalid_metadata", "display_name_i18n"),
    ],
)
def test_import_rejects_unsafe_library_metadata(
    client: TestClient, user_dir: Path, overrides: dict[str, Any], reason: str, field: str | None
) -> None:
    data = {**library_dict("lib", {"e": subsystem_body()}), **overrides}
    args = _error(_import(client, data, dry_run=True), 422, "library_file_invalid")
    assert args["reason"] == reason
    assert args.get("field") == field
    assert not user_dir.exists()


@pytest.mark.parametrize("entry_id", ["export", "entries"])
def test_import_rejects_entry_ids_reserved_by_the_rest_api(
    client: TestClient, user_dir: Path, entry_id: str
) -> None:
    data = library_dict("lib", {"ok": subsystem_body(), entry_id: subsystem_body()})
    args = _error(_import(client, data, dry_run=True), 422, "library_file_invalid")
    assert args["reason"] == "reserved_entry_id"
    assert args["entry_id"] == entry_id
    assert not user_dir.exists()


# ----------------------------------------------------------------------------
# その他のレビュー指摘
# ----------------------------------------------------------------------------


def test_expected_revision_without_overwrite_is_rejected(
    client: TestClient, user_dir: Path
) -> None:
    """``expected_revision`` だけ送るのは上書きのつもりの誤り。黙って新規登録にしない。"""
    args = _error(_register(client, "PID", expected_revision=1), 422, "library_entry_invalid")
    assert (args["reason"], args["field"]) == ("invalid_metadata", "expected_revision")
    assert not user_dir.exists()


def test_register_rejects_duplicate_local_goto_tags(client: TestClient) -> None:
    body = subsystem_body()
    first, second = _goto("A"), {**_goto("A"), "id": "goto_A_again"}
    body["params"]["blocks"].extend([first, second, _from("A")])
    body["params"]["connections"] = [
        _wire("Inport_0", "goto_A"),
        _wire("Inport_0", "goto_A_again"),
        _wire("from_A", "Outport_0"),
    ]
    args = _error(
        client.post(ENTRIES, json={"block": body, "display_name": "Dup"}),
        422,
        "library_entry_invalid",
    )
    assert args["violations"] == [{"path": "goto_A_again", "tag": "A", "reason": "duplicate_goto"}]


def test_entry_id_keeps_combining_marks(client: TestClient) -> None:
    """結合文字 (母音記号など) を落とすと別の語になる。語の一部として残す。"""
    name = "हिंदी"  # デーヴァナーガリー (結合文字 3 つを含む)
    r = _register(client, name)
    assert r.status_code == 200, r.text
    assert r.json()["entry"]["id"] == name


def test_library_error_log_cannot_be_forged_with_newlines(
    client: TestClient, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    from flode.exceptions import LibraryEntryInvalidError

    mocker.patch.object(
        library_store.LibraryStore,
        "register_entry",
        side_effect=LibraryEntryInvalidError("bad\n2026-01-01 [INFO] forged line"),
    )
    with caplog.at_level("WARNING", logger="flode.server"):
        _error(_register(client), 422, "library_entry_invalid")
    messages = [r.getMessage() for r in caplog.records if "Library API" in r.getMessage()]
    assert len(messages) == 1
    assert "\n" not in messages[0]
    assert "forged line" in messages[0]


def test_wrapped_internal_error_type_is_logged(
    client: TestClient, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    """深い検証で包まれた元例外の型をログに残す (内部バグが 422 に化けて見えなくなるのを防ぐ)。"""
    from flode.subsystems import Subsystem

    mocker.patch.object(Subsystem, "_from_dict", side_effect=KeyError("internal\nbug"))
    with caplog.at_level("WARNING", logger="flode.server.library_store"):
        _error(_register(client), 422, "library_entry_invalid")
    messages = [r.getMessage() for r in caplog.records if r.name == "flode.server.library_store"]
    assert any("KeyError" in m and "\n" not in m for m in messages)


def test_lazy_store_is_created_once_under_concurrency(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """lifespan を通らない経路 (テスト用) でも、store は 1 つしか作られない。"""
    import threading
    import time
    from types import SimpleNamespace

    created: list[object] = []

    def slow_rebuild(store: library_store.LibraryStore) -> None:
        # 構築に時間がかかる状況を作り、複数スレッドが同時に「まだ無い」と判断できるようにする
        time.sleep(0.05)
        created.append(store)

    mocker.patch.object(
        library_store.LibraryStore, "_rebuild", autospec=True, side_effect=slow_rebuild
    )
    state = SimpleNamespace(settings=Settings(workspace_root=tmp_path))
    request: Any = SimpleNamespace(app=SimpleNamespace(state=state))
    seen: list[object] = []
    threads = [
        threading.Thread(target=lambda: seen.append(libraries_routes._store(request)))
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads)
    assert len(created) == 1
    assert len(seen) == 8 and all(s is created[0] for s in seen)


# ----------------------------------------------------------------------------
# CSRF guard が新ルートすべてに効いていること (本文の Content-Type)
# ----------------------------------------------------------------------------

# 全書き込みルート (本文を使わない DELETE / reload にも本文を付けて送る)
GUARDED_ROUTES = [
    ("POST", ENTRIES),
    ("PATCH", f"{ENTRIES}/pid"),
    ("DELETE", f"{ENTRIES}/pid?expected_revision=1"),
    ("POST", f"{API}/import"),
    ("DELETE", f"{API}/lib"),
    ("POST", f"{API}/reload"),
]
GUARDED_IDS = ["register", "patch", "delete-entry", "import", "delete-lib", "reload"]
# どのルートにとっても「通れば実際に書き込む」形の本文
_SIMPLE_REQUEST_BODY = json.dumps(
    {
        "block": subsystem_body(),
        "display_name": "Injected",
        "description": "injected",
        "content": json.dumps(library_dict("injected", {"e": subsystem_body()})),
    }
)


@pytest.fixture
def populated_client(client: TestClient, user_dir: Path) -> TestClient:
    """エントリ ``pid`` と取り込みライブラリ ``lib`` がある状態 (削除・編集が実際に効く)。"""
    assert _register(client, "PID").status_code == 200
    assert _import(client, library_dict("lib", {"e": subsystem_body()})).status_code == 200
    return client


def _snapshot(client: TestClient, user_dir: Path) -> tuple[Any, list[str]]:
    listing = client.get(API).json()
    files = sorted(str(p.relative_to(user_dir)) for p in user_dir.rglob("*") if p.is_file())
    return listing, files


@pytest.mark.parametrize(("method", "path"), GUARDED_ROUTES, ids=GUARDED_IDS)
@pytest.mark.parametrize(
    "content_type",
    ["text/plain", "text/plain;charset=UTF-8", "application/x-www-form-urlencoded", None],
    ids=["text-plain", "text-plain-charset", "form", "no-content-type"],
)
def test_body_without_json_content_type_never_reaches_a_write_route(
    populated_client: TestClient, user_dir: Path, method: str, path: str, content_type: str | None
) -> None:
    """ブラウザの simple request (preflight 無しで送れる形) では、どの書き込みルートも動かない。"""
    before = _snapshot(populated_client, user_dir)
    headers = {} if content_type is None else {"Content-Type": content_type}
    r = populated_client.request(method, path, content=_SIMPLE_REQUEST_BODY, headers=headers)
    assert r.status_code == 415, r.text
    assert _snapshot(populated_client, user_dir) == before


@pytest.mark.parametrize(("method", "path"), GUARDED_ROUTES, ids=GUARDED_IDS)
@pytest.mark.parametrize(
    "origin", ["https://evil.example", "null", "http://127.0.0.1.evil.example"]
)
def test_bodyless_cross_origin_request_never_reaches_a_write_route(
    populated_client: TestClient, user_dir: Path, method: str, path: str, origin: str
) -> None:
    before = _snapshot(populated_client, user_dir)
    r = populated_client.request(method, path, headers={"Origin": origin})
    assert r.status_code == 403, r.text
    assert isinstance(r.json()["detail"], str)  # guard の拒否 (ルートの構造化エラーではない)
    assert _snapshot(populated_client, user_dir) == before


@pytest.mark.parametrize(("method", "path"), GUARDED_ROUTES, ids=GUARDED_IDS)
def test_guarded_routes_do_work_with_json_and_same_origin(
    populated_client: TestClient, user_dir: Path, method: str, path: str
) -> None:
    """上 2 件の対照: 同じ要求を JSON + same-origin で送れば実際に処理される。"""
    r = populated_client.request(
        method,
        path,
        content=_SIMPLE_REQUEST_BODY
        if method in ("POST", "PATCH") and "reload" not in path
        else None,
        headers={"Content-Type": "application/json", "Origin": BASE_URL},
    )
    # register / import は本文に余分なフィールドがあるので 422 (ルートまで届いた証拠)
    assert r.status_code in (200, 422), r.text
    assert not (r.status_code == 422 and "Content-Type" in r.text)


# ----------------------------------------------------------------------------
# 403 (書き込み不可) は 422 (不正な要求) より先
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("DELETE", f"{ENTRIES}/pid", None),  # expected_revision 欠落
        ("DELETE", f"{ENTRIES}/pid?expected_revision=abc", None),
        ("DELETE", f"{ENTRIES}/pid?expected_revision=0", None),
        ("POST", ENTRIES, b"not json"),
        ("POST", ENTRIES, b"{}"),
        ("PATCH", f"{ENTRIES}/pid", b'{"unknown": 1}'),
        ("POST", f"{API}/import", b"[]"),
    ],
    ids=["no-query", "bad-query", "zero-revision", "not-json", "empty", "unknown-field", "array"],
)
@pytest.mark.parametrize("write_allowed", [False, True], ids=["forbidden", "disabled"])
def test_permission_is_checked_before_request_validation(
    tmp_path: Path, method: str, path: str, body: bytes | None, write_allowed: bool
) -> None:
    """書けないサーバは、要求の形を調べる前に 403 を返す (要求の中身を読まない)。"""
    code = "user_library_disabled" if write_allowed else "library_write_forbidden"
    headers = {"Content-Type": "application/json"} if body is not None else {}
    with _open_client(tmp_path, user_library_dir=None, write_allowed=write_allowed) as client:
        _error(client.request(method, path, content=body, headers=headers), 403, code)


# ----------------------------------------------------------------------------
# ZWJ / ZWNJ (位置を限って許可) と行区切り文字
# ----------------------------------------------------------------------------

ZWJ = "‍"
ZWNJ = "‌"
FAMILY = f"\U0001f468{ZWJ}\U0001f469{ZWJ}\U0001f467"  # 絵文字の ZWJ 列
PERSIAN = f"می{ZWNJ}خواهم"  # ZWNJ を含むペルシア語の単語


@pytest.mark.parametrize("name", [FAMILY, f"{FAMILY} plant", PERSIAN, f"a{ZWJ}b{ZWNJ}c"])
def test_joiners_between_characters_are_allowed_in_display_strings(
    client: TestClient, name: str
) -> None:
    r = _register(client, name, description=f"about {name}", category_suffix=name)
    assert r.status_code == 200, r.text
    entry = r.json()["entry"]
    assert (entry["display_name"], entry["category_suffix"]) == (name, name)
    assert ZWJ not in entry["id"] and ZWNJ not in entry["id"]
    assert client.patch(f"{ENTRIES}/{entry['id']}", json={"description": name}).status_code == 200


@pytest.mark.parametrize("joiner", [ZWJ, ZWNJ], ids=["zwj", "zwnj"])
@pytest.mark.parametrize(
    "template",
    ["{j}PID", "PID{j}", "P{j}{j}ID", "P {j}ID", "P{j} ID", "{j}"],
    ids=["leading", "trailing", "consecutive", "after-space", "before-space", "alone"],
)
def test_misplaced_joiners_are_rejected(
    client: TestClient, user_dir: Path, joiner: str, template: str
) -> None:
    name = template.format(j=joiner)
    for fields in ({"display_name": name}, {"display_name": "ok", "category_suffix": name}):
        args = _error(
            client.post(ENTRIES, json={"block": subsystem_body(), **fields}),
            422,
            "library_entry_invalid",
        )
        assert args["reason"] == "invalid_metadata"
    assert not user_dir.exists()


def test_description_rejects_joiner_next_to_line_break(client: TestClient) -> None:
    args = _error(
        _register(client, "PID", description=f"line\n{ZWJ}next"), 422, "library_entry_invalid"
    )
    assert args["field"] == "description"


@pytest.mark.parametrize("variant", [f"P{ZWJ}ID", f"PI{ZWNJ}D", f"p{ZWJ}i{ZWNJ}d"])
def test_names_differing_only_by_joiners_are_the_same_name(
    client: TestClient, variant: str
) -> None:
    """見た目が同じ名前で既存エントリを偽装できないよう、同名判定は ZWJ / ZWNJ を無視する。"""
    _register(client, "PID")
    args = _error(_register(client, variant), 409, "library_entry_name_conflict")
    assert args["entry_id"] == "pid"
    _register(client, "Other")
    _error(
        client.patch(f"{ENTRIES}/other", json={"display_name": variant}),
        409,
        "library_entry_name_conflict",
    )


@pytest.mark.parametrize("separator", [" ", " "], ids=["line-separator", "paragraph-separator"])
@pytest.mark.parametrize("field", ["display_name", "description", "category_suffix"])
def test_unicode_line_separators_are_rejected(
    client: TestClient, user_dir: Path, separator: str, field: str
) -> None:
    fields = {"display_name": "ok", field: f"a{separator}b"}
    args = _error(
        client.post(ENTRIES, json={"block": subsystem_body(), **fields}),
        422,
        "library_entry_invalid",
    )
    assert args["field"] == field
    assert not user_dir.exists()


@pytest.mark.parametrize(
    "text",
    ["a​b", "a⁠b", "a﻿b", "a‪b", "a⁦b", "a‎b", "a؜b", "a\U000e0041b"],
    ids=["zwsp", "word-joiner", "bom", "lre", "lri", "lrm", "alm", "tag"],
)
def test_other_format_characters_stay_rejected(client: TestClient, text: str) -> None:
    _error(_register(client, text), 422, "library_entry_invalid")


def test_identifiers_never_accept_joiners(client: TestClient, user_dir: Path) -> None:
    """REST のパスに乗る識別子 (エントリ id / ライブラリ名) では ZWJ / ZWNJ も不可。"""
    with_id = library_dict("lib", {"good": subsystem_body()})
    with_id["entries"].append({"id": f"a{ZWJ}b", "display_name": "E", "block": subsystem_body()})
    args = _error(_import(client, with_id, dry_run=True), 422, "library_entry_invalid")
    assert args["field"] == "id"
    with_name = library_dict(f"li{ZWNJ}b", {"e": subsystem_body()})
    args = _error(_import(client, with_name, dry_run=True), 422, "library_file_invalid")
    assert args["reason"] == "invalid_name"
    # 表示名なら取り込みでも通る
    shown = library_dict("lib", {"e": subsystem_body()}, display_name=FAMILY)
    shown["entries"][0]["display_name"] = PERSIAN
    assert _import(client, shown, dry_run=True).status_code == 200
    assert not user_dir.exists()
