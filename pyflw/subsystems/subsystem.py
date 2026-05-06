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
from collections import defaultdict, deque
from typing import Any

import numpy as np

from ..core.block import Block
from ..core.persistence import LayoutDict, normalize_layout
from ..exceptions import AlgebraicLoopError, BlockSpecError
from ._mask import (
    collect_placeholder_names,
    normalize_mask_params,
    substitute_placeholders,
)
from .ports import Inport, Outport

_logger = logging.getLogger("pyflw.subsystem")


class Subsystem(Block):
    """Atomic Subsystem: 内部に独自のブロック群と結線を持つ複合ブロック。

    Args:
        n_inputs: 外部入力ポート数。内部に同数の ``Inport(port_idx=i)`` を含むこと。
        n_outputs: 外部出力ポート数。内部に同数の ``Outport(port_idx=j)`` を含むこと。
        blocks: 内部ブロックのリスト (Inport / Outport を含む)。``None`` の場合は
            空 (``add()`` で追加)。
        connections: 内部結線のリスト ``[(src_id, dst_id, src_idx, dst_idx), ...]``。
            ``None`` の場合は ``connect()`` で追加。
        port_shapes_in: 各外部入力ポートの shape (ADR-0017 SM-B)。``None`` で全 ``()``
            (= SM-A scalar)。指定する場合は内部 ``Inport(port_idx=i)`` の port_shape と
            一致させること。
        port_shapes_out: 各外部出力ポートの shape (同上、内部 ``Outport`` と一致)。
    """

    def __init__(
        self,
        n_inputs: int,
        n_outputs: int,
        blocks: list[Block] | None = None,
        connections: list[dict[str, Any]] | None = None,
        *,
        id: str | None = None,
        name: str | None = None,
        port_shapes_in: tuple[tuple[int, ...], ...] | list[tuple[int, ...]] | None = None,
        port_shapes_out: tuple[tuple[int, ...], ...] | list[tuple[int, ...]] | None = None,
        layout: LayoutDict | None = None,
        mask_params: list[dict[str, Any]] | None = None,
        mask_values: dict[str, Any] | None = None,
    ) -> None:
        if not isinstance(n_inputs, int) or n_inputs < 0:
            raise BlockSpecError(
                f"Subsystem: n_inputs must be a non-negative int, got {n_inputs!r}"
            )
        if not isinstance(n_outputs, int) or n_outputs < 0:
            raise BlockSpecError(
                f"Subsystem: n_outputs must be a non-negative int, got {n_outputs!r}"
            )

        # 一旦 direct_feedthrough=False で初期化、内部構築後に再計算
        super().__init__(
            id=id,
            name=name,
            n_inputs=n_inputs,
            n_outputs=n_outputs,
            n_states=0,
            direct_feedthrough=False,
            port_shapes_in=port_shapes_in,
            port_shapes_out=port_shapes_out,
        )

        self._inner_blocks: list[Block] = []
        self._inner_blocks_by_id: dict[str, Block] = {}
        self._inner_type_counters: dict[str, int] = {}

        # 内部状態 layout: 各内部ブロックに対し state vector の slice を割り当てる
        # build (deferred) で確定
        self._state_slices: list[tuple[Block, slice]] = []
        self._discrete_slices: list[tuple[Block, slice]] = []
        self._continuous_slices: list[tuple[Block, slice]] = []

        # トポロジカル実行順 (build 時に確定)
        self._exec_order: list[Block] | None = None

        # save/load 用に元の引数を保持
        self._params = {
            "n_inputs": n_inputs,
            "n_outputs": n_outputs,
            "blocks": [],  # build 後に populate
            "connections": [],
        }
        # ADR-0018 §(5) MUST: SM-B Subsystem を save→load しても外側 ``port_shapes_*``
        # が消えて内部 Inport/Outport との整合性 check (``_build``) が壊れないように、
        # 非 default 時のみ JSON に出力する (= 純 SM-A モデルは byte-identical を維持)。
        scalar_shape: tuple[int, ...] = ()
        if any(s != scalar_shape for s in self.port_shapes_in):
            self._params["port_shapes_in"] = [list(s) for s in self.port_shapes_in]
        if any(s != scalar_shape for s in self.port_shapes_out):
            self._params["port_shapes_out"] = [list(s) for s in self.port_shapes_out]

        # ADR-0020 §Decision (1): Subsystem 内部 GUI レイアウト (再帰)。``None`` /
        # 空 dict のとき ``params.layout`` を JSON に出さず、SM-A モデルの byte-identical
        # を維持する。形式正規化は ``normalize_layout`` に委譲。
        self.layout: LayoutDict | None = normalize_layout(layout)

        # ADR-0021 §(6)(9): マスクパラメータ宣言 + 現在値。declarative `mask_params`
        # が None / 空のとき「マスクなし Subsystem」として byte-identical を維持。
        self.mask_params: list[dict[str, Any]] | None = normalize_mask_params(
            mask_params
        )
        self.mask_values: dict[str, Any] = self._init_mask_values(mask_values)

        if blocks is not None:
            for b in blocks:
                self.add(b)
        if connections is not None:
            for c in connections:
                self.connect(c["src"], c["dst"], c.get("src_idx", 0), c.get("dst_idx", 0))

    # ---------- ブロック登録・結線 (Simulator と同形 API) ----------

    def add(self, block: Block) -> Block:
        """内部ブロックを登録する。``Simulator.add`` と同形 (ADR-0004)。

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
        self._inner_blocks_by_id[block.id] = block
        self._inner_blocks.append(block)
        # 構造変更があったので次回 _build を強制再実行
        self._exec_order = None
        return block

    def _auto_id(self, block: Block) -> str:
        type_name = type(block).__name__
        n = self._inner_type_counters.get(type_name, 0)
        candidate = f"{type_name}_{n}"
        while candidate in self._inner_blocks_by_id:
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
        if dst_idx < 0 or dst_idx >= dst_block.n_inputs:
            raise IndexError(
                f"{dst_block.id}: input index {dst_idx} out of range "
                f"(n_inputs={dst_block.n_inputs})"
            )
        if src_idx < 0 or src_idx >= src_block.n_outputs:
            raise IndexError(
                f"{src_block.id}: output index {src_idx} out of range "
                f"(n_outputs={src_block.n_outputs})"
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

        # Inport / Outport の一覧
        inports = [b for b in self._inner_blocks if isinstance(b, Inport)]
        outports = [b for b in self._inner_blocks if isinstance(b, Outport)]
        if len(inports) != self.n_inputs:
            raise BlockSpecError(
                f"Subsystem {self.id!r}: declared n_inputs={self.n_inputs} but "
                f"found {len(inports)} Inport block(s)"
            )
        if len(outports) != self.n_outputs:
            raise BlockSpecError(
                f"Subsystem {self.id!r}: declared n_outputs={self.n_outputs} but "
                f"found {len(outports)} Outport block(s)"
            )
        # port_idx の重複・抜けチェック
        in_indices = sorted(p.port_idx for p in inports)
        if in_indices != list(range(self.n_inputs)):
            raise BlockSpecError(
                f"Subsystem {self.id!r}: Inport port_idx values {in_indices} "
                f"do not cover [0, {self.n_inputs})"
            )
        out_indices = sorted(p.port_idx for p in outports)
        if out_indices != list(range(self.n_outputs)):
            raise BlockSpecError(
                f"Subsystem {self.id!r}: Outport port_idx values {out_indices} "
                f"do not cover [0, {self.n_outputs})"
            )

        self._inports_by_idx = {p.port_idx: p for p in inports}
        self._outports_by_idx = {p.port_idx: p for p in outports}

        # ADR-0018 §(5): 内部 Inport/Outport の port_shape と外側 Subsystem の
        # port_shapes_in/out が一致するかを build 時に check する。
        for i, inport in self._inports_by_idx.items():
            inner_shape = inport.port_shape
            outer_shape = self.port_shapes_in[i]
            if inner_shape != outer_shape:
                raise BlockSpecError(
                    f"Subsystem {self.id!r}: port_shapes_in[{i}]={outer_shape} "
                    f"does not match inner Inport(port_idx={i}).port_shape={inner_shape}. "
                    f"Either pass port_shapes_in to Subsystem(...) or set port_shape on "
                    f"the Inport, so they agree."
                )
        for j, outport in self._outports_by_idx.items():
            inner_shape = outport.port_shape
            outer_shape = self.port_shapes_out[j]
            if inner_shape != outer_shape:
                raise BlockSpecError(
                    f"Subsystem {self.id!r}: port_shapes_out[{j}]={outer_shape} "
                    f"does not match inner Outport(port_idx={j}).port_shape={inner_shape}. "
                    f"Either pass port_shapes_out to Subsystem(...) or set port_shape on "
                    f"the Outport, so they agree."
                )

        # ネスト Subsystem の内部 build を先に発火 (direct_feedthrough 推論や n_states
        # の確定が外側から正しく見えるようにする)。code-reviewer MUST #2 修正。
        for b in self._inner_blocks:
            inner_build = getattr(b, "_build", None)
            if callable(inner_build):
                inner_build()

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
            if b.n_states > 0 and b.sample_time is not None and b.sample_time > 0.0
        ]
        if cont_states and disc_states:
            raise BlockSpecError(
                f"Subsystem {self.id!r}: mixing continuous-state and discrete-state "
                f"blocks inside one Subsystem is not supported in Phase 2. "
                f"Continuous: {[b.id for b in cont_states]}, "
                f"Discrete: {[b.id for b in disc_states]}. "
                f"Split into separate Subsystems or wait for Phase 3."
            )

        # トポロジカル順 (direct_feedthrough のみ依存辺)
        self._exec_order = self._compute_exec_order()

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

        # direct_feedthrough を内部 Inport→Outport 経路から推論 (LO-A)
        self.direct_feedthrough = self._infer_direct_feedthrough(inports, outports)

        # sample_time 継承 (ST-A): 内部の最小サンプル時間
        sample_times = [
            float(b.sample_time)
            for b in self._inner_blocks
            if b.sample_time is not None and b.sample_time > 0.0
        ]
        if sample_times:
            self.sample_time = min(sample_times)

        # save/load 用 params の確定
        self._params["blocks"] = [b.to_dict() for b in self._inner_blocks]
        self._params["connections"] = self._serialize_inner_connections()

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
        outport_ids: set[str] = {o.id for o in outports if o.id is not None}
        for inp in inports:
            assert inp.id is not None
            visited: set[str] = set()
            stack: list[str] = [inp.id]
            while stack:
                cur = stack.pop()
                if cur in visited:
                    continue
                visited.add(cur)
                if cur in outport_ids:
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

    def _init_mask_values(
        self, explicit: dict[str, Any] | None
    ) -> dict[str, Any]:
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
            raise BlockSpecError(
                f"Subsystem {self.id!r} has no mask_params declared"
            )
        if name not in {p["name"] for p in self.mask_params}:
            raise BlockSpecError(
                f"Subsystem {self.id!r}: unknown mask name {name!r}"
            )
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
        self, t: float, x: np.ndarray, u_external: np.ndarray
    ) -> tuple[dict[Block, np.ndarray], dict[Block, np.ndarray]]:
        """内部の 2 パス出力計算 (``Simulator._step`` の縮小版)。

        外部 ``u_external[port_idx]`` を Inport の ``_external_value`` に注入してから
        実行する。

        Returns:
            ``(outputs, inputs)``: 各内部ブロックの出力と入力ベクトル。
        """
        for port_idx in range(self.n_inputs):
            self._inports_by_idx[port_idx]._external_value = float(u_external[port_idx])

        # 内部状態を slice ごとに取り出す
        cont_state = {b: x[sl] for b, sl in self._state_slices}

        outputs: dict[Block, np.ndarray] = {}
        inputs: dict[Block, np.ndarray] = {}

        def state_for(b: Block) -> np.ndarray:
            return cont_state.get(b, np.zeros(0))

        assert self._exec_order is not None
        for b in self._exec_order:
            if b.direct_feedthrough:
                u = np.zeros(b.n_inputs)
                for i, src in enumerate(b.input_sources):
                    if src is not None:
                        sb, si = src
                        u[i] = outputs[sb][si]
                inputs[b] = u
            else:
                u = np.zeros(b.n_inputs)
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

    def output(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        self._build()
        outputs, _inputs = self._step_inner(t, x, u)
        # Outport ごとに集める
        y = np.zeros(self.n_outputs)
        for port_idx in range(self.n_outputs):
            outport = self._outports_by_idx[port_idx]
            src = outport.input_sources[0]
            if src is not None:
                sb, si = src
                y[port_idx] = outputs[sb][si]
        return y

    def derivative(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        self._build()
        if self.n_states == 0:
            return np.zeros(0)
        _outputs, inputs = self._step_inner(t, x, u)
        xdot = np.zeros(self.n_states)
        for b, sl in self._continuous_slices:
            xdot[sl] = np.asarray(
                b.derivative(t, x[sl], inputs.get(b, np.zeros(b.n_inputs))),
                dtype=float,
            )
        return xdot

    def update(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        self._build()
        if self.n_states == 0:
            return np.asarray(x, dtype=float)
        _outputs, inputs = self._step_inner(t, x, u)
        x_next: np.ndarray = np.array(x, dtype=float, copy=True)
        for b, sl in self._discrete_slices:
            x_next[sl] = np.asarray(
                b.update(t, x[sl], inputs.get(b, np.zeros(b.n_inputs))),
                dtype=float,
            )
        return x_next

    # ---------- 永続化サポート ----------

    def to_dict(self) -> dict[str, Any]:
        """``Block.to_dict`` を override して内部 ``blocks``/``connections`` をネスト。

        ADR-0018 §(5): SM-B Subsystem は ``port_shapes_in`` / ``port_shapes_out``
        が non-default の時のみ ``params`` に追加される (純 SM-A モデルの JSON は
        byte-identical を維持するため)。

        ADR-0020 §Decision (1)(5): 内部 GUI レイアウトを ``params.layout`` に
        再帰的に保存する。``self.layout is None`` または空のときは出力しない (=
        layout を持たない既存 Subsystem の JSON は完全互換)。stale id (= 削除済み
        block を参照) は drop。
        """
        from ..core.persistence import block_type_path

        # 内部 build を発火させ、内部構造の整合性チェック (BlockSpecError /
        # AlgebraicLoopError) を save 時にも走らせる。不完全な Subsystem は
        # 素直に保存できないので例外がそのまま伝播する設計。
        self._build()
        params: dict[str, Any] = {
            "n_inputs": self.n_inputs,
            "n_outputs": self.n_outputs,
        }
        scalar_shape: tuple[int, ...] = ()
        if any(s != scalar_shape for s in self.port_shapes_in):
            params["port_shapes_in"] = [list(s) for s in self.port_shapes_in]
        if any(s != scalar_shape for s in self.port_shapes_out):
            params["port_shapes_out"] = [list(s) for s in self.port_shapes_out]
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
                b.id: self.layout[b.id]
                for b in self._inner_blocks
                if b.id in self.layout
            }
            stale = [k for k in self.layout if k not in inner_ids]
            for s in stale:
                _logger.warning(
                    "Subsystem %r.to_dict: layout entry %r refers to unknown inner "
                    "block id; dropping",
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
        n_inputs: int,
        n_outputs: int,
        blocks: list[Any],
        connections: list[dict[str, Any]],
        id: str | None = None,
        port_shapes_in: list[list[int]] | None = None,
        port_shapes_out: list[list[int]] | None = None,
        layout: LayoutDict | None = None,
        mask_params: list[dict[str, Any]] | None = None,
        mask_values: dict[str, Any] | None = None,
    ) -> Subsystem:
        """JSON load 時の factory (ADR-0009 §(7) / code-reviewer MUST #3 修正)。

        ``blocks`` の各要素は ``dict`` (= JSON から読んだ block entry) または
        ``Block`` インスタンス。``dict`` なら ``resolve_block_class`` で class を解決
        して再構築し、内部に ``add`` する。

        ``port_shapes_in`` / ``port_shapes_out`` (ADR-0018 §(5)): non-default の
        SM-B Subsystem を save→load する際に外側 port shape を復元する。``None`` の
        場合は SM-A 互換 (全 ``()``) として扱う。

        ``Simulator.load`` 経由でのみ使われる想定 (= 通常の ``__init__`` 経路は
        ``blocks`` に Block インスタンスを渡す)。
        """
        from ..core.persistence import resolve_block_class

        ps_in: tuple[tuple[int, ...], ...] | None = (
            tuple(tuple(int(v) for v in s) for s in port_shapes_in)
            if port_shapes_in is not None
            else None
        )
        ps_out: tuple[tuple[int, ...], ...] | None = (
            tuple(tuple(int(v) for v in s) for s in port_shapes_out)
            if port_shapes_out is not None
            else None
        )
        sub = cls(
            n_inputs=n_inputs,
            n_outputs=n_outputs,
            id=id,
            port_shapes_in=ps_in,
            port_shapes_out=ps_out,
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
                    resolved_params = substitute_placeholders(
                        raw_params, active_mask_values
                    )
                else:
                    resolved_params = raw_params
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
