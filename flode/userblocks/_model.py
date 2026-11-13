"""ユーザーブロック読み込みの公開データ型 (ADR-0081 §論点 8-A / §論点 9)。

すべて不変 (frozen) の dataclass。``BlockLoadReport`` は読み込み / 再読み込み 1 回分の結果で、
server (U3) は ``GET /blocks`` の ``sources`` / ``load_errors`` と
``POST /blocks/reload`` の応答をここから組み立てる。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

#: 読み込みエラーの種別 (REST ``load_errors[].kind`` と同じ語彙、ADR-0081 §8-A)。
LoadErrorKind = Literal["syntax", "import", "spec", "conflict", "config"]
#: ``"info"`` は動作に影響しない告知 (ルートの ``__init__.py`` を実行しない等)。
#: ``strict=True`` の判定・エラー件数には数えない。
LoadErrorSeverity = Literal["error", "info"]
SourceKind = Literal["workspace", "dir", "module"]
FileStatus = Literal["ok", "error"]

#: 読み込み元 id (``SourceInfo.id`` / ``LoadError.source`` / ``UserBlockInfo.source``)。
WORKSPACE_SOURCE_ID = "workspace"
DIR_SOURCE_PREFIX = "dir:"
MODULE_SOURCE_PREFIX = "module:"


@dataclass(frozen=True)
class LoadError:
    """読み込みエラー 1 件 (ファイル単位またはブロック単位)。

    Attributes:
        source: 読み込み元 id (``"workspace"`` / ``"dir:<name>"`` / ``"module:<module>"``)。
        path: 表示用の相対パス (ワークスペースは ``"blocks/foo.py"``、``dirs`` はそのフォルダ
            からの相対、``modules`` と読み込み元全体のエラーは ``None``)。区切りは ``/``。
        line: 1 始まりの行番号 (特定できなければ ``None``)。
        kind: 種別。
        message: 説明文 (外部由来の文字列を含むので長さを制限済み)。
        severity: ``"error"`` または ``"info"``。
        type_path: ブロック単位のエラーなら対象の型名、ファイル単位なら ``None``。
    """

    source: str
    path: str | None
    line: int | None
    kind: LoadErrorKind
    message: str
    severity: LoadErrorSeverity = "error"
    type_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON にそのまま載せられる dict (REST ``load_errors[]`` の要素) を返す。"""
        return {
            "source": self.source,
            "path": self.path,
            "line": self.line,
            "kind": self.kind,
            "message": self.message,
            "severity": self.severity,
            "type_path": self.type_path,
        }


@dataclass(frozen=True)
class SourceFile:
    """読み込み元で走査したファイル 1 件 (``path`` は読み込み元ルートからの相対、``/`` 区切り)。"""

    path: str
    status: FileStatus


@dataclass(frozen=True)
class SourceInfo:
    """読み込み元 1 件の情報 (REST ``sources[]`` の材料)。

    Attributes:
        id: 読み込み元 id。
        kind: ``"workspace"`` / ``"dir"`` / ``"module"``。
        label: 表示名 (ワークスペースは ``"blocks/"``、``dirs`` は名前、``modules`` はモジュール名)。
        root: 読み込み元のフォルダの絶対パス (``modules`` は ``None``)。
        reloadable: 再読み込みの対象か (``modules`` は ``False``、ADR-0081 Q5a)。
        files: 走査したファイルと状態 (``modules`` は空)。
        from_cwd: ワークスペースが起動時の cwd から決まったか (ログ表示用、R-1)。
    """

    id: str
    kind: SourceKind
    label: str
    root: str | None
    reloadable: bool
    files: tuple[SourceFile, ...] = ()
    from_cwd: bool = False


@dataclass(frozen=True)
class UserParamSpec:
    """ユーザーブロックの引数 1 つ (Inspector 用、ADR-0081 §論点 7)。

    Attributes:
        name: 引数名。
        type: 型の表示ラベル (注釈なしは ``"any"``)。
        default: JSON 往復済みの既定値 (パレットから置いたときに entry に書かれる値)。
        description: 引数の説明 (明示 ``param_descriptions`` > docstring ``Args:``)。
        choices: 選択肢 (宣言が無ければ ``None``)。
    """

    name: str
    type: str
    default: Any
    description: str = ""
    choices: tuple[str, ...] | None = None


