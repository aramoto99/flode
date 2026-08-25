"""SPEC-0008 + SPEC-0017 + SPEC-0018 + SPEC-0019 / ADR-0059 (v5.1.0+): ルックアップ系ブロック群。

業界標準ブロック線図ツールの "Lookup Tables" カテゴリ全種を提供する。

* Wave 1: :class:`LookupTable1D` (SPEC-0008, v5.1.0)
* Wave 3 第 1 弾: :class:`LookupTable2D` (SPEC-0017, v5.6.0)
* Wave 3 第 2 弾: :class:`Prelookup` + :class:`InterpolationUsingPrelookup`
  (SPEC-0019, v5.7.0)
* Wave 3 第 3 弾: :class:`LookupTableND` (SPEC-0018, v5.8.0、3〜n 次元)

補間オブジェクトは ``__init__`` で 1 度だけ構築し、``output`` のホットパスでは
評価のみ行う (ADR-0064 §A-1、ADR-0068 §A-1)。
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy.interpolate import RegularGridInterpolator, interp1d

from ..core.block import Block
from ..exceptions import BlockEvalError, BlockSpecError

_logger = logging.getLogger(__name__)

#: ADR-0068 §D-1: 軸数がこの値を超えると ``LookupTableND`` 構築時に warning を出す
#: (hard limit ではない)。
LOOKUP_ND_AXIS_WARNING_THRESHOLD = 6


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

    def _extrapolate_from_edge(self, val: float) -> float:
        """定義域外の ``val`` を端点 slope で線形外挿する (linear 外挿専用)。

        ``slope == 0`` かつ ``val = ±inf`` は ``0 * inf = nan`` になるため、
        極限値 (= 端点値) を直接返す。
        """
        if val < float(self._breakpoints[0]):
            edge_x, edge_y, slope = (
                float(self._breakpoints[0]),
                float(self._table[0]),
                self._left_slope,
            )
        else:
            edge_x, edge_y, slope = (
                float(self._breakpoints[-1]),
                float(self._table[-1]),
                self._right_slope,
            )
        if slope == 0.0 and np.isinf(val):
            return edge_y
        return edge_y + slope * (val - edge_x)

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        val = float(np.asarray(u).reshape(-1)[0])

        # ±inf × linear 外挿: scipy 1.18+ の interp1d は外挿を lerp 形式
        # ``y_lo*(1-t) + y_hi*t`` で計算するため inf - inf = nan (+ RuntimeWarning)
        # になる (~1.17 は point-slope 形式で ±inf を返していた)。scipy を呼ばず
        # 全補間方式で端点 slope から極限値を直接計算する。
        if self.extrapolation == "linear" and np.isinf(val):
            return np.array([self._extrapolate_from_edge(val)])

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

        # nearest / flat + linear 外挿: scipy が直接サポートしないため、
        # 定義域外 (有限) を独自 slope で上書き (±inf は上で処理済み)
        if (
            self.extrapolation == "linear"
            and self.interpolation in ("nearest", "flat")
            and not np.isnan(val)
            and (val < self._breakpoints[0] or val > self._breakpoints[-1])
        ):
            y = self._extrapolate_from_edge(val)

        return np.array([y])


class LookupTable2D(Block):
    """2 次元ルックアップテーブル ``y = f(u[0], u[1])``。

    2 つのブレークポイント配列 (``breakpoints_row`` / ``breakpoints_col``、
    各々厳密単調増加) と shape ``(len(breakpoints_row), len(breakpoints_col))``
    のテーブル値 ``table`` から 2-D 区分関数を構成する。``table[i][j]`` は
    ``(breakpoints_row[i], breakpoints_col[j])`` 上の値 (行優先 = numpy 慣習、
    SPEC-0017 §論点 2 確定)。

    軸の意味付け (SPEC-0017 §論点 1 確定):

    * ``u[0]`` = row 軸 (``breakpoints_row``)
    * ``u[1]`` = col 軸 (``breakpoints_col``)

    補間方式 ``interpolation``:

    * ``"linear"`` (既定) — 双線形 (bilinear) 補間。``RegularGridInterpolator``
      の ``method="linear"`` を利用
    * ``"nearest"`` — 最も近い格子点の値。各軸独立に中点で切替
    * ``"flat"`` — 左下角ホールド (SPEC-0017 §論点 3 確定)。``(u[0], u[1])`` を
      含む cell ``(i, j)`` = ``[bp_row[i], bp_row[i+1]) × [bp_col[j], bp_col[j+1])``
      の値 = ``table[i][j]``。1-D ``"flat"`` (左側 breakpoint 値) の自然な 2-D 拡張、
      ``np.searchsorted(side="right")`` で実装

    外挿方式 ``extrapolation``:

    * ``"clip"`` (既定) — 各軸で端点に飽和してから補間
    * ``"linear"`` — 2 段階 1-D 外挿の合成 (SPEC-0017 §論点 4 / ADR-0064 §B-1
      確定)。row 軸方向に 1-D 線形外挿で各 col の中間値を求め (= row_strip)、
      次に col 軸方向に row_strip を 1-D 線形外挿。4 隅外は双線形外挿、エッジ外
      は 1 軸線形外挿になる。``interpolation`` 設定と直交 (内側補間と外側外挿の
      分離原則)
    * ``"error"`` — 定義域外で :class:`BlockEvalError` を raise

    Args:
        breakpoints_row: row 軸ブレークポイント (厳密単調増加、長さ >= 2)。
            既定値 ``[0.0, 1.0]``。``u[0]`` がこの軸に沿って補間される。
        breakpoints_col: col 軸ブレークポイント (厳密単調増加、長さ >= 2)。
            既定値 ``[0.0, 1.0]``。
        table: 2-D テーブル値。shape ``(len(breakpoints_row), len(breakpoints_col))``。
            既定値 ``[[0.0, 0.0], [0.0, 0.0]]`` (ゼロ平面 = 対称な自明な既定)。
        interpolation: 補間方式 (``"linear"`` / ``"nearest"`` / ``"flat"``)。
        extrapolation: 外挿方式 (``"clip"`` / ``"linear"`` / ``"error"``)。

    Raises:
        BlockSpecError: ブレークポイント長不足・厳密単調増加違反、``table`` の
            shape 不一致 / jagged / 次元違反、enum 値外、要素の数値 coerce 失敗。

    Note:
        入力 ``nan`` / ``±inf`` の挙動は 1-D と同方針 (寛容)。``extrapolation``
        設定に従い ``nan`` 伝播 / 端点飽和 / 例外。

        実用上限は 50×50 程度を目安とする (SPEC-0017 §非機能要件)。それ以上の
        サイズも構築・評価は可能だが、frontend ``<GridEditor>`` の描画が重くなる。
        virtualization は SPEC-0018 (n-D Lookup) で再考。
    """

    _ALLOWED_INTERPOLATIONS: tuple[str, ...] = ("linear", "nearest", "flat")
    _ALLOWED_EXTRAPOLATIONS: tuple[str, ...] = ("clip", "linear", "error")
    _param_enums = {
        "interpolation": _ALLOWED_INTERPOLATIONS,
        "extrapolation": _ALLOWED_EXTRAPOLATIONS,
    }

    def __init__(
        self,
        breakpoints_row: npt.ArrayLike = (0.0, 1.0),
        breakpoints_col: npt.ArrayLike = (0.0, 1.0),
        table: npt.ArrayLike = ((0.0, 0.0), (0.0, 0.0)),
        interpolation: str = "linear",
        extrapolation: str = "clip",
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if interpolation not in self._ALLOWED_INTERPOLATIONS:
            raise BlockSpecError(
                f"LookupTable2D: interpolation must be one of {self._ALLOWED_INTERPOLATIONS}, "
                f"got {interpolation!r}"
            )
        if extrapolation not in self._ALLOWED_EXTRAPOLATIONS:
            raise BlockSpecError(
                f"LookupTable2D: extrapolation must be one of {self._ALLOWED_EXTRAPOLATIONS}, "
                f"got {extrapolation!r}"
            )

        try:
            bp_row = np.asarray(breakpoints_row, dtype=float)
            bp_col = np.asarray(breakpoints_col, dtype=float)
        except (TypeError, ValueError) as exc:
            raise BlockSpecError(
                f"LookupTable2D: breakpoints must contain numeric values: {exc}"
            ) from exc

        if bp_row.ndim != 1:
            raise BlockSpecError(
                f"LookupTable2D: breakpoints_row must be a 1-D array, got shape {bp_row.shape}"
            )
        if bp_col.ndim != 1:
            raise BlockSpecError(
                f"LookupTable2D: breakpoints_col must be a 1-D array, got shape {bp_col.shape}"
            )
        if bp_row.size < 2:
            raise BlockSpecError(
                f"LookupTable2D: breakpoints_row must have at least 2 elements, got len={bp_row.size}"
            )
        if bp_col.size < 2:
            raise BlockSpecError(
                f"LookupTable2D: breakpoints_col must have at least 2 elements, got len={bp_col.size}"
            )
        if not np.all(np.diff(bp_row) > 0):
            raise BlockSpecError(
                f"LookupTable2D: breakpoints_row must be strictly increasing, "
                f"got {bp_row.tolist()!r}"
            )
        if not np.all(np.diff(bp_col) > 0):
            raise BlockSpecError(
                f"LookupTable2D: breakpoints_col must be strictly increasing, "
                f"got {bp_col.tolist()!r}"
            )

        # jagged な list (= 行ごとに長さが異なる) は np.asarray が numpy >= 2.0 で
        # ValueError を投げる。早期に BlockSpecError へラップする。
        try:
            tbl = np.asarray(table, dtype=float)
        except (TypeError, ValueError) as exc:
            raise BlockSpecError(
                f"LookupTable2D: table must be a regular 2-D array of numeric values "
                f"(got jagged shape or non-numeric): {exc}"
            ) from exc

        if tbl.ndim != 2:
            raise BlockSpecError(
                f"LookupTable2D: table must be 2-D, got ndim={tbl.ndim} shape={tbl.shape}"
            )
        expected_shape = (int(bp_row.size), int(bp_col.size))
        if tbl.shape != expected_shape:
            raise BlockSpecError(
                f"LookupTable2D: table.shape={tbl.shape} must equal "
                f"(len(breakpoints_row), len(breakpoints_col))={expected_shape}"
            )

        super().__init__(id=id, name=name, n_inputs=2, n_outputs=1)

        self._bp_row: npt.NDArray[np.float64] = bp_row
        self._bp_col: npt.NDArray[np.float64] = bp_col
        self._table: npt.NDArray[np.float64] = tbl
        self.interpolation = interpolation
        self.extrapolation = extrapolation

        # 定義域内補間: linear / nearest は scipy RegularGridInterpolator。
        # flat は独自実装 (scipy 非対応)。"error" 検出は output() 側で行うため、
        # ここでは bounds_error=False で構築 (定義域外は post-process で扱う)。
        scipy_method = "linear" if interpolation == "linear" else "nearest"
        # flat の場合も RegularGridInterpolator は構築するが output で参照しない。
        # 構築コスト微小、コードの単純化を優先 (ADR-0064 §A-1 1 回構築方針)。
        self._interp = RegularGridInterpolator(
            (bp_row, bp_col),
            tbl,
            method=scipy_method,
            bounds_error=False,
            fill_value=np.nan,
        )

        # linear 外挿用: row 軸方向に table 全体を 1-D 線形補間/外挿する interp1d。
        # axis=0 で構築すると interp1d(u0) は shape (n_col,) を返し、これを再度
        # col 軸方向に 1-D 線形外挿して最終値を得る (2 段階 1-D 外挿の合成、
        # ADR-0064 §B-1)。
        self._row_extrap_1d = interp1d(
            bp_row,
            tbl,
            axis=0,
            kind="linear",
            bounds_error=False,
            fill_value="extrapolate",
            assume_sorted=True,
        )

        self._params = {
            "breakpoints_row": bp_row.tolist(),
            "breakpoints_col": bp_col.tolist(),
            "table": tbl.tolist(),
            "interpolation": interpolation,
            "extrapolation": extrapolation,
        }

    def _flat_lookup(self, u0: float, u1: float) -> float:
        """``"flat"`` 補間: cell ``(i, j)`` の左下角値 = ``table[i][j]`` を返す。

        ``np.searchsorted(side="right") - 1`` + ``clip([0, len-2])`` で 1-D
        ``"flat"`` (左側 breakpoint 値) の 2-D 拡張。境界点 (例 ``u = bp[-1]``)
        は右側 cell の左下角扱い。
        """
        i = int(
            np.clip(np.searchsorted(self._bp_row, u0, side="right") - 1, 0, self._bp_row.size - 2)
        )
        j = int(
            np.clip(np.searchsorted(self._bp_col, u1, side="right") - 1, 0, self._bp_col.size - 2)
        )
        return float(self._table[i, j])

    def _linear_extrapolate(self, u0: float, u1: float) -> float:
        """``"linear"`` 外挿: 2 段階 1-D 外挿の合成 (ADR-0064 §B-1)。

        1. row 軸方向に ``table`` を 1-D 線形外挿で ``u0`` で評価
           → shape ``(n_col,)`` の row_strip
        2. col 軸方向に row_strip を 1-D 線形外挿で ``u1`` で評価

        4 隅外 (両軸外) は数学的に双線形外挿になり cross term を自動含有。
        ``interpolation`` 設定と独立 (内側補間方式に関わらず外挿は常に線形)。
        """
        row_strip = np.asarray(self._row_extrap_1d(u0)).reshape(-1)
        # row_strip は length n_col の 1-D 配列。col 方向に再度 1-D 線形外挿。
        # 毎回構築するが、外挿経路はホットパスではないため許容 (SPEC-0017 §非機能要件)。
        col_extrap = interp1d(
            self._bp_col,
            row_strip,
            kind="linear",
            bounds_error=False,
            fill_value="extrapolate",
            assume_sorted=True,
        )
        return float(col_extrap(u1))

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        u_arr = np.asarray(u).reshape(-1)
        u0 = float(u_arr[0])
        u1 = float(u_arr[1])

        # nan は比較が全て False になるため、in_row/in_col は False となり
        # extrapolation 経路に入る (== 1-D と同方針)。
        in_row = bool(self._bp_row[0] <= u0 <= self._bp_row[-1])
        in_col = bool(self._bp_col[0] <= u1 <= self._bp_col[-1])

        if not (in_row and in_col):
            if self.extrapolation == "error":
                # nan / inf や定義域外で例外 (構造化エラー protocol)
                raise BlockEvalError(
                    f"LookupTable2D[{self.name}]: input ({u0}, {u1}) is outside "
                    f"breakpoints_row [{float(self._bp_row[0])}, {float(self._bp_row[-1])}] "
                    f"× breakpoints_col [{float(self._bp_col[0])}, {float(self._bp_col[-1])}] "
                    f"and extrapolation='error'",
                    block_id=self.id,
                )
            if self.extrapolation == "linear":
                # nan は伝播 (np.isnan で early return、interp1d が nan を返すため不要)
                y = self._linear_extrapolate(u0, u1)
                return np.array([y])
            # extrapolation == "clip": 端点に飽和してから補間
            u0 = float(np.clip(u0, self._bp_row[0], self._bp_row[-1]))
            u1 = float(np.clip(u1, self._bp_col[0], self._bp_col[-1]))

        if self.interpolation == "flat":
            # nan が clip 後に残るのは clip(nan)=nan の場合 (ありうる)
            if np.isnan(u0) or np.isnan(u1):
                return np.array([float("nan")])
            y = self._flat_lookup(u0, u1)
        else:
            # RegularGridInterpolator は shape (npts, ndim) を期待 → (1, 2) で渡す。
            # 戻り値は shape (1,) なので .item() で scalar 抽出 (numpy 2.0 警告回避)。
            y = float(self._interp(np.array([[u0, u1]])).item())
        return np.array([y])


class Prelookup(Block):
    """1-D Prelookup: 入力 ``u`` から ``(k, f)`` を分離出力する (SPEC-0019)。

    breakpoints 検索結果を `(k=index, f=fraction)` の 2 出力に分離することで、
    後段の :class:`InterpolationUsingPrelookup` 複数本で **検索コストを共有**
    する設計パターンに使う。1-D に対し ``u → k, f`` の前処理段。

    数値仕様 (ADR-0067 §A-1 採用、純 numpy):

    * 定義域内: ``k = clip(searchsorted(bp, u, side="right") - 1, 0, n-2)``、
      ``f = (u - bp[k]) / (bp[k+1] - bp[k])``
    * 定義域外 + ``"clip"``: ``u`` を端点に飽和してから上式
    * 定義域外 + ``"linear"`` (ADR-0067 §B-1): 端点 cell に ``k`` を固定し、
      ``f`` が ``[0, 1]`` を外れる値で出力。後段の線形補間式
      ``y = table[k] + f*(table[k+1]-table[k])`` に流れることで自動で線形外挿
    * 定義域外 + ``"error"``: :class:`BlockEvalError`

    Args:
        breakpoints: ブレークポイント配列 (厳密単調増加、長さ >= 2)。既定値
            ``[0.0, 1.0]``。
        extrapolation: 外挿方式 (``"clip"`` / ``"linear"`` / ``"error"``)。

    Raises:
        BlockSpecError: ``breakpoints`` の長さ不足・厳密単調増加違反、
            ``extrapolation`` の enum 値外、または要素が float に coerce できない。

    Note:
        scipy 不使用の純 numpy 実装 (SPEC-0008/0017 とは対照的)。
    """

    _ALLOWED_EXTRAPOLATIONS: tuple[str, ...] = ("clip", "linear", "error")
    _param_enums = {"extrapolation": _ALLOWED_EXTRAPOLATIONS}

    def __init__(
        self,
        breakpoints: npt.ArrayLike = (0.0, 1.0),
        extrapolation: str = "clip",
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if extrapolation not in self._ALLOWED_EXTRAPOLATIONS:
            raise BlockSpecError(
                f"Prelookup: extrapolation must be one of {self._ALLOWED_EXTRAPOLATIONS}, "
                f"got {extrapolation!r}"
            )

        try:
            bp = np.asarray(breakpoints, dtype=float)
        except (TypeError, ValueError) as exc:
            raise BlockSpecError(
                f"Prelookup: breakpoints must contain numeric values: {exc}"
            ) from exc

        if bp.ndim != 1:
            raise BlockSpecError(
                f"Prelookup: breakpoints must be a 1-D array, got shape {bp.shape}"
            )
        if bp.size < 2:
            raise BlockSpecError(
                f"Prelookup: breakpoints must have at least 2 elements, got len={bp.size}"
            )
        if not np.all(np.diff(bp) > 0):
            raise BlockSpecError(
                f"Prelookup: breakpoints must be strictly increasing, got {bp.tolist()!r}"
            )

        super().__init__(id=id, name=name, n_inputs=1, n_outputs=2)

        self._breakpoints: npt.NDArray[np.float64] = bp
        self.extrapolation = extrapolation

        self._params = {
            "breakpoints": bp.tolist(),
            "extrapolation": extrapolation,
        }

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        val = float(np.asarray(u).reshape(-1)[0])
        bp = self._breakpoints
        n = bp.size

        if np.isnan(val):
            # nan は 1-D LookupTable と同方針で伝播
            return np.array([float("nan"), float("nan")])

        in_domain = bool(bp[0] <= val <= bp[-1])

        if not in_domain:
            if self.extrapolation == "error":
                raise BlockEvalError(
                    f"Prelookup[{self.name}]: input {val} is outside breakpoints "
                    f"[{float(bp[0])}, {float(bp[-1])}] and extrapolation='error'",
                    block_id=self.id,
                )
            if self.extrapolation == "linear":
                # 端点 cell に k を固定、f は区間外値で出力 (後段で線形外挿)
                if val < bp[0]:
                    k = 0
                else:  # val > bp[-1] (inf 含む)
                    k = n - 2
                f = (val - float(bp[k])) / (float(bp[k + 1]) - float(bp[k]))
                return np.array([float(k), f])
            # extrapolation == "clip": 端点に飽和
            val = float(np.clip(val, bp[0], bp[-1]))

        # 定義域内 (or clip 後): 純 numpy 検索
        k = int(np.clip(np.searchsorted(bp, val, side="right") - 1, 0, n - 2))
        f = (val - float(bp[k])) / (float(bp[k + 1]) - float(bp[k]))
        return np.array([float(k), f])


class InterpolationUsingPrelookup(Block):
    """1-D Prelookup を用いた補間 (SPEC-0019)。

    :class:`Prelookup` の出力 ``(k, f)`` を受け取り、内部 ``table`` から
    ``y`` を計算する。同じ breakpoints を複数の table で共有する設計
    パターン (= 検索コスト分離) のための後段ブロック。

    補間方式 ``interpolation``:

    * ``"linear"`` (既定) — ``y = table[k] + f * (table[k+1] - table[k])``。
      ``f`` が ``[0, 1]`` 範囲外でも数式が自動的に線形外挿になる (Prelookup
      側で ``extrapolation="linear"`` を選択した時の経路、ADR-0067 §B-1)
    * ``"nearest"`` — ``y = table[k+1] if f >= 0.5 else table[k]``。
      ``LookupTable1D(interpolation="nearest")`` は scipy の中点丸め
      (``f=0.5`` のとき左側) を採用、本ブロックは ``f>=0.5`` で右側 (1 LSB
      差を許容、ADR-0067 §OQ5)
    * ``"flat"`` — ``y = table[k]`` (``f`` を無視、左側値ホールド)

    ``k`` は :class:`Prelookup` が出力する想定 ``[0, n-2]`` だが、上流に
    別のブロックが入っているケースに備えて黙って ``clip([0, n-2])`` する
    (``BlockEvalError`` は投げない、ADR-0067 §B-1 / Consequences §ネガティブ)。

    Args:
        table: テーブル値配列 (1-D、長さ >= 2)。既定値 ``[0.0, 1.0]``。
        interpolation: 補間方式 (``"linear"`` / ``"nearest"`` / ``"flat"``)。

    Raises:
        BlockSpecError: ``table`` の長さ不足 / 1-D 違反 / 数値 coerce 失敗、
            ``interpolation`` の enum 値外。

    Note:
        scipy 不使用の純 numpy 実装。
    """

    _ALLOWED_INTERPOLATIONS: tuple[str, ...] = ("linear", "nearest", "flat")
    _param_enums = {"interpolation": _ALLOWED_INTERPOLATIONS}

    def __init__(
        self,
        table: npt.ArrayLike = (0.0, 1.0),
        interpolation: str = "linear",
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if interpolation not in self._ALLOWED_INTERPOLATIONS:
            raise BlockSpecError(
                f"InterpolationUsingPrelookup: interpolation must be one of "
                f"{self._ALLOWED_INTERPOLATIONS}, got {interpolation!r}"
            )

        try:
            tbl = np.asarray(table, dtype=float)
        except (TypeError, ValueError) as exc:
            raise BlockSpecError(
                f"InterpolationUsingPrelookup: table must contain numeric values: {exc}"
            ) from exc

        if tbl.ndim != 1:
            raise BlockSpecError(
                f"InterpolationUsingPrelookup: table must be a 1-D array, got shape {tbl.shape}"
            )
        if tbl.size < 2:
            raise BlockSpecError(
                f"InterpolationUsingPrelookup: table must have at least 2 elements, "
                f"got len={tbl.size}"
            )

        super().__init__(id=id, name=name, n_inputs=2, n_outputs=1)

        self._table: npt.NDArray[np.float64] = tbl
        self.interpolation = interpolation

        self._params = {
            "table": tbl.tolist(),
            "interpolation": interpolation,
        }

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        u_arr = np.asarray(u).reshape(-1)
        k_raw = float(u_arr[0])
        f = float(u_arr[1])
        tbl = self._table
        n = tbl.size

        # k / f の nan は伝播 (= nan 出力)。
        if np.isnan(k_raw) or np.isnan(f):
            return np.array([float("nan")])
        # k は黙って clip ([0, n-2])。Prelookup の出力域だが上流ブロック自由なので保険。
        # ``np.clip`` を ``int()`` より先に評価することで ``k_raw=±inf`` でも
        # OverflowError を避けて n-2 / 0 に飽和させる (ADR-0056 構造化エラー protocol)。
        k = int(np.clip(k_raw, 0, n - 2))

        if self.interpolation == "linear":
            y = float(tbl[k]) + f * (float(tbl[k + 1]) - float(tbl[k]))
        elif self.interpolation == "nearest":
            y = float(tbl[k + 1]) if f >= 0.5 else float(tbl[k])
        else:  # "flat"
            y = float(tbl[k])

        return np.array([y])


class LookupTableND(Block):
    """n 次元ルックアップテーブル ``y = f(u[0], u[1], ..., u[n-1])`` (SPEC-0018)。

    軸数 n は ``len(breakpoints_axes)`` で動的に決まる。``LookupTable1D`` (n=1) /
    ``LookupTable2D`` (n=2) の自然な n-D 拡張。3〜6 軸を想定スコープ、7 軸以上は
    warning + 構築可能 (hard limit なし、ADR-0068 §D-1)。

    軸の意味付け:
        ``breakpoints_axes[i]`` は軸 ``i`` の breakpoints。``table`` は
        ``np.ndarray`` 化したとき shape ``tuple(len(bp) for bp in breakpoints_axes)``
        を持つ。``table[i0, i1, ..., i_{n-1}]`` =
        ``(breakpoints_axes[0][i0], ..., breakpoints_axes[n-1][i_{n-1}])`` の値。

    補間方式 ``interpolation``:

    * ``"linear"`` — n 線形 (= tensorial linear) 補間。
      ``scipy.interpolate.RegularGridInterpolator(method="linear")``
    * ``"nearest"`` — 最も近い格子点の値。各軸独立に中点で切替
    * ``"flat"`` — 左下角ホールド (SPEC-0017 と同方針)。各軸独立に
      ``np.searchsorted(side="right")`` で cell を特定

    外挿方式 ``extrapolation``:

    * ``"clip"`` — 各軸で端点に飽和してから補間
    * ``"linear"`` — 2 段階 1-D 外挿の合成を n 軸に再帰拡張 (ADR-0068 §C-1)。
      各軸独立 1-D 線形延長の合成で n 軸線形外挿が自動成立 (cross term 含む)
    * ``"error"`` — 定義域外で :class:`BlockEvalError` を raise

    Args:
        breakpoints_axes: 各軸 breakpoints のリスト (各々厳密単調増加、長さ >= 2)。
            軸数 (= ``len(breakpoints_axes)``) は >= 2 必須。既定値
            ``[[0.0, 1.0], [0.0, 1.0]]`` (= 2 軸ゼロ平面、``LookupTable2D``
            既定と等価)。
        table: n-D テーブル値。shape は
            ``tuple(len(bp) for bp in breakpoints_axes)`` と一致必須。
        interpolation: 補間方式 (``"linear"`` / ``"nearest"`` / ``"flat"``)。
        extrapolation: 外挿方式 (``"clip"`` / ``"linear"`` / ``"error"``)。

    Raises:
        BlockSpecError: 軸数 < 2 / 各軸長さ < 2 / 厳密単調増加違反 / shape 不一致 /
            enum 値外 / 数値 coerce 失敗。
    """

    _ALLOWED_INTERPOLATIONS: tuple[str, ...] = ("linear", "nearest", "flat")
    _ALLOWED_EXTRAPOLATIONS: tuple[str, ...] = ("clip", "linear", "error")
    _param_enums = {
        "interpolation": _ALLOWED_INTERPOLATIONS,
        "extrapolation": _ALLOWED_EXTRAPOLATIONS,
    }

    def __init__(
        self,
        breakpoints_axes: list[npt.ArrayLike] | None = None,
        table: npt.ArrayLike | None = None,
        interpolation: str = "linear",
        extrapolation: str = "clip",
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if interpolation not in self._ALLOWED_INTERPOLATIONS:
            raise BlockSpecError(
                f"LookupTableND: interpolation must be one of {self._ALLOWED_INTERPOLATIONS}, "
                f"got {interpolation!r}"
            )
        if extrapolation not in self._ALLOWED_EXTRAPOLATIONS:
            raise BlockSpecError(
                f"LookupTableND: extrapolation must be one of {self._ALLOWED_EXTRAPOLATIONS}, "
                f"got {extrapolation!r}"
            )

        # 既定: 2 軸ゼロ平面 (LookupTable2D 既定と等価、palette drop 時の自明な初期値)。
        if breakpoints_axes is None:
            breakpoints_axes = [[0.0, 1.0], [0.0, 1.0]]
        if table is None:
            table = [[0.0, 0.0], [0.0, 0.0]]

        if not isinstance(breakpoints_axes, list) or len(breakpoints_axes) < 2:
            got_len = len(breakpoints_axes) if isinstance(breakpoints_axes, list) else 0
            raise BlockSpecError(
                f"LookupTableND: breakpoints_axes must have at least 2 axes "
                f"(got {got_len}); use LookupTable1D for 1-D"
            )

        n_axes = len(breakpoints_axes)
        if n_axes > LOOKUP_ND_AXIS_WARNING_THRESHOLD:
            _logger.warning(
                "LookupTableND: %d axes exceeds the recommended threshold of %d. "
                "Construction is allowed but memory usage scales exponentially.",
                n_axes,
                LOOKUP_ND_AXIS_WARNING_THRESHOLD,
            )

        # 各軸 breakpoints の検証 (SPEC-0008 / 0017 と同パターン)
        bp_arrays: list[npt.NDArray[np.float64]] = []
        for axis_i, bp_raw in enumerate(breakpoints_axes):
            try:
                bp = np.asarray(bp_raw, dtype=float)
            except (TypeError, ValueError) as exc:
                raise BlockSpecError(
                    f"LookupTableND: breakpoints_axes[{axis_i}] must contain numeric values: {exc}"
                ) from exc
            if bp.ndim != 1:
                raise BlockSpecError(
                    f"LookupTableND: breakpoints_axes[{axis_i}] must be 1-D, got shape {bp.shape}"
                )
            if bp.size < 2:
                raise BlockSpecError(
                    f"LookupTableND: breakpoints_axes[{axis_i}] must have at "
                    f"least 2 elements, got len={bp.size}"
                )
            if not np.all(np.diff(bp) > 0):
                raise BlockSpecError(
                    f"LookupTableND: breakpoints_axes[{axis_i}] must be "
                    f"strictly increasing, got {bp.tolist()!r}"
                )
            bp_arrays.append(bp)

        try:
            tbl = np.asarray(table, dtype=float)
        except (TypeError, ValueError) as exc:
            raise BlockSpecError(
                f"LookupTableND: table must be a regular n-D array of numeric "
                f"values (got jagged shape or non-numeric): {exc}"
            ) from exc

        if tbl.ndim != n_axes:
            raise BlockSpecError(
                f"LookupTableND: table must be {n_axes}-D (matching "
                f"len(breakpoints_axes)), got ndim={tbl.ndim} shape={tbl.shape}"
            )
        expected_shape = tuple(int(bp.size) for bp in bp_arrays)
        if tbl.shape != expected_shape:
            raise BlockSpecError(
                f"LookupTableND: table.shape={tbl.shape} must equal "
                f"tuple(len(bp) for bp in breakpoints_axes)={expected_shape}"
            )

        super().__init__(id=id, name=name, n_inputs=n_axes, n_outputs=1)

        self._bp_arrays: list[npt.NDArray[np.float64]] = bp_arrays
        self._table: npt.NDArray[np.float64] = tbl
        self._n_axes: int = n_axes
        self.interpolation = interpolation
        self.extrapolation = extrapolation

        scipy_method = "linear" if interpolation == "linear" else "nearest"
        self._interp = RegularGridInterpolator(
            tuple(bp_arrays),
            tbl,
            method=scipy_method,
            bounds_error=False,
            fill_value=np.nan,
        )

        self._params = {
            "breakpoints_axes": [bp.tolist() for bp in bp_arrays],
            "table": tbl.tolist(),
            "interpolation": interpolation,
            "extrapolation": extrapolation,
        }

    def _flat_lookup(self, u_vals: npt.NDArray[np.float64]) -> float:
        """各軸独立に左下角 cell を特定し ``table[i0, i1, ..., i_{n-1}]`` を返す。

        SPEC-0017 の 2-D ``_flat_lookup`` を n 軸に一般化。``searchsorted(side="right")``
        + ``clip([0, n-2])`` を各軸で行い、最終 index タプルで table から取得。
        """
        idx: list[int] = []
        for axis_i in range(self._n_axes):
            bp = self._bp_arrays[axis_i]
            ii = int(
                np.clip(
                    np.searchsorted(bp, u_vals[axis_i], side="right") - 1,
                    0,
                    bp.size - 2,
                )
            )
            idx.append(ii)
        return float(self._table[tuple(idx)])

    def _linear_extrapolate(self, u_vals: npt.NDArray[np.float64]) -> float:
        """n 軸線形外挿を「2 段階 1-D 外挿の合成」の n 軸再帰拡張で計算 (ADR-0068 §C-1)。

        軸 0 から順に 1-D 線形補間/外挿で table を縮約: 軸 0 で u[0] を eval すると
        shape (n_1, n_2, ..., n_{n-1}) の strip → 軸 1 で u[1] を eval すると
        shape (n_2, ..., n_{n-1}) → ... → 最終的にスカラー。

        ``interp1d(axis=0, kind="linear", fill_value="extrapolate")`` を各軸で
        逐次適用 (= n 回構築・eval)。

        **設計上の注意 (ADR-0068 §C-1 の「補間/外挿の直交分離」)**:
        本メソッドは ``extrapolation == "linear"`` かつ 1 軸でも定義域外のとき
        呼ばれ、**全軸を線形で処理する** (定義域内の他軸も含めて)。これは
        ``interpolation`` 設定 (``"nearest"`` / ``"flat"`` でも) に依存せず常に
        線形で外挿する SPEC-0017 / SPEC-0018 共通方針 (= 内側補間と外側外挿の
        分離原則)。1-D / 2-D 版とも同じ判断。

        **性能上の注意**: 2-D 版 (``LookupTable2D``) は ``__init__`` で
        ``_row_extrap_1d`` を 1 つだけ事前構築し、col 軸の ``interp1d`` のみを
        外挿経路で構築する。n-D 版は軸数が動的なため全軸の ``interp1d`` を
        事前保持せず、毎外挿呼び出しで n 回構築する。外挿経路はホットパス外
        (clip / 定義域内なら通らない) のため許容するが、外挿が頻発するモデル
        では性能影響あり。
        """
        current = self._table
        for axis_i in range(self._n_axes):
            bp = self._bp_arrays[axis_i]
            # axis=0 で 1-D 線形外挿 (= 最初の残存軸を消費)
            interp_1d = interp1d(
                bp,
                current,
                axis=0,
                kind="linear",
                bounds_error=False,
                fill_value="extrapolate",
                assume_sorted=True,
            )
            current = np.asarray(interp_1d(float(u_vals[axis_i])))
        # current は 0-D scalar (np.ndarray) になっているはず
        return float(np.asarray(current).item())

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        u_arr = np.asarray(u, dtype=float).reshape(-1)
        if u_arr.size != self._n_axes:
            raise BlockEvalError(
                f"LookupTableND[{self.name}]: expected {self._n_axes} inputs, got {u_arr.size}",
                block_id=self.id,
            )

        # 各軸の定義域内判定 (nan は <=/>= で False になり外挿経路へ)
        in_domain_flags = [
            bool(self._bp_arrays[i][0] <= u_arr[i] <= self._bp_arrays[i][-1])
            for i in range(self._n_axes)
        ]
        all_in_domain = all(in_domain_flags)

        if not all_in_domain:
            if self.extrapolation == "error":
                bounds_repr = ", ".join(
                    f"axis[{i}] [{float(self._bp_arrays[i][0])}, {float(self._bp_arrays[i][-1])}]"
                    for i in range(self._n_axes)
                )
                raise BlockEvalError(
                    f"LookupTableND[{self.name}]: input {u_arr.tolist()} is "
                    f"outside {bounds_repr} and extrapolation='error'",
                    block_id=self.id,
                )
            if self.extrapolation == "linear":
                # nan 含むときは結果も nan (interp1d が nan 伝播)
                y = self._linear_extrapolate(u_arr)
                return np.array([y])
            # extrapolation == "clip": 各軸独立に端点飽和
            u_arr = np.array(
                [
                    float(
                        np.clip(
                            u_arr[i],
                            self._bp_arrays[i][0],
                            self._bp_arrays[i][-1],
                        )
                    )
                    for i in range(self._n_axes)
                ]
            )

        if self.interpolation == "flat":
            if bool(np.any(np.isnan(u_arr))):
                return np.array([float("nan")])
            y = self._flat_lookup(u_arr)
        else:
            # RegularGridInterpolator は shape (npts, ndim) を期待 → (1, n_axes)。
            y = float(self._interp(u_arr.reshape(1, -1)).item())
        return np.array([y])
