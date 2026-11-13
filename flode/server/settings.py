"""サーバ設定 (ADR-0011 §(6) / ADR-0041 §3、v0.21.0 で legacy ``model_dir`` を削除)。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..userblocks import LoadRequest


@dataclass
class Settings:
    """``create_app`` に渡す設定。

    Attributes:
        workspace_root: File API ``/api/v1/files/*`` のルートディレクトリ
            (ADR-0041 §3、v0.15.0 新設、v0.21.0 で必須化)。``--workspace=PATH``
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
        bundle_builtin_libraries: 組み込み ``flode/libraries/std.flwlib.json`` を
            自動的に library registry に追加するか (default ``True``、ADR-0029 §LOC-A)。
        python_blocks_allowed: ``PythonFunction`` の実行可否 (SPEC-0023 / ADR-0073 hard gate)。
            ``create_app`` がプロセス policy に適用する。CLI は bind host とフラグから
            決めた値を入れる (loopback → True、非 loopback はフラグ必須)。``create_app`` を
            直接使う埋め込み利用者は **公開 bind なら必ず False にする** こと。
        python_blocks_reason: 拒否理由 (エラーメッセージに埋め込む、``allowed=False`` 時のみ)。
        user_blocks_enabled: ワークスペース ``blocks/`` と config ``[blocks]`` のユーザーブロックを
            起動時に読むか (ADR-0081 §論点 6)。**既定 ``False`` (fail-closed)**: ``create_app`` を
            直接使う場合は明示しない限り読まない。CLI は bind host と ``--allow-user-blocks`` /
            ``[blocks] allow_non_loopback`` から決めた値を入れる。
        user_blocks_reason: 読まない理由 (``GET /blocks`` の ``user_blocks.reason``)。
        user_blocks_reload_allowed: ``POST /blocks/reload`` を受け付けるか。``loopback_bind`` が
            ``False`` なら値に関係なく受け付けない (非 loopback では許可があっても 403)。
        user_blocks_request: 読み込む管理ソース。``None`` で ``user_blocks_enabled=True`` なら
            ``workspace_root`` の ``blocks/`` だけを読む (``dirs`` / ``modules`` なし)。
            ``user_blocks_enabled=False`` でも、非 loopback の files API で守るルート
            (``dirs`` / ``modules`` の実体) の計算に使う (CLI は常に入れる)。
        loopback_bind: bind host が loopback であることを呼び出し側が確認済みか。**既定 ``False``
            (fail-closed)**: ``False`` の間は ``GET /blocks`` の絶対パスを伏せ、files API による
            ワークスペース ``blocks/`` 配下の変更と再読み込みを 403 にする。
    """

    workspace_root: Path
    scope_batch_size: int = 100
    max_concurrent: int = 4
    allow_origins: list[str] = field(default_factory=list)
    library_paths: list[Path] = field(default_factory=list)
    bundle_builtin_libraries: bool = True
    python_blocks_allowed: bool = True
    python_blocks_reason: str = ""
    user_blocks_enabled: bool = False
    user_blocks_reason: str = ""
    user_blocks_reload_allowed: bool = False
    user_blocks_request: LoadRequest | None = None
    loopback_bind: bool = False
