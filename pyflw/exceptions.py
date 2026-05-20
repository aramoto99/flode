"""pyflw 共通例外。

外部に投げる例外は全てここで定義し、各モジュールから import する。
標準例外 (`ValueError`, `RuntimeError` 等) を直接 raise しない方針 (CLAUDE.md)。
"""

from __future__ import annotations


class PyflwError(Exception):
    """pyflw が投げる全例外の基底。

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


class BlockSpecError(PyflwError):
    """ブロック仕様の不正 (ID 衝突、不正文字、`id` と `name` 両方指定など)。"""


class UnknownBlockIdError(PyflwError, KeyError):
    """`Simulator.connect` / `get_block` 等で未登録の ID 文字列が渡された。

    `KeyError` を継承するため `dict[block_id]` 風の使い方とも互換。
    """


class SchedulingError(PyflwError):
    """マルチレートスケジューラの構築不能 (継承解決失敗、`sample_time` 不正値など)。"""


class AlgebraicLoopError(PyflwError):
    """代数ループ検出時に投げる。Phase 0 の `ValueError` を昇格。

    Args:
        message: 説明文。``str(exc)`` で取得できる。
        block_ids: 代数ループに関与しているブロック ID 配列 (ADR-0056 §C-3)。
            UI 側で「Diagram で表示」ボタンが全関与ブロックを選択表示するため、
            検出ロジック (``Simulator._execution_order``) が解決済リストを渡す。
            ``None`` のときは空リスト扱い (= 旧互換)。
    """

    def __init__(
        self, message: str, *, block_ids: list[str] | None = None
    ) -> None:
        super().__init__(message)
        self.block_ids: list[str] = list(block_ids) if block_ids else []


class SolverError(PyflwError):
    """``scipy.solve_ivp`` の積分失敗 (発散、最大ステップ数超過など)。"""


class ModelLoadError(PyflwError):
    """``Simulator.load`` 失敗の基底 (ADR-0008)。

    JSON パースエラー、schema 違反、ブロック type 解決失敗などを表す。
    """


class SchemaVersionError(ModelLoadError):
    """``schema_version`` がサポート対象外、または migration が定義されていない。"""


class UnknownBlockTypeError(ModelLoadError):
    """``type`` 文字列に対応する ``Block`` サブクラスが解決できない。"""


class ModelSerializationError(PyflwError):
    """``Simulator.save`` 失敗の基底 (ADR-0008)。

    ブロックパラメータが JSON-serializable でない場合などに発生する。
    """


class SimulationStillRunningError(PyflwError):
    """シミュレーションがまだ実行中で、結果が取得できない (ADR-0011)。"""


class LibraryFileError(PyflwError):
    """``.flwlib.json`` の load / 検証失敗 (ADR-0029)。

    schema_version 未対応、必須キー欠落、subsystem body 解釈失敗などを表す。
    """


class LibraryEntryNotFoundError(PyflwError, KeyError):
    """REST `GET /api/v1/libraries/{lib}/{entry}` で未登録の id が指定された (ADR-0029)。

    ``KeyError`` を継承するため、library / entry を dict 風に扱う code でも互換。
    """


class PathTraversalError(PyflwError):
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
