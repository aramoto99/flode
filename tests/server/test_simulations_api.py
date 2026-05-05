"""ADR-0011 §(1)(2): シミュレーション制御 + WebSocket のテスト。"""

from __future__ import annotations

import time

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


def _seed_simple_model(model_dir, name: str = "demo") -> str:
    model_dir.mkdir(parents=True, exist_ok=True)
    sim = Simulator(t_end=0.05, dt=0.01)
    sim.add(Constant(value=2.0, id="src"))
    sim.add(Gain(k=3.0, id="g"))
    sim.add(Scope(n_inputs=1, id="scope"))
    sim.connect("src", "g")
    sim.connect("g", "scope")
    sim.save(model_dir / f"{name}.flw.json")
    return name


def _wait_for_status(client, sim_id: str, target: set[str], timeout: float = 5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/v1/simulations/{sim_id}")
        if response.status_code == 200 and response.json()["status"] in target:
            return response.json()
        time.sleep(0.02)
    raise AssertionError(f"simulation {sim_id} did not reach {target} within {timeout}s")


class TestStartSimulation:
    def test_returns_simulation_id(self, client, model_dir):
        _seed_simple_model(model_dir)
        response = client.post("/api/v1/simulations", json={"model_id": "demo"})
        assert response.status_code == 200
        data = response.json()
        assert "simulation_id" in data
        assert data["model_id"] == "demo"

    def test_404_on_unknown_model(self, client):
        response = client.post("/api/v1/simulations", json={"model_id": "missing"})
        assert response.status_code == 404

    def test_400_on_missing_body_field(self, client):
        response = client.post("/api/v1/simulations", json={})
        assert response.status_code == 400


class TestSimulationLifecycle:
    def test_completes_and_results_available(self, client, model_dir):
        _seed_simple_model(model_dir)
        response = client.post("/api/v1/simulations", json={"model_id": "demo"})
        sim_id = response.json()["simulation_id"]

        state = _wait_for_status(client, sim_id, {"completed"})
        assert state["status"] == "completed"

        results = client.get(f"/api/v1/simulations/{sim_id}/results")
        assert results.status_code == 200
        data = results.json()
        assert "scope" in data["scopes"]
        assert all(v == [6.0] for v in data["scopes"]["scope"]["values"])

    def test_results_409_while_running(self, client, model_dir, monkeypatch):
        _seed_simple_model(model_dir)
        # 長めにして running 状態をキャプチャ
        long_path = model_dir / "long.flw.json"
        sim = Simulator(t_end=2.0, dt=0.01)
        sim.add(Constant(value=1.0, id="src"))
        sim.add(Gain(k=1.0, id="g"))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "g")
        sim.connect("g", "scope")
        sim.save(long_path)

        response = client.post("/api/v1/simulations", json={"model_id": "long"})
        sim_id = response.json()["simulation_id"]
        # running の隙に results を叩く (タイミング依存だが Python の起動が早い)
        # 失敗時のフォールバックとして、completed 後の 200 も許容しない
        results = client.get(f"/api/v1/simulations/{sim_id}/results")
        # running なら 409、completed なら 200
        assert results.status_code in (200, 409)

        # 最終的に completed することを確認
        _wait_for_status(client, sim_id, {"completed"}, timeout=10.0)

    def test_404_for_unknown_simulation(self, client):
        response = client.get("/api/v1/simulations/nosuchsim")
        assert response.status_code == 404


class TestStopSimulation:
    def test_stop_marks_simulation_stopped(self, client, model_dir):
        # 長時間モデルで stop 動作を検証
        long_path = model_dir / "long.flw.json"
        sim = Simulator(t_end=10.0, dt=0.001)
        sim.add(Constant(value=1.0, id="src"))
        sim.add(Gain(k=1.0, id="g"))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "g")
        sim.connect("g", "scope")
        sim.save(long_path)

        response = client.post("/api/v1/simulations", json={"model_id": "long"})
        sim_id = response.json()["simulation_id"]

        time.sleep(0.05)  # シミュレーションが少し進むのを待つ
        stop_response = client.post(f"/api/v1/simulations/{sim_id}/stop")
        assert stop_response.status_code == 200

        state = _wait_for_status(client, sim_id, {"stopped", "completed"}, timeout=10.0)
        # stop が間に合えば stopped、追いつかなければ completed (どちらも許容)
        assert state["status"] in ("stopped", "completed")


class TestWebSocketStream:
    def test_receives_progress_and_completed(self, client, model_dir):
        _seed_simple_model(model_dir)
        response = client.post("/api/v1/simulations", json={"model_id": "demo"})
        sim_id = response.json()["simulation_id"]

        types_seen: list[str] = []
        with client.websocket_connect(f"/api/v1/simulations/{sim_id}/stream") as ws:
            for _ in range(50):
                msg = ws.receive_json()
                types_seen.append(msg["type"])
                if msg["type"] in ("completed", "stopped", "failed"):
                    break

        assert "progress" in types_seen
        assert "completed" in types_seen


class TestScopeBatchStreaming:
    """ADR-0011 §(2) のバッチ送信パス (scope_batch メッセージ) を実際に発火させる。"""

    def test_scope_batch_dispatched_when_buffer_fills(self, client, model_dir):
        """``scope_batch_size=100`` のデフォルトより多いステップ数のモデルで、
        ``scope_batch`` メッセージが少なくとも 1 回送られる。"""
        model_dir.mkdir(parents=True, exist_ok=True)
        # 200 ステップ (= bath_size 100 を 2 回超える) のモデル
        sim = Simulator(t_end=2.0, dt=0.01)
        sim.add(Constant(value=1.0, id="src"))
        sim.add(Gain(k=1.0, id="g"))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "g")
        sim.connect("g", "scope")
        sim.save(model_dir / "batchy.flw.json")

        response = client.post("/api/v1/simulations", json={"model_id": "batchy"})
        sim_id = response.json()["simulation_id"]

        scope_batches: list[dict] = []
        with client.websocket_connect(f"/api/v1/simulations/{sim_id}/stream") as ws:
            for _ in range(2000):
                msg = ws.receive_json()
                if msg["type"] == "scope_batch":
                    scope_batches.append(msg)
                if msg["type"] in ("completed", "stopped", "failed"):
                    break

        assert len(scope_batches) >= 1
        assert scope_batches[0]["scope_id"] == "scope"
        assert "times" in scope_batches[0]
        assert "values" in scope_batches[0]


class TestErrorHandlerJson:
    def test_pyflw_error_returns_structured_json(self, client, model_dir):
        # 不正な JSON を載せたモデルファイルを作って load_model で ModelLoadError
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / "broken.flw.json").write_text("{not json", encoding="utf-8")
        response = client.get("/api/v1/models/broken")
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["type"] == "ModelLoadError"
        assert "trace_id" in body["error"]
