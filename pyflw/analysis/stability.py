"""安定性解析 (固有値 / 漸近安定性 / 根軌跡) — ADR-0027 §(1)B / §(6)(7)。

``LinearSystem`` (ADR-0026) を入力に取る:

- :func:`eigenvalues` / :func:`is_stable` は **numpy のみで動く** (extras 不要、
  ADR-0027 §Decision Option 3 hybrid)。
- :func:`root_locus` は ``python-control`` 経由 (`pyflw[control]` extras 必須、
  未インストール時は ``ImportError`` で誘導、ADR-0027 §(10) E4)。

MIMO 入力に対する :func:`root_locus` は ``input_idx`` / ``output_idx`` で SISO
抽出する (ADR-0027 §(7))。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from ..exceptions import BlockSpecError
from .linearize import LinearSystem

if TYPE_CHECKING:  # pragma: no cover - optional matplotlib type
    from matplotlib.axes import Axes

_PYFLW_CONTROL_HINT = "Install via `pip install pyflw[control]` or `pip install python-control`."


def _import_control() -> Any:
    """``python-control`` を遅延 import (extras 未インストール時に案内付き)。"""
    try:
        import control as _control
    except ImportError as e:
        raise ImportError(
            f"This function requires the optional `python-control` package. {_PYFLW_CONTROL_HINT}"
        ) from e
    return _control


# ---------------------------------------------------------------------------
# 固有値 / 漸近安定性 (numpy のみ)
# ---------------------------------------------------------------------------


def eigenvalues(ls: LinearSystem) -> np.ndarray:
    """A 行列の固有値を返す (`np.linalg.eig` の薄ラッパ)。

    Args:
        ls: :class:`LinearSystem`。

    Returns:
        複素 1D ndarray、shape ``(n,)``。順序は LAPACK ``geev`` の依存。

    Raises:
        BlockSpecError: 空の状態空間 (``A.shape[0] == 0``)。
    """
    if ls.A.shape[0] == 0:
        raise BlockSpecError(
            "eigenvalues: empty state-space (A.shape[0] == 0). "
            "Linearise a model with at least one continuous state first."
        )
    eig_values, _ = np.linalg.eig(ls.A)
    return np.asarray(eig_values, dtype=complex)


def is_stable(ls: LinearSystem, *, tol: float = 1e-9) -> bool:
    """連続系の漸近安定性判定 (ADR-0027 §(6))。

    全固有値の実部 < ``-tol`` のとき ``True``。境界値 (``Re(λ) ∈ [-tol, +tol]``)
    は **不安定として扱う** (= 限界安定 / 中立安定は False、純虚軸極を含むモデルは
    False)。

    第三状態 (``"marginal"``) を返さない理由は ADR-0027 §(6) 参照: API の単純さを
    優先し、境界値が必要な利用者は :func:`eigenvalues` 直接利用。

    Args:
        ls: :class:`LinearSystem`。
        tol: マージン (default ``1e-9``、LAPACK ``geev`` の数値誤差を吸収)。

    Returns:
        ``True`` (漸近安定) / ``False`` (それ以外)。

    Raises:
        BlockSpecError: 空の状態空間。
        ValueError: ``tol < 0``。
    """
    if tol < 0.0:
        raise ValueError(f"is_stable: tol must be >= 0, got {tol}")
    eig_values = eigenvalues(ls)
    return bool(np.all(np.real(eig_values) < -tol))


# ---------------------------------------------------------------------------
# 根軌跡 (python-control 経由)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class RootLocus:
    """根軌跡データ (SISO のみ、ADR-0027 §(2)/§(7))。

    Attributes:
        roots: 各 K 値での閉ループ極の位置、shape ``(n_K, n_states)``、dtype complex。
        gains: 対応する K 値、shape ``(n_K,)``。
        input_idx: SISO 抽出に用いた入力 idx (= ``ls.B`` の列)。
        output_idx: SISO 抽出に用いた出力 idx (= ``ls.C`` の行)。
    """

    roots: np.ndarray
    gains: np.ndarray
    input_idx: int
    output_idx: int

    def plot(
        self,
        ax: Axes | None = None,
        *,
        show: bool = False,
    ) -> Axes:
        """根軌跡を複素平面に描画する (各極の K sweep を line plot)。"""
        import matplotlib.pyplot as plt

        if ax is None:
            _, ax = plt.subplots()
        for j in range(self.roots.shape[1]):
            ax.plot(
                np.real(self.roots[:, j]),
                np.imag(self.roots[:, j]),
                marker=".",
                markersize=2,
                linewidth=0.7,
            )
        ax.axhline(0.0, color="gray", linewidth=0.5)
        ax.axvline(0.0, color="gray", linewidth=0.5)
        ax.set_xlabel("Re")
        ax.set_ylabel("Im")
        ax.grid(True, linestyle=":")
        ax.set_title(f"Root locus (input[{self.input_idx}] → output[{self.output_idx}])")
        if show:
            plt.show()
        return ax


def _siso_extract(
    ls: LinearSystem, input_idx: int, output_idx: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """``ls`` から ``(input_idx, output_idx)`` SISO サブシステムを抽出する。

    A はそのまま、B は対象列のみ、C は対象行のみ、D は対象要素のみ。
    """
    n_in = ls.B.shape[1]
    n_out = ls.C.shape[0]
    if input_idx < 0 or input_idx >= n_in:
        raise BlockSpecError(
            f"root_locus: input_idx={input_idx} out of range (LinearSystem has {n_in} input(s))"
        )
    if output_idx < 0 or output_idx >= n_out:
        raise BlockSpecError(
            f"root_locus: output_idx={output_idx} out of range (LinearSystem has {n_out} output(s))"
        )
    A = np.asarray(ls.A, dtype=float)
    B = np.asarray(ls.B[:, input_idx : input_idx + 1], dtype=float)
    C = np.asarray(ls.C[output_idx : output_idx + 1, :], dtype=float)
    D = np.asarray(ls.D[output_idx : output_idx + 1, input_idx : input_idx + 1], dtype=float)
    return A, B, C, D


def root_locus(
    ls: LinearSystem,
    *,
    k_range: tuple[float, float] | np.ndarray | None = None,
    input_idx: int = 0,
    output_idx: int = 0,
) -> RootLocus:
    """SISO 抽出した伝達関数の根軌跡を計算する (ADR-0027 §(7))。

    MIMO ``LinearSystem`` の場合は ``input_idx`` / ``output_idx`` で SISO 抽出。

    Args:
        ls: :class:`LinearSystem`。
        k_range: K sweep 範囲。``(k_min, k_max)`` または明示 ndarray。``None`` で
            ``python-control`` のデフォルト (極零点の絶対値から推定された対数スケール)。
        input_idx: SISO 抽出する入力 idx (default ``0``)。
        output_idx: SISO 抽出する出力 idx (default ``0``)。

    Returns:
        :class:`RootLocus`。

    Raises:
        ImportError: ``pyflw[control]`` extras 未インストール。
        BlockSpecError: ``input_idx`` / ``output_idx`` 範囲外、空の状態空間。
    """
    if ls.A.shape[0] == 0:
        raise BlockSpecError(
            "root_locus: empty state-space (A.shape[0] == 0). "
            "Linearise a model with at least one continuous state first."
        )
    A, B, C, D = _siso_extract(ls, input_idx, output_idx)
    control = _import_control()
    siso = control.ss(A, B, C, D)
    # python-control 0.10 では ``root_locus_map`` が SISO 用、戻り値の構造は
    # ``(roots, gains)`` を持つ ``ContourList``-like オブジェクト or tuple。
    # ``rlocus`` (legacy) は figure を作る副作用ありなので ``root_locus_map`` を選択。
    if k_range is None:
        rl_data = control.root_locus_map(siso)
    elif isinstance(k_range, tuple) and len(k_range) == 2:
        # k_min, k_max を対数スケールで sweep
        k_min, k_max = float(k_range[0]), float(k_range[1])
        if k_min <= 0.0 or k_max <= k_min:
            raise BlockSpecError(
                f"root_locus: invalid k_range={k_range}; expect (k_min, k_max) with "
                f"0 < k_min < k_max"
            )
        gains = np.logspace(np.log10(k_min), np.log10(k_max), 50)
        rl_data = control.root_locus_map(siso, gains=gains)
    else:
        rl_data = control.root_locus_map(siso, gains=np.asarray(k_range, dtype=float))

    roots = np.asarray(rl_data.loci, dtype=complex)
    gains = np.asarray(rl_data.gains, dtype=float)
    # python-control では loci shape が ``(n_K, n_states)``。numpy default 形式。
    return RootLocus(
        roots=roots,
        gains=gains,
        input_idx=int(input_idx),
        output_idx=int(output_idx),
    )
