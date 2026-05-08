from __future__ import annotations

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
        self._params = {"signs": signs}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
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
