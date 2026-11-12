"""REST `/api/v1/libraries` エンドポイントのテスト (ADR-0029)。"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flode.libraries import CURRENT_LIBRARY_SCHEMA_VERSION
from flode.server.app import create_app
from flode.server.settings import Settings


@pytest.fixture
def client() -> TestClient:
    tmp = tempfile.mkdtemp(prefix="flode_test_workspace_")
    settings = Settings(workspace_root=Path(tmp))
    app = create_app(settings=settings)
    return TestClient(app)


def test_get_libraries_schema_version_is_current(client: TestClient) -> None:
    """``GET /api/v1/libraries`` の schema_version はローダの現行版に一致する (ADR-0080 F-5)。"""
    with client:
        r = client.get("/api/v1/libraries")
    assert r.status_code == 200
    data = r.json()
    assert data["schema_version"] == CURRENT_LIBRARY_SCHEMA_VERSION == "libraries.v4"
    assert "en" in data["supported_locales"]
    assert "ja" in data["supported_locales"]
    assert isinstance(data["load_errors"], list)
    # 組み込み std がデフォルトで含まれる
    names = [lib["name"] for lib in data["libraries"]]
    assert "std" in names


def test_get_libraries_omits_block_body(client: TestClient) -> None:
    """list endpoint は本体 (``block``) を含めない (= ペイロード削減)。"""
    with client:
        r = client.get("/api/v1/libraries")
    data = r.json()
    for lib in data["libraries"]:
        for entry in lib["entries"]:
            assert "block" not in entry
            assert "subsystem" not in entry
            assert "id" in entry
            assert "display_name" in entry


def test_get_libraries_additive_metadata_for_std(client: TestClient) -> None:
    """ADR-0080 §A1-6: エントリ / ライブラリ metadata の additive フィールド。"""
    with client:
        r = client.get("/api/v1/libraries")
    std = next(lib for lib in r.json()["libraries"] if lib["name"] == "std")
    assert std["uid"] is None  # 同梱 std は uid を持たない
    for entry in std["entries"]:
        assert entry["kind"] == "subsystem"
        assert entry["revision"] == 1
        assert entry["updated_at"] is None
        assert entry["contains_python"] is False
        assert entry["python_block_paths"] == []


def test_get_library_entry_returns_block_body(client: TestClient) -> None:
    """``GET /api/v1/libraries/{lib}/{entry}`` が本体を ``block`` で返す。

    返された本体は ``Subsystem._from_dict()`` で再構築可能。
    """
    from flode.subsystems import Subsystem

    with client:
        r = client.get("/api/v1/libraries/std/pid_controller")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == "pid_controller"
    assert "subsystem" not in data
    assert data["revision"] == 1
    assert data["library_uid"] is None
    sub_dict = data["block"]
    assert sub_dict["type"] == "flode.subsystems.subsystem.Subsystem"
    assert isinstance(sub_dict["params"], dict)
    # 再構築 = byte-identical 保証 (= round-trip 可)
    rebuilt = Subsystem._from_dict(**sub_dict["params"])
    assert rebuilt.n_inputs == 1
    assert rebuilt.n_outputs == 1


PYTHON_CODE = "@block\ndef passthrough(t: float, u: float) -> float:\n    return u\n"
USER_LIBRARY_UID = "8c1e2f0a-0000-4000-8000-000000000001"


@pytest.fixture
def python_library_client(tmp_path: Path) -> TestClient:
    """PythonFunction 単体 / 入れ子の 2 エントリを持つ v4 ライブラリを読み込んだ client。"""
    python_block = {
        "id": "pf",
        "type": "flode.blocks.pythonfunc.PythonFunction",
        "params": {"code": PYTHON_CODE, "user_params": {}},
    }
    nested = {
        "id": None,
        "type": "flode.subsystems.subsystem.Subsystem",
        "params": {
            "blocks": [
                {"id": "in", "type": "flode.subsystems.ports.Inport", "params": {"port_idx": 0}},
                python_block,
                {"id": "out", "type": "flode.subsystems.ports.Outport", "params": {"port_idx": 0}},
            ],
            "connections": [
                {"src": "in", "src_idx": 0, "dst": "pf", "dst_idx": 0},
                {"src": "pf", "src_idx": 0, "dst": "out", "dst_idx": 0},
            ],
        },
    }
    library = {
        "schema_version": CURRENT_LIBRARY_SCHEMA_VERSION,
        "name": "mine",
        "uid": USER_LIBRARY_UID,
        "display_name": "Mine",
        "entries": [
            {
                "id": "code",
                "display_name": "Code",
                "revision": 4,
                "updated_at": "2026-11-12T10:00:00Z",
                "block": python_block,
            },
            {"id": "wrapped", "display_name": "Wrapped", "block": nested},
        ],
    }
    lib_path = tmp_path / "mine.flwlib.json"
    lib_path.write_text(json.dumps(library), encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = Settings(workspace_root=workspace, library_paths=[lib_path])
    return TestClient(create_app(settings=settings))


def test_get_libraries_additive_metadata_for_python_entries(
    python_library_client: TestClient,
) -> None:
    with python_library_client as client:
        r = client.get("/api/v1/libraries")
    data = r.json()
    assert data["load_errors"] == []
    mine = next(lib for lib in data["libraries"] if lib["name"] == "mine")
    assert mine["uid"] == USER_LIBRARY_UID
    entries = {e["id"]: e for e in mine["entries"]}
    assert entries["code"]["kind"] == "python_function"
    assert entries["code"]["revision"] == 4
    assert entries["code"]["updated_at"] == "2026-11-12T10:00:00Z"
    assert entries["code"]["contains_python"] is True
    assert entries["code"]["python_block_paths"] == [""]
    assert entries["wrapped"]["kind"] == "subsystem"
    assert entries["wrapped"]["revision"] == 1
    assert entries["wrapped"]["updated_at"] is None
    assert entries["wrapped"]["contains_python"] is True
    assert entries["wrapped"]["python_block_paths"] == ["pf"]


def test_get_library_entry_detail_carries_revision_and_library_uid(
    python_library_client: TestClient,
) -> None:
    """drop・差し替えの由来は詳細レスポンスから作る (ADR-0080 §A5)。"""
    with python_library_client as client:
        r = client.get("/api/v1/libraries/mine/code")
    assert r.status_code == 200
    data = r.json()
    assert data["revision"] == 4
    assert data["library_uid"] == USER_LIBRARY_UID
    assert data["kind"] == "python_function"
    assert data["block"]["type"] == "flode.blocks.pythonfunc.PythonFunction"
    assert data["block"]["params"]["code"] == PYTHON_CODE


def test_get_library_entry_404(client: TestClient) -> None:
    """未登録 library / entry id は 404。"""
    with client:
        r1 = client.get("/api/v1/libraries/nope/pid_controller")
        r2 = client.get("/api/v1/libraries/std/nope")
    assert r1.status_code == 404
    assert r2.status_code == 404


def test_get_libraries_does_not_affect_blocks_endpoint(client: TestClient) -> None:
    """libraries 追加で /blocks の schema_version (= blocks.v2) が変わらない。"""
    with client:
        r = client.get("/api/v1/blocks")
    assert r.status_code == 200
    assert r.json()["schema_version"] == "blocks.v2"
