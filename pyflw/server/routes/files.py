"""File API エンドポイント (ADR-0041 §論点 1-A)。

JupyterLab ``jupyter_server.contents`` API 互換の 6 endpoint を提供する。
``.flw.json`` ファイル自身を **唯一の真実** とし、frontend FileBrowser から
ローカル workspace のディレクトリツリーを直接操作できるようにする。

エンドポイント:

| Method | Path | 用途 |
|---|---|---|
| ``GET`` | ``/files/tree?path=<rel>`` | 子ディレクトリ列挙 (1 階層) |
| ``GET`` | ``/files/content?path=<rel>`` | ファイル内容 (parsed JSON + mtime + etag) |
| ``PUT`` | ``/files/content?path=<rel>`` | 書き込み (etag 楽観ロック) |
| ``POST`` | ``/files/rename`` body ``{from, to}`` | リネーム / 移動 |
| ``DELETE`` | ``/files?path=<rel>`` | ファイル / 空ディレクトリ削除 |
| ``POST`` | ``/files/mkdir?path=<rel>`` | ディレクトリ作成 (mkdir -p、末尾 segment は ``exist_ok=False``) |

Path traversal 防御は ``pyflw.server.security.resolve_workspace_path`` (ADR-0041
§2) に集約。本モジュールは business logic のみ。
"""

from __future__ import annotations

import errno
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ...exceptions import PathTraversalError
from ..security import resolve_workspace_path

_logger = logging.getLogger("pyflw.server.routes.files")

router = APIRouter(prefix="/files", tags=["files"])


# ---------------------------------------------------------------------------
# 共通 helpers
# ---------------------------------------------------------------------------


def _workspace_root(request: Request) -> Path:
    """``app.state.settings.workspace_root`` を取得、未設定なら 503。

    ``--model-dir`` legacy モードで起動された場合、File API は使えないため
    503 Service Unavailable を返す (= 利用者向けに再起動方法を案内)。
    """
    settings = request.app.state.settings
    workspace_root: Path | None = settings.workspace_root
    if workspace_root is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "File API not enabled. Start pyflw-server with --workspace=PATH "
                "(see ADR-0041 for migration from --model-dir)."
            ),
        )
    return workspace_root


def _is_same_as_workspace_root(resolved: Path, workspace_root: Path) -> bool:
    """``resolved`` が workspace root と同一の path を指すかを inode 比較で判定。

    ``Path.samefile`` は OS の inode (Windows では file index) ベースで比較し、
    大文字小文字 / UNC 正規化 / case-insensitive FS の差異に頑健 (= 単純な
    ``==`` 比較より安全)。samefile が ``OSError`` を投げる稀な環境
    (= path が即座に消える等) は ``==`` フォールバック。
    """
    try:
        return resolved.samefile(workspace_root)
    except OSError:
        return resolved == workspace_root.resolve()


def _resolve(workspace_root: Path, raw: str) -> Path:
    """``resolve_workspace_path`` を呼び、``PathTraversalError`` を 403 にマップ。

    エラーメッセージに利用者の入力を含めない (ADR-0041 §論点 2-A、log injection
    多層防御)。詳細は server log のみに記録。
    """
    try:
        return resolve_workspace_path(workspace_root, raw)
    except PathTraversalError as e:
        _logger.warning("Path traversal rejected: %s", e)
        raise HTTPException(
            status_code=403,
            detail="Path traversal rejected (see server log for details).",
        ) from e


