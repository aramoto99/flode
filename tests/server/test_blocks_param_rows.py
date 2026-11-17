"""ADR-0086: ``POST /api/v1/blocks/param-rows`` と registry の ``row_editor``。

ユーザーブロックの .py は ``tmp_path`` 配下のワークスペースに作る。読み込み状態の後始末と
``Path.home()`` の隔離は ``tests/server/conftest.py`` の autouse fixture が行う。
"""

from __future__ import annotations

import asyncio
import json
import textwrap
import threading
import tracemalloc
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

import flode.server.routes.blocks as blocks_routes
from flode.core.persistence import managed_block_types
from flode.server import create_app
from flode.server.routes.blocks import (
    MAX_CONCURRENT_PARAM_SEARCHES,
    MAX_PARAM_ROWS_BODY_BYTES,
    MAX_PARAM_ROWS_ITEM_CHARS,
    MAX_PARAM_ROWS_ITEMS,
    MAX_PARAM_ROWS_PARAMS_DEPTH,
    MAX_PARAM_ROWS_PARAMS_NODES,
    MAX_PARAM_ROWS_PARAMS_STRING_CHARS,
    PARAM_ROWS_BUSY_DETAIL,
    PARAM_ROWS_REMOTE_ERROR_DETAIL,
)
from flode.server.settings import Settings
from flode.userblocks import LoadRequest, load_blocks

URL = "/api/v1/blocks/param-rows"
BIN_TYPE = "flode_ws.bins.PartsBin"
GAIN_TYPE = "flode.blocks.mathops.Gain"

#: 部品箱。行エディタが呼ばれるたびに ``calls.txt`` に 1 行 (JSON) 足す (ユーザーコードが走った印)。
BIN = '''
import json
from pathlib import Path

from flode import Block

CALLS = Path(__file__).with_name("calls.txt")
STOCK = {"resistor": 10, "capacitor": 4, "relay": 1}


def _record(**kwargs):
    with CALLS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(kwargs) + "\\n")


class PartsBin(Block):
    """Parts bin."""

    block_dynamic_ports = True
    block_param_search = {"parts": "find_parts"}
    block_param_rows = {"parts": "edit_parts", "notes": "edit_broken"}

    def __init__(self, parts: list[str] = [], notes: list[str] = [], k: float = 1.0, **kwargs):
        super().__init__(n_inputs=len(parts), n_outputs=1, **kwargs)

    @classmethod
    def find_parts(cls, query, limit, current, **_):
        return {"columns": ["part"], "rows": []}

    @classmethod
    def edit_parts(cls, action, param, params, **kw):
        _record(action=action, param=param, params=params, **kw)
        match action:
            case "describe":
                rows = []
                for line in kw["rows"]:
                    name, _, part = line.partition(":")
                    part = part.strip()
                    error = None if part in STOCK else f"unknown part {part!r}"
                    rows.append({"cells": [name, part, STOCK.get(part)], "error": error})
                return {"columns": ["name", "part", "stock"], "rows": rows, "ports": "input"}
            case "form":
                return {
                    "variants": [
                        {"id": "part", "label": "Part", "fields": [
                            {"key": "name", "label": "Name", "kind": "text"},
                            {"key": "part", "label": "Part", "kind": "choice",
                             "options": [{"value": p} for p in STOCK]},
                        ]},
                        {"id": "kit", "label": "Kit", "fields": [
                            {"key": "parts", "label": "Parts", "kind": "pick"},
                        ]},
                    ],
                    "variant": "part",
                    "values": {"name": "r1"} if kw["row"] else {},
                }
            case "compose":
                if kw["variant"] == "kit":
                    return {"row": "kit: " + "+".join(kw["values"]["parts"])}
                return {"row": f"{kw['values']['name']}: {kw['values']['part']}"}
            case "search":
                rows = [
                    {"cells": [p, n], "value": p} for p, n in STOCK.items() if kw["query"] in p
                ]
                return {"columns": ["part", "stock"], "rows": rows}
            case _:
                return NotImplemented

    @staticmethod
    def edit_broken(action, param, params, **kw):
        _record(action=action)
        if action == "describe":
            raise ValueError("catalog is offline")
        if action == "form":
            return {"variants": [{"id": "a"}, {"id": "a"}], "variant": "a"}
        return NotImplemented

    def output(self, t, x, u):
        return u
'''


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "blocks").mkdir(parents=True)
    (ws / "blocks" / "bins.py").write_text(textwrap.dedent(BIN), encoding="utf-8")
    return ws


