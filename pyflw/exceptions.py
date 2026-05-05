"""pyflw 共通例外。

外部に投げる例外は全てここで定義し、各モジュールから import する。
標準例外 (`ValueError`, `RuntimeError` 等) を直接 raise しない方針 (CLAUDE.md)。
"""

from __future__ import annotations


class PyflwError(Exception):
    """pyflw が投げる全例外の基底。"""


class BlockSpecError(PyflwError):
    """ブロック仕様の不正 (ID 衝突、不正文字、`id` と `name` 両方指定など)。"""


class UnknownBlockIdError(PyflwError, KeyError):
    """`Simulator.connect` / `get_block` 等で未登録の ID 文字列が渡された。

    `KeyError` を継承するため `dict[block_id]` 風の使い方とも互換。
    """


class SchedulingError(PyflwError):
    """マルチレートスケジューラの構築不能 (継承解決失敗、`sample_time` 不正値など)。"""


class AlgebraicLoopError(PyflwError):
    """代数ループ検出時に投げる。Phase 0 の `ValueError` を昇格。"""


class SolverError(PyflwError):
    """``scipy.solve_ivp`` の積分失敗 (発散、最大ステップ数超過など)。"""
