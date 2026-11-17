"""ADR-0085: ``POST /api/v1/blocks/search-param-values`` と registry の ``searchable``。

ユーザーブロックの .py は ``tmp_path`` 配下のワークスペースに作る。読み込み状態の後始末と
``Path.home()`` の隔離は ``tests/server/conftest.py`` の autouse fixture が行う。
"""

from __future__ import annotations

import json
import textwrap
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

import flode.server.routes.blocks as blocks_routes
from flode.core.persistence import managed_block_types
from flode.server import create_app
from flode.server.routes.blocks import (
    MAX_CONCURRENT_PARAM_SEARCHES,
    MAX_PARAM_ROWS_BODY_BYTES,
    MAX_PARAM_SEARCH_CURRENT_ITEM_CHARS,
    MAX_PARAM_SEARCH_CURRENT_ITEMS,
    MAX_PARAM_SEARCH_PARAM_CHARS,
    MAX_PARAM_SEARCH_QUERY_CHARS,
    MAX_PARAM_SEARCH_TYPE_PATH_CHARS,
    PARAM_SEARCH_BUSY_DETAIL,
    PARAM_SEARCH_DEFAULT_LIMIT,
    PARAM_SEARCH_MAX_LIMIT,
    PARAM_SEARCH_REMOTE_ERROR_DETAIL,
)
from flode.server.settings import Settings
from flode.userblocks import LoadRequest, load_blocks

URL = "/api/v1/blocks/search-param-values"
CATALOG_TYPE = "flode_ws.parts.PartsCatalog"
GAIN_TYPE = "flode.blocks.mathops.Gain"

#: 部品カタログ。検索するたびに ``calls.txt`` に 1 行足す (ユーザーコードが走ったかの印)。
CATALOG = '''
from pathlib import Path

from flode import Block

CALLS = Path(__file__).with_name("calls.txt")
PARTS = [("resistor", 10), ("capacitor", 4), ("inductor", 2), ("relay", 1)]


class PartsCatalog(Block):
    """Parts catalog."""

    block_param_search = {"parts": "find_parts", "spares": "find_broken"}

    def __init__(self, parts: list[str] = [], spares: list[str] = [], k: float = 1.0, **kwargs):
        super().__init__(n_inputs=1, n_outputs=1, **kwargs)

    @classmethod
    def find_parts(cls, query, limit, current, **_):
        with CALLS.open("a", encoding="utf-8") as f:
            f.write(query + "\\n")
        taken = {line.split(":")[0] for line in current}
        rows = []
        for name, stock in PARTS:
            if query in name:
                label = name if name not in taken else name + "_2"
                rows.append({"cells": [name, stock, None], "value": f"{label}: {name}"})
        return {"columns": ["part", "stock", "note"], "rows": rows}

    @classmethod
    def find_broken(cls, query, limit, current, **_):
        if query == "raise":
            raise ValueError("catalog is offline")
        if query == "raise-surrogate":
            raise ValueError("bad \\ud800 text")
        if query == "surrogate-cell":
            return {"columns": ["a"], "rows": [{"cells": ["x\\ud800"], "value": "x"}]}
        if query == "surrogate-value":
            return {"columns": ["a"], "rows": [{"cells": ["x"], "value": "x\\ud800"}]}
        if query == "surrogate-column":
            return {"columns": ["a\\udc80"], "rows": []}
        return {"columns": ["a", "b"], "rows": [{"cells": ["only one"], "value": "x"}]}

    def output(self, t, x, u):
        return u
'''


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "blocks").mkdir(parents=True)
    (ws / "blocks" / "parts.py").write_text(textwrap.dedent(CATALOG), encoding="utf-8")
    return ws


def _calls(workspace: Path) -> list[str]:
    path = workspace / "blocks" / "calls.txt"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _settings(workspace: Path, **overrides: Any) -> Settings:
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


