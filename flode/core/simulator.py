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
import numbers
from collections import defaultdict, deque
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
import numpy.typing as npt
from scipy.integrate import OdeSolver, solve_ivp

from ..exceptions import (
    AlgebraicLoopError,
    BlockSpecError,
    ModelLoadError,
    PortIndexError,
    SchedulingError,
    SolverError,
    UnknownBlockIdError,
)
from .block import BASE_CLOCK_SAMPLE_TIME, Block
from .identifiers import fold_block_id, normalize_block_id, validate_block_id
from .persistence import (
    CURRENT_SCHEMA_VERSION,
    LayoutDict,
    migrate_to_current,
    normalize_layout,
    normalize_model_ids,
    parse_t_end,
    resolve_block_class,
    serialize_connections,
    serialize_t_end,
)
from .signals import cast_value

if TYPE_CHECKING:  # pragma: no cover - 循環 import 回避
    from ..analysis.linearize import LinearSystem
    from .signals import SignalResolution

#: ADR-0079 §(2) (SPEC-0028 §3.7 の拡張): 実行順 (order) と並行に並べた
#: ``(in_shapes, in_dtypes, out_shapes, out_dtypes)`` の列。hot loop で辞書引き
#: しないための前処理形。``_step_vector`` はブロックの宣言ではなくこれを読む。
SignalPlan = list[
    tuple[
        tuple[tuple[int, ...], ...],
        tuple[np.dtype[Any], ...],
        tuple[tuple[int, ...], ...],
        tuple[np.dtype[Any], ...],
    ]
]


def _build_signal_plan(order: list[Block], resolution: SignalResolution) -> SignalPlan:
    """解決結果を実行順並行の signal plan へ前処理する (ADR-0079 §(2))。

    materialize 済みの full mode 結果を前提とするため、全ポートが語彙 5 種の
    dtype と確定 shape を持つ (unknown は来ない = 全域性 AC-3)。
    """
    plan: SignalPlan = []
    for b in order:
        bid = b.id if b.id is not None else "<unassigned>"
        in_keys = [(bid, "in", i) for i in range(b.n_inputs)]
        out_keys = [(bid, "out", j) for j in range(b.n_outputs)]
        in_shapes = tuple(_plan_shape(resolution, k) for k in in_keys)
        in_dts = tuple(np.dtype(resolution.ports[k]) for k in in_keys)
        out_shapes = tuple(_plan_shape(resolution, k) for k in out_keys)
        out_dts = tuple(np.dtype(resolution.ports[k]) for k in out_keys)
        plan.append((in_shapes, in_dts, out_shapes, out_dts))
    return plan


def _plan_shape(resolution: SignalResolution, key: tuple[str, str, int]) -> tuple[int, ...]:
    """plan 用の確定 shape (full mode では未確定は残らない — 残っていれば実装バグ)。"""
    shape = resolution.shapes[key]
    if shape is None:
        raise BlockSpecError(
            f"internal error: shape of port {key[0]!r}.{key[1]}[{key[2]}] is unresolved "
            "after full-mode signal resolution"
        )
    return shape


# ADR-0011 §(4): on_step_callback の型エイリアス
StepCallback = Callable[[float, float], bool]

_logger = logging.getLogger("flode.scheduler")
# ADR-0055 §論点 3 / SPEC-0003 §3-5: 仮想エッジ展開時の WARNING / INFO 専用
_logger_routing = logging.getLogger("flode.routing.goto")

_SAMPLE_TIME_RATIO_TOL = 1e-9

#: bug-fix 2026-09-13: 基準ステップ時刻 ``t = k * dt_base`` の丸め桁。float 乗算だと
#: ``3 * 0.3 = 0.8999999999999999`` のように真の格子点より僅かに小さくなり、
#: ``Step(step_time=0.9)`` / ``PulseGenerator(period=0.9)`` 等の時刻比較が
#: 1 サンプル遅れる。12 桁で丸めれば ``round(0.8999999999999999, 12) == 0.9``
#: (= リテラルと同じ double) になり、格子点上の境界判定が厳密に一致する。
_GRID_TIME_DECIMALS = 12
#: 丸め桁に対して 3 桁の余裕を持たせた基準ステップの下限 (= 1e-9 s)。
_MIN_DT_BASE = 10.0 ** -(_GRID_TIME_DECIMALS - 3)

#: ``scipy.integrate.solve_ivp`` の ``method`` 名 (frontend ModelSettingsModal の
#: SOLVER_OPTIONS と同じ集合)。構築時検証 (bug-fix 2026-09-14) の SSOT。
_SOLVER_METHODS: tuple[str, ...] = ("RK45", "RK23", "DOP853", "Radau", "BDF", "LSODA")


def _validate_positive_finite(name: str, value: Any) -> float:
    """``Simulator`` のソルバー設定値 (dt / rtol / atol / dt_base) を検証して float で返す。

    ``parse_t_end`` と同じく構築時に :class:`ModelLoadError` で拒否する
    (``Simulator.from_dict`` 経由でも同じ例外型になる)。
    """
    # 判定は parse_t_end (persistence.py) と同じ numbers.Real ベースに揃える
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ModelLoadError(f"Invalid {name}: must be a number, got {type(value).__name__}")
    f = float(value)
    if not math.isfinite(f) or f <= 0.0:
        raise ModelLoadError(f"Invalid {name}: must be a positive finite number, got {value!r}")
    return f


