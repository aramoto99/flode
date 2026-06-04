"""SPEC-0008 + SPEC-0017 / ADR-0059 (v5.1.0 / v5.6.0): ルックアップテーブルブロック群。

業界標準ブロック線図ツールの "Lookup Tables" カテゴリ。Wave 1 で 1-D
(:class:`LookupTable1D`)、Wave 3 第 1 弾で 2-D (:class:`LookupTable2D`) を追加。
n-D は SPEC-0018 で後続。

補間オブジェクトは ``__init__`` で 1 度だけ構築し、``output`` のホットパスでは
評価のみ行う (ADR-0064 §A-1)。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt
from scipy.interpolate import RegularGridInterpolator, interp1d

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

        ``Simulator.compile()`` (ADR-0037) 経路では ``RegularGridInterpolator``
        が XLA トレース不可なため fallback 対象 (1-D と同じ)。
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
                    f"x breakpoints_col [{float(self._bp_col[0])}, {float(self._bp_col[-1])}] "
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
