"""離散時間ブロック。

実装ブロック:

* ``UnitDelay`` — 1 サンプル遅延 ``y[k+1] = u[k]`` (Simulink UnitDelay 互換、ADR-0014)
* ``DiscreteIntegrator`` — 前進 Euler 積分 ``x[k+1] = x[k] + T*gain*u[k]``
* ``ZeroOrderHoldDirect`` — Simulink ZOH 互換 ``y(t_k) = u(t_k)`` (ADR-0010 §(4) /
  ADR-0014 §(3))
* ``DiscreteStateSpace`` — 離散 LTI ``x[k+1] = A_d x[k] + B_d u[k]`` (ADR-0006)
* ``DiscreteTransferFunction`` — 離散 LTI ``H(z) = num(z)/den(z)`` (ADR-0006)

``Memory`` は ``UnitDelay`` と意味論が同一のため別実装しない。
``FirstOrderHold`` / 高次離散ブロックは Phase 5+ 以降。

.. note::

   v0.13.0 (ADR-0033) で ``ZeroOrderHold`` (legacy) を削除した。v0.5.0 (ADR-0014
   §(4)) から `DeprecationWarning` を発出していた 2-state state-based ホールドで、
   ADR-0014 適用後は ``UnitDelay`` と完全に同一の semantics だった。利用者は
   ``UnitDelay`` (1 サンプル遅延) または ``ZeroOrderHoldDirect`` (Simulink ZOH
   互換、即時反映) に移行すること。
"""

from __future__ import annotations

import logging

import numpy as np
import scipy.signal

from ..core.block import Block
from ..exceptions import BlockSpecError
from ._lti_utils import _DF_TOLERANCE

_zohd_logger = logging.getLogger("pyflw.blocks.discrete")


