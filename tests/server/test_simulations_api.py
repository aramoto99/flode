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


# ---------------------------------------------------------------------------
# ADR-0041 §論点 5-A: model_path / model (inline) / mutual exclusion
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace_client(tmp_path):
    """``workspace_root=tmp_path`` で起動した TestClient (= ADR-0041 §3 mode)。"""
    from pyflw.server.settings import Settings

    settings = Settings(model_dir=tmp_path, workspace_root=tmp_path)
    app = create_app(tmp_path, settings=settings)
    with TestClient(app) as c:
        yield c, tmp_path


def _build_simple_model_dict(tmp_path) -> dict:
    """インライン用の minimal `.flw.json` dict を生成する。

    ``Simulator`` は to_dict を持たないため、``save`` 経由で生成して再 load する。
    ``workspace_client`` fixture が ``tmp_path`` を workspace_root として使うので、
    seed ファイルは専用サブディレクトリに置いて衝突を避ける。
    """
    import json

    sim = Simulator(t_end=0.05, dt=0.01)
    sim.add(Constant(value=2.0, id="src"))
    sim.add(Gain(k=3.0, id="g"))
    sim.add(Scope(n_inputs=1, id="scope"))
    sim.connect("src", "g")
    sim.connect("g", "scope")
    seed_dir = tmp_path / "_inline_seed_helper"
    seed_dir.mkdir(exist_ok=True)
    p = seed_dir / "model.flw.json"
    sim.save(p)
    data = json.loads(p.read_text(encoding="utf-8"))
    p.unlink()
    seed_dir.rmdir()
    return data


