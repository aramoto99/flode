"""File API エンドポイント (ADR-0041 §論点 1-A)。

汎用 contents API 形式 (ファイル CRUD REST) の 6 endpoint を提供する。
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
| ``POST`` | ``/files/copy?from=<rel>&to=<rel>`` | ファイル / ディレクトリ複製 (v0.31.9、末尾は ``exist_ok=False``) |

Path traversal 防御は ``pyflw.server.security.resolve_workspace_path`` (ADR-0041
§2) に集約。本モジュールは business logic のみ。
"""

from __future__ import annotations

import errno
import hashlib
import json
import logging
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pathspec
from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from rapidfuzz import fuzz

from ...exceptions import PathTraversalError
from ..security import resolve_workspace_path

# ADR-0043 §論点 5-A: 検索時に hard-coded で除外するディレクトリ。
# .gitignore と無関係に常に除外 (= 巨大なノイズ源 + 機密漏洩防止)。
# security-reviewer SHOULD: ``.ssh`` / ``.aws`` / ``.gnupg`` / ``.docker`` /
# ``.idea`` を追加 (= secret / IDE workspace dump の露出回避)。
_HARD_CODED_EXCLUDE_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        ".pytest_cache",
        "dist",
        "build",
        ".mypy_cache",
        ".ruff_cache",
        ".ssh",
        ".aws",
        ".gnupg",
        ".docker",
        ".idea",
    }
)
# secret ファイル名パターン: content 検索でこれらの中身が response 行に混入する
# のを防ぐため、列挙段階で除外する。``.env.local`` / ``.env.production`` 等の
# ``.env.`` prefix も _iter_workspace_files 側で startswith 判定。
_HARD_CODED_EXCLUDE_FILE_NAMES: frozenset[str] = frozenset(
    {".env", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"}
)

# 検索結果のデフォルト上限 (ADR-0043 §論点 5-A): UI レスポンス性確保のため。
_DEFAULT_SEARCH_LIMIT = 100
_MAX_SEARCH_LIMIT = 1000
# security-reviewer MUST: ``q`` 長さ上限 (= rapidfuzz の O(|q|·|rel|) DoS 防止)。
_MAX_QUERY_LEN = 256
# security-reviewer MUST: content 検索の 1 ファイルあたり最大バイト数 (OOM 防止)。
_MAX_CONTENT_FILE_SIZE = 2 * 1024 * 1024  # 2 MiB
# security-reviewer SHOULD: fs walk で訪問する file 上限。超過は truncated=True。
_MAX_FILES_SCANNED = 50_000

_logger = logging.getLogger("pyflw.server.routes.files")

router = APIRouter(prefix="/files", tags=["files"])


# ---------------------------------------------------------------------------
# 共通 helpers
# ---------------------------------------------------------------------------


def _workspace_root(request: Request) -> Path:
    """``app.state.settings.workspace_root`` を取得 (v0.21.0: 必須なので常に non-null)。

    v2.x では legacy ``--model-dir`` モードで ``workspace_root=None`` だった場合
    に 503 を返していたが、v0.21.0 で ``Settings.workspace_root`` 必須化に伴い
    本 helper は単純に value を返すだけに簡素化。
    """
    settings = request.app.state.settings
    workspace_root: Path = settings.workspace_root
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


@router.get("/workspace_info")
def get_workspace_info(request: Request) -> dict[str, Any]:
    """workspace root の絶対 path と短縮 hash を返す (ADR-0043 §論点 1-A / §論点 8-A)。

    frontend は ``hash`` を localStorage キーの suffix にし、別 workspace で
    起動した場合は復元せず clean state にする。``absolute_path`` は人間可読な
    表示用 (= status bar 等)。

    hash は ``sha256(str(workspace_root.resolve())).hexdigest()[:16]`` で固定。
    16 文字 (= 64 bit) あれば衝突確率が無視できる程度に低く、URL / localStorage
    キーに収まる長さ。

    Returns:
        ``{absolute_path: str, hash: str}``。
    """
    workspace_root = _workspace_root(request)
    abs_path = str(workspace_root.resolve())
    digest = hashlib.sha256(abs_path.encode("utf-8")).hexdigest()[:16]
    return {"absolute_path": abs_path, "hash": digest}


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
    for child in sorted(resolved.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
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


# response_model=None: 戻り値が dict | Response の union のため FastAPI の
# response model 自動推論を無効化する (= 304 時は生の Response を返す)。
@router.get("/content", response_model=None)
def get_content(request: Request, path: str, response: Response) -> dict[str, Any] | Response:
    """ファイル内容を **parsed JSON** として返す。

    条件付き GET (RFC 7232): リクエストの ``If-None-Match`` が現在の etag と
    一致する場合は本文なしの 304 を返す。外部変更検知の 5 秒ポーリング
    (frontend ``useExternalChangesPoll``) が「etag 確認のためだけに全文を
    ダウンロードする」無駄を避けるための対応。

    Note:
        比較は **単一値の文字列完全一致のみ** の簡略版 (= サーバが返した etag
        をそのまま echo する自前 frontend 専用)。RFC 7232 §2.3.2 の weak
        comparator (``W/`` prefix 無視) やカンマ区切り複数値・``*`` は
        サポートしない。PUT の ``expected_etag`` 楽観ロックと同じ方針。

    Returns:
        ``{path, content, mtime, etag}``。``content`` は parsed object (= dict /
        list 等)、frontend で再 parse 不要。

    Status:
        * 200: 正常 (``ETag`` レスポンスヘッダ付き)
        * 304: ``If-None-Match`` が現在の etag と一致 (本文なし)
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
        raise HTTPException(status_code=400, detail=f"Path is a directory, not a file: {path}")
    # ``stat`` を **read_text の前** に取得して、レスポンスの ``etag`` と
    # ``content`` の対応を保つ (code-reviewer MUST 修正)。read 後に外部書き換えで
    # mtime_ns / size が変わると、後撮りの stat が新しい状態を指して content と
    # 不整合になるため。stat → read の順なら少なくとも etag は read 時点の
    # 「読もうとしたファイル」を指す (= read 中の race は別問題、ADR §Risks #5)。
    try:
        st = resolved.stat()
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Cannot stat file: {e}") from e
    etag = _make_etag(st.st_size, st.st_mtime_ns)
    if_none_match = request.headers.get("if-none-match")
    if if_none_match is not None and if_none_match == etag:
        # 変更なし。read_text / json.loads を丸ごとスキップして本文なしで返す。
        return Response(status_code=304, headers={"ETag": etag})
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Cannot read file: {e}") from e
    try:
        content = json.loads(text)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"File is not valid JSON: {e}") from e
    response.headers["ETag"] = etag
    return {
        "path": path,
        "content": content,
        "mtime": _format_mtime(st.st_mtime_ns),
        "etag": etag,
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
        raise HTTPException(status_code=400, detail=f"Path is a directory: {path}")

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

    # 親ディレクトリ auto-create (= リファレンス Web IDE 互換、ADR-0041 §Risks #13)。
    # ``resolved`` は ``_resolve`` を通過済 (= containment check で workspace
    # root 配下が保証される) ため、その parent も workspace 配下に収まる
    # (= root と同一か、root 内のサブディレクトリ)。よって mkdir で root 外に
    # ディレクトリ作成する経路は存在しない。
    resolved.parent.mkdir(parents=True, exist_ok=True)

    try:
        text = json.dumps(body.content, indent=2, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=422, detail=f"Content not JSON-serializable: {e}") from e

    try:
        resolved.write_text(text, encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Cannot write file: {e}") from e

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
        raise HTTPException(status_code=404, detail=f"Source not found: {body.from_}")
    if dst.exists():
        raise HTTPException(status_code=409, detail=f"Destination already exists: {body.to}")

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
        raise HTTPException(status_code=400, detail="Cannot delete workspace root")
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
                    detail=(f"Directory not empty (recursive delete not supported): {path}"),
                ) from e
            raise HTTPException(status_code=500, detail=f"Cannot delete directory: {e}") from e
    else:
        try:
            resolved.unlink()
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"Cannot delete file: {e}") from e

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
        * 204: 作成成功 (body なし、DELETE と同じ pattern)
        * 400: workspace root を作成しようとした
        * 403: path traversal
        * 409: 既存
        * 500: I/O エラー

    v0.31.4: 旧 v0.31.3 まで 201 Created + 空 body を返していたが、frontend の
    ``_fetch`` が 204 のみ空 body を許容する仕様 (= ``response.json()`` を呼ぶ)
    で「Unexpected end of JSON input」エラー → エラーで catch されて
    ``refresh()`` が走らず、画面更新されないバグ。204 に統一して解消。
    """
    workspace_root = _workspace_root(request)
    resolved = _resolve(workspace_root, path)

    if _is_same_as_workspace_root(resolved, workspace_root):
        raise HTTPException(status_code=400, detail="Cannot mkdir workspace root")
    if resolved.exists():
        raise HTTPException(status_code=409, detail=f"Path already exists: {path}")

    try:
        resolved.mkdir(parents=True, exist_ok=False)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Cannot create directory: {e}") from e

    return Response(status_code=204)


# ---------------------------------------------------------------------------
# POST /copy (v0.31.9)
# ---------------------------------------------------------------------------


@router.post("/copy")
def copy_path(
    request: Request,
    from_: str = Query(alias="from"),
    to: str = Query(),
) -> Response:
    """ファイル / ディレクトリを複製 (= リファレンス Web IDE の "Duplicate" 相当の汎用版)。

    Frontend の Ctrl+C / Ctrl+V (v0.31.9) から呼ばれる。同一 workspace 内の
    src → dst 複製のみサポート (workspace 越え禁止は ``_resolve`` の path
    traversal 防御で担保)。``dst`` の親ディレクトリは ``parents=True`` で
    auto-create、``dst`` 自身は ``exist_ok=False`` (= 既存なら 409)。

    引数名は ``from`` が Python 予約語のため ``from_`` を内部名にし、FastAPI
    の query parameter は ``from`` のまま使えるよう関数シグネチャ上の名前
    だけを変えている。

    Status:
        * 204: 複製成功 (body なし)
        * 400: src と dst が同一、または workspace root を src/dst にしようとした
        * 403: path traversal
        * 404: src が存在しない
        * 409: dst が既存
        * 500: I/O エラー
    """
    workspace_root = _workspace_root(request)
    src = _resolve(workspace_root, from_)
    dst = _resolve(workspace_root, to)

    if _is_same_as_workspace_root(src, workspace_root):
        raise HTTPException(status_code=400, detail="Cannot copy workspace root")
    if _is_same_as_workspace_root(dst, workspace_root):
        raise HTTPException(status_code=400, detail="Cannot overwrite workspace root")
    if src == dst:
        raise HTTPException(status_code=400, detail="Source and destination are the same")
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"Source not found: {from_}")
    if dst.exists():
        raise HTTPException(status_code=409, detail=f"Destination already exists: {to}")

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Cannot copy: {e}") from e

    return Response(status_code=204)


# ---------------------------------------------------------------------------
# GET /search (ADR-0043 §論点 5)
# ---------------------------------------------------------------------------


def _load_gitignore(workspace_root: Path) -> pathspec.PathSpec[Any] | None:
    """workspace root 直下の ``.gitignore`` を読んで PathSpec を返す。

    存在しない / 読めない場合は ``None`` (= filter なし)。``.gitignore`` が
    workspace root にあるとき限定で参照、サブディレクトリの個別 ``.gitignore``
    は本実装では読まない (= MVP として root のみ尊重、ニーズが顕在化したら
    pathspec.PathSpec.from_gitignore_file 拡張)。
    """
    gitignore = workspace_root / ".gitignore"
    if not gitignore.is_file():
        return None
    try:
        text = gitignore.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        _logger.debug("Cannot read .gitignore: %s", e)
        return None
    lines = text.splitlines()
    return pathspec.PathSpec.from_lines("gitwildmatch", lines)


def _iter_workspace_files(
    workspace_root: Path,
    gitignore_spec: pathspec.PathSpec[Any] | None,
) -> Iterator[tuple[Path, str]]:
    """workspace 配下のファイルを再帰列挙し、``(absolute_path, relative_posix)`` を yield する。

    - ``_HARD_CODED_EXCLUDE_DIRS`` のディレクトリは pruning (= 配下に潜らない)
    - ``gitignore_spec`` でマッチした path も除外
    - シンボリックリンクは辿らない (= 無限ループ防止)
    - ``OSError`` は debug log で skip

    Yields:
        ``(file_path, relative_posix)`` の tuple。``relative_posix`` は workspace
        root 相対の forward-slash 文字列 (= UI 表示・REST 戻り値に使う統一形式)。
    """
    workspace_resolved = workspace_root.resolve()
    # ``os.walk`` 風の iterative DFS、symlink はフォロー禁止
    stack: list[Path] = [workspace_resolved]
    while stack:
        directory = stack.pop()
        try:
            entries = list(directory.iterdir())
        except OSError as e:
            _logger.debug("Skipping unreadable directory %s: %s", directory, e)
            continue
        # ファイル / ディレクトリを分けて処理 (= ディレクトリは prune 判定後に stack 追加)
        for entry in entries:
            try:
                # ``is_symlink`` を先にチェック (= シンボリックリンクは無条件 skip)
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    if entry.name in _HARD_CODED_EXCLUDE_DIRS:
                        continue
                    rel = entry.relative_to(workspace_resolved).as_posix() + "/"
                    if gitignore_spec is not None and gitignore_spec.match_file(rel):
                        continue
                    stack.append(entry)
                elif entry.is_file():
                    # security-reviewer SHOULD: secret ファイル名 (.env / .env.*
                    # / id_rsa 等) は中身を露出させないため列挙段階で除外。
                    name = entry.name
                    if name in _HARD_CODED_EXCLUDE_FILE_NAMES:
                        continue
                    if name.startswith(".env."):
                        continue
                    rel = entry.relative_to(workspace_resolved).as_posix()
                    if gitignore_spec is not None and gitignore_spec.match_file(rel):
                        continue
                    yield entry, rel
            except OSError as e:
                _logger.debug("Skipping entry %s: %s", entry, e)


@router.get("/search")
def search_files(
    request: Request,
    q: str,
    kind: str = "path",
    limit: int = _DEFAULT_SEARCH_LIMIT,
) -> dict[str, Any]:
    """ワークスペース内のファイルを検索する (ADR-0043 §論点 5-A)。

    ``kind=path``: file path に対する fuzzy match (rapidfuzz WRatio、score ≥ 50)。
    ``kind=content``: ファイル内容の substring (case-insensitive) line grep。

    ``.git/`` / ``.venv/`` / ``__pycache__/`` / ``node_modules/`` 等を hard-code
    除外、workspace root 直下の ``.gitignore`` も尊重。シンボリックリンクは辿らない。
    結果は ``limit`` 件で打ち切り、``truncated`` flag に反映。

    Args:
        q: 検索クエリ (空文字 / 空白のみは 400)。
        kind: ``"path"`` または ``"content"``。それ以外は 400。
        limit: 最大結果数 (default 100、上限 1000)。

    Returns:
        ``{
            kind: str,
            results: [
                {path, line_no?, line_content?, score?},
                ...
            ],
            truncated: bool,
        }``。``line_no`` / ``line_content`` は ``kind=content`` のみ。
        ``score`` は ``kind=path`` のみ (= 0-100 の rapidfuzz WRatio スコア)。
    """
    if not q.strip():
        raise HTTPException(status_code=400, detail="Empty query")
    # security-reviewer MUST: ``q`` 長さ上限 (= rapidfuzz の DoS 防止)
    if len(q) > _MAX_QUERY_LEN:
        raise HTTPException(status_code=400, detail=f"Query too long (max {_MAX_QUERY_LEN} chars)")
    if kind not in ("path", "content"):
        raise HTTPException(
            status_code=400, detail=f"Invalid kind: {kind!r} (must be 'path' or 'content')"
        )
    if limit < 1 or limit > _MAX_SEARCH_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid limit: {limit} (must be 1..{_MAX_SEARCH_LIMIT})",
        )

    workspace_root = _workspace_root(request)
    gitignore_spec = _load_gitignore(workspace_root)
    results: list[dict[str, Any]] = []
    truncated = False

    if kind == "path":
        # rapidfuzz WRatio はファイル名 vs クエリの「全体的な近さ」を 0-100 で返す。
        # スコア ≥ 50 をしきい値とし、降順ソートで limit 件返す。
        # security-reviewer SHOULD: fs walk visit 上限と heap で全件蓄積を回避。
        import heapq

        scored: list[tuple[float, str]] = []
        scanned = 0
        for _file_path, rel in _iter_workspace_files(workspace_root, gitignore_spec):
            scanned += 1
            if scanned > _MAX_FILES_SCANNED:
                truncated = True
                break
            score = fuzz.WRatio(q, rel)
            if score >= 50:
                # top-limit 件だけ保持する min-heap (= 全件蓄積を避ける)
                if len(scored) < limit:
                    heapq.heappush(scored, (score, rel))
                else:
                    truncated = True  # 1 件でも溢れたら truncated
                    heapq.heappushpop(scored, (score, rel))
        # スコア降順で出力
        for score, rel in sorted(scored, key=lambda x: -x[0]):
            results.append({"path": rel, "score": float(score)})
    else:  # kind == "content"
        # substring case-insensitive line grep。バイナリ判定は単純化のため非テキスト
        # ファイル (= UTF-8 decode 失敗) は skip。
        # security-reviewer MUST: 大ファイルの read_text による OOM を防ぐため
        # ``_MAX_CONTENT_FILE_SIZE`` 超は skip。fs walk 自体も visit 上限あり。
        q_lower = q.lower()
        scanned = 0
        for file_path, rel in _iter_workspace_files(workspace_root, gitignore_spec):
            scanned += 1
            if scanned > _MAX_FILES_SCANNED:
                truncated = True
                break
            if len(results) >= limit:
                truncated = True
                break
            try:
                if file_path.stat().st_size > _MAX_CONTENT_FILE_SIZE:
                    continue
                text = file_path.read_text(encoding="utf-8", errors="strict")
            except (OSError, UnicodeDecodeError):
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                if q_lower in line.lower():
                    results.append(
                        {
                            "path": rel,
                            "line_no": line_no,
                            "line_content": line[:200],  # 1 行 200 文字で打ち切り
                        }
                    )
                    if len(results) >= limit:
                        truncated = True
                        break

    return {"kind": kind, "results": results, "truncated": truncated}
