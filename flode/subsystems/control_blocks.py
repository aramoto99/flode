"""Subsystem behavior modifier blocks (ADR-0058)。

Subsystem 内部に配置することで親 Subsystem の発火/有効化セマンティクスを
修飾する境界ブロック群。``Inport`` / ``Outport`` と並ぶ「Subsystem 制御」
境界ブロック (= :mod:`flode.subsystems.ports` の延長で、データを持たず
親の挙動を宣言する用途)。

設計:
    - ``Trigger`` を内部に置くと、親 Subsystem は trigger 入力 1 個を持ち、
      指定エッジで内部ブロックを 1 step だけ fire する (= ADR-0036 の旧
      ``TriggeredSubsystem`` を一般化したもの)。
    - ``Enable`` を内部に置くと、親 Subsystem は enable 入力 1 個を持ち、
      enable=true の間だけ内部ブロックを動作させる。disable 中は state /
      output policy に従い ``"held"`` (凍結) または ``"reset"`` (初期化) する。
    - 両方を同 Subsystem に置くと「edge AND enable」で fire する。

スコープ (MVP = ADR-0058 §論点 1):
    - ``"function-call"`` trigger 種別は MVP では未実装 (build 時
      ``NotImplementedError``)。
    - 多重配置 (= 同 Subsystem 内に ``Trigger`` 2 個 / ``Enable`` 2 個) は
      親 ``Subsystem._build()`` 側で ``BlockSpecError`` で reject される。
    - root (= Simulator 直下) 配置は ``Simulator.build()`` 側で
      ``BlockSpecError`` で reject される。

実装メモ:
    - ``n_inputs = n_outputs = n_states = 0`` (= データを持たない、純粋な
      メタ宣言ブロック)。``direct_feedthrough=False`` で algebraic loop
      には参加しない。
    - ``output()`` は形式上の実装で空 ndarray を返す (= 親 Subsystem の
      ``_step_inner()`` から呼ばれない経路)。
"""

from __future__ import annotations

import math
from typing import Any, Literal, get_args

import numpy as np
import numpy.typing as npt

from ..core.block import Block
from ..exceptions import BlockSpecError

# 型エイリアスを単一の真実とし、tuple / _param_enums / validation はすべて
# ここから ``get_args`` で導出する (= 値追加時の更新漏れを防ぐ、Scope.buffer_mode
# の get_args パターンに揃える)。

# ADR-0058 §論点 10: 4 種の trigger 種別。``"function-call"`` は MVP では
# 構築は通すが、親 ``Subsystem._build()`` で ``NotImplementedError`` を出す
# (= 受け皿だけ用意、Phase 6+ で実装)。
TriggerType = Literal["rising", "falling", "either", "function-call"]
TRIGGER_TYPES: tuple[str, ...] = get_args(TriggerType)

# ADR-0058 §論点 4: enable=false → true 遷移時の内部 state の扱い。
EnableStatePolicy = Literal["held", "reset"]
ENABLE_STATE_POLICIES: tuple[str, ...] = get_args(EnableStatePolicy)

# ADR-0058 §論点 5: enable=false 中の親 Subsystem 出力ポートの扱い。
EnableOutputPolicy = Literal["held", "reset"]
ENABLE_OUTPUT_POLICIES: tuple[str, ...] = get_args(EnableOutputPolicy)


def is_trigger_edge(prev: float, curr: float, mode: str) -> bool:
    """trigger 信号の edge を検出する (ADR-0036 §(4) / ADR-0058 §論点 10)。

    旧 ``flode.subsystems.triggered._is_trigger_edge`` (private) を本モジュールに
    公開関数として移し、新 ``Trigger`` block と旧 ``TriggeredSubsystem`` 両者から
    呼べるようにしたもの。semantics は ADR-0036 のまま不変 (= 数値完全不変ガード
    の根拠、Chunk B で ``triggered.py`` から呼び替える前提)。

    Edge 判定基準:
        - ``rising``: ``prev <= 0`` かつ ``curr > 0`` (= 0 を境界に上昇)
        - ``falling``: ``prev >= 0`` かつ ``curr < 0`` (= 0 を境界に下降)
        - ``either``: rising または falling のいずれか (= 0 を境界に符号変化)
        - ``prev == curr`` は edge でない (= 変化なし)。
        - 初回評価 (``prev`` が NaN sentinel) と ``curr`` が NaN は edge とみなさない
          (= 起動時の偽エッジ防止 / 上流発散時の safe fallback)。

    Args:
        prev: 前ステップの trigger 信号値 (NaN は初回 sentinel)。
        curr: 現ステップの trigger 信号値 (NaN は edge 扱いしない)。
        mode: ``"rising"`` / ``"falling"`` / ``"either"`` のいずれか。

    Returns:
        Edge 検出時 True、それ以外 False。

    Raises:
        BlockSpecError: ``mode`` が 3 種のいずれでもない場合 (``"function-call"`` は
            edge 検出経路を通らないので本関数では未対応)。旧 ``_is_trigger_edge`` と
            例外型を揃える (Chunk B 移行時の互換性のため)。
    """
    # 旧 _is_trigger_edge と同じく prev / curr の両方を NaN ガードする
    # (= ADR-0036 §(8) 数値完全不変、Chunk B 切り替え時の挙動差ゼロ保証)。
    if math.isnan(prev) or math.isnan(curr):
        return False
    if mode == "rising":
        return prev <= 0.0 < curr
    if mode == "falling":
        return prev >= 0.0 > curr
    if mode == "either":
        return (prev <= 0.0 < curr) or (prev >= 0.0 > curr)
    raise BlockSpecError(
        f"is_trigger_edge: unknown mode {mode!r}, expected one of ('rising', 'falling', 'either')"
    )


