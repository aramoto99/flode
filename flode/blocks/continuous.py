"""連続時間 LTI ブロック (``Integrator`` / ``StateSpace`` / ``TransferFunction`` /
``MimoTransferFunction`` / ``Derivative``)。

- ADR-0006: SISO ``TransferFunction`` の SS 化方針 (scipy.signal.tf2ss 利用)
- ADR-0010 §(2)、ADR-0016 Phase 3 #1: ``MimoTransferFunction`` (共通分母 MIMO TF、
  自前 controllable canonical form 構築で scipy ゼロ多項式バグ回避)
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np
import numpy.typing as npt
import scipy.signal

from ..core.block import Block
from ..exceptions import BlockSpecError
from ._lti_utils import _DF_TOLERANCE, build_companion_form_siso
from ._vector_state import VectorStateMixin, X0Like


class Integrator(VectorStateMixin, Block):
    """連続時間積分器 ``y = x``、``x_dot = u``。

    ``direct_feedthrough=False`` (出力は状態 ``x`` のみ参照) なので、閉ループ内
    の代数ループを切る用途に使える。

    ADR-0079 §(5): ベクトル信号を積分できる。``x0`` がスカラなら状態 shape は
    上流の入力 shape に従い (スカラ拡張)、配列なら入力はその shape (またはスカラ)
    でなければならない。状態は flat で格納される (``linearize`` の state_names は
    C order の flat index)。

    Args:
        x0: 初期状態 ``x(0)`` (スカラまたは配列)。
    """

    # D-4 (SPEC-0028 Q11): 連続ブロックは入力に float64 を要求する
    required_input_dtype: ClassVar[str | None] = "float64"

    def __init__(
        self,
        x0: X0Like = 0.0,
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
        self._init_vector_state(x0)
        self._params = {"x0": self._x0_param()}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.array([x[0]])

    def derivative(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.array([u[0]])

    def _output_k(
        self, t: float, xs: npt.NDArray[Any], u: tuple[npt.NDArray[Any], ...]
    ) -> npt.NDArray[Any]:
        return xs

    def _derivative_k(
        self, t: float, xs: npt.NDArray[Any], u: tuple[npt.NDArray[Any], ...]
    ) -> npt.NDArray[Any]:
        return self._u_state(u[0])


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

    # D-4 (SPEC-0028 Q11): 連続ブロックは入力に float64 を要求する
    required_input_dtype: ClassVar[str | None] = "float64"

    def __init__(
        self,
        A: npt.NDArray[Any],
        B: npt.NDArray[Any],
        C: npt.NDArray[Any],
        D: npt.NDArray[Any] | None = None,
        x0: npt.NDArray[Any] | None = None,
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
        D_arr: npt.NDArray[Any]
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

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.asarray(self._C @ x + self._D @ u, dtype=float).ravel()

    def derivative(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
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

    # D-4 (SPEC-0028 Q11): 連続ブロックは入力に float64 を要求する
    required_input_dtype: ClassVar[str | None] = "float64"

    def __init__(
        self,
        numerator: npt.NDArray[Any] | list[float],
        denominator: npt.NDArray[Any] | list[float],
        x0: npt.NDArray[Any] | None = None,
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

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        # C: (1,n)、x: (n,)、D: (1,1)、u: (1,)
        y = self._C @ x + self._D @ u
        return np.asarray(y, dtype=float).ravel()

    def derivative(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.asarray(self._A @ x + self._B @ u, dtype=float).ravel()


class MimoTransferFunction(Block):
    """連続 LTI MIMO 伝達関数 ``H(s) = N(s) / d(s)`` (共通分母版、ADR-0010 §(2)、ADR-0016)。

    入力 ``q`` 個 / 出力 ``p`` 個の伝達関数行列を扱う。共通分母 ``d(s)`` (1D) と、
    分子多項式行列 ``N(s) = [[n_{ij}(s)]]`` (3D list) を受け取る:

    .. code-block:: text

        H[i][j](s) = numerators[i][j] / denominator
        i in [0, p)、j in [0, q)
        各 numerators[i][j] は s の降べき多項式係数。
        denominator は s の降べき多項式係数 (共通)。

    ADR-0010 §(7) で予告された companion form **自前構築** で実装する
    (``scipy.signal.tf2ss`` のゼロ多項式時の ``BadCoefficients`` warning + 不正な
    B/C/D 返却問題を回避)。

    Internal realization:
        各 (i, j) の SISO 伝達関数 ``numerators[i][j] / denominator`` を
        ``build_companion_form_siso`` で SS 化し、block-diagonal で結合する
        (Option 2、ADR-0016 §(1) #1)。state size は ``p * q * n`` (n = deg(den))。

        - ``A``: shape ``(p*q*n, p*q*n)``、各 ``A_{ij}`` を blkdiag 配置
        - ``B``: shape ``(p*q*n, q)``、入力 j のみがブロック (i, j) の B に接続
        - ``C``: shape ``(p, p*q*n)``、出力 i は ブロック (i, j) for all j の C を集約
        - ``D``: shape ``(p, q)``、各 (i, j) で biproper なら非ゼロ

    SM-A 信号モデル (ADR-0010 §(1)) に従い、ポートは ``q`` 個のスカラー入力 +
    ``p`` 個のスカラー出力。

    Phase 3 では **共通分母版のみ** をサポート (各 (i, j) で異なる分母を許容する
    独立分母版は Phase 4+ で再検討、ADR-0010 §(2))。

    Args:
        numerators: 3D list ``[p][q][num_coefs]``。``numerators[i][j]`` は出力 i に
            対する入力 j からの分子多項式係数 (s の降べき)。``proper`` であること
            (各 ``len(numerators[i][j]) <= len(denominator)``)。``[0.0]`` (ゼロ
            多項式) を許容。
        denominator: 共通分母多項式の係数 (s の降べき、1D)。``denominator[0] != 0``
            必須。``deg(denominator) >= 1`` 必須 (純粋ゲインは ``Gain`` を使う)。
        x0: 初期状態 (shape ``(p*q*n,)``)。``None`` のときゼロ。なお
            ``numerators[i][j] == [0.0]`` の (i, j) に対応する状態は dead state で
            あり、その位置に非ゼロ値を入れても入出力に影響しない。

    Raises:
        BlockSpecError: 形状不正、空配列、improper system、零分母など。
    """

    # D-4 (SPEC-0028 Q11): 連続ブロックは入力に float64 を要求する
    required_input_dtype: ClassVar[str | None] = "float64"

    def __init__(
        self,
        numerators: list[list[list[float]]],
        denominator: npt.NDArray[Any] | list[float],
        x0: npt.NDArray[Any] | None = None,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        # --- 入力 validation ---
        if not isinstance(numerators, (list, tuple)) or len(numerators) == 0:
            raise BlockSpecError(
                "MimoTransferFunction: numerators must be a non-empty list of rows"
            )
        p = len(numerators)
        if not isinstance(numerators[0], (list, tuple)):
            raise BlockSpecError(
                f"MimoTransferFunction: numerators[0] must be a list, "
                f"got {type(numerators[0]).__name__}"
            )
        q = len(numerators[0])
        if q == 0:
            raise BlockSpecError(
                "MimoTransferFunction: numerators[0] must be a non-empty list of polynomials"
            )
        for i, row in enumerate(numerators):
            if not isinstance(row, (list, tuple)) or len(row) != q:
                raise BlockSpecError(
                    f"MimoTransferFunction: numerators[{i}] must be a list of length {q}, "
                    f"got {len(row) if isinstance(row, (list, tuple)) else type(row).__name__}"
                )
            for j, poly in enumerate(row):
                if not isinstance(poly, (list, tuple, np.ndarray)) or len(poly) == 0:
                    raise BlockSpecError(
                        f"MimoTransferFunction: numerators[{i}][{j}] must be a non-empty "
                        f"sequence of polynomial coefficients"
                    )

        den = np.asarray(denominator, dtype=float).ravel()
        if den.size == 0:
            raise BlockSpecError("MimoTransferFunction: denominator must be non-empty")
        if den[0] == 0.0:
            raise BlockSpecError(
                "MimoTransferFunction: leading coefficient of denominator must be non-zero"
            )
        n = den.size - 1  # deg(den)
        if n == 0:
            raise BlockSpecError(
                "MimoTransferFunction: deg(denominator)=0 (pure gain) is not supported; "
                "use a Gain block instead"
            )

        # --- 各 (i, j) を SISO companion realization に変換 ---
        # block-diagonal A (p*q*n, p*q*n)、B / C / D は非ゼロ要素のみ書き込む
        n_total = p * q * n
        A = np.zeros((n_total, n_total), dtype=float)
        B = np.zeros((n_total, q), dtype=float)
        C = np.zeros((p, n_total), dtype=float)
        D = np.zeros((p, q), dtype=float)

        for i in range(p):
            for j in range(q):
                num_ij = np.asarray(numerators[i][j], dtype=float).ravel()
                # ゼロ多項式 (entire numerator polynomial = 0): skip realization,
                # この (i, j) は zero contribution。state を holding するだけ。
                if np.all(num_ij == 0.0):
                    # A の block-diagonal 部分は denominator のみで決まるため、
                    # ゼロ numerator でも poles は持つ (autonomous decay)。ただし
                    # B[block, j] = 0、C[i, block] = 0 なので入出力に寄与しない。
                    A_ij, _, _, _ = build_companion_form_siso(np.array([0.0]), den)
                    block_start = (i * q + j) * n
                    block_end = block_start + n
                    A[block_start:block_end, block_start:block_end] = A_ij
                    # B / C / D はゼロのまま (この block は dead state)
                    continue

                if num_ij.size > den.size:
                    raise BlockSpecError(
                        f"MimoTransferFunction: numerators[{i}][{j}] has degree "
                        f"{num_ij.size - 1} > deg(denominator)={n} (improper). "
                        f"Only proper or biproper systems are supported."
                    )

                A_ij, B_ij, C_ij, D_ij = build_companion_form_siso(num_ij, den)
                block_start = (i * q + j) * n
                block_end = block_start + n
                A[block_start:block_end, block_start:block_end] = A_ij
                B[block_start:block_end, j : j + 1] = B_ij
                C[i : i + 1, block_start:block_end] = C_ij
                D[i, j] = float(D_ij[0, 0])

        df = bool(np.max(np.abs(D)) > _DF_TOLERANCE) if D.size else False

        super().__init__(
            id=id,
            name=name,
            n_inputs=q,
            n_outputs=p,
            n_states=n_total,
            direct_feedthrough=df,
        )
        self._A = A
        self._B = B
        self._C = C
        self._D = D
        self._p = p
        self._q = q
        self._n_per_block = n
        # JSON serialize 用に元の入力を保持 (scalar / list 形式、ADR-0008)
        self._numerators_raw = [
            [np.asarray(numerators[i][j], dtype=float) for j in range(q)] for i in range(p)
        ]
        self._denominator = den

        if x0 is None:
            self.x0 = np.zeros(n_total)
        else:
            x0_arr = np.atleast_1d(np.asarray(x0, dtype=float))
            if x0_arr.shape != (n_total,):
                raise BlockSpecError(
                    f"MimoTransferFunction: x0 must have shape ({n_total},), got {x0_arr.shape}"
                )
            self.x0 = x0_arr

        # JSON 表現は input list of lists のまま保存 (ADR-0008、3D list-of-lists)
        self._params = {
            "numerators": [[list(self._numerators_raw[i][j]) for j in range(q)] for i in range(p)],
            "denominator": list(den),
            "x0": self.x0,
        }

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.asarray(self._C @ x + self._D @ u, dtype=float).ravel()

    def derivative(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.asarray(self._A @ x + self._B @ u, dtype=float).ravel()


class Derivative(VectorStateMixin, Block):
    """フィルタ付き微分 ``H(s) = N*s / (s + N)`` (ADR-0006 §(3))。ベクトル信号は要素ごと (ADR-0079)。

    純粋微分 ``s`` は実装不能なので 1 次フィルタ近似を採用する。``N`` を大きく
    すると純粋微分に近づくがノイズも拡大する。リファレンスツールの Derivative の
    Filter Coefficient ``N`` (default 1000) と同じ慣習に従う。

    実現形: 状態 ``x`` を ``x_dot = -N*x + N*u``、出力 ``y = -N*x + N*u``
    とすると、入力から出力への伝達関数は ``N*s / (s + N)`` になる。
    ``direct_feedthrough = True`` (``y`` に ``u`` が直接寄与する)。

    Args:
        N: フィルタ帯域 (rad/s)。default 1000.0。
        x0: 内部状態の初期値。default 0.0。
    """

    # D-4 (SPEC-0028 Q11): 連続ブロックは入力に float64 を要求する
    required_input_dtype: ClassVar[str | None] = "float64"

    def __init__(
        self,
        N: float = 1000.0,
        x0: X0Like = 0.0,
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
        self._init_vector_state(x0)
        self._params = {"N": self.N, "x0": self._x0_param()}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.array([self.N * (u[0] - x[0])])

    def derivative(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.array([self.N * (u[0] - x[0])])

    def _output_k(
        self, t: float, xs: npt.NDArray[Any], u: tuple[npt.NDArray[Any], ...]
    ) -> npt.NDArray[Any]:
        return np.asarray(self.N * (self._u_state(u[0]) - xs))

    def _derivative_k(
        self, t: float, xs: npt.NDArray[Any], u: tuple[npt.NDArray[Any], ...]
    ) -> npt.NDArray[Any]:
        return np.asarray(self.N * (self._u_state(u[0]) - xs))