@pytest.fixture
def client(workspace: Path, make_client: Callable[[Settings], TestClient]) -> TestClient:
    return make_client(_settings(workspace))


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type_path": CATALOG_TYPE,
        "param": "parts",
        "query": "r",
        "current": [],
    }
    body.update(overrides)
    return {k: v for k, v in body.items() if v is not _OMIT}


_OMIT = object()


def _params_by_name(client: TestClient, type_path: str) -> dict[str, dict[str, Any]]:
    blocks = {b["type_path"]: b for b in client.get("/api/v1/blocks").json()["blocks"]}
    return {p["name"]: p for p in blocks[type_path]["params_spec"]}


class TestRegistry:
    def test_searchable_only_on_declared_params(self, client: TestClient):
        params = _params_by_name(client, CATALOG_TYPE)

        assert params["parts"]["searchable"] is True
        assert params["spares"]["searchable"] is True
        assert "searchable" not in params["k"]

    def test_builtin_payload_is_unchanged(self, client: TestClient):
        params = _params_by_name(client, GAIN_TYPE)

        assert all("searchable" not in p for p in params.values())

    def test_single_block_endpoint_also_has_searchable(self, client: TestClient):
        body = client.get(f"/api/v1/blocks/{CATALOG_TYPE}").json()

        assert [p.get("searchable", False) for p in body["params_spec"]] == [True, True, False]


class TestSearch:
    def test_result_shape(self, client: TestClient, workspace: Path):
        resp = client.post(URL, json=_body(query="  r ", current=["resistor: resistor"]))

        assert resp.status_code == 200, resp.json()
        assert resp.json() == {
            "columns": ["part", "stock", "note"],
            "rows": [
                {"cells": ["resistor", 10, None], "value": "resistor_2: resistor"},
                {"cells": ["capacitor", 4, None], "value": "capacitor: capacitor"},
                {"cells": ["inductor", 2, None], "value": "inductor: inductor"},
                {"cells": ["relay", 1, None], "value": "relay: relay"},
            ],
            "truncated": False,
        }
        # 検索語は前後の空白を除いて渡す
        assert _calls(workspace) == ["r"]

    def test_truncated_when_more_than_limit(self, client: TestClient):
        resp = client.post(URL, json=_body(limit=2))

        assert resp.status_code == 200
        body = resp.json()
        assert [r["value"] for r in body["rows"]] == ["resistor: resistor", "capacitor: capacitor"]
        assert body["truncated"] is True

    @pytest.mark.parametrize(
        ("limit", "expected"),
        [
            (_OMIT, PARAM_SEARCH_DEFAULT_LIMIT),
            (None, PARAM_SEARCH_DEFAULT_LIMIT),
            (0, 1),
            (-5, 1),
            (7, 7),
            (10**9, PARAM_SEARCH_MAX_LIMIT),
        ],
    )
    def test_limit_is_clamped(
        self, client: TestClient, mocker: MockerFixture, limit: Any, expected: int
    ):
        spy = mocker.spy(blocks_routes, "search_param_values")

        resp = client.post(URL, json=_body(limit=limit))

        assert resp.status_code == 200
        assert spy.call_args.args[3] == expected

    def test_get_is_405(self, client: TestClient):
        resp = client.get(URL)

        assert resp.status_code == 405
        assert "POST" in resp.json()["detail"]


class TestNotFound:
    @pytest.mark.parametrize(
        ("type_path", "param"),
        [
            (GAIN_TYPE, "k"),
            ("flode_ws.parts.NoSuchBlock", "parts"),
            (CATALOG_TYPE, "k"),
            (CATALOG_TYPE, "no_such_param"),
        ],
    )
    def test_404(self, client: TestClient, workspace: Path, type_path: str, param: str):
        resp = client.post(URL, json=_body(type_path=type_path, param=param))

        assert resp.status_code == 404
        assert isinstance(resp.json()["detail"], str)
        assert _calls(workspace) == []

    def test_disabled_user_blocks_never_run_user_code(
        self, workspace: Path, make_client: Callable[[Settings], TestClient]
    ):
        client = make_client(_settings(workspace, user_blocks_enabled=False))

        resp = client.post(URL, json=_body())

        assert resp.status_code == 404
        assert _calls(workspace) == []
        assert CATALOG_TYPE not in {
            b["type_path"] for b in client.get("/api/v1/blocks").json()["blocks"]
        }