class Trigger(Block):
    """Subsystem 内部に配置することで親を Triggered Subsystem 化する境界ブロック。

    親 ``Subsystem`` の ``_build()`` が ``isinstance(b, Trigger)`` で本ブロックを
    検出し、親側に trigger 入力ポート (= 末尾 slot) を 1 個追加する。fire 判定は
    親の ``update()`` で :func:`is_trigger_edge` で行う。

    n_inputs = n_outputs = n_states = 0、``direct_feedthrough=False``。データを
    持たない純粋なメタ宣言ブロックで、`Inport` / `Outport` と並ぶ「Subsystem
    制御」境界ブロック。

    Args:
        trigger_type: ``"rising"`` (default、上昇エッジで fire) / ``"falling"``
            (下降エッジ) / ``"either"`` (両方) / ``"function-call"`` (プログラム
            的呼び出し駆動、**MVP では親 ``Subsystem._build()`` で
            ``NotImplementedError``**)。
        id: ブロック ID (省略時は auto-id)。
        name: ``id`` の Phase 0 alias (両方指定すると ``BlockSpecError``)。

    Raises:
        BlockSpecError: ``trigger_type`` が enum 外の場合。
    """

    # ADR-0058 §論点 10: GUI ParameterPanel が enum select を出すヒント
    # (ADR-0039 follow-up = `_param_enums` 機構)。
    _param_enums = {"trigger_type": TRIGGER_TYPES}

    def __init__(
        self,
        trigger_type: TriggerType = "rising",
        *,
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        # 早期 fail: super().__init__ が auto-id 割り当て等の副作用を持つ前に
        # 値検証する (Inport / Outport と同じパターン)。
        if trigger_type not in TRIGGER_TYPES:
            raise BlockSpecError(
                f"Trigger: trigger_type must be one of {TRIGGER_TYPES}, got {trigger_type!r}"
            )
        super().__init__(
            id=id,
            name=name,
            n_inputs=0,
            n_outputs=0,
            n_states=0,
            direct_feedthrough=False,
        )
        self.trigger_type: TriggerType = trigger_type
        self._params = {"trigger_type": trigger_type}

    def output(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: npt.NDArray[Any],
    ) -> npt.NDArray[Any]:
        # 境界ブロックなので出力は持たない (n_outputs=0)。形式上 0-length ndarray
        # を返す (= Inport / Outport と同じ idiom)。
        return np.zeros(0)


class Enable(Block):
    """Subsystem 内部に配置することで親を Enabled Subsystem 化する境界ブロック。

    親 ``Subsystem`` の ``_build()`` が ``isinstance(b, Enable)`` で本ブロックを
    検出し、親側に enable 入力ポートを追加する。slot 順序は ``[data_inports...,
    enable_slot, trigger_slot]`` で、Trigger なしのとき enable_slot は末尾。

    enable 値が ``> 0`` の間だけ親 Subsystem の内部ブロックが動作する。disable
    中の挙動:
        - 内部 state: ``states_when_enabling`` policy で ``"held"`` (default、
          凍結維持) または ``"reset"`` (enable 真へ遷移した瞬間に初期値に戻す)
        - 出力: ``outputs_when_disabled`` policy で ``"held"`` (直前値保持) または
          ``"reset"`` (0 を返す)
        - 連続状態の ``derivative()`` は 0 を返し、solve_ivp の積分は継続する
          (= state vector は held + dx/dt=0 で凍結、ADR-0058 §論点 6)

    Args:
        states_when_enabling: enable=false → true 遷移時の内部 state の扱い。
            ``"held"`` (default) / ``"reset"``。
        outputs_when_disabled: enable=false 中の親 Subsystem 出力ポートの扱い。
            ``"held"`` (default) / ``"reset"``。
        id: ブロック ID (省略時は auto-id)。
        name: ``id`` の Phase 0 alias。

    Raises:
        BlockSpecError: ``states_when_enabling`` / ``outputs_when_disabled`` が
            enum 外の場合。
    """

    # ADR-0058 §論点 4 / 5: GUI ParameterPanel が enum select を出すヒント。
    _param_enums = {
        "states_when_enabling": ENABLE_STATE_POLICIES,
        "outputs_when_disabled": ENABLE_OUTPUT_POLICIES,
    }

    def __init__(
        self,
        *,
        states_when_enabling: EnableStatePolicy = "held",
        outputs_when_disabled: EnableOutputPolicy = "held",
        id: str | None = None,
        name: str | None = None,
    ) -> None:
        # 早期 fail: super().__init__ が auto-id 割り当て等の副作用を持つ前に
        # 値検証する (Inport / Outport と同じパターン)。
        if states_when_enabling not in ENABLE_STATE_POLICIES:
            raise BlockSpecError(
                f"Enable: states_when_enabling must be one of "
                f"{ENABLE_STATE_POLICIES}, got {states_when_enabling!r}"
            )
        if outputs_when_disabled not in ENABLE_OUTPUT_POLICIES:
            raise BlockSpecError(
                f"Enable: outputs_when_disabled must be one of "
                f"{ENABLE_OUTPUT_POLICIES}, got {outputs_when_disabled!r}"
            )
        super().__init__(
            id=id,
            name=name,
            n_inputs=0,
            n_outputs=0,
            n_states=0,
            direct_feedthrough=False,
        )
        self.states_when_enabling: EnableStatePolicy = states_when_enabling
        self.outputs_when_disabled: EnableOutputPolicy = outputs_when_disabled
        self._params = {
            "states_when_enabling": states_when_enabling,
            "outputs_when_disabled": outputs_when_disabled,
        }

    def output(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: npt.NDArray[Any],
    ) -> npt.NDArray[Any]:
        return np.zeros(0)
