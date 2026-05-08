"""線形化等の解析機能 (ADR-0026)。

公開 API:

- :func:`linearize` (added in ``v0.10.0``) — 動作点 ``(t, x, u)`` 周りで Jacobian を
  中心差分 / 前進差分で数値計算し、状態空間 ``(A, B, C, D)`` を返す。
- :class:`LinearSystem` (added in ``v0.10.0``) — 線形化結果の dataclass
  (numpy 行列 + 状態 / 入出力ラベル + 動作点情報 + ``to_control_ss()`` ヘルパ)。

:meth:`pyflw.Simulator.linearize` メソッド経由でも同等の API を提供する。
"""

from .linearize import LinearSystem, linearize

__all__ = ["LinearSystem", "linearize"]
