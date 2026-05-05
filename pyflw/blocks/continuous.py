from __future__ import annotations

import numpy as np
import scipy.signal

from ..core.block import Block
from ..exceptions import BlockSpecError
from ._lti_utils import _DF_TOLERANCE


class Integrator(Block):
    """連続時間積分器 ``y = x``、``x_dot = u``。

    ``direct_feedthrough=False`` (出力は状態 ``x`` のみ参照) なので、閉ループ内
    の代数ループを切る用途に使える。

    Args:
        x0: 初期状態 ``x(0)``。
    """

    def __init__(
        self,
        x0: float = 0.0,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        super().__init__(
            id=id,
            name=name,
            n_inputs=1,
            n_outputs=1,
            n_states=1,
            direct_feedthrough=False,
        )
        self.x0 = np.array([float(x0)])
        self._params = {"x0": float(x0)}

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.array([x[0]])

    def derivative(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.array([u[0]])


class StateSpace(Block):
    """連続 LTI 状態空間 ``x_dot = A x + B u``、``y = C x + D u``。

    ``direct_feedthrough`` は ``D`` 行列の最大絶対値が ``1e-12`` を超えるかで
    自動推論する (ADR-0006 §(6))。

    Args:
        A: システム行列 (shape ``(n, n)``)。
        B: 入力行列 (shape ``(n, m)``)、``m = n_inputs``。
        C: 出力行列 (shape ``(p, n)``)、``p = n_outputs``。
        D: 直達行列 (shape ``(p, m)``)。``None`` のときゼロ行列。
        x0: 初期状態 (shape ``(n,)``)。``None`` のときゼロ。
    """

    def __init__(
        self,
        A: np.ndarray,
        B: np.ndarray,
        C: np.ndarray,
        D: np.ndarray | None = None,
        x0: np.ndarray | None = None,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        A_arr = np.asarray(A, dtype=float)
        B_arr = np.asarray(B, dtype=float)
        C_arr = np.asarray(C, dtype=float)
        if A_arr.ndim != 2 or A_arr.shape[0] != A_arr.shape[1]:
            raise BlockSpecError(f"StateSpace: A must be square, got shape {A_arr.shape}")
        n = A_arr.shape[0]
        if n == 0:
            raise BlockSpecError(
                "StateSpace: n_states=0 (pure gain) is not supported; use a static "
                "block (e.g. Gain) instead"
            )
        if B_arr.ndim != 2 or B_arr.shape[0] != n:
            raise BlockSpecError(
                f"StateSpace: B must have shape (n, m) with n={n}, got {B_arr.shape}"
            )
        m = B_arr.shape[1]
        if C_arr.ndim != 2 or C_arr.shape[1] != n:
            raise BlockSpecError(
                f"StateSpace: C must have shape (p, n) with n={n}, got {C_arr.shape}"
            )
        p = C_arr.shape[0]
        if D is None:
            D_arr = np.zeros((p, m))
        else:
            D_arr = np.asarray(D, dtype=float)
            if D_arr.shape != (p, m):
                raise BlockSpecError(f"StateSpace: D must have shape ({p}, {m}), got {D_arr.shape}")
        df = bool(np.max(np.abs(D_arr)) > _DF_TOLERANCE) if D_arr.size else False

        super().__init__(
            id=id,
            name=name,
            n_inputs=m,
            n_outputs=p,
            n_states=n,
            direct_feedthrough=df,
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
                raise BlockSpecError(f"StateSpace: x0 must have shape ({n},), got {x0_arr.shape}")
            self.x0 = x0_arr
        self._params = {
            "A": A_arr,
            "B": B_arr,
            "C": C_arr,
            "D": D_arr,
            "x0": self.x0,
        }

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.asarray(self._C @ x + self._D @ u, dtype=float).ravel()

    def derivative(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.asarray(self._A @ x + self._B @ u, dtype=float).ravel()


class TransferFunction(Block):
    """連続 LTI 伝達関数 ``H(s) = num(s) / den(s)`` (SISO)。

    内部で ``scipy.signal.tf2ss`` により制御正準形 SS に変換して実装する
    (ADR-0006 §(1))。``deg(num) <= deg(den)`` を要求 (improper は不可)。

    Args:
        numerator: 分子多項式の係数 (s の降べき、numpy convention)。
        denominator: 分母多項式の係数。
        x0: 初期状態 (shape ``(len(denominator)-1,)``)。
    """

    def __init__(
        self,
        numerator: np.ndarray | list[float],
        denominator: np.ndarray | list[float],
        x0: np.ndarray | None = None,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        num = np.asarray(numerator, dtype=float).ravel()
        den = np.asarray(denominator, dtype=float).ravel()
        if num.size == 0 or den.size == 0:
            raise BlockSpecError("TransferFunction: numerator/denominator must be non-empty")
        if den[0] == 0.0:
            raise BlockSpecError(
                "TransferFunction: leading coefficient of denominator must be non-zero"
            )
        if np.all(num == 0.0):
            raise BlockSpecError("TransferFunction: numerator cannot be all zeros")
        # プロパー性: deg(num) > deg(den) は improper として拒否
        # numpy convention: deg = len - 1
        if (num.size - 1) > (den.size - 1):
            raise BlockSpecError(
                f"TransferFunction: improper system (deg(num)={num.size - 1} > "
                f"deg(den)={den.size - 1}). Only proper or biproper systems are supported."
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
                    f"TransferFunction: x0 must have shape ({n},), got {x0_arr.shape}"
                )
            self.x0 = x0_arr
        self._params = {
            "numerator": num,
            "denominator": den,
            "x0": self.x0,
        }

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        # C: (1,n)、x: (n,)、D: (1,1)、u: (1,)
        y = self._C @ x + self._D @ u
        return np.asarray(y, dtype=float).ravel()

    def derivative(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.asarray(self._A @ x + self._B @ u, dtype=float).ravel()


class Derivative(Block):
    """フィルタ付き微分 ``H(s) = N*s / (s + N)`` (ADR-0006 §(3))。

    純粋微分 ``s`` は実装不能なので 1 次フィルタ近似を採用する。``N`` を大きく
    すると純粋微分に近づくがノイズも拡大する。Simulink Derivative の Filter
    Coefficient ``N`` (default 1000) と同じ慣習に従う。

    実現形: 状態 ``x`` を ``x_dot = -N*x + N*u``、出力 ``y = -N*x + N*u``
    とすると、入力から出力への伝達関数は ``N*s / (s + N)`` になる。
    ``direct_feedthrough = True`` (``y`` に ``u`` が直接寄与する)。

    Args:
        N: フィルタ帯域 (rad/s)。default 1000.0。
        x0: 内部状態の初期値。default 0.0。
    """

    def __init__(
        self,
        N: float = 1000.0,
        x0: float = 0.0,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if N <= 0.0:
            raise BlockSpecError(f"Derivative: N must be > 0, got {N}")
        super().__init__(
            id=id,
            name=name,
            n_inputs=1,
            n_outputs=1,
            n_states=1,
            direct_feedthrough=True,
        )
        self.N = float(N)
        self.x0 = np.array([float(x0)])
        self._params = {"N": self.N, "x0": float(x0)}

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.array([self.N * (u[0] - x[0])])

    def derivative(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.array([self.N * (u[0] - x[0])])
