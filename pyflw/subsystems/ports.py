"""Subsystem 境界ブロック (Inport / Outport)。

ADR-0009 §(2)。``Subsystem`` 内部に置かれる専用ブロックで、外部からの入力を
``Inport.output`` から取り出し、内部の出力を ``Outport`` で集めて Subsystem の
外部出力に渡す。

これらは ``Subsystem`` の外で単独に使うとほぼ意味がない (常に 0 を返す pass-through
状態) ため、ユーザーは ``Subsystem.add(Inport(port_idx=...))`` の形で使う想定。
"""

from __future__ import annotations

import numpy as np

from ..core.block import Block
from ..exceptions import BlockSpecError


class Inport(Block):
    """Subsystem 内部から見た外部入力ポート (ADR-0009 §(2)、ADR-0018 で SM-B 拡張)。

    親 ``Subsystem.output(t, x, u)`` が呼ばれると、Subsystem ランタイムが各 Inport
    インスタンスの ``_external_value`` に対応する値を set する。``output`` はその
    値をそのまま 1 出力ポートに流す pass-through。

    SM-B (ADR-0017) 対応: ``port_shape`` 引数で出力 port の shape を宣言できる。
    default ``()`` (rank-0 scalar) で SM-A 互換、後方互換性あり。

    Args:
        port_idx: 親 Subsystem の入力ポート番号 (0-indexed)。
        port_shape: 出力 port の shape。default ``()`` (= SM-A scalar)。SM-B 用に
            ``(n,)`` 等を指定可能。親 ``Subsystem.port_shapes_in[port_idx]`` と
            一致させること (Subsystem._build で整合性 check、ADR-0018 §(5))。
    """

    # ADR-0018 §(5): フレームワーク内部の Inport は SM-A path (`output`) と
    # SM-B path (`output_v`) の両方を実装する必要があるため、ADR-0017 §(8) U3 の
    # dual API 禁止 check を skip する class 属性を立てる。
    _skip_dual_api_check = True
    # port_shapes は ``port_shape`` 引数から一意に決まるため JSON 二重出力を抑止
    _serialize_port_shapes = False

    def __init__(
        self,
        port_idx: int,
        *,
        id: str | None = None,
        name: str | None = None,
        port_shape: tuple[int, ...] = (),
    ) -> None:
        if not isinstance(port_idx, int) or port_idx < 0:
            raise BlockSpecError(f"Inport: port_idx must be a non-negative int, got {port_idx!r}")
        super().__init__(
            id=id,
            name=name,
            n_inputs=0,
            n_outputs=1,
            port_shapes_out=(tuple(port_shape),),
        )
        self.port_idx = port_idx
        self.port_shape: tuple[int, ...] = tuple(port_shape)
        # Subsystem ランタイムが各ステップで上書きする
        # SM-A (port_shape=()) では float、SM-B では ndarray を保持する。
        self._external_value: np.ndarray | float
        if self.port_shape == ():
            self._external_value = 0.0
        else:
            self._external_value = np.zeros(self.port_shape, dtype=float)
        self._params = {"port_idx": port_idx}
        # SM-B のとき JSON serialize に port_shape も含める
        if self.port_shape != ():
            self._params["port_shape"] = list(self.port_shape)

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        # SM-A path: rank-0 → 1D ndarray (n_outputs=1) で返す
        return np.array([float(self._external_value)])

    def output_v(
        self,
        t: float,
        x: np.ndarray,
        u: tuple[np.ndarray, ...],
    ) -> tuple[np.ndarray, ...]:
        # SM-B path: 任意 shape を tuple of 1 で返す
        return (np.asarray(self._external_value, dtype=float),)


class Outport(Block):
    """Subsystem 内部から見た外部出力ポート (ADR-0009 §(2)、ADR-0018 で SM-B 拡張)。

    内部ブロックの 1 出力を受け取り、親 Subsystem の ``y[port_idx]`` として外部に
    渡す。``Block.output`` は ``n_outputs=0`` のため空配列を返す。Subsystem
    ランタイムは ``_step_inner`` の終了後に ``self.input_sources`` を辿って
    Outport の入力ブロックの出力値を直接読み出す (= ``Outport`` 自体は値を保持
    しない pass-through 端点)。

    SM-B (ADR-0017) 対応: ``port_shape`` 引数で入力 port の shape を宣言できる。

    Args:
        port_idx: 親 Subsystem の出力ポート番号 (0-indexed)。
        port_shape: 入力 port の shape。default ``()`` (= SM-A scalar)。親
            ``Subsystem.port_shapes_out[port_idx]`` と一致させること
            (Subsystem._build で整合性 check)。
    """

    # ADR-0018 §(5): Inport と同じ理由で dual API 禁止 check を skip
    _skip_dual_api_check = True
    _serialize_port_shapes = False

    def __init__(
        self,
        port_idx: int,
        *,
        id: str | None = None,
        name: str | None = None,
        port_shape: tuple[int, ...] = (),
    ) -> None:
        if not isinstance(port_idx, int) or port_idx < 0:
            raise BlockSpecError(f"Outport: port_idx must be a non-negative int, got {port_idx!r}")
        super().__init__(
            id=id,
            name=name,
            n_inputs=1,
            n_outputs=0,
            port_shapes_in=(tuple(port_shape),),
        )
        self.port_idx = port_idx
        self.port_shape: tuple[int, ...] = tuple(port_shape)
        self._params = {"port_idx": port_idx}
        if self.port_shape != ():
            self._params["port_shape"] = list(self.port_shape)

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.zeros(0)

    def output_v(
        self,
        t: float,
        x: np.ndarray,
        u: tuple[np.ndarray, ...],
    ) -> tuple[np.ndarray, ...]:
        # n_outputs=0 のため empty tuple
        return ()
