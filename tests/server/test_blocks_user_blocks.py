"""ADR-0081 U3: ユーザーブロックの server 配線 (起動時の読み込み・``blocks.v3``・再読み込み)。

ユーザーブロックの .py は ``tmp_path`` 配下のワークスペースに作る。読み込み状態の後始末と
``Path.home()`` の隔離は ``tests/server/conftest.py`` の autouse fixture が行う。
"""

from __future__ import annotations

import dataclasses
import json
import textwrap
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from flode import Simulator
from flode.blocks import Constant, Gain, Scope
from flode.exceptions import BlockReloadInProgressError
from flode.server import create_app
from flode.server.block_catalog import LOAD_ERROR_SUMMARIES, BlockCatalog
from flode.server.settings import Settings
from flode.userblocks import LoadRequest

WriteFile = Callable[[str, str], Path]

DOUBLER = '''
from flode import block


@block(
    category="Filters",
    display_name={"ja": "倍率", "en": "Scaler"},
    choices={"mode": ("fast", "slow")},
    input_names=("x",),
    output_names=("y",),
)
def scaler_probe(t: float, u: float, *, k: float = 2.0, mode: str = "fast") -> float:
    """Scale the input.

    Args:
        k: Gain applied to the input.
    """
    return k * u
'''

DOUBLER_V2 = '''
from flode import block


@block(category="Filters")
def scaler_probe(t: float, u: float, *, gain: float = 10.0) -> float:
    """Scale the input (v2)."""
    return gain * u
'''

SINK = '''
from flode import block


@block(outputs=0)
def sink_probe(t: float, u: float) -> None:
    """Swallow the input."""
'''

USER_TYPE = "flode_ws.filters.ScalerProbe"
SINK_TYPE = "flode_ws.sinks.SinkProbe"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "blocks").mkdir(parents=True)
    return ws


@pytest.fixture
def write_block(workspace: Path) -> WriteFile:
    def _write(rel: str, source: str) -> Path:
        path = workspace / "blocks" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source), encoding="utf-8")
        return path

    return _write


