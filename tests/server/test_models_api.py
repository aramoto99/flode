"""ADR-0011 §(1): モデル CRUD REST エンドポイントのテスト。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from pyflw import Simulator
from pyflw.blocks import Constant, Gain, Scope
from pyflw.server import create_app


@pytest.fixture
def model_dir(tmp_path):
    return tmp_path / "models"


@pytest.fixture
def client(model_dir):
    app = create_app(model_dir)
    with TestClient(app) as c:
        yield c


def _seed_model(model_dir, name: str = "demo") -> str:
    """簡単なモデルファイルを model_dir に作成して model_id を返す。"""
    model_dir.mkdir(parents=True, exist_ok=True)
    sim = Simulator(t_end=0.05, dt=0.01)
    sim.add(Constant(value=2.0, id="src"))
    sim.add(Gain(k=3.0, id="g"))
    sim.add(Scope(n_inputs=1, id="scope"))
    sim.connect("src", "g")
    sim.connect("g", "scope")
    path = model_dir / f"{name}.flw.json"
    sim.save(path)
    return name


class TestListModels:
    def test_empty_dir(self, client):
        response = client.get("/api/v1/models")
        assert response.status_code == 200
        assert response.json() == {"models": []}

    def test_lists_existing_models(self, client, model_dir):
        _seed_model(model_dir, "alpha")
        _seed_model(model_dir, "beta")
        response = client.get("/api/v1/models")
        assert response.status_code == 200
        assert response.json() == {"models": ["alpha", "beta"]}


class TestGetModel:
    def test_returns_model_json(self, client, model_dir):
        _seed_model(model_dir, "demo")
        response = client.get("/api/v1/models/demo")
        assert response.status_code == 200
        data = response.json()
        assert data["schema_version"] == "0.5"
        assert any(b["id"] == "g" for b in data["blocks"])

    def test_404_when_missing(self, client):
        response = client.get("/api/v1/models/missing")
        assert response.status_code == 404

    def test_400_on_invalid_id(self, client):
        # ドット禁止 (ADR-0004 ID 規則)
        response = client.get("/api/v1/models/has.dot")
        assert response.status_code == 400


class TestCreateModel:
    def test_creates_with_metadata_name(self, client, model_dir):
        payload = {
            "schema_version": "0.4",
            "metadata": {"name": "fresh"},
            "simulator": {
                "t_end": 0.05,
                "dt": 0.01,
                "solver": "RK45",
                "rtol": 1e-6,
                "atol": 1e-9,
                "dt_base": None,
            },
            "blocks": [],
            "connections": [],
        }
        response = client.post("/api/v1/models", json=payload)
        assert response.status_code == 200
        assert response.json()["model_id"] == "fresh"
        assert (model_dir / "fresh.flw.json").exists()

    def test_collision_falls_back_to_suffix(self, client, model_dir):
        _seed_model(model_dir, "fresh")
        response = client.post(
            "/api/v1/models",
            json={"metadata": {"name": "fresh"}, "blocks": [], "connections": []},
        )
        assert response.json()["model_id"] == "fresh_1"


class TestUpdateModel:
    def test_overwrites_existing(self, client, model_dir):
        _seed_model(model_dir, "demo")
        new_payload = {"hello": "world"}
        response = client.put("/api/v1/models/demo", json=new_payload)
        assert response.status_code == 200
        data = json.loads((model_dir / "demo.flw.json").read_text(encoding="utf-8"))
        assert data == {"hello": "world"}

    def test_404_when_missing_strict_update(self, client):
        """PUT は upsert ではなく厳密 update (code-reviewer SHOULD 修正)。"""
        response = client.put("/api/v1/models/never-existed", json={"x": 1})
        assert response.status_code == 404

    def test_layout_round_trips_through_put_get(self, client, model_dir):
        """ADR-0020: ``layout`` フィールドが PUT → GET で round-trip する。

        サーバは raw JSON passthrough なので追加実装ゼロで通る (ADR-0020 §Decision (4))。
        本テストは regression 防止用。
        """
        _seed_model(model_dir, "demo")
        payload_with_layout = {
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
                    "type": "pyflw.blocks.sources.Constant",
                    "params": {"value": 1.0},
                }
            ],
            "connections": [],
            "layout": {"src": {"x": 100.0, "y": 60.0}},
        }
        put_resp = client.put("/api/v1/models/demo", json=payload_with_layout)
        assert put_resp.status_code == 200
        get_resp = client.get("/api/v1/models/demo")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["layout"] == {"src": {"x": 100.0, "y": 60.0}}


class TestModelIdValidation:
    def test_hyphen_allowed(self, client, model_dir):
        """``my-model`` のようなハイフン入り model_id を許容 (code-reviewer MUST 修正)。"""
        model_dir.mkdir(parents=True, exist_ok=True)
        # 直接ファイルを置いてから GET 経路をテスト
        from pyflw import Simulator
        from pyflw.blocks import Constant

        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(Constant(value=1.0, id="x"))
        sim.save(model_dir / "my-model.flw.json")
        response = client.get("/api/v1/models/my-model")
        assert response.status_code == 200

    def test_invalid_chars_rejected(self, client):
        """不正な文字を含む model_id はサーバ側で 400 (validate_model_id 拒否)。

        ``..`` や ``/`` を含む path は Starlette のパス正規化で 404 になる経路と、
        validator で 400 になる経路の両方がありうるが、いずれにせよファイル
        traversal は成立しない。``%`` を含む生 ID で 400 が出ることを確認。
        """
        response = client.get("/api/v1/models/has%23hash")
        # %23 = "#" → ID validator で拒否されて 400
        assert response.status_code == 400

    def test_unicode_rejected(self, client):
        """非 ASCII 文字も拒否される (validate_model_id ASCII-only)。"""
        response = client.get("/api/v1/models/モデル")
        assert response.status_code == 400


class TestDeleteModel:
    def test_removes_file(self, client, model_dir):
        _seed_model(model_dir, "demo")
        response = client.delete("/api/v1/models/demo")
        assert response.status_code == 200
        assert not (model_dir / "demo.flw.json").exists()

    def test_404_when_missing(self, client):
        response = client.delete("/api/v1/models/missing")
        assert response.status_code == 404