class UnitDelay(Block):
    """1 サンプル遅延 ``y[k+1] = u[k]`` (Simulink UnitDelay 互換、ADR-0014/0015)。

    Internal state (n_states=2):
        x[0] = output_curr  -- 現サンプルでの出力 (``output(t, x, u)`` が返す値)
        x[1] = output_next  -- 次サンプル境界で x[0] にシフトされる buffer

    Simulator は ``k % step_ratio == 0`` のサンプル境界で ``update(t, x, u)`` を
    呼び、``x_next = [x[1], u[0]]`` (= state[0] ← 前 buffer、state[1] ← 現入力)
    を保存する (ADR-0015 §(1)(2))。

    multi-rate (sample_time > dt_base) でも Simulink semantics と完全一致する。
    ADR-0014 で残った multi-rate 1 dt_base off-by-one は ADR-0015 で根本解決済み。

    ``direct_feedthrough=False`` なので閉ループ内で代数ループを切る用途にも使える。

    Args:
        sample_time: サンプル周期 [s]。``> 0`` 必須 (継承 ``-1.0`` も可)。
        x0: 初期状態 (= t=0 での出力値)。内部では state[0]=state[1]=x0 に展開する。
    """

    def __init__(
        self,
        *,
        sample_time: float,
        x0: float = 0.0,
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(
            id=id,
            name=name,
            n_inputs=1,
            n_outputs=1,
            n_states=2,
            direct_feedthrough=False,
            sample_time=sample_time,
        )
        # ADR-0015 §(2): state[0]=output_curr, state[1]=output_next。
        # 初期状態は両 state を ``x0`` で埋める (t=0 での出力 = x0、最初のサンプル
        # 境界で fire するまで buffer も x0)。
        self.x0 = np.array([float(x0), float(x0)])
        # JSON serialize 時は scalar の ``x0`` を保持 (ADR-0015 §(4))。
        self._params = {"sample_time": float(sample_time), "x0": float(x0)}

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.array([x[0]])

    def update(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        # state[0] ← 前回の state[1] (前サンプルで保存した値が現サンプルで visible)
        # state[1] ← u(t_k) (次サンプルで output される値)
        return np.array([x[1], u[0]])


class DiscreteIntegrator(Block):
    """前進 Euler 離散積分 ``x[k+1] = x[k] + sample_time * gain * u[k]``、出力 ``y[k] = x[k]`` (Simulink 互換)。

    Internal state (n_states=2、ADR-0015 §(3) で 2-state augmentation):
        x[0] = output_curr  -- 現サンプル境界での出力 (前回 fire で確定済み)
        x[1] = next_x       -- 次サンプル境界で x[0] にシフトされる buffer

    ``direct_feedthrough=False`` (出力は前ステップ確定状態のみ参照) なので
    閉ループ内の代数ループ切断にも使える。

    Args:
        sample_time: サンプル周期 [s]。``> 0`` 必須 (継承 ``-1.0`` も可)。
        gain: 入力に掛けるゲイン (積分定数)。
        x0: 初期状態。内部では state[0]=state[1]=x0 に展開する。
    """

    def __init__(
        self,
        *,
        sample_time: float,
        gain: float = 1.0,
        x0: float = 0.0,
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(
            id=id,
            name=name,
            n_inputs=1,
            n_outputs=1,
            n_states=2,
            direct_feedthrough=False,
            sample_time=sample_time,
        )
        self.gain = float(gain)
        # ADR-0015 §(3): state[0]=output_curr, state[1]=next_x。両方を x0 で埋める
        self.x0 = np.array([float(x0), float(x0)])
        # JSON serialize 時は scalar の x0 を維持 (ADR-0015 §(4))
        self._params = {
            "sample_time": float(sample_time),
            "gain": self.gain,
            "x0": float(x0),
        }

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.array([x[0]])

    def update(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        # ステップ幅は **解決後の sample_time** を使う (継承時の動的解決に対応)。
        # Simulator 経由なら ``_resolve_sample_times`` で必ず確定する。直接呼びだ
        # された場合や未登録の状態では `BlockSpecError` で明示する (silent zero-step
        # を返さない: 無音バグ防止)。
        ts = self._resolved_sample_time
        if ts is None or ts <= 0.0:
            raise BlockSpecError(
                f"DiscreteIntegrator {self.id!r}: sample_time has not been resolved. "
                "Add this block to a Simulator and call `run()` (or invoke "
                "`_resolve_sample_times`) before calling update() directly."
            )
        # ADR-0015 §(3) 2-state augmentation の semantics:
        # - x[1] は「累積最新値 = 標準形の x[k]」。fire のたびに ``T*g*u(t)`` を加算する
        # - x[0] は「output 用スナップショット = x[k-1]」。fire 時に旧 x[1] からシフト
        # 次回 fire で state[0] ← state[1] (シフト)、state[1] ← state[1] + T*g*u (=
        # 累積継続)。state[1] からの再帰更新は v0.3.0 1-state Forward Euler の連続性
        # を保つために必須 (state[0] からの計算は invariant `state[0] = state[1]` が
        # 初期境界以外で崩れ、累積が 1 step ずれるため不可)。
        return np.array([x[1], x[1] + ts * self.gain * u[0]])


# ADR-0014 §(3): サンプル時刻判定の許容誤差。整数比カウンタで決まる
# `_resolved_sample_time` の倍数からのずれを許容する閾値。Simulator の
# `_SAMPLE_TIME_RATIO_TOL = 1e-9` と整合。
_ZOH_SAMPLE_TOL = 1e-9


class ZeroOrderHoldDirect(Block):
    """Simulink ZOH 互換 ``y(t_k) = u(t_k)`` の即時反映ホールド (ADR-0014 §(3))。

    サンプル時刻 ``t_k`` で現入力 ``u(t_k)`` を出力に即時反映し、次サンプル時刻まで
    保持する。連続→ZOHDirect→連続のフローでも、中間時刻 ``t ∈ (t_k, t_{k+1})``
    では前回サンプル値を保持する (= 階段関数として下流の連続ブロックに渡る)。

    実装 (ADR-0014 §(3)):
      * ``direct_feedthrough=True``、``n_states=1``
      * ``output(t, x, u)``: ``t`` が ``_resolved_sample_time`` の整数倍 (tol 1e-9)
        ならば現入力 ``u`` を返し、それ以外 (中間時刻) は前回保存値 ``x`` を返す
      * ``update(t, x, u)``: サンプル時刻でのみ呼ばれ、``x_next = u`` で保存

    UnitDelay との違い: ZOHDirect は遅延が無い (``y(t_0) = u(t_0)``)。UnitDelay は
    1 サンプル遅延する (``y(t_0) = x0``、``y(t_{k+1}) = u(t_k)``)。

    Args:
        sample_time: サンプル周期 [s]。``> 0`` 必須 (継承 ``-1.0`` も可)。
        x0: 初回サンプル前のフォールバック値。t=0 がサンプル時刻なら直ちに
            ``u(0)`` で上書きされるため、通常はテスト結果に影響しない。
    """

    def __init__(
        self,
        *,
        sample_time: float,
        x0: float = 0.0,
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(
            id=id,
            name=name,
            n_inputs=1,
            n_outputs=1,
            n_states=1,
            direct_feedthrough=True,
            sample_time=sample_time,
        )
        self.x0 = np.array([float(x0)])
        self._params = {"sample_time": float(sample_time), "x0": float(x0)}

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        ts = self._resolved_sample_time
        if ts is None or ts <= 0.0:
            # サンプル時間未解決時は素朴 fallback (継承未解決などの境界条件)。
            # silent failure を避けるため警告ログを残す (Simulator 経由なら通常は発生しない)。
            _zohd_logger.warning(
                "ZeroOrderHoldDirect %r: _resolved_sample_time not set, "
                "falling back to direct passthrough (output=u). "
                "This is expected only outside Simulator.run().",
                self.id,
            )
            return np.array([u[0]])
        n = round(t / ts)
        # 許容誤差は `ts` と `|t|` の双方を下限に持たせる:
        # - `ts` を下限にすることで、短い sample_time × 大きな t で誤判定を防ぐ
        # - `|t|` を上限の一部に持たせることで、t が大きい時の浮動小数累積誤差に対応
        if abs(t - n * ts) <= _ZOH_SAMPLE_TOL * max(ts, abs(t)):
            # サンプル時刻ぴったり: 現入力を即時反映
            return np.array([u[0]])
        # 中間時刻: 前回サンプル値を保持
        return np.array([x[0]])

    def update(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.array([u[0]])


class DiscreteStateSpace(Block):
    """離散 LTI 状態空間 ``x[k+1] = A x[k] + B u[k]``、``y[k] = C x[k] + D u[k]`` (Simulink 互換)。

    ADR-0006 §(5)、ADR-0015 §(3) で 2n-state augmentation。``direct_feedthrough`` は
    ``D`` の最大絶対値が ``1e-12`` を超えるかで自動推論。

    Internal state (n_states=2n、ADR-0015 §(3)):
        x[0..n-1]   = output_curr — 現サンプル境界での状態 (前回 fire で確定)
        x[n..2n-1]  = next_x      — 次サンプル境界で前半にシフトされる buffer

    JSON 表現の ``x0`` は ``(n,)`` shape の scalar 配列のまま (Block 内部で
    ``[x0, x0]`` に展開、ADR-0015 §(4))。

    Args:
        A: 状態行列 (shape ``(n, n)``)。
        B: 入力行列 (shape ``(n, m)``)、``m = n_inputs``。
        C: 出力行列 (shape ``(p, n)``)、``p = n_outputs``。
        D: 直達行列 (shape ``(p, m)``)。``None`` でゼロ。
        sample_time: サンプル周期 [s]、``> 0`` 必須 (継承 ``-1.0`` も可)。
        x0: 初期状態 (shape ``(n,)``)。内部で ``[x0; x0]`` (shape ``(2n,)``) に展開。
    """

    def __init__(
        self,
        A: np.ndarray,
        B: np.ndarray,
        C: np.ndarray,
        D: np.ndarray | None = None,
        x0: np.ndarray | None = None,
        *,
        sample_time: float,
        id: str | None = None,
        name: str | None = None,
    ):
        A_arr = np.asarray(A, dtype=float)
        B_arr = np.asarray(B, dtype=float)
        C_arr = np.asarray(C, dtype=float)
        if A_arr.ndim != 2 or A_arr.shape[0] != A_arr.shape[1]:
            raise BlockSpecError(f"DiscreteStateSpace: A must be square, got shape {A_arr.shape}")
        n = A_arr.shape[0]
        if n == 0:
            raise BlockSpecError(
                "DiscreteStateSpace: n_states=0 (pure gain) is not supported; "
                "use a static block (e.g. Gain) instead"
            )
        if B_arr.ndim != 2 or B_arr.shape[0] != n:
            raise BlockSpecError(
                f"DiscreteStateSpace: B must have shape (n, m) with n={n}, got {B_arr.shape}"
            )
        m = B_arr.shape[1]
        if C_arr.ndim != 2 or C_arr.shape[1] != n:
            raise BlockSpecError(
                f"DiscreteStateSpace: C must have shape (p, n) with n={n}, got {C_arr.shape}"
            )
        p = C_arr.shape[0]
        D_arr: np.ndarray
        if D is None:
            D_arr = np.zeros((p, m))
        else:
            D_arr = np.asarray(D, dtype=float)
            if D_arr.shape != (p, m):
                raise BlockSpecError(
                    f"DiscreteStateSpace: D must have shape ({p}, {m}), got {D_arr.shape}"
                )
        df = bool(np.max(np.abs(D_arr)) > _DF_TOLERANCE) if D_arr.size else False

        # ADR-0015 §(3): 2n-state augmentation で n_states = 2n
        super().__init__(
            id=id,
            name=name,
            n_inputs=m,
            n_outputs=p,
            n_states=2 * n,
            direct_feedthrough=df,
            sample_time=sample_time,
        )
        self._A = A_arr
        self._B = B_arr
        self._C = C_arr
        self._D = D_arr
        self._n = n
        x0_user: np.ndarray
        if x0 is None:
            x0_user = np.zeros(n)
        else:
            x0_arr = np.atleast_1d(np.asarray(x0, dtype=float))
            if x0_arr.shape != (n,):
                raise BlockSpecError(
                    f"DiscreteStateSpace: x0 must have shape ({n},), got {x0_arr.shape}"
                )
            x0_user = x0_arr
        # 内部状態は [x0; x0] の 2n-vector (両半分を x0 で埋める)
        self.x0 = np.concatenate([x0_user, x0_user])
        # JSON serialize 用には scalar 配列の x0_user を保存 (ADR-0015 §(4))
        self._params = {
            "A": A_arr,
            "B": B_arr,
            "C": C_arr,
            "D": D_arr,
            "x0": x0_user,
            "sample_time": float(sample_time),
        }

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        # output は前半 (= output_curr) のみを使う
        x_curr = x[: self._n]
        return np.asarray(self._C @ x_curr + self._D @ u, dtype=float).ravel()

    def update(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        # ADR-0015 §(3) 2n-state augmentation の semantics:
        # - x[n:]  = x[k] (累積最新値、A@x + B@u を毎 fire で適用)
        # - x[:n]  = x[k-1] (output 用スナップショット、fire 時に旧 x[n:] からシフト)
        # 次回 fire で state[:n] ← state[n:]、state[n:] ← A @ state[n:] + B @ u
        # (= 累積継続)。x[:n] からの計算は invariant 崩れ時に標準形の累積が 1 step
        # ずれるため不可 (DiscreteIntegrator と同じ理由、ADR-0015 §(3) 訂正)。
        x_buf = x[self._n :]
        next_buf = np.asarray(self._A @ x_buf + self._B @ u, dtype=float).ravel()
        return np.concatenate([x_buf, next_buf])


class DiscreteTransferFunction(Block):
    """離散 LTI 伝達関数 ``H(z) = num(z) / den(z)`` (SISO、Simulink 互換)。

    ADR-0006 §(4)、ADR-0015 §(3) で 2n-state augmentation。内部で
    ``scipy.signal.tf2ss`` により SS に変換して ``DiscreteStateSpace`` 同等の実装。
    ``deg(num) <= deg(den)`` を要求。

    Internal state (n_states=2n、ADR-0015 §(3)):
        x[0..n-1]  = output_curr
        x[n..2n-1] = next_x

    Args:
        numerator: 分子多項式の係数 (z の降べき)。
        denominator: 分母多項式の係数。
        sample_time: サンプル周期 [s]、``> 0`` 必須。
        x0: 初期状態 (shape ``(len(denominator)-1,)``)。内部で ``[x0; x0]`` に展開。
    """

    def __init__(
        self,
        numerator: np.ndarray | list[float],
        denominator: np.ndarray | list[float],
        x0: np.ndarray | None = None,
        *,
        sample_time: float,
        id: str | None = None,
        name: str | None = None,
    ):
        num = np.asarray(numerator, dtype=float).ravel()
        den = np.asarray(denominator, dtype=float).ravel()
        if num.size == 0 or den.size == 0:
            raise BlockSpecError(
                "DiscreteTransferFunction: numerator/denominator must be non-empty"
            )
        if den[0] == 0.0:
            raise BlockSpecError(
                "DiscreteTransferFunction: leading coefficient of denominator must be non-zero"
            )
        if np.all(num == 0.0):
            raise BlockSpecError("DiscreteTransferFunction: numerator cannot be all zeros")
        if (num.size - 1) > (den.size - 1):
            raise BlockSpecError(
                f"DiscreteTransferFunction: improper system "
                f"(deg(num)={num.size - 1} > deg(den)={den.size - 1}). "
                f"Only proper or biproper systems are supported."
            )

        A, B, C, D = scipy.signal.tf2ss(num, den)
        A = np.atleast_2d(np.asarray(A, dtype=float))
        B = np.atleast_2d(np.asarray(B, dtype=float))
        C = np.atleast_2d(np.asarray(C, dtype=float))
        D = np.atleast_2d(np.asarray(D, dtype=float))
        n = A.shape[0]
        df = bool(np.max(np.abs(D)) > _DF_TOLERANCE) if D.size else False

        # ADR-0015 §(3): 2n-state augmentation で n_states = 2n
        super().__init__(
            id=id,
            name=name,
            n_inputs=1,
            n_outputs=1,
            n_states=2 * n,
            direct_feedthrough=df,
            sample_time=sample_time,
        )
        self._A = A
        self._B = B
        self._C = C
        self._D = D
        self._n = n
        self.numerator = num
        self.denominator = den
        x0_user: np.ndarray
        if x0 is None:
            x0_user = np.zeros(n)
        else:
            x0_arr = np.atleast_1d(np.asarray(x0, dtype=float))
            if x0_arr.shape != (n,):
                raise BlockSpecError(
                    f"DiscreteTransferFunction: x0 must have shape ({n},), got {x0_arr.shape}"
                )
            x0_user = x0_arr
        self.x0 = np.concatenate([x0_user, x0_user])
        self._params = {
            "numerator": num,
            "denominator": den,
            "x0": x0_user,
            "sample_time": float(sample_time),
        }

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        x_curr = x[: self._n]
        return np.asarray(self._C @ x_curr + self._D @ u, dtype=float).ravel()

    def update(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        # ADR-0015 §(3) 2n-state augmentation: x[:n]=x[k-1] (output snapshot)、
        # x[n:]=x[k] (累積)。state[n:] からの再帰更新で標準形の連続性を保つ
        # (DiscreteStateSpace と同じ semantics)。
        x_buf = x[self._n :]
        next_buf = np.asarray(self._A @ x_buf + self._B @ u, dtype=float).ravel()
        return np.concatenate([x_buf, next_buf])
