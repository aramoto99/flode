"""File API endpoint テスト (ADR-0041 §論点 1-A、§論点 15-A)。

6 endpoint × 正常系 + 4xx + path traversal + etag 楽観ロック を網羅する。
``workspace_root`` 未設定時の 503 も検証。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pyflw.server import create_app
from pyflw.server.settings import Settings

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """空の workspace を返す。テスト本体で必要に応じてファイルを置く。"""
    return tmp_path


@pytest.fixture
def client(workspace: Path) -> TestClient:
    """``workspace_root=workspace`` で起動した ``TestClient``。"""
    settings = Settings(workspace_root=workspace)
    app = create_app(settings=settings)
    return TestClient(app)


def _seed_flw_json(workspace: Path, rel: str, content: dict | None = None) -> Path:
    """``rel`` の位置に minimal な ``.flw.json`` を作成して Path を返す。"""
    full = workspace / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(
        json.dumps(content or {"schema_version": "0.8", "blocks": []}, indent=2),
        encoding="utf-8",
    )
    return full


# ---------------------------------------------------------------------------
# GET /tree
# ---------------------------------------------------------------------------


class TestGetTree:
    def test_empty_workspace(self, client: TestClient) -> None:
        r = client.get("/api/v1/files/tree", params={"path": ""})
        assert r.status_code == 200
        body = r.json()
        assert body == {"path": "", "children": []}

    def test_workspace_with_files(self, client: TestClient, workspace: Path) -> None:
        _seed_flw_json(workspace, "alpha.flw.json")
        _seed_flw_json(workspace, "beta.flw.json")
        r = client.get("/api/v1/files/tree", params={"path": ""})
        assert r.status_code == 200
        names = [c["name"] for c in r.json()["children"]]
        assert names == ["alpha.flw.json", "beta.flw.json"]

    def test_directories_listed_before_files(self, client: TestClient, workspace: Path) -> None:
        (workspace / "controllers").mkdir()
        _seed_flw_json(workspace, "alpha.flw.json")
        r = client.get("/api/v1/files/tree", params={"path": ""})
        children = r.json()["children"]
        assert children[0]["type"] == "directory"
        assert children[0]["name"] == "controllers"
        assert children[1]["type"] == "file"

    def test_file_metadata_includes_size_and_mtime(
        self, client: TestClient, workspace: Path
    ) -> None:
        _seed_flw_json(workspace, "x.flw.json")
        r = client.get("/api/v1/files/tree", params={"path": ""})
        f = r.json()["children"][0]
        assert isinstance(f["size"], int) and f["size"] > 0
        assert f["mtime"].endswith("Z")
        # ISO 8601 format (= microseconds + Z)
        assert "T" in f["mtime"]

    def test_directory_metadata_size_is_null(self, client: TestClient, workspace: Path) -> None:
        (workspace / "subdir").mkdir()
        r = client.get("/api/v1/files/tree", params={"path": ""})
        d = r.json()["children"][0]
        assert d["size"] is None

    def test_subdir_listing(self, client: TestClient, workspace: Path) -> None:
        _seed_flw_json(workspace, "controllers/pid.flw.json")
        r = client.get("/api/v1/files/tree", params={"path": "controllers"})
        names = [c["name"] for c in r.json()["children"]]
        assert names == ["pid.flw.json"]

    def test_404_for_nonexistent_directory(self, client: TestClient) -> None:
        r = client.get("/api/v1/files/tree", params={"path": "ghost"})
        assert r.status_code == 404

    def test_400_for_file_path(self, client: TestClient, workspace: Path) -> None:
        _seed_flw_json(workspace, "x.flw.json")
        r = client.get("/api/v1/files/tree", params={"path": "x.flw.json"})
        assert r.status_code == 400

    def test_403_for_path_traversal(self, client: TestClient) -> None:
        r = client.get("/api/v1/files/tree", params={"path": "../escape"})
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /content
# ---------------------------------------------------------------------------


class TestGetContent:
    def test_returns_parsed_json(self, client: TestClient, workspace: Path) -> None:
        _seed_flw_json(workspace, "x.flw.json", {"schema_version": "0.8", "key": 42})
        r = client.get("/api/v1/files/content", params={"path": "x.flw.json"})
        assert r.status_code == 200
        body = r.json()
        assert body["path"] == "x.flw.json"
        assert body["content"] == {"schema_version": "0.8", "key": 42}
        assert body["mtime"].endswith("Z")
        assert body["etag"].startswith('W/"')

    def test_404_for_nonexistent(self, client: TestClient) -> None:
        r = client.get("/api/v1/files/content", params={"path": "ghost.flw.json"})
        assert r.status_code == 404

    def test_400_for_directory_path(self, client: TestClient, workspace: Path) -> None:
        (workspace / "subdir").mkdir()
        r = client.get("/api/v1/files/content", params={"path": "subdir"})
        assert r.status_code == 400

    def test_422_for_invalid_json(self, client: TestClient, workspace: Path) -> None:
        bad = workspace / "bad.flw.json"
        bad.write_text("not valid json {", encoding="utf-8")
        r = client.get("/api/v1/files/content", params={"path": "bad.flw.json"})
        assert r.status_code == 422

    def test_403_for_path_traversal(self, client: TestClient) -> None:
        r = client.get("/api/v1/files/content", params={"path": "../etc/passwd"})
        assert r.status_code == 403


class TestGetContentConditional:
    """条件付き GET (RFC 7232 If-None-Match)。

    外部変更検知の 5 秒ポーリングが etag 確認のためだけに全文ダウンロード
    しないための 304 対応 (frontend ``getFileContentIfChanged`` が利用)。
    """

    def test_200_response_includes_etag_header(self, client: TestClient, workspace: Path) -> None:
        _seed_flw_json(workspace, "x.flw.json")
        r = client.get("/api/v1/files/content", params={"path": "x.flw.json"})
        assert r.status_code == 200
        assert r.headers["etag"] == r.json()["etag"]

    def test_304_when_etag_matches(self, client: TestClient, workspace: Path) -> None:
        _seed_flw_json(workspace, "x.flw.json")
        etag = client.get("/api/v1/files/content", params={"path": "x.flw.json"}).json()["etag"]
        r = client.get(
            "/api/v1/files/content",
            params={"path": "x.flw.json"},
            headers={"If-None-Match": etag},
        )
        assert r.status_code == 304
        assert r.content == b""  # 本文なし
        assert r.headers["etag"] == etag

    def test_200_when_etag_stale(self, client: TestClient, workspace: Path) -> None:
        path = _seed_flw_json(workspace, "x.flw.json")
        etag = client.get("/api/v1/files/content", params={"path": "x.flw.json"}).json()["etag"]
        # 外部変更を模擬 (サイズ変更で etag が確実に変わる)
        path.write_text(
            json.dumps({"schema_version": "0.8", "blocks": [], "x": 1}),
            encoding="utf-8",
        )
        r = client.get(
            "/api/v1/files/content",
            params={"path": "x.flw.json"},
            headers={"If-None-Match": etag},
        )
        assert r.status_code == 200
        assert r.json()["content"]["x"] == 1
        assert r.json()["etag"] != etag

    def test_no_header_returns_200(self, client: TestClient, workspace: Path) -> None:
        _seed_flw_json(workspace, "x.flw.json")
        r = client.get("/api/v1/files/content", params={"path": "x.flw.json"})
        assert r.status_code == 200
        assert "content" in r.json()


# ---------------------------------------------------------------------------
# PUT /content
# ---------------------------------------------------------------------------


class TestPutContent:
    def test_creates_new_file(self, client: TestClient, workspace: Path) -> None:
        body = {"content": {"schema_version": "0.8", "blocks": []}}
        r = client.put("/api/v1/files/content", params={"path": "new.flw.json"}, json=body)
        assert r.status_code == 200
        assert (workspace / "new.flw.json").exists()
        assert (
            json.loads((workspace / "new.flw.json").read_text(encoding="utf-8")) == body["content"]
        )

    def test_overwrites_existing_without_etag(self, client: TestClient, workspace: Path) -> None:
        _seed_flw_json(workspace, "x.flw.json", {"v": 1})
        body = {"content": {"v": 2}}
        r = client.put("/api/v1/files/content", params={"path": "x.flw.json"}, json=body)
        assert r.status_code == 200
        loaded = json.loads((workspace / "x.flw.json").read_text(encoding="utf-8"))
        assert loaded == {"v": 2}

    def test_succeeds_with_matching_etag(self, client: TestClient, workspace: Path) -> None:
        _seed_flw_json(workspace, "x.flw.json", {"v": 1})
        # まず GET で etag を取得
        r1 = client.get("/api/v1/files/content", params={"path": "x.flw.json"})
        etag = r1.json()["etag"]
        body = {"content": {"v": 2}, "expected_etag": etag}
        r2 = client.put("/api/v1/files/content", params={"path": "x.flw.json"}, json=body)
        assert r2.status_code == 200

    def test_409_for_mismatched_etag(self, client: TestClient, workspace: Path) -> None:
        _seed_flw_json(workspace, "x.flw.json", {"v": 1})
        body = {"content": {"v": 2}, "expected_etag": 'W/"99-99"'}
        r = client.put("/api/v1/files/content", params={"path": "x.flw.json"}, json=body)
        assert r.status_code == 409
        detail = r.json()["detail"]
        assert "current_etag" in detail
        assert detail["message"].startswith("etag mismatch")

    def test_400_for_directory_path(self, client: TestClient, workspace: Path) -> None:
        (workspace / "subdir").mkdir()
        body = {"content": {"v": 1}}
        r = client.put("/api/v1/files/content", params={"path": "subdir"}, json=body)
        assert r.status_code == 400

    def test_auto_creates_parent_dir(self, client: TestClient, workspace: Path) -> None:
        body = {"content": {"v": 1}}
        r = client.put(
            "/api/v1/files/content",
            params={"path": "new/sub/dir/file.flw.json"},
            json=body,
        )
        assert r.status_code == 200
        assert (workspace / "new" / "sub" / "dir" / "file.flw.json").exists()

    def test_403_for_path_traversal(self, client: TestClient) -> None:
        body = {"content": {"v": 1}}
        r = client.put(
            "/api/v1/files/content",
            params={"path": "../escape.flw.json"},
            json=body,
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# POST /rename
# ---------------------------------------------------------------------------


class TestRename:
    def test_rename_file(self, client: TestClient, workspace: Path) -> None:
        _seed_flw_json(workspace, "old.flw.json")
        r = client.post(
            "/api/v1/files/rename",
            json={"from": "old.flw.json", "to": "new.flw.json"},
        )
        assert r.status_code == 200
        assert not (workspace / "old.flw.json").exists()
        assert (workspace / "new.flw.json").exists()

    def test_rename_directory(self, client: TestClient, workspace: Path) -> None:
        (workspace / "old_dir").mkdir()
        r = client.post(
            "/api/v1/files/rename",
            json={"from": "old_dir", "to": "new_dir"},
        )
        assert r.status_code == 200
        assert not (workspace / "old_dir").exists()
        assert (workspace / "new_dir").exists()

    def test_move_across_directories(self, client: TestClient, workspace: Path) -> None:
        _seed_flw_json(workspace, "src/file.flw.json")
        r = client.post(
            "/api/v1/files/rename",
            json={"from": "src/file.flw.json", "to": "dst/file.flw.json"},
        )
        assert r.status_code == 200
        assert (workspace / "dst" / "file.flw.json").exists()

    def test_404_for_nonexistent_source(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/files/rename",
            json={"from": "ghost.flw.json", "to": "new.flw.json"},
        )
        assert r.status_code == 404

    def test_409_for_existing_destination(self, client: TestClient, workspace: Path) -> None:
        _seed_flw_json(workspace, "a.flw.json")
        _seed_flw_json(workspace, "b.flw.json")
        r = client.post(
            "/api/v1/files/rename",
            json={"from": "a.flw.json", "to": "b.flw.json"},
        )
        assert r.status_code == 409

    def test_403_for_path_traversal_in_source(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/files/rename",
            json={"from": "../etc/passwd", "to": "new.flw.json"},
        )
        assert r.status_code == 403

    def test_403_for_path_traversal_in_destination(
        self, client: TestClient, workspace: Path
    ) -> None:
        _seed_flw_json(workspace, "x.flw.json")
        r = client.post(
            "/api/v1/files/rename",
            json={"from": "x.flw.json", "to": "../escape.flw.json"},
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /
# ---------------------------------------------------------------------------


class TestDelete:
    def test_delete_file(self, client: TestClient, workspace: Path) -> None:
        _seed_flw_json(workspace, "x.flw.json")
        r = client.delete("/api/v1/files", params={"path": "x.flw.json"})
        assert r.status_code == 204
        assert not (workspace / "x.flw.json").exists()

    def test_delete_empty_directory(self, client: TestClient, workspace: Path) -> None:
        (workspace / "empty").mkdir()
        r = client.delete("/api/v1/files", params={"path": "empty"})
        assert r.status_code == 204
        assert not (workspace / "empty").exists()

    def test_409_for_non_empty_directory(self, client: TestClient, workspace: Path) -> None:
        _seed_flw_json(workspace, "subdir/x.flw.json")
        r = client.delete("/api/v1/files", params={"path": "subdir"})
        assert r.status_code == 409
        assert (workspace / "subdir").exists()

    def test_404_for_nonexistent(self, client: TestClient) -> None:
        r = client.delete("/api/v1/files", params={"path": "ghost.flw.json"})
        assert r.status_code == 404

    def test_400_for_workspace_root_delete(self, client: TestClient) -> None:
        r = client.delete("/api/v1/files", params={"path": ""})
        assert r.status_code == 400

    def test_403_for_path_traversal(self, client: TestClient) -> None:
        r = client.delete("/api/v1/files", params={"path": "../escape"})
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# POST /mkdir
# ---------------------------------------------------------------------------


class TestMkdir:
    def test_creates_new_directory(self, client: TestClient, workspace: Path) -> None:
        # v0.31.4: 204 No Content (= delete と同じ pattern、201 + 空 body は
        # frontend `_fetch` の `response.json()` で「Unexpected end of JSON
        # input」エラーになっていたため統一)
        r = client.post("/api/v1/files/mkdir", params={"path": "new_dir"})
        assert r.status_code == 204
        assert (workspace / "new_dir").is_dir()

    def test_creates_nested_directory(self, client: TestClient, workspace: Path) -> None:
        r = client.post("/api/v1/files/mkdir", params={"path": "a/b/c"})
        assert r.status_code == 204
        assert (workspace / "a" / "b" / "c").is_dir()

    def test_409_for_existing_directory(self, client: TestClient, workspace: Path) -> None:
        (workspace / "existing").mkdir()
        r = client.post("/api/v1/files/mkdir", params={"path": "existing"})
        assert r.status_code == 409

    def test_409_for_existing_file(self, client: TestClient, workspace: Path) -> None:
        _seed_flw_json(workspace, "x.flw.json")
        r = client.post("/api/v1/files/mkdir", params={"path": "x.flw.json"})
        assert r.status_code == 409

    def test_400_for_workspace_root(self, client: TestClient) -> None:
        r = client.post("/api/v1/files/mkdir", params={"path": ""})
        assert r.status_code == 400

    def test_403_for_path_traversal(self, client: TestClient) -> None:
        r = client.post("/api/v1/files/mkdir", params={"path": "../escape"})
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# POST /copy (v0.31.9)
# ---------------------------------------------------------------------------


class TestCopy:
    def test_copies_file(self, client: TestClient, workspace: Path) -> None:
        _seed_flw_json(workspace, "src.flw.json")
        r = client.post("/api/v1/files/copy", params={"from": "src.flw.json", "to": "dst.flw.json"})
        assert r.status_code == 204
        assert (workspace / "src.flw.json").is_file()  # 元は残る
        assert (workspace / "dst.flw.json").is_file()

    def test_copies_directory_recursively(self, client: TestClient, workspace: Path) -> None:
        (workspace / "src_dir").mkdir()
        _seed_flw_json(workspace, "src_dir/a.flw.json")
        _seed_flw_json(workspace, "src_dir/b.flw.json")
        r = client.post("/api/v1/files/copy", params={"from": "src_dir", "to": "dst_dir"})
        assert r.status_code == 204
        assert (workspace / "dst_dir" / "a.flw.json").is_file()
        assert (workspace / "dst_dir" / "b.flw.json").is_file()

    def test_404_for_missing_source(self, client: TestClient) -> None:
        r = client.post("/api/v1/files/copy", params={"from": "nope.flw.json", "to": "x.flw.json"})
        assert r.status_code == 404

    def test_409_for_existing_destination(self, client: TestClient, workspace: Path) -> None:
        _seed_flw_json(workspace, "src.flw.json")
        _seed_flw_json(workspace, "dst.flw.json")
        r = client.post("/api/v1/files/copy", params={"from": "src.flw.json", "to": "dst.flw.json"})
        assert r.status_code == 409

    def test_400_for_same_source_and_destination(self, client: TestClient, workspace: Path) -> None:
        _seed_flw_json(workspace, "x.flw.json")
        r = client.post("/api/v1/files/copy", params={"from": "x.flw.json", "to": "x.flw.json"})
        assert r.status_code == 400

    def test_400_for_workspace_root_as_source(self, client: TestClient) -> None:
        r = client.post("/api/v1/files/copy", params={"from": "", "to": "anywhere"})
        assert r.status_code == 400

    def test_403_for_path_traversal_source(self, client: TestClient) -> None:
        r = client.post("/api/v1/files/copy", params={"from": "../escape", "to": "x"})
        assert r.status_code == 403

    def test_403_for_path_traversal_destination(self, client: TestClient, workspace: Path) -> None:
        _seed_flw_json(workspace, "x.flw.json")
        r = client.post("/api/v1/files/copy", params={"from": "x.flw.json", "to": "../escape"})
        assert r.status_code == 403

    def test_creates_destination_parent(self, client: TestClient, workspace: Path) -> None:
        _seed_flw_json(workspace, "src.flw.json")
        r = client.post(
            "/api/v1/files/copy", params={"from": "src.flw.json", "to": "new_dir/sub/dst.flw.json"}
        )
        assert r.status_code == 204
        assert (workspace / "new_dir" / "sub" / "dst.flw.json").is_file()


# ADR-0043 §論点 1-A / §論点 8-A: workspace_info endpoint
class TestWorkspaceInfo:
    def test_returns_absolute_path_and_hash(self, client: TestClient, workspace: Path) -> None:
        r = client.get("/api/v1/files/workspace_info")
        assert r.status_code == 200
        data = r.json()
        assert "absolute_path" in data
        assert "hash" in data
        assert isinstance(data["hash"], str)
        assert len(data["hash"]) == 16
        assert data["absolute_path"] == str(workspace.resolve())

    def test_hash_is_stable(self, client: TestClient) -> None:
        r1 = client.get("/api/v1/files/workspace_info").json()
        r2 = client.get("/api/v1/files/workspace_info").json()
        assert r1["hash"] == r2["hash"]


# ADR-0043 §論点 5: search endpoint
class TestSearchFiles:
    def _seed_search_corpus(self, workspace: Path) -> None:
        (workspace / "models").mkdir()
        (workspace / "models" / "pid_controller.flw.json").write_text(
            '{"name": "pid"}', encoding="utf-8"
        )
        (workspace / "models" / "lqr_controller.flw.json").write_text(
            '{"name": "lqr"}', encoding="utf-8"
        )
        (workspace / "demo.flw.json").write_text(
            '{"description": "demo model with PID inside"}', encoding="utf-8"
        )
        (workspace / "notes.txt").write_text(
            "First line\nSecond line with PID reference\nThird line",
            encoding="utf-8",
        )

    def test_path_search_finds_matches(self, client: TestClient, workspace: Path) -> None:
        self._seed_search_corpus(workspace)
        r = client.get("/api/v1/files/search", params={"q": "pid", "kind": "path"})
        assert r.status_code == 200
        data = r.json()
        assert data["kind"] == "path"
        paths = [r["path"] for r in data["results"]]
        assert any("pid_controller" in p for p in paths)
        for entry in data["results"]:
            assert "score" in entry
            assert 50.0 <= entry["score"] <= 100.0

    def test_content_search_finds_matches(self, client: TestClient, workspace: Path) -> None:
        self._seed_search_corpus(workspace)
        r = client.get("/api/v1/files/search", params={"q": "PID", "kind": "content"})
        assert r.status_code == 200
        data = r.json()
        assert data["kind"] == "content"
        paths = [(r["path"], r["line_no"]) for r in data["results"]]
        assert any("demo.flw.json" == p for p, _ in paths)
        assert any("notes.txt" == p and ln == 2 for p, ln in paths)
        for entry in data["results"]:
            assert "line_no" in entry
            assert "line_content" in entry
            assert len(entry["line_content"]) <= 200

    def test_content_search_case_insensitive(self, client: TestClient, workspace: Path) -> None:
        self._seed_search_corpus(workspace)
        r1 = client.get("/api/v1/files/search", params={"q": "pid", "kind": "content"})
        r2 = client.get("/api/v1/files/search", params={"q": "PID", "kind": "content"})
        assert len(r1.json()["results"]) == len(r2.json()["results"])

    def test_empty_query_400(self, client: TestClient) -> None:
        r = client.get("/api/v1/files/search", params={"q": "", "kind": "path"})
        assert r.status_code == 400

    def test_whitespace_only_query_400(self, client: TestClient) -> None:
        r = client.get("/api/v1/files/search", params={"q": "   ", "kind": "path"})
        assert r.status_code == 400

    def test_invalid_kind_400(self, client: TestClient) -> None:
        r = client.get("/api/v1/files/search", params={"q": "pid", "kind": "regex"})
        assert r.status_code == 400

    def test_invalid_limit_400(self, client: TestClient) -> None:
        r = client.get("/api/v1/files/search", params={"q": "pid", "kind": "path", "limit": 0})
        assert r.status_code == 400
        r = client.get(
            "/api/v1/files/search",
            params={"q": "pid", "kind": "path", "limit": 9999},
        )
        assert r.status_code == 400

    def test_truncated_flag(self, client: TestClient, workspace: Path) -> None:
        for i in range(6):
            (workspace / f"file{i}.flw.json").write_text("{}", encoding="utf-8")
        r = client.get(
            "/api/v1/files/search",
            params={"q": "file", "kind": "path", "limit": 3},
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data["results"]) <= 3
        assert data["truncated"] is True

    def test_excludes_hard_coded_dirs(self, client: TestClient, workspace: Path) -> None:
        (workspace / "__pycache__").mkdir()
        (workspace / "__pycache__" / "pid_cached.txt").write_text("PID", encoding="utf-8")
        (workspace / "regular_pid.flw.json").write_text("{}", encoding="utf-8")
        r = client.get("/api/v1/files/search", params={"q": "pid", "kind": "path"})
        paths = [r["path"] for r in r.json()["results"]]
        assert any("regular_pid" in p for p in paths)
        assert not any("__pycache__" in p for p in paths)

    def test_respects_gitignore(self, client: TestClient, workspace: Path) -> None:
        (workspace / ".gitignore").write_text("*.log\nignored_dir/\n", encoding="utf-8")
        (workspace / "real.flw.json").write_text("{}", encoding="utf-8")
        (workspace / "skipped.log").write_text("PID inside", encoding="utf-8")
        (workspace / "ignored_dir").mkdir()
        (workspace / "ignored_dir" / "hidden.flw.json").write_text("{}", encoding="utf-8")

        r = client.get("/api/v1/files/search", params={"q": "skipped", "kind": "path"})
        assert all("skipped.log" not in r["path"] for r in r.json()["results"])
        r = client.get("/api/v1/files/search", params={"q": "hidden", "kind": "path"})
        assert all("hidden" not in r["path"] for r in r.json()["results"])
        r = client.get("/api/v1/files/search", params={"q": "PID", "kind": "content"})
        assert all("skipped.log" != r["path"] for r in r.json()["results"])

    def test_default_kind_is_path(self, client: TestClient, workspace: Path) -> None:
        (workspace / "test.flw.json").write_text("{}", encoding="utf-8")
        r = client.get("/api/v1/files/search", params={"q": "test"})
        assert r.status_code == 200
        assert r.json()["kind"] == "path"

    def test_path_traversal_in_q_does_not_escape(self, client: TestClient, workspace: Path) -> None:
        (workspace / "real.flw.json").write_text("{}", encoding="utf-8")
        r = client.get("/api/v1/files/search", params={"q": "../etc", "kind": "path"})
        assert r.status_code == 200
        # security-reviewer SHOULD: 戻り値に ``..`` / 絶対 path 不在を確認
        for entry in r.json()["results"]:
            assert not entry["path"].startswith("/"), entry
            assert ".." not in entry["path"], entry

    def test_query_too_long_400(self, client: TestClient) -> None:
        # security-reviewer MUST: ``q`` 長さ上限 (= rapidfuzz DoS 防止)
        r = client.get(
            "/api/v1/files/search",
            params={"q": "A" * 5000, "kind": "path"},
        )
        assert r.status_code == 400
        assert "Query too long" in r.json()["detail"]

    def test_excludes_env_file_content(self, client: TestClient, workspace: Path) -> None:
        # security-reviewer SHOULD: ``.env`` の中身が content 検索で漏れない
        (workspace / ".env").write_text("SECRET_KEY=abc123", encoding="utf-8")
        (workspace / ".env.production").write_text("DB_PASS=xyz", encoding="utf-8")
        (workspace / "normal.flw.json").write_text("SECRET_KEY=harmless", encoding="utf-8")
        r = client.get(
            "/api/v1/files/search",
            params={"q": "SECRET_KEY", "kind": "content"},
        )
        paths = [entry["path"] for entry in r.json()["results"]]
        assert ".env" not in paths
        assert ".env.production" not in paths
        # normal file はヒットすること (= 機能の正常動作確認)
        assert "normal.flw.json" in paths

    def test_excludes_ssh_directory(self, client: TestClient, workspace: Path) -> None:
        # security-reviewer SHOULD: ``.ssh`` 配下が検索対象外
        (workspace / ".ssh").mkdir()
        (workspace / ".ssh" / "id_rsa").write_text("KEY", encoding="utf-8")
        r = client.get(
            "/api/v1/files/search",
            params={"q": "id_rsa", "kind": "path"},
        )
        paths = [entry["path"] for entry in r.json()["results"]]
        assert not any(".ssh" in p for p in paths)


# v0.21.0 (ADR-0041 §論点 4-A): legacy ``--model-dir`` モード削除に伴い
# ``workspace_root=None`` (= 503 経路) のテストは無効化。``Settings`` で
# ``workspace_root`` は必須キーワードになっているため、不正な状態自体が作れない。