class TestBadRequest:
    @pytest.mark.parametrize(
        ("body", "fragment"),
        [
            ([], "JSON object"),
            (_body(type_path=_OMIT), "type_path"),
            (_body(type_path=""), "type_path"),
            (_body(param=3), "param"),
            (_body(query=_OMIT), "query"),
            (_body(query=["r"]), "query"),
            (_body(query=""), "must not be empty"),
            (_body(query="   "), "must not be empty"),
            (_body(query="r" * (MAX_PARAM_SEARCH_QUERY_CHARS + 1)), "query"),
            (_body(limit=True), "limit"),
            (_body(limit=2.5), "limit"),
            (_body(limit="10"), "limit"),
            (_body(current=_OMIT), "current"),
            (_body(current="a"), "current"),
            (_body(current=["a", 1]), "current[1]"),
            (_body(current=["a"] * (MAX_PARAM_SEARCH_CURRENT_ITEMS + 1)), "current"),
            (_body(current=["a" * (MAX_PARAM_SEARCH_CURRENT_ITEM_CHARS + 1)]), "current[0]"),
        ],
    )
    def test_invalid_body(self, client: TestClient, workspace: Path, body: Any, fragment: str):
        resp = client.post(URL, json=body)

        assert resp.status_code == 400
        assert fragment in resp.json()["detail"]
        assert _calls(workspace) == []

    def test_invalid_json(self, client: TestClient):
        resp = client.post(URL, content=b"{", headers={"content-type": "application/json"})

        assert resp.status_code == 400

    def test_very_deep_json_is_400_not_500(self, client: TestClient, workspace: Path):
        # security SHOULD-2: request.json() の RecursionError が 500 になっていた
        depth = 100_000
        content = b'{"current": ' + b"[" * depth + b"]" * depth + b"}"
        resp = client.post(URL, content=content, headers={"content-type": "application/json"})

        assert resp.status_code == 400
        assert _calls(workspace) == []

    def test_too_large_body(self, client: TestClient, workspace: Path):
        padding = "x" * (MAX_PARAM_ROWS_BODY_BYTES + 1)
        resp = client.post(
            URL,
            content=json.dumps(_body(pad=padding)),
            headers={"content-type": "application/json"},
        )

        assert resp.status_code == 400
        assert "bytes" in resp.json()["detail"]
        assert _calls(workspace) == []

    def test_too_large_body_without_content_length(self, client: TestClient, workspace: Path):
        padding = b"x" * (MAX_PARAM_ROWS_BODY_BYTES + 1)

        def chunks() -> Iterator[bytes]:
            yield b'{"pad": "'
            yield padding
            yield b'"}'

        resp = client.post(URL, content=chunks(), headers={"content-type": "application/json"})

        assert resp.status_code == 400
        assert "bytes" in resp.json()["detail"]
        assert _calls(workspace) == []

    @pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
    def test_nan_and_infinity_are_400(self, client: TestClient, workspace: Path, constant: str):
        content = json.dumps(_body()).encode()[:-1] + f', "x": {constant}}}'.encode()
        resp = client.post(URL, content=content, headers={"content-type": "application/json"})

        assert resp.status_code == 400
        assert constant in resp.json()["detail"]
        assert _calls(workspace) == []

    def test_user_exception_is_400(self, client: TestClient):
        resp = client.post(URL, json=_body(param="spares", query="raise"))

        assert resp.status_code == 400
        assert resp.json()["detail"] == "ValueError: catalog is offline"

    def test_invalid_result_is_400(self, client: TestClient):
        resp = client.post(URL, json=_body(param="spares", query="x"))

        assert resp.status_code == 400
        assert resp.json()["detail"] == (
            "the search function returned an invalid result: "
            "rows[0].cells has 1 cells but there are 2 columns"
        )


