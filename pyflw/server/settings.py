"""サーバ設定 (ADR-0011 §(6))。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    """``create_app`` に渡す設定。

    Attributes:
        model_dir: ``.flw.json`` を置くディレクトリ。サーバ起動時に存在しなければ
            ``mkdir -p`` 相当で作成する。
        scope_batch_size: WebSocket での Scope データ送信のバッチサイズ
            (default 100、ADR-0011 §(2))。
        max_concurrent: 同時実行可能なシミュレーション数 (default 4)。
        allow_origins: CORS 許可オリジン (default 空 = CORS 無効)。
            Frontend 別ホスト開発時に opt-in。
    """

    model_dir: Path
    scope_batch_size: int = 100
    max_concurrent: int = 4
    allow_origins: list[str] = field(default_factory=list)
