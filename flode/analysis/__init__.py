"""線形化と周波数 / 安定性解析機能 (ADR-0026 / ADR-0027)。

公開 API:

- :func:`linearize` (added in ``v0.10.0``) — 動作点 ``(t, x, u)`` 周りで Jacobian を
  中心差分 / 前進差分で数値計算し、状態空間 ``(A, B, C, D)`` を返す。
- :class:`LinearSystem` (added in ``v0.10.0``) — 線形化結果の dataclass
  (numpy 行列 + 状態 / 入出力ラベル + 動作点情報 + ``to_control_ss()`` /
  ``bode()`` / ``nyquist()`` / ``eigenvalues()`` / ``is_stable()`` /
  ``root_locus()`` ヘルパ)。
- :func:`bode` / :func:`nyquist` (added in ``v0.10.1``) — Bode / Nyquist 応答を
  ``python-control`` 経由で計算 (``pyflw[control]`` extras 必須)。
- :func:`eigenvalues` / :func:`is_stable` (added in ``v0.10.1``) — A 行列の固有値と
  漸近安定性判定 (numpy のみ、extras 不要)。
- :func:`root_locus` (added in ``v0.10.1``) — SISO 抽出した根軌跡 (extras 必須)。
- :class:`BodeResponse` / :class:`NyquistResponse` / :class:`RootLocus` —
  対応する解析結果 dataclass (frozen, ndarray + ``plot()``)。

:meth:`pyflw.Simulator.linearize` メソッド経由でも同等の API を提供する。
"""

from .frequency_response import BodeResponse, NyquistResponse, bode, nyquist
from .linearize import LinearSystem, linearize
from .stability import RootLocus, eigenvalues, is_stable, root_locus

__all__ = [
    "BodeResponse",
    "LinearSystem",
    "NyquistResponse",
    "RootLocus",
    "bode",
    "eigenvalues",
    "is_stable",
    "linearize",
    "nyquist",
    "root_locus",
]
