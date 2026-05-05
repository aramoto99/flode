"""Simulator: ブロック登録・結線・実行の中心。

ADR-0002 (離散時間 + マルチレート) で `run()` を連続/離散ハイブリッド対応に拡張。
ADR-0004 (ブロック ID 規則) で自動採番 / `connect` の `Block | str` 対応 / `rename` を追加。
ADR-0008 (JSON 永続化) で `save` / `load` を追加。
"""

from __future__ import annotations

import datetime
import json
import logging
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import numpy as np
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
    migrate_to_current,
    resolve_block_class,
    serialize_connections,
)

_logger = logging.getLogger("pyflw.scheduler")

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
        t_end: float = 10.0,
        dt: float = 0.01,
        solver: str = "RK45",
        rtol: float = 1e-6,
        atol: float = 1e-9,
        dt_base: float | None = None,
    ) -> None:
        self.t_end = float(t_end)
        self.dt = float(dt)
        self.solver = solver
        self.rtol = rtol
        self.atol = atol
        self.dt_base_hint: float | None = None if dt_base is None else float(dt_base)
        self.blocks: list[Block] = []
        self._blocks_by_id: dict[str, Block] = {}
        self._type_counters: dict[str, int] = {}

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
        # Subsystem 等、内部構造を持つブロックは direct_feedthrough / n_states /
        # x0 を ``_build()`` で確定する (Block 基底の default は no-op)。
        # 実行順序解析の前に全ブロックに対し呼ぶ。
        for b in self.blocks:
            b._build()
        deps: dict[Block, set[Block]] = {b: set() for b in self.blocks}
        rev: dict[Block, set[Block]] = defaultdict(set)
        for b in self.blocks:
            if b.direct_feedthrough:
                for src in b.input_sources:
                    if src is not None:
                        deps[b].add(src[0])
                        rev[src[0]].add(b)
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
            raise AlgebraicLoopError(f"Algebraic loop detected involving: {remaining}")
        return order

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
                            "(no implicit ZeroOrderHold inserted)",
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

    def _init_discrete_state(self) -> dict[Block, np.ndarray]:
        return {
            b: np.asarray(b.x0, dtype=float).copy()
            for b in self.blocks
            if b.n_states > 0 and b._resolved_sample_time is not None
        }

    def _step(
        self,
        t: float,
        x_cont: np.ndarray,
        discrete_state: dict[Block, np.ndarray],
        order: list[Block],
        layout: list[tuple[Block, slice]],
    ) -> tuple[dict[Block, np.ndarray], dict[Block, np.ndarray]]:
        """1 時刻での出力計算 (Phase 0 と同じ 2 パス、状態は連続/離散に分離)。

        戻り値の ``inputs`` 辞書は **全ブロック** (direct_feedthrough の真偽によらず)
        について ``inputs[b]`` を持つ。direct_feedthrough=True はパス 1 で、
        False はパス 2 で書き込まれる。
        """
        cont_state = {b: x_cont[sl] for b, sl in layout}
        outputs: dict[Block, np.ndarray] = {}
        inputs: dict[Block, np.ndarray] = {}

        def state_for(b: Block) -> np.ndarray:
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
            y = np.atleast_1d(np.asarray(b.output(t, xb, u), dtype=float))
            outputs[b] = y
        for b in order:
            if not b.direct_feedthrough:
                u = np.zeros(b.n_inputs)
                for i, src in enumerate(b.input_sources):
                    if src is not None:
                        sb, si = src
                        u[i] = outputs[sb][si]
                inputs[b] = u
        return outputs, inputs

    def run(self) -> None:
        """シミュレーションを実行する。

        ハイブリッド (連続+離散) ループ:
            1. 出力計算 2 パス (時刻 t)
            2. 連続部分を ``solve_ivp`` で 1 ステップ積分 ``[t, t+dt_base]``
            3. 新時刻で出力再計算
            4. 該当する離散ブロックの ``update`` (double buffering で一斉書き換え)
            5. ``record`` (Scope 等)
        """
        order = self._execution_order()
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

        n_steps = int(round(self.t_end / dt_base))
        if n_steps < 1:
            raise SchedulingError(
                f"t_end={self.t_end}, dt_base={dt_base}: computed n_steps={n_steps} < 1"
            )

        def f_continuous(t: float, x: np.ndarray) -> np.ndarray:
            _, ins = self._step(t, x, discrete_state, order, layout)
            xdot = np.zeros(n_total)
            for b, sl in layout:
                xdot[sl] = np.asarray(b.derivative(t, x[sl], ins[b]), dtype=float)
            return xdot

        for k in range(n_steps + 1):
            t = k * dt_base
            outputs, inputs = self._step(t, x_cont, discrete_state, order, layout)
            self._record(t, inputs)

            if k == n_steps:
                break

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

            t_new = (k + 1) * dt_base
            _, inputs_new = self._step(t_new, x_cont, discrete_state, order, layout)

            if discrete_state:
                next_discrete: dict[Block, np.ndarray] = dict(discrete_state)
                for b in order:
                    if b not in discrete_state:
                        continue
                    if (k + 1) % b._step_ratio == 0:
                        x_b = discrete_state[b]
                        u_b = inputs_new.get(b, np.zeros(b.n_inputs))
                        next_discrete[b] = np.array(b.update(t_new, x_b, u_b), dtype=float)
                discrete_state = next_discrete

    def _record(self, t: float, inputs: dict[Block, np.ndarray]) -> None:
        for b in self.blocks:
            if hasattr(b, "record"):
                b.record(t, inputs[b])

    def save(self, path: str | Path, *, indent: int = 2) -> None:
        """モデル定義 (ブロック・結線・Simulator 設定) を JSON ファイルに保存する。

        ADR-0008 で確定した ``schema_version = "0.1"`` 形式で出力する。
        ``run()`` 後の状態 (Scope バッファ、積分結果) は保存対象外。

        Args:
            path: 保存先パス (``.flw.json`` 拡張子を推奨)。
            indent: ``json.dumps`` のインデント (default ``2``)。``0`` 以下を渡すと
                ``json.dumps`` を ``indent=None`` で呼び、改行・インデントなしの
                compact 出力 (機械可読向け) になる。

        Raises:
            ModelSerializationError: ブロックパラメータが JSON-serializable でない、
                または ``__main__`` モジュールで定義された class を含む場合。
        """
        from .. import __version__ as _pyflw_version

        payload: dict[str, Any] = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "metadata": {
                "created_at": datetime.datetime.now(datetime.timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
                "tool": f"pyflw {_pyflw_version}",
            },
            "simulator": {
                "t_end": float(self.t_end),
                "dt": float(self.dt),
                "solver": str(self.solver),
                "rtol": float(self.rtol),
                "atol": float(self.atol),
                "dt_base": (None if self.dt_base_hint is None else float(self.dt_base_hint)),
            },
            "blocks": [b.to_dict() for b in self.blocks],
            "connections": serialize_connections(self.blocks),
        }
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
            try:
                # Subsystem は ``_from_dict`` factory 経由で復元する (内部 blocks
                # の dict を resolve_block_class で展開するため)。それ以外の通常
                # ブロックは ``__init__`` で直接構築。
                if hasattr(block_cls, "_from_dict") and callable(block_cls._from_dict):
                    block = block_cls._from_dict(id=b_data["id"], **b_data["params"])
                else:
                    block = block_cls(id=b_data["id"], **b_data["params"])
            except (TypeError, ValueError) as e:
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

        return sim
