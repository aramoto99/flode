"""Atomic Subsystem (ADR-0009)。

``Subsystem`` は外部から見ると 1 つの ``Block``、内部に独自のブロック群と結線を
持つ複合ブロック。``output`` / ``derivative`` / ``update`` は内部の軽量
ランタイム (``_SubsystemRuntime``) に委譲される。

スケジューラ統合 (ADR-0009 §(5)):
* Inport の値は ``Subsystem.output(t, x, u)`` 呼び出し時に内部 Inport インスタンスの
  ``_external_value`` に注入される
* 内部の 2 パス出力計算 (``Simulator._step`` と同等) を実行
* Outport の ``_captured_value`` を集めて Subsystem の出力ベクトルとする
* 連続状態は ``Block.derivative`` で内部の各連続ブロックの derivative を集約
* 離散状態は ``Block.update`` で内部の各離散ブロックの update を集約
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict, deque
from typing import Any

import numpy as np
import numpy.typing as npt

from ..core.block import (
    BASE_CLOCK_SAMPLE_TIME,
    Block,
    in_serialization_build,
    register_serialization_invalidation,
    serialization_build,
)
from ..core.identifiers import fold_block_id
from ..core.persistence import LayoutDict, normalize_layout
from ..exceptions import (
    AlgebraicLoopError,
    BlockSpecError,
    ModelSerializationError,
    PortIndexError,
)
from ._mask import (
    collect_placeholder_names,
    normalize_mask_params,
    substitute_placeholders,
)
from .control_blocks import Enable, Trigger, is_trigger_edge
from .ports import Inport, Outport

_logger = logging.getLogger("flode.subsystem")


class Subsystem(Block):
    """Atomic Subsystem: 内部に独自のブロック群と結線を持つ複合ブロック。

    ADR-0039 (v2.0): ``n_inputs`` / ``n_outputs`` / ``port_shapes_in`` /
    ``port_shapes_out`` は **内部 ``Inport`` / ``Outport`` から派生する property**
    で、コンストラクタには渡せない (TypeError)。利用者は
    ``sub.add(Inport(port_idx=i, port_shape=...))`` で port を増やす。

    Args:
        blocks: 内部ブロックのリスト (Inport / Outport を含む)。``None`` の場合は
            空 (``add()`` で追加)。
        connections: 内部結線のリスト ``[(src_id, dst_id, src_idx, dst_idx), ...]``。
            ``None`` の場合は ``connect()`` で追加。
        id: ブロック id (省略時は親 ``Simulator`` で auto 採番)。
        name: 表示名 (省略可)。
        layout: 内部 GUI レイアウト (ADR-0020、再帰)。
        mask_params: マスクパラメータ宣言 (ADR-0021)。
        mask_values: マスク現在値。
    """

    def __init__(
        self,
        blocks: list[Block] | None = None,
        connections: list[dict[str, Any]] | None = None,
        *,
        id: str | None = None,
        name: str | None = None,
        layout: LayoutDict | None = None,
        mask_params: list[dict[str, Any]] | None = None,
        mask_values: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        # ADR-0039: n_inputs / n_outputs / port_shapes_in / port_shapes_out は
        # 廃止された引数。明示的に拒否して移行を促す (= silent ignore は禁止)。
        forbidden = (
            "n_inputs",
            "n_outputs",
            "port_shapes_in",
            "port_shapes_out",
        )
        rejected = [k for k in forbidden if k in kwargs]
        if rejected:
            raise TypeError(
                f"Subsystem: arguments {rejected} were removed in v2.0 (ADR-0039). "
                f"They are now derived from inner Inport/Outport blocks. "
                f"Use ``sub.add(Inport(port_idx=i, port_shape=...))`` to add ports. "
                f"See CHANGELOG [0.14.0] migration guide."
            )
        if kwargs:
            raise TypeError(f"Subsystem: unexpected keyword arguments {sorted(kwargs)}")

        # 派生 property に対応するため n_inputs=0 / n_outputs=0 で初期化 (= 内部
        # Inport / Outport が無い空状態)。port_shapes_in / out も派生 property
        # なので空 tuple で初期化される。
        super().__init__(
            id=id,
            name=name,
            n_inputs=0,
            n_outputs=0,
            n_states=0,
            direct_feedthrough=False,
        )

        self._inner_blocks: list[Block] = []
        self._inner_blocks_by_id: dict[str, Block] = {}
        # ADR-0071 §(2): NFKC fold key → NFC id。Simulator._folded_ids と同じ
        # 「見た目類似 id の共存拒否」を内部スコープにも適用する
        self._inner_folded_ids: dict[str, str] = {}
        self._inner_type_counters: dict[str, int] = {}

        # 内部状態 layout: 各内部ブロックに対し state vector の slice を割り当てる
        # build (deferred) で確定
        self._state_slices: list[tuple[Block, slice]] = []
        self._discrete_slices: list[tuple[Block, slice]] = []
        self._continuous_slices: list[tuple[Block, slice]] = []

        # トポロジカル実行順 (build 時に確定)
        self._exec_order: list[Block] | None = None

        # ADR-0039 code-reviewer NITS-1: port_idx → port instance マップは
        # ``_build()`` 内で populate されるが、型を __init__ で宣言しておくことで
        # 「どの属性が保証されるか」を読み手に明示する。
        self._inports_by_idx: dict[int, Inport] = {}
        self._outports_by_idx: dict[int, Outport] = {}

        # ADR-0058: Subsystem behavior modifier (Trigger / Enable control block)。
        # ``_build()`` 内で内部 inner_blocks をスキャンして確定する。
        # ``_has_trigger`` / ``_has_enable`` が共に False のとき、output / derivative
        # / update は既存 hot-path をそのまま通る (= 数値完全不変ガード、ADR-0058
        # §論点 14)。
        self._trigger_block: Trigger | None = None
        self._enable_block: Enable | None = None
        self._has_trigger: bool = False
        self._has_enable: bool = False
        # ``_step_inner`` に渡すデータ Inport 数 (= n_inputs - control_count)。
        self._n_data_inports: int = 0
        # 外部 u 配列における slot index ([data..., enable, trigger] 順)。
        self._enable_slot_idx: int | None = None
        self._trigger_slot_idx: int | None = None
        # Trigger fire 判定用の前ステップ値 (NaN sentinel で起動時の偽エッジ防止、
        # 旧 TriggeredSubsystem._prev_trigger_value と同じ initial)。
        self._prev_trigger_value: float = float("nan")
        # Enable 遷移検出用の前ステップ enable 値 (NaN = 初回、`> 0` で enabled)。
        self._prev_enable_value: float = float("nan")
        # fire しないステップ / disable 中ステップで返す出力キャッシュ。
        # ``_build`` 後に zeros(n_outputs) で初期化される (= n_outputs は派生 property)。
        self._last_y: npt.NDArray[Any] | None = None

        # ADR-0055 §論点 5-A: Goto/From 仮想エッジ展開で外部 (Simulator) から
        # 追加される内部 ``(dst, src)`` deps の set。``_compute_exec_order`` が
        # 冒頭で deps に merge する。Goto/From を含まない Subsystem では常に空
        # set のため、既存テストの数値完全不変ガード。
        self._virtual_inner_deps: set[tuple[Block, Block]] = set()
        # bug-fix 2026-09-13: 外部 (上位スコープ) の From から参照される Goto、
        # またはそれを含む内側 Subsystem。``_infer_direct_feedthrough`` で Outport と
        # 同じ「到達目標」として扱い、Inport から直達で到達できるなら本 Subsystem
        # を直達にする (= パス 1 で実入力を使って Goto が値を記録できるようにする)。
        # ``Simulator._resolve_goto_from_virtual_edges`` が populate する。
        self._df_extra_targets: set[Block] = set()

        # save/load 用 params (= ADR-0039 で n_inputs / n_outputs / port_shapes_*
        # フィールドは廃止、内部 blocks / connections のみ保存)。
        self._params = {
            "blocks": [],  # build 後に populate
            "connections": [],
        }

        # ADR-0020 §Decision (1): Subsystem 内部 GUI レイアウト (再帰)。``None`` /
        # 空 dict のとき ``params.layout`` を JSON に出さず、SM-A モデルの byte-identical
        # を維持する。形式正規化は ``normalize_layout`` に委譲。
        self.layout: LayoutDict | None = normalize_layout(layout)

        # ADR-0021 §(6)(9): マスクパラメータ宣言 + 現在値。declarative `mask_params`
        # が None / 空のとき「マスクなし Subsystem」として byte-identical を維持。
        self.mask_params: list[dict[str, Any]] | None = normalize_mask_params(mask_params)
        self.mask_values: dict[str, Any] = self._init_mask_values(mask_values)

        if blocks is not None:
            for b in blocks:
                self.add(b)
        if connections is not None:
            for c in connections:
                self.connect(c["src"], c["dst"], c.get("src_idx", 0), c.get("dst_idx", 0))

    # ---------- 派生 property: n_inputs / n_outputs / port_shapes_in / port_shapes_out ----------
    #
    # ADR-0039 §Decision §(2): Subsystem の port count / shape は内部 Inport / Outport
    # から毎回算出する派生 property。setter は silent no-op (= ``Block.__init__`` 内の
    # ``self.n_inputs = n_inputs`` 直接代入 や migration 経由の代入を吸収)。

    @property
    def n_inputs(self) -> int:
        # ADR-0058 §論点 4: slot 順序 [data_inports..., enable_slot, trigger_slot]。
        # Enable / Trigger を内部に持つ Subsystem は外側から見た n_inputs に
        # 1 個ずつ加算される。
        n_data = sum(1 for b in self._inner_blocks if isinstance(b, Inport))
        n_enable = sum(1 for b in self._inner_blocks if isinstance(b, Enable))
        n_trigger = sum(1 for b in self._inner_blocks if isinstance(b, Trigger))
        return n_data + n_enable + n_trigger

    @n_inputs.setter
    def n_inputs(self, value: int) -> None:  # noqa: ARG002
        # 派生値なので外部からの代入は silent ignore (Block.__init__ の代入を吸収)
        pass

    @property
    def n_outputs(self) -> int:
        return sum(1 for b in self._inner_blocks if isinstance(b, Outport))

    @n_outputs.setter
    def n_outputs(self, value: int) -> None:  # noqa: ARG002
        pass

    @property
    def port_shapes_in(self) -> tuple[tuple[int, ...], ...]:
        # 内部 Inport を port_idx 順で並べて port_shape を集める。port_idx 重複や
        # 抜けは ``_build`` で検出するため、ここでは見つかった順に並べる。
        # ADR-0058 §論点 4: enable / trigger slot は scalar () shape を末尾に追加。
        inports = sorted(
            (b for b in self._inner_blocks if isinstance(b, Inport)),
            key=lambda p: p.port_idx,
        )
        shapes: tuple[tuple[int, ...], ...] = tuple(p.port_shape for p in inports)
        has_enable = any(isinstance(b, Enable) for b in self._inner_blocks)
        has_trigger = any(isinstance(b, Trigger) for b in self._inner_blocks)
        if has_enable:
            shapes = shapes + ((),)
        if has_trigger:
            shapes = shapes + ((),)
        return shapes

    @port_shapes_in.setter
    def port_shapes_in(self, value: tuple[tuple[int, ...], ...]) -> None:  # noqa: ARG002
        pass

    @property
    def port_shapes_out(self) -> tuple[tuple[int, ...], ...]:
        outports = sorted(
            (b for b in self._inner_blocks if isinstance(b, Outport)),
            key=lambda p: p.port_idx,
        )
        return tuple(p.port_shape for p in outports)

    @port_shapes_out.setter
    def port_shapes_out(self, value: tuple[tuple[int, ...], ...]) -> None:  # noqa: ARG002
        pass

    # ---------- ブロック登録・結線 (Simulator と同形 API) ----------

    def add(self, block: Block) -> Block:
        """内部ブロックを登録する。``Simulator.add`` と同形 (ADR-0004)。

        ADR-0039: ``Inport`` を追加すると外側 ``self.input_sources`` (= 親階層
        からの結線先 slot) を 1 個拡張する。``Outport`` を追加した場合は外側出力
        側なので ``input_sources`` には影響しない。

        既にビルド済み (``_build`` 後) の場合は ``_exec_order`` を ``None`` に戻して
        再ビルドを促す (code-reviewer SHOULD 修正)。
        """
        if not isinstance(block, Block):
            raise TypeError(f"Expected Block instance, got {type(block).__name__}")
        if block.id is None:
            block.id = self._auto_id(block)
        else:
            if block.id in self._inner_blocks_by_id:
                raise BlockSpecError(
                    f"Subsystem {self.id!r}: inner block id {block.id!r} already exists"
                )
            # ADR-0071 §(2): NFKC fold key での衝突 (全角/半角違い等) も拒否
            existing = self._inner_folded_ids.get(fold_block_id(block.id))
            if existing is not None:
                raise BlockSpecError(
                    f"Subsystem {self.id!r}: inner block id {block.id!r} conflicts "
                    f"with existing id {existing!r}: the two are NFKC-equivalent "
                    f"(visually confusable). Choose a distinct name."
                )
        self._inner_blocks_by_id[block.id] = block
        self._inner_folded_ids[fold_block_id(block.id)] = block.id
        self._inner_blocks.append(block)
        # ADR-0039: Inport が追加されたら外側 input_sources を拡張 (= n_inputs
        # property に同期させる、Block 契約「input_sources の長さ == n_inputs」を維持)。
        # ADR-0058 §論点 4: slot 順序 [data_inports..., enable, trigger]。control
        # block (Enable / Trigger) は input_sources の末尾側に並ぶため、Inport を
        # 追加するときは control slot の **前** に挿入する。
        if isinstance(block, Inport):
            # 既に存在する control slot の数 (= block 自身は Inport なので除外不要)
            n_control_at_tail = sum(
                1 for b in self._inner_blocks if isinstance(b, (Enable, Trigger))
            )
            insert_pos = len(self.input_sources) - n_control_at_tail
            self.input_sources.insert(insert_pos, None)
        elif isinstance(block, Enable):
            # Enable は末尾側 control 群の最初 (= Trigger があるならその前)。
            # ``isinstance(b, Trigger)`` で Trigger 有無を判定。block 自身は Enable
            # なので Trigger には該当せず、自動的に除外される。
            trigger_present = any(isinstance(b, Trigger) for b in self._inner_blocks)
            if trigger_present:
                # 末尾 Trigger slot の 1 つ前に挿入
                self.input_sources.insert(-1, None)
            else:
                self.input_sources.append(None)
        elif isinstance(block, Trigger):
            # Trigger は常に末尾 (ADR-0058 §論点 4)
            self.input_sources.append(None)
        # 構造変更があったので次回 _build を強制再実行
        self._exec_order = None
        return block

    def _auto_id(self, block: Block) -> str:
        type_name = type(block).__name__
        n = self._inner_type_counters.get(type_name, 0)
        candidate = f"{type_name}_{n}"
        # fold key での衝突もスキップ (ADR-0071 §(2)、Simulator._auto_id と同方針)
        while candidate in self._inner_blocks_by_id or candidate in self._inner_folded_ids:
            n += 1
            candidate = f"{type_name}_{n}"
        self._inner_type_counters[type_name] = n + 1
        return candidate

    def get_block(self, block_id: str) -> Block:
        if block_id not in self._inner_blocks_by_id:
            raise BlockSpecError(f"Subsystem {self.id!r}: no inner block with id {block_id!r}")
        return self._inner_blocks_by_id[block_id]

    def _resolve(self, x: Block | str) -> Block:
        if isinstance(x, Block):
            return x
        if isinstance(x, str):
            return self.get_block(x)
        raise TypeError(f"Expected Block or str (block id), got {type(x).__name__}")

    def connect(
        self,
        src: Block | str,
        dst: Block | str,
        src_idx: int = 0,
        dst_idx: int = 0,
    ) -> None:
        """内部ブロック同士を結線する。``Simulator.connect`` と同形。"""
        src_block = self._resolve(src)
        dst_block = self._resolve(dst)
        # bug-fix 2026-09-14: builtin IndexError ではなくドメイン例外 (IndexError 互換)
        if dst_idx < 0 or dst_idx >= dst_block.n_inputs:
            raise PortIndexError(
                f"{dst_block.id}: input index {dst_idx} out of range "
                f"(n_inputs={dst_block.n_inputs})",
                block_id=dst_block.id,
            )
        if src_idx < 0 or src_idx >= src_block.n_outputs:
            raise PortIndexError(
                f"{src_block.id}: output index {src_idx} out of range "
                f"(n_outputs={src_block.n_outputs})",
                block_id=src_block.id,
            )
        dst_block.input_sources[dst_idx] = (src_block, src_idx)
        # 構造変更があったので次回 _build を強制再実行
        self._exec_order = None

    # ---------- ビルド (内部状態 / 実行順 / direct_feedthrough 確定) ----------

    def _build(self) -> None:
        """内部 layout / 実行順 / direct_feedthrough を確定する。

        最初の ``output`` / ``derivative`` / ``update`` 呼び出しで遅延実行される。
        ``add`` / ``connect`` で内部構造が変更されると ``_exec_order = None`` に戻り、
        次の ``_build`` で再構築される。

        ADR-0021 §(6): マスク placeholder ($Kp 等) の resolve は他の build パスより
        前に行う。port_shape を変える placeholder は ``BlockSpecError`` で拒否する
        (= ADR-0017 静的 port_shape 宣言との整合)。
        """
        if self._exec_order is not None:
            return  # 既にビルド済み (構造変更が無いため再実行不要)
        # 再ビルド時の累積を避けるため、layout 系を都度クリア
        self._state_slices = []
        self._continuous_slices = []
        self._discrete_slices = []

        # ADR-0021 §(6): マスク placeholder の resolve
        self._resolve_mask_placeholders()

        # Inport / Outport / control block (Trigger / Enable) の一覧
        # ADR-0039: n_inputs / n_outputs / port_shapes_in / port_shapes_out は
        # すべて派生 property のため、内部 Inport / Outport との count 一致と
        # port_shape 整合は **自動的に成立**する。port_idx の重複・抜けのみ検証。
        # ADR-0058: Trigger / Enable control block を同パスで検出し、多重配置を
        # reject する。
        inports = [b for b in self._inner_blocks if isinstance(b, Inport)]
        outports = [b for b in self._inner_blocks if isinstance(b, Outport)]
        triggers = [b for b in self._inner_blocks if isinstance(b, Trigger)]
        enables = [b for b in self._inner_blocks if isinstance(b, Enable)]

        # ADR-0058 §論点 8: 多重配置は build 時に BlockSpecError で reject
        if len(triggers) > 1:
            raise BlockSpecError(
                f"Subsystem {self.id!r}: at most one Trigger block is allowed, "
                f"got {len(triggers)}: {[t.id for t in triggers]}"
            )
        if len(enables) > 1:
            raise BlockSpecError(
                f"Subsystem {self.id!r}: at most one Enable block is allowed, "
                f"got {len(enables)}: {[e.id for e in enables]}"
            )

        trigger_block: Trigger | None = triggers[0] if triggers else None
        enable_block: Enable | None = enables[0] if enables else None

        # ADR-0058 §論点 10: function-call trigger は MVP では未実装
        if trigger_block is not None and trigger_block.trigger_type == "function-call":
            raise NotImplementedError(
                f"Subsystem {self.id!r}: Trigger.trigger_type='function-call' is "
                f"not implemented in MVP (ADR-0058 §論点 10). Use 'rising' / "
                f"'falling' / 'either' for edge-driven triggers."
            )

        self._trigger_block = trigger_block
        self._enable_block = enable_block
        self._has_trigger = trigger_block is not None
        self._has_enable = enable_block is not None
        self._n_data_inports = len(inports)
        # 外部 u 配列の slot index ([data..., enable, trigger] 順、ADR-0058 §論点 4)
        if self._has_enable:
            self._enable_slot_idx = self._n_data_inports
        else:
            self._enable_slot_idx = None
        if self._has_trigger:
            offset = 1 if self._has_enable else 0
            self._trigger_slot_idx = self._n_data_inports + offset
        else:
            self._trigger_slot_idx = None

        # port_idx の重複・抜けチェック (= 連番 [0..N-1])
        n_in = len(inports)
        n_out = len(outports)
        in_indices = sorted(p.port_idx for p in inports)
        if in_indices != list(range(n_in)):
            raise BlockSpecError(
                f"Subsystem {self.id!r}: Inport port_idx values {in_indices} "
                f"do not cover [0, {n_in})"
            )
        out_indices = sorted(p.port_idx for p in outports)
        if out_indices != list(range(n_out)):
            raise BlockSpecError(
                f"Subsystem {self.id!r}: Outport port_idx values {out_indices} "
                f"do not cover [0, {n_out})"
            )

        self._inports_by_idx = {p.port_idx: p for p in inports}
        self._outports_by_idx = {p.port_idx: p for p in outports}

        # ネスト Subsystem の内部 build を先に発火 (direct_feedthrough 推論や n_states
        # の確定が外側から正しく見えるようにする)。code-reviewer MUST #2 修正。
        for b in self._inner_blocks:
            inner_build = getattr(b, "_build", None)
            if callable(inner_build):
                inner_build()

        # SPEC-0030 (v0.58.0): Subsystem 内部の離散専用ブロック
        # (requires_discrete_rate=True) の同期系 sample_time (-1 / "dt") は
        # fail-closed に拒否する。内部にはクロック解決が走らないため (既知制限、
        # ADR-0014)、これらは派生 sample_time 計算で連続と誤分類され、離散専用
        # ブロックが無警告凍結する (v0.57.0 で修正したバグのネスト版)。
        # requires_discrete_rate=False (無状態・デコレータ製ポリモーフィック) の
        # -1 は「連続として動く」が正当な意味を持つため従来どおり許す (ルート
        # レベルの解決規則と同じ線引き — code-reviewer SHOULD 2026-09-11)。
        # なお無状態の "dt" は内部ではレート源にならない (解決が走らないため)
        # 点だけルートと非対称だが、無害 (何も発火しない) なので拒否しない。
        for b in self._inner_blocks:
            st_inner = b.sample_time
            if b.requires_discrete_rate and (
                st_inner == BASE_CLOCK_SAMPLE_TIME
                or st_inner == -1.0
                # security MUST-2 (2026-09-11): 0 / None も連続誤分類 → 凍結経路
                or st_inner is None
                or st_inner == 0.0
            ):
                raise BlockSpecError(
                    f"Subsystem {self.id!r}: inner block {b.id!r} has "
                    f"sample_time={st_inner!r}. Discrete-only blocks inside a "
                    "Subsystem require an explicit positive period in this "
                    f"release (synced values -1.0 / {BASE_CLOCK_SAMPLE_TIME!r} "
                    "are unsupported here, and 0/None would silently freeze)."
                )
            # bug-fix 2026-09-13: 状態を持たない Triggered Subsystem はルートでは
            # 基準クロック ("dt") で update される (下記 sample_time 継承参照) が、
            # Subsystem 内部ではクロック解決が走らず ``_discrete_slices`` (n_states
            # > 0) にも入らないため一度も発火しない。無警告凍結を避けて fail-closed。
            if isinstance(b, Subsystem) and b._has_trigger and b.n_states == 0:
                raise BlockSpecError(
                    f"Subsystem {self.id!r}: inner Triggered Subsystem {b.id!r} has no "
                    "internal state, so it would never fire when nested (inner clock "
                    "resolution is not supported in this release). Place it at the "
                    "root level, or give it an explicit-rate discrete block inside."
                )
        # bug-fix 2026-09-13: 内部ブロックの ``_resolved_sample_time`` をここで確定
        # する。``Simulator._resolve_sample_times`` はルート直下しか走らないため、
        # update() / output() で解決済み周期を要求するブロック (DiscreteIntegrator /
        # RateLimiter / ZeroOrderHoldDirect 等) が Subsystem 内で
        # "sample_time has not been resolved" になっていた。上の拒否で同期系
        # (-1 / "dt") の離散専用ブロックは除外済みなので、数値周期はそのまま、
        # それ以外 (連続 / 無状態の -1・"dt") は連続として確定できる。
        for b in self._inner_blocks:
            st_inner = b.sample_time
            if (
                isinstance(st_inner, (int, float))
                and not isinstance(st_inner, bool)
                and st_inner > 0.0
            ):
                b._resolved_sample_time = float(st_inner)
            else:
                b._resolved_sample_time = None

        # Phase 2 では Subsystem 内部の連続+離散混在を拒否する
        # (code-reviewer MUST #1 修正: Phase 3 で外部スケジューラとの統合を再設計)。
        cont_states = [
            b
            for b in self._inner_blocks
            if b.n_states > 0 and (b.sample_time is None or b.sample_time == 0.0)
        ]
        disc_states = [
            b
            for b in self._inner_blocks
            # -1 / "dt" は上の拒否で除外済み → ここに来る非 None は数値のみ
            if b.n_states > 0 and isinstance(b.sample_time, (int, float)) and b.sample_time > 0.0
        ]
        if cont_states and disc_states:
            raise BlockSpecError(
                f"Subsystem {self.id!r}: mixing continuous-state and discrete-state "
                f"blocks inside one Subsystem is not supported in Phase 2. "
                f"Continuous: {[b.id for b in cont_states]}, "
                f"Discrete: {[b.id for b in disc_states]}. "
                f"Split into separate Subsystems or wait for Phase 3."
            )
        # code-reviewer MUST (2026-09-13): Subsystem.update() は内部の離散ブロックを
        # 親の周期 (= 内部最小周期) で一括 update するため、周期の異なる離散
        # ブロックが混在すると遅い方が速い周期で更新され無警告で誤った結果になる
        # (内部ブロック単位の step_ratio ゲートは未実装、ADR-0014 既知制限)。
        # 従来は DiscreteIntegrator 等が "sample_time not resolved" で落ちていた
        # ので顕在化しなかった。fail-closed に拒否する。
        disc_rates = sorted({float(b.sample_time) for b in disc_states})  # type: ignore[arg-type]
        if len(disc_rates) > 1:
            raise BlockSpecError(
                f"Subsystem {self.id!r}: inner discrete blocks with different sample_time "
                f"{disc_rates} are not supported in this release (a Subsystem updates all "
                "inner discrete blocks at its fastest inner rate; per-block step-ratio "
                "gating is not implemented). Use a single rate inside the Subsystem, or "
                "split rates into separate Subsystems with RateTransition at root."
            )

        # トポロジカル順 (direct_feedthrough のみ依存辺)
        self._exec_order = self._compute_exec_order()
        # bug-fix (2026-09-08): シリアライズ目的の build 区間では PythonFunction の
        # exec が skip され「不完全な built 状態」になりうるため、build 済み
        # キャッシュを次の実行時 build で完全再構築させる。無効化は最外区間の
        # 終了時にまとめて行う (即時無効化はネスト時に build 回数が指数化 —
        # code-reviewer MUST)。登録はキャッシュが立った**直後**に行う: この後の
        # _build 処理 (例: _params 確定の to_dict) が例外で中断しても登録済みで
        # あることを保証する (save 失敗後にモデルが実行不能で残る回帰の防止 —
        # security-reviewer MUST-1)。
        if in_serialization_build():
            register_serialization_invalidation(lambda: setattr(self, "_exec_order", None))

        # 状態 layout 計算
        offset = 0
        for b in self._inner_blocks:
            if b.n_states > 0:
                sl = slice(offset, offset + b.n_states)
                self._state_slices.append((b, sl))
                # 連続+離散混在は上で拒否済みなので片方のみ
                if b.sample_time is None or b.sample_time == 0.0:
                    self._continuous_slices.append((b, sl))
                else:
                    self._discrete_slices.append((b, sl))
                offset += b.n_states
        self.n_states = offset
        # x0 を組み立て
        x0 = np.zeros(offset)
        for b, sl in self._state_slices:
            x0[sl] = np.asarray(b.x0, dtype=float)
        self.x0 = x0

        # bug-fix 2026-09-13: Enable-only で連続内部状態を持つ Subsystem は
        # Simulator から update() が呼ばれない (連続ブロックとして layout される)
        # ため、enable false→true 遷移の検出 = ``states_when_enabling="reset"`` が
        # 一度も発火せず、無警告で "held" と同じ挙動になっていた。連続状態の
        # 境界リセットはスケジューラ側の仕組み (ステップ境界 hook) が必要なので、
        # 設計対応までは fail-closed に拒否する。
        if (
            self._has_enable
            and not self._has_trigger
            and self._enable_block is not None
            and self._enable_block.states_when_enabling == "reset"
            and self._continuous_slices
        ):
            raise BlockSpecError(
                f"Subsystem {self.id!r}: Enable(states_when_enabling='reset') is not "
                "supported when the subsystem holds continuous states "
                f"({[b.id for b, _ in self._continuous_slices]}): the reset transition "
                "is never detected for continuous-state subsystems in this release. "
                "Use states_when_enabling='held', or discrete inner blocks."
            )

        # direct_feedthrough を内部 Inport→Outport 経路から推論 (LO-A)
        self.direct_feedthrough = self._infer_direct_feedthrough(inports, outports)
        # ADR-0058 §論点 11 / 旧 TriggeredSubsystem._build と同じく、Trigger 付き
        # Subsystem は出力が「前回 fire 時の _last_y キャッシュ」になるため、内部の
        # 直達経路に関係なく外側からは非直達。Simulator のトポロジカルソートが
        # 誤って direct_feedthrough=True と扱うと代数ループ誤検知や順序ミスを
        # 起こすため、推論結果を強制 False に書き換える。
        if self._has_trigger:
            self.direct_feedthrough = False
        # bug-fix 2026-09-13: Enabled Subsystem の enable ポートは、データ経路が
        # 非直達でも output() 時点で読む必要がある (無効中の出力ポリシー判定)。
        # そのポートだけを制御入力として宣言し、Simulator / 親 Subsystem の
        # スケジューラがパス 1 で値を組み立てる (データ経路は非直達のまま =
        # 自身の出力をデータ入力に戻すループは代数ループにならない)。
        if self._has_enable and self._enable_slot_idx is not None:
            self.control_input_ports = (self._enable_slot_idx,)
        else:
            self.control_input_ports = ()

        # sample_time 継承 (ST-A): 内部の最小サンプル時間
        sample_times = [
            float(b.sample_time)
            for b in self._inner_blocks
            if isinstance(b.sample_time, (int, float)) and b.sample_time > 0.0
        ]
        if sample_times:
            self.sample_time = min(sample_times)
        elif self._has_trigger and self.n_states == 0:
            # bug-fix 2026-09-13: 内部に状態も離散レートもない Triggered Subsystem
            # (純粋なサンプル & ホールド) は基準クロック ("dt") で update() を受け、
            # trigger の edge を毎基準ステップ判定する (従来は連続扱いで update()
            # が呼ばれず発火しなかった)。連続内部状態のみを持つ Triggered
            # Subsystem は従来どおり連続分類のまま (fire しても連続状態は更新され
            # ない既知の制限、ADR-0058 §論点 6)。
            self.sample_time = BASE_CLOCK_SAMPLE_TIME

        # save/load 用 params の確定
        # bug-fix 2026-09-13: 永続化できない内部ブロック (``@block`` で __main__ に
        # 定義したユーザーブロック等) があっても **実行は妨げない**。to_dict は
        # save 時 (``Subsystem.to_dict``) に改めて計算され、そこで
        # ModelSerializationError が利用者に届く。従来は build 時点で例外になり、
        # Subsystem に入れただけで run() すらできなかった。
        try:
            self._params["blocks"] = [b.to_dict() for b in self._inner_blocks]
        except ModelSerializationError as exc:
            if in_serialization_build():
                # save 経路 (Subsystem.to_dict → _build) では利用者に即座に届ける
                raise
            _logger.debug(
                "Subsystem %r: inner block params not cached at build (%s); "
                "save() will raise the same error",
                self.id,
                exc,
            )
            self._params.pop("blocks", None)
        self._params["connections"] = self._serialize_inner_connections()

        # ADR-0058: control block hot-path で参照する出力キャッシュを build 末尾で
        # 初期化。n_outputs は派生 property なので、ここで確定値が取れる。
        # Trigger / Enable を持たない Subsystem では output() の既存 hot-path が
        # _last_y を参照しないので、初期化しても数値挙動への影響はない (= 数値
        # 完全不変ガード、既存テストへの影響なし)。
        if self._last_y is None or self._last_y.shape != (self.n_outputs,):
            self._last_y = np.zeros(self.n_outputs)

    def reset(self) -> None:
        """``Simulator.run()`` 開始時の lifecycle hook (run 間の再現性、bug-fix 2026-09-13)。

        Trigger / Enable の前ステップ値 (NaN sentinel) と出力キャッシュを初期状態に
        戻し、内部ブロックの ``reset()`` (RandomSource の RNG、Relay の x0、
        入れ子 Subsystem 等) にも伝搬する。これが無いと同じ ``Simulator`` の 2 回目の
        ``run()`` が前回の最終状態から edge 判定を始め、結果が初回と一致しなかった。
        """
        self._prev_trigger_value = float("nan")
        self._prev_enable_value = float("nan")
        if self._last_y is not None:
            self._last_y = np.zeros(self.n_outputs)
        for b in self._inner_blocks:
            inner_reset = getattr(b, "reset", None)
            if callable(inner_reset):
                inner_reset()

    def _compute_exec_order(self) -> list[Block]:
        """内部 direct_feedthrough 依存に基づくトポロジカル順 (代数ループ検出付き)。"""
        deps: dict[Block, set[Block]] = {b: set() for b in self._inner_blocks}
        rev: dict[Block, set[Block]] = defaultdict(set)
        for b in self._inner_blocks:
            if b.direct_feedthrough:
                for src in b.input_sources:
                    if src is not None:
                        deps[b].add(src[0])
                        rev[src[0]].add(b)
            else:
                # bug-fix 2026-09-13: 制御入力ポート (入れ子 Enabled Subsystem の
                # enable) だけを直達辺として扱う (Simulator._execution_order と同じ)
                for i in b.control_input_ports:
                    src = b.input_sources[i]
                    if src is not None:
                        deps[b].add(src[0])
                        rev[src[0]].add(b)
        # ADR-0055 §論点 5-A: Goto/From 仮想エッジ展開で外部 (Simulator) から
        # 追加された内部 deps を merge。``_virtual_inner_deps`` は
        # ``Simulator._resolve_goto_from_virtual_edges`` が populate するが、
        # 同 ``_compute_exec_order`` が呼ばれる時点で空 set かもしれない
        # (= Goto/From を含まない Subsystem、または再ビルド前の初回 build)。
        # 後者は外部 trigger ``sub._exec_order = None`` で再 build される。
        # 変数名 ``vdep_src`` は上の ``src`` (= ``tuple[Block, int] | None``) との
        # 名前衝突 / 型再推論衝突を避けるため (mypy --strict 対策)。
        for vdep_dst, vdep_src in self._virtual_inner_deps:
            if vdep_dst in deps and vdep_src in deps:
                deps[vdep_dst].add(vdep_src)
                rev[vdep_src].add(vdep_dst)
        ready: deque[Block] = deque(b for b in self._inner_blocks if not deps[b])
        order: list[Block] = []
        while ready:
            b = ready.popleft()
            order.append(b)
            for child in rev[b]:
                deps[child].discard(b)
                if not deps[child]:
                    ready.append(child)
        if len(order) != len(self._inner_blocks):
            remaining = [b.id for b in self._inner_blocks if b not in order]
            raise AlgebraicLoopError(f"Algebraic loop inside Subsystem {self.id!r}: {remaining}")
        return order

    def _infer_direct_feedthrough(self, inports: list[Inport], outports: list[Outport]) -> bool:
        """各 Inport から各 Outport に到達する direct_feedthrough 経路があるかを判定。

        グラフ走査で「direct_feedthrough=True のブロックのみを辿って Outport に
        到達できる Inport が 1 つでもあるか」を評価する。1 つでもあれば True。
        """
        # 隣接リスト (direct_feedthrough=True のブロックのみ辺を持つ)
        # _build 時点で全ブロックは Simulator/Subsystem 経由で id 採番済みなので
        # b.id は非 None 文字列に narrow できる
        adj: dict[str, list[str]] = defaultdict(list)
        for b in self._inner_blocks:
            if isinstance(b, Outport):
                continue  # Outport は端点
            if not b.direct_feedthrough and not isinstance(b, Inport):
                continue  # 非直達ブロックでチェーン切れ
            assert b.id is not None
            for dst in self._inner_blocks:
                assert dst.id is not None
                for _dst_idx, src in enumerate(dst.input_sources):
                    if src is None:
                        continue
                    if src[0] is b:
                        adj[b.id].append(dst.id)
        # bug-fix 2026-09-13: Goto → From の仮想配線も直達辺として辿る
        # (ADR-0055 §論点 5-A の deps と同じ対)。これが無いと「Inport → Goto /
        # From → Outport」の Subsystem が非直達と誤判定され、パス 1 で入力ゼロの
        # まま Goto が値を記録して From が 0 を読んでいた。
        for vdep_dst, vdep_src in self._virtual_inner_deps:
            if vdep_src.id is not None and vdep_dst.id is not None and vdep_src.direct_feedthrough:
                adj[vdep_src.id].append(vdep_dst.id)
        # 到達目標 = Outport + 外部から参照される Goto (またはそれを含む直達な
        # 内側 Subsystem)。Goto 自体は n_outputs=0 なので到達すれば終端。
        from ..blocks.routing import Goto

        target_ids: set[str] = {o.id for o in outports if o.id is not None}
        for extra in self._df_extra_targets:
            if extra.id is not None and (isinstance(extra, Goto) or extra.direct_feedthrough):
                target_ids.add(extra.id)
        for inp in inports:
            assert inp.id is not None
            visited: set[str] = set()
            stack: list[str] = [inp.id]
            while stack:
                cur = stack.pop()
                if cur in visited:
                    continue
                visited.add(cur)
                if cur in target_ids:
                    return True
                for next_id in adj.get(cur, []):
                    if next_id not in visited:
                        stack.append(next_id)
        return False

    def _serialize_inner_connections(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for b in self._inner_blocks:
            for dst_idx, src in enumerate(b.input_sources):
                if src is None:
                    continue
                src_block, src_idx = src
                out.append(
                    {
                        "src": src_block.id,
                        "src_idx": int(src_idx),
                        "dst": b.id,
                        "dst_idx": int(dst_idx),
                    }
                )
        return out

    # ---------- マスクパラメータ (ADR-0021) ----------

    def _init_mask_values(self, explicit: dict[str, Any] | None) -> dict[str, Any]:
        """``mask_params`` のデフォルトと明示指定 ``explicit`` を merge する。

        宣言 ``mask_params`` が ``None`` のとき:
          - ``explicit`` も空 / None なら空 dict を返す
          - ``explicit`` に値があれば ``BlockSpecError`` (= 宣言なしに値を渡すのは
            silent ignore よりエラーが安全。ADR-0021 code-reviewer MUST 修正)
        """
        if not self.mask_params:
            if explicit:
                raise BlockSpecError(
                    f"Subsystem {self.id!r}: mask_values provided ({sorted(explicit)}) "
                    f"but mask_params is not declared"
                )
            return {}
        out: dict[str, Any] = {}
        for spec in self.mask_params:
            out[spec["name"]] = spec.get("default")
        if explicit:
            for name, value in explicit.items():
                if name not in out:
                    raise BlockSpecError(
                        f"Subsystem {self.id!r}: mask_values key {name!r} is not "
                        f"declared in mask_params (declared: {sorted(out)})"
                    )
                out[name] = value
        return out

    def set_mask_value(self, name: str, value: Any) -> None:
        """マスク値を更新し、次回 ``_build`` で再 resolve させる (ADR-0021 §(6))。"""
        if not self.mask_params:
            raise BlockSpecError(f"Subsystem {self.id!r} has no mask_params declared")
        if name not in {p["name"] for p in self.mask_params}:
            raise BlockSpecError(f"Subsystem {self.id!r}: unknown mask name {name!r}")
        self.mask_values[name] = value
        self._exec_order = None  # 次 build で resolve を再実行させる

    def _resolve_mask_placeholders(self) -> None:
        """``_unresolved_params`` を持つ内部 block を ``mask_values`` で再 resolve する。

        ``_from_dict`` 経路 (= JSON load) で初回構築された inner block には、その時の
        original placeholder params が ``_unresolved_params`` として保存される。
        ``set_mask_value`` で値が変わった後の ``_build`` で本メソッドが呼ばれ、新値
        で再度 substitute → 同 type / 同 id で block を再生成する。再生成後は **他の
        block の ``input_sources`` のうち旧 block を参照するエントリを新 block に
        差し替える** ことで配線参照の整合性を保つ (= dangling reference 防止)。

        port_shape が変わる placeholder は ADR-0017 静的宣言を破壊するため
        ``BlockSpecError``。``_unresolved_params`` を持たない block (= 通常 block /
        placeholder 未使用) は no-op。
        """
        if not self.mask_params:
            return  # マスクなし Subsystem は no-op
        replacements: dict[Block, Block] = {}
        for i, b in enumerate(self._inner_blocks):
            unresolved = getattr(b, "_unresolved_params", None)
            if unresolved is None:
                continue  # placeholder を持たない通常 block
            new_params = substitute_placeholders(unresolved, self.mask_values)
            if new_params == b._params:
                continue  # 既に同値で resolve 済 (= 初回 _from_dict 直後)
            try:
                # bug-fix 2026-09-13: 入れ子 Subsystem は ``_from_dict`` factory で
                # 再構築する (``_from_dict`` 側の再帰対応と対にする。素の
                # ``__init__`` は内側 blocks の dict を受け付けない)
                rebuild_factory = getattr(type(b), "_from_dict", None)
                new_block: Block
                if callable(rebuild_factory):
                    new_block = rebuild_factory(**new_params)
                else:
                    new_block = type(b)(**new_params)
            except (TypeError, ValueError, BlockSpecError) as e:
                raise BlockSpecError(
                    f"Subsystem {self.id!r}: cannot rebuild inner block {b.id!r} "
                    f"after mask resolve (params={new_params!r}): {e}"
                ) from e
            if (
                new_block.port_shapes_in != b.port_shapes_in
                or new_block.port_shapes_out != b.port_shapes_out
            ):
                raise BlockSpecError(
                    f"Subsystem {self.id!r}: mask resolve changed port_shape for "
                    f"inner block {b.id!r} (placeholder cannot change port shape, "
                    f"ADR-0017 static port_shape declaration). Move structural "
                    f"variation out to a variant subsystem (Phase 4+)."
                )
            new_block.id = b.id
            new_block._unresolved_params = dict(unresolved)  # type: ignore[attr-defined]
            new_block.input_sources = list(b.input_sources)
            assert b.id is not None  # _build 段階では id は確定済み
            self._inner_blocks_by_id[b.id] = new_block
            self._inner_blocks[i] = new_block
            replacements[b] = new_block
        if not replacements:
            return
        # 他の block の input_sources のうち旧 block を参照するエントリを新 block に
        # 差し替える。これをやらないと _compute_exec_order が依存解決できず
        # AlgebraicLoopError になる (= dangling reference)。
        for b in self._inner_blocks:
            for idx, src in enumerate(b.input_sources):
                if src is None:
                    continue
                src_block, src_idx = src
                if src_block in replacements:
                    b.input_sources[idx] = (replacements[src_block], src_idx)

    # ---------- Block 契約の実装 (内部ランタイム委譲) ----------

    def _step_inner(
        self, t: float, x: npt.NDArray[Any], u_external: npt.NDArray[Any]
    ) -> tuple[dict[Block, npt.NDArray[Any]], dict[Block, npt.NDArray[Any]]]:
        """内部の 2 パス出力計算 (``Simulator._step`` の縮小版)。

        外部 ``u_external[port_idx]`` を Inport の ``_external_value`` に注入してから
        実行する。

        ADR-0039: ``self._inports_by_idx`` (= 内部 Inport のみ、TriggeredSubsystem の
        trigger slot は含まない) でループすることで、``u_external`` の長さが
        ``n_inputs`` と一致しないケース (= TriggeredSubsystem が trigger 入力を
        除いた ``u_data`` を渡してくる) でも IndexError にならない。

        Returns:
            ``(outputs, inputs)``: 各内部ブロックの出力と入力ベクトル。
        """
        for port_idx, inport in self._inports_by_idx.items():
            # ADR-0017 SM-B: port_shape != () の Inport (= ベクトルポート) は本来
            # ndarray を ``_external_value`` に注入する必要がある。Phase 5b 時点では
            # SM-A path (scalar) しか実装されていないため、SM-B Inport は
            # ``_step_inner`` 経由では未対応 (= ADR-0018 §(5) 既知制限、別途
            # ``Subsystem.run()`` で BlockSpecError)。
            inport._external_value = float(u_external[port_idx])

        # 内部状態を slice ごとに取り出す
        cont_state = {b: x[sl] for b, sl in self._state_slices}

        outputs: dict[Block, npt.NDArray[Any]] = {}
        inputs: dict[Block, npt.NDArray[Any]] = {}

        def state_for(b: Block) -> npt.NDArray[Any]:
            return cont_state.get(b, np.zeros(0))

        assert self._exec_order is not None
        for b in self._exec_order:
            # ADR-0058 §論点 2 (SHOULD 2): Trigger / Enable は宣言的境界ブロックで、
            # 内部の output / input dataflow には参加しない。明示的に skip して
            # ``outputs`` 辞書に entry を作らない (= 内部接続から参照されない保証)。
            if isinstance(b, (Trigger, Enable)):
                continue
            if b.direct_feedthrough:
                u = np.zeros(b.n_inputs)
                for i, src in enumerate(b.input_sources):
                    if src is not None:
                        sb, si = src
                        u[i] = outputs[sb][si]
                inputs[b] = u
            else:
                u = np.zeros(b.n_inputs)
                # bug-fix 2026-09-13: 制御入力ポートだけは output() 前に埋める
                for i in b.control_input_ports:
                    src = b.input_sources[i]
                    if src is not None:
                        sb, si = src
                        u[i] = outputs[sb][si]
            xb = state_for(b)
            y = np.atleast_1d(np.asarray(b.output(t, xb, u), dtype=float))
            outputs[b] = y
        for b in self._exec_order:
            if not b.direct_feedthrough:
                u = np.zeros(b.n_inputs)
                for i, src in enumerate(b.input_sources):
                    if src is not None:
                        sb, si = src
                        u[i] = outputs[sb][si]
                inputs[b] = u
        return outputs, inputs

    # ---------- ADR-0058 hot-path helpers (control block を持つ Subsystem 用) ----------

    def _is_enabled(self, u: npt.NDArray[Any]) -> bool:
        """``u[enable_slot_idx]`` を読んで enable 状態を返す。Enable なしなら常に True。

        ADR-0058 §エッジケース: NaN は無効化扱い (= safe fallback)。
        """
        if not self._has_enable:
            return True
        assert self._enable_slot_idx is not None
        val = float(u[self._enable_slot_idx])
        if math.isnan(val):
            return False
        return val > 0.0

    def _compute_y_from_outputs(self, outputs: dict[Block, npt.NDArray[Any]]) -> npt.NDArray[Any]:
        """内部 ``outputs`` 辞書から Outport を集めて y ベクトルを作る。"""
        y = np.zeros(self.n_outputs)
        for port_idx in range(self.n_outputs):
            outport = self._outports_by_idx[port_idx]
            src = outport.input_sources[0]
            if src is not None:
                sb, si = src
                y[port_idx] = outputs[sb][si]
        return y

    # ---------- Block 契約: output / derivative / update ----------

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        self._build()
        # ADR-0058 §論点 14 数値完全不変ガード: Trigger / Enable を持たない Subsystem
        # は既存 hot-path をそのまま通る (= 既存テスト 949+ 件の数値が bit 単位で
        # 変化しないことを保証)。
        if not (self._has_trigger or self._has_enable):
            outputs, _inputs = self._step_inner(t, x, u)
            return self._compute_y_from_outputs(outputs)

        # 制御ブロック付き hot-path。_last_y は build 直後に初期化。
        if self._last_y is None:
            self._last_y = np.zeros(self.n_outputs)

        enabled = self._is_enabled(u)
        if not enabled:
            # ADR-0058 §論点 5: disable 中の出力ポリシー
            assert self._enable_block is not None
            if self._enable_block.outputs_when_disabled == "reset":
                return np.zeros(self.n_outputs)
            return np.asarray(self._last_y, dtype=float)

        if self._has_trigger:
            # Trigger-driven (enable 真のときも): _last_y キャッシュを返す
            # (= update() で fire 時に更新される、旧 TriggeredSubsystem.output と同等)
            return np.asarray(self._last_y, dtype=float)

        # Enable-only かつ enabled: 通常 Subsystem として現在 state から計算。
        # ADR-0058 §論点 2 MUST 2: Simulator の 2-pass output 計算 (= ADR-0014 [A]
        # phase) は 1 step 内で複数回 ``output()`` を呼ぶ可能性がある。内部 state
        # を変えない設計 (``update()`` のみが state を進める) のため、``_step_inner``
        # 再実行は idempotent (内部ブロックの ``output()`` も状態を変えない)。
        # 余計な計算コストはあるが、副作用ゼロで仕様通り。
        u_data = u[: self._n_data_inports]
        outputs, _inputs = self._step_inner(t, x, u_data)
        y = self._compute_y_from_outputs(outputs)
        # _last_y を更新: 次に disable に遷移したとき "held" policy で返す値の cache
        self._last_y = y
        return y

    def derivative(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        self._build()
        if self.n_states == 0:
            return np.zeros(0)
        # ADR-0058 §論点 14 数値完全不変ガード
        if not (self._has_trigger or self._has_enable):
            _outputs, inputs = self._step_inner(t, x, u)
            xdot = np.zeros(self.n_states)
            for b, sl in self._continuous_slices:
                xdot[sl] = np.asarray(
                    b.derivative(t, x[sl], inputs.get(b, np.zeros(b.n_inputs))),
                    dtype=float,
                )
            return xdot

        # ADR-0058 §論点 6: Enable=false / Trigger fire 外は derivative=0 で凍結
        # (= solve_ivp は積分継続するが dx/dt=0 で実質的に state を固定)。
        enabled = self._is_enabled(u)
        if not enabled:
            return np.zeros(self.n_states)
        if self._has_trigger:
            # Trigger 駆動: ADR-0036 §(4-C) 踏襲、fire 外は derivative=0 で凍結
            # (= 連続状態を持つ場合は warning が _build 後に 1 度出る別経路で対応)
            return np.zeros(self.n_states)

        # Enable-only かつ enabled: 通常 Subsystem として derivative を計算
        u_data = u[: self._n_data_inports]
        _outputs, inputs = self._step_inner(t, x, u_data)
        xdot = np.zeros(self.n_states)
        for b, sl in self._continuous_slices:
            xdot[sl] = np.asarray(
                b.derivative(t, x[sl], inputs.get(b, np.zeros(b.n_inputs))),
                dtype=float,
            )
        return xdot

    def _advance_inner(self, t: float, x: npt.NDArray[Any]) -> npt.NDArray[Any]:
        """内部離散ブロックの ``advance`` (ADR-0078 シフト相) を state slice ごとに適用。"""
        x_adv = np.array(x, dtype=float, copy=True)
        for b, sl in self._discrete_slices:
            x_adv[sl] = np.asarray(b.advance(t, x[sl]), dtype=float)
        return x_adv

    def advance(self, t: float, x: npt.NDArray[Any]) -> npt.NDArray[Any]:
        """ADR-0078: 制御ブロックを持たない Subsystem は内部離散ブロックを再帰的に
        シフトする。Trigger / Enable 付きは発火するかどうかが ``update`` の中で
        しか分からないため、ここでは何もせず ``update`` の fire 経路で行う。"""
        self._build()
        if self.n_states == 0 or self._has_trigger or self._has_enable:
            return np.asarray(x, dtype=float)
        return self._advance_inner(t, x)

    def update(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        self._build()
        # ADR-0058 §論点 14 数値完全不変ガード
        if not (self._has_trigger or self._has_enable):
            if self.n_states == 0:
                return np.asarray(x, dtype=float)
            _outputs, inputs = self._step_inner(t, x, u)
            x_next: npt.NDArray[Any] = np.array(x, dtype=float, copy=True)
            for b, sl in self._discrete_slices:
                x_next[sl] = np.asarray(
                    b.update(t, x[sl], inputs.get(b, np.zeros(b.n_inputs))),
                    dtype=float,
                )
            return x_next

        # 制御ブロック付き hot-path
        if self._last_y is None:
            self._last_y = np.zeros(self.n_outputs)

        # Enable 状態の遷移検出 (false → true) と prev 更新。
        # ADR-0058 §論点 4 MUST 3: ``_prev_enable_value`` は NaN sentinel 初期化なので
        # 「初回ステップで enable=true から始まる」ケースでは ``prev_was_disabled=False``
        # となり ``enable_transition_to_true=False``。これは意図的設計で、Trigger の
        # 偽エッジ防止 (``_prev_trigger_value=NaN``) と対称的。起動直後は内部状態が
        # 既に x0 なので、reset policy 下でも追加の reset は不要 (= 余計な書き戻しを
        # 避けて数値的に冪等)。
        enable_transition_to_true = False
        if self._has_enable:
            assert self._enable_slot_idx is not None and self._enable_block is not None
            curr_en = float(u[self._enable_slot_idx])
            prev_en = self._prev_enable_value
            curr_enabled = (not math.isnan(curr_en)) and curr_en > 0.0
            prev_was_disabled = (not math.isnan(prev_en)) and prev_en <= 0.0
            enable_transition_to_true = curr_enabled and prev_was_disabled
            self._prev_enable_value = curr_en
        else:
            curr_enabled = True

        # Trigger edge 検出と prev 更新 (旧 TriggeredSubsystem.update と同じ semantics)
        if self._has_trigger:
            assert self._trigger_slot_idx is not None and self._trigger_block is not None
            curr_trig = float(u[self._trigger_slot_idx])
            edge = is_trigger_edge(
                self._prev_trigger_value, curr_trig, self._trigger_block.trigger_type
            )
            self._prev_trigger_value = curr_trig
        else:
            edge = False

        # ADR-0058 §論点 4: state reset on enable false→true 遷移 (policy: reset)
        if (
            enable_transition_to_true
            and self._enable_block is not None
            and self._enable_block.states_when_enabling == "reset"
        ):
            x = np.array(self.x0, dtype=float, copy=True)

        # Fire 条件 (ADR-0058 §論点 9: edge AND enable):
        # - Trigger + Enable: enabled and edge
        # - Trigger only: edge
        # - Enable only: enabled (level-driven、毎ステップ fire)
        if self._has_trigger and self._has_enable:
            fire = curr_enabled and edge
        elif self._has_trigger:
            fire = edge
        else:  # has_enable only
            fire = curr_enabled

        if not fire:
            # 凍結 (state reset があった場合はその x を返す、なければ受信 x をそのまま)
            return np.asarray(x, dtype=float)

        # Fire: 内部離散ブロックをシフト (ADR-0078、ルートで advance を呼ばない分を
        # ここで行う) → 内部 step を実行し _last_y を更新
        if self.n_states > 0:
            x = self._advance_inner(t, x)
        u_data = u[: self._n_data_inports]
        outputs, inputs = self._step_inner(t, x, u_data)
        self._last_y = self._compute_y_from_outputs(outputs)
        if self.n_states == 0:
            return np.asarray(x, dtype=float)
        x_next = np.array(x, dtype=float, copy=True)
        for b, sl in self._discrete_slices:
            x_next[sl] = np.asarray(
                b.update(t, x[sl], inputs.get(b, np.zeros(b.n_inputs))),
                dtype=float,
            )
        return x_next

    # ---------- 永続化サポート ----------

    def to_dict(self) -> dict[str, Any]:
        """``Block.to_dict`` を override して内部 ``blocks``/``connections`` をネスト。

        ADR-0039: ``n_inputs`` / ``n_outputs`` / ``port_shapes_in`` /
        ``port_shapes_out`` は **派生 property** のため、JSON には保存しない
        (= 内部 ``Inport`` / ``Outport`` から復元される SSOT)。

        ADR-0020 §Decision (1)(5): 内部 GUI レイアウトを ``params.layout`` に
        再帰的に保存する。``self.layout is None`` または空のときは出力しない (=
        layout を持たない既存 Subsystem の JSON は完全互換)。stale id (= 削除済み
        block を参照) は drop。

        Note (bug-fix 2026-09-08): 本メソッド全体を ``serialization_build()``
        区間で囲み、ネスト PythonFunction のユーザーコード exec を抑止する
        (save しただけでコードが走る問題の修正。整合性チェックは従来どおり)。
        抑止 build 直後は ``x0`` / ``n_states`` 等の派生値が静的既定に落ちるが、
        次の実行時 build で復元される (run の数値は不変)。
        """
        from ..core.persistence import block_type_path

        # 区間はメソッド全体: _build だけでなく子の to_dict 再帰も含めて
        # 「serialize パスで exec しない」を構造的に保証する (security-reviewer
        # SHOULD-1)。ネストした子の to_dict の区間は素通しでコスト増なし。
        with serialization_build():
            # 内部 build を発火させ、内部構造の整合性チェック (BlockSpecError /
            # AlgebraicLoopError) を save 時にも走らせる。不完全な Subsystem は
            # 素直に保存できないので例外がそのまま伝播する設計。
            self._build()
            params: dict[str, Any] = {}
            # ADR-0021 §(7): mask_params / mask_values を canonical 順序で出力
            if self.mask_params:
                params["mask_params"] = [dict(p) for p in self.mask_params]
                # mask_values は declared 順で並べる (= diff の安定化)
                params["mask_values"] = {
                    p["name"]: self.mask_values[p["name"]] for p in self.mask_params
                }
            params["blocks"] = [b.to_dict() for b in self._inner_blocks]
            params["connections"] = self._serialize_inner_connections()
            if self.layout:
                inner_ids = {b.id for b in self._inner_blocks}
                ordered_layout: LayoutDict = {
                    b.id: self.layout[b.id] for b in self._inner_blocks if b.id in self.layout
                }
                stale = [k for k in self.layout if k not in inner_ids]
                for s in stale:
                    _logger.warning(
                        "Subsystem %r.to_dict: layout entry %r refers to unknown "
                        "inner block id; dropping",
                        self.id,
                        s,
                    )
                if ordered_layout:
                    params["layout"] = ordered_layout
            return {
                "id": self._id,
                "type": block_type_path(self.__class__),
                "params": params,
            }

    @classmethod
    def _from_dict(
        cls,
        *,
        blocks: list[Any],
        connections: list[dict[str, Any]],
        id: str | None = None,
        layout: LayoutDict | None = None,
        mask_params: list[dict[str, Any]] | None = None,
        mask_values: dict[str, Any] | None = None,
        **legacy_kwargs: Any,
    ) -> Subsystem:
        """JSON load 時の factory (ADR-0009 §(7) / ADR-0039 で n_inputs/n_outputs 廃止)。

        ``blocks`` の各要素は ``dict`` (= JSON から読んだ block entry) または
        ``Block`` インスタンス。``dict`` なら ``resolve_block_class`` で class を解決
        して再構築し、内部に ``add`` する。

        ADR-0039: ``n_inputs`` / ``n_outputs`` / ``port_shapes_in`` /
        ``port_shapes_out`` は派生 property になったため、JSON 上に存在していても
        ``legacy_kwargs`` で受け取って **読み捨てる** (= migration `_builtin_migrate_0_7_to_0_8`
        で削除されているはずだが、誤って残った場合の defensive)。
        """
        from ..core.persistence import resolve_block_class

        # ADR-0039: legacy フィールドを受けたら警告してから捨てる
        legacy_dropped = {
            k: legacy_kwargs.pop(k)
            for k in list(legacy_kwargs)
            if k in {"n_inputs", "n_outputs", "port_shapes_in", "port_shapes_out"}
        }
        if legacy_dropped:
            _logger.warning(
                "Subsystem %r._from_dict: dropping legacy schema 0.7 fields %s "
                "(now derived from inner Inport/Outport, ADR-0039)",
                id,
                sorted(legacy_dropped),
            )
        if legacy_kwargs:
            raise TypeError(
                f"Subsystem._from_dict: unexpected keyword arguments {sorted(legacy_kwargs)}"
            )

        sub = cls(
            id=id,
            layout=layout,
            mask_params=mask_params,
            mask_values=mask_values,
        )
        # ADR-0021 §(6): mask_values が宣言されている場合、内部 block の params に
        # 含まれる placeholder ($Kp 等) を resolve してから block を instantiate する。
        # JSON 上の placeholder 元形は ``_unresolved_params`` として block に保存され、
        # ``to_dict`` で round-trip される + ``set_mask_value`` 後の再 resolve で参照される。
        active_mask_values = sub.mask_values if sub.mask_params else None
        # ADR-0021 code-reviewer MUST 修正: 宣言と参照の整合性チェック
        # (= 未参照の宣言 / 未宣言の参照を warning ログで明示)
        if sub.mask_params:
            declared = {p["name"] for p in sub.mask_params}
            referenced: set[str] = set()
            for b in blocks:
                if isinstance(b, dict) and isinstance(b.get("params"), dict):
                    referenced |= collect_placeholder_names(b["params"])
            unused = declared - referenced
            undefined = referenced - declared
            if undefined:
                raise BlockSpecError(
                    f"Subsystem {id!r}: undefined mask placeholder(s) "
                    f"{sorted(undefined)} referenced in inner blocks "
                    f"(declared: {sorted(declared)})"
                )
            if unused:
                _logger.warning(
                    "Subsystem %r: declared mask_params %s are not referenced by any "
                    "inner block placeholder",
                    id,
                    sorted(unused),
                )
        for b in blocks:
            if isinstance(b, dict):
                block_cls = resolve_block_class(b["type"])
                raw_params: dict[str, Any] = dict(b["params"])
                if active_mask_values is not None:
                    resolved_params = substitute_placeholders(raw_params, active_mask_values)
                else:
                    resolved_params = raw_params
                # bug-fix 2026-09-13: 入れ子 Subsystem は ``_from_dict`` factory で
                # 再帰的に復元する (``Simulator.from_dict`` と同じ分岐)。直接
                # ``__init__`` に渡すと内側 blocks の dict が Block として拒否される。
                inner_factory = getattr(block_cls, "_from_dict", None)
                if callable(inner_factory):
                    instance = inner_factory(id=b["id"], **resolved_params)
                else:
                    instance = block_cls(id=b["id"], **resolved_params)
                # placeholder が含まれていた場合のみ ``_unresolved_params`` を保存
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
