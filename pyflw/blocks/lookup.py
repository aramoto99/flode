"""SPEC-0008 / ADR-0059 (v5.1.0): 1 次元ルックアップテーブルブロック。

業界標準ブロック線図ツールの "Lookup Tables" カテゴリ第 1 弾。
``scipy.interpolate.interp1d`` を ``__init__`` で構築し、``output`` のホット
パスでは評価のみ行う。2-D / n-D は Wave 3 で後続 SPEC 送り。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt
from scipy.interpolate import interp1d

from ..core.block import Block
from ..exceptions import BlockEvalError, BlockSpecError


class LookupTable1D(Block):
    """1 次元ルックアップテーブル ``y = f(u)``。

    ブレークポイント配列 ``breakpoints`` (厳密単調増加) と対応するテーブル値
    ``table`` (同長) から区分関数を構成し、``interpolation`` で補間方式、
    ``extrapolation`` で定義域外の挙動を選択する。

    補間方式 ``interpolation``:

    * ``"linear"`` (既定) — 区分線形補間
    * ``"nearest"`` — 最も近いブレークポイントの値 (中点で切替)
    * ``"flat"`` — 前値ホールド (左側ブレークポイントの値、ステップ階段関数)

    外挿方式 ``extrapolation``:

    * ``"clip"`` (既定) — 端点値で飽和 (左端外で ``table[0]``、右端外で ``table[-1]``)
    * ``"linear"`` — 端点近傍 2 ブレークポイントから算出した傾きで線形外挿
    * ``"error"`` — 定義域外で :class:`BlockEvalError` を raise

    ``__init__`` で ``scipy.interpolate.interp1d`` を 1 度だけ構築し、
    ``self._interp`` に保持する。``output(t, x, u)`` ではこれを呼ぶだけ
    (毎ステップの再構築を避けるため)。

    Args:
        breakpoints: ブレークポイント配列 (厳密単調増加、長さ >= 2)。既定値
            ``[0.0, 1.0]`` は ``table=[0.0, 1.0]`` と組合せて恒等写像
            ``y = x`` (domain ``[0, 1]``) を表す。
        table: テーブル値配列。長さは ``breakpoints`` と一致必須。
        interpolation: 補間方式 (``"linear"`` / ``"nearest"`` / ``"flat"``)。
        extrapolation: 外挿方式 (``"clip"`` / ``"linear"`` / ``"error"``)。

    Raises:
        BlockSpecError: ``breakpoints`` の長さ不足・厳密単調増加違反、
            ``table`` 長不一致、``interpolation`` / ``extrapolation`` の enum 値外、
            または要素が float に coerce できないとき。

    Note:
        入力 ``nan`` は ``extrapolation`` 設定に関わらず ``nan`` を伝播する
        (scipy 仕様、ADR-0053 寛容方針と整合)。入力 ``±inf`` は ``extrapolation``
        設定に従う (clip で端点値、linear で ``±inf``、error で例外)。

        ``Simulator.compile()`` (ADR-0037 codegen + GPU jax) 経路では
        ``scipy.interpolate`` が XLA トレース不可なため fallback 対象になる。
    """

    _ALLOWED_INTERPOLATIONS: tuple[str, ...] = ("linear", "nearest", "flat")
    _ALLOWED_EXTRAPOLATIONS: tuple[str, ...] = ("clip", "linear", "error")
    # ADR-0019 / ADR-0039 follow-up: GUI ParameterPanel が enum select を出すヒント
    _param_enums = {
        "interpolation": _ALLOWED_INTERPOLATIONS,
        "extrapolation": _ALLOWED_EXTRAPOLATIONS,
    }

    # scipy interp1d の kind パラメータへのマッピング ("flat" は scipy の "previous")
    _KIND_MAP: dict[str, str] = {
        "linear": "linear",
        "nearest": "nearest",
        "flat": "previous",
    }

    def __init__(
        self,
        breakpoints: npt.ArrayLike = (0.0, 1.0),
        table: npt.ArrayLike = (0.0, 1.0),
        interpolation: str = "linear",
        extrapolation: str = "clip",
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        # enum 検証 (numpy 変換より先に明示エラーを出す)
        if interpolation not in self._ALLOWED_INTERPOLATIONS:
            raise BlockSpecError(
                f"LookupTable1D: interpolation must be one of {self._ALLOWED_INTERPOLATIONS}, "
                f"got {interpolation!r}"
            )
        if extrapolation not in self._ALLOWED_EXTRAPOLATIONS:
            raise BlockSpecError(
                f"LookupTable1D: extrapolation must be one of {self._ALLOWED_EXTRAPOLATIONS}, "
                f"got {extrapolation!r}"
            )

        # 配列を float 化 (混合型 / 非数値は TypeError → BlockSpecError にラップ)
        try:
            bp = np.asarray(breakpoints, dtype=float)
            tbl = np.asarray(table, dtype=float)
        except (TypeError, ValueError) as exc:
            raise BlockSpecError(
                f"LookupTable1D: breakpoints/table must contain numeric values: {exc}"
            ) from exc

        if bp.ndim != 1 or tbl.ndim != 1:
            raise BlockSpecError(
                f"LookupTable1D: breakpoints and table must be 1-D arrays, "
                f"got shapes {bp.shape} and {tbl.shape}"
            )
        if bp.size < 2:
            raise BlockSpecError(
                f"LookupTable1D: breakpoints must have at least 2 elements, got len={bp.size}"
            )
        if tbl.size != bp.size:
            raise BlockSpecError(
                f"LookupTable1D: len(table)={tbl.size} must equal len(breakpoints)={bp.size}"
            )
        if not np.all(np.diff(bp) > 0):
            raise BlockSpecError(
                f"LookupTable1D: breakpoints must be strictly increasing, got {bp.tolist()!r}"
            )

        super().__init__(id=id, name=name, n_inputs=1, n_outputs=1)

        self._breakpoints: npt.NDArray[np.float64] = bp
        self._table: npt.NDArray[np.float64] = tbl
        self.interpolation = interpolation
        self.extrapolation = extrapolation

        self._interp = self._build_interp(bp, tbl, interpolation, extrapolation)
        # 端点近傍 2 ブレークポイントから左右の slope を算出。
        # linear 外挿 × nearest/flat 補間の組合せでのみ output() で使うが、
        # ホットパスを単純化するため条件分岐せず常に保持する (cost は加減乗のみ)。
        self._left_slope, self._right_slope = self._endpoint_slopes(bp, tbl)

        # ADR-0008 PS-A: np.ndarray → list 自動変換で永続化、schema bump 不要。
        self._params = {
            "breakpoints": bp.tolist(),
            "table": tbl.tolist(),
            "interpolation": interpolation,
            "extrapolation": extrapolation,
        }

    @staticmethod
    def _build_interp(
        bp: npt.NDArray[np.float64],
        tbl: npt.NDArray[np.float64],
        interpolation: str,
        extrapolation: str,
    ) -> Any:
        kind = LookupTable1D._KIND_MAP[interpolation]
        if extrapolation == "error":
            # scipy が定義域外で ValueError を raise → output() で BlockEvalError にラップ
            return interp1d(bp, tbl, kind=kind, bounds_error=True, assume_sorted=True)
        if extrapolation == "clip":
            return interp1d(
                bp,
                tbl,
                kind=kind,
                bounds_error=False,
                fill_value=(float(tbl[0]), float(tbl[-1])),
                assume_sorted=True,
            )
        # extrapolation == "linear"
        if interpolation == "linear":
            # scipy 標準の外挿 (端点近傍の傾きを線形に延ばす) と等価
            return interp1d(
                bp,
                tbl,
                kind="linear",
                bounds_error=False,
                fill_value="extrapolate",
                assume_sorted=True,
            )
        # nearest / flat + linear extrapolation は scipy が直接サポートしない。
        # 定義域内は kind で評価し、定義域外は output() 側で独自 slope 外挿する。
        # 定義域外は一旦 nan を返させ、output() で上書きする。
        return interp1d(
            bp,
            tbl,
            kind=kind,
            bounds_error=False,
            fill_value=np.nan,
            assume_sorted=True,
        )

    @staticmethod
    def _endpoint_slopes(
        bp: npt.NDArray[np.float64], tbl: npt.NDArray[np.float64]
    ) -> tuple[float, float]:
        """端点近傍 2 ブレークポイントから左右の slope を算出する。

        linear 外挿 × nearest/flat 補間の組合せでのみ使われる。breakpoints は
        厳密単調増加が __init__ で保証されているため、divisor は常に正。
        """
        left = float((tbl[1] - tbl[0]) / (bp[1] - bp[0]))
        right = float((tbl[-1] - tbl[-2]) / (bp[-1] - bp[-2]))
        return left, right

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        val = float(np.asarray(u).reshape(-1)[0])
        try:
            y = float(self._interp(val))
        except ValueError as exc:
            # extrapolation="error" + 定義域外
            raise BlockEvalError(
                f"LookupTable1D[{self.name}]: input {val} is outside breakpoints "
                f"[{float(self._breakpoints[0])}, {float(self._breakpoints[-1])}] "
                f"and extrapolation='error'",
                block_id=self.id,
            ) from exc

        # nearest / flat + linear 外挿: 定義域外を独自 slope で上書き
        if (
            self.extrapolation == "linear"
            and self.interpolation in ("nearest", "flat")
            and not np.isnan(val)
        ):
            if val < self._breakpoints[0]:
                y = float(self._table[0]) + self._left_slope * (val - float(self._breakpoints[0]))
            elif val > self._breakpoints[-1]:
                y = float(self._table[-1]) + self._right_slope * (
                    val - float(self._breakpoints[-1])
                )

        return np.array([y])
