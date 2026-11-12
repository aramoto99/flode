"""Block library エンドポイント (ADR-0029 / ADR-0080)。

`/api/v1/libraries` 系は ``.flwlib.json`` で配布される再利用ブロック (Subsystem /
PythonFunction) を提供する。``/api/v1/blocks`` (= Block class registry) と責務分離する:
blocks は **コード上の** Block class 定義、libraries は **ファイル上の** テンプレート。

読み取り (常に許可):

* ``GET /api/v1/libraries`` — 全 library のメタデータ (entry の本体 ``block`` は
  含めない; サイズが大きいため)
* ``GET /api/v1/libraries/{lib}/{entry}`` — 1 entry の本体 ``block`` を含めた詳細
* ``GET /api/v1/libraries/{name}/export`` — ライブラリ全体のダウンロード

書き込み (ADR-0080 §A4。:func:`require_library_write` を通ったときだけ):

* ``POST /api/v1/libraries/user/entries`` — ブロックの登録 (新規 / 上書き)
* ``PATCH /api/v1/libraries/user/entries/{entry_id}`` — 表示名・説明・分類の編集
* ``DELETE /api/v1/libraries/user/entries/{entry_id}?expected_revision=N`` — エントリ削除
* ``POST /api/v1/libraries/import`` — ライブラリファイルの取り込み (JSON 本文)
* ``DELETE /api/v1/libraries/{name}`` — 取り込みライブラリの削除
* ``POST /api/v1/libraries/reload`` — 全ライブラリの再読み込み

ルートは判定と入出力の変換だけを行い、書き込みの中身 (path・ロック・検証・registry の
差し替え) は :class:`flode.server.library_store.LibraryStore` に任せる。固定パスの
ルート (``/reload`` / ``/import`` / ``/user/entries``) は、パラメータ付きのルートより
**先に** 宣言する (宣言順で照合されるため)。
"""

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from ...exceptions import LibraryFileInvalidError
from ...libraries import CURRENT_LIBRARY_SCHEMA_VERSION, Library, LibraryEntry
from ..library_registry import ORIGIN_USER, USER_LIBRARY_NAME, LibraryRegistry
from ..library_store import (
    ImportReport,
    LibraryStore,
    parse_bounded_json,
)
from ..library_store import export_library as serialize_library_for_export

router = APIRouter(prefix="/libraries", tags=["libraries"])

#: 書き込みルートで受け付ける本文の最大バイト数 (ADR-0080 §A4-4)。
MAX_LIBRARY_REQUEST_BYTES = 16 * 1024 * 1024

#: GUI から変更できないライブラリ (ユーザーライブラリ以外) の ``write_disabled_reason``。
REASON_LIBRARY_READ_ONLY = "library_read_only"

_REGISTER_FIELDS: frozenset[str] = frozenset(
    {
        "block",
        "display_name",
        "description",
        "category_suffix",
        "overwrite_entry_id",
        "expected_revision",
        "save_as_new",
    }
)
_METADATA_FIELDS: tuple[str, ...] = ("display_name", "description", "category_suffix")
_IMPORT_FIELDS: frozenset[str] = frozenset({"filename", "content", "dry_run"})

# lifespan を通らない経路 (テスト用) で store を遅延生成するときのロック。
_STORE_CREATION_LOCK = threading.Lock()


# ----------------------------------------------------------------------------
# 共通 helper / dependency
# ----------------------------------------------------------------------------


def _store(request: Request) -> LibraryStore:
    """app.state から :class:`LibraryStore` を取り出す (lifespan 未起動時は lazy build)。

    .. note::

        lazy build 経路 (``app.state.library_store`` が無い) は **テスト専用**。本番の
        lifespan (``create_app`` 内) は起動時に必ず store を作る。
    """
    store = getattr(request.app.state, "library_store", None)
    if store is None:
        # 同期ルートは threadpool で並行に動く。store を 2 つ作ると、ロックも変更検知の
        # 記録も別々になり書き込みの直列化が崩れるので、生成はロック内で 1 回だけ行う
        with _STORE_CREATION_LOCK:
            store = getattr(request.app.state, "library_store", None)
            if store is None:
                settings = request.app.state.settings
                store = LibraryStore(
                    library_paths=settings.library_paths,
                    bundle_builtin=settings.bundle_builtin_libraries,
                    user_library_dir=settings.user_library_dir,
                    write_allowed=settings.library_write_allowed,
                    write_reason=settings.library_write_reason,
                )
                request.app.state.library_store = store
    if not isinstance(store, LibraryStore):
        raise HTTPException(status_code=500, detail="library_store state is corrupted")
    return store


