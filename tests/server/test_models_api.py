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


class TestGetModelMigration:
    """ADR-0039 v0.14.1: GET endpoint が古い schema を最新に migrate して返す。"""

    def test_old_schema_07_is_migrated_to_current_on_get(self, client, model_dir):
        """schema 0.7 形式のファイルを直に置いて GET し、最新 schema が返ることを確認。

        v2.0 で派生 property 化された Subsystem の n_inputs / n_outputs フィールドが
        migration 時に除去される (= ADR-0039 §Decision §(3)、`_builtin_migrate_0_7_to_0_8`)。
        """
        from pyflw.core.persistence import CURRENT_SCHEMA_VERSION

        model_dir.mkdir(parents=True, exist_ok=True)
        # 古い 0.7 形式のモデル (= Subsystem に n_inputs / n_outputs フィールド)
        old = {
            "schema_version": "0.7",
            "metadata": {"name": "old", "tool": "pytest"},
            "simulator": {"t_end": 1.0, "dt": 0.01, "solver": "RK45"},
            "blocks": [
                {
                    "id": "sub",
                    "type": "pyflw.subsystems.subsystem.Subsystem",
                    "params": {
                        "n_inputs": 1,
                        "n_outputs": 1,
                        "blocks": [
                            {
                                "id": "in0",
                                "type": "pyflw.subsystems.ports.Inport",
                                "params": {"port_idx": 0},
                            },
                            {
                                "id": "out0",
                                "type": "pyflw.subsystems.ports.Outport",
                                "params": {"port_idx": 0},
                            },
                        ],
                        "connections": [],
                    },
                },
            ],
            "connections": [],
        }
        (model_dir / "old.flw.json").write_text(json.dumps(old), encoding="utf-8")

        response = client.get("/api/v1/models/old")
        assert response.status_code == 200
        body = response.json()
        # GET レスポンスは最新 schema (= 0.8) になっている
        assert body["schema_version"] == CURRENT_SCHEMA_VERSION
        # Subsystem の派生フィールドは除去されている
        sub_params = body["blocks"][0]["params"]
        assert "n_inputs" not in sub_params
        assert "n_outputs" not in sub_params
        # 内部 blocks は保持
        assert len(sub_params["blocks"]) == 2

    def test_old_schema_06_is_migrated_to_current_on_get(self, client, model_dir):
        """schema 0.6 のシンプルなモデル (Subsystem なし) も GET で 0.8 化されること。

        0.6 → 0.7 / 0.7 → 0.8 の 2 段 migration が GET 経路で確実に走ることを
        担保する (code-reviewer SHOULD-3 対応)。
        """
        from pyflw.core.persistence import CURRENT_SCHEMA_VERSION

        model_dir.mkdir(parents=True, exist_ok=True)
        old = {
            "schema_version": "0.6",
            "metadata": {"name": "v06", "tool": "pytest"},
            "simulator": {"t_end": 1.0, "dt": 0.01, "solver": "RK45"},
            "blocks": [
                {"id": "src", "type": "pyflw.blocks.sources.Constant", "params": {"value": 1.0}}
            ],
            "connections": [],
        }
        (model_dir / "v06.flw.json").write_text(json.dumps(old), encoding="utf-8")

        response = client.get("/api/v1/models/v06")
        assert response.status_code == 200
        assert response.json()["schema_version"] == CURRENT_SCHEMA_VERSION

    def test_unsupported_schema_returns_400(self, client, model_dir):
        """未対応 schema は 400 で返る (= グローバルハンドラ任せにしない、MUST-1)。"""
        model_dir.mkdir(parents=True, exist_ok=True)
        bad = {
            "schema_version": "999.0",
            "simulator": {"t_end": 1, "dt": 0.01, "solver": "RK45"},
            "blocks": [],
            "connections": [],
        }
        (model_dir / "bad.flw.json").write_text(json.dumps(bad), encoding="utf-8")

        response = client.get("/api/v1/models/bad")
        assert response.status_code == 400


class TestGetModel:
    def test_returns_model_json(self, client, model_dir):
        from pyflw.core.persistence import CURRENT_SCHEMA_VERSION

        _seed_model(model_dir, "demo")
        response = client.get("/api/v1/models/demo")
        assert response.status_code == 200
        data = response.json()
        assert data["schema_version"] == CURRENT_SCHEMA_VERSION
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
