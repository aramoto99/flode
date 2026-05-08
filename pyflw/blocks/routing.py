"""信号ルーティング系ブロック。

- ``Switch``: 3 入力 1 出力スイッチ (Phase 1)
- ``Mux``: スカラー n 個 → 1D vector (n,) (ADR-0017 SM-B、ADR-0018、Phase 3 #4)
- ``Demux``: 1D vector (n,) → スカラー n 個 (同上)

``Mux`` / ``Demux`` は ADR-0017 で導入された SM-B (ベクトルポート) の最初の
ユーザー向けユースケース。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from ..core.block import Block
from ..exceptions import BlockSpecError


class Switch(Block):
    """3 入力スイッチ ``y = u[0] if control op threshold else u[2]``。

    入力ポート: ``[input_true, control, input_false]`` の 3 つ。
    ``control`` (= ``u[1]``) が閾値判定をパスすれば ``input_true``、
    そうでなければ ``input_false`` を出力する。

    Args:
        threshold: 比較しきい値。
        criterion: 比較演算子。``">="`` (default) / ``">"`` / ``"!="``。
            Simulink Switch の "u2 >= Threshold" / "u2 > Threshold" / "u2 ~= 0" 相当。

    Note:
        ``control`` が ``NaN`` のときは Python の比較規則 (NaN との比較は常に
        ``False``、ただし ``!=`` は ``True``) に従い ``input_false`` 側 (``"!="``
        は ``input_true`` 側) が選ばれる。NaN が伝播してきた場合の挙動として
        意図的にこの仕様のまま据え置く (デバッグ時の追跡しやすさは Phase 2 で
        検討)。
    """

    _ALLOWED_CRITERIA = (">=", ">", "!=")

    def __init__(
        self,
        threshold: float = 0.0,
        criterion: str = ">=",
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        if criterion not in self._ALLOWED_CRITERIA:
            raise BlockSpecError(
                f"Switch: criterion must be one of {self._ALLOWED_CRITERIA}, got {criterion!r}"
            )
        super().__init__(id=id, name=name, n_inputs=3, n_outputs=1)
        self.threshold = float(threshold)
        self.criterion = criterion
        self._params = {"threshold": self.threshold, "criterion": criterion}

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        control = float(u[1])
        if self.criterion == ">=":
            select_true = control >= self.threshold
        elif self.criterion == ">":
            select_true = control > self.threshold
        else:  # "!="
            select_true = control != self.threshold
        return np.array([float(u[0]) if select_true else float(u[2])])


class Mux(Block):
    """スカラー入力 ``n`` 個を 1D ベクトル (shape ``(n,)``) に集約する。

    ADR-0017 §(7) で API が例示され、ADR-0018 で正式化された SM-B (ベクトルポート)
    の最初のユーザー向けブロック。``direct_feedthrough=True``、状態なし。

    Internal port shape (ADR-0017):
        port_shapes_in  = ((), (), ..., ())  # n 個の rank-0 scalar
        port_shapes_out = ((n,),)            # 1 個の length-n vector

    Args:
        n: 入力ポート数 (= 出力 vector の長さ)。``>= 1`` 必須。

    Raises:
        BlockSpecError: ``n`` が int でない、または ``< 1``。
    """

    # port_shapes は ``n`` から一意に決まるため JSON に出さない (= load 時に
    # ``Mux(n=...)`` から再構築されるので二重持ちは矛盾の元)。ADR-0018 §(1)
    _serialize_port_shapes = False

    def __init__(
        self,
        n: int,
        *,
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        if not isinstance(n, int) or isinstance(n, bool):
            raise BlockSpecError(f"Mux: n must be an int, got {type(n).__name__}")
        if n < 1:
            raise BlockSpecError(f"Mux: n must be >= 1, got {n}")
        super().__init__(
            id=id,
            name=name,
            n_inputs=n,
            n_outputs=1,
            n_states=0,
            direct_feedthrough=True,
            port_shapes_in=tuple(() for _ in range(n)),
            port_shapes_out=((n,),),
        )
        self.n = n
        self._params = {"n": n}

    def output_v(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        # 各 u[i] は rank-0 ndarray。float 化して 1D に concat。
        vec = np.array([float(np.asarray(ui).item()) for ui in u], dtype=float)
        return (vec,)


class Demux(Block):
    """1D ベクトル入力 (shape ``(n,)``) を ``n`` 個のスカラーに分解する。

    ADR-0017 §(7) で API が例示され、ADR-0018 で正式化された Demux ブロック。
    ``Mux`` の逆操作。``direct_feedthrough=True``、状態なし。

    Internal port shape (ADR-0017):
        port_shapes_in  = ((n,),)              # 1 個の length-n vector
        port_shapes_out = ((), (), ..., ())    # n 個の rank-0 scalar

    Args:
        n: 入力 vector の長さ (= 出力ポート数)。``>= 1`` 必須。

    Raises:
        BlockSpecError: ``n`` が int でない、または ``< 1``。
    """

    # port_shapes は ``n`` から一意に決まるため JSON に出さない (Mux と同様)。
    _serialize_port_shapes = False

    def __init__(
        self,
        n: int,
        *,
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        if not isinstance(n, int) or isinstance(n, bool):
            raise BlockSpecError(f"Demux: n must be an int, got {type(n).__name__}")
        if n < 1:
            raise BlockSpecError(f"Demux: n must be >= 1, got {n}")
        super().__init__(
            id=id,
            name=name,
            n_inputs=1,
            n_outputs=n,
            n_states=0,
            direct_feedthrough=True,
            port_shapes_in=((n,),),
            port_shapes_out=tuple(() for _ in range(n)),
        )
        self.n = n
        self._params = {"n": n}

    def output_v(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        vec = np.asarray(u[0], dtype=float)
        # 各 element を rank-0 ndarray として返す
        return tuple(np.asarray(vec[i], dtype=float) for i in range(self.n))
