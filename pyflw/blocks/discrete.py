"""離散時間ブロック。

実装ブロック:

* ``UnitDelay`` — 1 サンプル遅延 ``y[k+1] = u[k]`` (Simulink UnitDelay 互換、ADR-0014)
* ``DiscreteIntegrator`` — 前進 Euler 積分 ``x[k+1] = x[k] + T*gain*u[k]``
* ``ZeroOrderHold`` — state-based 離散ホールド (ADR-0014 適用後は ``UnitDelay`` と
  完全に同一の semantics。Phase 3 で deprecate 予定)
* ``ZeroOrderHoldDirect`` — Simulink ZOH 互換 ``y(t_k) = u(t_k)`` (ADR-0010 §(4) /
  ADR-0014 §(3))
* ``DiscreteStateSpace`` — 離散 LTI ``x[k+1] = A_d x[k] + B_d u[k]`` (ADR-0006)
* ``DiscreteTransferFunction`` — 離散 LTI ``H(z) = num(z)/den(z)`` (ADR-0006)

``Memory`` は ``UnitDelay`` と意味論が同一のため別実装しない。
``FirstOrderHold`` / 高次離散ブロックは Phase 3 以降。
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
    """1 サンプル遅延 ``y[k+1] = u[k]`` (Simulink UnitDelay 互換、ADR-0014)。

    Simulator は現サンプル時刻 ``t_k`` の入力で ``update(t_k, x, u(t_k))`` を呼び、
    ``x_next = u(t_k)`` を保存する (ADR-0014 §(1))。次サンプル時刻 ``t_{k+1}`` で
    ``output(t_{k+1}, x, u) = x = u(t_k)`` が返る → 真の 1 サンプル遅延。

    ``direct_feedthrough=False`` なので閉ループ内で代数ループを切る用途にも使える。

    Args:
        sample_time: サンプル周期 [s]。``> 0`` 必須 (継承 ``-1.0`` も可)。
        x0: 初期状態 (= t=0 での出力値)。
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
            direct_feedthrough=False,
            sample_time=sample_time,
        )
        self.x0 = np.array([float(x0)])
        self._params = {"sample_time": float(sample_time), "x0": float(x0)}

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.array([x[0]])

    def update(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.array([u[0]])


class DiscreteIntegrator(Block):
    """前進 Euler 離散積分 ``x[k+1] = x[k] + sample_time * gain * u[k]``、出力 ``y[k] = x[k]``。

    ``direct_feedthrough=False`` (出力は前ステップ確定状態のみ参照) なので
    閉ループ内の代数ループ切断にも使える。

    Args:
        sample_time: サンプル周期 [s]。``> 0`` 必須 (継承 ``-1.0`` も可)。
        gain: 入力に掛けるゲイン (積分定数)。
        x0: 初期状態。
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
            n_states=1,
            direct_feedthrough=False,
            sample_time=sample_time,
        )
        self.gain = float(gain)
        self.x0 = np.array([float(x0)])
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
        return np.array([x[0] + ts * self.gain * u[0]])


class ZeroOrderHold(Block):
    """state-based 離散ホールド。**ADR-0014 適用後は ``UnitDelay`` と完全同一**。

    実装は ``y[k] = x[k]``、``update`` で ``x[k+1] = u[k]``。これは Simulink の
    Zero Order Hold (``direct_feedthrough=True``、サンプル時刻で u(t_k) を即座に
    反映、初回 t=0 でも ``y(0) = u(0)``) と異なり、1 サンプル遅延する
    (= UnitDelay と同一の semantics)。

    Simulink ZOH 互換の即時反映挙動が必要な場合は ``ZeroOrderHoldDirect`` を
    使用すること。本 class は Phase 3 で ``DeprecationWarning`` 発出、
    Phase 4 で削除予定 (ADR-0014 §(4))。

    Args:
        sample_time: サンプル周期 [s]。``> 0`` 必須 (継承 ``-1.0`` も可)。
        x0: 初回サンプル前 (``t=0`` 時点) の出力値。
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
            direct_feedthrough=False,
            sample_time=sample_time,
        )
        self.x0 = np.array([float(x0)])
        self._params = {"sample_time": float(sample_time), "x0": float(x0)}

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.array([x[0]])

    def update(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.array([u[0]])


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
    """離散 LTI 状態空間 ``x[k+1] = A x[k] + B u[k]``、``y[k] = C x[k] + D u[k]``。

    ADR-0006 §(5)。``direct_feedthrough`` は ``D`` の最大絶対値が ``1e-12`` を
    超えるかで自動推論。

    Args:
        A: 状態行列 (shape ``(n, n)``)。
        B: 入力行列 (shape ``(n, m)``)、``m = n_inputs``。
        C: 出力行列 (shape ``(p, n)``)、``p = n_outputs``。
        D: 直達行列 (shape ``(p, m)``)。``None`` でゼロ。
        sample_time: サンプル周期 [s]、``> 0`` 必須 (継承 ``-1.0`` も可)。
        x0: 初期状態 (shape ``(n,)``)。
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
        if D is None:
            D_arr = np.zeros((p, m))
        else:
            D_arr = np.asarray(D, dtype=float)
            if D_arr.shape != (p, m):
                raise BlockSpecError(
                    f"DiscreteStateSpace: D must have shape ({p}, {m}), got {D_arr.shape}"
                )
        df = bool(np.max(np.abs(D_arr)) > _DF_TOLERANCE) if D_arr.size else False

        super().__init__(
            id=id,
            name=name,
            n_inputs=m,
            n_outputs=p,
            n_states=n,
            direct_feedthrough=df,
            sample_time=sample_time,
        )
        self._A = A_arr
        self._B = B_arr
        self._C = C_arr
        self._D = D_arr
        if x0 is None:
            self.x0 = np.zeros(n)
        else:
            x0_arr = np.atleast_1d(np.asarray(x0, dtype=float))
            if x0_arr.shape != (n,):
                raise BlockSpecError(
                    f"DiscreteStateSpace: x0 must have shape ({n},), got {x0_arr.shape}"
                )
            self.x0 = x0_arr
        self._params = {
            "A": A_arr,
            "B": B_arr,
            "C": C_arr,
            "D": D_arr,
            "x0": self.x0,
            "sample_time": float(sample_time),
        }

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.asarray(self._C @ x + self._D @ u, dtype=float).ravel()

    def update(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.asarray(self._A @ x + self._B @ u, dtype=float).ravel()


class DiscreteTransferFunction(Block):
    """離散 LTI 伝達関数 ``H(z) = num(z) / den(z)`` (SISO)。

    ADR-0006 §(4)。内部で ``scipy.signal.tf2ss`` により SS に変換して実装。
    ``deg(num) <= deg(den)`` を要求。

    Args:
        numerator: 分子多項式の係数 (z の降べき)。
        denominator: 分母多項式の係数。
        sample_time: サンプル周期 [s]、``> 0`` 必須。
        x0: 初期状態 (shape ``(len(denominator)-1,)``)。
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

        super().__init__(
            id=id,
            name=name,
            n_inputs=1,
            n_outputs=1,
            n_states=n,
            direct_feedthrough=df,
            sample_time=sample_time,
        )
        self._A = A
        self._B = B
        self._C = C
        self._D = D
        self.numerator = num
        self.denominator = den
        if x0 is None:
            self.x0 = np.zeros(n)
        else:
            x0_arr = np.atleast_1d(np.asarray(x0, dtype=float))
            if x0_arr.shape != (n,):
                raise BlockSpecError(
                    f"DiscreteTransferFunction: x0 must have shape ({n},), got {x0_arr.shape}"
                )
            self.x0 = x0_arr
        self._params = {
            "numerator": num,
            "denominator": den,
            "x0": self.x0,
            "sample_time": float(sample_time),
        }

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.asarray(self._C @ x + self._D @ u, dtype=float).ravel()

    def update(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.asarray(self._A @ x + self._B @ u, dtype=float).ravel()
