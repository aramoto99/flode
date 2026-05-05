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
    """Subsystem 内部から見た外部入力ポート (ADR-0009 §(2))。

    親 ``Subsystem.output(t, x, u)`` が呼ばれると、Subsystem ランタイムが各 Inport
    インスタンスの ``_external_value`` に対応するスカラーを set する。
    ``output`` はその値をそのまま 1 出力ポートに流す pass-through。

    現状はスカラー (1 要素) のみ対応。ベクトル port は ADR-0010 SM-A で
    Phase 3 送りとなっているため、本ブロックの API も Phase 3 で見直し予定。

    Args:
        port_idx: 親 Subsystem の入力ポート番号 (0-indexed)。
    """

    def __init__(
        self,
        port_idx: int,
        *,
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        if not isinstance(port_idx, int) or port_idx < 0:
            raise BlockSpecError(f"Inport: port_idx must be a non-negative int, got {port_idx!r}")
        super().__init__(id=id, name=name, n_inputs=0, n_outputs=1)
        self.port_idx = port_idx
        # Subsystem ランタイムが各ステップで上書きする
        self._external_value: float = 0.0
        self._params = {"port_idx": port_idx}

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.array([self._external_value])


class Outport(Block):
    """Subsystem 内部から見た外部出力ポート (ADR-0009 §(2))。

    内部ブロックの 1 出力を受け取り、親 Subsystem の ``y[port_idx]`` として外部に
    渡す。``Block.output`` は ``n_outputs=0`` のため空配列を返す。Subsystem
    ランタイムは ``_step_inner`` の終了後に ``self.input_sources`` を辿って
    Outport の入力ブロックの出力値を直接読み出す (= ``Outport`` 自体は値を保持
    しない pass-through 端点)。

    Args:
        port_idx: 親 Subsystem の出力ポート番号 (0-indexed)。
    """

    def __init__(
        self,
        port_idx: int,
        *,
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        if not isinstance(port_idx, int) or port_idx < 0:
            raise BlockSpecError(f"Outport: port_idx must be a non-negative int, got {port_idx!r}")
        super().__init__(id=id, name=name, n_inputs=1, n_outputs=0)
        self.port_idx = port_idx
        self._params = {"port_idx": port_idx}

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.zeros(0)