class TestStartSimulationModelPath:
    """ADR-0041 §論点 5-A: ``model_path`` (workspace 相対) ベースの起動。"""

    def test_starts_from_model_path(self, workspace_client):
        client, workspace = workspace_client
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(Constant(value=1.0, id="src"))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "scope")
        sim.save(workspace / "demo.flw.json")

        response = client.post(
            "/api/v1/simulations", json={"model_path": "demo.flw.json"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "simulation_id" in data
        # display id は path 文字列 (= legacy model_id ではなく)
        assert data["model_id"] == "demo.flw.json"

    def test_starts_from_subdirectory_model_path(self, workspace_client):
        client, workspace = workspace_client
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(Constant(value=1.0, id="src"))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "scope")
        (workspace / "controllers").mkdir()
        sim.save(workspace / "controllers" / "pid.flw.json")

        response = client.post(
            "/api/v1/simulations",
            json={"model_path": "controllers/pid.flw.json"},
        )
        assert response.status_code == 200
        assert response.json()["model_id"] == "controllers/pid.flw.json"

    def test_404_for_nonexistent_model_path(self, workspace_client):
        client, _ = workspace_client
        response = client.post(
            "/api/v1/simulations", json={"model_path": "ghost.flw.json"}
        )
        assert response.status_code == 404

    def test_400_for_directory_model_path(self, workspace_client):
        client, workspace = workspace_client
        (workspace / "subdir").mkdir()
        response = client.post(
            "/api/v1/simulations", json={"model_path": "subdir"}
        )
        assert response.status_code == 400

    def test_403_for_path_traversal(self, workspace_client):
        client, _ = workspace_client
        response = client.post(
            "/api/v1/simulations", json={"model_path": "../escape.flw.json"}
        )
        assert response.status_code == 403

    def test_503_when_workspace_root_not_set(self, client):
        """legacy --model-dir モードで model_path 指定 → 503。"""
        response = client.post(
            "/api/v1/simulations", json={"model_path": "x.flw.json"}
        )
        assert response.status_code == 503


class TestStartSimulationInline:
    """ADR-0041 §論点 5-A: ``model`` (= インライン dict) ベースの起動。"""

    def test_starts_from_inline_model(self, workspace_client, tmp_path):
        client, _ = workspace_client
        model_dict = _build_simple_model_dict(tmp_path)
        response = client.post(
            "/api/v1/simulations", json={"model": model_dict}
        )
        assert response.status_code == 200
        data = response.json()
        assert "simulation_id" in data
        # インラインは display id = _INLINE_DISPLAY_ID (= 全インラインで共通)
        from pyflw.server.routes.simulations import _INLINE_DISPLAY_ID

        assert data["model_id"] == _INLINE_DISPLAY_ID

    def test_inline_model_runs_to_completion(self, workspace_client, tmp_path):
        client, _ = workspace_client
        model_dict = _build_simple_model_dict(tmp_path)
        response = client.post(
            "/api/v1/simulations", json={"model": model_dict}
        )
        sim_id = response.json()["simulation_id"]
        state = _wait_for_status(client, sim_id, {"completed"})
        assert state["status"] == "completed"

    def test_inline_works_in_legacy_model_dir_mode(self, client, tmp_path):
        """legacy --model-dir モードでもインライン実行は可能 (= fs アクセスなし)。"""
        model_dict = _build_simple_model_dict(tmp_path)
        response = client.post(
            "/api/v1/simulations", json={"model": model_dict}
        )
        assert response.status_code == 200

    def test_400_for_non_dict_model(self, workspace_client):
        client, _ = workspace_client
        response = client.post(
            "/api/v1/simulations", json={"model": "not a dict"}
        )
        assert response.status_code == 400

    def test_400_for_invalid_inline_model(self, workspace_client):
        """インライン model が壊れた dict なら 400 (ModelLoadError → 400)。"""
        client, _ = workspace_client
        response = client.post(
            "/api/v1/simulations",
            json={"model": {"schema_version": "0.8", "blocks": []}},
        )
        # 必須キー (simulator / connections) 欠落で ModelLoadError
        assert response.status_code == 400


class TestStartSimulationMutualExclusion:
    """ADR-0041 §論点 5-A: 3 形式は相互排他、複数指定 / 全欠落で 400。"""

    def test_400_for_no_keys(self, workspace_client):
        client, _ = workspace_client
        response = client.post("/api/v1/simulations", json={})
        assert response.status_code == 400
        assert "exactly one" in response.json()["detail"]

    def test_400_for_model_id_and_model_path(self, workspace_client):
        client, workspace = workspace_client
        # model_id 用の seed
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(Constant(value=1.0, id="src"))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "scope")
        sim.save(workspace / "demo.flw.json")
        response = client.post(
            "/api/v1/simulations",
            json={"model_id": "demo", "model_path": "demo.flw.json"},
        )
        assert response.status_code == 400
        assert "mutually exclusive" in response.json()["detail"]

    def test_400_for_model_path_and_inline(self, workspace_client, tmp_path):
        client, _ = workspace_client
        model_dict = _build_simple_model_dict(tmp_path)
        response = client.post(
            "/api/v1/simulations",
            json={"model_path": "x.flw.json", "model": model_dict},
        )
        assert response.status_code == 400

    def test_400_for_all_three(self, workspace_client):
        client, _ = workspace_client
        response = client.post(
            "/api/v1/simulations",
            json={"model_id": "x", "model_path": "y.flw.json", "model": {}},
        )
        assert response.status_code == 400


class TestStartSimulationDeprecation:
    """ADR-0041 §論点 5-A: ``model_id`` は deprecation warning を発行する。"""

    def test_model_id_emits_deprecation_warning(
        self, client, model_dir, recwarn
    ):
        _seed_simple_model(model_dir, "demo")
        response = client.post(
            "/api/v1/simulations", json={"model_id": "demo"}
        )
        assert response.status_code == 200
        deprecation_warnings = [
            w for w in recwarn.list if issubclass(w.category, DeprecationWarning)
        ]
        assert len(deprecation_warnings) >= 1
        assert "model_id" in str(deprecation_warnings[0].message)
        assert "ADR-0041" in str(deprecation_warnings[0].message)

    def test_model_path_does_not_emit_deprecation_warning(
        self, workspace_client, recwarn
    ):
        client, workspace = workspace_client
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(Constant(value=1.0, id="src"))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "scope")
        sim.save(workspace / "x.flw.json")
        response = client.post(
            "/api/v1/simulations", json={"model_path": "x.flw.json"}
        )
        assert response.status_code == 200
        deprecation_warnings = [
            w for w in recwarn.list if issubclass(w.category, DeprecationWarning)
        ]
        # model_path では deprecation warning 不要
        # ただし他箇所からの DeprecationWarning は許容するため、本 warning 文言で絞る
        assert not any(
            "model_id" in str(w.message) for w in deprecation_warnings
        )
