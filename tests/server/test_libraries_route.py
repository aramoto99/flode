"""REST `/api/v1/libraries` エンドポイントのテスト (ADR-0029)。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pyflw.server.app import create_app
from pyflw.server.settings import Settings


@pytest.fixture
def client() -> TestClient:
    tmp = tempfile.mkdtemp(prefix="pyflw_test_workspace_")
    settings = Settings(workspace_root=Path(tmp))
    app = create_app(settings=settings)
    return TestClient(app)


def test_get_libraries_schema_v1(client: TestClient) -> None:
    """``GET /api/v1/libraries`` が schema_version + supported_locales + load_errors を返す。"""
    with client:
        r = client.get("/api/v1/libraries")
    assert r.status_code == 200
    data = r.json()
    assert data["schema_version"] == "libraries.v1"
    assert "en" in data["supported_locales"]
    assert "ja" in data["supported_locales"]
    assert isinstance(data["load_errors"], list)
    # 組み込み std がデフォルトで含まれる
    names = [lib["name"] for lib in data["libraries"]]
    assert "std" in names


def test_get_libraries_omits_subsystem_body(client: TestClient) -> None:
    """list endpoint は subsystem body を含めない (= ペイロード削減)。"""
    with client:
        r = client.get("/api/v1/libraries")
    data = r.json()
    for lib in data["libraries"]:
        for entry in lib["entries"]:
            assert "subsystem" not in entry
            assert "id" in entry
            assert "display_name" in entry


def test_get_library_entry_returns_subsystem_body(client: TestClient) -> None:
    """``GET /api/v1/libraries/{lib}/{entry}`` が subsystem body を含める。

    返された subsystem body は ``Subsystem._from_dict()`` で再構築可能。
    """
    from pyflw.subsystems import Subsystem

    with client:
        r = client.get("/api/v1/libraries/std/pid_controller")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == "pid_controller"
    sub_dict = data["subsystem"]
    assert sub_dict["type"] == "pyflw.subsystems.subsystem.Subsystem"
    assert isinstance(sub_dict["params"], dict)
    # 再構築 = byte-identical 保証 (= round-trip 可)
    rebuilt = Subsystem._from_dict(**sub_dict["params"])
    assert rebuilt.n_inputs == 1
    assert rebuilt.n_outputs == 1


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
