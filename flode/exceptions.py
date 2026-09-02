"""flode 共通例外。

外部に投げる例外は全てここで定義し、各モジュールから import する。
標準例外 (`ValueError`, `RuntimeError` 等) を直接 raise しない方針 (CLAUDE.md)。
"""

from __future__ import annotations


class FlodeError(Exception):
    """flode が投げる全例外の基底。

    Args:
        block_id: 失敗の関与ブロック ID (ADR-0056)。ブロックが特定できる raise 箇所
            (= From/Goto 解決、ブロック単位の validation 等) は keyword で付与でき、
            サーバ層 ``build_failure_payload`` が構造化エラー payload の ``block_id``
            に展開する (= UI の Log tab からそのブロックへジャンプ可能になる)。
            ブロックが特定できない raise 箇所は省略してよい (= ``None``)。
    """

    def __init__(self, *args: object, block_id: str | None = None) -> None:
        super().__init__(*args)
        self.block_id: str | None = block_id


class BlockSpecError(FlodeError):
    """ブロック仕様の不正 (ID 衝突、不正文字、`id` と `name` 両方指定など)。"""


class BlockEvalError(FlodeError):
    """ブロック ``output(t, x, u)`` 内のドメインエラー。

    ``__init__`` 構築時の仕様違反は ``BlockSpecError``、ソルバ起因の数値破綻は
    ``SolverError`` を使う。本クラスは「ブロック構築は正しいが、実行時の入力
    値・状態がブロック固有の許容ドメイン外」という意味の runtime 例外に使う。

    ``block_id`` kwarg を継承するため、ADR-0056 構造化エラー protocol で
    UI の Log tab から発生ブロックへジャンプ可能になる。
    """


class PythonFunctionSourceError(BlockSpecError):
    """``PythonFunction`` のソースが静的解析で受理できない (SPEC-0023 / ADR-0073 §論点 2-E)。

    構文エラー (``kind="syntax"``) と仕様違反 (``kind="spec"``: ``@block`` が 0 / 2 個以上、
    非リテラルのデコレータ引数、語彙外の型注釈、class 形など) の両方を表す。
    introspect API はこの属性を inline エラー表示 (行・列) に使う。

    Args:
        message: 説明文。
        kind: ``"syntax"`` または ``"spec"``。
        lineno: 1 始まりの行番号 (特定できないときは ``None``)。
        col: 1 始まりの列番号 (特定できないときは ``None``)。
    """

    def __init__(
        self,
        message: str,
        *,
        kind: str = "spec",
        lineno: int | None = None,
        col: int | None = None,
        block_id: str | None = None,
    ) -> None:
        super().__init__(message, block_id=block_id)
        self.kind: str = kind
        self.lineno: int | None = lineno
        self.col: int | None = col


class PythonFunctionRewriteError(BlockSpecError):
    """``PythonFunction`` の静的ソース書き換えが適用できない (SPEC-0024 / ADR-0074)。

    構文的に書き換え不能なソース (``kind="unsupported"``)、または書き換え結果の
    自己検証 (W3: 再解析して要求構造と突合) が失敗した場合 (``kind="verify"``) に
    投げられる。**元コードは一切変更されない** (呼び出し側は成功時のみ新コードを得る)。

    Args:
        message: 説明文。
        kind: ``"syntax"`` / ``"spec"`` / ``"unsupported"`` / ``"verify"``。
        lineno: 1 始まりの行番号 (特定できないときは ``None``)。
        col: 1 始まりの列番号 (特定できないときは ``None``)。
    """

    def __init__(
        self,
        message: str,
        *,
        kind: str = "unsupported",
        lineno: int | None = None,
        col: int | None = None,
        block_id: str | None = None,
    ) -> None:
        super().__init__(message, block_id=block_id)
        self.kind: str = kind
        self.lineno: int | None = lineno
        self.col: int | None = col


class PythonBlocksDisabledError(BlockSpecError):
    """``PythonFunction`` の実行がプロセス policy で禁止されている (ADR-0073 §論点 4 hard gate)。

    非 loopback アドレスに bind したサーバで ``--allow-python-blocks`` が無い場合など。
    ``_build()`` (= ``exec`` の直前) で投げられ、モデルを開くだけでは発生しない。
    """