def _grid_time(k: int, dt_base: float) -> float:
    """``k`` 番目の基準ステップ時刻 (格子点に丸めた ``k * dt_base``)。"""
    return round(k * dt_base, _GRID_TIME_DECIMALS)


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
        solver: str | type[OdeSolver] = "RK45",
        rtol: float = 1e-6,
        atol: float = 1e-9,
        dt_base: float | None = None,
        on_step_callback: StepCallback | None = None,
    ) -> None:
        # ADR-0042 §論点 4-A: ``"inf"`` (case-insensitive) を受け入れて
        # ``math.inf`` に変換する。``parse_t_end`` で全 validation 一元化。
        self.t_end: float = parse_t_end(t_end)
        # bug-fix 2026-09-13: ソルバー設定も構築時に検証する (t_end と同じく
        # ModelLoadError)。従来 ``rtol <= 0`` は scipy が毎ステップ警告しつつ
        # ``100*eps`` に黙って丸め、``atol < 0`` は scipy の生の ValueError が
        # run() 途中で飛び、``atol == 0`` は状態 0 からの積分でステップ幅が 0 に
        # 収束して事実上停止していた。
        self.dt = _validate_positive_finite("dt", dt)
        # bug-fix 2026-09-14: solver 名も構築時に検証する。従来は連続状態があると
        # scipy の生 ValueError が run() 途中で飛び、無ければ黙って通っていた。
        if isinstance(solver, str):
            if solver not in _SOLVER_METHODS:
                raise ModelLoadError(
                    f"Invalid solver: {solver!r}. Supported: {', '.join(_SOLVER_METHODS)}"
                )
        elif not (isinstance(solver, type) and issubclass(solver, OdeSolver)):
            # scipy は OdeSolver サブクラスも受け付ける (Python API 専用、JSON 不可)
            raise ModelLoadError(
                f"Invalid solver: must be one of {', '.join(_SOLVER_METHODS)} or an "
                f"OdeSolver subclass, got {solver!r}"
            )
        self.solver: str | type[OdeSolver] = solver
        self.rtol = _validate_positive_finite("rtol", rtol)
        self.atol = _validate_positive_finite("atol", atol)
        self.dt_base_hint: float | None = (
            None if dt_base is None else _validate_positive_finite("dt_base", dt_base)
        )
        self.blocks: list[Block] = []
        self._blocks_by_id: dict[str, Block] = {}
        # ADR-0071 §(2): NFKC fold key → NFC id。重複判定専用 (``Gain_1`` と
        # 全角 ``Gain_１`` のような見た目類似 id の共存を拒否する)。
        # ``add`` / ``rename`` で ``_blocks_by_id`` と必ず併走更新する。
        self._folded_ids: dict[str, str] = {}
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
        # ADR-0079 §(2): run() が信号面解決の結果から作る実行時 plan
        # (shape + dtype)。None = 解決器を通らない従来経路 (= SM-A path)。
        # ``_step_vector`` が参照し、``plan is None`` が経路選択の唯一の判定。
        self._signal_plan: SignalPlan | None = None

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
            # ADR-0071 §(2): NFKC fold key での衝突 (全角/半角・互換文字違いの
            # 見た目類似 id) も拒否する
            existing = self._folded_ids.get(fold_block_id(block.id))
            if existing is not None:
                raise BlockSpecError(
                    f"Block id {block.id!r} conflicts with existing id "
                    f"{existing!r}: the two are NFKC-equivalent (visually "
                    f"confusable, e.g. full-width vs half-width). Choose a "
                    f"distinct name."
                )
        self._blocks_by_id[block.id] = block
        self._folded_ids[fold_block_id(block.id)] = block.id
        self.blocks.append(block)
        return block

    def _auto_id(self, block: Block) -> str:
        type_name = type(block).__name__
        n = self._type_counters.get(type_name, 0)
        candidate = f"{type_name}_{n}"
        # fold key での衝突もスキップする (全角形 ``Ｇａｉｎ＿０`` が既に居ても
        # 自動採番が例外を出さない、ADR-0071 §(2))
        while candidate in self._blocks_by_id or candidate in self._folded_ids:
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
        # ADR-0071 §(3): 入口層で NFC 正規化してから検証・比較する
        if isinstance(new_id, str):
            new_id = normalize_block_id(new_id)
        validate_block_id(new_id)
        if new_id == old_id:
            return
        if new_id in self._blocks_by_id:
            raise BlockSpecError(f"Block id {new_id!r} already exists")
        new_fold = fold_block_id(new_id)
        existing = self._folded_ids.get(new_fold)
        if existing is not None and existing != old_id:
            raise BlockSpecError(
                f"Block id {new_id!r} conflicts with existing id {existing!r}: "
                f"the two are NFKC-equivalent (visually confusable). Choose a "
                f"distinct name."
            )
        block = self._blocks_by_id.pop(old_id)
        del self._folded_ids[fold_block_id(old_id)]
        block.id = new_id
        self._blocks_by_id[new_id] = block
        self._folded_ids[new_fold] = new_id

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
        # ADR-0055 §論点 1-A: 各 ``b._build()`` 直後に仮想エッジ展開フェーズを
        # 挟む。Goto/From を含まないモデルは早期 return するため、既存テストへの
        # 影響ゼロ (= ADR-0036 §(8) 数値完全不変ガード)。
        # ADR-0079 D-11: port shape の検査はここでは行わない。トポロジカル順
        # (代数ループ検出) の後に信号面解決器 (``flode.core.signals``) が
        # 宣言との整合を検査する (= shape 不一致より代数ループが先に報告される)。
        self._resolve_goto_from_virtual_edges()
        deps: dict[Block, set[Block]] = {b: set() for b in self.blocks}
        rev: dict[Block, set[Block]] = defaultdict(set)
        for b in self.blocks:
            if b.direct_feedthrough:
                for src in b.input_sources:
                    if src is not None:
                        deps[b].add(src[0])
                        rev[src[0]].add(b)
            else:
                # bug-fix 2026-09-13: 非直達ブロックでも制御入力 (Enabled Subsystem
                # の enable ポート等) は output() 時点で必要 → そのポートだけ直達辺
                for i in b.control_input_ports:
                    src = b.input_sources[i]
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
                    b._df_extra_targets = set()

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
            # ADR-0079 D-2: shape はブロックへ書き戻さない。Goto/From の shape は
            # 信号面解決器が透過 (fanout) 規則で決め、plan にだけ置く
            # (ADR-0055 §論点 4-A の目的は保たれ、実装位置だけが移った)。
            # 解決済み Goto への参照を埋め込み (run 時に From.output が読む)
            from_block._resolved_goto = resolved_goto
            from_block._plan_out_shape = None
            # bug-fix 2026-09-13: Trigger / Enable 付き Subsystem の内部ブロックは
            # fire / enable 中にしか実行されないので、初回 fire 前は Goto が値を
            # 持たない。これはスケジューリングバグではなく「ホールド値がまだ無い」
            # 状態なので、From は 0 を返してよい (Outport の初期キャッシュと同じ)。
            resolved_goto._hold_before_first_run = any(
                getattr(s, "_has_trigger", False) or getattr(s, "_has_enable", False)
                for s in scope_of.get(resolved_goto, ())
            )
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
        # bug-fix 2026-09-13: 先に全対象を無効化してから build する。親の ``_build``
        # は内側の ``_build`` を先に呼ぶので、内側 Subsystem の direct_feedthrough
        # 再推論 (``_df_extra_targets`` 反映) が親の推論より必ず先に済む
        # (set の走査順に依存しない)。
        for sub in subsystems_with_goto_from:
            sub._exec_order = None
        for sub in subsystems_with_goto_from:
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
        # bug-fix 2026-09-13: From が Goto より上位スコープにいる場合、Goto を含む
        # 各祖先 Subsystem (共通祖先より下) に「外部から参照される到達目標」を
        # 登録する。Inport からその目標へ直達で到達できる Subsystem は直達扱いに
        # なり、パス 1 で実入力を使って Goto が値を記録する (非直達のままだと
        # 入力ゼロで記録した値を From が読んでしまう)。
        goto_path = goto_scope[common_len:]
        for depth, ancestor in enumerate(goto_path):
            target = goto_path[depth + 1] if depth + 1 < len(goto_path) else goto_block
            ancestor._df_extra_targets.add(target)
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

    def _record_v(
        self,
        t: float,
        inputs_v: dict[Block, tuple[npt.NDArray[Any], ...]],
    ) -> None:
        """SM-B run path 用の record。tuple-of-ndarray inputs を 1D ndarray に
        変換して既存 ``record(t, u_1d)`` に橋渡しする (ADR-0018 §(3))。

        ADR-0079 §(4): 各 input port の ndarray を **C order で列展開**して
        concat する (rank-0 は 1 列、``(3,)`` は 3 列、``(2, 2)`` は 4 列)。
        全ポート ``()`` なら従来の「rank-0 を順に並べた 1D」と同一。

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
            # tuple of ndarrays → 1D ndarray (C order 列展開、ADR-0079 §(4))
            if u_tuple:
                u_1d = np.concatenate(
                    [np.ravel(np.asarray(ui, dtype=float), order="C") for ui in u_tuple]
                )
            else:
                u_1d = np.zeros(0)
            b.record(t, u_1d)

    def _is_sm_a_mode(self) -> bool:
        """モデルが SM-A hot path (``_step``) で走るかの pre-filter 判定。

        ADR-0079 §(2): 経路選択の正は ``run()`` の ``plan is None``。本メソッドは
        その plan を作る条件の否定 (= dtype 宣言なし **かつ** shape 起点なし) を
        build 前でも答えられる形で返す (``has_shape_source`` は非 ``()`` の
        ``port_shapes_in/out`` 宣言と配列パラメータ ``Gain.k`` の O(V) 走査)。
        """
        from .signals import has_declared_dtype, has_shape_source

        return not (has_declared_dtype(self) or has_shape_source(self))

    def _resolve_sample_times(self, order: list[Block]) -> None:
        """サンプル時間のクロック解決 (SPEC-0030) を 2 相で行う。

        各ブロックの ``_resolved_sample_time`` 属性に決定値を格納する。
        元の ``sample_time`` 属性は変更しない。語彙:

        * ``None`` / ``0`` — 連続、``> 0`` — 明示周期 (系のクロック)
        * ``"dt"`` — 基準クロック (``self.dt``) に同期 (常に解決可能)
        * ``-1.0`` — 上流のレートに同期。上流に離散レートがなければ、
          離散専用ブロック (``requires_discrete_rate=True``) は
          ``BlockSpecError`` (fail-closed、"dt" と明示値を案内)。それ以外は
          連続 (``@block`` デコレータ製の意図されたポリモーフィズム、ADR-0003)

        相 1: 順序に依存しない解決 (連続 / 明示 / "dt") を全ブロックで先に確定。
        相 2: ``-1`` ブロックを、上流に未解決の ``-1`` が残っている間は先送り
        しながら固定点まで反復して解決する (v0.57.0 code-reviewer MUST 対応:
        追加順に依存しない)。``-1`` 同士の循環は「循環内上流 = レートなし」で
        一括判定する (決定的 — 離散専用ならエラー、それ以外は連続)。
        """
        pending: list[Block] = []
        for b in order:
            st = b.sample_time
            if st == BASE_CLOCK_SAMPLE_TIME:
                # SPEC-0030: 基準クロックへの明示同期。宣言なので警告は出さない
                b._resolved_sample_time = float(self.dt)
            elif st is None or st == 0.0:
                if b.requires_discrete_rate:
                    # security MUST-2 (2026-09-11): 離散専用ブロックを連続扱いに
                    # すると update() が呼ばれず x0 で無警告凍結する。-1 経路
                    # だけでなく 0 / None の直接指定でも同じ穴が開くため
                    # fail-closed に揃える
                    raise BlockSpecError(
                        f"Block {b.id!r}: sample_time={st!r} would make this "
                        "discrete-only block continuous (it would never update). "
                        f"Use a positive period, {BASE_CLOCK_SAMPLE_TIME!r} "
                        "(base clock dt), or -1.0 (inherited from upstream)."
                    )
                b._resolved_sample_time = None
            elif isinstance(st, (int, float)) and st > 0.0:
                b._resolved_sample_time = float(st)
            elif st == -1.0:
                if not any(src is not None for src in b.input_sources):
                    raise BlockSpecError(
                        f"Block {b.id!r} has sample_time=-1.0 (inherited) but no inputs"
                    )
                pending.append(b)
            else:
                raise BlockSpecError(f"Block {b.id!r}: invalid sample_time={st}")

        unresolved_ids = {id(b) for b in pending}

        def _resolve_inherited(b: Block) -> None:
            # 未解決の -1 上流は「レートなし」として読む (通常経路では未解決上流
            # ゼロを呼び出し側が保証するため inert。循環解決時のみ実効する)
            upstream: list[float | None] = [
                (None if id(src[0]) in unresolved_ids else src[0]._resolved_sample_time)
                for src in b.input_sources
                if src is not None
            ]
            discrete = [t for t in upstream if t is not None and t > 0.0]
            if not discrete:
                if b.requires_discrete_rate:
                    # SPEC-0030 (v0.58.0): 同期すべき上流レートが存在しない。
                    # 連続扱いは無警告凍結 (v0.57.0 で修正したバグ)、暗黙の dt
                    # フォールバックは 1 センチネル 2 意味の同居 (v0.57.0 案の
                    # 欠点) — どちらも取らず、案内板型エラーで明示を求める
                    raise BlockSpecError(
                        f"Block {b.id!r}: sample_time=-1.0 (inherited) but "
                        "no upstream block carries a discrete rate. Use "
                        f"sample_time={BASE_CLOCK_SAMPLE_TIME!r} to run on the "
                        "base clock (dt), or set an explicit period for a device "
                        "with its own clock."
                    )
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

        # 相 2: 上流の -1 が全て解決済みのブロックから順に解決 (固定点反復)
        while pending:
            deferred: list[Block] = []
            resolved_now: list[Block] = []
            for b in pending:
                has_unresolved_upstream = any(
                    src is not None and id(src[0]) in unresolved_ids for src in b.input_sources
                )
                if has_unresolved_upstream:
                    deferred.append(b)
                else:
                    _resolve_inherited(b)
                    resolved_now.append(b)
            if not resolved_now:
                # 進捗なし = -1 同士の循環。unresolved 集合を凍結したまま全員を
                # 「循環内上流 = レートなし」で一括解決する (循環内の処理順に
                # 結果が依存しないよう、解決済みへの昇格は行わない)
                for b in deferred:
                    _resolve_inherited(b)
                break
            for b in resolved_now:
                unresolved_ids.discard(id(b))
            pending = deferred

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
        # code-reviewer SHOULD (2026-09-13): 格子時刻を 12 桁で丸める (_grid_time)
        # ため、それより 3 桁の余裕を切る基準ステップでは隣接格子点が同じ値に
        # 丸まりうる (solve_ivp に長さ 0 の区間が渡る)。明示的に拒否する。
        if dt_base < _MIN_DT_BASE:
            raise SchedulingError(
                f"Computed dt_base={dt_base:g} is below the supported minimum "
                f"{_MIN_DT_BASE:g} (time grid is rounded to {_GRID_TIME_DECIMALS} decimals). "
                "Rescale the model's time unit instead of using such a small step."
            )

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
        # bug-fix 2026-09-13: ``n_states == 0`` でも離散レートを持つブロック
        # (例: 状態なし Triggered Subsystem) は ``update()`` の呼び出しが必要
        # (edge 検出 / 出力キャッシュ更新)。状態ベクトルは空 (shape (0,)) で登録する。
        return {
            b: np.asarray(b.x0, dtype=float).copy()
            for b in self.blocks
            if b._resolved_sample_time is not None
        }

    def _step(
        self,
        t: float,
        x_cont: npt.NDArray[Any],
        discrete_state: dict[Block, npt.NDArray[Any]],
        order: list[Block],
        layout: list[tuple[Block, slice]],
        *,
        fresh: frozenset[Block] | None = None,
        cache: dict[Block, npt.NDArray[Any]] | None = None,
    ) -> tuple[dict[Block, npt.NDArray[Any]], dict[Block, npt.NDArray[Any]]]:
        """1 時刻での SM-A scalar-port 用出力計算 (既存 hot path、ADR-0017 §(4))。

        全ブロック port_shape == () の場合に呼ばれる。各 ``inputs[b]`` / ``outputs[b]`` は
        1D ndarray (shape ``(n_inputs,)`` / ``(n_outputs,)``)。

        戻り値の ``inputs`` 辞書は **全ブロック** (direct_feedthrough の真偽によらず)
        について ``inputs[b]`` を持つ。direct_feedthrough=True はパス 1 で、
        False はパス 2 で書き込まれる。

        ADR-0078 サンプル時刻処理 / 出力キャッシュ (``cache`` が None でない場合のみ有効):

        * 離散ブロック (``discrete_state`` に載るブロック) のうち ``fresh`` (= 今回
          発火するブロック) は、トポロジカル順に ``advance(t, x, u)`` で状態をシフト
          (``discrete_state`` を in-place 更新) してから ``output()`` を呼び、結果を
          ``cache`` に書く。
        * それ以外の離散ブロックは ``cache`` の値 (= 直前のサンプル時刻で確定した
          出力) を返す = サンプル&ホールド。ODE 右辺評価は ``fresh=frozenset()``。
        * 非直達ブロックの ``advance`` に渡る ``u`` は制御入力ポートのみ確定
          (fire 判定にはそれで足りる)。
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
                # bug-fix 2026-09-13: 制御入力ポートだけは output() 前に埋める
                # (依存辺は _execution_order で追加済みなので上流は計算済み)
                for i in b.control_input_ports:
                    src = b.input_sources[i]
                    if src is not None:
                        sb, si = src
                        u[i] = outputs[sb][si]
            # ADR-0056 §C-3: 例外時に runtime が関与ブロックを payload に詰めるため
            # output 呼出直前で current_block を更新する。
            self._current_block = b
            if cache is not None and b in discrete_state:
                if fresh is not None and b in fresh:
                    xb = np.asarray(b.advance(t, discrete_state[b], u), dtype=float)
                    discrete_state[b] = xb
                    y = np.atleast_1d(np.asarray(b.output(t, xb, u), dtype=float))
                    cache[b] = y
                else:
                    y = cache[b]
            else:
                y = np.atleast_1d(np.asarray(b.output(t, state_for(b), u), dtype=float))
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
        *,
        fresh: frozenset[Block] | None = None,
        cache: dict[Block, tuple[npt.NDArray[Any], ...]] | None = None,
    ) -> tuple[
        dict[Block, tuple[npt.NDArray[Any], ...]], dict[Block, tuple[npt.NDArray[Any], ...]]
    ]:
        """ADR-0017 §(4) / ADR-0079 §(2) SM-T vector-port 用出力計算。

        各ブロックの ``output_v`` を呼び、tuple of ndarrays でポート間の信号を
        伝搬する。各ポートの shape / dtype は **plan** (信号面解決の結果) から
        読む — ブロックの宣言 ``port_shapes_in/out`` は参照しない (D-2)。

        戻り値の ``outputs`` / ``inputs`` 辞書は ``tuple[ndarray, ...]`` 形式。
        SM-A 互換ブロックは ``Block.output_v`` の default 実装が ``output`` を wrap
        するため、混在モデルでも動作する。

        ``fresh`` / ``cache`` は ``_step`` と同じ ADR-0078 サンプル時刻処理 / 出力
        キャッシュの制御 (キャッシュ値は dtype cast 後の tuple)。``advance`` に渡す
        ``u`` は SM-A 互換の 1D ndarray (rank-0 要素を並べたもの)。

        ``plan is None`` は解決器を通っていない経路 (テストの直接呼び出し等) で、
        その場合は宣言 shape + float64 で動く (従来互換)。
        """
        cont_state = {b: x_cont[sl] for b, sl in layout}
        outputs: dict[Block, tuple[npt.NDArray[Any], ...]] = {}
        inputs: dict[Block, tuple[npt.NDArray[Any], ...]] = {}
        plan = self._signal_plan

        def state_for(b: Block) -> npt.NDArray[Any]:
            if b in cont_state:
                return cont_state[b]
            if b in discrete_state:
                return discrete_state[b]
            return np.zeros(0)

        def _in_spec(
            b: Block, idx: int
        ) -> tuple[tuple[tuple[int, ...], ...], tuple[np.dtype[Any], ...] | None]:
            if plan is None:
                return b.port_shapes_in, None
            return plan[idx][0], plan[idx][1]

        def _zero_inputs(
            shapes: tuple[tuple[int, ...], ...], in_dts: tuple[np.dtype[Any], ...] | None
        ) -> tuple[npt.NDArray[Any], ...]:
            if in_dts is None:
                return tuple(np.zeros(shape, dtype=float) for shape in shapes)
            return tuple(np.zeros(shape, dtype=in_dts[i]) for i, shape in enumerate(shapes))

        def _gather_inputs(
            b: Block,
            shapes: tuple[tuple[int, ...], ...],
            in_dts: tuple[np.dtype[Any], ...] | None,
        ) -> tuple[npt.NDArray[Any], ...]:
            u_list: list[npt.NDArray[Any]] = []
            for i, src in enumerate(b.input_sources):
                if src is None:
                    u_list.append(np.zeros(shapes[i], dtype=float if in_dts is None else in_dts[i]))
                else:
                    sb, si = src
                    ui = outputs[sb][si]
                    if in_dts is not None and ui.dtype != in_dts[i]:
                        # D-4 自動昇格の実行時実体 (in-plan cast、SPEC-0028 §3.7)。
                        # 例: int64 の上流 → Integrator の in は float64。
                        ui = cast_value(ui, in_dts[i])
                    u_list.append(ui)
            return tuple(u_list)

        for idx, b in enumerate(order):
            in_shapes, in_dts = _in_spec(b, idx)
            if b.direct_feedthrough:
                u = _gather_inputs(b, in_shapes, in_dts)
                inputs[b] = u
            else:
                u = _zero_inputs(in_shapes, in_dts)
                if b.control_input_ports:
                    # bug-fix 2026-09-13: 制御入力ポートだけは output() 前に埋める
                    # (SM-A path の _step と同じ扱い)。データポートの上流はこの時点で
                    # 未計算でもよいので、_gather_inputs (全ポート解決) は使わない。
                    u_list = list(u)
                    for i in b.control_input_ports:
                        src = b.input_sources[i]
                        if src is not None:
                            sb, si = src
                            ui = outputs[sb][si]
                            if in_dts is not None and ui.dtype != in_dts[i]:
                                ui = cast_value(ui, in_dts[i])
                            u_list[i] = ui
                    u = tuple(u_list)
            # ADR-0078 サンプル時刻処理 / 出力キャッシュ (SM-A ``_step`` と同じ規則)
            if cache is not None and b in discrete_state:
                if fresh is not None and b in fresh:
                    # ADR-0079 §(5): vector-port 版 advance (SM-A ブロックは Block 基底の
                    # wrapper が rank-0 に縮退して advance() を呼ぶ)
                    xb = np.asarray(b.advance_v(t, discrete_state[b], u), dtype=float)
                    discrete_state[b] = xb
                    outputs[b] = self._output_v_cast(b, t, xb, u, plan, idx)
                    cache[b] = outputs[b]
                else:
                    outputs[b] = cache[b]
                continue
            outputs[b] = self._output_v_cast(b, t, state_for(b), u, plan, idx)
        for idx, b in enumerate(order):
            if not b.direct_feedthrough:
                in_shapes, in_dts = _in_spec(b, idx)
                inputs[b] = _gather_inputs(b, in_shapes, in_dts)
        return outputs, inputs

    @staticmethod
    def _output_v_cast(
        b: Block,
        t: float,
        xb: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
        plan: SignalPlan | None,
        idx: int,
    ) -> tuple[npt.NDArray[Any], ...]:
        """``output_v`` を呼び、長さ / shape 検証と dtype cast (SPEC-0028 §3.6) を施す。

        ADR-0079 §(2): 出力 shape が plan の予測と一致することをここで検証する
        (予測 == 実行、AC-2 をこの 1 箇所が保証する)。不一致はブロック実装の
        バグなので ``BlockSpecError``。
        """
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
        if plan is None:
            return tuple(np.asarray(yi, dtype=float) for yi in y)
        # SPEC-0028 §3.6: 予測 dtype への強制 cast (SSOT の適用点は
        # ここ 1 箇所。cast_value は dtype 一致時 no-op、nan/inf/域外も
        # 決定的)。予測 == 実行 (AC-2) をこの行が保証する。
        out_shapes = plan[idx][2]
        out_dts = plan[idx][3]
        result: list[npt.NDArray[Any]] = []
        for j, yi in enumerate(y):
            arr = np.asarray(yi)
            if arr.shape != out_shapes[j]:
                raise BlockSpecError(
                    f"{type(b).__name__} {b.id!r}.output_v returned shape {arr.shape} "
                    f"on out[{j}] but the resolved signal plan expects "
                    f"{out_shapes[j]}; this is a block implementation bug "
                    "(the block's shape rule in flode.core.signals and its "
                    "output_v disagree).",
                    block_id=b.id,
                )
            result.append(cast_value(arr, out_dts[j]))
        return tuple(result)

    def run(self) -> None:
        """シミュレーションを実行する。

        ハイブリッド (連続+離散) ループ (ADR-0015 §(1) を ADR-0078 で補正):

        - [A]  ``_step`` (トポロジカル順、1 パス): 発火ブロック
          (``k % step_ratio == 0``) は ``x_k = advance(t_k, x_k^-, u_k)`` で
          2-state のシフト相を実行してから ``y_k = output(t_k, x_k, u_k)`` を計算し
          キャッシュ、非発火の離散ブロックはキャッシュ値 (サンプル&ホールド)。
          こうして全ブロックの **同時刻の** 入力 ``u_k`` が揃う
        - [A'] ``x_{k+1}^- = update(t_k, x_k, u_k)`` を発火ブロックに呼び
          ``next_discrete`` に書き込む (double buffering で一斉差し替え)。
          ``outputs`` / ``inputs`` は Scope record と f_continuous (= ODE 右辺、
          キャッシュ値のみ参照) が使う
        - [E]  ``record(t_k, inputs)`` (Scope 等)
        - [B]  連続部分を ``solve_ivp`` で 1 ステップ進める ``[t_k, t_{k+1}]``

        ADR-0015 で ADR-0014 の multi-rate off-by-one を解決し、ADR-0078 で
        「update が 1 サンプル古い上流出力を受ける」(離散→離散の余分な遅延) と
        「直達項がサンプル間でホールドされない」を是正した。UnitDelay の出力は
        ``y(n*T) = u((n-1)*T)`` (リファレンスツール semantics) で、直列 / ループでも
        合成則 (2 段で ``u((n-2)*T)``) が成り立つ。

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
        # ADR-0079 §(1)(2): 経路選択。``_execution_order()`` で全ブロックの
        # ``_build()`` とトポロジカル順 (代数ループ検出) が完了したあと、
        # pre-filter (dtype 宣言 or shape 起点が root に 1 つでもあるか、O(V)) が
        # False なら解決器を一切呼ばず plan = None で従来の高速 ``_step`` パス
        # (= AC-1 の構造的保証)。True なら full mode で信号面 (shape + dtype) を
        # 解決し (error 級診断は SignalShapeError / BlockSpecError に昇格)、
        # ``_step_vector`` + plan で実行する。``_step`` は plan を一切参照しない
        # ので、非 () モデルが ``_step`` に入る経路は存在しない。
        from .signals import (
            has_declared_dtype,
            has_shape_source,
            reject_nested_dtype_declarations,
            resolve_for_execution,
        )

        # security MUST-1 (2026-09-08): Subsystem 内部の dtype 宣言は root-only
        # pre-filter をすり抜けて「予測と実行値の無警告乖離」を起こすため、
        # 宣言の有無に関わらず全モデルで fail-closed に拒否する (O(全ブロック)
        # の param 走査のみ — 数値挙動には一切影響しない)
        reject_nested_dtype_declarations(self)

        if has_declared_dtype(self) or has_shape_source(self):
            self._prepare_signal_plan(order, resolve_for_execution(self))
        else:
            self._signal_plan = None

        sm_a_mode = self._signal_plan is None
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
        self._warn_never_fired_gotos()

    def _warn_never_fired_gotos(self) -> None:
        """Trigger / Enable 配下で一度も実行されなかった Goto を WARNING で残す。

        code-reviewer SHOULD (2026-09-13): これらの Goto を読む From は run 全区間で
        0 を返す (bug-fix で例外から 0 返却に変更)。「まだ fire していない」と
        「配線ミスで一生 fire しない」を数値では区別できないため、後者の診断情報を
        ログで補う (数値挙動は変えない)。
        """
        from ..blocks.routing import Goto

        for scope_path, blocks in self._walk_scopes():
            for b in blocks:
                if isinstance(b, Goto) and b._hold_before_first_run and b._last_input is None:
                    _logger_routing.warning(
                        "Goto %r (tag=%r, scope=%s) never fired during this run "
                        "(its Triggered/Enabled Subsystem was never activated); "
                        "From blocks reading it returned 0.0 for the entire simulation",
                        b.id,
                        b.tag,
                        self._scope_path_str(scope_path),
                    )

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

        # ADR-0078: 離散ブロックの出力キャッシュ (サンプル時刻で確定し、サンプル間
        # = 非発火ステップと ODE 右辺評価ではキャッシュ値を返す = サンプル&ホールド)。
        out_cache: dict[Block, npt.NDArray[Any]] = {}

        def f_continuous(t: float, x: npt.NDArray[Any]) -> npt.NDArray[Any]:
            _, ins = self._step(
                t, x, discrete_state, order, layout, fresh=frozenset(), cache=out_cache
            )
            xdot = np.zeros(n_total)
            for b, sl in layout:
                # ADR-0056 §C-3: derivative 内例外時に関与ブロックを記録。
                self._current_block = b
                xdot[sl] = np.asarray(b.derivative(t, x[sl], ins[b]), dtype=float)
            self._current_block = None
            return xdot

        k = 0
        while True:
            t = _grid_time(k, dt_base)

            # ADR-0078 サンプル時刻の処理順 (ADR-0015 §(1) を 1 パスに整理):
            #   [A] _step (トポロジカル順): 発火ブロック (k % step_ratio == 0) は
            #       advance(t_k, x, u_k) でシフトしてから output(t_k, x_k, u_k) を計算し
            #       キャッシュ、非発火の離散ブロックはキャッシュ値 (サンプル&ホールド)
            #       → 全ブロックの同時刻の入力 u_k
            #   [A'] update(t_k, x_k, u_k) を発火ブロックに呼び x_{k+1}^- を確定
            #       (double buffering で一斉差し替え)
            if discrete_state:
                hit = [b for b in order if b in discrete_state and k % b._step_ratio == 0]
                outputs, inputs = self._step(
                    t, x_cont, discrete_state, order, layout, fresh=frozenset(hit), cache=out_cache
                )
                next_discrete: dict[Block, npt.NDArray[Any]] = dict(discrete_state)
                for b in hit:
                    x_b = discrete_state[b]
                    u_b = inputs.get(b, np.zeros(b.n_inputs))
                    # ADR-0056 §C-3: discrete update 例外時のブロック記録。
                    self._current_block = b
                    next_discrete[b] = np.array(b.update(t, x_b, u_b), dtype=float)
                self._current_block = None
                # closure 共有のため in-place update (= 同じ dict 参照を維持)。
                # f_continuous / f_continuous_vector が discrete_state を closure で
                # capture しているため、再代入では新値が見えない (ADR-0018 修正)。
                discrete_state.clear()
                discrete_state.update(next_discrete)
            else:
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
                t_next = _grid_time(k + 1, dt_base)
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
        ``_record_v`` が各ポートを C order で列展開した 1D ndarray を受け取る
        (ADR-0079 §(4): Scope はベクトル入力を n 列として記録する)。

        ``f_continuous_vector`` を本 method 内で定義することで closure が正しく
        ``discrete_state`` 再代入を追跡する (SM-A と同じ理由)。

        ADR-0042 §論点 1-A: ``n_steps is None`` のとき unbounded ループ
        (= ``self.t_end = math.inf``)。終了は ``self._stop_requested`` のみ。
        """

        # ADR-0078: 離散ブロックの出力キャッシュ (SM-A と同じ)。
        out_cache: dict[Block, tuple[npt.NDArray[Any], ...]] = {}

        def f_continuous_vector(t: float, x: npt.NDArray[Any]) -> npt.NDArray[Any]:
            # ADR-0018 §(2)(4): SM-B run path。``_step_vector`` から得た
            # ``inputs[b]`` は tuple of ndarrays。SM-A 連続ブロックは SM-A
            # ``derivative(t, x, u_1d)`` を期待するため、tuple を 1D ndarray に
            # concat (= rank-0 element を順に並べる) する wrapper で互換性を保つ。
            # SM-B-aware 連続ブロック (Phase 4+) は ``derivative_v`` を将来追加。
            _, ins = self._step_vector(
                t, x, discrete_state, order, layout, fresh=frozenset(), cache=out_cache
            )
            xdot = np.zeros(n_total)
            for b, sl in layout:
                u_tuple = ins[b]
                # ADR-0056 §C-3: SM-B derivative 例外時のブロック記録。
                self._current_block = b
                # ADR-0079 §(5): vector-port 版 derivative (flat x_dot を返す)
                xdot[sl] = np.asarray(b.derivative_v(t, x[sl], u_tuple), dtype=float)
            self._current_block = None
            return xdot

        k = 0
        while True:
            t = _grid_time(k, dt_base)

            # [A]/[A'] 離散ブロック処理 (SM-B path、SM-A と同じ 1 パス順序、ADR-0078)
            if discrete_state:
                hit = [b for b in order if b in discrete_state and k % b._step_ratio == 0]
                _, inputs_v = self._step_vector(
                    t, x_cont, discrete_state, order, layout, fresh=frozenset(hit), cache=out_cache
                )
                next_discrete: dict[Block, npt.NDArray[Any]] = dict(discrete_state)
                for b in hit:
                    x_b = discrete_state[b]
                    u_tuple = inputs_v.get(
                        b, tuple(np.zeros((), dtype=float) for _ in range(b.n_inputs))
                    )
                    # ADR-0056 §C-3: SM-B discrete update 例外時の記録。
                    self._current_block = b
                    # ADR-0079 §(5): vector-port 版 update
                    next_discrete[b] = np.array(b.update_v(t, x_b, u_tuple), dtype=float)
                self._current_block = None
                # closure 共有のため in-place update (= 同じ dict 参照を維持)。
                # f_continuous / f_continuous_vector が discrete_state を closure で
                # capture しているため、再代入では新値が見えない (ADR-0018 修正)。
                discrete_state.clear()
                discrete_state.update(next_discrete)
            else:
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
                t_next = _grid_time(k + 1, dt_base)
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
        method: Literal["central", "forward"] = "central",
        epsilon: float | None = None,
    ) -> LinearSystem:
        """動作点 ``(t, x, u)`` 周りでモデルを線形化する (ADR-0026)。

        ``flode.linearize(self, ...)`` の薄いラッパ。詳細は
        :func:`flode.analysis.linearize` を参照。

        Args:
            t: 動作点時刻 [s]。default ``0.0``。
            x: 連続状態の動作点 (shape ``(n_states,)``)。``None`` で各ブロックの
                ``x0`` を ``_state_layout()`` 順に concat したもの。
            u: 外部入力の動作点 (shape ``(n_inputs_total,)``)。``None`` で全ゼロ。
            method: ``"central"`` (default) / ``"forward"``。
            epsilon: 摂動相対 step。``None`` で次元ごと自動 (``sqrt(eps_machine)``)。

        Returns:
            :class:`flode.analysis.LinearSystem`。

        Example:
            >>> ls = sim.linearize()  # doctest: +SKIP
            >>> isinstance(ls.A, np.ndarray)  # doctest: +SKIP
            True
        """
        # 循環 import 回避のため遅延 import
        from ..analysis.linearize import linearize as _linearize

        return _linearize(self, t=t, x=x, u=u, method=method, epsilon=epsilon)

    def resolve_signals(self) -> SignalResolution:
        """信号面 (shape + dtype) を静的に解決する (ADR-0079 §(1) / §(9))。

        ``flode.core.signals.resolve_signals(self)`` の薄いラッパ。実行はせず、
        各ポートが運ぶ ``(shape, dtype)`` を build 時規則で推論する。
        **シミュレーション結果には一切影響しない** (表示・測定用)。
        例外は送出せず、失敗は診断 (``dtype.build_failed`` 等) として返る。

        Returns:
            :class:`flode.core.signals.SignalResolution`
            (``ports`` / ``shapes`` / ``diagnostics`` / ``summary``)。

        Example:
            >>> res = sim.resolve_signals()  # doctest: +SKIP
            >>> res.out_shape("mux-1", 0)  # doctest: +SKIP
            (3,)
        """
        # 循環 import 回避のため遅延 import (linearize と同じ流儀)
        from .signals import resolve_signals as _resolve_signals

        return _resolve_signals(self)

    def resolve_dtypes(self) -> SignalResolution:
        """``resolve_signals`` の互換 alias (SPEC-0027 / ADR-0077 の公開名、ADR-0038)。

        Example:
            >>> res = sim.resolve_dtypes()  # doctest: +SKIP
            >>> res.out_dtype("const-1", 0)  # doctest: +SKIP
            'int64'
        """
        return self.resolve_signals()

    def _prepare_signal_plan(self, order: list[Block], resolution: SignalResolution) -> None:
        """解決結果から実行 plan を作り、ブロック側の runtime cache に反映する。

        ``run()`` と ``linearize`` が共有する (ADR-0079 §(2))。``_state_layout`` /
        ``_init_discrete_state`` より **前** に呼ぶこと (ベクトル状態ブロックの
        ``n_states`` / ``x0`` がここで確定する、§(5) 7a')。
        """
        self._signal_plan = _build_signal_plan(order, resolution)
        self._apply_plan_to_blocks(order, self._signal_plan, resolution)

    def _apply_plan_to_blocks(
        self, order: list[Block], plan: SignalPlan, resolution: SignalResolution
    ) -> None:
        """解決済み plan のうち、ブロック側が実行時に必要とする値を注入する。

        ADR-0079 D-2 (宣言へは書き戻さない) の範囲内で、**runtime cache** として
        以下だけを渡す:

        - ``From._plan_out_shape``: 初回 fire 前のホールド値 (ゼロ) の shape
        - ``Scope`` / ``Display`` 等の ``_apply_input_shapes(shapes)``: 列展開の
          列数とラベルの確定 (duck-typing、持たないブロックは無視)
        - ベクトル状態ブロックの ``_apply_state_shape(shape)``: 実効 state shape
          (= 出力 shape) から ``n_states`` / ``x0`` を確定 (§(5) 7a')
        - ``Subsystem._apply_inner_signal_plan(...)``: 内部 plan の注入と内部ブロックへの
          再帰適用、内部 layout の再計算 (§(6))
        """
        for idx, b in enumerate(order):
            in_shapes, _in_dts, out_shapes, _out_dts = plan[idx]
            if hasattr(b, "_plan_out_shape") and out_shapes:
                b._plan_out_shape = out_shapes[0]
            apply_shapes = getattr(b, "_apply_input_shapes", None)
            if callable(apply_shapes):
                apply_shapes(in_shapes)
            apply_state = getattr(b, "_apply_state_shape", None)
            if callable(apply_state) and out_shapes:
                apply_state(out_shapes[0])
            apply_inner = getattr(b, "_apply_inner_signal_plan", None)
            if callable(apply_inner):
                bid = b.id if b.id is not None else "<unassigned>"
                inner_res = resolution.inner.get(bid)
                if inner_res is not None:
                    inner_order = list(getattr(b, "_exec_order", None) or [])
                    inner_plan = _build_signal_plan(inner_order, inner_res)
                    apply_inner(inner_plan)
                    self._apply_plan_to_blocks(inner_order, inner_plan, inner_res)
                    finalize = getattr(b, "_finalize_inner_signal_plan", None)
                    if callable(finalize):
                        finalize()

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
        from .. import __version__ as _flode_version
        from .block import serialization_build

        normalized_layout = normalize_layout(layout)

        # bug-fix (2026-09-08): ブロックのシリアライズ (to_dict 再帰) を
        # serialization_build 区間で囲み、「save パス全体でユーザーコードを
        # exec しない」を Subsystem 側の自己防衛に頼らず構造的に保証する
        # (security-reviewer SHOULD-1)。
        with serialization_build():
            payload: dict[str, Any] = {
                "schema_version": CURRENT_SCHEMA_VERSION,
                "metadata": {
                    "created_at": datetime.datetime.now(datetime.UTC)
                    .replace(microsecond=0)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "tool": f"flode {_flode_version}",
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
        # ADR-0071 §(7): 非 ASCII id を \uXXXX エスケープせず生の UTF-8 で書く。
        # GUI 保存経路 (server/routes/files.py の ensure_ascii=False) とバイト列を
        # 一致させ、保存経路の違いで git diff が壊れるのを防ぐ。
        text = json.dumps(payload, indent=indent if indent > 0 else None, ensure_ascii=False)
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
        # ADR-0071 §(3): id とその全参照 (connections / layout / branch_waypoints /
        # scope_settings) を単一関数で NFC 正規化する (片側だけだと参照が切れる)
        data = normalize_model_ids(data)

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
                # id は未検証 (任意長) のため先頭 80 文字に丸めて増幅を避ける
                raise ModelLoadError(
                    f"Cannot instantiate block {str(b_data['id'])[:80]!r} "
                    f"of type {str(b_data['type'])[:120]!r}: {e}"
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