@dataclass(frozen=True)
class UserBlockInfo:
    """読み込めたユーザーブロック 1 つのメタデータ。

    ``block_class`` 以外の全フィールドの一致で「定義が変わっていない」と判定する
    (再読み込みの ``changed``、ADR-0081 §2-A 手順 7)。ハッシュ不可 (dict / list を含む)。

    Attributes:
        type_path: 型名 (``flode_ws.filters.MovingAverage`` 等)。
        class_name: クラス名 (型名の最後の区切り)。
        source: 読み込み元 id。
        module: 定義モジュール名。
        path: 定義ファイルの表示用相対パス (``modules`` は ``None``)。
        display_name: 表示名 (``Mapping`` で宣言された場合は ``en``、無ければ最初の値)。
        display_name_i18n: ``Mapping`` で宣言された表示名 (無ければ空)。
        description: 説明 (明示 > docstring の 1 行目)。
        description_i18n: ``Mapping`` で宣言された説明 (無ければ空)。
        docstring: クラス自身の docstring (``inspect.cleandoc`` 済み、無ければ空)。
        category: 宣言カテゴリ (未宣言は ``None`` = セクション直下)。
        params: 引数の一覧 (宣言順)。
        n_inputs: 既定値でインスタンス化したときの入力ポート数。
        n_outputs: 同出力ポート数。
        n_states: 同状態数。
        direct_feedthrough: 同直達フラグ。
        port_shapes_in: 同入力ポートの宣言 shape。
        port_shapes_out: 同出力ポートの宣言 shape。
        input_names: 入力ポート名 (空 = 無名)。
        output_names: 出力ポート名 (空 = 無名)。
        block_class: クラス本体 (比較対象外)。
    """

    type_path: str
    class_name: str
    source: str
    module: str
    path: str | None
    display_name: str
    display_name_i18n: Mapping[str, str]
    description: str
    description_i18n: Mapping[str, str]
    docstring: str
    category: str | None
    params: tuple[UserParamSpec, ...]
    n_inputs: int
    n_outputs: int
    n_states: int
    direct_feedthrough: bool
    port_shapes_in: tuple[tuple[int, ...], ...]
    port_shapes_out: tuple[tuple[int, ...], ...]
    input_names: tuple[str, ...]
    output_names: tuple[str, ...]
    block_class: type = field(compare=False, repr=False)


@dataclass(frozen=True)
class LoadRequest:
    """読み込む管理ソースの指定 (``flode.load_blocks`` と server の共通入力)。

    Attributes:
        workspace: ワークスペースのフォルダ (``<workspace>/blocks/`` を ``flode_ws`` として読む)。
            ``None`` ならワークスペースは読まない。
        workspace_from_cwd: ワークスペースが明示されず起動時の cwd から決まったか。``True`` で
            ホームディレクトリそのもの・ファイルシステムのルートなら読まない (ADR-0081 §R-1)。
        dirs: ``(名前, フォルダ)`` の列 (記述順)。``flode_dirs.<名前>`` として読む。
        modules: インストール済みモジュール名の列 (記述順)。
    """

    workspace: Path | None = None
    workspace_from_cwd: bool = False
    dirs: tuple[tuple[str, Path], ...] = ()
    modules: tuple[str, ...] = ()


@dataclass(frozen=True)
class BlockLoadReport:
    """読み込み / 再読み込み 1 回分の結果 (ADR-0081 §論点 9)。

    Attributes:
        blocks: 読み込めたブロックの型名 (昇順)。
        block_infos: 読み込めたブロックのメタデータ (``blocks`` と同じ順)。
        errors: 読み込みエラー (``severity="info"`` を含む)。
        sources: 読み込み元 (ワークスペース → ``dirs`` → ``modules`` の順)。
        added: 前回の状態から増えた型名。
        removed: 前回の状態から消えた型名。
        changed: 両方にあり、メタデータが変わった型名。
        restart_required_sources: 再読み込みの対象外で、反映にプロセス再起動が要る読み込み元 id
            (``modules``)。
    """

    blocks: tuple[str, ...] = ()
    block_infos: tuple[UserBlockInfo, ...] = ()
    errors: tuple[LoadError, ...] = ()
    sources: tuple[SourceInfo, ...] = ()
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()
    restart_required_sources: tuple[str, ...] = ()

    @property
    def error_count(self) -> int:
        """``severity="error"`` の件数 (``"info"`` は数えない)。"""
        return sum(1 for e in self.errors if e.severity == "error")
