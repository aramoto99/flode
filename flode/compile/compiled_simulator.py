"""``CompiledSimulator`` dataclass (ADR-0037 §(2))。

``Simulator.compile()`` の戻り値。frozen dataclass で副作用なし、内部 ``_step_fn``
は ``backend="jax"`` なら ``jax.jit`` 済関数、``backend="numpy"`` なら numpy 参照
実装の関数。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:  # pragma: no cover
    from ..analysis.linearize import LinearSystem
    from ..core.simulator import Simulator


@dataclass(frozen=True, eq=False)
class CompiledSimulator:
    """``Simulator.compile()`` で生成される pure functional simulator (ADR-0037 §(2))。

    ``backend`` ごとに ``_step_fn`` / ``_derivative_fn`` の実装が切替わる:

    * ``backend="jax"``: ``jax.jit`` で XLA HLO 化された関数 (= GPU/CPU 動的)
    * ``backend="numpy"``: numpy 参照実装 (= テスト / debug 用、ADR-0037 §(2-A))

    ``frozen=True, eq=False`` は ADR-0026 ``LinearSystem`` と同じパターン
    (= ndarray の自動 ``==`` がブロードキャスト不一致になるため)。

    Attributes:
        backend: ``"jax"`` または ``"numpy"``。
        n_states: 連続状態の総次元 (= ``LinearSystem.A.shape[0]`` と一致)。
        state_layout: ``[(block_id, slice), ...]``、``Simulator._state_layout()`` 由来。
        port_specs: 入出力 port の ``{block_id: [(port_idx, shape, dtype), ...]}``
            mapping (= SM-B vector port を pytree に変換するメタ情報、ADR-0037 §(5))。
        _simulator: 元の :class:`Simulator` への参照 (linearize / step で内部状態に
            アクセスするため)。``frozen=True`` でも ``ref`` 自体は変更しないので OK。

    Note:
        ``_step_fn`` / ``_derivative_fn`` は **内部実装** で副作用なし。``run()`` /
        ``step()`` / ``linearize()`` は self を変更しない (= 同じ ``CompiledSimulator``
        を複数スレッドから安全に呼べる)。
    """

    backend: Literal["jax", "numpy"]
    n_states: int
    state_layout: list[tuple[str, slice]]
    port_specs: dict[str, list[tuple[int, tuple[int, ...], type]]]
    # private 実装詳細 (= 直接アクセスするコードはテスト以外に書かない想定)
    _simulator: Simulator
    _step_fn: Callable[..., Any] | None = field(default=None, repr=False)
    _derivative_fn: Callable[..., Any] | None = field(default=None, repr=False)

    def linearize(
        self,
        *,
        t: float = 0.0,
        x: npt.NDArray[Any] | None = None,
        u: npt.NDArray[Any] | None = None,
    ) -> LinearSystem:
        """``backend`` に応じた線形化を行う (ADR-0037 §(3))。

        ``backend="jax"`` の場合は :func:`jax.jacfwd` で機械精度 Jacobian を計算、
        ``backend="numpy"`` の場合は ADR-0026 中心差分にフォールバック。

        Args:
            t: 動作点の時刻。
            x: 動作点の状態ベクトル (``None`` で ``Block.x0`` から初期化)。
            u: 動作点の外部入力ベクトル (``None`` で zeros)。

        Returns:
            :class:`LinearSystem` ((A, B, C, D) を含む dataclass、ADR-0026)。
            ``jacobian_method`` フィールドに ``"jax"`` または ``"central"`` が記録
            される (= ADR-0037 §(4))。

        Raises:
            BlockSpecError: モデル線形化要件 (連続状態 ≥ 1) を満たさない。
        """
        from ..analysis.linearize import linearize as _linearize_func

        method: Literal["central", "forward", "jax"] = "jax" if self.backend == "jax" else "central"
        return _linearize_func(self._simulator, t=t, x=x, u=u, method=method)

    def step(
        self,
        t: float,
        state: npt.NDArray[Any],
        inputs: dict[str, npt.NDArray[Any]],
    ) -> tuple[npt.NDArray[Any], dict[str, npt.NDArray[Any]]]:
        """1 ステップ遷移 (純粋関数、ADR-0037 §(2))。

        現在は API 予約のみ (= NotImplementedError)。v0.17.0 では
        :meth:`linearize` のみ実装され、``step`` / ``run`` は v0.17.1〜v0.17.2 で
        本格実装する (ADR-0037 §(8) commit 分割案)。
        """
        raise NotImplementedError(
            "CompiledSimulator.step() is reserved for v0.17.1+ (ADR-0037 §(8) commit "
            "10-15). For now, use Simulator.run() (numpy hot path) or "
            "CompiledSimulator.linearize() (jax autodiff)."
        )

    def run(
        self,
        t_end: float,
        *,
        dt: float = 0.01,
        **kwargs: Any,
    ) -> Any:
        """完全な ``run()`` 再現 (= 既存 Simulator.run() と同じ戻り値、ADR-0037 §(2))。

        現在は API 予約のみ。v0.17.0 では :meth:`linearize` のみ実装。
        """
        raise NotImplementedError(
            "CompiledSimulator.run() is reserved for v0.17.1+ (ADR-0037 §(8) commit "
            "10-15). For now, use Simulator.run() directly (numpy hot path)."
        )


def _ensure_jax_available() -> Any:
    """jax が利用可能か確認、未インストールなら明示エラー (ADR-0037 §Decision §6)。

    Returns:
        ``jax`` モジュール。

    Raises:
        ImportError: ``pyflw[codegen]`` 未インストール時。
    """
    try:
        import jax
    except ImportError as e:
        raise ImportError(
            "pyflw[codegen] is required for jax-backed compile / linearize. "
            "Install with: pip install pyflw[codegen] (= jax[cpu]>=0.4,<0.5). "
            "GPU support: pip install pyflw[gpu] (= jax[cuda12]). "
            "See ADR-0037 §Decision §6 / docs/codegen_guide.rst for details."
        ) from e
    # ADR-0037 §Risks #2: 64-bit 強制を遅延設定 (= ML エコシステムへの副作用最小化)。
    # 既に有効なら no-op、無効なら True に設定 (= numpy default の 64-bit と整合)。
    if not jax.config.read("jax_enable_x64"):
        jax.config.update("jax_enable_x64", True)
    return jax


def _build_compiled_simulator(
    simulator: Simulator,
    *,
    backend: Literal["jax", "numpy"] = "jax",
) -> CompiledSimulator:
    """``Simulator.compile()`` の本体 (ADR-0037 §Decision §(2))。

    ``backend="jax"`` の場合に :func:`_ensure_jax_available` でガードし、必要な
    metadata (state_layout / port_specs) を ``Simulator`` から抽出して
    :class:`CompiledSimulator` を組み立てる。

    Args:
        simulator: 元の Simulator (= まだ ``run()`` 前でもよいが ``add_block`` 済みの
            状態であること)。
        backend: ``"jax"`` または ``"numpy"``。

    Raises:
        ImportError: ``backend="jax"`` で ``pyflw[codegen]`` 未インストール。
        BlockSpecError: モデル内に jax tracing 不可能なブロック (= Subsystem 内部に
            等) がある (ADR-0036 §(9) / ADR-0037 §Decision §(10) 規約)。
    """
    from ..exceptions import BlockSpecError
    from ..subsystems.control_blocks import Enable, Trigger
    from ..subsystems.subsystem import Subsystem

    if backend not in ("jax", "numpy"):
        raise ValueError(f"Simulator.compile: backend must be 'jax' or 'numpy', got {backend!r}")
    if backend == "jax":
        _ensure_jax_available()

    # ADR-0036 §(9) / ADR-0058 §論点 5: 内部に Trigger / Enable control block を
    # 持つ Subsystem は MVP で codegen 対象外。明示的に拒否してエラーメッセージで
    # 旧 numpy hot path 経路へ誘導する (= jax_backend allowlist 経由でも reject
    # されるが、ここでは「内部 control block の有無」を判定して具体的なメッセージ
    # を返す)。schema 0.8 → 0.9 migration 後は class 自体が存在しないため、
    # Subsystem 内部の Trigger / Enable filter で検出する。
    # NOTE: ``simulator.blocks`` は root 直下のフラットなリストで、ネスト Subsystem
    # 内部の control block は本ループで検出しない (= 階層の最外側だけ判定すれば
    # codegen build 時に jax tracing が同等の boundary block で hit するため十分)。
    # NOTE: ``backend in {"jax", "numpy"}`` の両方で reject する。``backend="numpy"``
    # の compile path も JAX-style 純関数 view を生成する経路で、Trigger/Enable の
    # state mutation を扱うランタイムを実装していない (= Phase 6+ で再設計)。
    for b in simulator.blocks:
        if isinstance(b, Subsystem):
            inner_blocks = getattr(b, "_inner_blocks", [])
            has_control = any(isinstance(ib, (Trigger, Enable)) for ib in inner_blocks)
            if has_control:
                raise BlockSpecError(
                    f"Simulator.compile: Subsystem {b.id!r} contains a Trigger / "
                    f"Enable control block; codegen is out of scope in MVP "
                    f"(ADR-0036 §(9) / ADR-0037 §Decision §(10) / ADR-0058 §論点 5). "
                    f"Use Simulator.run() (numpy hot path) which handles edge / "
                    f"enable gating, or wait for Phase 6+ JAX tracing extension."
                )

    # state_layout 抽出 (= Simulator._state_layout 互換、戻り値 (layout, n_total))
    layout, n_total = simulator._state_layout()
    state_layout: list[tuple[str, slice]] = [
        (b.id if b.id is not None else "", sl) for b, sl in layout
    ]
    n_states = n_total

    # port_specs 抽出 (= SM-B port shape を保持、ADR-0037 §(5))
    port_specs: dict[str, list[tuple[int, tuple[int, ...], type]]] = {}
    for b in simulator.blocks:
        block_id = b.id if b.id is not None else ""
        port_specs[block_id] = []
        for port_idx, shape in enumerate(b.port_shapes_in):
            port_specs[block_id].append((port_idx, tuple(shape), np.float64))

    return CompiledSimulator(
        backend=backend,
        n_states=n_states,
        state_layout=state_layout,
        port_specs=port_specs,
        _simulator=simulator,
    )
