"""ADR-0019 §(1)(9): Block class registry REST エンドポイントのテスト。

`GET /api/v1/blocks`         — 全 33+ ブロック metadata 列挙
`GET /api/v1/blocks/{type}`  — 個別の完全 docstring + metadata
`POST /api/v1/blocks/resolve-port-shapes` — params 指定で port shape 再計算
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pyflw.server import create_app
from pyflw.server.settings import Settings


@pytest.fixture
def client(tmp_path):
    settings = Settings(workspace_root=tmp_path)
    app = create_app(settings=settings)
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# GET /api/v1/blocks
# ---------------------------------------------------------------------------


class TestListBlocks:
    def test_returns_all_builtin_blocks(self, client: TestClient) -> None:
        resp = client.get("/api/v1/blocks")
        assert resp.status_code == 200
        data = resp.json()
        # ADR-0028 (v0.11.0): schema_version を ``"blocks.v1"`` → ``"blocks.v2"`` に bump
        assert data["schema_version"] == "blocks.v2"
        assert data["supported_locales"] == ["en", "ja"]
        # built-in は 30+ (sources/math/cont/disc/logic/routing/sinks) +
        # subsystems 3 = 33 以上
        assert len(data["blocks"]) >= 33

    def test_each_entry_has_required_fields(self, client: TestClient) -> None:
        resp = client.get("/api/v1/blocks")
        for entry in resp.json()["blocks"]:
            for key in (
                "type_path",
                "display_name",
                # ADR-0028 (blocks.v2): i18n フィールド
                "display_name_i18n",
                "category",
                "icon",
                "docstring_summary",
                "docstring_summary_i18n",
                "params_spec",
                "default_n_inputs",
                "default_n_outputs",
                "port_shapes_in_default",
                "port_shapes_out_default",
                "tags",
                "search_keywords",
            ):
                assert key in entry, f"missing {key} in {entry['type_path']}"
            # full docstring は list レスポンスに含めない (ADR-0019 §1.3)
            assert "docstring_full" not in entry
            # v0.33.0: per-block color は撤廃済 (= frontend 側で slate-600 固定)
            assert "color" not in entry

    def test_i18n_translations_for_builtin_blocks(self, client: TestClient) -> None:
        """ADR-0028: built-in 全 33+ ブロックが ja/en 両方の翻訳を持つ。"""
        resp = client.get("/api/v1/blocks")
        for entry in resp.json()["blocks"]:
            type_path = entry["type_path"]
            i18n_name = entry["display_name_i18n"]
            i18n_summary = entry["docstring_summary_i18n"]
            # 3rd-party 拡張は空 dict を許容するが、built-in は両言語が揃う
            if type_path.startswith("pyflw.blocks.") or type_path.startswith("pyflw.subsystems."):
                assert "en" in i18n_name and "ja" in i18n_name, (
                    f"{type_path}: missing locale in display_name_i18n {i18n_name}"
                )
                assert "en" in i18n_summary and "ja" in i18n_summary, (
                    f"{type_path}: missing locale in docstring_summary_i18n"
                )

    def test_legacy_fields_match_en_translation(self, client: TestClient) -> None:
        """ADR-0028 後方互換: ``display_name`` / ``docstring_summary`` は en コピー。"""
        resp = client.get("/api/v1/blocks")
        for entry in resp.json()["blocks"]:
            i18n_name = entry["display_name_i18n"]
            if "en" in i18n_name:
                assert entry["display_name"] == i18n_name["en"], (
                    f"{entry['type_path']}: display_name and display_name_i18n['en'] mismatch"
                )
            i18n_summary = entry["docstring_summary_i18n"]
            if "en" in i18n_summary:
                assert entry["docstring_summary"] == i18n_summary["en"], (
                    f"{entry['type_path']}: docstring_summary and docstring_summary_i18n['en'] mismatch"
                )

    def test_constant_japanese_translation(self, client: TestClient) -> None:
        """ADR-0028: Constant の ja 翻訳が "定数" になっている。"""
        resp = client.get("/api/v1/blocks")
        c = next(
            b for b in resp.json()["blocks"] if b["type_path"] == "pyflw.blocks.sources.Constant"
        )
        assert c["display_name_i18n"]["ja"] == "定数"
        assert c["docstring_summary_i18n"]["ja"].startswith("定数値ソース")

    def test_gain_entry_specifics(self, client: TestClient) -> None:
        resp = client.get("/api/v1/blocks")
        gain = next(
            b for b in resp.json()["blocks"] if b["type_path"] == "pyflw.blocks.mathops.Gain"
        )
        assert gain["category"] == "mathops"
        assert gain["display_name"] == "Gain"
        assert gain["default_n_inputs"] == 1
        assert gain["default_n_outputs"] == 1
        assert gain["port_shapes_in_default"] == [[]]
        assert gain["tags"] == ["sm_a"]

    def test_mux_is_sm_b_tagged(self, client: TestClient) -> None:
        resp = client.get("/api/v1/blocks")
        mux = next(b for b in resp.json()["blocks"] if b["type_path"] == "pyflw.blocks.routing.Mux")
        assert "sm_b" in mux["tags"]
        assert mux["category"] == "routing"

    def test_constant_is_source_tagged(self, client: TestClient) -> None:
        resp = client.get("/api/v1/blocks")
        c = next(
            b for b in resp.json()["blocks"] if b["type_path"] == "pyflw.blocks.sources.Constant"
        )
        assert "source" in c["tags"]
        assert c["category"] == "sources"
        assert c["default_n_inputs"] == 0
        assert c["default_n_outputs"] == 1

    def test_scope_is_sink_tagged(self, client: TestClient) -> None:
        resp = client.get("/api/v1/blocks")
        sc = next(b for b in resp.json()["blocks"] if b["type_path"] == "pyflw.blocks.sinks.Scope")
        assert "sink" in sc["tags"]
        assert sc["category"] == "sinks"

    def test_response_is_canonical_sorted(self, client: TestClient) -> None:
        """type_path 昇順で返ることを確認 (起動↔テストの安定性)。"""
        resp = client.get("/api/v1/blocks")
        type_paths = [b["type_path"] for b in resp.json()["blocks"]]
        assert type_paths == sorted(type_paths)


# ---------------------------------------------------------------------------
# 検索別名 (search_keywords)
# ---------------------------------------------------------------------------


class TestSearchKeywords:
    def test_relational_has_compare_synonyms(self, client: TestClient) -> None:
        """「関係演算」が compare / 比較 で検索ヒットするための別名を持つ。

        "comp" は ``compare`` の部分一致で拾われるため、別名に ``compare`` が
        あれば足りる (= 今回の主因の回帰防止)。
        """
        resp = client.get("/api/v1/blocks")
        rel = next(
            b
            for b in resp.json()["blocks"]
            if b["type_path"] == "pyflw.blocks.logic.RelationalOperator"
        )
        assert "compare" in rel["search_keywords"]
        assert "比較" in rel["search_keywords"]

    def test_seeded_math_blocks_have_synonyms(self, client: TestClient) -> None:
        """シードした Product / Saturation も別名がレスポンスに乗る
        (= type_path リネーム時に無言で空配列に戻る回帰を検出)。"""
        blocks = {b["type_path"]: b for b in client.get("/api/v1/blocks").json()["blocks"]}
        assert "multiply" in blocks["pyflw.blocks.mathops.Product"]["search_keywords"]
        assert "飽和" in blocks["pyflw.blocks.mathops.Saturation"]["search_keywords"]

    def test_block_without_synonyms_has_empty_list(self, client: TestClient) -> None:
        """別名未登録のブロックは空配列 (= 後方互換、frontend は ?? [] で扱う)。"""
        resp = client.get("/api/v1/blocks")
        gain = next(
            b for b in resp.json()["blocks"] if b["type_path"] == "pyflw.blocks.mathops.Gain"
        )
        assert gain["search_keywords"] == []

    def test_class_attribute_overrides_central_table(self) -> None:
        """class 属性 ``_search_keywords`` が中央テーブルより優先される
        (= 3rd-party 拡張ブロックが自前で別名宣言できる)。"""
        from pyflw.core.block import Block
        from pyflw.server.registry import _resolve_search_keywords, build_metadata

        class _DummyBlock(Block):
            _search_keywords = ("synonymx", "別名y")

            def __init__(self, *, id: str | None = None, name: str | None = None) -> None:
                super().__init__(id=id, name=name, n_inputs=1, n_outputs=1)

            def output(self, t, x, u):  # type: ignore[no-untyped-def]
                return u

        assert _resolve_search_keywords(_DummyBlock) == ["synonymx", "別名y"]
        meta = build_metadata(_DummyBlock)
        assert meta.search_keywords == ["synonymx", "別名y"]

    def test_empty_class_attribute_means_explicit_no_synonyms(self) -> None:
        """``_search_keywords = []`` は「明示的に別名なし」として尊重し、
        中央テーブルへフォールバックしない (= is not None 判定)。"""
        from pyflw.core.block import Block
        from pyflw.server.registry import _resolve_search_keywords

        # 中央テーブルに登録済の type_path を持つが、空 list で上書きするブロック
        class _NoKeywords(Block):
            _search_keywords: tuple[str, ...] = ()

            def __init__(self, *, id: str | None = None, name: str | None = None) -> None:
                super().__init__(id=id, name=name, n_inputs=1, n_outputs=1)

            def output(self, t, x, u):  # type: ignore[no-untyped-def]
                return u

        assert _resolve_search_keywords(_NoKeywords) == []


# ---------------------------------------------------------------------------
# GET /api/v1/blocks/{type_path}
# ---------------------------------------------------------------------------


class TestGetBlockMetadata:
    def test_returns_full_docstring(self, client: TestClient) -> None:
        resp = client.get("/api/v1/blocks/pyflw.blocks.mathops.Gain")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type_path"] == "pyflw.blocks.mathops.Gain"
        # full docstring が返る
        assert "docstring_full" in data
        assert isinstance(data["docstring_full"], str)

    def test_404_for_unknown_type_path(self, client: TestClient) -> None:
        resp = client.get("/api/v1/blocks/no.such.Block")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/blocks/resolve-port-shapes
# ---------------------------------------------------------------------------


class TestResolvePortShapes:
    def test_mux_n_3_returns_three_inputs(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/blocks/resolve-port-shapes",
            json={"type_path": "pyflw.blocks.routing.Mux", "params": {"n": 3}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["n_inputs"] == 3
        assert data["n_outputs"] == 1
        assert data["port_shapes_in"] == [[], [], []]
        assert data["port_shapes_out"] == [[3]]

    def test_demux_n_5_returns_five_outputs(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/blocks/resolve-port-shapes",
            json={"type_path": "pyflw.blocks.routing.Demux", "params": {"n": 5}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["n_inputs"] == 1
        assert data["n_outputs"] == 5
        assert data["port_shapes_in"] == [[5]]

    def test_sum_signs_alters_n_inputs(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/blocks/resolve-port-shapes",
            json={
                "type_path": "pyflw.blocks.mathops.Sum",
                "params": {"signs": "+++"},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["n_inputs"] == 3
        assert data["n_outputs"] == 1

    def test_400_on_invalid_params(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/blocks/resolve-port-shapes",
            json={"type_path": "pyflw.blocks.routing.Mux", "params": {"n": 0}},
        )
        # n=0 で BlockSpecError → 400
        assert resp.status_code == 400

    def test_404_on_unknown_type(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/blocks/resolve-port-shapes",
            json={"type_path": "no.such.Block", "params": {}},
        )
        assert resp.status_code == 404

    def test_400_on_missing_type_path(self, client: TestClient) -> None:
        resp = client.post("/api/v1/blocks/resolve-port-shapes", json={"params": {}})
        assert resp.status_code == 400

    def test_400_on_non_object_body(self, client: TestClient) -> None:
        resp = client.post("/api/v1/blocks/resolve-port-shapes", json=[1, 2, 3])
        assert resp.status_code == 400

    def test_get_method_returns_405(self, client: TestClient) -> None:
        """GET の場合は 405 + 適切なメッセージ (path conflict 防止)。"""
        resp = client.get("/api/v1/blocks/resolve-port-shapes")
        assert resp.status_code == 405


# ---------------------------------------------------------------------------
# Registry build (smoke - no startup error)
# ---------------------------------------------------------------------------


class TestRegistryBuild:
    def test_build_succeeds_at_startup(self, client: TestClient) -> None:
        """Lifespan で build_block_registry が走り、`app.state.block_registry` が
        セットされていることを GET 1 回で確認 (= 失敗していたら 500 になる)。"""
        resp = client.get("/api/v1/blocks")
        assert resp.status_code == 200

    def test_all_categories_present(self, client: TestClient) -> None:
        resp = client.get("/api/v1/blocks")
        cats = {b["category"] for b in resp.json()["blocks"]}
        # ADR-0019 §(2) で定義した 9 カテゴリのうち少なくとも 8 (uncategorized は
        # 拡張ブロック専用で built-in には来ない想定)
        expected = {
            "sources",
            "mathops",
            "continuous",
            "discrete",
            "logic",
            "routing",
            "sinks",
            "subsystems",
        }
        assert expected.issubset(cats)

    def test_no_blocks_have_unknown_tag(self, client: TestClient) -> None:
        """built-in 33+ クラスはすべて default factory で実体化できる
        (`_BUILTIN_DEFAULT_ARGS` 完備、ADR-0019 §Risks #2)。"""
        resp = client.get("/api/v1/blocks")
        for b in resp.json()["blocks"]:
            assert "unknown" not in b["tags"], (
                f"{b['type_path']} has 'unknown' tag — _BUILTIN_DEFAULT_ARGS missing?"
            )
