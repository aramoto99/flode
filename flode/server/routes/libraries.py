"""Block library エンドポイント (ADR-0029 / ADR-0080)。

`/api/v1/libraries` 系は ``.flwlib.json`` で配布される再利用ブロック (Subsystem /
PythonFunction) を提供する。``/api/v1/blocks`` (= Block class registry) と責務分離する:
blocks は **コード上の** Block class 定義、libraries は **ファイル上の** テンプレート。

エンドポイント:

* ``GET /api/v1/libraries`` — 全 library のメタデータ (entry の本体 ``block`` は
  含めない; サイズが大きいため)
* ``GET /api/v1/libraries/{lib}/{entry}`` — 1 entry の本体 ``block`` を含めた詳細
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ...libraries import CURRENT_LIBRARY_SCHEMA_VERSION, Library, LibraryEntry
from ..library_registry import LibraryRegistry, build_library_registry

router = APIRouter(prefix="/libraries", tags=["libraries"])


def _registry(request: Request) -> LibraryRegistry:
    """app.state から library registry を取り出す型安全 helper (lifespan 未起動時 lazy build)。

    .. note::

        本関数の lazy build 経路 (``app.state.library_registry is None``) は
        **テスト専用**。本番 lifespan (``create_app`` 内) では必ず
        ``build_library_registry`` を起動時に呼ぶため、このパスに到達したら
        設定の不整合 (= バグ) を示す。
    """
    reg = getattr(request.app.state, "library_registry", None)
    if reg is None:
        # テスト fixture 等で lifespan が起動していない場合の lazy build
        settings = getattr(request.app.state, "settings", None)
        library_paths = list(getattr(settings, "library_paths", []) or [])
        bundle_builtin = bool(getattr(settings, "bundle_builtin_libraries", True))
        reg = build_library_registry(library_paths, bundle_builtin=bundle_builtin)
        request.app.state.library_registry = reg
    if not isinstance(reg, LibraryRegistry):
        raise HTTPException(status_code=500, detail="library_registry state is corrupted")
    return reg


def _entry_metadata_dict(entry: LibraryEntry) -> dict[str, Any]:
    """:class:`LibraryEntry` を REST response 用 dict に変換 (本体 ``block`` 抜き)。

    ``kind`` / ``contains_python`` / ``python_block_paths`` は本体から導出した値で、
    ファイルには保存されていない (ADR-0080 §A1-2 / §A1-6)。
    """
    return {
        "id": entry.id,
        "display_name": entry.display_name,
        "display_name_i18n": dict(entry.display_name_i18n),
        "description": entry.description,
        "description_i18n": dict(entry.description_i18n),
        "category_suffix": entry.category_suffix,
        "kind": entry.kind,
        "revision": entry.revision,
        "updated_at": entry.updated_at,
        "contains_python": entry.contains_python,
        "python_block_paths": list(entry.python_block_paths),
    }


def _library_metadata_dict(lib: Library) -> dict[str, Any]:
    """:class:`Library` を REST response 用 dict に変換 (entries は metadata だけ)。"""
    return {
        "name": lib.name,
        "uid": lib.uid,
        "display_name": lib.display_name,
        "display_name_i18n": dict(lib.display_name_i18n),
        "description": lib.description,
        "description_i18n": dict(lib.description_i18n),
        "version": lib.version,
        "entries": [_entry_metadata_dict(e) for e in lib.entries],
    }


@router.get("")
def list_libraries(request: Request) -> dict[str, Any]:
    """全 library のメタデータを返す (entry の本体は含めない、ADR-0029)。

    Body サイズ削減のため、各 entry の重い本体 ``block`` (内部 blocks/connections) は
    ``GET /api/v1/libraries/{lib}/{entry}`` で個別 fetch する設計。

    Returns:
        ``{"libraries": [...], "load_errors": [...], "schema_version": "libraries.v4",
        "supported_locales": ["en", "ja"]}``。``schema_version`` はローダの
        ``CURRENT_LIBRARY_SCHEMA_VERSION`` に一致する。
    """
    # 遅延 import で循環回避 (registry_translations は SUPPORTED_LOCALES のみ使う)
    from ..registry_translations import SUPPORTED_LOCALES

    reg = _registry(request)
    return {
        "libraries": [_library_metadata_dict(lib) for lib in reg.libraries.values()],
        "load_errors": [{"path": e.path, "message": e.message} for e in reg.load_errors],
        "schema_version": CURRENT_LIBRARY_SCHEMA_VERSION,
        "supported_locales": list(SUPPORTED_LOCALES),
    }


@router.get("/{library_name}/{entry_id}")
def get_library_entry(request: Request, library_name: str, entry_id: str) -> dict[str, Any]:
    """1 entry の本体 ``block`` を含めた詳細を返す (ADR-0029 / ADR-0080)。

    Inline 配置時の drop 経路で frontend が呼ぶ。本体は ``Block.to_dict()`` の出力と
    byte-identical (= REST 経由でも byte-identical を維持)。

    ``revision`` と ``library_uid`` を本体と同じレスポンスに載せる: 配置したブロックの
    由来は一覧ではなくこのレスポンスから作るので、一覧キャッシュが古くても本体と版が
    食い違わない (ADR-0080 §A5)。

    Returns:
        ``{"id", "display_name", ..., "revision", "library_uid",
        "block": {"id", "type", "params"}}``。

    Raises:
        HTTPException: 404 — library / entry が registry に存在しない場合。
    """
    reg = _registry(request)
    lib = reg.libraries.get(library_name)
    if lib is None:
        raise HTTPException(
            status_code=404,
            detail=f"Library {library_name!r} not found in registry",
        )
    entry = lib.get_entry(entry_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Entry {entry_id!r} not found in library {library_name!r} "
                f"(available: {[e.id for e in lib.entries]})"
            ),
        )
    return {
        **_entry_metadata_dict(entry),
        "library_uid": lib.uid,
        # ``block`` は ``Block.to_dict()`` の出力 (= byte-identical)
        "block": entry.block,
    }
