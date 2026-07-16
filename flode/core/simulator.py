"""Simulator: ブロック登録・結線・実行の中心。

ADR-0002 (離散時間 + マルチレート) で `run()` を連続/離散ハイブリッド対応に拡張。
ADR-0004 (ブロック ID 規則) で自動採番 / `connect` の `Block | str` 対応 / `rename` を追加。
ADR-0008 (JSON 永続化) で `save` / `load` を追加。
"""

from __future__ import annotations

import datetime
import json
import logging
import math
from collections import defaultdict, deque
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
import numpy.typing as npt
from scipy.integrate import solve_ivp

from ..exceptions import (
    AlgebraicLoopError,
    BlockSpecError,
    ModelLoadError,
    SchedulingError,
    SolverError,
    UnknownBlockIdError,
)
from .block import Block
from .identifiers import validate_block_id
from .persistence import (
    CURRENT_SCHEMA_VERSION,
    LayoutDict,
    migrate_to_current,
    normalize_layout,
    parse_t_end,
    resolve_block_class,
    serialize_connections,
    serialize_t_end,
)

if TYPE_CHECKING:  # pragma: no cover - 循環 import 回避
    from ..analysis.linearize import LinearSystem
    from ..compile.compiled_simulator import CompiledSimulator

# ADR-0011 §(4): on_step_callback の型エイリアス
StepCallback = Callable[[float, float], bool]

_logger = logging.getLogger("pyflw.scheduler")
# ADR-0055 §論点 3 / SPEC-0003 §3-5: 仮想エッジ展開時の WARNING / INFO 専用
_logger_routing = logging.getLogger("pyflw.routing.goto")

_SAMPLE_TIME_RATIO_TOL = 1e-9