def _loopback_settings(workspace: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "workspace_root": workspace,
        "user_blocks_enabled": True,
        "user_blocks_reload_allowed": True,
        "user_blocks_request": LoadRequest(workspace=workspace),
        "loopback_bind": True,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def make_client() -> Iterator[Callable[[Settings], TestClient]]:
    """``create_app`` + lifespan 付き ``TestClient`` を作る (終了時に閉じる)。"""
    opened: list[TestClient] = []

    def _make(settings: Settings) -> TestClient:
        client = TestClient(create_app(settings=settings))
        client.__enter__()
        opened.append(client)
        return client

    yield _make
    for client in opened:
        client.__exit__(None, None, None)


def _blocks_by_type(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {b["type_path"]: b for b in payload["blocks"]}


def _model_with(type_path: str, params: dict[str, Any], tmp: Path) -> dict[str, Any]:
    """Constant → (type_path) → Scope の inline モデル (組み込みで保存してから型を差し替える)。"""
    sim = Simulator(t_end=0.03, dt=0.01)
    sim.add(Constant(value=3.0, id="c"))
    sim.add(Gain(k=1.0, id="u"))
    sim.add(Scope(n_inputs=1, id="scope"))
    sim.connect("c", "u")
    sim.connect("u", "scope")
    path = tmp / "_seed.flw.json"
    sim.save(path)
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    path.unlink()
    for entry in data["blocks"]:
        if entry["id"] == "u":
            entry["type"] = type_path
            entry["params"] = params
    return data


def _run_and_get_scope(client: TestClient, model: dict[str, Any]) -> list[Any]:
    resp = client.post("/api/v1/simulations", json={"model": model})
    assert resp.status_code == 200, resp.json()
    sim_id = resp.json()["simulation_id"]
    deadline = time.time() + 10
    while time.time() < deadline:
        state = client.get(f"/api/v1/simulations/{sim_id}").json()
        if state["status"] != "running":
            break
        time.sleep(0.02)
    results = client.get(f"/api/v1/simulations/{sim_id}/results").json()
    assert results["status"] == "completed", results
    values: list[Any] = results["scopes"]["scope"]["values"]
    return values


def _reload(client: TestClient, body: Any = None, **kwargs: Any) -> Any:
    return client.post("/api/v1/blocks/reload", json={} if body is None else body, **kwargs)


# ---------------------------------------------------------------------------
# 起動時の読み込み (create_app 直接)
# ---------------------------------------------------------------------------


class TestStartupLoading:
    def test_create_app_default_does_not_read_user_blocks(
        self, workspace: Path, write_block: WriteFile, make_client: Any
    ) -> None:
        marker = workspace / "executed.txt"
        write_block("filters.py", f"open({str(marker)!r}, 'w').write('x')\n" + DOUBLER)
        client = make_client(Settings(workspace_root=workspace))

        body = client.get("/api/v1/blocks").json()

        assert not marker.exists(), "create_app の既定でユーザーコードが実行された"
        assert USER_TYPE not in _blocks_by_type(body)
        assert body["sources"] == []
        assert body["load_errors"] == []
        status = body["user_blocks"]
        assert status["enabled"] is False
        assert status["reason"]
        assert status["reload_allowed"] is False
        assert status["reload_reason"]

    def test_loopback_reads_workspace_blocks(
        self, workspace: Path, write_block: WriteFile, make_client: Any
    ) -> None:
        write_block("filters.py", DOUBLER)
        client = make_client(_loopback_settings(workspace))

        body = client.get("/api/v1/blocks").json()

        assert body["schema_version"] == "blocks.v3"
        entry = _blocks_by_type(body)[USER_TYPE]
        assert entry["source"] == "workspace"
        assert entry["display_name"] == "Scaler"
        assert entry["display_name_i18n"] == {"ja": "倍率", "en": "Scaler"}
        assert entry["docstring_summary"] == "Scale the input."
        assert entry["category"] == "Filters"
        assert entry["icon"] == "default"
        assert (entry["default_n_inputs"], entry["default_n_outputs"]) == (1, 1)
        assert entry["input_names"] == ["x"]
        assert entry["output_names"] == ["y"]
        assert entry["params_spec"] == [
            {
                "name": "k",
                "type": "float",
                "has_default": True,
                "default": 2.0,
                "description": "Gain applied to the input.",
            },
            {
                "name": "mode",
                "type": "str",
                "has_default": True,
                "default": "fast",
                "description": "",
                "enum_values": ["fast", "slow"],
            },
        ]
        assert body["sources"] == [
            {
                "id": "workspace",
                "kind": "workspace",
                "label": "blocks/",
                "root": str((workspace / "blocks").resolve()),
                "reloadable": True,
                "from_cwd": False,
                "files": [{"path": "filters.py", "status": "ok"}],
            }
        ]
        assert body["user_blocks"] == {
            "enabled": True,
            "reason": None,
            "reload_allowed": True,
            "reload_reason": None,
            "restart_required_sources": [],
        }

    def test_sink_and_undeclared_category(
        self, workspace: Path, write_block: WriteFile, make_client: Any
    ) -> None:
        write_block("sinks.py", SINK)
        client = make_client(_loopback_settings(workspace))

        entry = _blocks_by_type(client.get("/api/v1/blocks").json())[SINK_TYPE]

        assert entry["category"] == ""
        assert (entry["default_n_inputs"], entry["default_n_outputs"]) == (1, 0)
        assert "sink" in entry["tags"]
        assert entry["params_spec"] == []
        assert (entry["input_names"], entry["output_names"]) == ([], [])

    def test_builtin_entries_get_builtin_source(
        self, workspace: Path, write_block: WriteFile, make_client: Any
    ) -> None:
        write_block("filters.py", DOUBLER)
        client = make_client(_loopback_settings(workspace))

        blocks = _blocks_by_type(client.get("/api/v1/blocks").json())
        gain = blocks["flode.blocks.mathops.Gain"]

        assert gain["source"] == "builtin"
        assert (gain["input_names"], gain["output_names"]) == ([], [])
        assert all(b["source"] == "builtin" for t, b in blocks.items() if t.startswith("flode."))

    def test_detail_endpoint_returns_user_block(
        self, workspace: Path, write_block: WriteFile, make_client: Any
    ) -> None:
        write_block("filters.py", DOUBLER)
        client = make_client(_loopback_settings(workspace))

        detail = client.get(f"/api/v1/blocks/{USER_TYPE}").json()

        assert detail["source"] == "workspace"
        assert detail["docstring_full"].startswith("Scale the input.")

    def test_enabled_without_request_reads_workspace_root(
        self, workspace: Path, write_block: WriteFile, make_client: Any
    ) -> None:
        write_block("filters.py", DOUBLER)
        client = make_client(_loopback_settings(workspace, user_blocks_request=None))

        assert USER_TYPE in _blocks_by_type(client.get("/api/v1/blocks").json())

    def test_settings_are_copied_defensively(self, workspace: Path) -> None:
        settings = _loopback_settings(workspace)
        app = create_app(settings=settings)
        settings.user_blocks_enabled = False
        settings.loopback_bind = False
        settings.user_blocks_reload_allowed = False

        copied = app.state.settings
        assert copied is not settings
        assert copied.user_blocks_enabled is True
        assert copied.loopback_bind is True
        assert copied.user_blocks_reload_allowed is True
        assert copied.user_blocks_request == LoadRequest(workspace=workspace)


# ---------------------------------------------------------------------------
# 非 loopback (許可あり) — 絶対パスを伏せる・再読み込みは 403
# ---------------------------------------------------------------------------


class TestNonLoopback:
    def test_paths_are_hidden(
        self, workspace: Path, write_block: WriteFile, tmp_path: Path, make_client: Any
    ) -> None:
        write_block("filters.py", DOUBLER)
        write_block("broken.py", f"raise ValueError({str(workspace / 'secret.txt')!r})\n")
        missing_dir = tmp_path / "no-such-lab"
        request = LoadRequest(workspace=workspace, dirs=(("lab", missing_dir),))
        client = make_client(
            Settings(
                workspace_root=workspace,
                user_blocks_enabled=True,
                user_blocks_reload_allowed=False,
                user_blocks_request=request,
                loopback_bind=False,
            )
        )

        body = client.get("/api/v1/blocks").json()

        assert USER_TYPE in _blocks_by_type(body)
        assert [s["root"] for s in body["sources"]] == [None]
        text = json.dumps(body, ensure_ascii=False)
        for secret in ("secret.txt", tmp_path.name, "no-such-lab"):
            assert secret not in text
        errors = {e["source"]: e for e in body["load_errors"]}
        # メッセージは種別ごとの固定文。場所は kind / path / line で分かる
        assert errors["workspace"]["message"] == LOAD_ERROR_SUMMARIES["import"]
        assert (errors["workspace"]["path"], errors["workspace"]["line"]) == ("blocks/broken.py", 1)
        assert errors["dir:lab"]["message"] == LOAD_ERROR_SUMMARIES["config"]
        assert body["user_blocks"]["reload_allowed"] is False
        assert "non-loopback" in body["user_blocks"]["reload_reason"]

    def test_loopback_keeps_full_messages(
        self, workspace: Path, write_block: WriteFile, make_client: Any
    ) -> None:
        secret = str(workspace / "secret.txt")
        write_block("broken.py", f"raise ValueError({secret!r})\n")
        client = make_client(_loopback_settings(workspace))

        [error] = client.get("/api/v1/blocks").json()["load_errors"]

        assert secret in error["message"]

    def test_reload_is_forbidden_even_when_allowed(
        self, workspace: Path, write_block: WriteFile, make_client: Any
    ) -> None:
        write_block("filters.py", DOUBLER)
        client = make_client(_loopback_settings(workspace, loopback_bind=False))

        resp = _reload(client)

        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["code"] == "reload_not_allowed"
        assert detail["category"] == "user_blocks"
        assert detail["template_key"] == "error.user_blocks.reload_not_allowed"
        assert detail["template_args"]["non_loopback"] is True
        assert detail["raw_message"] == detail["template_args"]["message"]


# ---------------------------------------------------------------------------
# POST /blocks/reload
# ---------------------------------------------------------------------------


class TestReload:
    def test_reload_reports_changes(
        self, workspace: Path, write_block: WriteFile, make_client: Any
    ) -> None:
        write_block("filters.py", DOUBLER)
        client = make_client(_loopback_settings(workspace))
        write_block("filters.py", DOUBLER_V2)
        write_block("sinks.py", SINK)

        resp = _reload(client)

        assert resp.status_code == 200
        body = resp.json()
        assert body["schema_version"] == "blocks.v3"
        assert body["added"] == [SINK_TYPE]
        assert body["removed"] == []
        assert body["changed"] == [USER_TYPE]
        assert body["restart_required_sources"] == []
        assert body["errors"] == body["load_errors"] == []
        entry = _blocks_by_type(body)[USER_TYPE]
        assert [p["name"] for p in entry["params_spec"]] == ["gain"]
        # GET も新しい registry を返す
        assert _blocks_by_type(client.get("/api/v1/blocks").json())[USER_TYPE] == entry

    def test_reload_removes_deleted_block(
        self, workspace: Path, write_block: WriteFile, make_client: Any
    ) -> None:
        path = write_block("filters.py", DOUBLER)
        client = make_client(_loopback_settings(workspace))
        path.unlink()

        body = _reload(client).json()

        assert body["removed"] == [USER_TYPE]
        assert USER_TYPE not in _blocks_by_type(body)

    def test_syntax_error_is_isolated(
        self, workspace: Path, write_block: WriteFile, make_client: Any
    ) -> None:
        write_block("filters.py", DOUBLER)
        client = make_client(_loopback_settings(workspace))
        write_block("broken.py", "def oops(:\n")

        body = _reload(client).json()

        assert USER_TYPE in _blocks_by_type(body)
        [error] = body["load_errors"]
        assert (error["path"], error["kind"], error["line"]) == ("blocks/broken.py", "syntax", 1)
        assert error["source"] == "workspace"
        assert error["severity"] == "error"
        files = {f["path"]: f["status"] for f in body["sources"][0]["files"]}
        assert files == {"broken.py": "error", "filters.py": "ok"}

    def test_reload_replaces_registry_object_once(
        self, workspace: Path, write_block: WriteFile, make_client: Any
    ) -> None:
        write_block("filters.py", DOUBLER)
        client = make_client(_loopback_settings(workspace))
        app = client.app
        before = app.state.block_registry
        write_block("filters.py", DOUBLER_V2)

        assert _reload(client).status_code == 200

        after = app.state.block_registry
        assert isinstance(after, BlockCatalog)
        assert after is not before
        # 古い世代は書き換えられていない (copy-on-write)、組み込みは使い回す
        old = {m.type_path: m for m in before.blocks}[USER_TYPE]
        assert [p.name for p in old.params_spec] == ["k", "mode"]
        assert after.builtin is before.builtin

    def test_get_during_reload_sees_previous_registry(
        self,
        workspace: Path,
        write_block: WriteFile,
        make_client: Any,
        mocker: MockerFixture,
    ) -> None:
        write_block("filters.py", DOUBLER)
        client = make_client(_loopback_settings(workspace))
        write_block("filters.py", DOUBLER_V2)
        started = threading.Event()
        release = threading.Event()
        from flode.server.routes import blocks as blocks_route

        real_reload = blocks_route.reload_sources

        def slow_reload() -> Any:
            started.set()
            assert release.wait(10)
            return real_reload()

        mocker.patch.object(blocks_route, "reload_sources", side_effect=slow_reload)
        result: dict[str, Any] = {}
        worker = threading.Thread(target=lambda: result.update(resp=_reload(client)))
        worker.start()
        try:
            assert started.wait(10)
            during = _blocks_by_type(client.get("/api/v1/blocks").json())[USER_TYPE]
            # 再読み込み中の 2 回目は 409
            second = _reload(client)
        finally:
            release.set()
            worker.join(10)

        assert [p["name"] for p in during["params_spec"]] == ["k", "mode"]
        assert second.status_code == 409
        assert second.json()["detail"]["code"] == "reload_in_progress"
        assert result["resp"].status_code == 200
        after = _blocks_by_type(client.get("/api/v1/blocks").json())[USER_TYPE]
        assert [p["name"] for p in after["params_spec"]] == ["gain"]

    def test_loader_lock_busy_is_409_and_keeps_registry(
        self, workspace: Path, write_block: WriteFile, make_client: Any, mocker: MockerFixture
    ) -> None:
        write_block("filters.py", DOUBLER)
        client = make_client(_loopback_settings(workspace))
        before = client.app.state.block_registry
        from flode.server.routes import blocks as blocks_route

        mocker.patch.object(
            blocks_route,
            "reload_sources",
            side_effect=BlockReloadInProgressError("busy (Python API)"),
        )

        resp = _reload(client)

        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["code"] == "reload_in_progress"
        assert detail["template_key"] == "error.user_blocks.reload_in_progress"
        assert client.app.state.block_registry is before
        # ロックは解放されている (次の再読み込みは通る)
        mocker.stopall()
        assert _reload(client).status_code == 200

    def test_disabled_reload_is_403(self, workspace: Path, make_client: Any) -> None:
        client = make_client(Settings(workspace_root=workspace))

        resp = _reload(client)

        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["code"] == "user_blocks_disabled"
        assert detail["template_args"]["non_loopback"] is True

    @pytest.mark.parametrize("body", [{"workspace": "/etc"}, [], "x", None, 1])
    def test_body_must_be_empty_object(self, workspace: Path, make_client: Any, body: Any) -> None:
        client = make_client(_loopback_settings(workspace))

        resp = client.post(
            "/api/v1/blocks/reload",
            content=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )

        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "invalid_reload_body"

    def test_empty_body_is_400(self, workspace: Path, make_client: Any) -> None:
        client = make_client(_loopback_settings(workspace))

        resp = client.post("/api/v1/blocks/reload")

        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "invalid_reload_body"

    def test_non_json_content_type_is_415(self, workspace: Path, make_client: Any) -> None:
        client = make_client(_loopback_settings(workspace))

        resp = client.post(
            "/api/v1/blocks/reload", content="{}", headers={"Content-Type": "text/plain"}
        )

        assert resp.status_code == 415

    def test_cross_origin_is_403(self, workspace: Path, make_client: Any) -> None:
        client = make_client(_loopback_settings(workspace))

        resp = _reload(client, headers={"Origin": "http://evil.example"})

        assert resp.status_code == 403

    def test_get_reload_is_405(self, workspace: Path, make_client: Any) -> None:
        client = make_client(_loopback_settings(workspace))

        assert client.get("/api/v1/blocks/reload").status_code == 405


# ---------------------------------------------------------------------------
# 一連の流れ: GET → 置いて実行 → .py を書き換えて reload → 定義が変わる
# ---------------------------------------------------------------------------


def test_place_run_edit_reload_run(
    workspace: Path, write_block: WriteFile, tmp_path: Path, make_client: Any
) -> None:
    write_block("filters.py", DOUBLER)
    client = make_client(_loopback_settings(workspace))

    entry = _blocks_by_type(client.get("/api/v1/blocks").json())[USER_TYPE]
    params = {p["name"]: p["default"] for p in entry["params_spec"]}
    values = _run_and_get_scope(client, _model_with(USER_TYPE, params, tmp_path))
    assert values[-1] == [6.0]

    write_block("filters.py", DOUBLER_V2)
    body = _reload(client).json()
    assert body["changed"] == [USER_TYPE]

    new_entry = _blocks_by_type(body)[USER_TYPE]
    new_params = {p["name"]: p["default"] for p in new_entry["params_spec"]}
    assert new_params == {"gain": 10.0}
    values = _run_and_get_scope(client, _model_with(USER_TYPE, new_params, tmp_path))
    assert values[-1] == [30.0]


class TestReloadConsistency:
    def test_server_lock_held_is_409_and_keeps_registry(
        self, workspace: Path, write_block: WriteFile, make_client: Any
    ) -> None:
        write_block("filters.py", DOUBLER)
        client = make_client(_loopback_settings(workspace))
        before = client.app.state.block_registry
        write_block("filters.py", DOUBLER_V2)
        lock = client.app.state.block_reload_lock

        assert lock.acquire(blocking=False)
        try:
            resp = _reload(client)
        finally:
            lock.release()

        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "reload_in_progress"
        assert client.app.state.block_registry is before
        assert not lock.locked()

    def test_compose_failure_keeps_registry_and_logs(
        self,
        workspace: Path,
        write_block: WriteFile,
        make_client: Any,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        write_block("filters.py", DOUBLER)
        client = make_client(_loopback_settings(workspace))
        before = client.app.state.block_registry
        from flode.server.routes import blocks as blocks_route

        mocker.patch.object(blocks_route, "compose_catalog", side_effect=RuntimeError("boom"))

        with caplog.at_level("ERROR", logger="flode.server.routes.blocks"):
            with pytest.raises(RuntimeError, match="boom"):
                _reload(client)

        assert client.app.state.block_registry is before
        assert "registry was not replaced" in caplog.text
        assert not client.app.state.block_reload_lock.locked()


def test_user_block_replaces_builtin_entry_with_same_type(
    workspace: Path, write_block: WriteFile, make_client: Any, mocker: MockerFixture
) -> None:
    """管理型表と同じ型名の組み込み側エントリは捨てる (ADR-0081 §1-D)。"""
    from flode.server import block_catalog
    from flode.server.registry import build_block_registry

    write_block("filters.py", DOUBLER)
    real = build_block_registry()
    fake = dataclasses.replace(real[0], type_path=USER_TYPE, display_name="Stale builtin")
    mocker.patch.object(block_catalog, "build_block_registry", return_value=[*real, fake])
    client = make_client(_loopback_settings(workspace))

    blocks = client.get("/api/v1/blocks").json()["blocks"]

    matching = [b for b in blocks if b["type_path"] == USER_TYPE]
    assert len(matching) == 1
    assert matching[0]["source"] == "workspace"
    assert matching[0]["display_name"] == "Scaler"
