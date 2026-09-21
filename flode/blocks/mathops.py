from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import numpy.typing as npt

from ..core.block import Block
from ..exceptions import BlockSpecError
from ._elementwise import ElementwiseMixin

#: ``Gain.multiplication`` の語彙 (ADR-0079 §(3))。
GAIN_MULTIPLICATION_MODES: tuple[str, ...] = ("elementwise", "matrix-Ku", "matrix-uK")

#: ``Gain.k`` に許す最大 rank (行列まで)。
_GAIN_MAX_RANK = 2


def _broadcast_inputs(u: Sequence[npt.NDArray[Any]]) -> tuple[npt.NDArray[Any], ...]:
    """合流規則 (完全一致 + rank-0 拡張) を満たす入力群を共通 shape に揃える。"""
    if len(u) <= 1:
        return tuple(np.asarray(ui) for ui in u)
    return tuple(np.broadcast_arrays(*[np.asarray(ui) for ui in u]))


class Gain(ElementwiseMixin, Block):
    """ゲイン ``y = k * u`` (要素ごと) または行列ゲイン ``y = K @ u`` / ``y = u @ K``。

    ADR-0079 §(3): ``k`` はスカラ / 1-D / 2-D を受ける。既定の
    ``multiplication="elementwise"`` ではスカラ ``k`` が入力全要素に、配列 ``k`` は
    入力と同 shape の要素ごとに掛かる。``"matrix-Ku"`` は ``k @ u``、``"matrix-uK"``
    は ``u @ k`` (numpy ``matmul`` の規則、次元不整合は build 時に検出)。

    Args:
        k: ゲイン係数 (スカラ、または list / ndarray で 1-D / 2-D)。
        multiplication: ``"elementwise"`` (既定) / ``"matrix-Ku"`` / ``"matrix-uK"``。

    Raises:
        BlockSpecError: ``k`` の rank が 2 を超える / 非数値、``multiplication`` が語彙外。
    """

    _param_enums = {"multiplication": GAIN_MULTIPLICATION_MODES}

    def __init__(
        self,
        k: float | Sequence[Any] | npt.NDArray[Any] = 1.0,
        multiplication: str = "elementwise",
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if multiplication not in GAIN_MULTIPLICATION_MODES:
            raise BlockSpecError(
                f"Gain: multiplication must be one of {GAIN_MULTIPLICATION_MODES}, "
                f"got {multiplication!r}"
            )
        super().__init__(id=id, name=name, n_inputs=1, n_outputs=1)
        self.multiplication = multiplication
        self.k: float | npt.NDArray[Any]
        if np.ndim(k) == 0:
            # スカラ (従来どおり float 化。配列でないので信号面の起点にならない)
            self.k = float(k)  # type: ignore[arg-type]
        else:
            try:
                k_arr = np.asarray(k, dtype=float)
            except (TypeError, ValueError) as e:
                raise BlockSpecError(
                    f"Gain: k must be numeric (scalar, 1-D or 2-D), got {k!r}"
                ) from e
            if k_arr.ndim > _GAIN_MAX_RANK:
                raise BlockSpecError(
                    f"Gain: k must be a scalar, 1-D or 2-D array, got rank {k_arr.ndim}"
                )
            self.k = k_arr
        if multiplication != "elementwise" and np.ndim(self.k) == 0:
            raise BlockSpecError(
                f"Gain: multiplication={multiplication!r} requires a 1-D or 2-D k, got a scalar"
            )
        # AC-9: 既定 (elementwise) では multiplication を書き出さない = 既存 JSON 不変
        self._params = {"k": self.k}
        if multiplication != "elementwise":
            self._params["multiplication"] = multiplication

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.array([self.k * u[0]])

    def _kernel(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        if self.multiplication == "elementwise":
            # スカラ k × rank-0 u は output と同じ式 (k * u[0]) = bit-identical
            return (np.asarray(self.k * u[0]),)
        if np.ndim(u[0]) == 0:
            # 信号面解決器が build 時に拒否するので通常は到達しない。解決器を
            # 通らない直接呼び出しでも numpy の ValueError を漏らさない (fail-closed)。
            raise BlockSpecError(
                f"Gain {self.id!r}: multiplication={self.multiplication!r} needs a "
                "vector / matrix input, got a scalar (connect a Mux output).",
                block_id=self.id,
            )
        if self.multiplication == "matrix-Ku":
            return (np.asarray(np.matmul(self.k, u[0])),)
        return (np.asarray(np.matmul(u[0], self.k)),)


class Sum(ElementwiseMixin, Block):
    """符号付き加算 ``y = Σ sign_i * u_i``。

    入力ポート数は ``len(signs)``。``signs`` の各文字は ``"+"`` または ``"-"``。

    Note:
        本クラスは ``signs`` の妥当性検証 (空文字 / 不正文字) を意図的に行わない
        (v0.1.0 以降の後方互換、ADR-0038 Public API 凍結対象)。Strict な validation
        が必要な場合は同等機能の ``Add`` (v0.35.0、矩形版) を使う。

    Args:
        signs: 符号を表す文字列。例: ``"++-"`` で ``y = u[0] + u[1] - u[2]``。
    """

    def __init__(
        self,
        signs: str = "++",
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        super().__init__(id=id, name=name, n_inputs=len(signs), n_outputs=1)
        self.signs = np.array([1.0 if s == "+" else -1.0 for s in signs])
        # SM-D Stage 1 (SPEC-0028 §3.6): 整数/bool 入力用の int64 符号。
        # int64 で累積し、宣言 dtype への wrap は _step_vector の cast_value に
        # 委ねる (mod 2^n は準同型なので結果は native 累積と一致。int8 符号だと
        # bool 入力時に result_type が int8 になり極端な多入力で壊れる —
        # security NIT-3 2026-09-08)。float 経路 (上の self.signs) には触れない。
        self._signs_int = np.array([1 if s == "+" else -1 for s in signs], dtype=np.int64)
        self._params = {"signs": signs}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        if u.dtype.kind in "bui":
            # SM-D Stage 1 (SPEC-0028 §3.6): 整数/bool は整数演算で累積する。
            # 予測 dtype への wrap は _step_vector の cast_value が行う
            # (uint8 は int16 で累積 → mod 256 wrap で準同型的に正しい)。
            return np.array([np.dot(self._signs_int, u)])
        return np.array([float(np.dot(self.signs, u))])

    def _kernel(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        return (_signed_sum(self.signs, self._signs_int, u),)


def _signed_sum(
    signs: npt.NDArray[Any],
    signs_int: npt.NDArray[Any],
    u: tuple[npt.NDArray[Any], ...],
) -> npt.NDArray[Any]:
    """``Σ sign_i * u_i`` のテンソル版 (Sum / Add 共通、ADR-0079 §(3))。

    入力を共通 shape に揃えて ``(n, *shape)`` に積み、先頭軸で ``np.dot`` を取る。
    全入力が rank-0 のとき ``stacked`` は 1-D なので ``np.dot(signs, stacked)`` は
    SM-A ``output`` の式と同一 (= bit-identical、AC-11)。
    """
    stacked = np.stack(_broadcast_inputs(u))
    if stacked.dtype.kind in "bui":
        return np.asarray(np.dot(signs_int, stacked))
    if stacked.ndim == 1:
        return np.asarray(float(np.dot(signs, stacked)))
    return np.asarray(np.dot(signs, stacked))


class Add(ElementwiseMixin, Block):
    """符号付き加算 (矩形版) ``y = Σ sign_i * u_i`` (v0.35.0)。

    ``Sum`` (= 円形 ○) と機能同等だが、形状が **矩形 □** で描画される。
    リファレンスツールの Add ブロック (vs Sum) と同じ使い分け: 図面上で「加算ノード」を
    丸 / 角どちらで表現したいかの好みで選ぶ。

    入力ポート数は ``len(signs)``。``signs`` の各文字は ``"+"`` または ``"-"``。

    Note:
        v0.35.0 では SM-A (スカラー port) のみ対応。SM-B (ベクトル / テンソル
        port) 対応は後続 release で予定。

    Args:
        signs: 符号文字列。例: ``"++-"`` で ``y = u[0] + u[1] - u[2]``。
            空文字または ``"+"``/``"-"`` 以外を含むと ``BlockSpecError``。

    Raises:
        BlockSpecError: signs が空または不正文字を含む。
    """

    def __init__(
        self,
        signs: str = "++",
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if not signs:
            raise BlockSpecError("Add: signs must be non-empty")
        if any(c not in "+-" for c in signs):
            raise BlockSpecError(f"Add: signs must contain only '+'/'-', got {signs!r}")
        super().__init__(id=id, name=name, n_inputs=len(signs), n_outputs=1)
        self.signs = np.array([1.0 if s == "+" else -1.0 for s in signs])
        # SM-D Stage 1 (SPEC-0028 §3.6): 整数/bool 入力用の int64 符号。
        # int64 で累積し、宣言 dtype への wrap は _step_vector の cast_value に
        # 委ねる (mod 2^n は準同型なので結果は native 累積と一致。int8 符号だと
        # bool 入力時に result_type が int8 になり極端な多入力で壊れる —
        # security NIT-3 2026-09-08)。float 経路 (上の self.signs) には触れない。
        self._signs_int = np.array([1 if s == "+" else -1 for s in signs], dtype=np.int64)
        self._params = {"signs": signs}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        if u.dtype.kind in "bui":
            # SM-D Stage 1 (SPEC-0028 §3.6): 整数/bool は整数演算で累積する。
            # 予測 dtype への wrap は _step_vector の cast_value が行う
            # (uint8 は int16 で累積 → mod 256 wrap で準同型的に正しい)。
            return np.array([np.dot(self._signs_int, u)])
        return np.array([float(np.dot(self.signs, u))])

    def _kernel(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        return (_signed_sum(self.signs, self._signs_int, u),)


class Product(ElementwiseMixin, Block):
    """全入力の乗算 ``y = Π u_i``。

    Args:
        n_inputs: 入力ポート数 (>= 2)。
    """

    def __init__(
        self,
        n_inputs: int = 2,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        super().__init__(id=id, name=name, n_inputs=n_inputs, n_outputs=1)
        self._params = {"n_inputs": int(n_inputs)}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        if u.dtype.kind in "bui":
            # SM-D Stage 1: dtype=u.dtype 必須 — np.prod は既定で default int に
            # 昇格し wrap 位置が変わるため (SPEC-0028 §3.6)
            return np.array([np.prod(u, dtype=u.dtype)])
        return np.array([float(np.prod(u))])

    def _kernel(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        stacked = np.stack(_broadcast_inputs(u))
        if stacked.dtype.kind in "bui":
            return (np.asarray(np.prod(stacked, axis=0, dtype=stacked.dtype)),)
        return (np.asarray(np.prod(stacked, axis=0)),)


class Saturation(ElementwiseMixin, Block):
    """飽和 ``y = clip(u, lower, upper)``。

    Args:
        lower: 下限値。``upper`` より小さい必要がある。
        upper: 上限値。``lower`` より大きい必要がある。
    """

    def __init__(
        self,
        lower: float = -1.0,
        upper: float = 1.0,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if lower >= upper:
            raise BlockSpecError(f"Saturation: require lower < upper, got [{lower}, {upper}]")
        super().__init__(id=id, name=name, n_inputs=1, n_outputs=1)
        self.lower = float(lower)
        self.upper = float(upper)
        self._params = {"lower": self.lower, "upper": self.upper}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.array([float(np.clip(u[0], self.lower, self.upper))])

    def _kernel(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        return (np.asarray(np.clip(np.asarray(u[0], dtype=float), self.lower, self.upper)),)


class Abs(ElementwiseMixin, Block):
    """絶対値 ``y = |u|``。"""

    def __init__(
        self,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        super().__init__(id=id, name=name, n_inputs=1, n_outputs=1)
        self._params = {}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.array([abs(float(u[0]))])

    def _kernel(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        return (np.asarray(np.abs(np.asarray(u[0], dtype=float))),)


class Sign(ElementwiseMixin, Block):
    """符号関数 ``y = sign(u)`` (-1 / 0 / +1)。"""

    def __init__(
        self,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        super().__init__(id=id, name=name, n_inputs=1, n_outputs=1)
        self._params = {}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        v = float(u[0])
        return np.array([1.0 if v > 0.0 else (-1.0 if v < 0.0 else 0.0)])

    def _kernel(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        # output と同じ判定順 (nan は 0.0、np.sign の nan 伝播とは違う)
        v = np.asarray(u[0], dtype=float)
        return (np.asarray(np.where(v > 0.0, 1.0, np.where(v < 0.0, -1.0, 0.0))),)


class MinMax(ElementwiseMixin, Block):
    """複数入力の最小値または最大値を出力する。

    Args:
        operator: ``"min"`` または ``"max"``。
        n_inputs: 入力ポート数 (>= 1)。
    """

    _ALLOWED_OPS = ("min", "max")
    # ADR-0039 follow-up (v0.15.0): GUI ParameterPanel が enum select を出すヒント
    _param_enums = {"operator": _ALLOWED_OPS}

    def __init__(
        self,
        operator: str = "min",
        n_inputs: int = 2,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if operator not in self._ALLOWED_OPS:
            raise BlockSpecError(
                f"MinMax: operator must be one of {self._ALLOWED_OPS}, got {operator!r}"
            )
        if n_inputs < 1:
            raise BlockSpecError(f"MinMax: n_inputs must be >= 1, got {n_inputs}")
        super().__init__(id=id, name=name, n_inputs=n_inputs, n_outputs=1)
        self.operator = operator
        self._params = {"operator": operator, "n_inputs": int(n_inputs)}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        if u.dtype.kind in "bui":
            # SM-D Stage 1: int64 > 2^53 の大小比較が float 経由で壊れるため
            # 整数のまま比較する (SPEC-0028 §3.6)
            v_int = np.min(u) if self.operator == "min" else np.max(u)
            return np.array([v_int])
        v = float(np.min(u)) if self.operator == "min" else float(np.max(u))
        return np.array([v])

    def _kernel(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        stacked = np.stack(_broadcast_inputs(u))
        reduced = np.min(stacked, axis=0) if self.operator == "min" else np.max(stacked, axis=0)
        return (np.asarray(reduced),)


class Divide(ElementwiseMixin, Block):
    """乗除を ``signs`` 文字列で記述する。``"*"`` は乗算、``"/"`` は除算。

    例: ``signs="*/"`` → ``y = u[0] / u[1]``、
    ``signs="**/"`` → ``y = (u[0] * u[1]) / u[2]``。
    最初の文字が ``"/"`` のとき (``signs="/"`` 等) は ``y = 1.0 / u[0]`` (逆数)
    として扱う。

    入力ポート数は ``len(signs)``。除数 0 は ``np.inf`` / ``np.nan`` になり得るが
    エラーにはしない (ユーザー側で Saturation 等を併用する想定)。

    Args:
        signs: 演算子列。``"*"`` (乗算) または ``"/"`` (除算) のみ。空文字は不可。
    """

    def __init__(
        self,
        signs: str = "*/",
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if not signs:
            raise BlockSpecError("Divide: signs must be non-empty")
        for s in signs:
            if s not in ("*", "/"):
                raise BlockSpecError(f"Divide: signs must contain only '*' or '/', got {signs!r}")
        super().__init__(id=id, name=name, n_inputs=len(signs), n_outputs=1)
        self.signs = signs
        self._params = {"signs": signs}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        # 先頭が "/" のときは "1 / u[0]" (= 逆数) を起点として後続の乗除を続ける。
        # bug-fix 2026-09-13: Python の float 演算は 0 除算で ZeroDivisionError を
        # 投げ run 全体が落ちていた。docstring / ADR-0053 §論点 6 (定義域外は
        # nan / inf 伝播) どおり numpy の float64 演算で計算し、警告は抑制する。
        with np.errstate(divide="ignore", invalid="ignore"):
            result = (
                np.float64(u[0]) if self.signs[0] == "*" else np.float64(1.0) / np.float64(u[0])
            )
            for s, val in zip(self.signs[1:], u[1:], strict=True):
                if s == "*":
                    result = result * np.float64(val)
                else:
                    result = result / np.float64(val)
        return np.array([float(result)])

    def _kernel(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        # output と同じ演算順 (先頭が "/" なら 1/u[0] 起点) を要素ごとに適用する
        arrays = [np.asarray(ui, dtype=np.float64) for ui in u]
        with np.errstate(divide="ignore", invalid="ignore"):
            result = arrays[0] if self.signs[0] == "*" else np.float64(1.0) / arrays[0]
            for s, val in zip(self.signs[1:], arrays[1:], strict=True):
                result = result * val if s == "*" else result / val
        return (np.asarray(result, dtype=np.float64),)


# ---------------------------------------------------------------------------
# Phase 2 送りブロック群 第 1 弾 (SPEC-0002 / ADR-0053、v0.36.0)
# ---------------------------------------------------------------------------


class MathFunction(ElementwiseMixin, Block):
    """汎用数学関数 ``y = f(u)``。``function`` で関数を選択する。

    SPEC-0002 / ADR-0053 で確定した 9 関数を提供する。``pow`` / ``mod`` / ``rem``
    の 3 つのみ 2 入力 (``__init__`` で ``n_inputs=2`` を強制)、それ以外は単項。
    定義域外 (``log(負)`` / ``sqrt(負)`` / ``reciprocal(0)``) は ``nan`` / ``inf``
    を伝播する (既存 ``Divide`` の 0 除算と同じ寛容方針、ADR-0053 §論点 6)。

    Args:
        function: ``"exp"`` / ``"log"`` / ``"log10"`` / ``"sqrt"`` / ``"square"``
            / ``"reciprocal"`` (= 単項、``n_inputs=1``)、または ``"pow"`` /
            ``"mod"`` / ``"rem"`` (= 2 入力、``n_inputs=2``)。

    Raises:
        BlockSpecError: ``function`` が enum 値外。
    """

    _ALLOWED_FUNCTIONS: tuple[str, ...] = (
        "exp",
        "log",
        "log10",
        "sqrt",
        "square",
        "reciprocal",
        "pow",
        "mod",
        "rem",
    )
    _BINARY_FUNCTIONS: tuple[str, ...] = ("pow", "mod", "rem")
    # ADR-0019 / ADR-0039 follow-up: GUI ParameterPanel が enum select を出すヒント
    _param_enums = {"function": _ALLOWED_FUNCTIONS}

    def __init__(
        self,
        function: str = "exp",
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if function not in self._ALLOWED_FUNCTIONS:
            raise BlockSpecError(
                f"MathFunction: function must be one of {self._ALLOWED_FUNCTIONS}, got {function!r}"
            )
        n_inputs = 2 if function in self._BINARY_FUNCTIONS else 1
        super().__init__(id=id, name=name, n_inputs=n_inputs, n_outputs=1)
        self.function = function
        self._params = {"function": function}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        f = self.function
        if f == "exp":
            r = float(np.exp(float(u[0])))
        elif f == "log":
            r = float(np.log(float(u[0])))
        elif f == "log10":
            r = float(np.log10(float(u[0])))
        elif f == "sqrt":
            r = float(np.sqrt(float(u[0])))
        elif f == "square":
            r = float(np.square(float(u[0])))
        elif f == "reciprocal":
            # np.reciprocal は int 入力で 1 / 2 = 0 になる罠を回避するため float 強制。
            # Python の 1.0 / 0.0 は ZeroDivisionError を投げるため、SPEC-0002 §エッジ
            # ケース表「u=0 で inf を伝播」を満たすには numpy 演算を経由する必要がある
            # (np.float64 vs np.float64 の除算は inf を返す)。ADR-0053 §論点 6 で定義
            # 域外を nan / inf で伝播統一する方針と整合。
            r = float(np.divide(1.0, float(u[0])))
        elif f == "pow":
            r = float(np.power(float(u[0]), float(u[1])))
        elif f == "mod":
            # 数学的 mod、符号は除数に従う。
            r = float(np.mod(float(u[0]), float(u[1])))
        else:  # "rem"
            # C 流 rem、符号は被除数に従う。
            r = float(np.fmod(float(u[0]), float(u[1])))
        return np.array([r])

    def _kernel(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        f = self.function
        a = np.asarray(u[0], dtype=float)
        if f == "exp":
            r = np.exp(a)
        elif f == "log":
            r = np.log(a)
        elif f == "log10":
            r = np.log10(a)
        elif f == "sqrt":
            r = np.sqrt(a)
        elif f == "square":
            r = np.square(a)
        elif f == "reciprocal":
            r = np.divide(1.0, a)
        else:
            b = np.asarray(u[1], dtype=float)
            if f == "pow":
                r = np.power(a, b)
            elif f == "mod":
                r = np.mod(a, b)
            else:  # "rem"
                r = np.fmod(a, b)
        return (np.asarray(r, dtype=float),)


class TrigFunction(ElementwiseMixin, Block):
    """三角・双曲線関数 ``y = f(u)``。``function`` で関数を選択する (radian 固定)。

    SPEC-0002 / ADR-0053 で確定した 10 関数を提供する。``atan2`` のみ 2 入力
    (第 1 入力 = y、第 2 入力 = x、数学慣習 ``atan2(y, x)``)、それ以外は単項。
    定義域外 (``asin``/``acos`` の |u| > 1 等) は ``nan`` を伝播する。

    Args:
        function: ``"sin"`` / ``"cos"`` / ``"tan"`` / ``"asin"`` / ``"acos"`` /
            ``"atan"`` / ``"sinh"`` / ``"cosh"`` / ``"tanh"`` (= 単項、
            ``n_inputs=1``)、または ``"atan2"`` (= 2 入力、``n_inputs=2``)。

    Raises:
        BlockSpecError: ``function`` が enum 値外。
    """

    _ALLOWED_FUNCTIONS: tuple[str, ...] = (
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "sinh",
        "cosh",
        "tanh",
        "atan2",
    )
    _BINARY_FUNCTIONS: tuple[str, ...] = ("atan2",)
    _param_enums = {"function": _ALLOWED_FUNCTIONS}

    def __init__(
        self,
        function: str = "sin",
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if function not in self._ALLOWED_FUNCTIONS:
            raise BlockSpecError(
                f"TrigFunction: function must be one of {self._ALLOWED_FUNCTIONS}, got {function!r}"
            )
        n_inputs = 2 if function in self._BINARY_FUNCTIONS else 1
        super().__init__(id=id, name=name, n_inputs=n_inputs, n_outputs=1)
        self.function = function
        self._params = {"function": function}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        f = self.function
        if f == "sin":
            r = float(np.sin(float(u[0])))
        elif f == "cos":
            r = float(np.cos(float(u[0])))
        elif f == "tan":
            r = float(np.tan(float(u[0])))
        elif f == "asin":
            r = float(np.arcsin(float(u[0])))
        elif f == "acos":
            r = float(np.arccos(float(u[0])))
        elif f == "atan":
            r = float(np.arctan(float(u[0])))
        elif f == "sinh":
            r = float(np.sinh(float(u[0])))
        elif f == "cosh":
            r = float(np.cosh(float(u[0])))
        elif f == "tanh":
            r = float(np.tanh(float(u[0])))
        else:  # "atan2"
            # 第 1 入力 = y、第 2 入力 = x (数学慣習 atan2(y, x))。
            r = float(np.arctan2(float(u[0]), float(u[1])))
        return np.array([r])

    _UNARY_UFUNCS: dict[str, Callable[[npt.NDArray[Any]], npt.NDArray[Any]]] = {
        "sin": np.sin,
        "cos": np.cos,
        "tan": np.tan,
        "asin": np.arcsin,
        "acos": np.arccos,
        "atan": np.arctan,
        "sinh": np.sinh,
        "cosh": np.cosh,
        "tanh": np.tanh,
    }

    def _kernel(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        a = np.asarray(u[0], dtype=float)
        if self.function == "atan2":
            return (np.asarray(np.arctan2(a, np.asarray(u[1], dtype=float)), dtype=float),)
        return (np.asarray(self._UNARY_UFUNCS[self.function](a), dtype=float),)


class DeadZone(ElementwiseMixin, Block):
    """不感帯 ``y = 0 (lower <= u <= upper)、u - lower (u < lower)、u - upper (u > upper)``。

    端点 ``u == lower`` / ``u == upper`` では出力 ``0.0`` (strict 不等号、リファレンス
    ツール互換)。``lower == upper`` は許可 (= 退化単一点 dead zone、実質 ``y = u - lower``
    の連続関数、ADR-0053 §論点 5)。

    Args:
        lower: 不感帯の下限。``upper`` より大きいとエラー。
        upper: 不感帯の上限。``lower`` より小さいとエラー。

    Raises:
        BlockSpecError: ``lower > upper``。
    """

    def __init__(
        self,
        lower: float = -0.5,
        upper: float = 0.5,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if lower > upper:
            raise BlockSpecError(f"DeadZone: lower ({lower}) must be <= upper ({upper})")
        super().__init__(id=id, name=name, n_inputs=1, n_outputs=1)
        self.lower = float(lower)
        self.upper = float(upper)
        self._params = {"lower": self.lower, "upper": self.upper}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        v = float(u[0])
        if v < self.lower:
            r = v - self.lower
        elif v > self.upper:
            r = v - self.upper
        else:
            r = 0.0
        return np.array([r])

    def _kernel(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        v = np.asarray(u[0], dtype=float)
        r = np.where(v < self.lower, v - self.lower, np.where(v > self.upper, v - self.upper, 0.0))
        return (np.asarray(r, dtype=float),)


# ---------------------------------------------------------------------------
# 比較系 dispatch helper (CompareToConstant / CompareToZero 共通)
# ---------------------------------------------------------------------------


_COMPARE_OPS: dict[str, Callable[[float, float], bool]] = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
}


def _build_compare_fn(op: str) -> Callable[[float, float], bool]:
    """比較演算子文字列を ``Callable[[float, float], bool]`` に dispatch する。

    Args:
        op: ``"=="`` / ``"!="`` / ``"<"`` / ``"<="`` / ``">"`` / ``">="`` のいずれか。

    Returns:
        2 引数を取り bool を返す関数。

    Raises:
        BlockSpecError: ``op`` が ``_COMPARE_OPS`` に未登録。
    """
    if op not in _COMPARE_OPS:
        raise BlockSpecError(f"Compare op must be one of {tuple(_COMPARE_OPS.keys())}, got {op!r}")
    return _COMPARE_OPS[op]


class CompareToConstant(ElementwiseMixin, Block):
    """入力を定数と比較 ``y = (u op const) ? 1.0 : 0.0``。

    出力型は ``0.0`` / ``1.0`` の float (既存 ``RelationalOperator`` 踏襲、
    Boolean dtype 一括改修は ADR-0053 §論点 3 で別 ADR 送り)。

    ``nan`` を含む比較は numpy 仕様に従い、``!=`` のみ ``True`` (= ``1.0``)、
    他は全て ``False`` (= ``0.0``)。

    Args:
        op: ``"=="`` / ``"!="`` / ``"<"`` / ``"<="`` / ``">"`` / ``">="``。
        const: 比較対象の定数。

    Raises:
        BlockSpecError: ``op`` が enum 値外。
    """

    _ALLOWED_OPS_COMPARE: tuple[str, ...] = ("==", "!=", "<", "<=", ">", ">=")
    _param_enums = {"op": _ALLOWED_OPS_COMPARE}

    def __init__(
        self,
        op: str = "==",
        const: float = 0.0,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if op not in self._ALLOWED_OPS_COMPARE:
            raise BlockSpecError(
                f"CompareToConstant: op must be one of {self._ALLOWED_OPS_COMPARE}, got {op!r}"
            )
        super().__init__(id=id, name=name, n_inputs=1, n_outputs=1)
        self.op = op
        self.const = float(const)
        self._compare = _build_compare_fn(op)
        self._params = {"op": op, "const": self.const}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.array([1.0 if self._compare(float(u[0]), self.const) else 0.0])

    def _kernel(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        # _COMPARE_OPS の lambda は ndarray にもそのまま適用できる (要素ごと比較)
        mask = self._compare(np.asarray(u[0], dtype=float), self.const)  # type: ignore[arg-type]
        return (np.asarray(np.where(mask, 1.0, 0.0), dtype=float),)


class CompareToZero(ElementwiseMixin, Block):
    """入力をゼロと比較 ``y = (u op 0) ? 1.0 : 0.0``。

    ``CompareToConstant(const=0)`` の固定特殊化を別クラスで提供 (ADR-0053
    §論点 4)。リファレンスツールでも別ブロックとして UI に並んでおり、ゼロ越え trigger
    idiom が 1 ブロックで表現できる。

    Args:
        op: ``"=="`` / ``"!="`` / ``"<"`` / ``"<="`` / ``">"`` / ``">="``。

    Raises:
        BlockSpecError: ``op`` が enum 値外。
    """

    _ALLOWED_OPS_COMPARE: tuple[str, ...] = CompareToConstant._ALLOWED_OPS_COMPARE
    _param_enums = {"op": _ALLOWED_OPS_COMPARE}

    def __init__(
        self,
        op: str = "==",
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if op not in self._ALLOWED_OPS_COMPARE:
            raise BlockSpecError(
                f"CompareToZero: op must be one of {self._ALLOWED_OPS_COMPARE}, got {op!r}"
            )
        super().__init__(id=id, name=name, n_inputs=1, n_outputs=1)
        self.op = op
        self._compare = _build_compare_fn(op)
        self._params = {"op": op}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.array([1.0 if self._compare(float(u[0]), 0.0) else 0.0])

    def _kernel(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        mask = self._compare(np.asarray(u[0], dtype=float), 0.0)  # type: ignore[arg-type]
        return (np.asarray(np.where(mask, 1.0, 0.0), dtype=float),)


# ---------------------------------------------------------------------------
# ADR-0079 Stage 3 (SPEC-0031 #19): 要素縮約と最小限の線形代数
# ---------------------------------------------------------------------------

#: ``Reduce.operation`` の語彙 → numpy の縮約関数。
REDUCE_OPERATIONS: tuple[str, ...] = ("sum", "product", "min", "max", "mean")
_REDUCE_FUNCS: dict[str, Callable[[npt.NDArray[Any]], Any]] = {
    "sum": np.sum,
    "product": np.prod,
    "min": np.min,
    "max": np.max,
    "mean": np.mean,
}


class Reduce(Block):
    """入力信号の全要素を 1 つのスカラに縮約する ``y = op(u)`` (SPEC-0031 F-5.3)。

    ``Sum`` / ``Add`` は **ポート間** の和 (ベクトルでは要素ごと) であり、1 本の
    ベクトルの要素総和には使えない (Q6)。本ブロックが要素方向の縮約を担う。
    ``operation`` は ``"sum"`` (既定) / ``"product"`` / ``"min"`` / ``"max"`` /
    ``"mean"``。任意 shape を受け、出力は常にスカラ ``()``。スカラ入力は恒等。

    Args:
        operation: 縮約の種類 (``REDUCE_OPERATIONS``)。

    Raises:
        BlockSpecError: ``operation`` が語彙外。
    """

    _param_enums = {"operation": REDUCE_OPERATIONS}
    # SM-A (スカラ = 恒等) と SM-T (任意 shape → ()) の両 API を持つ内部例外
    _skip_dual_api_check = True

    def __init__(
        self,
        operation: str = "sum",
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if operation not in REDUCE_OPERATIONS:
            raise BlockSpecError(
                f"Reduce: operation must be one of {REDUCE_OPERATIONS}, got {operation!r}"
            )
        super().__init__(id=id, name=name, n_inputs=1, n_outputs=1)
        self.operation = operation
        self._reduce = _REDUCE_FUNCS[operation]
        self._params = {"operation": operation}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        # スカラ入力の縮約はどの operation でも恒等
        return np.array([float(u[0])])

    def output_v(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        return (np.asarray(self._reduce(np.asarray(u[0], dtype=float)), dtype=float),)


class DotProduct(Block):
    """2 入力の全要素内積 ``y = Σ u0[i] * u1[i]`` (SPEC-0031 #19、線形代数)。

    入力 2 本は合流規則 (完全一致 + スカラ拡張) を満たす同 shape で、出力はスカラ
    ``()``。2 次形式 ``xᵀ P x`` は ``Gain(P, "matrix-Ku")`` → ``DotProduct`` で書ける。
    スカラ同士は積。
    """

    _skip_dual_api_check = True

    def __init__(self, *, id: str | None = None, name: str | None = None):
        super().__init__(id=id, name=name, n_inputs=2, n_outputs=1)
        self._params = {}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.array([float(u[0]) * float(u[1])])

    def output_v(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        a, b = _broadcast_inputs(u)
        return (np.asarray(np.dot(np.ravel(a), np.ravel(b)), dtype=float),)


class MatrixMultiply(Block):
    """行列積 ``y = u0 @ u1`` (SPEC-0031 #19、線形代数)。

    shape は numpy ``matmul`` の規則 (rank 1 / 2、内側次元一致) で build 時に
    解決器が検査する (``shape.mismatch``)。両入力がスカラなら積、片方だけスカラは
    build エラー (信号の行列積に暗黙のスカラ拡張は持ち込まない)。信号同士の積が
    要る場面 (時変ゲイン、``K(t) x``) 向け。定数行列との積は ``Gain`` の行列モード。
    """

    _skip_dual_api_check = True

    def __init__(self, *, id: str | None = None, name: str | None = None):
        super().__init__(id=id, name=name, n_inputs=2, n_outputs=1)
        self._params = {}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.array([float(u[0]) * float(u[1])])

    def output_v(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        a = np.asarray(u[0], dtype=float)
        b = np.asarray(u[1], dtype=float)
        if a.ndim == 0 and b.ndim == 0:
            return (np.asarray(a * b, dtype=float),)
        if a.ndim == 0 or b.ndim == 0:
            # 解決器が build 時に拒否するので通常は到達しない (fail-closed)
            raise BlockSpecError(
                f"MatrixMultiply {self.id!r}: both inputs must be vectors / matrices "
                f"(got shapes {a.shape} and {b.shape}); use Gain for a scalar factor.",
                block_id=self.id,
            )
        return (np.asarray(np.matmul(a, b), dtype=float),)