class Simulator:
    """連続/離散ハイブリッドシミュレータ。

    Args:
        t_end: シミュレーション終了時刻 [s]。
        dt: 連続のみモデル時の基本ステップ。離散ブロックがある場合は
            ``dt_base = min(dt, 最も細かい sample_time)`` が採用される。
            ``dt_base`` 引数で明示指定された場合はそちらを優先する。
        solver: scipy ``solve_ivp`` の method (``"RK45"``, ``"LSODA"`` 等)。
        rtol / atol: ``solve_ivp`` の許容誤差。
        dt_base: 基本ステップの明示指定。``None`` (default) なら ``dt`` と
            離散ブロックの sample_time から自動推定する。手動指定すると
            離散周期との整数比チェックをスキップして強制適用される。
    """

    def __init__(
        self,
        t_end: float | str = 10.0,
        dt: float = 0.01,
        solver: str = "RK45",
        rtol: float = 1e-6,
        atol: float = 1e-9,
        dt_base: float | None = None,
        on_step_callback: StepCallback | None = None,
    ) -> None:
        # ADR-0042 §論点 4-A: ``"inf"`` (case-insensitive) を受け入れて
        # ``math.inf`` に変換する。``parse_t_end`` で全 validation 一元化。
        self.t_end: float = parse_t_end(t_end)
        self.dt = float(dt)
        self.solver = solver
        self.rtol = rtol
        self.atol = atol
        self.dt_base_hint: float | None = None if dt_base is None else float(dt_base)
        self.blocks: list[Block] = []
        self._blocks_by_id: dict[str, Block] = {}
        self._type_counters: dict[str, int] = {}
        # ADR-0011 §(4): 各 ``record`` 後に呼ばれる progress hook。GUI バックエンドが
        # シミュレーション進捗を WebSocket で配信するため。``None`` で no-op。
        # 引数は ``(t, t_end)`` の 2 floats、戻り値は ``True`` でシミュレーション
        # 続行、``False`` で graceful 停止。
        self.on_step_callback: StepCallback | None = on_step_callback
        # 停止要求フラグ (run() 中に外部から `request_stop()` で True にすると graceful 停止)
        self._stop_requested: bool = False
        # ADR-0020 §Decision (3): 直近 ``Simulator.load()`` で読んだファイルの
        # top-level ``layout`` を保持する。GUI が ``last_loaded_layout`` を取り出して
        # React Flow に渡すために使う。CLI / pytest からは無視できる (動作不変)。
        self.last_loaded_layout: LayoutDict | None = None
        # ADR-0055 §論点 1-A: 仮想エッジ展開フェーズで構築される、
        # ``_execution_order`` の topo sort に merge する追加 deps (``(dst, src)`` の set)。
        # 共通祖先スコープが Simulator (= ()) のペアのみ格納し、Subsystem 共通祖先の
        # ペアは Subsystem._virtual_inner_deps に流す (= ADR-0055 §論点 5-A)。
        # ``_resolve_goto_from_virtual_edges`` が冒頭で必ずリセットする。
        self._virtual_deps_top: set[tuple[Block, Block]] = set()
        # ADR-0056 §C-3: 例外発生時の関与ブロック追跡。``_step`` / ``_run_sm_*_loop``
        # で各ブロックの ``output`` / ``derivative`` / ``update`` を呼ぶ直前にセット
        # する。run() が成功完了すれば ``None`` に戻る。例外が伝搬したときは最後に
        # set されたブロックが残り、サーバ層が構造化エラー payload に詰める。
        self._current_block: Block | None = None

    def add(self, block: Block) -> Block:
        """ブロックを Simulator に登録する。

        ``block.id is None`` のとき自動採番 (``{type_name}_{counter}``)。
        既存 ID と衝突する場合は ``BlockSpecError``。
        """
        if not isinstance(block, Block):
            raise TypeError(f"Expected Block instance, got {type(block).__name__}")
        if block.id is None:
            block.id = self._auto_id(block)
        else:
            if block.id in self._blocks_by_id:
                raise BlockSpecError(
                    f"Block id {block.id!r} already exists. "
                    "Use a unique `id=` argument or omit it for auto-generation."
                )
        self._blocks_by_id[block.id] = block
        self.blocks.append(block)
        return block

    def _auto_id(self, block: Block) -> str:
        type_name = type(block).__name__
        n = self._type_counters.get(type_name, 0)
        candidate = f"{type_name}_{n}"
        while candidate in self._blocks_by_id:
            n += 1
            candidate = f"{type_name}_{n}"
        self._type_counters[type_name] = n + 1
        return candidate

    # _type_counters[type_name] は「次に試す番号」を保持する。ユーザー指定で
    # 飛ばされた番号は再利用しない (ADR-0004 §(2)-5: 連番は削除しても再利用しない)。

    def get_block(self, block_id: str) -> Block:
        """ID から Block を取得する。不在なら ``UnknownBlockIdError``。"""
        try:
            return self._blocks_by_id[block_id]
        except KeyError as e:
            raise UnknownBlockIdError(f"No block registered with id {block_id!r}") from e

    def rename(self, old_id: str, new_id: str) -> None:
        """登録済みブロックの ID をリネームする。

        結線情報はオブジェクト参照で保持されるため自動的に追従する (壊れない)。
        ``new_id`` の文字集合は ``validate_block_id`` で検証、衝突時は ``BlockSpecError``。
        """
        if old_id not in self._blocks_by_id:
            raise UnknownBlockIdError(f"No block registered with id {old_id!r}")
        validate_block_id(new_id)
        if new_id == old_id:
            return
        if new_id in self._blocks_by_id:
            raise BlockSpecError(f"Block id {new_id!r} already exists")
        block = self._blocks_by_id.pop(old_id)
        block.id = new_id
        self._blocks_by_id[new_id] = block

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
        """``src.src_idx`` を ``dst.dst_idx`` に結線する。

        ``src`` / ``dst`` は ``Block`` インスタンス、または登録済み ID 文字列。
        """
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

    def _execution_order(self) -> list[Block]:
        # ADR-0058 §論点 3 / SPEC-0007 §機能要件 4: root (= Simulator 直下) に
        # Trigger / Enable control block を配置することは禁止。これらは Subsystem
        # 内部にのみ意味を持つ境界ブロックなので、root に置かれていたら早期 fail。
        # 循環 import 回避のため関数内で import (= simulator.py が subsystems を
        # トップで import すると subsystems/__init__.py が control_blocks を引いて、
        # control_blocks が core.block を引く、という解決可能なチェーンだが
        # 既存のレイヤリングを尊重)。
        from ..subsystems.control_blocks import Enable, Trigger

        for b in self.blocks:
            if isinstance(b, (Trigger, Enable)):
                kind = type(b).__name__
                raise BlockSpecError(
                    f"{kind} block {b.id!r} cannot be placed at root level "
                    f"(Simulator); it must be inside a Subsystem (ADR-0058 §論点 3)."
                )

        # Subsystem 等、内部構造を持つブロックは direct_feedthrough / n_states /
        # x0 を ``_build()`` で確定する (Block 基底の default は no-op)。
        # 実行順序解析の前に全ブロックに対し呼ぶ。
        for b in self.blocks:
            b._build()
        # ADR-0055 §論点 1-A: 各 ``b._build()`` 直後・``_check_port_shapes`` の前に
        # 仮想エッジ展開フェーズを挟む。Goto/From を含まないモデルは早期 return
        # するため、既存 949 件テストへの影響ゼロ (= ADR-0036 §(8) / 本 ADR
        # §Consequences 数値完全不変ガード)。
        self._resolve_goto_from_virtual_edges()
        # ADR-0017 §(4): build 時 port shape 整合性 check (_execution_order の前)
        self._check_port_shapes()
        deps: dict[Block, set[Block]] = {b: set() for b in self.blocks}
        rev: dict[Block, set[Block]] = defaultdict(set)
        for b in self.blocks:
            if b.direct_feedthrough:
                for src in b.input_sources:
                    if src is not None:
                        deps[b].add(src[0])
                        rev[src[0]].add(b)
        # ADR-0055 §論点 1-A / §論点 5-A: 仮想エッジ展開で追加された
        # Simulator level の仮想 deps を topo sort に merge。共通祖先スコープが
        # Simulator (= ()) のときだけ ``_virtual_deps_top`` が populate される
        # (Subsystem 共通祖先のときは ``Subsystem._virtual_inner_deps`` 経由)。
        for dst_block, src_block in self._virtual_deps_top:
            deps[dst_block].add(src_block)
            rev[src_block].add(dst_block)
        ready: deque[Block] = deque(b for b in self.blocks if not deps[b])
        order: list[Block] = []
        while ready:
            b = ready.popleft()
            order.append(b)
            for child in rev[b]:
                deps[child].discard(b)
                if not deps[child]:
                    ready.append(child)
        if len(order) != len(self.blocks):
            remaining = [b.id for b in self.blocks if b not in order]
            # ADR-0056 §C-3: 関与ブロック ID を例外 attr に持たせる。``Block.id`` は
            # 仕様上 ``str | None`` だが ``_execution_order`` 到達時点で全 block が
            # ``add()`` 経由で auto-ID 採番済なので Optional は剥がせる。
            remaining_ids = [str(b_id) for b_id in remaining if b_id is not None]
            raise AlgebraicLoopError(
                f"Algebraic loop detected involving: {remaining}",
                block_ids=remaining_ids,
            )
        return order

    # ------------------------------------------------------------------
    # ADR-0055 §論点 1-A: 仮想エッジ展開 (Goto / From)
    # ------------------------------------------------------------------

    def _walk_scopes(self) -> Iterator[tuple[tuple[Any, ...], list[Block]]]:
        """全スコープ (Simulator + 再帰 Subsystem 内部) を yield する。

        各 yield は ``(scope_path, blocks)``:
          - ``scope_path``: ``tuple[Subsystem, ...]``。Simulator 自身は ``()``、
            ネスト Subsystem は ``(outer_sub, inner_sub, ...)``。
          - ``blocks``: そのスコープ直下のブロックリスト
            (Simulator なら ``self.blocks``、Subsystem なら ``sub._inner_blocks``)。
        """
        # 遅延 import で循環回避 (Subsystem は core.block を継承)
        from ..subsystems import Subsystem

        yield ((), self.blocks)

        def _walk_sub(
            sub: Subsystem, path: tuple[Any, ...]
        ) -> Iterator[tuple[tuple[Any, ...], list[Block]]]:
            yield (path, sub._inner_blocks)
            for inner in sub._inner_blocks:
                if isinstance(inner, Subsystem):
                    yield from _walk_sub(inner, path + (inner,))

        for b in self.blocks:
            if isinstance(b, Subsystem):
                yield from _walk_sub(b, (b,))

    @staticmethod
    def _scope_path_str(scope_path: tuple[Any, ...]) -> str:
        """エラー / ログメッセージ用のスコープパス文字列 (ADR-0055 §U5)。"""
        if not scope_path:
            return "<root>"
        return "/".join((s.id or "?") for s in scope_path)

    def _resolve_goto_from_virtual_edges(self) -> None:
        """SPEC-0003 §3 / ADR-0055 §論点 1〜6: tag ベース仮想配線を解決する。

        実行内容 (要点):
          1. 全スコープを 1 パス走査して Goto / From を収集
             (Goto/From を 1 つも持たないモデルは早期 return)
          2. 一意性チェック (Local 同一スコープ内重複 / Global モデル全体重複)
          3. 同 tag が Local と Global で並存する場合 WARNING を通知
             (SPEC-0003 §3-2 緩和)
          4. 各 From を Local → Global の優先順位で解決 (ADR-0055 §論点 2-A
             Amendment 版、Scoped は Phase 2 送り)
          5. 解決済み Goto/From の port_shape を build 時確定 (§論点 4-A)
          6. ``direct_feedthrough = True`` に書き換え + 仮想 deps を共通祖先
             スコープの exec_order に追加 (§論点 5-A)
          7. ``_last_input`` リセット (= 2 回目以降 run の安全網)
          8. Subsystem は ``_virtual_inner_deps`` 反映のため再ビルド
             (ネストした全祖先 Subsystem を対象)
          9. dangling Goto を INFO で残す (§3-5)

        Note: SPEC-0003 / ADR-0055 Amendment (2026-05-19) で Scoped visibility と
        GotoTagVisibility は Phase 2 送りに縮減されたため、本実装からも除外。
        """
        # ADR-0055 §論点 1-A 「Goto/From を含まないモデルは早期 return」 =
        # 既存テスト + spring_mass_damper の数値完全不変ガード。
        self._virtual_deps_top = set()
        # Subsystem._virtual_inner_deps もリセット (再ビルド時にも入念に)
        from ..subsystems import Subsystem

        for _sp, blocks in self._walk_scopes():
            for b in blocks:
                if isinstance(b, Subsystem):
                    b._virtual_inner_deps = set()

        from ..blocks.routing import From, Goto

        # ------------- Phase 1: 全スコープ 1 パス走査 + registry 構築 -------------
        scope_of: dict[Block, tuple[Any, ...]] = {}
        local_registry: dict[tuple[tuple[Any, ...], str], Goto] = {}
        global_registry: dict[str, Goto] = {}
        from_list: list[tuple[From, tuple[Any, ...]]] = []
        subsystems_with_goto_from: set[Subsystem] = set()
        found_any = False

        for scope_path, blocks in self._walk_scopes():
            for b in blocks:
                scope_of[b] = scope_path
                if isinstance(b, (Goto, From)):
                    found_any = True
                    # ネストの中間 Subsystem も再ビルド対象に含める
                    # (= 深ネスト時にも仮想 deps が正しく反映される)
                    for sub in scope_path:
                        subsystems_with_goto_from.add(sub)
                if isinstance(b, Goto):
                    if b.tag_visibility == "local":
                        key = (scope_path, b.tag)
                        if key in local_registry:
                            raise BlockSpecError(
                                f"duplicate Local Goto tag {b.tag!r} in scope "
                                f"{self._scope_path_str(scope_path)}",
                                block_id=b.id,
                            )
                        local_registry[key] = b
                    else:  # "global"
                        if b.tag in global_registry:
                            raise BlockSpecError(
                                f"duplicate Global Goto tag {b.tag!r}",
                                block_id=b.id,
                            )
                        global_registry[b.tag] = b
                elif isinstance(b, From):
                    from_list.append((b, scope_path))

        if not found_any:
            return  # 数値完全不変ガード

        # ------------- Phase 2: 同 tag 異 visibility 衝突 WARNING (SPEC-0003 §3-2 緩和) -------------
        self._warn_visibility_mixed_kinds(local_registry, global_registry)

        # ------------- Phase 3: From の解決 + 仮想エッジ構築 (§論点 4-A / 5-A) -------------
        used_gotos: set[Goto] = set()

        for from_block, from_scope in from_list:
            resolved_goto = self._resolve_from(
                from_block, from_scope, local_registry, global_registry
            )
            used_gotos.add(resolved_goto)
            # Goto の上流接続を取得
            if resolved_goto.input_sources[0] is None:
                raise BlockSpecError(
                    f"Goto {resolved_goto.id!r}(tag={resolved_goto.tag!r}): "
                    f"input port 0 is not connected; cannot resolve virtual edge "
                    f"for From {from_block.id!r}"
                )
            src_block, src_idx = resolved_goto.input_sources[0]
            # ADR-0055 §論点 4-A: build 時 shape 確定 (Goto/From のみの例外 API)
            src_shape = src_block.port_shapes_out[src_idx]
            resolved_goto._set_port_shapes_in_for_build((src_shape,))
            from_block._set_port_shapes_out_for_build((src_shape,))
            # 解決済み Goto への参照を埋め込み (run 時に From.output が読む)
            from_block._resolved_goto = resolved_goto
            # 2 回目以降の ``run()`` で安全網 (= ``From._ensure_resolved`` の
            # ``_last_input is None`` ガード) が正しく機能するよう、build 時に
            # Goto._last_input をリセットする。
            resolved_goto._last_input = None
            # ADR-0055 §論点 5-A: From は仮想 wire 経由で Goto に依存するため
            # direct_feedthrough を True に書き換え。これで仮想 deps を topo sort
            # に merge した時点で「Goto → From」の順序が保証される。
            from_block.direct_feedthrough = True
            self._add_virtual_dep(from_block, from_scope, resolved_goto, scope_of)

        # ------------- Phase 4: dangling 検出 INFO (SPEC-0003 §3-5) -------------
        self._log_dangling(local_registry, global_registry, used_gotos)

        # ------------- Phase 5: Subsystem 内部 exec_order の再計算 (§論点 5-A) -------------
        for sub in subsystems_with_goto_from:
            sub._exec_order = None
            sub._build()

    def _resolve_from(
        self,
        from_block: Any,
        from_scope: tuple[Any, ...],
        local_registry: dict[tuple[tuple[Any, ...], str], Any],
        global_registry: dict[str, Any],
    ) -> Any:
        """SPEC-0003 §3-3 / ADR-0055 §論点 2-A (Amendment 版) の解決優先順位を実装する。

        1. Local: 同一スコープの ``Goto(tag, "local")``
        2. Global: モデル全体の ``Goto(tag, "global")``
        3. 失敗: ``BlockSpecError``

        Note: Scoped 解決は SPEC-0003 / ADR-0055 Amendment (2026-05-19) で
        Phase 2 送り。Phase 2 で Local と Global の間に Scoped 解決ステップを
        挟む形で復活させる。
        """
        tag = from_block.tag
        # 1. Local
        local_hit = local_registry.get((from_scope, tag))
        if local_hit is not None:
            return local_hit
        # 2. Global
        global_hit = global_registry.get(tag)
        if global_hit is not None:
            return global_hit
        # 3. 失敗
        raise BlockSpecError(
            f"From {from_block.id!r}(tag={tag!r}) in scope "
            f"{self._scope_path_str(from_scope)}: no matching Goto found "
            f"(tried Local→Global)",
            block_id=from_block.id,
        )

    def _add_virtual_dep(
        self,
        from_block: Block,
        from_scope: tuple[Any, ...],
        goto_block: Block,
        scope_of: dict[Block, tuple[Any, ...]],
    ) -> None:
        """共通祖先スコープに仮想 deps を追加する (ADR-0055 §論点 5-A、Plan §U2)。

        実行順序の保証: Goto は ``output`` / ``output_v`` で入力を
        ``_last_input`` に記録し、From はそれを読み出す。よって exec_order
        では「Goto → From」(または「Goto を含む Subsystem → From を含む
        Subsystem」) の順が必要。

        - 同一スコープ (= from_scope == goto_scope): そのスコープの
          ``deps[from_block].add(goto_block)``
        - 跨ぎ (= from_scope と goto_scope が共通祖先 prefix を持つ): 共通祖先
          スコープ直下のブロック対 (``from_top``, ``goto_top``) で依存追加。
          ``from_top`` / ``goto_top`` は、共通祖先より深い側 (= from や goto を
          含む祖先 Subsystem) を指す。
        """
        goto_scope = scope_of.get(goto_block, ())
        # 共通祖先スコープ = from_scope と goto_scope の identity 一致 prefix
        common_len = 0
        for a, b in zip(from_scope, goto_scope, strict=False):
            if a is b:
                common_len += 1
            else:
                break
        common_scope = from_scope[:common_len]
        # 共通祖先スコープの「直下」のブロックを特定
        # (= scope_path[common_len] が存在すればそれ、なければブロック自身)
        from_top: Block = from_scope[common_len] if common_len < len(from_scope) else from_block
        goto_top: Block = goto_scope[common_len] if common_len < len(goto_scope) else goto_block
        # 自己依存 (= from_top is goto_top) は skip (= 同一 Subsystem 内で from
        # も goto も同じ Subsystem 配下にいる場合、その Subsystem の内部 deps で
        # 別途追加するため、外側で自己依存を作るとループになる)。
        if from_top is goto_top:
            return
        # 共通スコープが Simulator (= ()) なら top-level deps、Subsystem ならその内部
        if not common_scope:
            self._virtual_deps_top.add((from_top, goto_top))
        else:
            boundary_sub = common_scope[-1]
            boundary_sub._virtual_inner_deps.add((from_top, goto_top))

    def _warn_visibility_mixed_kinds(
        self,
        local_registry: dict[tuple[tuple[Any, ...], str], Any],
        global_registry: dict[str, Any],
    ) -> None:
        """同 tag が Local と Global で並存する場合 WARNING (SPEC-0003 §3-2 緩和)。

        解決は Local → Global の優先順位で行うため意味的には区別可能だが、
        潜在的なバグの可能性を残しておく。
        """
        local_tags = {tag for (_sp, tag) in local_registry}
        global_tags = set(global_registry)
        for tag in local_tags & global_tags:
            _logger_routing.warning(
                "tag %r is declared as both Local and Global Goto; "
                "Local resolution takes precedence (SPEC-0003 §3-3)",
                tag,
            )

    def _log_dangling(
        self,
        local_registry: dict[tuple[tuple[Any, ...], str], Any],
        global_registry: dict[str, Any],
        used_gotos: set[Any],
    ) -> None:
        """SPEC-0003 §3-5: 対応 From が無い Goto を INFO ログで残す (エラーにはしない)。"""
        for (scope_path, tag), goto in local_registry.items():
            if goto not in used_gotos:
                _logger_routing.info(
                    "dangling Goto: tag=%r visibility=local scope=%s",
                    tag,
                    self._scope_path_str(scope_path),
                )
        for tag, goto in global_registry.items():
            if goto not in used_gotos:
                _logger_routing.info("dangling Goto: tag=%r visibility=global", tag)

    def _check_port_shapes(self) -> None:
        """ADR-0017 §(4): 接続元出力 port_shape と接続先入力 port_shape が一致するかチェック。

        SM-A モード (全ポート shape ``()``) では既存挙動と等価 (全 ``()`` 同士の一致は
        常に成立)。SM-B モード (一部に非 ``()`` shape があれば) は厳密な shape 一致を
        要求 (broadcasting なし、ADR-0017 §(6) Phase 4+ 送り)。

        Raises:
            BlockSpecError: 接続元出力と接続先入力の port_shape が不一致。
                エラーメッセージで Mux/Demux 経由を誘導する。
        """
        for dst in self.blocks:
            for dst_idx, src in enumerate(dst.input_sources):
                if src is None:
                    continue
                src_block, src_idx = src
                src_shape = src_block.port_shapes_out[src_idx]
                dst_shape = dst.port_shapes_in[dst_idx]
                if src_shape != dst_shape:
                    raise BlockSpecError(
                        f"Port shape mismatch: {src_block.id!r}.out[{src_idx}] has "
                        f"shape {src_shape} but {dst.id!r}.in[{dst_idx}] expects "
                        f"shape {dst_shape}. Use a Mux/Demux block (Phase 3+) to "
                        f"adapt scalar/vector ports."
                    )

    def _check_scope_inputs_are_scalar(self) -> None:
        """ADR-0018 §(3) S-A: ``Scope`` ブロックは SM-A scalar 入力のみ受け付ける。

        SM-B モードで Scope に vector 信号を直接繋ぐと build 時に明示エラーで
        拒否し、Demux 経由 (port-by-port に分解) を誘導する。Scope クラス名で
        判定 (= ADR-0018 §(8) U2 で Option a "abstraction leak" を許容)。
        """
        # 遅延 import で循環回避 (Scope は ``pyflw.blocks.sinks``、Block は ``core``)
        from ..blocks.sinks import Scope

        for b in self.blocks:
            if isinstance(b, Scope):
                for i, shape in enumerate(b.port_shapes_in):
                    if shape != ():
                        raise BlockSpecError(
                            f"Scope {b.id!r}: input port {i} has shape {shape}, but "
                            f"Scope only accepts scalar (rank-0) inputs. Use a Demux "
                            f"block to split the vector signal into scalar ports first."
                        )

    def _check_subsystem_sm_b_unsupported(self) -> None:
        """ADR-0018 §(4.3): SM-B port を持つ ``Subsystem`` は Phase 3 では run 不可。

        ``Subsystem.output_v`` は override されておらず、``Block.output_v`` default
        wrapper は ``output`` を呼んで内部で ``_step_inner`` の SM-A scalar coercion
        (``float(u_external[port_idx])``) を経由する。従って SM-B 信号 (ndarray) は
        サイレントに切り捨てられる。`_step_inner_v` は Phase 4 で追加予定 (ADR-0018
        §(4.3))。
        """
        # 遅延 import で循環回避
        from ..subsystems import Subsystem

        for b in self.blocks:
            if isinstance(b, Subsystem):
                has_sm_b = any(s != () for s in b.port_shapes_in) or any(
                    s != () for s in b.port_shapes_out
                )
                if has_sm_b:
                    raise BlockSpecError(
                        f"Subsystem {b.id!r}: running a Subsystem with SM-B vector "
                        f"ports (port_shapes_in={b.port_shapes_in}, "
                        f"port_shapes_out={b.port_shapes_out}) is not supported in "
                        f"Phase 3 (ADR-0018 §(4.3)). Save/load round-trip is preserved, "
                        f"but execution awaits ``_step_inner_v`` in Phase 4."
                    )

    def _record_v(
        self,
        t: float,
        inputs_v: dict[Block, tuple[npt.NDArray[Any], ...]],
    ) -> None:
        """SM-B run path 用の record。tuple-of-ndarray inputs を SM-A の 1D ndarray に
        変換して既存 ``record(t, u_1d)`` に橋渡しする (ADR-0018 §(3))。

        Scope は SM-A only (ビルド時に確認済み) なので、各 input port は rank-0
        ndarray。これらを 1D ndarray に concat して既存 API に渡す。

        Contract:
            ``inputs_v`` は ``_step_vector`` の 2nd-pass 戻り値で、``record`` を持つ
            ブロック (Scope 等) は ``direct_feedthrough=True`` であるかぎり必ず
            ``inputs_v[b]`` が書き込まれている。``direct_feedthrough=False`` の
            recordable ブロックは現 Phase では存在しないが、将来追加された場合
            ``inputs_v.get(b) is None`` になりうる。その時はサイレント skip ではなく
            ``BlockSpecError`` で気付ける形にしてある (= debug ノイズを残さない)。
        """
        for b in self.blocks:
            if not hasattr(b, "record"):
                continue
            u_tuple = inputs_v.get(b)
            if u_tuple is None:
                # _step_vector は direct_feedthrough=True の recordable ブロックには
                # 必ず inputs を書き込む。ここに来たら implementation bug。
                raise BlockSpecError(
                    f"Block {b.id!r} has record() but no inputs were gathered in "
                    f"_step_vector. This indicates an internal bug or an unsupported "
                    f"direct_feedthrough=False sink block."
                )
            # tuple of rank-0 ndarrays → 1D ndarray (length = n_inputs)
            u_1d = np.array([float(np.asarray(ui).item()) for ui in u_tuple], dtype=float)
            b.record(t, u_1d)

    def _is_sm_a_mode(self) -> bool:
        """ADR-0017 §(8) U2: 全ブロックが SM-A 互換 (全 port_shape == ()) か判定。

        ホットパス分岐用。``run()`` 冒頭で 1 回判定し、SM-A モードなら既存の
        高速 ``_step`` パスを使う (4xx 件のテストへの影響ゼロを保証)。
        """
        for b in self.blocks:
            for shape in b.port_shapes_in:
                if shape != ():
                    return False
            for shape in b.port_shapes_out:
                if shape != ():
                    return False
        return True

    def _resolve_sample_times(self, order: list[Block]) -> None:
        """継承サンプル時間 (``sample_time = -1.0``) をトポロジカル順に解決する。

        各ブロックの ``_resolved_sample_time`` 属性に決定値を格納する。
        元の ``sample_time`` 属性は変更しない。

        Note:
            ``order`` は ``_execution_order`` の戻り値 (direct_feedthrough=True
            ブロックの依存に基づくトポロジカル順)。継承解決は ``input_sources`` を
            遡るので、上流が先に解決済みであることが必要。direct_feedthrough=False
            のブロック (Integrator/UnitDelay 等) は依存辺を持たないため
            ``order`` の先頭側に来る傾向があり、それらが「上流」として参照される
            ケースでも ADR-0002 §(2) の規則どおりに解決できる。
        """
        for b in order:
            st = b.sample_time
            if st is None or st == 0.0:
                b._resolved_sample_time = None
                continue
            if st > 0.0:
                b._resolved_sample_time = float(st)
                continue
            if st == -1.0:
                upstream: list[float | None] = [
                    src[0]._resolved_sample_time for src in b.input_sources if src is not None
                ]
                if not upstream:
                    raise BlockSpecError(
                        f"Block {b.id!r} has sample_time=-1.0 (inherited) but no inputs"
                    )
                discrete = [t for t in upstream if t is not None and t > 0.0]
                if not discrete:
                    b._resolved_sample_time = None
                else:
                    distinct = sorted(set(discrete))
                    if len(distinct) > 1:
                        _logger.warning(
                            "Block %r has multiple upstream sample_times %s; inheriting min=%g",
                            b.id,
                            distinct,
                            distinct[0],
                        )
                    has_continuous = any(t is None for t in upstream)
                    if has_continuous:
                        _logger.warning(
                            "Block %r inherits sample_time from a mix of continuous "
                            "and discrete upstream blocks; using discrete min=%g "
                            "(no implicit ZOH inserted)",
                            b.id,
                            distinct[0],
                        )
                    b._resolved_sample_time = float(distinct[0])
                continue
            raise BlockSpecError(f"Block {b.id!r}: invalid sample_time={st}")

    def _compute_dt_base(self) -> float:
        """基本ステップ ``dt_base`` と各ブロックの ``_step_ratio`` を決定する。"""
        discrete_periods = [
            b._resolved_sample_time
            for b in self.blocks
            if b._resolved_sample_time is not None and b._resolved_sample_time > 0.0
        ]
        if self.dt_base_hint is not None:
            dt_base = self.dt_base_hint
        elif not discrete_periods:
            dt_base = self.dt
        else:
            dt_base_discrete = min(discrete_periods)
            ratios = [t / dt_base_discrete for t in discrete_periods]
            non_integer = [
                (t, r)
                for t, r in zip(discrete_periods, ratios, strict=True)
                if abs(r - round(r)) > _SAMPLE_TIME_RATIO_TOL
            ]
            if non_integer:
                _logger.warning(
                    "Sample times %s are not integer multiples of base step %g; "
                    "rounding ratios to nearest integer (this may cause off-by-one "
                    "drift in long simulations)",
                    [t for t, _ in non_integer],
                    dt_base_discrete,
                )
            dt_base = min(dt_base_discrete, self.dt)

        if dt_base <= 0.0:
            raise SchedulingError(f"Computed dt_base={dt_base} is non-positive")

        for b in self.blocks:
            t = b._resolved_sample_time
            if t is None or t == 0.0:
                b._step_ratio = 1
            else:
                ratio = t / dt_base
                b._step_ratio = max(1, int(round(ratio)))
        return dt_base

    def _state_layout(self) -> tuple[list[tuple[Block, slice]], int]:
        """連続状態 (``sample_time is None``) のブロックだけをレイアウト。"""
        layout: list[tuple[Block, slice]] = []
        offset = 0
        for b in self.blocks:
            if b.n_states > 0 and b._resolved_sample_time is None:
                layout.append((b, slice(offset, offset + b.n_states)))
                offset += b.n_states
        return layout, offset

    def _init_discrete_state(self) -> dict[Block, npt.NDArray[Any]]:
        return {
            b: np.asarray(b.x0, dtype=float).copy()
            for b in self.blocks
            if b.n_states > 0 and b._resolved_sample_time is not None
        }

    def _step(
        self,
        t: float,
        x_cont: npt.NDArray[Any],
        discrete_state: dict[Block, npt.NDArray[Any]],
        order: list[Block],
        layout: list[tuple[Block, slice]],
    ) -> tuple[dict[Block, npt.NDArray[Any]], dict[Block, npt.NDArray[Any]]]:
        """1 時刻での SM-A scalar-port 用出力計算 (既存 hot path、ADR-0017 §(4))。

        全ブロック port_shape == () の場合に呼ばれる。各 ``inputs[b]`` / ``outputs[b]`` は
        1D ndarray (shape ``(n_inputs,)`` / ``(n_outputs,)``)。

        戻り値の ``inputs`` 辞書は **全ブロック** (direct_feedthrough の真偽によらず)
        について ``inputs[b]`` を持つ。direct_feedthrough=True はパス 1 で、
        False はパス 2 で書き込まれる。
        """
        cont_state = {b: x_cont[sl] for b, sl in layout}
        outputs: dict[Block, npt.NDArray[Any]] = {}
        inputs: dict[Block, npt.NDArray[Any]] = {}

        def state_for(b: Block) -> npt.NDArray[Any]:
            if b in cont_state:
                return cont_state[b]
            if b in discrete_state:
                return discrete_state[b]
            return np.zeros(0)

        for b in order:
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
            # ADR-0056 §C-3: 例外時に runtime が関与ブロックを payload に詰めるため
            # output 呼出直前で current_block を更新する。
            self._current_block = b
            y = np.atleast_1d(np.asarray(b.output(t, xb, u), dtype=float))
            outputs[b] = y
        self._current_block = None
        for b in order:
            if not b.direct_feedthrough:
                u = np.zeros(b.n_inputs)
                for i, src in enumerate(b.input_sources):
                    if src is not None:
                        sb, si = src
                        u[i] = outputs[sb][si]
                inputs[b] = u
        return outputs, inputs

    def _step_vector(
        self,
        t: float,
        x_cont: npt.NDArray[Any],
        discrete_state: dict[Block, npt.NDArray[Any]],
        order: list[Block],
        layout: list[tuple[Block, slice]],
    ) -> tuple[
        dict[Block, tuple[npt.NDArray[Any], ...]], dict[Block, tuple[npt.NDArray[Any], ...]]
    ]:
        """ADR-0017 §(4) SM-B vector-port 用出力計算。

        各ブロックの ``output_v`` を呼び、tuple of ndarrays でポート間の信号を
        伝搬する。``port_shapes_in/out`` で宣言された shape を尊重する。

        戻り値の ``outputs`` / ``inputs`` 辞書は ``tuple[ndarray, ...]`` 形式。
        SM-A 互換ブロックは ``Block.output_v`` の default 実装が ``output`` を wrap
        するため、混在モデルでも動作する。
        """
        cont_state = {b: x_cont[sl] for b, sl in layout}
        outputs: dict[Block, tuple[npt.NDArray[Any], ...]] = {}
        inputs: dict[Block, tuple[npt.NDArray[Any], ...]] = {}

        def state_for(b: Block) -> npt.NDArray[Any]:
            if b in cont_state:
                return cont_state[b]
            if b in discrete_state:
                return discrete_state[b]
            return np.zeros(0)

        def _zero_inputs(b: Block) -> tuple[npt.NDArray[Any], ...]:
            return tuple(np.zeros(shape, dtype=float) for shape in b.port_shapes_in)

        def _gather_inputs(b: Block) -> tuple[npt.NDArray[Any], ...]:
            u_list: list[npt.NDArray[Any]] = []
            for i, src in enumerate(b.input_sources):
                if src is None:
                    u_list.append(np.zeros(b.port_shapes_in[i], dtype=float))
                else:
                    sb, si = src
                    u_list.append(outputs[sb][si])
            return tuple(u_list)

        for b in order:
            if b.direct_feedthrough:
                u = _gather_inputs(b)
                inputs[b] = u
            else:
                u = _zero_inputs(b)
            xb = state_for(b)
            y = b.output_v(t, xb, u)
            # output_v を直接 override したブロック (Mux/Demux 等) が n_outputs と
            # 異なる長さの tuple を返すと、後続の signal 伝搬で IndexError や shape
            # mismatch のような不可解な error になり debug が困難。ここで明示的に
            # 拒否しておく (Block.output_v の default wrapper には長さ check がある
            # が、override 経路はそれを通らない)。
            if len(y) != b.n_outputs:
                raise BlockSpecError(
                    f"{type(b).__name__} {b.id!r}.output_v returned {len(y)} "
                    f"output(s), expected {b.n_outputs}"
                )
            outputs[b] = tuple(np.asarray(yi, dtype=float) for yi in y)
        for b in order:
            if not b.direct_feedthrough:
                inputs[b] = _gather_inputs(b)
        return outputs, inputs

    def compile(
        self,
        *,
        backend: Literal["jax", "numpy"] = "jax",
    ) -> CompiledSimulator:
        """純粋関数表現を生成して compile (= XLA HLO 化、ADR-0037 §Decision §(2))。

        Phase 5b で導入された opt-in API。``backend="jax"`` の場合 ``jax.jit`` で
        XLA 化、``backend="numpy"`` の場合は numpy 参照実装。``Simulator.run()``
        (= numpy ホットパス) は本メソッドを呼び出さない限り影響を受けない (=
        ADR-0036 §(8) / ADR-0037 §Decision §(8) 数値完全不変ガード)。

        Args:
            backend: ``"jax"`` (default、jax.jit + XLA) または ``"numpy"`` (= numpy
                参照実装、テスト / debug 用)。

        Returns:
            :class:`pyflw.compile.CompiledSimulator`。``linearize()`` で
            ``jax.jacfwd`` 経由の機械精度線形化、``step()`` / ``run()`` は v0.17.1+
            で本格実装される。

        Raises:
            ImportError: ``backend="jax"`` で ``pyflw[codegen]`` 未インストール。
            BlockSpecError: モデル内に Codegen 不可能なブロック (= 内部に
                ``Trigger`` / ``Enable`` control block を持つ ``Subsystem``、MVP では
                Python fallback 必須、ADR-0058 §論点 5) がある。
            ValueError: ``backend`` が ``"jax"`` / ``"numpy"`` 以外。

        Examples:
            >>> from pyflw import Simulator
            >>> sim = Simulator()
            >>> # ... add blocks ...
            >>> compiled = sim.compile(backend="jax")  # doctest: +SKIP
            >>> ls = compiled.linearize()  # 機械精度 Jacobian (= ADR-0037 §(3))
        """
        from ..compile.compiled_simulator import _build_compiled_simulator

        return _build_compiled_simulator(self, backend=backend)

    def run(self) -> None:
        """シミュレーションを実行する。

        ハイブリッド (連続+離散) ループ (ADR-0015 §(1)、ADR-0014 §(1) を multi-rate
        互換のため再更新):

        - [A'] 離散ブロック update (発火条件 ``k % step_ratio == 0``、output 計算の
          **前**、2-pass approach):

          1. pre-fire の ``discrete_state`` で 1 回目の ``_step`` を呼び ``inputs`` を
             組み立てる (output は前状態を見る)
          2. fire 条件を満たすブロックに ``update(t_k, x_b, inputs[b])`` を呼んで
             ``next_discrete`` に書き込む (double buffering で同時刻発火を整合)
          3. ``discrete_state = next_discrete`` で一斉差し替え
        - [A]  post-fire の ``discrete_state`` で 2 回目の ``_step`` を呼び
          ``outputs`` / ``inputs`` を再計算 (Scope record と f_continuous が使う)
        - [E]  ``record(t_k, inputs)`` (Scope 等)
        - [B]  連続部分を ``solve_ivp`` で 1 ステップ進める ``[t_k, t_{k+1}]``

        ADR-0015 で ADR-0014 の multi-rate off-by-one を根本解決した。fire を
        ``[A]`` の前に置くことで、サンプル境界 ``t = n*sample_time`` で update が
        呼ばれ、UnitDelay の出力が ``y(n*T) = u((n-1)*T)`` (リファレンスツール semantics) と
        一致する (single-rate / multi-rate 両方)。

        実装は SM-A / SM-B モードで完全分離 (ADR-0018 §(2) R-A): モード判定後、
        ``_run_sm_a_loop`` (既存ホットパス) または ``_run_sm_b_loop`` (vector port
        対応) に委譲する。各ループのステップラベル ``[A']`` / ``[A]`` / ``[E]`` /
        ``[B]`` は両 method 内のコメントを参照。
        """
        # code-reviewer SHOULD-2: 前回 run() の失敗で残った ``_current_block`` を
        # 明示的にクリア (= 再利用 Simulator で「失敗後すぐ build_failure_payload
        # を呼ぶと前回の block が拾われる」リスクを除去)。
        self._current_block = None
        order = self._execution_order()
        # ADR-0017 §(8) U2 / ADR-0018 §(2): SM-A / SM-B モード判定。``_execution_order()``
        # で全ブロックの ``_build()`` (Subsystem の n_states 確定など) と port shape
        # check が完了したあと判定する。SM-A モード (全ポート shape == ()) なら既存の
        # 高速 _step パス、SM-B モード (任意 vector port あり) は _step_vector パスを使う。
        sm_a_mode = self._is_sm_a_mode()
        if not sm_a_mode:
            # ADR-0018 §(3) S-A: Scope は SM-A only。SM-B 信号を Scope に直接繋ぐと
            # build 時に明示エラー (Demux 経由を誘導)。
            self._check_scope_inputs_are_scalar()
            # ADR-0018 §(4.3): SM-B Subsystem は Phase 4 まで run 不可。silent 破損
            # を避けるため build 時に明示拒否。
            self._check_subsystem_sm_b_unsupported()
        self._resolve_sample_times(order)
        dt_base = self._compute_dt_base()
        layout, n_total = self._state_layout()

        x_cont = np.zeros(n_total)
        for b, sl in layout:
            x_cont[sl] = np.asarray(b.x0, dtype=float)

        discrete_state = self._init_discrete_state()

        for b in self.blocks:
            if hasattr(b, "reset"):
                b.reset()

        # ADR-0042 §論点 1-A: ``t_end = math.inf`` (unbounded) では n_steps を
        # 計算せず ``None`` として、ループ側で `_stop_requested` のみで終了させる。
        # 有限値の場合は従来通り ``int(round(t_end / dt_base))`` で打ち切り。
        is_unbounded = math.isinf(self.t_end)
        if is_unbounded:
            # ADR-0042 §論点 2-A: unbounded run で Scope(buffer_mode="unbounded")
            # を使うと OOM 必至なので build 時に reject。
            for b in self.blocks:
                buffer_mode = getattr(b, "buffer_mode", None)
                if buffer_mode == "unbounded":
                    raise BlockSpecError(
                        f"Scope {b.id!r}: buffer_mode='unbounded' is not allowed "
                        f"when t_end=inf (would OOM). Use buffer_mode='ring' "
                        f"(default) or 'bounded'."
                    )
            n_steps: int | None = None
        else:
            n_steps = int(round(self.t_end / dt_base))
            if n_steps < 1:
                raise SchedulingError(
                    f"t_end={self.t_end}, dt_base={dt_base}: computed n_steps={n_steps} < 1"
                )

        # 停止フラグはこの run() 呼び出しの間だけ有効。前回の値が残っているのを
        # ここでクリアする。
        self._stop_requested = False

        # ADR-0018 §(2) R-A: SM-A / SM-B run path 完全分離。SM-A モードでは
        # 既存ホットパスを完全に維持 (= 541 件テストへの影響ゼロ)。
        # f_continuous は loop method 内で定義する (= ``discrete_state`` の再代入を
        # closure が正しく拾えるようにする)。
        if sm_a_mode:
            self._run_sm_a_loop(n_steps, dt_base, n_total, order, layout, x_cont, discrete_state)
        else:
            self._run_sm_b_loop(n_steps, dt_base, n_total, order, layout, x_cont, discrete_state)

    def _run_sm_a_loop(
        self,
        n_steps: int | None,
        dt_base: float,
        n_total: int,
        order: list[Block],
        layout: list[tuple[Block, slice]],
        x_cont: npt.NDArray[Any],
        discrete_state: dict[Block, npt.NDArray[Any]],
    ) -> None:
        """SM-A モードのメインループ (ADR-0014/0015 §(1) と完全同一)。

        ``f_continuous`` を本 method 内で定義することで、ループ内の
        ``discrete_state = next_discrete`` 再代入を closure が正しく追跡する
        (= ADR-0014 §Risks #3 で確認した nonlocal capture セマンティクス)。

        ADR-0042 §論点 1-A: ``n_steps is None`` のとき unbounded ループ
        (= ``self.t_end = math.inf``)。終了は ``self._stop_requested`` のみ。
        """

        def f_continuous(t: float, x: npt.NDArray[Any]) -> npt.NDArray[Any]:
            _, ins = self._step(t, x, discrete_state, order, layout)
            xdot = np.zeros(n_total)
            for b, sl in layout:
                # ADR-0056 §C-3: derivative 内例外時に関与ブロックを記録。
                self._current_block = b
                xdot[sl] = np.asarray(b.derivative(t, x[sl], ins[b]), dtype=float)
            self._current_block = None
            return xdot

        k = 0
        while True:
            t = k * dt_base

            # [A'] 離散ブロックの状態更新 (ADR-0015 §(1)、output 計算の前)。
            if discrete_state:
                _, inputs_pre = self._step(t, x_cont, discrete_state, order, layout)
                next_discrete: dict[Block, npt.NDArray[Any]] = dict(discrete_state)
                for b in order:
                    if b not in discrete_state:
                        continue
                    if k % b._step_ratio == 0:
                        x_b = discrete_state[b]
                        u_b = inputs_pre.get(b, np.zeros(b.n_inputs))
                        # ADR-0056 §C-3: discrete update 例外時のブロック記録。
                        self._current_block = b
                        next_discrete[b] = np.array(b.update(t, x_b, u_b), dtype=float)
                self._current_block = None
                # closure 共有のため in-place update (= 同じ dict 参照を維持)。
                # f_continuous / f_continuous_vector が discrete_state を closure で
                # capture しているため、再代入では新値が見えない (ADR-0018 修正)。
                discrete_state.clear()
                discrete_state.update(next_discrete)

            # [A] 出力計算 2 パス (post-fire の discrete_state を反映)
            outputs, inputs = self._step(t, x_cont, discrete_state, order, layout)
            # [E] record (Scope 等)
            self._record(t, inputs)

            if self.on_step_callback is not None:
                cont = self.on_step_callback(t, self.t_end)
                if cont is False:
                    return
            if self._stop_requested:
                return

            # 終了判定: 有限 t_end (n_steps int) では k == n_steps で break、
            # unbounded (n_steps None) では _stop_requested のみが終了条件。
            if n_steps is not None and k == n_steps:
                break

            # [B] 連続部分の積分 [t_k, t_{k+1}]
            if n_total > 0:
                t_next = (k + 1) * dt_base
                sol = solve_ivp(
                    f_continuous,
                    (t, t_next),
                    x_cont,
                    t_eval=[t_next],
                    method=self.solver,
                    rtol=self.rtol,
                    atol=self.atol,
                    max_step=dt_base,
                )
                if not sol.success:
                    raise SolverError(f"Solver failed at t=[{t}, {t_next}]: {sol.message}")
                x_cont = sol.y[:, -1]
            k += 1

    def _run_sm_b_loop(
        self,
        n_steps: int | None,
        dt_base: float,
        n_total: int,
        order: list[Block],
        layout: list[tuple[Block, slice]],
        x_cont: npt.NDArray[Any],
        discrete_state: dict[Block, npt.NDArray[Any]],
    ) -> None:
        """SM-B (vector ports) モード用メインループ (ADR-0018 §(2))。

        構造は SM-A と同一だが、各ステップ内で ``_step_vector`` を呼んで
        ``inputs[b]: tuple[npt.NDArray[Any], ...]`` で signal を伝搬する。``record`` は
        SM-A 入力 (rank-0 scalar) のみを Scope に渡すため、Scope 側に SM-B 信号が
        来るとビルド時に既に拒否されている (``_check_scope_inputs_are_scalar``)。

        ``f_continuous_vector`` を本 method 内で定義することで closure が正しく
        ``discrete_state`` 再代入を追跡する (SM-A と同じ理由)。

        ADR-0042 §論点 1-A: ``n_steps is None`` のとき unbounded ループ
        (= ``self.t_end = math.inf``)。終了は ``self._stop_requested`` のみ。
        """

        def f_continuous_vector(t: float, x: npt.NDArray[Any]) -> npt.NDArray[Any]:
            # ADR-0018 §(2)(4): SM-B run path。``_step_vector`` から得た
            # ``inputs[b]`` は tuple of ndarrays。SM-A 連続ブロックは SM-A
            # ``derivative(t, x, u_1d)`` を期待するため、tuple を 1D ndarray に
            # concat (= rank-0 element を順に並べる) する wrapper で互換性を保つ。
            # SM-B-aware 連続ブロック (Phase 4+) は ``derivative_v`` を将来追加。
            _, ins = self._step_vector(t, x, discrete_state, order, layout)
            xdot = np.zeros(n_total)
            for b, sl in layout:
                u_tuple = ins[b]
                u_1d = np.array(
                    [float(np.asarray(ui).item()) for ui in u_tuple],
                    dtype=float,
                )
                # ADR-0056 §C-3: SM-B derivative 例外時のブロック記録。
                self._current_block = b
                xdot[sl] = np.asarray(b.derivative(t, x[sl], u_1d), dtype=float)
            self._current_block = None
            return xdot

        k = 0
        while True:
            t = k * dt_base

            # [A'] 離散ブロック update (SM-B path)
            if discrete_state:
                _, inputs_pre_v = self._step_vector(t, x_cont, discrete_state, order, layout)
                next_discrete: dict[Block, npt.NDArray[Any]] = dict(discrete_state)
                for b in order:
                    if b not in discrete_state:
                        continue
                    if k % b._step_ratio == 0:
                        x_b = discrete_state[b]
                        u_tuple = inputs_pre_v.get(
                            b, tuple(np.zeros(s, dtype=float) for s in b.port_shapes_in)
                        )
                        # SM-B 離散ブロックは Phase 3 では存在しない。SM-A 互換
                        # wrapper: tuple of rank-0 → 1D ndarray
                        u_1d = np.array(
                            [float(np.asarray(ui).item()) for ui in u_tuple],
                            dtype=float,
                        )
                        # ADR-0056 §C-3: SM-B discrete update 例外時の記録。
                        self._current_block = b
                        next_discrete[b] = np.array(b.update(t, x_b, u_1d), dtype=float)
                self._current_block = None
                # closure 共有のため in-place update (= 同じ dict 参照を維持)。
                # f_continuous / f_continuous_vector が discrete_state を closure で
                # capture しているため、再代入では新値が見えない (ADR-0018 修正)。
                discrete_state.clear()
                discrete_state.update(next_discrete)

            # [A] 2nd pass (post-fire)
            _, inputs_v = self._step_vector(t, x_cont, discrete_state, order, layout)
            # [E] record: SM-B 信号は Scope で拒否済み。SM-A scalar 入力を持つ
            # ブロック (Scope 含む) は inputs_v[b] が rank-0 ndarray のタプルなので、
            # SM-A の ``_record`` が期待する 1D ndarray に変換する。
            self._record_v(t, inputs_v)

            if self.on_step_callback is not None:
                cont = self.on_step_callback(t, self.t_end)
                if cont is False:
                    return
            if self._stop_requested:
                return

            # 終了判定: 有限 t_end (n_steps int) では k == n_steps で break、
            # unbounded (n_steps None) では _stop_requested のみが終了条件。
            if n_steps is not None and k == n_steps:
                break

            # [B] 連続積分 (SM-B 版 f_continuous_vector)
            if n_total > 0:
                t_next = (k + 1) * dt_base
                sol = solve_ivp(
                    f_continuous_vector,
                    (t, t_next),
                    x_cont,
                    t_eval=[t_next],
                    method=self.solver,
                    rtol=self.rtol,
                    atol=self.atol,
                    max_step=dt_base,
                )
                if not sol.success:
                    raise SolverError(f"Solver failed at t=[{t}, {t_next}]: {sol.message}")
                x_cont = sol.y[:, -1]
            k += 1

    def _record(self, t: float, inputs: dict[Block, npt.NDArray[Any]]) -> None:
        for b in self.blocks:
            if hasattr(b, "record"):
                b.record(t, inputs[b])

    def request_stop(self) -> None:
        """別スレッドからの graceful 停止要求 (ADR-0011 §(4))。

        ``run()`` ループ中の各ステップ末尾でフラグがチェックされ、True であれば
        その時点までの結果を保ったまま戻る。``Scope`` 等の record も停止時点までの
        値を保持する。
        """
        self._stop_requested = True

    def linearize(
        self,
        *,
        t: float = 0.0,
        x: npt.NDArray[Any] | None = None,
        u: npt.NDArray[Any] | None = None,
        method: Literal["central", "forward", "jax"] = "central",
        epsilon: float | None = None,
    ) -> LinearSystem:
        """動作点 ``(t, x, u)`` 周りでモデルを線形化する (ADR-0026)。

        ``pyflw.linearize(self, ...)`` の薄いラッパ。詳細は
        :func:`pyflw.analysis.linearize` を参照。

        Args:
            t: 動作点時刻 [s]。default ``0.0``。
            x: 連続状態の動作点 (shape ``(n_states,)``)。``None`` で各ブロックの
                ``x0`` を ``_state_layout()`` 順に concat したもの。
            u: 外部入力の動作点 (shape ``(n_inputs_total,)``)。``None`` で全ゼロ。
            method: ``"central"`` (default) / ``"forward"``。``"jax"`` は Phase 5+ 予約。
            epsilon: 摂動相対 step。``None`` で次元ごと自動 (``sqrt(eps_machine)``)。

        Returns:
            :class:`pyflw.analysis.LinearSystem`。

        Example:
            >>> ls = sim.linearize()  # doctest: +SKIP
            >>> isinstance(ls.A, np.ndarray)  # doctest: +SKIP
            True
        """
        # 循環 import 回避のため遅延 import
        from ..analysis.linearize import linearize as _linearize

        return _linearize(self, t=t, x=x, u=u, method=method, epsilon=epsilon)

    @property
    def is_stopped(self) -> bool:
        """直前の ``run()`` が ``request_stop()`` で打ち切られたかを示すフラグ。

        サーバ側 (ADR-0011) が `_stop_requested` プライベート属性に直接触れずに
        終了状態を判定するために使う公開 API。
        """
        return self._stop_requested

    def save(
        self,
        path: str | Path,
        *,
        indent: int = 2,
        layout: LayoutDict | None = None,
    ) -> None:
        """モデル定義 (ブロック・結線・Simulator 設定) を JSON ファイルに保存する。

        ADR-0008 で確定した canonical 形式で出力する。``run()`` 後の状態 (Scope
        バッファ、積分結果) は保存対象外。

        Args:
            path: 保存先パス (``.flw.json`` 拡張子を推奨)。
            indent: ``json.dumps`` のインデント (default ``2``)。``0`` 以下を渡すと
                ``json.dumps`` を ``indent=None`` で呼び、改行・インデントなしの
                compact 出力 (機械可読向け) になる。
            layout: 各 block の GUI 上の位置 (ADR-0020)。``{"<block_id>":
                {"x": float, "y": float}, ...}`` 形式。``None`` または空 dict のとき
                top-level ``layout`` キーを書き出さない (= byte-identical for
                CLI/pytest ユースケース)。

        Raises:
            ModelSerializationError: ブロックパラメータが JSON-serializable でない、
                または ``__main__`` モジュールで定義された class を含む場合。
            ModelLoadError: ``layout`` が ``LayoutDict`` 形式に正規化できない場合。
        """
        from .. import __version__ as _pyflw_version

        normalized_layout = normalize_layout(layout)

        payload: dict[str, Any] = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "metadata": {
                "created_at": datetime.datetime.now(datetime.UTC)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
                "tool": f"pyflw {_pyflw_version}",
            },
            "simulator": {
                # ADR-0042 §論点 4-A: ``math.inf`` のときは ``"inf"`` 文字列で
                # 永続化 (= JSON RFC 8259 違反の `"Infinity"` を避ける)
                "t_end": serialize_t_end(self.t_end),
                "dt": float(self.dt),
                "solver": str(self.solver),
                "rtol": float(self.rtol),
                "atol": float(self.atol),
                "dt_base": (None if self.dt_base_hint is None else float(self.dt_base_hint)),
            },
            "blocks": [b.to_dict() for b in self.blocks],
            "connections": serialize_connections(self.blocks),
        }
        # ADR-0020 §Decision (1): キー順序 = blocks → connections → layout の末尾。
        if normalized_layout is not None:
            block_ids = {b.id for b in self.blocks}
            for stale_id in [k for k in normalized_layout if k not in block_ids]:
                _logger.warning(
                    "Simulator.save: layout entry %r refers to unknown block id; "
                    "dropping (block was likely deleted)",
                    stale_id,
                )
                del normalized_layout[stale_id]
            if normalized_layout:
                # blocks 順に揃えて canonical な diff を出す (ADR-0020 §Decision (1))
                ordered: LayoutDict = {
                    b.id: normalized_layout[b.id] for b in self.blocks if b.id in normalized_layout
                }
                payload["layout"] = ordered
        text = json.dumps(payload, indent=indent if indent > 0 else None)
        Path(path).write_text(text + ("\n" if indent > 0 else ""), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> Simulator:
        """JSON ファイルからモデルを再構築する (ADR-0008)。

        Args:
            path: 読み込みパス。

        Returns:
            復元された ``Simulator`` インスタンス (``run()`` 前の状態)。

        Raises:
            ModelLoadError: JSON パース失敗、必須キー欠落、構造不正など。
            SchemaVersionError: サポート外の ``schema_version``。
            UnknownBlockTypeError: ブロック ``type`` 解決失敗。
        """
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as e:
            raise ModelLoadError(f"Cannot read model file {path!r}: {e}") from e
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ModelLoadError(f"Invalid JSON in {path!r}: {e}") from e
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Any) -> Simulator:
        """parsed JSON 値から ``Simulator`` を再構築する (ADR-0041 §論点 5-A)。

        ``Simulator.load`` の dict → Simulator 部分を分離した public API。schema
        migration、ブロック復元、接続復元、layout 復元の全工程を実行する。
        REST ``/api/v1/simulations`` のインライン model 実行 (= 未保存
        editingModel をそのまま走らせる UX) で利用される。

        Args:
            data: ``json.loads`` の戻り値そのまま (= 任意の JSON 値)。dict で
                ない場合は ``ModelLoadError``。``Any`` 型にしているのは public
                API として「外部 JSON ソース直渡し」を許容するため (= caller が
                isinstance チェックを重複して書かないで済む、code-reviewer
                MUST 修正)。

        Returns:
            復元された ``Simulator`` インスタンス (``run()`` 前の状態)。

        Raises:
            ModelLoadError: top-level が dict でない、必須キー欠落、構造不正、
                ブロック復元失敗など。
            SchemaVersionError: サポート外の ``schema_version``。
            UnknownBlockTypeError: ブロック ``type`` 解決失敗。
        """
        if not isinstance(data, dict):
            raise ModelLoadError(f"Top-level JSON must be an object, got {type(data).__name__}")
        data = migrate_to_current(data)

        for key in ("simulator", "blocks", "connections"):
            if key not in data:
                raise ModelLoadError(f"Missing required key {key!r} in JSON model")
        sim_cfg = data["simulator"]
        for key in ("t_end", "dt", "solver", "rtol", "atol", "dt_base"):
            if key not in sim_cfg:
                raise ModelLoadError(f"Missing simulator setting {key!r}")

        try:
            sim = cls(
                t_end=sim_cfg["t_end"],
                dt=sim_cfg["dt"],
                solver=sim_cfg["solver"],
                rtol=sim_cfg["rtol"],
                atol=sim_cfg["atol"],
                dt_base=sim_cfg["dt_base"],
            )
        except (ValueError, TypeError) as e:
            raise ModelLoadError(f"Invalid simulator configuration: {e}") from e

        for b_data in data["blocks"]:
            if not isinstance(b_data, dict):
                raise ModelLoadError(
                    f"Each block entry must be an object, got {type(b_data).__name__}"
                )
            for key in ("id", "type", "params"):
                if key not in b_data:
                    raise ModelLoadError(f"Block entry missing required key {key!r}: {b_data!r}")
            block_cls = resolve_block_class(b_data["type"])
            # ADR-0017 §(5): SM-B port_shapes は optional フィールドとして JSON に
            # 入る。`__init__` の kwargs として渡すため取り出す (default は None)。
            extra_kwargs: dict[str, Any] = {}
            if "port_shapes_in" in b_data:
                extra_kwargs["port_shapes_in"] = [tuple(s) for s in b_data["port_shapes_in"]]
            if "port_shapes_out" in b_data:
                extra_kwargs["port_shapes_out"] = [tuple(s) for s in b_data["port_shapes_out"]]
            try:
                # Subsystem は ``_from_dict`` factory 経由で復元する (内部 blocks
                # の dict を resolve_block_class で展開するため)。それ以外の通常
                # ブロックは ``__init__`` で直接構築。
                if hasattr(block_cls, "_from_dict") and callable(block_cls._from_dict):
                    block = block_cls._from_dict(
                        id=b_data["id"], **b_data["params"], **extra_kwargs
                    )
                else:
                    block = block_cls(id=b_data["id"], **b_data["params"], **extra_kwargs)
            except (TypeError, ValueError, BlockSpecError) as e:
                # BlockSpecError: __init__ 検証エラー (e.g. LookupTable1D の breakpoints
                # 非単調) も ModelLoadError にラップし、ロード時に実行前で拒否する
                # (ADR-0008 セマンティクス + SPEC-0008 §エッジケース)。
                raise ModelLoadError(
                    f"Cannot instantiate block {b_data['id']!r} of type {b_data['type']!r}: {e}"
                ) from e
            sim.add(block)

        for c_data in data["connections"]:
            if not isinstance(c_data, dict):
                raise ModelLoadError(
                    f"Each connection entry must be an object, got {type(c_data).__name__}"
                )
            for key in ("src", "dst", "src_idx", "dst_idx"):
                if key not in c_data:
                    raise ModelLoadError(
                        f"Connection entry missing required key {key!r}: {c_data!r}"
                    )
            try:
                sim.connect(
                    c_data["src"],
                    c_data["dst"],
                    src_idx=int(c_data["src_idx"]),
                    dst_idx=int(c_data["dst_idx"]),
                )
            except (IndexError, ValueError, UnknownBlockIdError) as e:
                raise ModelLoadError(f"Invalid connection {c_data!r}: {e}") from e

        # ADR-0020 §Decision (3): top-level layout を読み取り、stale id を破棄して
        # ``last_loaded_layout`` に保持する。layout 欠落 (旧バージョン or layout-less
        # ファイル) では ``None`` のまま (GUI 側で grid auto-layout fallback)。
        raw_layout = data.get("layout")
        normalized = normalize_layout(raw_layout)
        if normalized is not None:
            block_ids = {b.id for b in sim.blocks}
            for stale in [k for k in normalized if k not in block_ids]:
                _logger.warning(
                    "Simulator.load: layout entry %r refers to unknown block id; "
                    "dropping (stale layout)",
                    stale,
                )
                del normalized[stale]
            sim.last_loaded_layout = normalized if normalized else None

        return sim
