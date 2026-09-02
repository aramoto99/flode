"""SPEC-0023 / ADR-0073: PythonFunction の REST 経路。

* ``POST /api/v1/blocks/python-function/introspect`` — 静的解析のみ (exec しない)
* ``POST /api/v1/simulations`` — soft gate (409 + digest echo) / hard gate (403)
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flode import Simulator
from flode.blocks import Constant, PythonFunction, Scope
from flode.blocks.pythonfunc import compute_python_digest, set_python_block_policy
from flode.server import create_app
from flode.server.settings import Settings


@pytest.fixture(autouse=True)
def _reset_policy():
    yield
    set_python_block_policy(allowed=True)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(settings=Settings(workspace_root=tmp_path))
    with TestClient(app) as c:
        yield c


GAIN_CODE = textwrap.dedent(
    """
    @block
    def gain(t: float, u: float, *, k: float = 2.0, label: str = "x") -> float:
        return k * u
    """
)


def _seed_pf_model(workspace: Path, code: str = GAIN_CODE, name: str = "pf") -> tuple[str, str]:
    sim = Simulator(t_end=0.05, dt=0.01)
    sim.add(Constant(value=1.0, id="src"))
    sim.add(PythonFunction(code=code, id="pf"))
    sim.add(Scope(n_inputs=1, id="scope"))
    sim.connect("src", "pf")
    sim.connect("pf", "scope")
    sim.save(workspace / f"{name}.flw.json")
    digest = compute_python_digest(sim)
    assert digest is not None
    return f"{name}.flw.json", digest


# ---------------------------------------------------------------------------
# introspect
# ---------------------------------------------------------------------------


class TestIntrospect:
    def test_resolves_structure_and_params_by_key(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/blocks/python-function/introspect",
            json={"items": [{"key": "b1", "code": GAIN_CODE}]},
        )
        assert resp.status_code == 200
        r = resp.json()["results"]["b1"]
        assert r["resolved"] is True
        assert r["func_name"] == "gain"
        assert (r["n_inputs"], r["n_outputs"], r["n_states"]) == (1, 1, 0)
        assert r["direct_feedthrough"] is True
        assert r["sample_time"] is None
        assert r["params_spec"] == [
            {
                "name": "k",
                "type": "float",
                "has_default": True,
                "default": 2.0,
                "enum_values": None,
                "description": "",
            },
            {
                "name": "label",
                "type": "str",
                "has_default": True,
                "default": "x",
                "enum_values": None,
                "description": "",
            },
        ]

    def test_partial_failure_is_reported_per_key(self, client: TestClient) -> None:
        bad = "@block\ndef f(t: float, u: float) -> float\n    return u\n"
        resp = client.post(
            "/api/v1/blocks/python-function/introspect",
            json={"items": [{"key": "ok", "code": GAIN_CODE}, {"key": "bad", "code": bad}]},
        )
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert results["ok"]["resolved"] is True
        assert results["bad"]["resolved"] is False
        err = results["bad"]["error"]
        assert err["kind"] == "syntax"
        assert err["lineno"] == 2
        assert "syntax error" in err["message"]

    def test_spec_error_carries_def_lineno(self, client: TestClient) -> None:
        code = "Vec = tuple[float, float]\n@block\ndef f(t: float, u: Vec) -> float:\n    return u[0]\n"
        resp = client.post(
            "/api/v1/blocks/python-function/introspect",
            json={"items": [{"key": "k", "code": code}]},
        )
        err = resp.json()["results"]["k"]["error"]
        assert err["kind"] == "spec"
        assert err["lineno"] == 3
        assert "inputs=N, outputs=M" in err["message"]

    def test_does_not_execute_user_code(self, client: TestClient, tmp_path: Path) -> None:
        marker = tmp_path / "executed.txt"
        code = f'open({str(marker)!r}, "w").write("x")\n\n@block\ndef f(t: float, u: float) -> float:\n    return u\n'
        resp = client.post(
            "/api/v1/blocks/python-function/introspect",
            json={"items": [{"key": "k", "code": code}]},
        )
        assert resp.status_code == 200
        assert resp.json()["results"]["k"]["resolved"] is True
        assert not marker.exists()

    @pytest.mark.parametrize(
        "body",
        [
            {"items": "nope"},
            {"items": [{"key": "", "code": "x"}]},
            {"items": [{"key": "k"}]},
            {"items": ["str"]},
            [],
        ],
    )
    def test_invalid_body_is_400(self, client: TestClient, body) -> None:
        resp = client.post("/api/v1/blocks/python-function/introspect", json=body)
        assert resp.status_code == 400

    def test_get_is_405_not_registry_lookup(self, client: TestClient) -> None:
        resp = client.get("/api/v1/blocks/python-function/introspect")
        assert resp.status_code == 405


# ---------------------------------------------------------------------------
# start API gates
# ---------------------------------------------------------------------------


class TestStartGates:
    def test_unconfirmed_returns_409_with_digest(self, client: TestClient, tmp_path: Path) -> None:
        path, digest = _seed_pf_model(tmp_path)
        resp = client.post("/api/v1/simulations", json={"model_path": path})
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["category"] == "python_function_unconfirmed"
        assert detail["template_key"] == "error.python_function_unconfirmed"
        assert detail["template_args"]["digest"] == digest
        assert detail["template_args"]["block_labels"] == ["pf"]
        assert detail["block_ids"] == ["pf"]
        assert detail["raw_traceback"] is None

    def test_wrong_ack_is_409(self, client: TestClient, tmp_path: Path) -> None:
        path, _ = _seed_pf_model(tmp_path)
        resp = client.post("/api/v1/simulations", json={"model_path": path, "python_ack": "0" * 64})
        assert resp.status_code == 409

    def test_matching_ack_starts(self, client: TestClient, tmp_path: Path) -> None:
        path, digest = _seed_pf_model(tmp_path)
        resp = client.post("/api/v1/simulations", json={"model_path": path, "python_ack": digest})
        assert resp.status_code == 200
        assert "simulation_id" in resp.json()

    def test_code_change_invalidates_ack(self, client: TestClient, tmp_path: Path) -> None:
        _, old_digest = _seed_pf_model(tmp_path, name="old")
        path, _ = _seed_pf_model(tmp_path, code=GAIN_CODE + "\n# edited\n", name="new")
        resp = client.post(
            "/api/v1/simulations", json={"model_path": path, "python_ack": old_digest}
        )
        assert resp.status_code == 409

    def test_model_without_python_ignores_ack(self, client: TestClient, tmp_path: Path) -> None:
        sim = Simulator(t_end=0.05, dt=0.01)
        sim.add(Constant(value=1.0, id="src"))
        sim.add(Scope(n_inputs=1, id="scope"))
        sim.connect("src", "scope")
        sim.save(tmp_path / "plain.flw.json")
        resp = client.post(
            "/api/v1/simulations", json={"model_path": "plain.flw.json", "python_ack": "junk"}
        )
        assert resp.status_code == 200

    def test_inline_model_also_gated(self, client: TestClient, tmp_path: Path) -> None:
        import json

        path, digest = _seed_pf_model(tmp_path)
        data = json.loads((tmp_path / path).read_text(encoding="utf-8"))
        resp = client.post("/api/v1/simulations", json={"model": data})
        assert resp.status_code == 409
        resp = client.post("/api/v1/simulations", json={"model": data, "python_ack": digest})
        assert resp.status_code == 200

    def test_disabled_policy_is_403_before_worker(self, client: TestClient, tmp_path: Path) -> None:
        path, digest = _seed_pf_model(tmp_path)
        set_python_block_policy(allowed=False, reason="bound to 0.0.0.0")
        resp = client.post("/api/v1/simulations", json={"model_path": path, "python_ack": digest})
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["category"] == "python_function_disabled"
        assert "allow-python-blocks" in detail["template_args"]["message"]
        assert detail["block_id"] == "pf"


class TestIntrospectLimits:
    def test_too_many_items_is_400(self, client: TestClient) -> None:
        from flode.server.routes.blocks import MAX_INTROSPECT_ITEMS

        items = [{"key": f"k{i}", "code": "x = 1"} for i in range(MAX_INTROSPECT_ITEMS + 1)]
        resp = client.post("/api/v1/blocks/python-function/introspect", json={"items": items})
        assert resp.status_code == 400
        assert str(MAX_INTROSPECT_ITEMS) in resp.json()["detail"]

    def test_oversized_code_is_400(self, client: TestClient) -> None:
        from flode.server.routes.blocks import MAX_INTROSPECT_CODE_CHARS

        code = "#" * (MAX_INTROSPECT_CODE_CHARS + 1)
        resp = client.post(
            "/api/v1/blocks/python-function/introspect",
            json={"items": [{"key": "k", "code": code}]},
        )
        assert resp.status_code == 400


class TestExecGateInsideLoader:
    def test_exec_block_source_itself_checks_policy(self) -> None:
        """不変条件 (a): 呼び出し側の規約に依存せず、ローダ自身が policy を見る。"""
        from flode.blocks.pythonfunc import exec_block_source
        from flode.exceptions import PythonBlocksDisabledError

        set_python_block_policy(allowed=False, reason="test")
        with pytest.raises(PythonBlocksDisabledError):
            exec_block_source(GAIN_CODE, block_id="pf")


# ---------------------------------------------------------------------------
# SPEC-0024: rewrite endpoint と introspect の後方互換拡張
# ---------------------------------------------------------------------------

SCALAR_CODE = "@block\ndef f(t: float, u: float) -> float:\n    return u\n"


class TestRewriteEndpoint:
    def test_applied_true_returns_code_and_spec(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/blocks/python-function/rewrite",
            json={"code": SCALAR_CODE, "edits": {"inputs": 2, "input_names": ["速度指令", ""]}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["applied"] is True
        assert "tuple[float, float]" in data["code"]
        assert 'input_names=("速度指令", "")' in data["code"]
        spec = data["spec"]
        assert spec["n_inputs"] == 2
        assert spec["input_names"] == ["速度指令", ""]
        assert spec["editable"]["inputs"] is True
        assert spec["editable"]["max_inputs"] == 32

    def test_applied_false_has_no_code_key(self, client: TestClient) -> None:
        # 名前列の長さ不一致はソース側の事情 → 200 + applied:false、code は返さない
        resp = client.post(
            "/api/v1/blocks/python-function/rewrite",
            json={"code": SCALAR_CODE, "edits": {"input_names": ["a", "b"]}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["applied"] is False
        assert "code" not in data
        assert data["error"]["kind"] == "spec"

    def test_no_u_function_is_applied_false(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/blocks/python-function/rewrite",
            json={
                "code": "@block\ndef f(t: float) -> float:\n    return t\n",
                "edits": {"inputs": 2},
            },
        )
        assert resp.json()["applied"] is False

    @pytest.mark.parametrize(
        "body",
        [
            {"code": SCALAR_CODE},  # edits なし
            {"code": SCALAR_CODE, "edits": {"inputs": 0}},
            {"code": SCALAR_CODE, "edits": {"inputs": 33}},
            {"code": SCALAR_CODE, "edits": {"inputs": True}},
            {"code": SCALAR_CODE, "edits": {"input_names": "ab"}},
            {"code": SCALAR_CODE, "edits": {"input_names": ["x" * 33]}},
            {"code": SCALAR_CODE, "edits": {"bogus": 1}},
            {"code": 123, "edits": {}},
        ],
    )
    def test_invalid_body_is_400(self, client: TestClient, body) -> None:
        resp = client.post("/api/v1/blocks/python-function/rewrite", json=body)
        assert resp.status_code == 400

    def test_oversized_code_is_400(self, client: TestClient) -> None:
        from flode.server.routes.blocks import MAX_INTROSPECT_CODE_CHARS

        resp = client.post(
            "/api/v1/blocks/python-function/rewrite",
            json={"code": "#" * (MAX_INTROSPECT_CODE_CHARS + 1), "edits": {"inputs": 2}},
        )
        assert resp.status_code == 400

    def test_get_is_405(self, client: TestClient) -> None:
        assert client.get("/api/v1/blocks/python-function/rewrite").status_code == 405

    def test_does_not_execute_user_code(self, client: TestClient, tmp_path: Path) -> None:
        marker = tmp_path / "executed.txt"
        code = f'open({str(marker)!r}, "w").write("x")\n\n@block\ndef f(t: float, u: float) -> float:\n    return u\n'
        resp = client.post(
            "/api/v1/blocks/python-function/rewrite",
            json={"code": code, "edits": {"inputs": 3}},
        )
        assert resp.status_code == 200
        assert resp.json()["applied"] is True
        assert not marker.exists()

    def test_cross_origin_is_blocked(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/blocks/python-function/rewrite",
            json={"code": SCALAR_CODE, "edits": {"inputs": 2}},
            headers={"Origin": "https://evil.example"},
        )
        assert resp.status_code == 403


class TestIntrospectBackwardCompat:
    def test_new_keys_added_old_keys_unchanged(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/blocks/python-function/introspect",
            json={"items": [{"key": "k", "code": SCALAR_CODE}]},
        )
        r = resp.json()["results"]["k"]
        # 旧キー (SPEC-0023) は全て健在
        for key in (
            "resolved",
            "func_name",
            "n_inputs",
            "n_outputs",
            "n_states",
            "direct_feedthrough",
            "sample_time",
            "params_spec",
        ):
            assert key in r
        # 新キー (SPEC-0024)
        assert r["input_names"] == []
        assert r["output_names"] == []
        assert r["editable"]["inputs"] is True
        assert r["editable"]["min_outputs"] == 1

    def test_editable_false_for_source_block(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/blocks/python-function/introspect",
            json={
                "items": [{"key": "k", "code": "@block\ndef s(t: float) -> float:\n    return t\n"}]
            },
        )
        r = resp.json()["results"]["k"]
        assert r["editable"]["inputs"] is False
        assert r["editable"]["min_inputs"] == 0


class TestRewriteSecurityHardening:
    def test_names_list_length_over_port_cap_is_400(self, client: TestClient) -> None:
        """security-reviewer SHOULD-2: 要素数もポート上限 (32) で 400。"""
        resp = client.post(
            "/api/v1/blocks/python-function/rewrite",
            json={"code": SCALAR_CODE, "edits": {"input_names": ["a"] * 33}},
        )
        assert resp.status_code == 400
        assert "at most 32" in resp.json()["detail"]
