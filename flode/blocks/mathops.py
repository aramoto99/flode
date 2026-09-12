from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import numpy.typing as npt

from ..core.block import Block
from ..exceptions import BlockSpecError


class Gain(Block):
    """スカラーゲイン ``y = k * u``。

    Args:
        k: ゲイン係数。
    """

    def __init__(
        self,
        k: float = 1.0,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        super().__init__(id=id, name=name, n_inputs=1, n_outputs=1)
        self.k = float(k)
        self._params = {"k": self.k}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        return np.array([self.k * u[0]])


class Sum(Block):
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


class Add(Block):
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


class Product(Block):
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


class Saturation(Block):
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


class Abs(Block):
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


class Sign(Block):
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


class MinMax(Block):
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


class Divide(Block):
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
        result = float(u[0]) if self.signs[0] == "*" else 1.0 / float(u[0])
        for s, val in zip(self.signs[1:], u[1:], strict=True):
            if s == "*":
                result *= float(val)
            else:
                result /= float(val)
        return np.array([result])


# ---------------------------------------------------------------------------
# Phase 2 送りブロック群 第 1 弾 (SPEC-0002 / ADR-0053、v0.36.0)
# ---------------------------------------------------------------------------


class MathFunction(Block):
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


class TrigFunction(Block):
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


class DeadZone(Block):
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


class CompareToConstant(Block):
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


class CompareToZero(Block):
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