class PythonFunctionEvalError(BlockEvalError):
    """``PythonFunction`` のユーザーコードが実行時に例外を投げた (ADR-0073 §論点 6)。

    flode 内部フレームを除いたユーザーコード側の traceback を保持し、
    ADR-0056 のログタブに「N 行目: <該当行>」として表示する。

    Args:
        message: ``"<ExcType>: <msg>"`` 形式の説明文。
        lineno: ユーザーコード内で実際に落ちた行 (1 始まり)。不明なら ``None``。
        source_line: その行のソーステキスト。不明なら ``None``。
        user_traceback: ユーザーコードのフレームだけを整形した traceback 文字列。
    """

    def __init__(
        self,
        message: str,
        *,
        lineno: int | None = None,
        source_line: str | None = None,
        user_traceback: str = "",
        block_id: str | None = None,
    ) -> None:
        super().__init__(message, block_id=block_id)
        self.lineno: int | None = lineno
        self.source_line: str | None = source_line
        self.user_traceback: str = user_traceback


class UnknownBlockIdError(FlodeError, KeyError):
    """`Simulator.connect` / `get_block` 等で未登録の ID 文字列が渡された。

    `KeyError` を継承するため `dict[block_id]` 風の使い方とも互換。
    """


class SchedulingError(FlodeError):
    """マルチレートスケジューラの構築不能 (継承解決失敗、`sample_time` 不正値など)。"""


class AlgebraicLoopError(FlodeError):
    """代数ループ検出時に投げる。Phase 0 の `ValueError` を昇格。

    Args:
        message: 説明文。``str(exc)`` で取得できる。
        block_ids: 代数ループに関与しているブロック ID 配列 (ADR-0056 §C-3)。
            UI 側で「Diagram で表示」ボタンが全関与ブロックを選択表示するため、
            検出ロジック (``Simulator._execution_order``) が解決済リストを渡す。
            ``None`` のときは空リスト扱い (= 旧互換)。
    """

    def __init__(self, message: str, *, block_ids: list[str] | None = None) -> None:
        super().__init__(message)
        self.block_ids: list[str] = list(block_ids) if block_ids else []


class SolverError(FlodeError):
    """``scipy.solve_ivp`` の積分失敗 (発散、最大ステップ数超過など)。"""


class ModelLoadError(FlodeError):
    """``Simulator.load`` 失敗の基底 (ADR-0008)。

    JSON パースエラー、schema 違反、ブロック type 解決失敗などを表す。
    """


class SchemaVersionError(ModelLoadError):
    """``schema_version`` がサポート対象外、または migration が定義されていない。"""


class UnknownBlockTypeError(ModelLoadError):
    """``type`` 文字列に対応する ``Block`` サブクラスが解決できない。"""


class ModelSerializationError(FlodeError):
    """``Simulator.save`` 失敗の基底 (ADR-0008)。

    ブロックパラメータが JSON-serializable でない場合などに発生する。
    """


class SimulationStillRunningError(FlodeError):
    """シミュレーションがまだ実行中で、結果が取得できない (ADR-0011)。"""


class LibraryFileError(FlodeError):
    """``.flwlib.json`` の load / 検証失敗 (ADR-0029)。

    schema_version 未対応、必須キー欠落、subsystem body 解釈失敗などを表す。
    """


class LibraryEntryNotFoundError(FlodeError, KeyError):
    """REST `GET /api/v1/libraries/{lib}/{entry}` で未登録の id が指定された (ADR-0029)。

    ``KeyError`` を継承するため、library / entry を dict 風に扱う code でも互換。
    """


class PathTraversalError(FlodeError):
    """workspace root 外への path 解決を試みたか、不正文字を含む path (ADR-0041)。

    REST `/api/v1/files/*` で利用者が渡す path を ``resolve_workspace_path`` で
    検証する際に投げられる。HTTP 層では 403 にマップされる。
    """


class BufferOverflowWarning(UserWarning):
    """``Scope.buffer_mode = "bounded"`` で capacity に達した直後に 1 回だけ発火 (ADR-0042 §2)。

    ``ring`` mode では古い sample が黙って drop されるが、``bounded`` mode は
    「ユーザーが明示的に上限を超えたら警告ほしい」用途。``unbounded`` mode は
    ``buffer_capacity`` を持たないので警告対象外。
    """
