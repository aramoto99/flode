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
from .ports import Inport
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

    ADR-0039 (v2.0): 親 :class:`Subsystem` と同じく ``n_inputs`` / ``n_outputs``
    は派生 property。``n_inputs = 内部 Inport 数 + 1`` (trigger 分)。
    ``n_outputs = 内部 Outport 数``。利用者は
    ``ts.add(Inport(port_idx=i))`` で内部データ入力を増やす。trigger 入力は
    末尾 (``input_sources[-1]``) 固定で、初期化時に自動確保される。

    Args:
        trigger_mode: ``"rising"`` (上昇エッジ) / ``"falling"`` (下降エッジ) /
            ``"either"`` (両方)。default ``"rising"``。
        blocks / connections / id / name / layout / mask_params / mask_values:
            :class:`Subsystem` と同形 (ADR-0021)。

    Raises:
        BlockSpecError: ``trigger_mode`` が ``TRIGGER_MODES`` 以外。
        TypeError: v1.0 互換引数 ``n_inputs`` / ``n_outputs`` /
            ``port_shapes_in`` / ``port_shapes_out`` が渡された場合 (= ADR-0039)。
    """

    _param_enums = {"trigger_mode": TRIGGER_MODES}

    def __init__(
        self,
        blocks: list[Block] | None = None,
        connections: list[dict[str, Any]] | None = None,
        *,
        trigger_mode: str = "rising",
        id: str | None = None,
        name: str | None = None,
        layout: LayoutDict | None = None,
        mask_params: list[dict[str, Any]] | None = None,
        mask_values: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        if trigger_mode not in TRIGGER_MODES:
            raise BlockSpecError(
                f"TriggeredSubsystem: trigger_mode must be one of {TRIGGER_MODES}, "
                f"got {trigger_mode!r}"
            )
        # 親 Subsystem.__init__ が ADR-0039 廃止引数 (n_inputs 等) の TypeError を
        # 出すので、ここでは kwargs をそのまま渡して親に検証を委譲する
        super().__init__(
            blocks=blocks,
            connections=connections,
            id=id,
            name=name,
            layout=layout,
            mask_params=mask_params,
            mask_values=mask_values,
            **kwargs,
        )

        # ADR-0036 §(2): trigger 入力は末尾 (input_sources[-1]) 固定。Subsystem
        # __init__ は内部 Inport が無い空状態から始まるため、ここで trigger slot
        # を手動で確保する。以降 ``add(Inport)`` で内部 Inport slot が末尾の前に
        # 挿入され、trigger は常に末尾を保つ。
        self.input_sources.append(None)

        self.trigger_mode = trigger_mode
        # Triggered Subsystem 用の追加 params (= JSON serialize 時に保持)
        self._params["trigger_mode"] = trigger_mode

        # 前回 trigger value (edge 検出用)。NaN で初期化 = 最初の評価では edge を
        # 立てない (起動時の偽エッジ防止)。
        self._prev_trigger_value: float = float("nan")
        # 最後に fire したときの出力ベクトル (= fire しないステップで返すキャッシュ)。
        # 初期値は zeros、最初の fire で更新される (n_outputs は派生 property)。
        self._last_y: npt.NDArray[Any] = np.zeros(self.n_outputs)

    @property
    def n_inputs(self) -> int:
        # 内部 Inport 数 + trigger 1 (ADR-0036 §(2))。``Subsystem.n_inputs`` の
        # property を直接呼ぶと再帰になるので、_inner_blocks を直接 filter する。
        return sum(1 for b in self._inner_blocks if isinstance(b, Inport)) + 1

    @n_inputs.setter
    def n_inputs(self, value: int) -> None:  # noqa: ARG002
        pass

    @property
    def port_shapes_in(self) -> tuple[tuple[int, ...], ...]:
        # 内部 Inport の port_shape (port_idx 順) + trigger slot の () を末尾に追加。
        # trigger は離散 scalar 信号 (ADR-0036 §(3)) なので shape は常に ()。
        inports = sorted(
            (b for b in self._inner_blocks if isinstance(b, Inport)),
            key=lambda p: p.port_idx,
        )
        return tuple(p.port_shape for p in inports) + ((),)

    @port_shapes_in.setter
    def port_shapes_in(self, value: tuple[tuple[int, ...], ...]) -> None:  # noqa: ARG002
        pass

    def add(self, block: Block) -> Block:
        """内部ブロックを登録する (ADR-0036 §(2) trigger slot 末尾保持)。

        親 ``Subsystem.add`` は ``Inport`` を追加すると ``input_sources.append(None)``
        するが、TriggeredSubsystem では trigger slot が末尾固定なので、追加された
        slot を末尾の 1 つ前に move して trigger を後ろに保つ。
        """
        result = super().add(block)
        if isinstance(block, Inport):
            # 親 add で末尾に append された None を、末尾の 1 つ前 (= trigger の前) に
            # 移動。input_sources = [..., new Inport slot, trigger slot] になる。
            new_slot = self.input_sources.pop()
            self.input_sources.insert(-1, new_slot)
        return result

    def _build(self) -> None:
        """親 ``Subsystem._build`` をそのまま呼び、最後に direct_feedthrough を
        強制 False にするだけ (ADR-0036 §(2))。

        ADR-0039: 派生 property 化で「内部 Inport 数 == n_inputs - 1」は自然成立
        するため、v1 で必要だった ``n_inputs - 1`` への一時上書き trick は廃止。
        """
        if self._exec_order is not None:
            return
        super()._build()
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

        ADR-0039: 内部 Inport 数 == ``n_inputs - 1`` は派生 property で自然成立
        する。v1 で必要だった ``self.n_inputs`` 一時上書き trick は不要 (=
        ``_step_inner`` は ``self.n_inputs`` を直接見ない設計に依存)。
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
        # ``_step_inner`` は内部 Inport の port_idx [0..N-1] を u_data から書き込む
        # ので、trigger を除いた u[:-1] を渡せばよい。``self.n_inputs`` の一時
        # 上書きは不要 (= ADR-0039 派生 property 化で `_step_inner` 内の
        # ``range(self.n_inputs)`` ではなく ``range(len(u_external))`` を見る形に
        # 揃える前提)。
        u_data = u[:-1]
        outputs, inputs = self._step_inner(t, x, u_data)
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
        blocks: list[Any],
        connections: list[dict[str, Any]],
        trigger_mode: str = "rising",
        id: str | None = None,
        layout: LayoutDict | None = None,
        mask_params: list[dict[str, Any]] | None = None,
        mask_values: dict[str, Any] | None = None,
        **legacy_kwargs: Any,
    ) -> TriggeredSubsystem:
        """JSON load 時の factory (Subsystem._from_dict の override、ADR-0036)。

        ADR-0039: ``n_inputs`` / ``n_outputs`` / ``port_shapes_in`` /
        ``port_shapes_out`` は派生 property になったため、JSON 上に残っていても
        ``legacy_kwargs`` で受け取って読み捨てる (= migration `_builtin_migrate_0_7_to_0_8`
        で削除されているはずだが、誤って残った場合の defensive)。
        """
        from ..core.persistence import resolve_block_class
        from ._mask import collect_placeholder_names, substitute_placeholders

        # ADR-0039: legacy フィールドを受けたら警告してから捨てる
        legacy_dropped = {
            k: legacy_kwargs.pop(k)
            for k in list(legacy_kwargs)
            if k in {"n_inputs", "n_outputs", "port_shapes_in", "port_shapes_out"}
        }
        if legacy_dropped:
            _logger.warning(
                "TriggeredSubsystem %r._from_dict: dropping legacy schema 0.7 fields %s "
                "(now derived from inner Inport/Outport, ADR-0039)",
                id,
                sorted(legacy_dropped),
            )
        if legacy_kwargs:
            raise TypeError(
                f"TriggeredSubsystem._from_dict: unexpected keyword arguments "
                f"{sorted(legacy_kwargs)}"
            )

        sub = cls(
            trigger_mode=trigger_mode,
            id=id,
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
