"""ADR-0011 §(1)(2) / ADR-0041 §5: シミュレーション制御 + WebSocket のテスト。

v0.21.0: legacy ``model_id`` 受付削除済。``model_path`` (= workspace 相対) /
``model`` (= インライン dict) 経路のみテスト。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from flode import Simulator
from flode.blocks import Constant, Gain, Scope
from flode.server import create_app
from flode.server.routes.simulations import _INLINE_DISPLAY_ID
from flode.server.settings import Settings


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def client(workspace: Path) -> TestClient:
    settings = Settings(workspace_root=workspace)
    app = create_app(settings=settings)
    with TestClient(app) as c:
        yield c


def _seed_simple_model(workspace: Path, name: str = "demo") -> str:
    """workspace 配下に minimal な ``.flw.json`` を作成して **basename** を返す。"""
    sim = Simulator(t_end=0.05, dt=0.01)
    sim.add(Constant(value=2.0, id="src"))
    sim.add(Gain(k=3.0, id="g"))
    sim.add(Scope(n_inputs=1, id="scope"))
    sim.connect("src", "g")
    sim.connect("g", "scope")
    p = workspace / f"{name}.flw.json"
    sim.save(p)
    return f"{name}.flw.json"


def _build_simple_model_dict(tmp_path: Path) -> dict:
    """インライン用の minimal `.flw.json` dict を生成する。

    ``Simulator`` は ``to_dict`` を持たないため、``save`` 経由で生成して再 load する。
    """
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


def _wait_for_status(client, sim_id: str, target: set[str], timeout: float = 5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/v1/simulations/{sim_id}")
        if response.status_code == 200 and response.json()["status"] in target:
            return response.json()
        time.sleep(0.02)
    raise AssertionError(f"simulation {sim_id} did not reach {target} within {timeout}s")


# ---------------------------------------------------------------------------
# model_path 経路 (= workspace 相対 path)
# ---------------------------------------------------------------------------


class TestStartSimulationModelPath:
    def test_starts_from_model_path(self, client: TestClient, workspace: Path) -> None:
        path = _seed_simple_model(workspace, "demo")
        response = client.post("/api/v1/simulations", json={"model_path": path})
        assert response.status_code == 200
        data = response.json()
        assert "simulation_id" in data
        assert data["model_id"] == "demo.flw.json"

    def test_starts_from_subdirectory(self, client: TestClient, workspace: Path) -> None:
        (workspace / "controllers").mkdir()
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(Constant(value=1.0, id="src"))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "scope")
        sim.save(workspace / "controllers" / "pid.flw.json")
        response = client.post(
            "/api/v1/simulations",
            json={"model_path": "controllers/pid.flw.json"},
        )
        assert response.status_code == 200
        assert response.json()["model_id"] == "controllers/pid.flw.json"

    def test_404_for_nonexistent_model_path(self, client: TestClient) -> None:
        response = client.post("/api/v1/simulations", json={"model_path": "ghost.flw.json"})
        assert response.status_code == 404

    def test_400_for_directory_model_path(self, client: TestClient, workspace: Path) -> None:
        (workspace / "subdir").mkdir()
        response = client.post("/api/v1/simulations", json={"model_path": "subdir"})
        assert response.status_code == 400

    def test_403_for_path_traversal(self, client: TestClient) -> None:
        response = client.post("/api/v1/simulations", json={"model_path": "../escape.flw.json"})
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# model (inline) 経路
# ---------------------------------------------------------------------------


class TestStartSimulationInline:
    def test_starts_from_inline_model(self, client: TestClient, tmp_path: Path) -> None:
        model_dict = _build_simple_model_dict(tmp_path)
        response = client.post("/api/v1/simulations", json={"model": model_dict})
        assert response.status_code == 200
        assert response.json()["model_id"] == _INLINE_DISPLAY_ID

    def test_inline_model_runs_to_completion(self, client: TestClient, tmp_path: Path) -> None:
        model_dict = _build_simple_model_dict(tmp_path)
        response = client.post("/api/v1/simulations", json={"model": model_dict})
        sim_id = response.json()["simulation_id"]
        state = _wait_for_status(client, sim_id, {"completed"})
        assert state["status"] == "completed"

    def test_400_for_non_dict_model(self, client: TestClient) -> None:
        response = client.post("/api/v1/simulations", json={"model": "not a dict"})
        assert response.status_code == 400

    def test_400_for_invalid_inline_model(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/simulations",
            json={"model": {"schema_version": "0.8", "blocks": []}},
        )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# 相互排他 / model_id 撤去
# ---------------------------------------------------------------------------


class TestStartSimulationMutualExclusion:
    def test_400_for_no_keys(self, client: TestClient) -> None:
        response = client.post("/api/v1/simulations", json={})
        assert response.status_code == 400
        # ADR-0056 §B-2: detail は構造化 dict、raw_message に文言が入る。
        detail = response.json()["detail"]
        assert isinstance(detail, dict)
        assert detail["category"] == "start_validation"
        assert "exactly one" in detail["raw_message"]

    def test_400_for_both_keys(self, client: TestClient, workspace: Path, tmp_path: Path) -> None:
        path = _seed_simple_model(workspace, "demo")
        model_dict = _build_simple_model_dict(tmp_path)
        response = client.post(
            "/api/v1/simulations",
            json={"model_path": path, "model": model_dict},
        )
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert isinstance(detail, dict)
        assert detail["category"] == "start_validation"
        assert "mutually exclusive" in detail["raw_message"]

    def test_400_for_legacy_model_id(self, client: TestClient) -> None:
        """v0.21.0: legacy ``model_id`` は recognized なキーから外れて
        400 'no keys' エラーになる。"""
        response = client.post("/api/v1/simulations", json={"model_id": "demo"})
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Lifecycle / Stop / Stream (model_path 経由で動作確認)
# ---------------------------------------------------------------------------


class TestSimulationLifecycle:
    def test_completes_and_results_available(self, client: TestClient, workspace: Path) -> None:
        path = _seed_simple_model(workspace, "demo")
        response = client.post("/api/v1/simulations", json={"model_path": path})
        sim_id = response.json()["simulation_id"]

        state = _wait_for_status(client, sim_id, {"completed"})
        assert state["status"] == "completed"

        results = client.get(f"/api/v1/simulations/{sim_id}/results")
        assert results.status_code == 200
        data = results.json()
        assert "scope" in data["scopes"]
        assert all(v == [6.0] for v in data["scopes"]["scope"]["values"])

    def test_404_for_unknown_simulation(self, client: TestClient) -> None:
        response = client.get("/api/v1/simulations/nosuchsim")
        assert response.status_code == 404


class TestStopSimulation:
    def test_stop_marks_simulation_stopped(self, client: TestClient, workspace: Path) -> None:
        sim = Simulator(t_end=10.0, dt=0.001)
        sim.add(Constant(value=1.0, id="src"))
        sim.add(Gain(k=1.0, id="g"))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "g")
        sim.connect("g", "scope")
        sim.save(workspace / "long.flw.json")

        response = client.post("/api/v1/simulations", json={"model_path": "long.flw.json"})
        sim_id = response.json()["simulation_id"]

        time.sleep(0.05)
        stop_response = client.post(f"/api/v1/simulations/{sim_id}/stop")
        assert stop_response.status_code == 200

        state = _wait_for_status(client, sim_id, {"stopped", "completed"}, timeout=10.0)
        assert state["status"] in ("stopped", "completed")


class TestWebSocketStream:
    def test_receives_progress_and_completed(self, client: TestClient, workspace: Path) -> None:
        path = _seed_simple_model(workspace, "demo")
        response = client.post("/api/v1/simulations", json={"model_path": path})
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
    def test_scope_batch_dispatched_when_buffer_fills(
        self, client: TestClient, workspace: Path
    ) -> None:
        sim = Simulator(t_end=2.0, dt=0.01)
        sim.add(Constant(value=1.0, id="src"))
        sim.add(Gain(k=1.0, id="g"))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "g")
        sim.connect("g", "scope")
        sim.save(workspace / "batchy.flw.json")

        response = client.post("/api/v1/simulations", json={"model_path": "batchy.flw.json"})
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


class TestUnboundedTEnd:
    """ADR-0042 §論点 3-A: ``t_end="inf"`` で WS / REST の wire 形式が ``"inf"``。"""

    def _save_inf_model(self, workspace: Path) -> str:
        sim = Simulator(t_end="inf", dt=0.01)
        sim.add(Constant(value=1.0, id="src"))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "scope")
        sim.save(workspace / "unbounded.flw.json")
        return "unbounded.flw.json"

    def test_rest_state_t_end_is_inf_string(self, client: TestClient, workspace: Path) -> None:
        path = self._save_inf_model(workspace)
        response = client.post("/api/v1/simulations", json={"model_path": path})
        sim_id = response.json()["simulation_id"]

        # state を即取得 (= まだ走り続けている)
        time.sleep(0.05)
        state_resp = client.get(f"/api/v1/simulations/{sim_id}")
        assert state_resp.status_code == 200
        state = state_resp.json()
        # ADR-0042 §論点 3-A: REST で ``t_end`` は ``"inf"`` 文字列で配信
        assert state["t_end"] == "inf"

        # 後始末: 停止して bg thread を終わらせる
        client.post(f"/api/v1/simulations/{sim_id}/stop")
        _wait_for_status(client, sim_id, {"stopped", "completed"}, timeout=5.0)

    def test_ws_progress_t_end_is_inf_string(self, client: TestClient, workspace: Path) -> None:
        path = self._save_inf_model(workspace)
        response = client.post("/api/v1/simulations", json={"model_path": path})
        sim_id = response.json()["simulation_id"]

        progress_t_ends: list = []
        with client.websocket_connect(f"/api/v1/simulations/{sim_id}/stream") as ws:
            # 数件 progress を受信したら stop を送る
            for _ in range(20):
                msg = ws.receive_json()
                if msg["type"] == "progress":
                    progress_t_ends.append(msg["t_end"])
                    if len(progress_t_ends) >= 3:
                        ws.send_json({"type": "stop"})
                if msg["type"] in ("completed", "stopped", "failed"):
                    break

        assert len(progress_t_ends) >= 1
        # 全 progress message で t_end == "inf" 文字列
        assert all(t == "inf" for t in progress_t_ends), progress_t_ends

    def test_finite_t_end_still_serializes_as_number(
        self, client: TestClient, workspace: Path
    ) -> None:
        # 既存挙動: 有限 t_end は ``float`` で配信される (= 後方互換)
        path = _seed_simple_model(workspace, "demo")
        response = client.post("/api/v1/simulations", json={"model_path": path})
        sim_id = response.json()["simulation_id"]

        state = _wait_for_status(client, sim_id, {"completed"})
        # state.t_end は数値 (= 0.05)
        assert isinstance(state["t_end"], int | float)
        assert state["t_end"] == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# ADR-0081 §4-B: 解決できない型は全部列挙して unknown_block_type (400)
# ---------------------------------------------------------------------------


def _model_with_missing_types(tmp_path: Path) -> dict:
    """トップレベルに 2 件、Subsystem 内部に 1 件の解決できない型を持つモデル。"""
    from flode.subsystems import Inport, Outport, Subsystem

    sub = Subsystem(
        blocks=[
            Inport(port_idx=0, id="ip"),
            Gain(k=1.0, id="inner"),
            Outport(port_idx=0, id="op"),
        ],
        connections=[
            {"src": "ip", "src_port": 0, "dst": "inner", "dst_port": 0},
            {"src": "inner", "src_port": 0, "dst": "op", "dst_port": 0},
        ],
        id="sub",
    )
    sim = Simulator(t_end=0.05, dt=0.01)
    sim.add(Constant(value=1.0, id="src"))
    sim.add(Gain(k=2.0, id="g1"))
    sim.add(Gain(k=2.0, id="g2"))
    sim.add(sub)
    sim.connect("src", "g1")
    sim.connect("g1", "g2")
    sim.connect("g2", "sub")
    p = tmp_path / "_missing_seed.flw.json"
    sim.save(p)
    data = json.loads(p.read_text(encoding="utf-8"))
    p.unlink()
    for entry in data["blocks"]:
        if entry["id"] == "g1":
            entry["type"] = "flode_ws.filters.GoneBlock"
        elif entry["id"] == "g2":
            entry["type"] = "no.such.Block"
        elif entry["id"] == "sub":
            for inner in entry["params"]["blocks"]:
                if inner["id"] == "inner":
                    inner["type"] = "flode_ws.filters.GoneBlock"
    return data


class TestUnknownBlockType:
    def _assert_all_listed(self, response) -> None:
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["category"] == "unknown_block_type"
        assert detail["code"] == "unknown_block_type"
        assert detail["template_key"] == "error.unknown_block_type"
        args = detail["template_args"]
        assert args["types"] == ["flode_ws.filters.GoneBlock", "no.such.Block"]
        assert args["blocks"] == [
            {"block_id": "g1", "qualified_id": "g1", "type": "flode_ws.filters.GoneBlock"},
            {"block_id": "g2", "qualified_id": "g2", "type": "no.such.Block"},
            {
                "block_id": "inner",
                "qualified_id": "sub/inner",
                "type": "flode_ws.filters.GoneBlock",
            },
        ]
        assert args["block_labels"] == ["g1", "g2", "sub/inner"]
        assert detail["block_ids"] == ["g1", "g2", "inner"]
        assert detail["block_id"] == "g1"
        assert "flode_ws.filters.GoneBlock" in detail["raw_message"]

    def test_inline_lists_every_missing_type(self, client: TestClient, tmp_path: Path) -> None:
        response = client.post(
            "/api/v1/simulations", json={"model": _model_with_missing_types(tmp_path)}
        )
        self._assert_all_listed(response)

    def test_model_path_lists_every_missing_type(
        self, client: TestClient, workspace: Path, tmp_path: Path
    ) -> None:
        (workspace / "broken.flw.json").write_text(
            json.dumps(_model_with_missing_types(tmp_path)), encoding="utf-8"
        )
        response = client.post("/api/v1/simulations", json={"model_path": "broken.flw.json"})
        self._assert_all_listed(response)

    def test_resolve_dtypes_lists_every_missing_type(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        response = client.post(
            "/api/v1/models/resolve-dtypes", json={"model": _model_with_missing_types(tmp_path)}
        )
        self._assert_all_listed(response)

    def test_other_load_errors_keep_start_validation(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        model = _build_simple_model_dict(tmp_path)
        model["schema_version"] = "9.9"
        response = client.post("/api/v1/simulations", json={"model": model})
        assert response.status_code == 400
        assert response.json()["detail"]["category"] == "start_validation"


def _bare_model(blocks: list, tmp_path: Path) -> dict:
    model = _build_simple_model_dict(tmp_path)
    model["blocks"] = blocks
    model["connections"] = []
    model.pop("layout", None)
    return model


class TestUnknownBlockTypeLimits:
    def test_many_types_are_truncated(self, client: TestClient, tmp_path: Path) -> None:
        from flode.server.routes.simulations import MAX_LISTED_UNKNOWN_TYPES

        n = MAX_LISTED_UNKNOWN_TYPES + 10
        model = _bare_model(
            [{"id": f"b{i}", "type": f"no.such.Block{i}", "params": {}} for i in range(n)], tmp_path
        )
        response = client.post("/api/v1/simulations", json={"model": model})
        assert response.status_code == 400
        args = response.json()["detail"]["template_args"]
        assert len(args["types"]) == MAX_LISTED_UNKNOWN_TYPES
        assert args["truncated"] is True

    def test_many_blocks_are_truncated(self, client: TestClient, tmp_path: Path) -> None:
        from flode.server.routes.simulations import MAX_LISTED_UNKNOWN_BLOCKS

        n = MAX_LISTED_UNKNOWN_BLOCKS + 10
        model = _bare_model(
            [{"id": f"b{i}", "type": "no.such.Block", "params": {}} for i in range(n)], tmp_path
        )
        response = client.post("/api/v1/simulations", json={"model": model})
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert len(detail["template_args"]["blocks"]) == MAX_LISTED_UNKNOWN_BLOCKS
        assert detail["template_args"]["truncated"] is True
        assert len(detail["block_ids"]) == MAX_LISTED_UNKNOWN_BLOCKS

    def test_small_model_is_not_truncated(self, client: TestClient, tmp_path: Path) -> None:
        model = _bare_model([{"id": "b", "type": "no.such.Block", "params": {}}], tmp_path)
        response = client.post("/api/v1/simulations", json={"model": model})
        assert response.json()["detail"]["template_args"]["truncated"] is False

    @pytest.mark.parametrize("endpoint", ["/api/v1/simulations", "/api/v1/models/resolve-dtypes"])
    def test_deeply_nested_model_is_4xx(
        self, client: TestClient, endpoint: str, tmp_path: Path
    ) -> None:
        inner: dict = {"id": "leaf", "type": "flode_ws.gone.Missing", "params": {}}
        for i in range(300):
            inner = {
                "id": f"s{i}",
                "type": "flode.subsystems.subsystem.Subsystem",
                "params": {"blocks": [inner], "connections": []},
            }
        response = client.post(endpoint, json={"model": _bare_model([inner], tmp_path)})
        assert 400 <= response.status_code < 500, response.text

    def test_scan_is_not_recursive(self, tmp_path: Path) -> None:
        """列挙の走査自体は再帰しない (Python の再帰上限を超える深さでも全段を見る)。"""
        from flode.server.routes.simulations import _missing_block_types

        inner: dict = {"id": "leaf", "type": "flode_ws.gone.Missing", "params": {}}
        for i in range(3000):
            inner = {
                "id": f"s{i}",
                "type": "flode.subsystems.subsystem.Subsystem",
                "params": {"blocks": [inner]},
            }
        missing, truncated = _missing_block_types(_bare_model([inner], tmp_path))
        assert [m.type_path for m in missing] == ["flode_ws.gone.Missing"]
        assert missing[0].qualified_id.endswith("/s0/leaf")
        assert truncated is False

    def test_enumeration_failure_falls_back(
        self, client: TestClient, mocker: MockerFixture, tmp_path: Path
    ) -> None:
        from flode.server.routes import simulations as sim_route

        mocker.patch.object(sim_route, "resolve_block_class", side_effect=RuntimeError("x"))
        model = _bare_model([{"id": "b", "type": "no.such.Block", "params": {}}], tmp_path)
        response = client.post("/api/v1/simulations", json={"model": model})
        assert response.status_code == 400
        assert response.json()["detail"]["category"] == "start_validation"
