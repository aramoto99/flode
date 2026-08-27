"""CSRF guard (``flode/server/security/origin.py``) のテスト。

security-reviewer (v0.49.0): loopback bind でも、閲覧中の任意サイトの JS が
``Content-Type: text/plain`` の simple request で start API を叩けると、
PythonFunction 経由で任意コード実行になる。純関数の真理値表 + TestClient 統合の両方で固定する。
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flode import Simulator
from flode.blocks import Constant, PythonFunction, Scope
from flode.server import create_app
from flode.server.security.origin import (
    check_state_changing_request,
    is_unspoofable_host,
)
from flode.server.settings import Settings

# ---------------------------------------------------------------------------
# 純関数
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("localhost", True),
        ("LOCALHOST", True),
        ("::1", True),
        ("[::1]", True),
        ("192.168.1.5", True),  # IP リテラルは rebinding で偽装できない
        ("evil.example", False),
        ("mypc.local", False),
        ("localhost.evil.example", False),
        ("", False),
    ],
)
def test_is_unspoofable_host(host: str, expected: bool) -> None:
    assert is_unspoofable_host(host) is expected


def _check(**kw):
    base = {
        "method": "POST",
        "origin": None,
        "host": "127.0.0.1:8770",
        "content_type": "application/json",
        "has_body": True,
        "allow_origins": [],
    }
    base.update(kw)
    return check_state_changing_request(**base)


class TestCheckStateChangingRequest:
    def test_get_is_never_rejected(self) -> None:
        assert (
            _check(method="GET", origin="https://evil.example", content_type="text/plain") is None
        )

    def test_json_without_origin_is_allowed(self) -> None:
        assert _check() is None

    def test_non_json_body_is_415(self) -> None:
        r = _check(content_type="text/plain;charset=UTF-8")
        assert r is not None and r.status_code == 415

    def test_missing_content_type_with_body_is_415(self) -> None:
        r = _check(content_type=None)
        assert r is not None and r.status_code == 415

    def test_no_body_skips_content_type_check(self) -> None:
        assert _check(content_type=None, has_body=False) is None

    def test_json_with_charset_is_ok(self) -> None:
        assert _check(content_type="application/json; charset=utf-8") is None

    def test_cross_origin_is_403(self) -> None:
        r = _check(origin="https://evil.example")
        assert r is not None and r.status_code == 403

    def test_null_origin_is_403(self) -> None:
        r = _check(origin="null")
        assert r is not None and r.status_code == 403

    def test_same_origin_loopback_is_allowed(self) -> None:
        assert _check(origin="http://127.0.0.1:8770") is None
        assert _check(origin="http://localhost:8770", host="localhost:8770") is None
        assert _check(origin="http://[::1]:8770", host="[::1]:8770") is None

    def test_same_origin_lan_ip_is_allowed(self) -> None:
        assert _check(origin="http://192.168.1.5:8770", host="192.168.1.5:8770") is None

    def test_same_origin_hostname_is_rejected_unless_allowlisted(self) -> None:
        # DNS rebinding: evil.example → 127.0.0.1 だと Origin == Host になるが通さない
        r = _check(origin="http://evil.example:8770", host="evil.example:8770")
        assert r is not None and r.status_code == 403
        assert "rebinding" in r.detail
        assert (
            _check(
                origin="http://mypc.local:8770",
                host="mypc.local:8770",
                allow_origins=["http://mypc.local:8770"],
            )
            is None
        )

    def test_allow_origins_permits_dev_server(self) -> None:
        assert (
            _check(origin="http://127.0.0.1:5173", allow_origins=["http://127.0.0.1:5173"]) is None
        )

    def test_malformed_origin_is_403(self) -> None:
        r = _check(origin="not a url")
        assert r is not None and r.status_code == 403

    @pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
    def test_other_state_changing_methods_are_guarded(self, method: str) -> None:
        r = _check(method=method, origin="https://evil.example")
        assert r is not None and r.status_code == 403


# ---------------------------------------------------------------------------
# TestClient 統合 (= middleware が実際に効くこと)
# ---------------------------------------------------------------------------


def _seed_marker_model(workspace: Path, marker: Path) -> str:
    code = textwrap.dedent(
        f"""
        open({str(marker)!r}, "w").write("pwned")

        @block
        def f(t: float, u: float) -> float:
            return u
        """
    )
    sim = Simulator(t_end=0.05, dt=0.01)
    sim.add(Constant(value=1.0, id="src"))
    sim.add(PythonFunction(code=code, id="pf"))
    sim.add(Scope(n_inputs=1, id="scope"))
    sim.connect("src", "pf")
    sim.connect("pf", "scope")
    sim.save(workspace / "csrf.flw.json")
    return "csrf.flw.json"


class TestMiddleware:
    def test_simple_request_from_evil_origin_is_blocked_before_execution(
        self, tmp_path: Path
    ) -> None:
        marker = tmp_path / "pwned.txt"
        path = _seed_marker_model(tmp_path, marker)
        app = create_app(settings=Settings(workspace_root=tmp_path))
        with TestClient(app, base_url="http://127.0.0.1") as client:
            body = json.dumps({"model_path": path, "python_ack": "0" * 64})
            # ブラウザの no-cors fetch が送れる simple request の形
            r = client.post(
                "/api/v1/simulations",
                content=body,
                headers={
                    "Content-Type": "text/plain;charset=UTF-8",
                    "Origin": "https://evil.example",
                },
            )
            assert r.status_code == 415
            # preflight 付きで JSON を送れたとしても Origin で 403
            r = client.post(
                "/api/v1/simulations",
                content=body,
                headers={"Content-Type": "application/json", "Origin": "https://evil.example"},
            )
            assert r.status_code == 403
            assert "Cross-origin" in r.json()["detail"]
        assert not marker.exists()

    def test_same_origin_and_non_browser_requests_pass(self, tmp_path: Path) -> None:
        app = create_app(settings=Settings(workspace_root=tmp_path))
        payload = {
            "items": [
                {"key": "k", "code": "@block\ndef f(t: float, u: float) -> float:\n    return u\n"}
            ]
        }
        with TestClient(app, base_url="http://127.0.0.1") as client:
            # 非ブラウザ (Origin 無し)
            assert (
                client.post("/api/v1/blocks/python-function/introspect", json=payload).status_code
                == 200
            )
            # GUI と同じ same-origin
            r = client.post(
                "/api/v1/blocks/python-function/introspect",
                json=payload,
                headers={"Origin": "http://127.0.0.1"},
            )
            assert r.status_code == 200
            # GET は常に通る
            assert (
                client.get("/api/v1/blocks", headers={"Origin": "https://evil.example"}).status_code
                == 200
            )

    def test_allow_origins_setting_permits_configured_origin(self, tmp_path: Path) -> None:
        app = create_app(
            settings=Settings(workspace_root=tmp_path, allow_origins=["http://127.0.0.1:5173"])
        )
        payload = {"items": []}
        with TestClient(app, base_url="http://127.0.0.1") as client:
            r = client.post(
                "/api/v1/blocks/python-function/introspect",
                json=payload,
                headers={"Origin": "http://127.0.0.1:5173"},
            )
            assert r.status_code == 200
            r = client.post(
                "/api/v1/blocks/python-function/introspect",
                json=payload,
                headers={"Origin": "http://127.0.0.1:9999"},
            )
            assert r.status_code == 403


class TestPolicyViaSettings:
    def test_create_app_applies_python_blocks_policy(self, tmp_path: Path) -> None:
        from flode.blocks.pythonfunc import get_python_block_policy, set_python_block_policy

        try:
            create_app(
                settings=Settings(
                    workspace_root=tmp_path,
                    python_blocks_allowed=False,
                    python_blocks_reason="embedded",
                )
            )
            p = get_python_block_policy()
            assert p.allowed is False
            assert p.reason == "embedded"
            create_app(settings=Settings(workspace_root=tmp_path))
            assert get_python_block_policy().allowed is True
        finally:
            set_python_block_policy(allowed=True)
