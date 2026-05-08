"""LTI ブロック共通ユーティリティ (ADR-0006、ADR-0010 §(6))。

連続版と離散版の SS / TF ブロックで共有する定数とヘルパーを置く。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from ..exceptions import BlockSpecError

# ADR-0006 §(6): D 行列の最大絶対値がこの閾値を超えたら direct_feedthrough = True
_DF_TOLERANCE = 1e-12


def build_companion_form_siso(
    numerator: npt.NDArray[Any], denominator: npt.NDArray[Any]
) -> tuple[npt.NDArray[Any], npt.NDArray[Any], npt.NDArray[Any], npt.NDArray[Any]]:
    """SISO 伝達関数 ``H(s) = num(s) / den(s)`` を controllable canonical form に変換。

    ADR-0010 §(6) で予告された companion form 自前構築実装。``scipy.signal.tf2ss`` の
    ゼロ多項式 (off-diagonal の `numerators[i][j] = [0.0]`) で BadCoefficients warning
    を出す問題を回避する。MIMO 共通分母 TF を SISO ごとに realize して結合する用途
    (`MimoTransferFunction`) で使う。

    係数の慣習:
        ``numerator``、``denominator`` は **s の降べき** で表現
        (numpy / scipy convention)。例: ``[1, 2, 3]`` は ``s^2 + 2*s + 3``。

    Controllable canonical form:
        分母 ``d(s) = a_n s^n + a_{n-1} s^{n-1} + ... + a_1 s + a_0`` (a_n = 1 に正規化) と
        分子 ``b(s) = b_n s^n + b_{n-1} s^{n-1} + ... + b_0`` に対し:

        A = [[0, 1, 0, ..., 0],
             [0, 0, 1, ..., 0],
             ...
             [0, 0, 0, ..., 1],
             [-a_0, -a_1, ..., -a_{n-1}]]    shape (n, n)
        B = [0, 0, ..., 1]^T                  shape (n, 1)
        C = [b_0 - b_n*a_0, ..., b_{n-1} - b_n*a_{n-1}]  shape (1, n)
        D = [b_n]                             shape (1, 1)

        biproper (deg(num) == deg(den)) のとき D = b_n/a_n、strict proper のとき
        D = 0 になる (b_n = 0)。

    Args:
        numerator: 分子多項式の係数 (shape ``(m+1,)``、``m = deg(num)``)。
        denominator: 分母多項式の係数 (shape ``(n+1,)``、``n = deg(den)``)。

    Returns:
        (A, B, C, D) tuple。shape はそれぞれ ``(n, n)``、``(n, 1)``、``(1, n)``、``(1, 1)``。

    Raises:
        BlockSpecError: ``num`` / ``den`` が空、``den[0] == 0``、improper
            (``deg(num) > deg(den)``) の場合。
    """
    num = np.asarray(numerator, dtype=float).ravel()
    den = np.asarray(denominator, dtype=float).ravel()
    if num.size == 0 or den.size == 0:
        raise BlockSpecError("build_companion_form_siso: numerator/denominator must be non-empty")
    if den[0] == 0.0:
        raise BlockSpecError(
            "build_companion_form_siso: leading coefficient of denominator must be non-zero"
        )
    deg_num = num.size - 1
    deg_den = den.size - 1
    if deg_num > deg_den:
        raise BlockSpecError(
            f"build_companion_form_siso: improper system "
            f"(deg(num)={deg_num} > deg(den)={deg_den}). "
            f"Only proper or biproper systems are supported."
        )
    n = deg_den
    if n == 0:
        # H(s) = b_0 / a_0 (定数ゲイン)。state 不要だが、本ヘルパーは状態を持つ
        # SS 表現を返す契約なので呼び出し側で n>=1 のみを許可する想定。
        raise BlockSpecError(
            "build_companion_form_siso: deg(den)=0 (pure gain) is not supported by SS realization; "
            "use a static block (e.g. Gain) instead"
        )

    # 分母を monic 化: a_n = 1
    den_monic = den / den[0]
    # a = [a_0, a_1, ..., a_{n-1}] (係数昇べきで参照しやすくするため反転)
    # den_monic の格納は降べき: den_monic[0]=1, den_monic[1]=a_{n-1}, ..., den_monic[n]=a_0
    # よって a_i = den_monic[n - i]
    a_asc = den_monic[::-1].copy()  # a_asc[i] = a_i (昇べき)、a_asc[n]=1

    # 分子を分母と同じ正規化で除して、長さを n+1 に左 0 パディング
    num_normed = num / den[0]
    if num_normed.size < n + 1:
        num_padded = np.concatenate([np.zeros(n + 1 - num_normed.size, dtype=float), num_normed])
    else:
        num_padded = num_normed
    # b_asc[i] = b_i (昇べき)、b_asc[n] = b_n (= biproper 時の D)
    b_asc = num_padded[::-1].copy()

    # A: companion matrix (controllable canonical form)
    A = np.zeros((n, n), dtype=float)
    if n > 1:
        # 上三角の 1 つ上のサブダイアゴナルに 1 を配置
        for i in range(n - 1):
            A[i, i + 1] = 1.0
    # 最終行: -a_0, -a_1, ..., -a_{n-1}
    A[n - 1, :] = -a_asc[:n]

    # B: 末尾要素のみ 1
    B = np.zeros((n, 1), dtype=float)
    B[n - 1, 0] = 1.0

    # D: b_n (biproper のとき非ゼロ、proper のとき 0)
    D = np.array([[b_asc[n]]], dtype=float)

    # C: c_i = b_i - b_n * a_i (i = 0..n-1)、shape (1, n)
    c_row = b_asc[:n] - b_asc[n] * a_asc[:n]
    C = c_row.reshape(1, n)

    return A, B, C, D