def require_library_write(request: Request) -> None:
    """ユーザーライブラリに書き込むルート共通の判定 (ADR-0080 §A4-1)。

    Raises:
        LibraryWriteForbiddenError: 403 — サーバの設定で書き込みが許可されていない
            (非 loopback bind)。
        UserLibraryDisabledError: 403 — ユーザーライブラリが無効。
    """
    _store(request).require_write()


def require_library_reload(request: Request) -> None:
    """再読み込みルートの判定: 書き込みの許可だけを要件にする。

    再読み込みはユーザーライブラリに書き込まないので、無効でも通す。判定そのものは
    :func:`require_library_write` と同じ ``LibraryStore.require_write`` が行う。

    Raises:
        LibraryWriteForbiddenError: 403 — サーバの設定で書き込みが許可されていない
            (非 loopback bind)。
    """
    _store(request).require_write(needs_user_library=False)


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


async def _json_object_body(
    request: Request, _allowed: None = Depends(require_library_write)
) -> dict[str, Any]:
    """書き込みルートの本文を、サイズと入れ子の上限つきで JSON object として読む。

    書き込みの可否を先に判定する (拒否する要求の本文は読まない)。

    Raises:
        HTTPException: 411 — 本文の長さが不明 (``Content-Length`` 無し / chunked)。
            413 — :data:`MAX_LIBRARY_REQUEST_BYTES` を超える。400 — ``Content-Length``
            が不正。422 — JSON として読めない・入れ子が深すぎる・object でない。
    """
    headers = request.headers
    declared = headers.get("content-length")
    if declared is None or headers.get("transfer-encoding") is not None:
        raise HTTPException(
            status_code=411,
            detail="Library write requests must declare Content-Length (chunked bodies "
            "are not accepted).",
        )
    # ``isdigit()`` だけでは "²" のような非 ASCII の数字も通り、``int()`` で失敗する
    if not (declared.isascii() and declared.isdigit()):
        raise HTTPException(status_code=400, detail="Invalid Content-Length header.")
    too_large = HTTPException(
        status_code=413,
        detail=f"Request body exceeds the limit of {MAX_LIBRARY_REQUEST_BYTES} bytes.",
    )
    if int(declared) > MAX_LIBRARY_REQUEST_BYTES:
        raise too_large
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > MAX_LIBRARY_REQUEST_BYTES:
            raise too_large
        chunks.append(chunk)
    try:
        payload = await run_in_threadpool(parse_bounded_json, b"".join(chunks))
    except LibraryFileInvalidError as e:
        raise _unprocessable(f"Request body is not acceptable JSON: {e}") from e
    if not isinstance(payload, dict):
        raise _unprocessable("Request body must be a JSON object.")
    return payload


def _reject_unknown_fields(body: dict[str, Any], allowed: frozenset[str]) -> None:
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise _unprocessable(f"Unknown field(s): {', '.join(unknown)[:200]}")


def _string_field(body: dict[str, Any], key: str, *, default: str | None = None) -> str:
    """文字列フィールドを取り出す (``default`` が ``None`` なら必須)。"""
    if key not in body:
        if default is None:
            raise _unprocessable(f"Field {key!r} is required.")
        return default
    value = body[key]
    if not isinstance(value, str):
        raise _unprocessable(f"Field {key!r} must be a string.")
    return value


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


