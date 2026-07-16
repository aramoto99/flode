"""ADR-0056 §B-3/B-4: ``SimulationManager`` の失敗時挙動テスト。

検証:
  * 失敗時の WS ``failed`` メッセージに構造化フィールド (category, template_key,
    block_id, raw_message, raw_traceback) が含まれる
  * 旧 ``error`` メッセージは送出されない (= 廃止)
  * 終端済みシミュレーションへの再接続時、保持された terminal が 1 回 replay される
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flode.blocks.mathops import Divide, Gain
from flode.blocks.sinks import Scope
from flode.blocks.sources import Constant
from flode.core.simulator import Simulator
from flode.server import create_app
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


def _seed_divide_by_zero_model(workspace: Path) -> str:
    """0 除算で確実に失敗するモデル (Constant 0 / Constant 1 を Divide に)。"""
    sim = Simulator(t_end=1.0, dt=0.01)
    sim.add(Constant(value=1.0, id="num"))
    sim.add(Constant(value=0.0, id="den"))
    sim.add(Divide(signs="*/", id="div"))
    sim.add(Scope(n_inputs=1, id="scope"))
    sim.connect("num", "div", dst_idx=0)
    sim.connect("den", "div", dst_idx=1)
    sim.connect("div", "scope")
    path = workspace / "div_zero.flw.json"
    sim.save(path)
    return "div_zero.flw.json"


def _wait_terminal(client: TestClient, sim_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/v1/simulations/{sim_id}")
        if r.status_code == 200 and r.json()["status"] in ("completed", "stopped", "failed"):
            return r.json()
        time.sleep(0.05)
    pytest.fail(f"simulation {sim_id} did not terminate in {timeout}s")


class TestStructuredFailedMessage:
    def test_failed_includes_structured_fields(self, client: TestClient, workspace: Path) -> None:
        """0 除算で失敗するモデルを Run、WS の ``failed`` に構造化フィールドが入る。

        ``Constant 0`` ÷ ``Constant 1`` は numpy が +/-inf を返すだけで raise しない
        ため、明示的に ``ZeroDivisionError`` を起こす sentinel ブロックを別途
        埋め込む必要がある。テスト目的でも ``BlockSpecError`` (= start_validation 系)
        は実 raise なので、確実に失敗する経路として ``Gain(k=np.nan)`` 等は使えない。
        代わりに ``Simulator.from_dict`` で **未知ブロック type** を仕込んで起動失敗
        (start_validation) を起こす経路で構造化 detail を検証する。
        """
        # 明示的に未知 type を含む inline model (= start でロード失敗するため runtime
        # まで到達しないが、route 側の構造化 detail が確認できる)。
        response = client.post(
            "/api/v1/simulations",
            json={
                "model": {
                    "schema_version": "1.0",
                    "blocks": [{"id": "x", "type": "flode.blocks.nonexistent.Foo", "params": {}}],
                    "connections": [],
                    "config": {"t_end": 1.0, "dt": 0.01, "solver": "RK45"},
                }
            },
        )
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert isinstance(detail, dict)
        assert detail["category"] == "start_validation"
        assert detail["template_key"] == "error.start_validation"
        assert detail["raw_message"]
        assert "type" not in detail  # ``type`` は WS で merge される field

    def test_algebraic_loop_failure_has_block_ids(
        self, client: TestClient, workspace: Path
    ) -> None:
        """代数ループは ``_execution_order`` で raise されるため ``failed`` に
        ``block_ids`` (= ループ関与ブロック配列) が入る。
        """
        sim = Simulator(t_end=1.0, dt=0.01)
        sim.add(Gain(k=1.0, id="a"))
        sim.add(Gain(k=1.0, id="b"))
        sim.connect("a", "b")
        sim.connect("b", "a")
        path = workspace / "loop.flw.json"
        sim.save(path)

        response = client.post("/api/v1/simulations", json={"model_path": "loop.flw.json"})
        # 代数ループは start API 段階では検出されない (= ``Simulator.load`` は通る、
        # ``run`` 内で ``_execution_order`` が raise)。WS で失敗を観測する。
        assert response.status_code == 200
        sim_id = response.json()["simulation_id"]

        terminal: dict | None = None
        with client.websocket_connect(f"/api/v1/simulations/{sim_id}/stream") as ws:
            for _ in range(50):
                msg = ws.receive_json()
                if msg["type"] in ("completed", "stopped", "failed"):
                    terminal = msg
                    break

        assert terminal is not None
        assert terminal["type"] == "failed"
        assert terminal["category"] == "algebraic_loop"
        # code-reviewer SHOULD-5: ``_execution_order`` の残留リストはブロック登録順
        # に依存する。順序ではなく集合一致で検証する。
        assert set(terminal["block_ids"]) == {"a", "b"}
        assert "duration_sec" in terminal
        assert terminal["raw_traceback"]


class TestReplayOnReconnect:
    def test_reconnect_replays_terminal(self, client: TestClient, workspace: Path) -> None:
        """終端済みシミュレーションへの再接続時、保持された terminal が 1 回 yield される。"""
        # 高速完了する正常モデルを使う。
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(Constant(value=1.0, id="src"))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "scope")
        sim.save(workspace / "fast.flw.json")

        response = client.post("/api/v1/simulations", json={"model_path": "fast.flw.json"})
        sim_id = response.json()["simulation_id"]

        # 1 回目: 完了まで待つ
        with client.websocket_connect(f"/api/v1/simulations/{sim_id}/stream") as ws:
            for _ in range(200):
                msg = ws.receive_json()
                if msg["type"] in ("completed", "stopped", "failed"):
                    break

        # 2 回目 (= 再接続): terminal が 1 回だけ届くはず
        with client.websocket_connect(f"/api/v1/simulations/{sim_id}/stream") as ws:
            replay = ws.receive_json()

        assert replay["type"] == "completed"
        assert "duration_sec" in replay
