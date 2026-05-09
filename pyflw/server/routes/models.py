"""モデル CRUD エンドポイント (ADR-0011 §(1))。

モデルストレージはファイルベース (``.flw.json``)。サーバ起動時に渡された
``model_dir`` の配下にあるファイルを直接読み書きする。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ...core.identifiers import validate_model_id
from ...core.persistence import migrate_to_current
from ...exceptions import BlockSpecError, ModelLoadError

router = APIRouter(prefix="/models", tags=["models"])


def _model_dir(request: Request) -> Path:
    return request.app.state.settings.model_dir  # type: ignore[no-any-return]


def _model_path(model_dir: Path, model_id: str) -> Path:
    # Path traversal 防止: validate_model_id でファイル名を検証 (ハイフン許容)
    try:
        validate_model_id(model_id)
    except BlockSpecError as e:
        raise HTTPException(status_code=400, detail=f"Invalid model_id {model_id!r}: {e}") from e
    return model_dir / f"{model_id}.flw.json"


@router.get("")
def list_models(request: Request) -> dict[str, Any]:
    """モデル一覧 (model_id だけ返す軽量レスポンス)。"""
    md = _model_dir(request)
    # ``.flw.json`` は二重拡張子なので ``Path.stem`` は ``"name.flw"`` を返す。
    # ``removesuffix`` で完全な拡張子を取り除く。
    items = sorted(p.name.removesuffix(".flw.json") for p in md.glob("*.flw.json"))
    return {"models": items}


@router.get("/{model_id}")
def get_model(request: Request, model_id: str) -> dict[str, Any]:
    """モデル本体 (JSON) を返す。

    ADR-0039 (v0.14.1): 旧 schema 形式のファイル (= 0.6 / 0.7 等) は
    ``migrate_to_current`` で最新 schema にマイグレートしてから返す。これに
    より frontend は常に最新形式 (= 派生 property 化済) のデータを受け取れる。
    """
    path = _model_path(_model_dir(request), model_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Model {model_id!r} not found")
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ModelLoadError(f"Cannot read {path}: {e}") from e
    try:
        data = migrate_to_current(data)
    except ModelLoadError as e:
        # ``ModelLoadError`` は ``SchemaVersionError`` (サポート外 schema) と
        # ``schema_version`` キー欠落 / 型不正の双方を包含する。利用者向け 400 で
        # 原因を返す (= グローバルハンドラ任せにしない、code-reviewer MUST 修正)。
        raise HTTPException(status_code=400, detail=str(e)) from e
    return data


@router.post("")
async def create_model(request: Request) -> dict[str, str]:
    """新規モデルを作成。body は ``.flw.json`` 形式の JSON。``metadata.name`` から
    ``model_id`` を派生 (無ければ衝突しないファイル名を自動採番)。"""
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")
    md = _model_dir(request)
    md.mkdir(parents=True, exist_ok=True)

    name = payload.get("metadata", {}).get("name")
    if isinstance(name, str) and name:
        candidate = name
        try:
            validate_model_id(candidate)
        except BlockSpecError:
            candidate = "model"
    else:
        candidate = "model"

    # 衝突検出は ``open(path, "x")`` のアトミックな排他作成で行う (TOCTOU 競合
    # 回避)。FileExistsError なら接尾辞を増やしてリトライ。
    final_name = candidate
    n = 0
    while True:
        path = md / f"{final_name}.flw.json"
        try:
            with open(path, "x", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, indent=2))
            break
        except FileExistsError as e:
            n += 1
            final_name = f"{candidate}_{n}"
            if n > 1000:
                raise HTTPException(
                    status_code=500,
                    detail="Could not allocate a unique model_id",
                ) from e
    return {"model_id": final_name}


@router.put("/{model_id}")
async def update_model(request: Request, model_id: str) -> dict[str, str]:
    """既存モデルを上書き保存。存在しない ``model_id`` には 404 (upsert ではなく
    厳密な update セマンティクス、新規作成は ``POST`` 経由)。"""
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")
    path = _model_path(_model_dir(request), model_id)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Model {model_id!r} not found. Use POST /api/v1/models to create.",
        )
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"model_id": model_id}


@router.delete("/{model_id}")
def delete_model(request: Request, model_id: str) -> dict[str, str]:
    """モデルファイルを削除。"""
    path = _model_path(_model_dir(request), model_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Model {model_id!r} not found")
    path.unlink()
    return {"model_id": model_id, "status": "deleted"}
