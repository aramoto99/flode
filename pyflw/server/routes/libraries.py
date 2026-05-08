"""Block library エンドポイント (ADR-0029)。

`/api/v1/libraries` 系は ``.flwlib.json`` で配布されるマスク Subsystem 集合を提供する。
``/api/v1/blocks`` (= Block class registry) と責務分離する: blocks は **コード上の**
Block class 定義、libraries は **ファイル上の** Subsystem テンプレート。

エンドポイント:

* ``GET /api/v1/libraries`` — 全 library のメタデータ (entry の ``subsystem`` body は
  含めない; サイズが大きいため)
* ``GET /api/v1/libraries/{lib}/{entry}`` — 1 entry の subsystem body を含めた詳細
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

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
        bundle_builtin = bool(
            getattr(settings, "bundle_builtin_libraries", True)
        )
        reg = build_library_registry(library_paths, bundle_builtin=bundle_builtin)
        request.app.state.library_registry = reg
    if not isinstance(reg, LibraryRegistry):
        raise HTTPException(
            status_code=500, detail="library_registry state is corrupted"
        )
    return reg


def _entry_metadata_dict(entry: Any) -> dict[str, Any]:
    """:class:`LibraryEntry` を REST response 用 dict に変換 (subsystem body 抜き)。"""
    return {
        "id": entry.id,
        "display_name": entry.display_name,
        "display_name_i18n": dict(entry.display_name_i18n),
        "description": entry.description,
        "description_i18n": dict(entry.description_i18n),
        "category_suffix": entry.category_suffix,
    }


def _library_metadata_dict(lib: Any) -> dict[str, Any]:
    """:class:`Library` を REST response 用 dict に変換 (entries は metadata だけ)。"""
    return {
        "name": lib.name,
        "display_name": lib.display_name,
        "display_name_i18n": dict(lib.display_name_i18n),
        "description": lib.description,
        "description_i18n": dict(lib.description_i18n),
        "version": lib.version,
        "entries": [_entry_metadata_dict(e) for e in lib.entries],
    }


@router.get("")
def list_libraries(request: Request) -> dict[str, Any]:
    """全 library のメタデータを返す (entry の subsystem body は含めない、ADR-0029)。

    Body サイズ削減のため、各 entry の重い ``subsystem`` (内部 blocks/connections) は
    ``GET /api/v1/libraries/{lib}/{entry}`` で個別 fetch する設計。

    Returns:
        ``{"libraries": [...], "load_errors": [...], "schema_version": "libraries.v1",
        "supported_locales": ["en", "ja"]}``。
    """
    # 遅延 import で循環回避 (registry_translations は SUPPORTED_LOCALES のみ使う)
    from ..registry_translations import SUPPORTED_LOCALES

    reg = _registry(request)
    return {
        "libraries": [_library_metadata_dict(lib) for lib in reg.libraries.values()],
        "load_errors": [
            {"path": e.path, "message": e.message} for e in reg.load_errors
        ],
        "schema_version": "libraries.v1",
        "supported_locales": list(SUPPORTED_LOCALES),
    }


@router.get("/{library_name}/{entry_id}")
def get_library_entry(
    request: Request, library_name: str, entry_id: str
) -> dict[str, Any]:
    """1 entry の subsystem body を含めた詳細を返す (ADR-0029)。

    Inline 配置時の drop 経路で frontend が呼ぶ。subsystem body は
    ``Subsystem.to_dict()`` の出力と byte-identical (= REST 経由でも byte-identical を維持)。

    Returns:
        ``{"id", "display_name", ..., "subsystem": {"id", "type", "params"}}``。

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
        # ``subsystem`` は ``Subsystem.to_dict()`` の出力 (= byte-identical)
        "subsystem": entry.subsystem,
    }
