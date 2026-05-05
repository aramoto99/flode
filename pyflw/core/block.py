"""Block 基底クラス。

ADR-0002 (離散時間サポート) で `sample_time` 属性と `update` メソッドを追加。
ADR-0004 (ブロック ID 規則) で `id` 属性を正式名として導入し、`name` を後方互換 alias 化。
"""

from __future__ import annotations

import numpy as np

from ..exceptions import BlockSpecError
from .identifiers import validate_block_id


class Block:
    """全ブロックの基底クラス。

    Attributes:
        id: ブロック識別子。`None` の場合は ``Simulator.add`` で自動採番される。
        n_inputs: 入力ポート数。
        n_outputs: 出力ポート数。
        n_states: 状態次元数 (連続/離散とも n_states に集約)。
        direct_feedthrough: True なら入力 ``u`` が出力 ``y`` に直接影響する。
            False のブロック (Integrator, UnitDelay 等) が代数ループを切る。
        sample_time: ``None`` または ``0.0`` で連続、``> 0`` で離散周期 [s]、
            ``-1.0`` で上流から継承 (Simulator がビルド時に解決)。
        x0: 初期状態 (shape ``(n_states,)``)。
        input_sources: 各入力ポートの接続元 ``(Block, output_idx)``。``None`` は未接続。
    """

    def __init__(
        self,
        *,
        id: str | None = None,
        name: str | None = None,
        n_inputs: int = 1,
        n_outputs: int = 1,
        n_states: int = 0,
        direct_feedthrough: bool = True,
        sample_time: float | None = None,
    ) -> None:
        if id is not None and name is not None:
            raise BlockSpecError(
                "id and name cannot both be set; use id (name is a Phase 0 alias)"
            )
        resolved_id = id if id is not None else name
        if resolved_id is not None:
            validate_block_id(resolved_id)
        self._id: str | None = resolved_id

        if sample_time is not None:
            if not isinstance(sample_time, (int, float)):
                raise BlockSpecError(
                    f"sample_time must be a number or None, got {type(sample_time).__name__}"
                )
            st = float(sample_time)
            if st < 0.0 and st != -1.0:
                raise BlockSpecError(
                    f"sample_time={st} is invalid. Allowed: None, 0.0 (continuous), "
                    f">0 (discrete period), or -1.0 (inherited)."
                )
            sample_time = st

        self.n_inputs = n_inputs
        self.n_outputs = n_outputs
        self.n_states = n_states
        self.direct_feedthrough = direct_feedthrough
        self.sample_time: float | None = sample_time
        self.x0: np.ndarray = np.zeros(n_states)
        self.input_sources: list[tuple[Block, int] | None] = [None] * n_inputs

        self._resolved_sample_time: float | None = None
        self._step_ratio: int = 1

    @property
    def id(self) -> str | None:
        """ブロック識別子 (read-write)。

        Simulator に登録済みのブロックの ID を直接書き換えるのは未サポート。
        リネームは ``Simulator.rename(old, new)`` を使うこと。
        """
        return self._id

    @id.setter
    def id(self, value: str | None) -> None:
        if value is not None:
            validate_block_id(value)
        self._id = value

    @property
    def name(self) -> str | None:
        """Phase 0 後方互換 alias for ``id`` (read-only)。

        Phase 1 では deprecation 警告を出さない。Phase 2 リリース時に
        ``DeprecationWarning`` を発する判断を予定 (ADR-0004)。
        """
        return self._id

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        """ブロック出力 ``y(t, x, u)`` を計算する (必須実装)。

        Args:
            t: 現時刻。
            x: 現状態 (shape ``(n_states,)``)。状態を持たないブロックは空配列。
            u: 現入力 (shape ``(n_inputs,)``)。``direct_feedthrough=False`` のブロック
                では出力計算 1 パス目で ``u`` がゼロ埋めされる場合がある。

        Returns:
            出力ベクトル (shape ``(n_outputs,)``)。
        """
        raise NotImplementedError(f"{self.__class__.__name__}.output not implemented")

    def derivative(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        """連続状態の時間微分 ``x_dot(t, x, u)`` を返す。

        Default 実装は ``np.zeros(n_states)`` を返す。連続状態を持つブロックは
        オーバーライドする。``sample_time > 0`` の離散ブロックでは呼ばれない。
        """
        return np.zeros(self.n_states)

    def update(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        """離散ブロックの状態更新 ``x_next = update(t, x, u)`` を返す。

        Args:
            t: 現サンプル時刻。
            x: 現状態 (shape ``(n_states,)``)。
            u: 現入力 (shape ``(n_inputs,)``)。

        Returns:
            次サンプル時刻の状態 (shape ``(n_states,)``)。

        Note:
            Default 実装は ``x`` をそのまま返す (組合せ論理のみの離散ブロック用)。
            実装側は **新しい ndarray を返す** こと。in-place 更新すると Simulator の
            double buffering が破綻する。
        """
        return x

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self._id!r}>"