def _calls(workspace: Path) -> list[dict[str, Any]]:
    path = workspace / "blocks" / "calls.txt"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


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


_OMIT = object()


def _body(action: str = "describe", **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type_path": BIN_TYPE,
        "param": "parts",
        "action": action,
        "params": {"notes": [], "k": 1.0},
    }
    body.update(
        {
            "describe": {"rows": ["a: resistor"]},
            "form": {"row": None},
            "compose": {"variant": "part", "values": {"name": "b", "part": "relay"},
                        "rows": ["a: resistor"], "index": None},
            "search": {"field": "parts", "query": "r"},
        }.get(action, {})
    )  # fmt: skip
    body.update(overrides)
    return {k: v for k, v in body.items() if v is not _OMIT}


def _params_by_name(client: TestClient, type_path: str) -> dict[str, dict[str, Any]]:
    blocks = {b["type_path"]: b for b in client.get("/api/v1/blocks").json()["blocks"]}
    return {p["name"]: p for p in blocks[type_path]["params_spec"]}


class TestRegistry:
    def test_row_editor_only_on_declared_params(self, client: TestClient):
        params = _params_by_name(client, BIN_TYPE)

        assert params["parts"]["row_editor"] is True
        assert params["notes"]["row_editor"] is True
        assert "row_editor" not in params["k"]
        # 両方を宣言した引数は両方を宣言どおりに出す (ADR-0086 §4)
        assert params["parts"]["searchable"] is True
        assert "searchable" not in params["notes"]

    def test_builtin_payload_is_unchanged(self, client: TestClient):
        params = _params_by_name(client, GAIN_TYPE)

        assert all("row_editor" not in p for p in params.values())


class TestActions:
    def test_describe(self, client: TestClient, workspace: Path):
        resp = client.post(URL, json=_body(rows=["a: resistor", "b: gear"]))

        assert resp.status_code == 200, resp.json()
        assert resp.json() == {
            "columns": ["name", "part", "stock"],
            "rows": [
                {"cells": ["a", "resistor", 10], "error": None},
                {"cells": ["b", "gear", None], "error": "unknown part 'gear'"},
            ],
            "ports": "input",
        }
        assert _calls(workspace) == [
            {"action": "describe", "param": "parts", "params": {"notes": [], "k": 1.0},
             "rows": ["a: resistor", "b: gear"]}
        ]  # fmt: skip

    def test_form(self, client: TestClient, workspace: Path):
        resp = client.post(URL, json=_body("form", row="r1: resistor"))

        assert resp.status_code == 200, resp.json()
        assert resp.json() == {
            "variants": [
                {
                    "id": "part",
                    "label": "Part",
                    "fields": [
                        {"key": "name", "label": "Name", "kind": "text"},
                        {
                            "key": "part",
                            "label": "Part",
                            "kind": "choice",
                            "options": [
                                {"value": "resistor", "label": "resistor"},
                                {"value": "capacitor", "label": "capacitor"},
                                {"value": "relay", "label": "relay"},
                            ],
                        },
                    ],
                },
                {
                    "id": "kit",
                    "label": "Kit",
                    "fields": [{"key": "parts", "label": "Parts", "kind": "pick"}],
                },
            ],
            "variant": "part",
            "values": {"name": "r1", "part": "resistor"},
        }
        assert _calls(workspace)[0]["row"] == "r1: resistor"

    def test_form_without_row(self, client: TestClient, workspace: Path):
        resp = client.post(URL, json=_body("form", row=_OMIT))

        assert resp.status_code == 200
        assert resp.json()["values"] == {"name": "", "part": "resistor"}
        assert _calls(workspace)[0]["row"] is None

    def test_compose(self, client: TestClient, workspace: Path):
        resp = client.post(URL, json=_body("compose", index=0))

        assert resp.status_code == 200, resp.json()
        assert resp.json() == {"row": "b: relay"}
        call = _calls(workspace)[0]
        assert (call["variant"], call["values"], call["rows"], call["index"]) == (
            "part",
            {"name": "b", "part": "relay"},
            ["a: resistor"],
            0,
        )

    def test_compose_with_pick_values(self, client: TestClient):
        resp = client.post(
            URL, json=_body("compose", variant="kit", values={"parts": ["relay", "resistor"]})
        )

        assert resp.status_code == 200
        assert resp.json() == {"row": "kit: relay+resistor"}

    def test_search(self, client: TestClient, workspace: Path):
        resp = client.post(URL, json=_body("search", query="  re ", limit=1))

        assert resp.status_code == 200, resp.json()
        assert resp.json() == {
            "columns": ["part", "stock"],
            "rows": [{"cells": ["resistor", 10], "value": "resistor"}],
            "truncated": True,
        }
        call = _calls(workspace)[0]
        assert (call["field"], call["query"], call["limit"]) == ("parts", "re", 1)

    def test_search_default_limit(self, client: TestClient, workspace: Path):
        client.post(URL, json=_body("search"))

        assert _calls(workspace)[0]["limit"] == 200

    def test_params_are_filtered_on_the_server(self, client: TestClient, workspace: Path):
        resp = client.post(
            URL, json=_body(params={"parts": ["x"], "k": 2, "data_file": "/etc/passwd"})
        )

        assert resp.status_code == 200
        assert _calls(workspace)[0]["params"] == {"k": 2}

    def test_empty_and_unicode_strings_are_accepted(self, client: TestClient, workspace: Path):
        # 空の行・空の値は許す (改行・制御文字だけを断る)
        described = client.post(URL, json=_body(rows=["", "a: résistor ☃"]))
        composed = client.post(
            URL, json=_body("compose", values={"name": "", "part": "relay"}, rows=[""])
        )

        assert described.status_code == 200, described.json()
        assert composed.status_code == 200, composed.json()
        assert composed.json() == {"row": ": relay"}

    def test_get_is_405(self, client: TestClient):
        resp = client.get(URL)

        assert resp.status_code == 405
        assert "POST" in resp.json()["detail"]