def _format_mtime(mtime_ns: int) -> str:
    """``stat.st_mtime_ns`` を ISO 8601 UTC ("Z" 末尾) 文字列に変換する。"""
    seconds = mtime_ns / 1_000_000_000
    return datetime.fromtimestamp(seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _make_etag(size: int, mtime_ns: int) -> str:
    """Weak etag (RFC 7232) を ``size + mtime_ns`` から生成する。

    Weak (``W/`` prefix) を採用する理由 — TLS terminator や CDN 経由で再 encode
    される可能性があり byte-for-byte 一致を保証できないため。本 API は楽観ロックの
    用途のみで Weak etag で十分 (= 同一 mtime_ns + size なら同一とみなす)。
    """
    return f'W/"{size}-{mtime_ns}"'


def _stat_etag(resolved: Path) -> str:
    st = resolved.stat()
    return _make_etag(st.st_size, st.st_mtime_ns)


# ---------------------------------------------------------------------------
# Pydantic body schemas
# ---------------------------------------------------------------------------


class WriteContentBody(BaseModel):
    """``PUT /api/v1/files/content`` の body schema。

    Attributes:
        content: 任意の JSON value (dict / list / str / number / bool / None)。
            ``.flw.json`` を想定するが構造検証は schema migration 側 (= ADR-0008)
            に委ねる。
        expected_etag: 楽観ロック用の前回 etag。``None`` なら check skip
            (= 新規作成 or 強制上書き)。
    """

    content: Any
    expected_etag: str | None = None


class RenameBody(BaseModel):
    """``POST /api/v1/files/rename`` の body schema。

    ``from`` は Python 予約語のため alias で受ける。``populate_by_name=True``
    は将来 Python 内部から ``RenameBody(from_="a", to="b")`` の形で生成できる
    ようにするため (= テストや helper でのインスタンス化を容易にする)。
    """

    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(..., alias="from")
    to: str


# ---------------------------------------------------------------------------
# GET /tree
# ---------------------------------------------------------------------------


@router.get("/tree")
def get_tree(request: Request, path: str = "") -> dict[str, Any]:
    """ディレクトリ配下の子 entry を 1 階層だけ列挙する (再帰しない)。

    Returns:
        ``{path: <input>, children: [{name, type, size, mtime}, ...]}``。
        ``type`` は ``"file"`` または ``"directory"``、ディレクトリなら ``size``
        は ``None``。

    Status:
        * 200: 正常
        * 400: path がディレクトリでなくファイル / リンク等
        * 403: path traversal
        * 404: path 不在
    """
    workspace_root = _workspace_root(request)
    resolved = _resolve(workspace_root, path)
    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"Directory not found: {path}")
    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {path}")

    children: list[dict[str, Any]] = []
    # ソート規則: ディレクトリ優先 → 名前順 (case-insensitive)。
    for child in sorted(
        resolved.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
    ):
        try:
            st = child.stat()
        except OSError as e:
            # broken symlink 等で stat 失敗 — entry を skip。debug ログで運用者が
            # ``--log-level debug`` 指定時に診断できる (= silent ではない)。
            _logger.debug("Skipping entry with failed stat (%s): %s", e, child)
            continue
        if child.is_dir():
            children.append(
                {
                    "name": child.name,
                    "type": "directory",
                    "size": None,
                    "mtime": _format_mtime(st.st_mtime_ns),
                }
            )
        else:
            children.append(
                {
                    "name": child.name,
                    "type": "file",
                    "size": st.st_size,
                    "mtime": _format_mtime(st.st_mtime_ns),
                }
            )
    return {"path": path, "children": children}


# ---------------------------------------------------------------------------
# GET /content
# ---------------------------------------------------------------------------


@router.get("/content")
def get_content(request: Request, path: str) -> dict[str, Any]:
    """ファイル内容を **parsed JSON** として返す。

    Returns:
        ``{path, content, mtime, etag}``。``content`` は parsed object (= dict /
        list 等)、frontend で再 parse 不要。

    Status:
        * 200: 正常
        * 400: path がファイルでなくディレクトリ
        * 403: path traversal
        * 404: ファイル不在
        * 422: ファイル内容が valid JSON でない
        * 500: I/O エラー
    """
    workspace_root = _workspace_root(request)
    resolved = _resolve(workspace_root, path)
    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    if resolved.is_dir():
        raise HTTPException(
            status_code=400, detail=f"Path is a directory, not a file: {path}"
        )
    # ``stat`` を **read_text の前** に取得して、レスポンスの ``etag`` と
    # ``content`` の対応を保つ (code-reviewer MUST 修正)。read 後に外部書き換えで
    # mtime_ns / size が変わると、後撮りの stat が新しい状態を指して content と
    # 不整合になるため。stat → read の順なら少なくとも etag は read 時点の
    # 「読もうとしたファイル」を指す (= read 中の race は別問題、ADR §Risks #5)。
    try:
        st = resolved.stat()
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Cannot stat file: {e}") from e
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Cannot read file: {e}") from e
    try:
        content = json.loads(text)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=422, detail=f"File is not valid JSON: {e}"
        ) from e
    return {
        "path": path,
        "content": content,
        "mtime": _format_mtime(st.st_mtime_ns),
        "etag": _make_etag(st.st_size, st.st_mtime_ns),
    }


# ---------------------------------------------------------------------------
# PUT /content
# ---------------------------------------------------------------------------


