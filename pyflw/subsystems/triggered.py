"""Triggered Subsystem (ADR-0036)。

外部からのトリガー信号 (rising / falling / either edge) で内部ブロックを
発火するサブシステム。Simulink ``Triggered Subsystem`` 互換。

設計方針 (ADR-0036 §(2)(3)):

* :class:`Subsystem` を継承、trigger 入力は **入力末尾** (``input_sources[-1]``)
  固定。内部 ``Inport`` 数は ``n_inputs - 1`` (= データ入力のみ、trigger 入力は
  内部に流れない)
* trigger 入力は **離散信号必須** (= ``_resolved_sample_time != None``)、Simulator
  build 時に検証
* 内部ブロックは **trigger fire 時のみ** ``output`` / ``update`` が呼ばれる。
  fire しないステップでは内部状態凍結 + 前回出力をキャッシュ
* Phase 5b MVP (ADR-0036 §(4-C)) は **離散信号 trigger のみ** 対応、連続信号
  zero-crossing は将来 Phase で別 ADR
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import numpy.typing as npt

from ..core.block import Block
from ..core.persistence import LayoutDict
from ..exceptions import BlockSpecError
from .subsystem import Subsystem

_logger = logging.getLogger("pyflw.subsystems.triggered")

#: ``trigger_mode`` で許される値。
TRIGGER_MODES: tuple[str, ...] = ("rising", "falling", "either")


def _is_trigger_edge(prev: float, curr: float, mode: str) -> bool:
    """``mode`` に従って trigger edge を判定する (ADR-0036 §(3))。

    edge 判定基準: prev <= 0 → curr > 0 (rising)、prev >= 0 → curr < 0 (falling)、
    符号変化を検出する (= ``either``)。``prev == curr`` のときは edge ではない。

    最初の評価 (``prev`` が NaN sentinel) は edge と見なさない (= 起動時の偽エッジ
    防止)。
    """
    if np.isnan(prev) or np.isnan(curr):
        return False
    if mode == "rising":
        return prev <= 0.0 < curr
    if mode == "falling":
        return prev >= 0.0 > curr
    if mode == "either":
        return (prev <= 0.0 < curr) or (prev >= 0.0 > curr)
    raise BlockSpecError(
        f"_is_trigger_edge: unknown mode {mode!r}, expected one of {TRIGGER_MODES}"
    )


class TriggeredSubsystem(Subsystem):
    """トリガー信号で内部ブロックを発火するサブシステム (ADR-0036 §(2))。

    通常の :class:`Subsystem` を継承し、trigger 入力 (= 入力末尾の port) で
    edge 検出されたタイミングでのみ内部ブロックを実行する。fire しないステップでは
    内部状態が凍結され、出力は前回 fire 時の値を保持する (= Simulink Triggered
    Subsystem 互換)。

    Args:
        n_inputs: 外部入力数 (**trigger 入力を含む**)。内部 ``Inport`` 数は
            ``n_inputs - 1`` (= データ入力のみ、trigger は内部に流さない)。
        n_outputs: 外部出力数 (= 内部 ``Outport`` 数と一致)。
        trigger_mode: ``"rising"`` (上昇エッジ) / ``"falling"`` (下降エッジ) /
            ``"either"`` (両方)。default ``"rising"``。
        blocks / connections / id / name / port_shapes_in / port_shapes_out /
        layout / mask_params / mask_values: :class:`Subsystem` と同形 (ADR-0021)。

    Raises:
        BlockSpecError:
            - ``n_inputs < 1`` (trigger 入力分の最低 1 必須)
            - ``trigger_mode`` が ``TRIGGER_MODES`` 以外
            - 内部 ``Inport`` 数が ``n_inputs - 1`` と一致しない (= ``_build`` 時)
    """

    def __init__(
        self,
        n_inputs: int,
        n_outputs: int,
        blocks: list[Block] | None = None,
        connections: list[dict[str, Any]] | None = None,
        *,
        trigger_mode: str = "rising",
        id: str | None = None,
        name: str | None = None,
        port_shapes_in: tuple[tuple[int, ...], ...] | list[tuple[int, ...]] | None = None,
        port_shapes_out: tuple[tuple[int, ...], ...] | list[tuple[int, ...]] | None = None,
        layout: LayoutDict | None = None,
        mask_params: list[dict[str, Any]] | None = None,
        mask_values: dict[str, Any] | None = None,
    ) -> None:
        if n_inputs < 1:
            raise BlockSpecError(
                f"TriggeredSubsystem: n_inputs must be >= 1 (= at least the trigger "
                f"input), got {n_inputs}"
            )
        if trigger_mode not in TRIGGER_MODES:
            raise BlockSpecError(
                f"TriggeredSubsystem: trigger_mode must be one of {TRIGGER_MODES}, "
                f"got {trigger_mode!r}"
            )
        super().__init__(
            n_inputs=n_inputs,
            n_outputs=n_outputs,
            blocks=blocks,
            connections=connections,
            id=id,
            name=name,
            port_shapes_in=port_shapes_in,
            port_shapes_out=port_shapes_out,
            layout=layout,
            mask_params=mask_params,
            mask_values=mask_values,
        )
        self.trigger_mode = trigger_mode
        # Triggered Subsystem 用の追加 params (= JSON serialize 時に保持)
        self._params["trigger_mode"] = trigger_mode

        # 前回 trigger value (edge 検出用)。NaN で初期化 = 最初の評価では edge を
        # 立てない (起動時の偽エッジ防止)。
        self._prev_trigger_value: float = float("nan")
        # 最後に fire したときの出力ベクトル (= fire しないステップで返すキャッシュ)。
        # 初期値は zeros、最初の fire で更新される。
        self._last_y: npt.NDArray[Any] = np.zeros(self.n_outputs)

    def _build(self) -> None:
        """Subsystem._build を override して内部 ``Inport`` 数を ``n_inputs - 1`` 期待に変える。

        TriggeredSubsystem では trigger 入力 (= 入力末尾 port) は **内部に流れない
        制御信号** のため、内部 ``Inport`` の port_idx は ``[0, 1, ..., n_inputs-2]``
        の範囲。Subsystem._build の port_idx 整合チェックをこの規約で再実行する。
        """
        if self._exec_order is not None:
            return  # 既にビルド済

        # 一時的に self.n_inputs を 1 減らして親 _build を実行 (= データ入力数で
        # Inport 整合チェックさせる)、終わったら元に戻す。
        original_n_inputs = self.n_inputs
        original_port_shapes_in = self.port_shapes_in
        try:
            self.n_inputs = original_n_inputs - 1
            # trigger port を除いた残りの port_shape を一時的に渡す
            self.port_shapes_in = original_port_shapes_in[:-1]
            super()._build()
        finally:
            # 元に戻す
            self.n_inputs = original_n_inputs
            self.port_shapes_in = original_port_shapes_in
        # ADR-0036: trigger Subsystem は外側から見て discrete (周期 fire しない、
        # trigger でだけ動く)。direct_feedthrough は親 _build で内部から推論済だが、
        # **trigger 由来の出力遅延** が常にあるため強制 False。
        self.direct_feedthrough = False

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        """fire しないステップでは前回 fire 時の出力をキャッシュから返す。

        ``update`` の前後どちらで呼ばれても **同じ値** を返すため、Simulator の
        2-pass 出力計算 (ADR-0014 [A] phase) でも安全。
        """
        self._build()
        return np.asarray(self._last_y, dtype=float)

    def update(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        """trigger edge を検出してから内部状態を進める (ADR-0036 §(2)(3))。

        Simulator は本メソッドを ``k % step_ratio == 0`` の各サンプル境界で呼ぶ
        (Subsystem の継承に基づく)。本実装は:

        1. 入力末尾 ``u[-1]`` を trigger value として読む
        2. ``self._prev_trigger_value`` と比較して edge 判定
        3. edge なら内部 ``_step_inner`` で 内部 update を進めつつ ``_last_y`` を更新
        4. edge でなければ内部状態は **凍結** (= ``x`` をそのまま返す)
        5. ``self._prev_trigger_value = u[-1]`` で次ステップ用に保存
        """
        self._build()
        if self.n_states == 0 and len(u) == 1:
            # 内部状態ゼロ + データ入力ゼロの corner case
            self._prev_trigger_value = float(u[-1])
            return np.asarray(x, dtype=float)

        curr_trigger = float(u[-1])
        prev = self._prev_trigger_value
        edge = _is_trigger_edge(prev, curr_trigger, self.trigger_mode)
        # 次ステップ用に保存 (edge の有無に関わらず)
        self._prev_trigger_value = curr_trigger

        if not edge:
            # fire しない: 内部状態を凍結 + ``_last_y`` も維持
            return np.asarray(x, dtype=float)

        # fire する: データ入力部 (trigger を除く) で内部ブロックを実行。
        # ``_step_inner`` 内の ``for port_idx in range(self.n_inputs)`` は外側
        # n_inputs (= trigger 含む) を見るので、一時的に ``n_inputs - 1`` に下げて
        # データ Inport のみ書き込ませる (= ADR-0036 §(2) 実装トリック)。
        u_data = u[:-1]
        original_n_inputs = self.n_inputs
        try:
            self.n_inputs = original_n_inputs - 1
            outputs, inputs = self._step_inner(t, x, u_data)
        finally:
            self.n_inputs = original_n_inputs
        # 内部 discrete update (= 親 Subsystem.update のロジックを継承)
        x_next: npt.NDArray[Any] = np.array(x, dtype=float, copy=True)
        for b, sl in self._discrete_slices:
            x_next[sl] = np.asarray(
                b.update(t, x[sl], inputs.get(b, np.zeros(b.n_inputs))),
                dtype=float,
            )
        # ``_last_y`` を更新 (= 次回 output 呼び出しで返される値)
        y = np.zeros(self.n_outputs)
        for port_idx in range(self.n_outputs):
            outport = self._outports_by_idx[port_idx]
            src = outport.input_sources[0]
            if src is not None:
                sb, si = src
                y[port_idx] = outputs[sb][si]
        self._last_y = y
        return x_next

    def to_dict(self) -> dict[str, Any]:
        """``Subsystem.to_dict`` を override して ``trigger_mode`` を ``params`` に含める。

        親 ``Subsystem.to_dict`` は ``params`` を手動で構築するため、TriggeredSubsystem
        の追加 field (``trigger_mode``) は親の出力に追加で書き込む必要がある。
        他の field (n_inputs / n_outputs / blocks / connections / layout / mask) は
        親実装をそのまま流用。
        """
        d = super().to_dict()
        d["params"]["trigger_mode"] = self.trigger_mode
        return d

    @classmethod
    def _from_dict(
        cls,
        *,
        n_inputs: int,
        n_outputs: int,
        blocks: list[Any],
        connections: list[dict[str, Any]],
        trigger_mode: str = "rising",
        id: str | None = None,
        port_shapes_in: list[list[int]] | None = None,
        port_shapes_out: list[list[int]] | None = None,
        layout: LayoutDict | None = None,
        mask_params: list[dict[str, Any]] | None = None,
        mask_values: dict[str, Any] | None = None,
    ) -> TriggeredSubsystem:
        """JSON load 時の factory (Subsystem._from_dict の override、ADR-0036)。

        ``trigger_mode`` を kwargs で受け取り、コンストラクタに渡す。それ以外の
        ロジック (= mask placeholder 解決、内部 block の reconstruct、connect)
        は親 ``Subsystem._from_dict`` の実装を流用する形で書く。
        """
        # 親 _from_dict は ``cls(...)`` で TriggeredSubsystem を構築するため、
        # ``trigger_mode`` を一時的に class attribute として保存しておけば
        # ``__init__`` の default を上書きできる。だが副作用が複雑なので、
        # 親の本体ロジックを丸ごとコピーするのではなく、空 TriggeredSubsystem を
        # 直接作って blocks / connections を後から add する方式に変える。
        from ..core.persistence import resolve_block_class
        from ._mask import collect_placeholder_names, substitute_placeholders

        ps_in = (
            tuple(tuple(int(v) for v in s) for s in port_shapes_in)
            if port_shapes_in is not None
            else None
        )
        ps_out = (
            tuple(tuple(int(v) for v in s) for s in port_shapes_out)
            if port_shapes_out is not None
            else None
        )
        sub = cls(
            n_inputs=n_inputs,
            n_outputs=n_outputs,
            trigger_mode=trigger_mode,
            id=id,
            port_shapes_in=ps_in,
            port_shapes_out=ps_out,
            layout=layout,
            mask_params=mask_params,
            mask_values=mask_values,
        )
        active_mask_values = sub.mask_values if sub.mask_params else None
        if sub.mask_params:
            declared = {p["name"] for p in sub.mask_params}
            referenced: set[str] = set()
            for b in blocks:
                if isinstance(b, dict) and isinstance(b.get("params"), dict):
                    referenced |= collect_placeholder_names(b["params"])
            undefined = referenced - declared
            if undefined:
                raise BlockSpecError(
                    f"TriggeredSubsystem {id!r}: undefined mask placeholder(s) "
                    f"{sorted(undefined)} referenced in inner blocks "
                    f"(declared: {sorted(declared)})"
                )
        for b in blocks:
            if isinstance(b, dict):
                block_cls = resolve_block_class(b["type"])
                raw_params: dict[str, Any] = dict(b["params"])
                if active_mask_values is not None:
                    resolved_params = substitute_placeholders(raw_params, active_mask_values)
                else:
                    resolved_params = raw_params
                instance = block_cls(id=b["id"], **resolved_params)
                if active_mask_values is not None and resolved_params != raw_params:
                    instance._unresolved_params = raw_params
                sub.add(instance)
            else:
                sub.add(b)
        for c in connections:
            sub.connect(
                c["src"],
                c["dst"],
                src_idx=int(c.get("src_idx", 0)),
                dst_idx=int(c.get("dst_idx", 0)),
            )
        return sub

    def derivative(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        """連続状態は trigger でのみ進む (= fire しないステップではゼロ derivative)。

        ADR-0036 §(4-C) MVP で連続 trigger 信号は対象外、本メソッドは TriggeredSubsystem
        内部の連続ブロックがある場合に呼ばれる。fire 中の連続積分は通常通り Simulator
        の solve_ivp で進める。fire していない時間帯はゼロ derivative で凍結する
        Phase 5b MVP の単純化 (= Phase 6+ で zero-crossing 統合検討)。
        """
        self._build()
        if self.n_states == 0:
            return np.zeros(0)
        # MVP: 連続状態を持つ TriggeredSubsystem は warning 1 度
        # (= Phase 5b では離散信号 trigger 限定、ADR-0036 §(4-C))
        if self._continuous_slices:
            _logger.warning(
                "TriggeredSubsystem %r: contains continuous state; Phase 5b MVP "
                "freezes derivative (=0) outside trigger fires. See ADR-0036 §(4-C).",
                self.id,
            )
        return np.zeros(self.n_states)
