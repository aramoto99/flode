"""ベクトル状態ブロック共通の ``*_v`` (ADR-0079 §(5) D-7 / 7a')。

``Integrator`` / ``Derivative`` / ``UnitDelay`` / ``DiscreteIntegrator`` /
``RateTransition`` / ``ZeroOrderHoldDirect`` / ``RateLimiter`` は
:class:`VectorStateMixin` を継承し、テンソル対応の計算を ``_output_k`` /
``_derivative_k`` / ``_update_k`` / ``_advance_k`` (kernel) に書く。SM-A の
``output`` / ``derivative`` / ``update`` / ``advance`` は **1 バイトも変えない**
(D-5: 既存モデルの bit 不変)。

契約:

- 状態の格納は常に flat float64 ``(n_states,)`` (``_state_layout`` / ``solve_ivp``
  の契約は不変)。``n_states = _state_slots * prod(state_shape)``。
  ADR-0015 / ADR-0078 の 2-state 配置 (``_state_slots = 2``) では
  ``x[:n]`` = 表示用、``x[n:]`` = 真の状態で、kernel には ``x.reshape((2, *shape))``
  が渡る (``xs[0]`` / ``xs[1]``)。1-state は ``x.reshape(shape)``
- ``x0`` が rank-0 (スカラ既定) のときは **入力 shape へスカラ拡張** する (7a'):
  信号面解決器が plan で state shape を確定し、``Simulator._apply_plan_to_blocks``
  が ``_apply_state_shape(shape)`` で ``n_states`` / ``x0`` を再設定する。
  非 rank-0 の ``x0`` は完全一致を要求 (解決器の ``state`` 規則)
- kernel の ``u`` は各入力ポートの ndarray のタプル (rank-0 は state shape に
  broadcast して使う: ``_u_state``)
- 全入力が rank-0 のとき kernel の結果は SM-A 版と bit-identical であること
  (``tests/blocks/test_vector_state.py``)
- 永続化: ``_params["x0"]`` はユーザー指定値 (スカラなら float、配列なら
  ndarray → JSON では list)。実効 state shape は JSON に書かない (D-2)
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar

import numpy as np
import numpy.typing as npt

from ..exceptions import BlockSpecError

#: ``x0`` 引数の受理型 (スカラ / 入れ子 list / ndarray)。
X0Like = float | int | Sequence[Any] | npt.NDArray[Any]


class VectorStateMixin:
    """``output_v`` / ``derivative_v`` / ``update_v`` / ``advance_v`` を kernel へ委譲する mixin。

    MRO 上は ``Block`` の **前** に置く (``class Integrator(VectorStateMixin, Block)``)。
    leaf は ``output`` (SM-A、不変) と kernel だけを定義するので、``Block.__init__`` の
    dual-override 検査 (``output`` / ``output_v`` の leaf 同時定義禁止) に掛からない。
    """

    #: ADR-0015 / ADR-0078 の 2-state 配置なら 2、通常は 1。
    _state_slots: ClassVar[int] = 1

    # Block が持つ属性 (型ヒントのみ、mypy 用)
    id: str | None
    n_states: int
    state_shape: tuple[int, ...]
    x0: npt.NDArray[Any]

    def _init_vector_state(self, x0: X0Like) -> None:
        """leaf の ``__init__`` から呼ぶ: ``x0`` を記録し、その shape で状態を確定する。"""
        try:
            arr = np.asarray(x0, dtype=float)
        except (TypeError, ValueError) as e:
            raise BlockSpecError(
                f"{type(self).__name__}: x0 must be numeric (scalar or array), got {x0!r}"
            ) from e
        self._x0_value: npt.NDArray[Any] = arr
        self._x0_shape: tuple[int, ...] = tuple(int(d) for d in arr.shape)
        self._apply_state_shape(self._x0_shape)

    def _x0_param(self) -> float | npt.NDArray[Any]:
        """``_params["x0"]`` に書く値 (スカラは float、配列は ndarray = JSON では list)。"""
        if self._x0_shape == ():
            return float(self._x0_value)
        return self._x0_value

    def _apply_state_shape(self, shape: tuple[int, ...]) -> None:
        """実効 state shape を確定し ``n_states`` / ``x0`` (flat) を再設定する。

        信号面解決器の plan (``Simulator._apply_plan_to_blocks``) から呼ばれる
        runtime hook。``x0`` が非 rank-0 のときは宣言 shape と一致しなければならない
        (解決器が build 時に拒否するので、ここに来るのは実装ミスのみ)。
        """
        shape = tuple(int(d) for d in shape)
        if self._x0_shape != () and shape != self._x0_shape:
            raise BlockSpecError(
                f"{type(self).__name__} {self.id!r}: state shape {shape} does not match "
                f"the shape of x0 {self._x0_shape}",
                block_id=self.id,
            )
        self.state_shape = shape
        n = int(np.prod(shape, dtype=np.int64)) if shape else 1
        self.n_states = self._state_slots * n
        base = np.broadcast_to(self._x0_value, shape).astype(float).ravel()
        self.x0 = (
            np.concatenate([base] * self._state_slots) if self._state_slots > 1 else base.copy()
        )

    # ---------- kernel 用ヘルパ ----------

    def _reshape_state(self, x: npt.NDArray[Any]) -> npt.NDArray[Any]:
        """flat 状態を kernel 用の shape (``(slots, *shape)`` または ``shape``) に戻す。"""
        arr = np.asarray(x, dtype=float)
        if self._state_slots > 1:
            return arr.reshape((self._state_slots, *self.state_shape))
        return arr.reshape(self.state_shape)

    def _u_state(self, u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        """入力 ndarray を state shape に broadcast する (rank-0 のスカラ拡張、7a')。"""
        return np.broadcast_to(np.asarray(u, dtype=float), self.state_shape)

    # ---------- kernel (leaf が override) ----------

    def _output_k(
        self, t: float, xs: npt.NDArray[Any], u: tuple[npt.NDArray[Any], ...]
    ) -> npt.NDArray[Any]:
        """出力 (state shape の ndarray)。"""
        raise NotImplementedError(f"{type(self).__name__}._output_k not implemented")

    def _derivative_k(
        self, t: float, xs: npt.NDArray[Any], u: tuple[npt.NDArray[Any], ...]
    ) -> npt.NDArray[Any]:
        """状態微分 (kernel shape)。既定はゼロ (離散ブロック)。"""
        return np.zeros_like(xs)

    def _update_k(
        self, t: float, xs: npt.NDArray[Any], u: tuple[npt.NDArray[Any], ...]
    ) -> npt.NDArray[Any]:
        """離散更新 (kernel shape)。既定は恒等 (連続ブロック)。"""
        return xs

    def _advance_k(
        self, t: float, xs: npt.NDArray[Any], u: tuple[npt.NDArray[Any], ...]
    ) -> npt.NDArray[Any]:
        """シフト相 (kernel shape)。既定は恒等 (1-state ブロック)。"""
        return xs

    # ---------- vector-port API ----------

    def output_v(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        return (np.asarray(self._output_k(t, self._reshape_state(x), u)),)

    def derivative_v(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> npt.NDArray[Any]:
        return np.asarray(self._derivative_k(t, self._reshape_state(x), u), dtype=float).ravel()

    def update_v(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> npt.NDArray[Any]:
        return np.asarray(self._update_k(t, self._reshape_state(x), u), dtype=float).ravel()

    def advance_v(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> npt.NDArray[Any]:
        return np.asarray(self._advance_k(t, self._reshape_state(x), u), dtype=float).ravel()