@router.put("/content")
def put_content(
    request: Request,
    body: WriteContentBody,
    path: str,
) -> dict[str, Any]:
    """ファイル新規作成 / 上書き保存。

    ``expected_etag`` が指定された場合、現在の etag と一致しなければ 409
    (= 外部編集で衝突)。一致 or ``None`` なら書き込み。

    親ディレクトリは ``parents=True`` で auto-create。

    Status:
        * 200: 新規作成 / 上書き成功
        * 400: path がディレクトリ
        * 403: path traversal
        * 409: ``expected_etag`` 不一致 (= 外部変更検知)
        * 422: content が JSON-serializable でない
        * 500: I/O エラー
    """
    workspace_root = _workspace_root(request)
    resolved = _resolve(workspace_root, path)
    if resolved.exists() and resolved.is_dir():
        raise HTTPException(
            status_code=400, detail=f"Path is a directory: {path}"
        )

    # 楽観ロック: expected_etag 指定 + ファイル既存時のみ check
    if body.expected_etag is not None and resolved.exists():
        current_etag = _stat_etag(resolved)
        if body.expected_etag != current_etag:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "etag mismatch — file modified externally",
                    "current_etag": current_etag,
                },
            )

    # 親ディレクトリ auto-create (= JupyterLab 互換、ADR-0041 §Risks #13)。
    # ``resolved`` は ``_resolve`` を通過済 (= containment check で workspace
    # root 配下が保証される) ため、その parent も workspace 配下に収まる
    # (= root と同一か、root 内のサブディレクトリ)。よって mkdir で root 外に
    # ディレクトリ作成する経路は存在しない。
    resolved.parent.mkdir(parents=True, exist_ok=True)

    try:
        text = json.dumps(body.content, indent=2, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        raise HTTPException(
            status_code=422, detail=f"Content not JSON-serializable: {e}"
        ) from e

    try:
        resolved.write_text(text, encoding="utf-8")
    except OSError as e:
        raise HTTPException(
            status_code=500, detail=f"Cannot write file: {e}"
        ) from e

    st = resolved.stat()
    return {
        "path": path,
        "mtime": _format_mtime(st.st_mtime_ns),
        "etag": _make_etag(st.st_size, st.st_mtime_ns),
    }


# ---------------------------------------------------------------------------
# POST /rename
# ---------------------------------------------------------------------------


@router.post("/rename")
def rename(request: Request, body: RenameBody) -> dict[str, str]:
    """ファイル / ディレクトリのリネームまたは移動。

    Status:
        * 200: 成功
        * 403: ``from`` または ``to`` で path traversal
        * 404: ``from`` 不在
        * 409: ``to`` 既存
        * 500: I/O エラー (cross-device rename 等)
    """
    workspace_root = _workspace_root(request)
    src = _resolve(workspace_root, body.from_)
    dst = _resolve(workspace_root, body.to)

    if not src.exists():
        raise HTTPException(
            status_code=404, detail=f"Source not found: {body.from_}"
        )
    if dst.exists():
        raise HTTPException(
            status_code=409, detail=f"Destination already exists: {body.to}"
        )

    # 移動先の親ディレクトリは auto-create
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        src.rename(dst)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Cannot rename: {e}") from e

    return {"from": body.from_, "to": body.to}


# ---------------------------------------------------------------------------
# DELETE /
# ---------------------------------------------------------------------------


@router.delete("")
def delete(request: Request, path: str) -> Response:
    """ファイル / 空ディレクトリの削除。

    再帰削除はサポートしない (= 安全側、v3.x minor で ``?recursive=true`` を
    検討)。workspace root 自身の削除は 400 で拒否。

    Status:
        * 204: 削除成功
        * 400: workspace root を削除しようとした
        * 403: path traversal
        * 404: path 不在
        * 409: 非空ディレクトリ
    """
    workspace_root = _workspace_root(request)
    resolved = _resolve(workspace_root, path)

    if _is_same_as_workspace_root(resolved, workspace_root):
        raise HTTPException(
            status_code=400, detail="Cannot delete workspace root"
        )
    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {path}")

    if resolved.is_dir():
        try:
            resolved.rmdir()
        except OSError as e:
            # ``rmdir`` は非空ディレクトリで ``ENOTEMPTY`` (POSIX) / ``WinError
            # 145`` (Windows) を返す。それ以外 (= permission denied / file in use
            # 等) は 500 にマップして利用者に正しいリトライ戦略を取らせる
            # (code-reviewer MUST 修正)。
            if e.errno == errno.ENOTEMPTY or getattr(e, "winerror", None) == 145:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Directory not empty (recursive delete not supported): "
                        f"{path}"
                    ),
                ) from e
            raise HTTPException(
                status_code=500, detail=f"Cannot delete directory: {e}"
            ) from e
    else:
        try:
            resolved.unlink()
        except OSError as e:
            raise HTTPException(
                status_code=500, detail=f"Cannot delete file: {e}"
            ) from e

    return Response(status_code=204)


# ---------------------------------------------------------------------------
# POST /mkdir
# ---------------------------------------------------------------------------


@router.post("/mkdir")
def mkdir(request: Request, path: str) -> Response:
    """ディレクトリ作成 (``mkdir -p`` セマンティクス)。

    親ディレクトリは ``parents=True`` で auto-create、末尾 segment は
    ``exist_ok=False`` (= 既存なら 409)。

    Status:
        * 201: 作成成功
        * 400: workspace root を作成しようとした
        * 403: path traversal
        * 409: 既存
        * 500: I/O エラー
    """
    workspace_root = _workspace_root(request)
    resolved = _resolve(workspace_root, path)

    if _is_same_as_workspace_root(resolved, workspace_root):
        raise HTTPException(
            status_code=400, detail="Cannot mkdir workspace root"
        )
    if resolved.exists():
        raise HTTPException(
            status_code=409, detail=f"Path already exists: {path}"
        )

    try:
        resolved.mkdir(parents=True, exist_ok=False)
    except OSError as e:
        raise HTTPException(
            status_code=500, detail=f"Cannot create directory: {e}"
        ) from e

    return Response(status_code=201)
