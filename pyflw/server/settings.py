"""サーバ設定 (ADR-0011 §(6) / ADR-0041 §3)。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    """``create_app`` に渡す設定。

    Attributes:
        model_dir: ``.flw.json`` を置くディレクトリ (legacy、ADR-0011 §(6))。
            サーバ起動時に存在しなければ ``mkdir -p`` 相当で作成する。**ADR-0041
            v3.0 で削除予定** — v2.x の間は legacy ``/api/v1/models/*`` route が
            参照する。新規コードは ``workspace_root`` を見ること。
        workspace_root: File API ``/api/v1/files/*`` のルートディレクトリ
            (ADR-0041 §3、v0.15.0 新設)。``None`` の場合 File API は workspace 未
            設定として扱う (= legacy ``--model-dir`` モード)。``--workspace=PATH``
            CLI 引数または ``Settings(workspace_root=...)`` 直接指定で設定。
        scope_batch_size: WebSocket での Scope データ送信のバッチサイズ
            (default 100、ADR-0011 §(2))。
        max_concurrent: 同時実行可能なシミュレーション数 (default 4)。
        allow_origins: CORS 許可オリジン (default 空 = CORS 無効)。
            Frontend 別ホスト開発時に opt-in。
        library_paths: ``.flwlib.json`` のロード対象 path リスト (ADR-0029、v0.11.1)。
            ファイル / ディレクトリのいずれも可 (ディレクトリの場合は ``*.flwlib.json``
            を再帰的に検索する) 。空リスト + ``bundle_builtin_libraries=True`` だけでも
            組み込み ``std`` が利用可能になる。
        bundle_builtin_libraries: 組み込み ``pyflw/libraries/std.flwlib.json`` を
            自動的に library registry に追加するか (default ``True``、ADR-0029 §LOC-A)。
    """

    model_dir: Path
    workspace_root: Path | None = None
    scope_batch_size: int = 100
    max_concurrent: int = 4
    allow_origins: list[str] = field(default_factory=list)
    library_paths: list[Path] = field(default_factory=list)
    bundle_builtin_libraries: bool = True
