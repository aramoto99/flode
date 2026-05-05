"""離散時間ブロック。

Phase 1 で実装するブロック:

* ``UnitDelay`` — 1 サンプル遅延 (ADR-0002 §(3))
* ``DiscreteIntegrator`` — 前進 Euler 積分 ``x[k+1] = x[k] + T*gain*u[k]``
* ``ZeroOrderHold`` — 連続入力を離散周期でサンプリング保持
* ``DiscreteStateSpace`` — 離散 LTI ``x[k+1] = A_d x[k] + B_d u[k]`` (ADR-0006)
* ``DiscreteTransferFunction`` — 離散 LTI ``H(z) = num(z)/den(z)`` (ADR-0006)

``Memory`` は ``UnitDelay`` と意味論が同一のため Phase 1 では別実装しない。
``FirstOrderHold`` / 高次離散ブロックは Phase 2 以降。
"""

from __future__ import annotations

import numpy as np
import scipy.signal

from ..core.block import Block
from ..exceptions import BlockSpecError
from ._lti_utils import _DF_TOLERANCE


class UnitDelay(Block):
    """1 サンプル遅延 ``y[k] = x[k] = u[k-1]``。

    出力は現状態 (= 前ステップの入力)、状態更新は現入力をそのまま保持。
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
    """連続入力をサンプル点で取り込み、次サンプルまで状態として保持する。

    実装は state-based: ``y[k] = x[k]``、``x[k+1] = u(t_k)``。
    ``direct_feedthrough=False`` のため閉ループ内の代数ループ切断にも使える。

    Args:
        sample_time: サンプル周期 [s]。``> 0`` 必須 (継承 ``-1.0`` も可)。
        x0: 初回サンプル前 (``t=0`` 時点) の出力値。

    Note:
        Simulink の Zero Order Hold (``direct_feedthrough=True``、サンプル点で
        即座に出力反映) とは挙動が異なり、本実装は ``UnitDelay`` と等価
        (1 サンプル分遅延する)。真の ZOH (``direct_feedthrough=True`` 版) は
        Phase 2 で追加予定。命名変更も Phase 2 の破壊的変更候補。
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