def _library_metadata_dict(lib: Library, origin: str, user_reason: str) -> dict[str, Any]:
    """:class:`Library` を REST response 用 dict に変換 (entries は metadata だけ)。

    Args:
        lib: 変換する library。
        origin: 出所 (``"builtin"`` / ``"user"`` / ``"imported"`` / ``"path"``)。
        user_reason: ユーザーライブラリに書き込めない理由のコード (書き込めるなら空文字)。
    """
    reason = user_reason if origin == ORIGIN_USER else REASON_LIBRARY_READ_ONLY
    return {
        "name": lib.name,
        "uid": lib.uid,
        "display_name": lib.display_name,
        "display_name_i18n": dict(lib.display_name_i18n),
        "description": lib.description,
        "description_i18n": dict(lib.description_i18n),
        "version": lib.version,
        "origin": origin,
        "writable": not reason,
        "write_disabled_reason": reason,
        "entries": [_entry_metadata_dict(e) for e in lib.entries],
    }


def _registry_response(store: LibraryStore, reg: LibraryRegistry) -> dict[str, Any]:
    """``GET /libraries`` / ``POST /libraries/reload`` の応答を組み立てる。

    Args:
        store: 書き込みの可否 (サーバの設定) を答える store。
        reg: 呼び出し側がそのリクエストで 1 回だけ掴んだ registry。応答の全項目をこれから
            作る (途中で registry が差し替わっても応答の中身が混ざらない)。
    """
    # 遅延 import で循環回避 (registry_translations は SUPPORTED_LOCALES のみ使う)
    from ..registry_translations import SUPPORTED_LOCALES

    reason = store.write_disabled_reason(reg)
    return {
        "libraries": [
            _library_metadata_dict(lib, reg.origin_of(name), reason)
            for name, lib in reg.libraries.items()
        ],
        "load_errors": [{"path": e.path, "message": e.message} for e in reg.load_errors],
        "schema_version": CURRENT_LIBRARY_SCHEMA_VERSION,
        "supported_locales": list(SUPPORTED_LOCALES),
        # ユーザーライブラリはファイルがまだ無いと ``libraries`` に現れないので、
        # 登録できるかどうかを別枠で返す
        "user_library": {
            "name": USER_LIBRARY_NAME,
            "enabled": store.user_library_enabled,
            "exists": reg.origins.get(USER_LIBRARY_NAME) == ORIGIN_USER,
            "writable": not reason,
            "write_disabled_reason": reason,
        },
    }


def _entry_detail(reg: LibraryRegistry, library_name: str, entry_id: str) -> dict[str, Any]:
    """1 entry の詳細 (本体つき) を返す。無ければ 404。"""
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


def _user_entry_response(library: Library, entry: LibraryEntry) -> dict[str, Any]:
    return {
        "library": library.name,
        "library_uid": library.uid,
        "entry": _entry_metadata_dict(entry),
    }


def _import_response(report: ImportReport) -> dict[str, Any]:
    library = report.library
    return {
        "dry_run": report.dry_run,
        "library": {
            "name": library.name,
            "uid": library.uid,
            "display_name": library.display_name,
            "entry_count": len(library.entries),
        },
        "python_entries": [
            {
                "id": e.id,
                "display_name": e.display_name,
                "python_block_paths": list(e.python_block_paths),
            }
            for e in library.entries
            if e.contains_python
        ],
        "unknown_types": list(report.unknown_types),
        "conflict": (
            {"name": report.conflict_name, "reason": report.conflict} if report.conflict else None
        ),
    }


# ----------------------------------------------------------------------------
# 一覧 / 再読み込み / 取り込み (固定パス)
# ----------------------------------------------------------------------------


@router.get("")
def list_libraries(request: Request) -> dict[str, Any]:
    """全 library のメタデータを返す (entry の本体は含めない、ADR-0029)。

    Body サイズ削減のため、各 entry の重い本体 ``block`` (内部 blocks/connections) は
    ``GET /api/v1/libraries/{lib}/{entry}`` で個別 fetch する設計。

    Returns:
        ``{"libraries": [...], "load_errors": [...], "schema_version": "libraries.v4",
        "supported_locales": ["en", "ja"], "user_library": {...}}``。``schema_version`` は
        ローダの ``CURRENT_LIBRARY_SCHEMA_VERSION`` に一致する。各 library は ``origin`` /
        ``writable`` / ``write_disabled_reason`` を持つ (ADR-0080 §A1-6 / §A4-1)。
    """
    store = _store(request)
    return _registry_response(store, store.registry)


