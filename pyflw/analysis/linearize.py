"""モデル線形化 (ADR-0026)。

動作点 ``(t*, x*, u*)`` 周りで非線形モデルを線形化し、状態空間モデル
``(A, B, C, D)`` を返す。

設計方針:

- **数値手法**: 中心差分 default (誤差 O(h²))、`method="forward"` で前進差分
  (半分のコスト + 誤差 O(h)) を opt-in。`method="jax"` は将来 Phase 5 GPU で
  追加する API スロットのみ確保 (現状は :class:`NotImplementedError`)。
- **依存追加なし**: numpy / scipy のみ。`python-control` は :func:`LinearSystem.to_control_ss`
  経由でのみ使い、未インストールでも本モジュールは動作する。
- **既存 33 ブロック無改修**: ``Block.derivative`` / ``Block.output`` (および SM-B の
  ``output_v``) を観察するだけ。Block 基底契約は不変。
- **MVP scope**: 連続のみ線形化。離散ブロックは動作点で固定 + warning。連続状態が
  ゼロのモデルは :class:`BlockSpecError` で拒否。
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import numpy as np

from ..exceptions import BlockSpecError, SolverError

if TYPE_CHECKING:  # pragma: no cover - import 循環回避
    from ..core.block import Block
    from ..core.simulator import Simulator
    from .frequency_response import BodeResponse, NyquistResponse
    from .stability import RootLocus

_logger = logging.getLogger("pyflw.analysis.linearize")

#: 中心差分 / 前進差分の摂動係数 default。
#: ``sqrt(machine_eps)`` は中心差分の最適 step として古典的に採用される値
#: (打ち切り誤差と桁落ち誤差のバランス)。
SQRT_EPS: float = float(np.sqrt(np.finfo(np.float64).eps))


@dataclass(frozen=True, eq=False)
class LinearSystem:
    """線形化結果の状態空間表現。

    ``x_dot = A @ x + B @ u``、``y = C @ x + D @ u`` を表す。

    Attributes:
        A: システム行列、shape ``(n, n)``。``n`` は連続状態の総次元
            (Subsystem 内部含む、:meth:`Simulator._state_layout` の登録順)。
        B: 入力行列、shape ``(n, m)``。``m`` は外部入力 (= 結線されていない
            入力ポートを SM-B port shape ごと flatten した次元) の合計。
        C: 出力行列、shape ``(p, n)``。``p`` は外部出力 (= ``Scope`` を駆動する
            か、どのブロックにも消費されない出力ポートを flatten した次元) の合計。
        D: 直達行列、shape ``(p, m)``。
        state_names: 各状態次元のラベル ``"{block_id}.x[{i}]"``。長さ ``n``。
        input_names: 各入力次元のラベル ``"{block_id}.in[{port_idx}][{flat_idx}]"``。
            長さ ``m``。
        output_names: 各出力次元のラベル ``"{block_id}.out[{port_idx}][{flat_idx}]"``。
            長さ ``p``。
        operating_point: 動作点 ``{"t": float, "x": ndarray, "u": ndarray}``
            (再現性 + デバッグ用)。

    Note:
        ``frozen=True, eq=False`` で実装している。``eq=True`` だと dataclass の
        自動生成 ``__eq__`` が numpy 配列を ``==`` 比較し、ブロードキャスト結果が
        truth-ambiguous になるため。テストでは :func:`numpy.testing.assert_allclose`
        で要素ごとに比較する。
    """

    A: np.ndarray
    B: np.ndarray
    C: np.ndarray
    D: np.ndarray
    state_names: list[str]
    input_names: list[str]
    output_names: list[str]
    operating_point: dict[str, Any]

    def to_control_ss(self) -> Any:
        """``python-control`` の ``StateSpace`` インスタンスに変換する。

        Returns:
            ``control.StateSpace(A, B, C, D)``。

        Raises:
            ImportError: ``python-control`` がインストールされていない。
                ``pip install pyflw[control]`` を案内する。

        Example:
            >>> ls = sim.linearize()  # doctest: +SKIP
            >>> ax = ls.bode().plot()  # 直接 Bode 線図を描画 (ADR-0027)
        """
        try:
            import control as _control
        except ImportError as e:
            raise ImportError(
                "LinearSystem.to_control_ss() requires the optional `python-control` "
                "package. Install via `pip install pyflw[control]` or "
                "`pip install python-control`."
            ) from e
        return _control.ss(self.A, self.B, self.C, self.D)

    # ADR-0027 §(1)C: 委譲メソッド (= ``Simulator.linearize`` パターン)。循環 import を
    # 避けるため、各メソッドの中で対応関数を遅延 import する。
    def bode(
        self,
        *,
        omega: np.ndarray | None = None,
        omega_limits: tuple[float, float] | None = None,
        omega_num: int | None = None,
        Hz: bool = False,
    ) -> BodeResponse:
        """Bode 応答を計算する (:func:`pyflw.bode` への薄ラッパ、ADR-0027)。"""
        from .frequency_response import bode as _bode

        return _bode(
            self,
            omega=omega,
            omega_limits=omega_limits,
            omega_num=omega_num,
            Hz=Hz,
        )

    def nyquist(
        self,
        *,
        omega: np.ndarray | None = None,
        omega_limits: tuple[float, float] | None = None,
        omega_num: int | None = None,
    ) -> NyquistResponse:
        """Nyquist 軌跡を計算する (:func:`pyflw.nyquist` への薄ラッパ、ADR-0027)。"""
        from .frequency_response import nyquist as _nyquist

        return _nyquist(
            self, omega=omega, omega_limits=omega_limits, omega_num=omega_num
        )

    def eigenvalues(self) -> np.ndarray:
        """A 行列の固有値 (:func:`pyflw.eigenvalues` への薄ラッパ、ADR-0027)。"""
        from .stability import eigenvalues as _eigenvalues

        return _eigenvalues(self)

    def is_stable(self, *, tol: float = 1e-9) -> bool:
        """漸近安定性判定 (:func:`pyflw.is_stable` への薄ラッパ、ADR-0027)。"""
        from .stability import is_stable as _is_stable

        return _is_stable(self, tol=tol)

    def root_locus(
        self,
        *,
        k_range: tuple[float, float] | np.ndarray | None = None,
        input_idx: int = 0,
        output_idx: int = 0,
    ) -> RootLocus:
        """根軌跡を計算する (:func:`pyflw.root_locus` への薄ラッパ、ADR-0027)。"""
        from .stability import root_locus as _root_locus

        return _root_locus(
            self, k_range=k_range, input_idx=input_idx, output_idx=output_idx
        )


# ---------------------------------------------------------------------------
# 入出力次元の解決
# ---------------------------------------------------------------------------


def _is_sink(block: Block) -> bool:
    """記録専用 (sink) ブロックの duck-type 判定。

    判定条件: ``n_outputs == 0`` かつ ``record(t, u)`` メソッドを持つ。Phase 3
    時点で該当するのは Scope / Display / XYGraph の 3 種。``Terminator`` は
    ``record`` を持たないので sink としてはカウントしない (= 線形化の出力
    ベクトルに観察ポイントを追加したい場合は Scope 等に繋ぎ替える必要がある)。
    """
    return block.n_outputs == 0 and hasattr(block, "record")


def _drives_sink(simulator: Simulator, src_block: Block, src_idx: int) -> bool:
    """``(src_block, src_idx)`` を入力に持つ sink ブロックがあるか。"""
    for b in simulator.blocks:
        for src in b.input_sources:
            if src is not None and src[0] is src_block and src[1] == src_idx:
                if _is_sink(b):
                    return True
    return False


def _has_non_sink_consumer(
    simulator: Simulator, src_block: Block, src_idx: int
) -> bool:
    """``(src_block, src_idx)`` を sink 以外のブロックが入力にしているか。"""
    for b in simulator.blocks:
        for src in b.input_sources:
            if src is not None and src[0] is src_block and src[1] == src_idx:
                if not _is_sink(b):
                    return True
    return False


@dataclass(frozen=True)
class _InputSpec:
    """B 行列の 1 列に対応する外部入力次元。"""

    block: Block
    port_idx: int
    flat_idx: int  # SM-B vector port 内の flatten index (scalar port は 0)
    u_slice: int  # 全体 u_ext 配列内の位置 (= B 行列の列インデックス)


@dataclass(frozen=True)
class _OutputSpec:
    """C 行列の 1 行に対応する外部出力次元。"""

    block: Block
    port_idx: int
    flat_idx: int
    y_slice: int  # 全体 y_ext 配列内の位置 (= C 行列の行インデックス)


def _build_input_specs(simulator: Simulator) -> list[_InputSpec]:
    """外部入力ポート (= 結線されていない入力ポート) の flatten 仕様を構築。

    sink ブロック (Scope / Display / XYGraph、= ``_is_sink`` で True 判定。
    ``Terminator`` は ``record`` を持たないので除外) の未結線入力は **外部入力
    として扱わない** — sink は記録専用で動的システムを駆動しないため、
    Jacobian 列に含めると常に全ゼロ列になり、ユーザーが Bode / 安定性解析する
    際に混乱の元になる。
    """
    specs: list[_InputSpec] = []
    pos = 0
    for b in simulator.blocks:
        if _is_sink(b):
            # sink の未結線入力は線形化の対象外 (= record しか呼ばれない)
            continue
        for i in range(b.n_inputs):
            if b.input_sources[i] is not None:
                continue
            shape = b.port_shapes_in[i]
            n = int(np.prod(shape)) if shape else 1
            for flat in range(n):
                specs.append(_InputSpec(block=b, port_idx=i, flat_idx=flat, u_slice=pos))
                pos += 1
    return specs


def _build_output_specs(simulator: Simulator) -> list[_OutputSpec]:
    """外部出力ポートの flatten 仕様を構築。

    採用条件 (ADR-0026 §(6) 出力次元):
    - 下流に sink (Scope / Display / XYGraph 等) を駆動するポート、または
    - どのブロックにも消費されていないポート

    ただし sink 以外の non-sink 消費者がいるポートは内部信号として除外する
    (= 純粋な内部結線は外部に露出しない)。
    """
    specs: list[_OutputSpec] = []
    pos = 0
    for b in simulator.blocks:
        if _is_sink(b):
            # sink ブロック自体は外部出力を提供しない (記録は record で済む)
            continue
        for j in range(b.n_outputs):
            drives_sink = _drives_sink(simulator, b, j)
            has_non_sink = _has_non_sink_consumer(simulator, b, j)
            if has_non_sink and not drives_sink:
                # 純粋な内部信号
                continue
            shape = b.port_shapes_out[j]
            n = int(np.prod(shape)) if shape else 1
            for flat in range(n):
                specs.append(_OutputSpec(block=b, port_idx=j, flat_idx=flat, y_slice=pos))
                pos += 1
    return specs


def _build_state_names(layout: list[tuple[Block, slice]]) -> list[str]:
    """A 行列の各次元のラベル ``{block_id}.x[{i}]`` を生成。"""
    names: list[str] = []
    for b, sl in layout:
        for i in range(sl.stop - sl.start):
            names.append(f"{b.id}.x[{i}]")
    return names


def _build_input_names(specs: list[_InputSpec]) -> list[str]:
    return [f"{s.block.id}.in[{s.port_idx}][{s.flat_idx}]" for s in specs]


def _build_output_names(specs: list[_OutputSpec]) -> list[str]:
    return [f"{s.block.id}.out[{s.port_idx}][{s.flat_idx}]" for s in specs]


# ---------------------------------------------------------------------------
# 動作点での評価 (xdot, y_external) の計算
# ---------------------------------------------------------------------------


def _evaluate(
    simulator: Simulator,
    t: float,
    x_cont: np.ndarray,
    u_ext: np.ndarray,
    *,
    order: list[Block],
    layout: list[tuple[Block, slice]],
    n_states: int,
    discrete_state: dict[Block, np.ndarray],
    input_specs: list[_InputSpec],
    output_specs: list[_OutputSpec],
    sm_a_mode: bool,
) -> tuple[np.ndarray, np.ndarray]:
    """動作点 ``(t, x_cont, u_ext)`` で ``(xdot, y_external)`` を計算。

    ``Simulator._step`` / ``_step_vector`` のロジックを copy しつつ、結線されていない
    入力ポート (= ``input_sources[i] is None``) に ``u_ext`` の対応 slice を注入する
    (= 既存 hot path に minimal-invasive)。``record`` / ``update`` は副作用がある
    ため一切呼ばない (動作点固定)。
    """
    # ----- u_ext を block ごとの input dict に振り分ける -----
    # SM-A: block.id -> {port_idx: float}
    # SM-B: block.id -> {port_idx: ndarray (port_shape)}
    external_inputs_a: dict[int, dict[int, float]] = {}
    external_inputs_b: dict[int, dict[int, np.ndarray]] = {}
    if sm_a_mode:
        for s in input_specs:
            external_inputs_a.setdefault(id(s.block), {})[s.port_idx] = float(
                u_ext[s.u_slice]
            )
    else:
        # SM-B: port ごとに flat_idx を集めて C-order reshape
        # まず block_id -> port_idx -> flat array を組み立てる
        per_port: dict[int, dict[int, list[tuple[int, float]]]] = {}
        for s in input_specs:
            per_port.setdefault(id(s.block), {}).setdefault(s.port_idx, []).append(
                (s.flat_idx, float(u_ext[s.u_slice]))
            )
        for bid, ports in per_port.items():
            external_inputs_b[bid] = {}
            for p_idx, entries in ports.items():
                # block を再取得 (id() 経由ではなく specs から拾う)
                # 同 (bid, p_idx) に対応する任意の spec から block を取り出す
                _block = next(
                    s.block for s in input_specs if id(s.block) == bid and s.port_idx == p_idx
                )
                shape = _block.port_shapes_in[p_idx]
                flat_size = int(np.prod(shape)) if shape else 1
                buf = np.zeros(flat_size, dtype=float)
                for flat, val in entries:
                    buf[flat] = val
                external_inputs_b[bid][p_idx] = (
                    buf.reshape(shape) if shape else buf.reshape(())
                )

    # ----- 連続状態を block 別に slice -----
    cont_state = {b: x_cont[sl] for b, sl in layout}

    def state_for(b: Block) -> np.ndarray:
        if b in cont_state:
            return cont_state[b]
        if b in discrete_state:
            return discrete_state[b]
        return np.zeros(0)

    # ----- SM-A 経路 -----
    if sm_a_mode:
        outputs_a: dict[Block, np.ndarray] = {}
        inputs_a: dict[Block, np.ndarray] = {}

        def gather_inputs_a(b: Block) -> np.ndarray:
            u = np.zeros(b.n_inputs)
            ext = external_inputs_a.get(id(b), {})
            for i, src in enumerate(b.input_sources):
                if src is not None:
                    sb, si = src
                    u[i] = outputs_a[sb][si]
                elif i in ext:
                    u[i] = ext[i]
                # else: 0 (= 未結線で u_ext 対象でないケースは MVP では起きない)
            return u

        # Pass 1: direct_feedthrough ブロックの output
        for b in order:
            if b.direct_feedthrough:
                u = gather_inputs_a(b)
                inputs_a[b] = u
            else:
                u = np.zeros(b.n_inputs)
            xb = state_for(b)
            y = np.atleast_1d(np.asarray(b.output(t, xb, u), dtype=float))
            outputs_a[b] = y
        # Pass 2: 非 direct_feedthrough の入力を後から組み立て
        for b in order:
            if not b.direct_feedthrough:
                inputs_a[b] = gather_inputs_a(b)

        # 連続ブロックの xdot
        xdot = np.zeros(n_states)
        for b, sl in layout:
            xdot[sl] = np.asarray(b.derivative(t, x_cont[sl], inputs_a[b]), dtype=float)

        # 外部出力 y_external を取り出す
        y_ext = np.zeros(len(output_specs))
        for os_a in output_specs:
            y_ext[os_a.y_slice] = float(outputs_a[os_a.block][os_a.port_idx])
        return xdot, y_ext

    # ----- SM-B 経路 -----
    outputs_b: dict[Block, tuple[np.ndarray, ...]] = {}
    inputs_b: dict[Block, tuple[np.ndarray, ...]] = {}

    def zero_inputs_b(b: Block) -> tuple[np.ndarray, ...]:
        return tuple(np.zeros(shape, dtype=float) for shape in b.port_shapes_in)

    def gather_inputs_b(b: Block) -> tuple[np.ndarray, ...]:
        u_list: list[np.ndarray] = []
        ext = external_inputs_b.get(id(b), {})
        for i, src in enumerate(b.input_sources):
            if src is None:
                if i in ext:
                    u_list.append(ext[i])
                else:
                    u_list.append(np.zeros(b.port_shapes_in[i], dtype=float))
            else:
                sb, si = src
                u_list.append(outputs_b[sb][si])
        return tuple(u_list)

    for b in order:
        u_b: tuple[np.ndarray, ...]
        if b.direct_feedthrough:
            u_b = gather_inputs_b(b)
            inputs_b[b] = u_b
        else:
            u_b = zero_inputs_b(b)
        xb = state_for(b)
        y_b = b.output_v(t, xb, u_b)
        if len(y_b) != b.n_outputs:
            raise BlockSpecError(
                f"{type(b).__name__} {b.id!r}.output_v returned {len(y_b)} "
                f"output(s), expected {b.n_outputs}"
            )
        outputs_b[b] = tuple(np.asarray(yi, dtype=float) for yi in y_b)
    for b in order:
        if not b.direct_feedthrough:
            inputs_b[b] = gather_inputs_b(b)

    # SM-B 連続ブロックの xdot: SM-A 互換 wrapper (Simulator.f_continuous_vector と同じ)。
    # NOTE: ``Block.derivative`` の契約 (ADR-0001) は SM-A 1D ndarray (= 各 port が
    # scalar) を前提とする。SM-B vector port を持つカスタム連続ブロック (= ``@block``
    # で states>=1 かつ非 scalar port を宣言) は本 MVP では未対応。``derivative_v``
    # の追加は Phase 5+ (ADR-0026 §(10) note)。各入力 port の値が rank-0 でない場合
    # は明示エラーで誘導する (silent な ValueError を防ぐ)。
    xdot = np.zeros(n_states)
    for b, sl in layout:
        u_tuple = inputs_b[b]
        if any(np.asarray(ui).size != 1 for ui in u_tuple):
            raise BlockSpecError(
                f"linearize: block {b.id!r} has continuous states and SM-B vector "
                f"input ports. Vector-port continuous blocks are not yet supported "
                f"(Phase 5+, ADR-0026 §(10))."
            )
        u_1d = np.array(
            [float(np.asarray(ui).item()) for ui in u_tuple], dtype=float
        )
        xdot[sl] = np.asarray(b.derivative(t, x_cont[sl], u_1d), dtype=float)

    # 外部出力 y_external を取り出す (port shape を C-order で flatten)
    y_ext = np.zeros(len(output_specs))
    for os_b in output_specs:
        out_arr = np.asarray(
            outputs_b[os_b.block][os_b.port_idx], dtype=float
        ).ravel(order="C")
        y_ext[os_b.y_slice] = float(out_arr[os_b.flat_idx])
    return xdot, y_ext


# ---------------------------------------------------------------------------
# 中心差分 / 前進差分による Jacobian 計算
# ---------------------------------------------------------------------------


def _step_size(value: float, epsilon: float | None) -> float:
    """1 次元あたりの摂動 step。

    ``epsilon`` 指定時は相対 step、未指定時は ``sqrt(eps_machine)`` を採用。
    どちらも ``max(|value|, 1)`` でスケーリングする (零点近傍での桁落ちを防ぐ)。
    """
    base = epsilon if epsilon is not None else SQRT_EPS
    return base * max(abs(value), 1.0)


# ---------------------------------------------------------------------------
# 公開 API: linearize()
# ---------------------------------------------------------------------------


def linearize(
    simulator: Simulator,
    *,
    t: float = 0.0,
    x: np.ndarray | None = None,
    u: np.ndarray | None = None,
    method: Literal["central", "forward", "jax"] = "central",
    epsilon: float | None = None,
) -> LinearSystem:
    """動作点 ``(t, x, u)`` 周りでモデルを線形化し ``(A, B, C, D)`` を返す。

    Args:
        simulator: 線形化対象の :class:`Simulator`。``run()`` 前後どちらでも可
            (本関数は副作用を持たない: ``record`` / ``update`` を呼ばず、
            ``Simulator`` の状態を変更しない)。
        t: 動作点時刻 [s]。default ``0.0``。
        x: 連続状態の動作点。shape ``(n_states,)``。``None`` のとき各ブロックの
            ``x0`` を ``simulator._state_layout()`` 順に concat したもの。
        u: 外部入力の動作点。shape ``(n_inputs_total,)``。``None`` のとき全ゼロ。
        method: 数値手法。

            - ``"central"`` (default): 中心差分、誤差 O(h²)、評価 2n+1 回
            - ``"forward"``: 前進差分、誤差 O(h)、評価 n+1 回
            - ``"jax"``: Phase 5 で追加予定 (現状 :class:`NotImplementedError`)
        epsilon: 摂動相対サイズ。``None`` のとき次元ごとに
            ``h_i = sqrt(eps_machine) * max(|x_i|, 1.0)`` を自動採用。

    Returns:
        :class:`LinearSystem` インスタンス。

    Raises:
        AlgebraicLoopError: 動作点でビルド時に代数ループが検出される
            (``Simulator._execution_order()`` 経由)。Sum + Gain で
            direct_feedthrough だけのフィードバックを組むと発火する。
        BlockSpecError: 連続状態がゼロのモデル / ``x`` ``u`` の shape 不整合 /
            出力 ndim 不整合などの構造エラー。
        SolverError: 動作点で ``derivative`` または ``output`` が NaN / Inf を返す。
        ValueError: ``method`` / ``epsilon`` の値が不正。
        NotImplementedError: ``method="jax"`` (Phase 5+ で追加予定)。

    Example:
        Integrator with one external input:

        >>> from pyflw import Simulator, linearize
        >>> from pyflw.blocks import Integrator, Scope
        >>> sim = Simulator(t_end=10.0, dt=0.01)
        >>> i_block = sim.add(Integrator())
        >>> sim.connect(i_block, sim.add(Scope()))
        >>> ls = linearize(sim)
        >>> ls.A.shape  # (n_states, n_states)
        (1, 1)
        >>> ls.B.shape  # (n_states, n_external_inputs)
        (1, 1)
        >>> ls.C.shape  # (n_external_outputs, n_states)
        (1, 1)
    """
    if method == "jax":
        raise NotImplementedError(
            "method='jax' is reserved for Phase 5+ (GPU + autodiff). "
            "Use method='central' (default) or method='forward' for now."
        )
    if method not in ("central", "forward"):
        raise ValueError(
            f"linearize: method must be 'central' or 'forward' (or 'jax' Phase 5+), "
            f"got {method!r}"
        )
    if epsilon is not None and epsilon <= 0.0:
        raise ValueError(f"linearize: epsilon must be > 0 (or None for auto), got {epsilon}")

    # ----- Simulator setup (build / sample-time / state layout) -----
    order = simulator._execution_order()  # _build() を triggered
    if simulator._is_sm_a_mode():
        sm_a_mode = True
    else:
        sm_a_mode = False
        simulator._check_scope_inputs_are_scalar()
        simulator._check_subsystem_sm_b_unsupported()
    simulator._resolve_sample_times(order)
    simulator._compute_dt_base()
    layout, n_states = simulator._state_layout()

    if n_states == 0:
        raise BlockSpecError(
            "linearize: model has no continuous states. Linearisation requires "
            "at least one continuous block (e.g. Integrator / StateSpace / "
            "TransferFunction). Pure discrete or static models are not supported "
            "in this MVP (ADR-0026 §(8))."
        )

    # 離散ブロックは動作点固定 (x0) で warning を出す
    discrete_state = simulator._init_discrete_state()
    if discrete_state:
        msg = (
            "linearize: discrete blocks are held at their initial values during "
            "linearisation (continuous-only Jacobian, ADR-0026 §(8)). Hybrid "
            "linearisation will be addressed in Phase 5+."
        )
        warnings.warn(msg, UserWarning, stacklevel=2)
        _logger.warning(msg)

    # ----- 入出力次元の解決 -----
    input_specs = _build_input_specs(simulator)
    output_specs = _build_output_specs(simulator)
    n_in = len(input_specs)
    n_out = len(output_specs)

    # ----- 動作点 (x*, u*) のセットアップ -----
    if x is None:
        x_op = np.zeros(n_states)
        for b, sl in layout:
            x_op[sl] = np.asarray(b.x0, dtype=float)
    else:
        x_op = np.asarray(x, dtype=float).copy()
        if x_op.shape != (n_states,):
            raise BlockSpecError(
                f"linearize: x must have shape ({n_states},), got {x_op.shape}"
            )

    if u is None:
        u_op = np.zeros(n_in)
    else:
        u_op = np.asarray(u, dtype=float).copy()
        if u_op.shape != (n_in,):
            raise BlockSpecError(
                f"linearize: u must have shape ({n_in},), got {u_op.shape}"
            )

    # ----- 動作点で 1 回評価 (Forward 差分用 base、結果 sanity check) -----
    def evaluate(t_eval: float, x_eval: np.ndarray, u_eval: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return _evaluate(
            simulator,
            t_eval,
            x_eval,
            u_eval,
            order=order,
            layout=layout,
            n_states=n_states,
            discrete_state=discrete_state,
            input_specs=input_specs,
            output_specs=output_specs,
            sm_a_mode=sm_a_mode,
        )

    xdot0, y0 = evaluate(t, x_op, u_op)
    if not np.all(np.isfinite(xdot0)) or not np.all(np.isfinite(y0)):
        raise SolverError(
            "linearize: derivative() or output() returned NaN/Inf at the operating "
            "point. Check block parameters and the chosen (t, x, u)."
        )

    # ----- A = ∂xdot/∂x、C = ∂y/∂x の Jacobian -----
    A = np.zeros((n_states, n_states), dtype=float)
    C = np.zeros((n_out, n_states), dtype=float)
    for i in range(n_states):
        h = _step_size(float(x_op[i]), epsilon)
        if h == 0.0:
            continue
        if method == "central":
            x_plus = x_op.copy()
            x_plus[i] += h
            xdot_p, y_p = evaluate(t, x_plus, u_op)
            x_minus = x_op.copy()
            x_minus[i] -= h
            xdot_m, y_m = evaluate(t, x_minus, u_op)
            A[:, i] = (xdot_p - xdot_m) / (2.0 * h)
            C[:, i] = (y_p - y_m) / (2.0 * h)
        else:  # forward
            x_plus = x_op.copy()
            x_plus[i] += h
            xdot_p, y_p = evaluate(t, x_plus, u_op)
            A[:, i] = (xdot_p - xdot0) / h
            C[:, i] = (y_p - y0) / h

    # ----- B = ∂xdot/∂u、D = ∂y/∂u の Jacobian -----
    B = np.zeros((n_states, n_in), dtype=float)
    D = np.zeros((n_out, n_in), dtype=float)
    for i in range(n_in):
        h = _step_size(float(u_op[i]), epsilon)
        if h == 0.0:
            continue
        if method == "central":
            u_plus = u_op.copy()
            u_plus[i] += h
            xdot_p, y_p = evaluate(t, x_op, u_plus)
            u_minus = u_op.copy()
            u_minus[i] -= h
            xdot_m, y_m = evaluate(t, x_op, u_minus)
            B[:, i] = (xdot_p - xdot_m) / (2.0 * h)
            D[:, i] = (y_p - y_m) / (2.0 * h)
        else:  # forward
            u_plus = u_op.copy()
            u_plus[i] += h
            xdot_p, y_p = evaluate(t, x_op, u_plus)
            B[:, i] = (xdot_p - xdot0) / h
            D[:, i] = (y_p - y0) / h

    return LinearSystem(
        A=A,
        B=B,
        C=C,
        D=D,
        state_names=_build_state_names(layout),
        input_names=_build_input_names(input_specs),
        output_names=_build_output_names(output_specs),
        operating_point={"t": float(t), "x": x_op.copy(), "u": u_op.copy()},
    )
