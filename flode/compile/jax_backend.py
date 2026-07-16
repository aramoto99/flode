"""Jax-native re-evaluator + ``jax.jacfwd`` 線形化 (ADR-0037 §(3))。

flode コア Block の ``output`` / ``derivative`` は numpy ベースなので、jax tracer
を渡しても ``np.asarray`` で具象化されてしまい trace が切れる。本モジュールは
**block 種別ごとの jax-native 評価関数** を dispatch する形で、jax tracer を
最後まで保つ ``_evaluate_jax`` を構築する。

Phase 5b MVP (= v0.17.0) でサポートする block:

* :class:`flode.blocks.Constant` / :class:`flode.blocks.Step` /
  :class:`flode.blocks.Sine` / :class:`flode.blocks.Ramp` /
  :class:`flode.blocks.Clock` (= time-only sources)
* :class:`flode.blocks.Gain` / :class:`flode.blocks.Sum` (= 線形演算)
* :class:`flode.blocks.Integrator` (= 連続状態の積分)

未サポートブロックを含むモデルでは ``BlockSpecError`` を発出して
``method="central"`` への移行を案内する (= silent fallback しない、ADR-0037
§Decision §(8))。

Phase 6+ で jax tracing 対応を全 block に拡張、または block ごとの
``_jax_eval`` メソッドを追加する設計を検討。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt

from ..blocks.continuous import Integrator
from ..blocks.mathops import Gain, Sum
from ..blocks.sinks import Display, Scope, Terminator, XYGraph
from ..blocks.sources import Clock, Constant, Ramp, Sine, Step
from ..exceptions import BlockSpecError

if TYPE_CHECKING:  # pragma: no cover
    from ..analysis.linearize import _InputSpec, _OutputSpec
    from ..core.block import Block
    from ..core.simulator import Simulator


#: Phase 5b MVP で jax-native 評価をサポートする block 型の集合。
_SUPPORTED_BLOCK_TYPES: tuple[type, ...] = (
    Constant,
    Step,
    Sine,
    Ramp,
    Clock,
    Gain,
    Sum,
    Integrator,
)
#: linearize 計算で無視される sink ブロック (= 出力を持たないので Jacobian に影響しない)。
_SINK_BLOCK_TYPES: tuple[type, ...] = (Scope, Display, XYGraph, Terminator)


def _validate_supported_blocks(simulator: Simulator) -> None:
    """モデル内の全ブロックが jax-native 評価をサポートしているか検証する。

    Raises:
        BlockSpecError: 未サポートブロックが含まれる (= block id とその型を message に
            含めて、``method="central"`` への切替を案内)。
    """
    unsupported: list[tuple[str, str]] = []
    for b in simulator.blocks:
        if isinstance(b, _SINK_BLOCK_TYPES):
            continue
        if not isinstance(b, _SUPPORTED_BLOCK_TYPES):
            unsupported.append((b.id or "<unnamed>", type(b).__name__))
    if unsupported:
        names = ", ".join(f"{bid}({tname})" for bid, tname in unsupported)
        raise BlockSpecError(
            f"linearize(method='jax'): the following blocks are not yet supported in "
            f"v0.17.0 jax-native evaluator: {names}. "
            f"Supported types in v0.17.0: {sorted(t.__name__ for t in _SUPPORTED_BLOCK_TYPES)}. "
            f"Use method='central' (numerical) or wait for Phase 6+ extension. "
            f"See ADR-0037 §Decision §(3) and flode/compile/jax_backend.py for the "
            f"current support matrix."
        )


def _block_eval_jax(
    block: Block,
    t: Any,
    x_block: Any,
    u_block: Any,
    jnp_module: Any,
) -> tuple[Any, Any]:
    """1 ブロックの jax-native 評価 (= ``output_y`` と ``xdot_block`` を返す)。

    呼び出し前に ``_validate_supported_blocks`` で型をチェック済の前提。

    Args:
        block: 評価対象 (``_SUPPORTED_BLOCK_TYPES`` のいずれか)。
        t: 時刻 (jax scalar or float)。
        x_block: 連続状態 (block.n_states == 0 なら shape (0,))。
        u_block: 入力ベクトル (shape (block.n_inputs,))。
        jnp_module: ``jax.numpy`` モジュール (= 呼び出し側で import)。

    Returns:
        ``(output_y, xdot_block)`` のタプル。``output_y`` は shape ``(block.n_outputs,)``、
        ``xdot_block`` は shape ``(block.n_states,)`` (n_states=0 なら空配列)。
    """
    if isinstance(block, Constant):
        # value は constant、入力なし、出力 1 (Constant.value = scalar)。
        return jnp_module.array([block.value], dtype=jnp_module.float64), jnp_module.zeros(0)
    if isinstance(block, Step):
        # output = initial_value if t < step_time else final_value
        y = jnp_module.where(
            t < block.step_time,
            block.initial_value,
            block.final_value,
        )
        return jnp_module.array([y], dtype=jnp_module.float64), jnp_module.zeros(0)
    if isinstance(block, Sine):
        y = block.amplitude * jnp_module.sin(2 * jnp_module.pi * block.frequency * t + block.phase)
        return jnp_module.array([y], dtype=jnp_module.float64), jnp_module.zeros(0)
    if isinstance(block, Ramp):
        y = jnp_module.where(
            t < block.start_time,
            block.initial_output,
            block.initial_output + block.slope * (t - block.start_time),
        )
        return jnp_module.array([y], dtype=jnp_module.float64), jnp_module.zeros(0)
    if isinstance(block, Clock):
        return jnp_module.array([t], dtype=jnp_module.float64), jnp_module.zeros(0)
    if isinstance(block, Gain):
        return block.k * u_block, jnp_module.zeros(0)
    if isinstance(block, Sum):
        # signs は np.array of +1/-1 floats (= block.signs)
        signs = jnp_module.asarray(block.signs, dtype=jnp_module.float64)
        return jnp_module.array([jnp_module.dot(signs, u_block)]), jnp_module.zeros(0)
    if isinstance(block, Integrator):
        # output = x[0] (state)、derivative = u[0]
        return jnp_module.asarray(x_block, dtype=jnp_module.float64), jnp_module.asarray(
            u_block, dtype=jnp_module.float64
        )
    raise BlockSpecError(
        f"_block_eval_jax: unsupported block type {type(block).__name__} "
        f"(internal bug — _validate_supported_blocks should have caught this)"
    )


def _evaluate_jax(
    simulator: Simulator,
    t: Any,
    x_op: Any,
    u_op: Any,
    layout: list[tuple[Block, slice]],
    input_specs: list[_InputSpec],
    output_specs: list[_OutputSpec],
    jnp_module: Any,
) -> tuple[Any, Any]:
    """jax-traceable な ``(xdot, y) = f(x, u)``。``jax.jacfwd`` の対象関数。

    Args:
        simulator: 元の Simulator (= ブロック構造を読むだけで状態は変更しない)。
        t: 時刻 (jax scalar)。
        x_op: 連続状態ベクトル (shape ``(n_states,)``)。
        u_op: 外部入力ベクトル (shape ``(n_in,)``)。
        layout: ``[(block, slice), ...]`` (= simulator._state_layout 由来)。
        input_specs / output_specs: ``_build_input_specs`` / ``_build_output_specs`` 由来。
        jnp_module: ``jax.numpy``。

    Returns:
        ``(xdot, y)`` のタプル。``xdot`` は shape ``(n_states,)``、``y`` は shape ``(n_out,)``。
    """
    # state_for: block → x slice (= jax-array view)。連続状態のみ含み、離散は zeros。
    state_for: dict[Block, Any] = {}
    for b, sl in layout:
        st = b._resolved_sample_time
        if st is None or st <= 0.0:  # 連続のみ
            state_for[b] = x_op[sl]

    # ADR-0014/0015 Simulator._step と同じ 2-pass:
    # Pass 1: direct_feedthrough block の出力を topo 順に計算 (df=False は zero u で可)
    # Pass 2: non-df block の derivative 用 u_block を全 outputs から再構築
    u_for_block: dict[Block, Any] = {}
    outputs: dict[Block, Any] = {}
    order = simulator._execution_order()

    def _build_u_block(b: Block) -> Any:
        u_block = jnp_module.zeros(b.n_inputs, dtype=jnp_module.float64)
        for i, src in enumerate(b.input_sources):
            if src is not None:
                sb, si = src
                if sb in outputs:
                    u_block = u_block.at[i].set(outputs[sb][si])
        for spec in input_specs:
            if spec.block is b:
                u_block = u_block.at[spec.port_idx].set(u_op[spec.u_slice])
        return u_block

    # Pass 1: 全 block の output を計算 (df=False は state-only なので u は不要)
    for b in order:
        if isinstance(b, _SINK_BLOCK_TYPES):
            continue
        u_block = (
            _build_u_block(b)
            if b.direct_feedthrough
            else jnp_module.zeros(b.n_inputs, dtype=jnp_module.float64)
        )
        if b.direct_feedthrough:
            u_for_block[b] = u_block
        x_block = state_for.get(b, jnp_module.zeros(0))
        y_block, _ = _block_eval_jax(b, t, x_block, u_block, jnp_module)
        outputs[b] = y_block

    # Pass 2: non-df block の u_block を全 outputs から再構築 (= derivative 入力)
    for b in order:
        if isinstance(b, _SINK_BLOCK_TYPES):
            continue
        if not b.direct_feedthrough:
            u_for_block[b] = _build_u_block(b)

    # xdot 構築 (連続状態を持つ block のみ、Pass 2 後の正しい u を使う)
    n_states = sum(sl.stop - sl.start for _, sl in layout)
    xdot = jnp_module.zeros(n_states, dtype=jnp_module.float64)
    for b, sl in layout:
        st = b._resolved_sample_time
        if st is None or st <= 0.0:
            x_block = state_for[b]
            u_block = u_for_block.get(b, jnp_module.zeros(b.n_inputs))
            _, xdot_block = _block_eval_jax(b, t, x_block, u_block, jnp_module)
            xdot = xdot.at[sl].set(xdot_block)

    # y 構築 (output_specs に対応)
    n_out = len(output_specs)
    y = jnp_module.zeros(n_out, dtype=jnp_module.float64)
    for spec in output_specs:
        y = y.at[spec.y_slice].set(outputs[spec.block][spec.port_idx])

    return xdot, y


def linearize_via_jacfwd(
    simulator: Simulator,
    *,
    t: float,
    x_op: npt.NDArray[Any],
    u_op: npt.NDArray[Any],
    layout: list[tuple[Block, slice]],
    input_specs: list[_InputSpec],
    output_specs: list[_OutputSpec],
) -> tuple[
    npt.NDArray[Any],
    npt.NDArray[Any],
    npt.NDArray[Any],
    npt.NDArray[Any],
]:
    """``jax.jacfwd`` で ``(A, B, C, D)`` を計算する (ADR-0037 §(3))。

    Args:
        simulator: モデル (jax-native 評価対象、未サポートブロック含むなら事前に
            ``_validate_supported_blocks`` で検証済の前提)。
        t / x_op / u_op: 動作点。
        layout / input_specs / output_specs: 既存 ``linearize`` の中間結果を流用。

    Returns:
        ``(A, B, C, D)`` の 4-tuple、shape はそれぞれ
        ``(n_states, n_states)``, ``(n_states, n_in)``, ``(n_out, n_states)``,
        ``(n_out, n_in)``。すべて ``np.float64`` (= jax 64-bit 強制設定の結果)。
    """
    from .compiled_simulator import _ensure_jax_available

    jax = _ensure_jax_available()
    import jax.numpy as jnp

    x_jax = jnp.asarray(x_op, dtype=jnp.float64)
    u_jax = jnp.asarray(u_op, dtype=jnp.float64)
    t_jax = jnp.asarray(t, dtype=jnp.float64)

    def f(x: Any, u: Any) -> tuple[Any, Any]:
        return _evaluate_jax(simulator, t_jax, x, u, layout, input_specs, output_specs, jnp)

    n_states = x_jax.shape[0]
    n_in = u_jax.shape[0]

    # ∂(xdot, y) / ∂x: shape ((n_states, n_states), (n_out, n_states))
    A_jax, C_jax = jax.jacfwd(f, argnums=0)(x_jax, u_jax)
    # ∂(xdot, y) / ∂u: shape ((n_states, n_in), (n_out, n_in))
    B_jax, D_jax = jax.jacfwd(f, argnums=1)(x_jax, u_jax)

    # n_in / n_out が 0 のときは jax 戻り値が空配列 — np に変換して shape を整える。
    A = np.asarray(A_jax, dtype=np.float64).reshape((n_states, n_states))
    if n_in > 0:
        B = np.asarray(B_jax, dtype=np.float64).reshape((n_states, n_in))
    else:
        B = np.zeros((n_states, 0), dtype=np.float64)
    n_out = len(output_specs)
    if n_out > 0:
        C = np.asarray(C_jax, dtype=np.float64).reshape((n_out, n_states))
    else:
        C = np.zeros((0, n_states), dtype=np.float64)
    if n_out > 0 and n_in > 0:
        D = np.asarray(D_jax, dtype=np.float64).reshape((n_out, n_in))
    else:
        D = np.zeros((n_out, n_in), dtype=np.float64)
    return A, B, C, D