@router.post("/reload", dependencies=[Depends(require_library_reload)])
def reload_libraries(request: Request) -> dict[str, Any]:
    """起動時と同じ手順で全ライブラリを読み直す (手で置いたファイルの反映、ADR-0080 §A5)。

    ``config.toml`` は読み直さない。ユーザーライブラリには書き込まないので、書き込みが
    許可されていれば (loopback bind)、ユーザーライブラリが無効でも実行できる。

    Returns:
        ``GET /api/v1/libraries`` と同じ形。
    """
    store = _store(request)
    return _registry_response(store, store.reload())


@router.post("/import")
def import_library(
    request: Request, body: dict[str, Any] = Depends(_json_object_body)
) -> dict[str, Any]:
    """ライブラリファイルを read-only の別ライブラリとして取り込む (ADR-0080 §A4-4)。

    本文は JSON ``{"filename": str?, "content": str, "dry_run": bool?}``。``content`` は
    ファイル本文の文字列で、サーバ側で JSON として読む。``filename`` は表示専用で、
    サーバは保存先の決定に使わない。

    Returns:
        ``{"dry_run", "library": {"name", "uid", "display_name", "entry_count"},
        "python_entries": [{"id", "display_name", "python_block_paths"}],
        "unknown_types": [...], "conflict": {"name", "reason"} | null}``。
        ``dry_run`` が真なら何も書き込まず、未知の型と衝突を結果に載せる。``conflict.reason``
        は ``"reserved"`` / ``"exists"`` (``name`` は取り込むライブラリの名前) または
        ``"uid_exists"`` (``name`` は同じ ``uid`` を持つ既存ライブラリの名前)。dry-run の
        ``library.uid`` はファイルに書かれていた値 (無ければ ``null``)。
    """
    _reject_unknown_fields(body, _IMPORT_FIELDS)
    _string_field(body, "filename", default="")
    content = _string_field(body, "content")
    dry_run = body.get("dry_run", False)
    if not isinstance(dry_run, bool):
        raise _unprocessable("Field 'dry_run' must be a boolean.")
    return _import_response(_store(request).import_library(content, dry_run=dry_run))


# ----------------------------------------------------------------------------
# ユーザーライブラリのエントリ (固定パス ``/user/entries``)
# ----------------------------------------------------------------------------


@router.post(f"/{USER_LIBRARY_NAME}/entries")
def register_user_entry(
    request: Request, body: dict[str, Any] = Depends(_json_object_body)
) -> dict[str, Any]:
    """ブロックをユーザーライブラリに登録する (新規 / 上書き、ADR-0080 §A5)。

    本文は ``{"block", "display_name", "description"?, "category_suffix"?,
    "overwrite_entry_id"?, "expected_revision"?, "save_as_new"?}``。同名のエントリが
    あり ``overwrite_entry_id`` も ``save_as_new`` も無ければ 409
    ``library_entry_name_conflict`` (既存エントリの id / revision つき)。

    Returns:
        ``{"library": "user", "library_uid", "entry": {...metadata, "revision"}}``。
    """
    _reject_unknown_fields(body, _REGISTER_FIELDS)
    if "block" not in body:
        raise _unprocessable("Field 'block' is required.")
    overwrite_entry_id = body.get("overwrite_entry_id")
    if overwrite_entry_id is not None and not isinstance(overwrite_entry_id, str):
        raise _unprocessable("Field 'overwrite_entry_id' must be a string.")
    expected_revision = body.get("expected_revision")
    if expected_revision is not None and (
        isinstance(expected_revision, bool) or not isinstance(expected_revision, int)
    ):
        raise _unprocessable("Field 'expected_revision' must be an integer.")
    save_as_new = body.get("save_as_new", False)
    if not isinstance(save_as_new, bool):
        raise _unprocessable("Field 'save_as_new' must be a boolean.")
    library, entry = _store(request).register_entry(
        block=body["block"],
        display_name=_string_field(body, "display_name"),
        description=_string_field(body, "description", default=""),
        category_suffix=_string_field(body, "category_suffix", default=""),
        overwrite_entry_id=overwrite_entry_id,
        expected_revision=expected_revision,
        save_as_new=save_as_new,
    )
    return _user_entry_response(library, entry)