class TestNotFound:
    @pytest.mark.parametrize(
        ("type_path", "param"),
        [
            (GAIN_TYPE, "k"),
            ("flode_ws.bins.NoSuchBlock", "parts"),
            (BIN_TYPE, "k"),
            (BIN_TYPE, "no_such_param"),
        ],
    )
    def test_404(self, client: TestClient, workspace: Path, type_path: str, param: str):
        resp = client.post(URL, json=_body(type_path=type_path, param=param))

        assert resp.status_code == 404
        assert isinstance(resp.json()["detail"], str)
        assert _calls(workspace) == []

    def test_disabled_user_blocks_never_run_user_code(
        self, workspace: Path, make_client: Callable[[Settings], TestClient], mocker: MockerFixture
    ):
        load_blocks(workspace)
        assert BIN_TYPE in managed_block_types()
        client = make_client(_settings(workspace, user_blocks_enabled=False))
        spy = mocker.spy(blocks_routes, "param_rows")

        resp = client.post(URL, json=_body())

        assert resp.status_code == 404
        spy.assert_not_called()
        assert _calls(workspace) == []


def _deep(depth: int) -> Any:
    value: Any = 1
    for _ in range(depth):
        value = [value]
    return value


class TestBadRequest:
    @pytest.mark.parametrize(
        ("body", "fragment"),
        [
            ([], "JSON object"),
            (_body(type_path=_OMIT), "type_path"),
            (_body(param=3), "param"),
            (_body(action="delete"), "action"),
            (_body(action=_OMIT), "action"),
            (_body(params=_OMIT), "params"),
            (_body(params=[1]), "params"),
            # params 自身が深さ 1。入れ子の list が 16 段 = 深さ 17
            (_body(params={"k": _deep(MAX_PARAM_ROWS_PARAMS_DEPTH)}), "deeper"),
            (
                _body(params={"k": list(range(MAX_PARAM_ROWS_PARAMS_NODES))}),
                "more than",
            ),
            (
                _body(params={"k": "x" * (MAX_PARAM_ROWS_PARAMS_STRING_CHARS + 1)}),
                "characters",
            ),
            (_body(rows=_OMIT), "rows"),
            (_body(rows="a"), "rows"),
            (_body(rows=["a", 1]), "rows[1]"),
            (_body(rows=["a"] * (MAX_PARAM_ROWS_ITEMS + 1)), "rows"),
            (_body(rows=["a" * (MAX_PARAM_ROWS_ITEM_CHARS + 1)]), "rows[0]"),
            (_body("form", row=3), "row"),
            (_body("form", row="r" * (MAX_PARAM_ROWS_ITEM_CHARS + 1)), "row"),
            (_body("compose", variant=""), "variant"),
            (_body("compose", variant="v" * 65), "variant"),
            (_body("compose", values=[]), "values"),
            (_body("compose", values={f"k{i}": "" for i in range(17)}), "values"),
            (_body("compose", values={"": "x"}), "values"),
            (_body("compose", values={"k" * 65: "x"}), "values"),
            (_body("compose", values={"a": 1}), "values['a']"),
            (_body("compose", values={"a": "x" * 1001}), "values['a']"),
            (_body("compose", values={"a": ["x"] * 129}), "values['a']"),
            (_body("compose", values={"a": ["x", 2]}), "values['a'][1]"),
            (_body("compose", index=1), "index"),
            (_body("compose", index=-1), "index"),
            (_body("compose", index=True), "index"),
            (_body("compose", index=0.0), "index"),
            (_body("compose", rows=_OMIT), "rows"),
            (_body("search", field=""), "field"),
            (_body("search", field=_OMIT), "field"),
            (_body("search", query=""), "query"),
            (_body("search", query="   "), "query"),
            (_body("search", query="q" * 257), "query"),
            (_body("search", limit="10"), "limit"),
            (_body("search", limit=True), "limit"),
            # ユーザーコードに渡す文字列は 1 行・制御文字なし (security NIT-1)
            (_body(rows=["a: resistor", "b\nc"]), "rows[1]"),
            (_body(rows=["a\r"]), "rows[0]"),
            (_body(rows=["a "]), "rows[0]"),
            (_body(rows=["a\x00b"]), "rows[0]"),
            (_body("form", row="r1\n: resistor"), "row"),
            (_body("form", row="r1\x85"), "row"),
            (_body("compose", values={"name": "b\n", "part": "relay"}), "values['name']"),
            (_body("compose", values={"parts": ["relay", "x\x1b"]}), "values['parts'][1]"),
            (_body("compose", values={"na\nme": "b"}), "values"),
            (_body("compose", rows=["a "]), "rows[0]"),
            (_body("compose", variant="part\n"), "variant"),
            (_body("search", field="parts\t"), "field"),
            (_body("search", query="re\x00sistor"), "query"),
        ],
    )
    def test_invalid_body(self, client: TestClient, workspace: Path, body: Any, fragment: str):
        resp = client.post(URL, json=body)

        assert resp.status_code == 400, resp.json()
        assert fragment in resp.json()["detail"]
        assert _calls(workspace) == []

    def test_params_at_the_depth_limit_are_accepted(self, client: TestClient):
        resp = client.post(URL, json=_body(params={"k": _deep(MAX_PARAM_ROWS_PARAMS_DEPTH - 1)}))

        assert resp.status_code == 200, resp.json()

    def test_invalid_json(self, client: TestClient):
        resp = client.post(URL, content=b"{", headers={"content-type": "application/json"})

        assert resp.status_code == 400

    @pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
    def test_nan_and_infinity_are_400(self, client: TestClient, workspace: Path, constant: str):
        content = json.dumps(_body(params={"k": 1.0})).replace("1.0", constant)
        resp = client.post(URL, content=content, headers={"content-type": "application/json"})

        assert resp.status_code == 400
        assert constant in resp.json()["detail"]
        assert _calls(workspace) == []

    def test_large_flat_array_in_params_is_400(self, client: TestClient, workspace: Path):
        # security SHOULD-1: 本文の上限に収まる平らな配列 (約 200 万要素)
        n = (MAX_PARAM_ROWS_BODY_BYTES - 1024) // 2
        content = b'{"type_path": "%s", "param": "parts", "action": "describe", "rows": [], ' % (
            BIN_TYPE.encode()
        )
        content += b'"params": {"k": [' + b"0," * (n - 1) + b"0]}}"
        assert len(content) <= MAX_PARAM_ROWS_BODY_BYTES
        resp = client.post(URL, content=content, headers={"content-type": "application/json"})

        assert resp.status_code == 400
        assert "more than" in resp.json()["detail"]
        assert _calls(workspace) == []

    def test_params_check_rejects_before_pushing_a_wide_container(self):
        # 予算を超える入れ物は積む前に断る (積んでから数えると 200 万個の tuple を作る)
        wide = {"k": [0] * 2_000_000, "d": {}}
        tracemalloc.start()
        try:
            with pytest.raises(HTTPException) as exc_info:
                blocks_routes._check_param_rows_params(wide)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        assert exc_info.value.status_code == 400
        assert peak < 1024 * 1024

    def test_params_check_counts_dict_entries_twice(self):
        # dict はキーと値の 2 つずつ数える
        half = MAX_PARAM_ROWS_PARAMS_NODES // 2
        with pytest.raises(HTTPException, match="more than"):
            blocks_routes._check_param_rows_params({"k": {str(i): 0 for i in range(half)}})

    def test_body_is_parsed_and_validated_off_the_event_loop(
        self, client: TestClient, mocker: MockerFixture
    ):
        spy = mocker.spy(blocks_routes, "run_in_threadpool")

        resp = client.post(URL, json=_body())

        assert resp.status_code == 200
        called = [c.args[0] for c in spy.call_args_list]
        assert blocks_routes._loads_json in called
        assert blocks_routes._validated_param_rows_body in called

    def test_client_disconnect_while_reading_is_400(self):
        async def receive() -> dict[str, Any]:
            return {"type": "http.disconnect"}

        scope = {"type": "http", "method": "POST", "path": URL, "headers": []}
        request = Request(scope, receive)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(blocks_routes._read_limited_json(request))

        assert exc_info.value.status_code == 400
        assert "disconnected" in exc_info.value.detail

    def test_very_deep_json_is_400_not_500(self, client: TestClient, workspace: Path):
        depth = 100_000
        content = b'{"params": ' + b"[" * depth + b"]" * depth + b"}"
        resp = client.post(URL, content=content, headers={"content-type": "application/json"})

        assert resp.status_code == 400
        assert _calls(workspace) == []

    def test_too_large_body(self, client: TestClient, workspace: Path):
        padding = "x" * (MAX_PARAM_ROWS_BODY_BYTES + 1)
        resp = client.post(
            URL,
            content=json.dumps(_body(params={"k": padding})),
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

    def test_user_exception_is_400(self, client: TestClient):
        resp = client.post(URL, json=_body(param="notes", rows=[]))

        assert resp.status_code == 400
        assert resp.json()["detail"] == "ValueError: catalog is offline"

    def test_invalid_result_is_400(self, client: TestClient):
        resp = client.post(URL, json=_body("form", param="notes"))

        assert resp.status_code == 400
        assert resp.json()["detail"] == (
            "the row editor returned an invalid result for action 'form': "
            "variants[1].id 'a' appears more than once"
        )

    def test_not_implemented_is_400(self, client: TestClient):
        resp = client.post(URL, json=_body("search", param="notes"))

        assert resp.status_code == 400
        assert resp.json()["detail"] == (
            "the block does not support action 'search' for parameter 'notes'"
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
        assert resp.json()["detail"] == PARAM_ROWS_BUSY_DETAIL
        assert _calls(workspace) == []

    @pytest.mark.parametrize("body", [_body(), _body(param="notes", rows=[])])
    def test_slot_is_released_after_each_call(self, client: TestClient, body: dict[str, Any]):
        client.post(URL, json=body)

        semaphore: threading.BoundedSemaphore = client.app.state.param_search_semaphore
        taken = [semaphore.acquire(blocking=False) for _ in range(MAX_CONCURRENT_PARAM_SEARCHES)]
        for ok in taken:
            if ok:
                semaphore.release()
        assert all(taken)


class TestNonLoopback:
    def test_exception_text_is_hidden(
        self, workspace: Path, make_client: Callable[[Settings], TestClient]
    ):
        client = make_client(
            _settings(workspace, loopback_bind=False, user_blocks_reload_allowed=False)
        )

        raised = client.post(URL, json=_body(param="notes", rows=[]))
        invalid = client.post(URL, json=_body("form", param="notes"))
        described = client.post(URL, json=_body(rows=["b: gear"]))

        assert raised.status_code == 400
        assert raised.json()["detail"] == PARAM_ROWS_REMOTE_ERROR_DETAIL
        assert "catalog is offline" not in raised.text
        # flode 自身の検証文とブロックが返したデータはそのまま
        assert invalid.json()["detail"].startswith("the row editor returned an invalid result")
        assert described.json()["rows"][0]["error"] == "unknown part 'gear'"