class TestConcurrencyLimit:
    def test_409_when_all_slots_are_taken(self, client: TestClient, workspace: Path):
        semaphore: threading.BoundedSemaphore = client.app.state.param_search_semaphore
        for _ in range(MAX_CONCURRENT_PARAM_SEARCHES):
            assert semaphore.acquire(blocking=False)
        try:
            resp = client.post(URL, json=_body())
        finally:
            for _ in range(MAX_CONCURRENT_PARAM_SEARCHES):
                semaphore.release()

        assert resp.status_code == 409
        assert resp.json()["detail"] == PARAM_SEARCH_BUSY_DETAIL
        assert _calls(workspace) == []

    @pytest.mark.parametrize("body", [_body(), _body(param="spares", query="raise")])
    def test_slot_is_released_after_each_search(self, client: TestClient, body: dict[str, Any]):
        client.post(URL, json=body)

        semaphore: threading.BoundedSemaphore = client.app.state.param_search_semaphore
        taken = [semaphore.acquire(blocking=False) for _ in range(MAX_CONCURRENT_PARAM_SEARCHES)]
        for ok in taken:
            if ok:
                semaphore.release()
        assert all(taken)


class TestHardening:
    """code-reviewer / security-reviewer の指摘への回帰テスト。"""

    def test_disabled_settings_reject_even_with_a_filled_type_table(
        self, workspace: Path, make_client: Callable[[Settings], TestClient]
    ):
        # Python API で管理型表を埋めた後に、ユーザーブロック無効の app を作る
        load_blocks(workspace)
        client = make_client(_settings(workspace, user_blocks_enabled=False))
        assert CATALOG_TYPE in managed_block_types()

        resp = client.post(URL, json=_body())

        assert resp.status_code == 404
        assert _calls(workspace) == []

    def test_non_loopback_hides_the_exception_text(
        self, workspace: Path, make_client: Callable[[Settings], TestClient]
    ):
        client = make_client(
            _settings(workspace, loopback_bind=False, user_blocks_reload_allowed=False)
        )

        raised = client.post(URL, json=_body(param="spares", query="raise"))
        invalid = client.post(URL, json=_body(param="spares", query="x"))

        assert raised.status_code == 400
        assert raised.json()["detail"] == PARAM_SEARCH_REMOTE_ERROR_DETAIL
        # flode 自身の検証メッセージはそのまま
        assert invalid.status_code == 400
        assert invalid.json()["detail"].startswith(
            "the search function returned an invalid result: "
        )

    @pytest.mark.parametrize(
        ("query", "status", "check"),
        [
            ("raise-surrogate", 400, lambda b: b["detail"] == "ValueError: bad ? text"),
            ("surrogate-cell", 200, lambda b: b["rows"][0]["cells"] == ["x?"]),
            ("surrogate-value", 400, lambda b: "lone surrogate" in b["detail"]),
            ("surrogate-column", 400, lambda b: "lone surrogate" in b["detail"]),
        ],
    )
    def test_lone_surrogates_never_cause_500(
        self, client: TestClient, query: str, status: int, check: Callable[[Any], bool]
    ):
        resp = client.post(URL, json=_body(param="spares", query=query))

        assert resp.status_code == status
        assert check(resp.json())

    @pytest.mark.parametrize(
        ("body", "fragment"),
        [
            (_body(type_path="t" * (MAX_PARAM_SEARCH_TYPE_PATH_CHARS + 1)), "type_path"),
            (_body(param="p" * (MAX_PARAM_SEARCH_PARAM_CHARS + 1)), "param"),
        ],
    )
    def test_name_length_limits(self, client: TestClient, body: Any, fragment: str):
        resp = client.post(URL, json=body)

        assert resp.status_code == 400
        assert fragment in resp.json()["detail"]