@router.patch(f"/{USER_LIBRARY_NAME}/entries/{{entry_id}}")
def update_user_entry(
    request: Request, entry_id: str, body: dict[str, Any] = Depends(_json_object_body)
) -> dict[str, Any]:
    """エントリの表示名・説明・分類を編集する (revision は上げない、ADR-0080 §A5)。

    本文は ``{"display_name"?, "description"?, "category_suffix"?}``。送られた
    フィールドだけを後勝ちで更新する。

    Returns:
        ``{"library": "user", "library_uid", "entry": {...metadata}}``。
    """
    _reject_unknown_fields(body, frozenset(_METADATA_FIELDS))
    changes = {key: _string_field(body, key) for key in _METADATA_FIELDS if key in body}
    library, entry = _store(request).update_entry_metadata(entry_id, changes)
    return _user_entry_response(library, entry)


@router.delete(
    f"/{USER_LIBRARY_NAME}/entries/{{entry_id}}",
    dependencies=[Depends(require_library_write)],
)
def delete_user_entry(
    request: Request, entry_id: str, expected_revision: int = Query(..., ge=1)
) -> dict[str, Any]:
    """ユーザーライブラリからエントリを削除する (``expected_revision`` 必須)。

    既に配置されたブロックは inline コピーなので影響を受けない。

    Returns:
        ``{"library": "user", "library_uid", "deleted": entry_id}``。
    """
    library = _store(request).delete_entry(entry_id, expected_revision)
    return {"library": library.name, "library_uid": library.uid, "deleted": entry_id}


# ----------------------------------------------------------------------------
# ライブラリ単位 (パラメータ付きパス。固定パスより後に宣言する)
# ----------------------------------------------------------------------------


@router.get("/{library_name}/export")
def export_library(request: Request, library_name: str) -> Response:
    """ライブラリ全体を ``.flwlib.json`` としてダウンロードさせる (ADR-0080 §A4-6)。

    現行 schema で再シリアライズして返す。``user`` ライブラリは ``name`` を
    ``user-<uid 先頭 8 桁>`` に書き換える (``uid`` は保持する)。

    この URL は ``GET /{lib}/{entry}`` の entry が ``export`` の場合と同じ形だが、registry は
    予約エントリ id (``export`` / ``entries``) を持つライブラリを読み込まないので、常に
    ライブラリのダウンロードを返す (本ルートを先に宣言していることにも依存する)。

    Raises:
        LibraryNotFoundError: 404 — ライブラリが registry に無い。
    """
    reg = _store(request).registry  # 1 回だけ読む
    filename, text = serialize_library_for_export(reg, library_name)
    return Response(
        content=text,
        media_type="application/json",
        headers={
            # filename はサーバが slug 化した ASCII ([a-z0-9_-] + 拡張子) のみ
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


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
    return _entry_detail(_store(request).registry, library_name, entry_id)


@router.delete("/{library_name}", dependencies=[Depends(require_library_write)])
def delete_library(request: Request, library_name: str) -> dict[str, Any]:
    """取り込みライブラリを削除する (``origin == "imported"`` のみ、ADR-0080 §A4-3)。

    ファイルは ``<name>.bak`` にリネームされ、手動で復元できる。対象のファイルは
    ライブラリ名から registry 経由で特定する (クライアントは path を指定できない)。

    Returns:
        ``{"deleted": library_name}``。
    """
    _store(request).delete_imported_library(library_name)
    return {"deleted": library_name}
