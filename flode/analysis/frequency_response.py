"""周波数応答 (Bode / Nyquist) — ADR-0027 §(1)A / §(2)。

``LinearSystem`` (ADR-0026) を入力に取り、``python-control`` の
``frequency_response`` を薄くラップして ``BodeResponse`` / ``NyquistResponse``
を返す。可視化は ``Scope.plot`` (ADR-0023) と同じパターンで matplotlib に委譲。

依存:

- :mod:`numpy` (コア)
- :mod:`control` — ``pyflw[control]`` extras 経由 (未インストール時は ``ImportError``
  で ``pip install pyflw[control]`` を案内、ADR-0027 §(10) E1)。
- :mod:`matplotlib.pyplot` — 可視化のみ、import は ``plot()`` 内で遅延。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt

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
# BodeResponse
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class BodeResponse:
    """Bode 応答データ (ADR-0027 §(2))。

    ``magnitude``/``phase`` は ``(p, m, n_omega)`` の 3D ndarray (= ``python-control``
    0.10 の標準形式)。SISO (p=m=1) の場合も 3D を維持し、利用者は ``[0, 0, :]`` で
    1D 化する。

    Attributes:
        magnitude: 線形振幅。shape ``(p, m, n_omega)``。
        phase: 位相 [rad]。shape ``(p, m, n_omega)``。
        omega: 周波数 [rad/s] または [Hz]、shape ``(n_omega,)``。
        is_hz: ``omega`` が Hz 単位か rad/s 単位か (default ``False`` = rad/s)。
        input_names: ``LinearSystem.input_names`` のコピー (introspection 用)。
        output_names: ``LinearSystem.output_names`` のコピー。

    Note:
        ``frozen=True, eq=False`` (= ADR-0026 ``LinearSystem`` と同じ規約)。
        ndarray 含む dataclass の ``__eq__`` は truth-ambiguous になるため eq 無効。
    """

    magnitude: npt.NDArray[Any]
    phase: npt.NDArray[Any]
    omega: npt.NDArray[Any]
    is_hz: bool
    input_names: list[str]
    output_names: list[str]

    def magnitude_db(self) -> npt.NDArray[Any]:
        """振幅を dB に変換するヘルパ (``20 * log10(abs(magnitude))``)。

        Returns:
            shape ``(p, m, n_omega)``、単位 dB。

        Note:
            反共振点 (``magnitude == 0``) では ``-inf`` を返す。matplotlib は描画時に
            自動 skip する (ADR-0027 §Risks #2 の方針)。
        """
        return np.asarray(20.0 * np.log10(np.abs(self.magnitude)), dtype=float)

    def plot(
        self,
        ax: Axes | None = None,
        *,
        input_idx: int = 0,
        output_idx: int = 0,
        show: bool = False,
        deg: bool = True,
    ) -> Axes:
        """matplotlib で Bode 線図 (mag/phase 2 段) を描画する。

        Args:
            ax: 既存 ``Axes``。``None`` のとき ``plt.subplots(2, 1)`` で 2 段の axes を
                作る。指定する場合は対応する figure に位相用 twinx を生成する仕様にせず、
                単一の ``ax`` には magnitude のみ描画する (= 2 段プロット欲しい場合は
                ``None`` 指定が推奨、ADR-0023 ``Scope.plot`` パターン)。
            input_idx: SISO 抽出する入力 idx (default ``0``)。
            output_idx: SISO 抽出する出力 idx。
            show: ``True`` なら ``plt.show()`` を呼ぶ。
            deg: 位相を度で表示するか rad のままか (default ``True`` = degree)。

        Returns:
            ``ax`` (matplotlib.axes.Axes)。``ax=None`` で 2 段作った場合は magnitude
            軸 (上段)。
        """
        import matplotlib.pyplot as plt

        if input_idx < 0 or input_idx >= self.magnitude.shape[1]:
            raise BlockSpecError(
                f"BodeResponse.plot: input_idx={input_idx} out of range "
                f"[0, {self.magnitude.shape[1]})"
            )
        if output_idx < 0 or output_idx >= self.magnitude.shape[0]:
            raise BlockSpecError(
                f"BodeResponse.plot: output_idx={output_idx} out of range "
                f"[0, {self.magnitude.shape[0]})"
            )

        mag = np.asarray(self.magnitude_db()[output_idx, input_idx, :], dtype=float)
        ph = np.asarray(self.phase[output_idx, input_idx, :], dtype=float)
        if deg:
            ph = np.degrees(ph)
        x_label = "ω [Hz]" if self.is_hz else "ω [rad/s]"
        y_phase_label = "phase [deg]" if deg else "phase [rad]"

        if ax is None:
            _, axes = plt.subplots(2, 1, sharex=True)
            ax_mag, ax_phase = axes
        else:
            ax_mag = ax
            ax_phase = None

        ax_mag.semilogx(self.omega, mag)
        ax_mag.set_ylabel("magnitude [dB]")
        ax_mag.grid(True, which="both", linestyle=":")
        ax_mag.set_title(
            f"{self.output_names[output_idx]} ← {self.input_names[input_idx]}"
            if (self.output_names and self.input_names)
            else "Bode plot"
        )
        if ax_phase is not None:
            ax_phase.semilogx(self.omega, ph)
            ax_phase.set_xlabel(x_label)
            ax_phase.set_ylabel(y_phase_label)
            ax_phase.grid(True, which="both", linestyle=":")
        else:
            ax_mag.set_xlabel(x_label)

        if show:
            plt.show()
        # ``ax_mag`` は呼び出し元から渡された ``ax`` または ``plt.subplots(2, 1)`` で
        # 作った上段 axes。``Axes`` 型は ``mypy.overrides = ignore_missing_imports`` で
        # Any に縮退するため、戻り型整合のため明示 ignore。
        return ax_mag  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# NyquistResponse
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class NyquistResponse:
    """Nyquist 軌跡データ (ADR-0027 §(2))。

    Attributes:
        response: 複素応答 G(jω)、shape ``(p, m, n_omega)``、dtype complex128。
        omega: 周波数 [rad/s]、shape ``(n_omega,)``。
        input_names / output_names: ``LinearSystem`` ラベル継承。
    """

    response: npt.NDArray[Any]
    omega: npt.NDArray[Any]
    input_names: list[str]
    output_names: list[str]

    def plot(
        self,
        ax: Axes | None = None,
        *,
        input_idx: int = 0,
        output_idx: int = 0,
        show: bool = False,
    ) -> Axes:
        """Nyquist 軌跡を複素平面 (Re-Im) に描画する。"""
        import matplotlib.pyplot as plt

        if input_idx < 0 or input_idx >= self.response.shape[1]:
            raise BlockSpecError(
                f"NyquistResponse.plot: input_idx={input_idx} out of range "
                f"[0, {self.response.shape[1]})"
            )
        if output_idx < 0 or output_idx >= self.response.shape[0]:
            raise BlockSpecError(
                f"NyquistResponse.plot: output_idx={output_idx} out of range "
                f"[0, {self.response.shape[0]})"
            )

        if ax is None:
            _, ax = plt.subplots()
        g = self.response[output_idx, input_idx, :]
        ax.plot(np.real(g), np.imag(g))
        ax.plot(np.real(g), -np.imag(g), linestyle="--")  # 共役軌跡
        ax.axhline(0.0, color="gray", linewidth=0.5)
        ax.axvline(0.0, color="gray", linewidth=0.5)
        ax.scatter([-1.0], [0.0], marker="x", color="red", label="-1 + 0j")
        ax.set_xlabel("Re(G)")
        ax.set_ylabel("Im(G)")
        ax.set_aspect("equal", adjustable="datalim")
        ax.grid(True, linestyle=":")
        ax.set_title(
            f"Nyquist {self.output_names[output_idx]} ← {self.input_names[input_idx]}"
            if (self.output_names and self.input_names)
            else "Nyquist plot"
        )
        ax.legend()
        if show:
            plt.show()
        return ax


# ---------------------------------------------------------------------------
# 関数 API: bode / nyquist
# ---------------------------------------------------------------------------


def _validate_linear_system(ls: LinearSystem) -> None:
    if ls.A.shape[0] == 0:
        raise BlockSpecError(
            "Frequency response requires a non-empty state-space (A.shape[0] > 0). "
            "Linearise a model with at least one continuous state first."
        )


def bode(
    ls: LinearSystem,
    *,
    omega: npt.NDArray[Any] | None = None,
    omega_limits: tuple[float, float] | None = None,
    omega_num: int | None = None,
    Hz: bool = False,
) -> BodeResponse:
    """``LinearSystem`` の Bode 応答 (magnitude / phase) を計算する。

    内部で ``python-control.frequency_response`` を呼ぶ。``pyflw[control]`` extras が
    必要 (ADR-0027 §Decision Option 3 hybrid)。

    Args:
        ls: ADR-0026 :class:`LinearSystem`。
        omega: 周波数グリッド [rad/s]。``None`` のとき ``python-control`` の自動
            範囲 (極零点の log10 spread に基づく)。
        omega_limits: ``(omega_min, omega_max)`` を log10 スケールで指定。``omega``
            と排他。
        omega_num: 自動 omega の点数 (``None`` で control デフォルト)。
        Hz: ``True`` で周波数を Hz 単位として返す (内部計算は rad/s)。

    Returns:
        :class:`BodeResponse`。

    Raises:
        ImportError: ``pyflw[control]`` extras 未インストール。
        BlockSpecError: ``ls`` が空の状態空間 (``A.shape[0] == 0``) または
            ``omega``/``omega_limits`` の同時指定。
    """
    _validate_linear_system(ls)
    if omega is not None and omega_limits is not None:
        raise BlockSpecError("bode: pass either omega or omega_limits, not both")
    control = _import_control()
    sys_ss = ls.to_control_ss()
    fr = control.frequency_response(
        sys_ss,
        omega=omega,
        omega_limits=omega_limits,
        omega_num=omega_num,
        Hz=Hz,
        squeeze=False,
    )
    mag = np.asarray(fr.magnitude, dtype=float)
    phase = np.asarray(fr.phase, dtype=float)
    omega_arr = np.asarray(fr.omega, dtype=float)
    # python-control 0.10 では SISO 時に shape (n_omega,) を返すケースもあるため
    # ``squeeze=False`` を渡しているが、念のため次元が落ちていれば 3D に揃える
    if mag.ndim == 1:
        mag = mag.reshape(1, 1, -1)
        phase = phase.reshape(1, 1, -1)
    return BodeResponse(
        magnitude=mag,
        phase=phase,
        omega=omega_arr,
        is_hz=bool(Hz),
        input_names=list(ls.input_names),
        output_names=list(ls.output_names),
    )


def nyquist(
    ls: LinearSystem,
    *,
    omega: npt.NDArray[Any] | None = None,
    omega_limits: tuple[float, float] | None = None,
    omega_num: int | None = None,
) -> NyquistResponse:
    """``LinearSystem`` の Nyquist 軌跡 (G(jω) 複素応答) を計算する。

    Args:
        ls: :class:`LinearSystem`。
        omega: 周波数グリッド。``None`` で control 自動範囲。
        omega_limits: ``(omega_min, omega_max)`` log10 スケール。``omega`` と排他。
        omega_num: 自動 omega の点数。

    Returns:
        :class:`NyquistResponse`。

    Raises:
        ImportError: ``pyflw[control]`` extras 未インストール。
        BlockSpecError: 空の状態空間 / ``omega`` ``omega_limits`` 同時指定。
    """
    _validate_linear_system(ls)
    if omega is not None and omega_limits is not None:
        raise BlockSpecError("nyquist: pass either omega or omega_limits, not both")
    control = _import_control()
    sys_ss = ls.to_control_ss()
    fr = control.frequency_response(
        sys_ss,
        omega=omega,
        omega_limits=omega_limits,
        omega_num=omega_num,
        squeeze=False,
    )
    mag = np.asarray(fr.magnitude, dtype=float)
    phase = np.asarray(fr.phase, dtype=float)
    if mag.ndim == 1:
        mag = mag.reshape(1, 1, -1)
        phase = phase.reshape(1, 1, -1)
    response = mag * np.exp(1j * phase)
    return NyquistResponse(
        response=np.asarray(response, dtype=complex),
        omega=np.asarray(fr.omega, dtype=float),
        input_names=list(ls.input_names),
        output_names=list(ls.output_names),
    )
