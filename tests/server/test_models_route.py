"""SPEC-0027 §5.2: ``POST /api/v1/models/resolve-dtypes`` のテスト。

2 形式 (inline / model_path)・エラーマップ (400/403/404/405)・
型解決失敗の 200 + 診断・PythonFunction 非実行 (セキュリティ) を固定する。
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from flode import Simulator
from flode.blocks.cast import Cast
from flode.blocks.mathops import Gain
from flode.blocks.pythonfunc import PythonFunction
from flode.blocks.sources import Constant
from flode.server.app import create_app
from flode.server.settings import Settings


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def client(workspace: Path) -> Any:
    settings = Settings(workspace_root=workspace)
    app = create_app(settings=settings)
    with TestClient(app) as c:
        yield c


def _model_dict(sim: Simulator, tmp: Path) -> dict[str, Any]:
    """Simulator → インライン model dict (Simulator に to_dict が無いため save 経由)。"""
    path = tmp / "_serialize_helper.flw.json"
    sim.save(path)
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    path.unlink()
    return data


def _int_gain_model(tmp: Path) -> dict[str, Any]:
    sim = Simulator(t_end=0.1, dt=0.01)
    c = sim.add(Constant(value=2.0, dtype="int64", id="c"))
    g = sim.add(Gain(k=3.0, id="g"))
    sim.connect(c, g)
    return _model_dict(sim, tmp)


ENDPOINT = "/api/v1/models/resolve-dtypes"


class TestResolveDtypesEndpoint:
    def test_inline_model_resolves(self, client: TestClient, tmp_path: Path) -> None:
        resp = client.post(ENDPOINT, json={"model": _int_gain_model(tmp_path)})
        assert resp.status_code == 200
        body = resp.json()
        assert body["schema_version"] == "dtypes.v1"
        ports = {
            (p["block_id"], p["direction"], p["port_index"]): p["dtype"] for p in body["ports"]
        }
        assert ports[("c", "out", 0)] == "int64"
        assert ports[("g", "in", 0)] == "int64"
        assert ports[("g", "out", 0)] == "float64"

    def test_model_path_resolves(self, client: TestClient, workspace: Path) -> None:
        sim = Simulator(t_end=0.1, dt=0.01)
        sim.add(Constant(value=1.0, dtype="bool", id="c"))
        sim.save(workspace / "m.flw.json")
        resp = client.post(ENDPOINT, json={"model_path": "m.flw.json"})
        assert resp.status_code == 200
        assert resp.json()["summary"]["by_dtype"] == {"bool": 1}

    def test_get_is_405(self, client: TestClient) -> None:
        resp = client.get(ENDPOINT)
        assert resp.status_code == 405

    def test_non_object_body_is_400(self, client: TestClient) -> None:
        resp = client.post(ENDPOINT, json=[1, 2, 3])
        assert resp.status_code == 400

    def test_missing_keys_is_400(self, client: TestClient) -> None:
        resp = client.post(ENDPOINT, json={})
        assert resp.status_code == 400

    def test_both_keys_is_400(self, client: TestClient, tmp_path: Path) -> None:
        resp = client.post(
            ENDPOINT,
            json={"model": _int_gain_model(tmp_path), "model_path": "m.flw.json"},
        )
        assert resp.status_code == 400

    def test_path_traversal_is_403(self, client: TestClient) -> None:
        resp = client.post(ENDPOINT, json={"model_path": "../outside.flw.json"})
        assert resp.status_code == 403

    def test_missing_file_is_404(self, client: TestClient) -> None:
        resp = client.post(ENDPOINT, json={"model_path": "no_such.flw.json"})
        assert resp.status_code == 404

    def test_unknown_block_type_is_400(self, client: TestClient, tmp_path: Path) -> None:
        model = _int_gain_model(tmp_path)
        model["blocks"][0]["type"] = "no.such.Block"
        resp = client.post(ENDPOINT, json={"model": model})
        assert resp.status_code == 400

    def test_algebraic_loop_is_200_with_build_failed(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        sim = Simulator(t_end=0.1, dt=0.01)
        g1 = sim.add(Gain(k=1.0, id="g1"))
        g2 = sim.add(Gain(k=1.0, id="g2"))
        sim.connect(g1, g2)
        sim.connect(g2, g1)
        resp = client.post(ENDPOINT, json={"model": _model_dict(sim, tmp_path)})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ports"] == []
        assert [d["code"] for d in body["diagnostics"]] == ["dtype.build_failed"]
        assert body["diagnostics"][0]["severity"] == "error"

    def test_python_function_model_is_200_and_never_executes(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        # セキュリティの要 (SPEC-0027 §非機能要件): server 既定 policy
        # (--allow-python-blocks なし)・python_ack なしでも 200 が返り、
        # かつユーザーコードは module レベル副作用 (marker) ごと実行されない。
        marker = tmp_path / "executed.txt"
        code = textwrap.dedent(
            f"""
            open({str(marker)!r}, "w").write("executed")

            @block
            def f(t: float, u: float) -> float:
                return u
            """
        )
        sim = Simulator(t_end=0.1, dt=0.01)
        c = sim.add(Constant(value=1.0, dtype="int64", id="c"))
        pf = sim.add(PythonFunction(code=code, id="pf"))
        sim.connect(c, pf)
        resp = client.post(ENDPOINT, json={"model": _model_dict(sim, tmp_path)})
        assert resp.status_code == 200
        assert not marker.exists(), "endpoint 経由で PythonFunction が exec された"
        body = resp.json()
        codes = [d["code"] for d in body["diagnostics"]]
        assert "dtype.static_fallback" in codes
        ports = {
            (p["block_id"], p["direction"], p["port_index"]): p["dtype"] for p in body["ports"]
        }
        assert ports[("pf", "out", 0)] == "unknown"
        assert ports[("c", "out", 0)] == "int64"  # static mode でも他は解決される

    def test_nested_python_function_is_200_and_never_executes(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        # MUST-1 (security-reviewer): JSON 復元経路 (Subsystem._from_dict の
        # eager _inner_blocks) を通ったネスト PythonFunction でも非実行を固定。
        from flode.subsystems import Inport, Outport, Subsystem

        marker = tmp_path / "executed.txt"
        code = textwrap.dedent(
            f"""
            open({str(marker)!r}, "w").write("executed")

            @block
            def f(t: float, u: float) -> float:
                return u
            """
        )
        sub = Subsystem(
            blocks=[
                Inport(port_idx=0, id="ip"),
                PythonFunction(code=code, id="pf"),
                Outport(port_idx=0, id="op"),
            ],
            connections=[
                {"src": "ip", "src_port": 0, "dst": "pf", "dst_port": 0},
                {"src": "pf", "src_port": 0, "dst": "op", "dst_port": 0},
            ],
            id="sub",
        )
        sim = Simulator(t_end=0.1, dt=0.01)
        c = sim.add(Constant(value=1.0, id="c"))
        sim.add(sub)
        sim.connect(c, sub)
        model = _model_dict(sim, tmp_path)
        # 既知の別バグ (v0.53.7 以前から): Simulator.save() (= _model_dict) が
        # ネスト PythonFunction を exec する。本テストの対象は endpoint なので
        # save 由来の marker はここで除去し、以降の再出現だけを検証する。
        if marker.exists():
            marker.unlink()
        resp = client.post(ENDPOINT, json={"model": model})
        assert resp.status_code == 200
        assert not marker.exists(), "ネスト PythonFunction が endpoint 経由で exec された"
        codes = [d["code"] for d in resp.json()["diagnostics"]]
        assert "dtype.static_fallback" in codes

    def test_malformed_json_body_is_400(self, client: TestClient) -> None:
        resp = client.post(
            ENDPOINT,
            content="{not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_summary_fields_are_present(self, client: TestClient, tmp_path: Path) -> None:
        sim = Simulator(t_end=0.1, dt=0.01)
        c = sim.add(Constant(value=2.7, id="c"))
        cast = sim.add(Cast(dtype="int64", id="cast"))
        sim.connect(c, cast)
        resp = client.post(ENDPOINT, json={"model": _model_dict(sim, tmp_path)})
        assert resp.status_code == 200
        summary = resp.json()["summary"]
        assert summary["total_ports"] == 3
        assert summary["by_dtype"] == {"float64": 2, "int64": 1}
        assert summary["unresolved"] == 0
        assert summary["non_float_ports"] == 1
