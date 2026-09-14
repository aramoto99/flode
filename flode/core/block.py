"""Block 基底クラス。

ADR-0002 (離散時間サポート) で `sample_time` 属性と `update` メソッドを追加。
ADR-0004 (ブロック ID 規則) で `id` 属性を正式名として導入し、`name` を後方互換 alias 化。
ADR-0003 (`@block` DSL) で `_params` 辞書をオプション属性として宣言 (デコレータ生成 class
が書き込む。Phase 2 JSON save/load で参照予定)。
ADR-0017 (信号モデル SM-B) で ``port_shapes_in`` / ``port_shapes_out`` 属性と
``output_v`` メソッドを追加 (各ポートが任意 shape の ndarray を運ぶベクトルポート)。
SM-A (各ポート = 1 スカラー) は ``port_shapes = ()`` (rank-0) の特殊ケースとして表現。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, ClassVar

import numpy as np
import numpy.typing as npt

from ..exceptions import BlockSpecError
from .identifiers import normalize_block_id, validate_block_id

# ADR-0017 §(3): SM-A 互換 (rank-0 scalar) を表す port shape
_SCALAR_SHAPE: tuple[int, ...] = ()

#: SPEC-0030 (v0.58.0): ``sample_time`` の文字列値「基準クロック (Simulator.dt) に
#: 同期」。系のクロック (明示値) とも上流同期 (-1) とも異なる第 3 の宣言で、
#: 観測・実験側の器具ブロックが「シミュレーションの基準格子で動く」ことを
#: 明示する (同期回路のクロック配線に相当)。常に解決可能 (基準クロックは
#: 常に存在する)。文字列 param の先例は dtype="auto" (SPEC-0028)。
BASE_CLOCK_SAMPLE_TIME: str = "dt"

_logger = logging.getLogger("flode.core.block")

# ---------------------------------------------------------------------------
# シリアライズ目的の build 区間 (bug-fix 2026-09-08)
#
# ``Subsystem.to_dict()`` は整合性チェックのため ``_build()`` を呼ぶが、
# ``PythonFunction._build()`` はユーザーコードを exec する。「save しただけで
# コードが実行される」のを防ぐため、シリアライズ区間を ContextVar で示し、
# exec を伴う build だけが自発的に skip する (構造チェックは従来どおり走る)。
# ContextVar のため新規スレッドには区間が漏れない。区間内で生成した asyncio
# task / to_thread には Context コピーで継承されるが、抑止 (exec しない) 方向
# なので安全側 (security-reviewer 実測 2026-09-08)。
#
# 区間中に (exec 抑止つきで) build された Subsystem は「不完全な built 状態」の
# ため、次の実行時 build で完全再構築が必要 = キャッシュを無効化する。ただし
# **無効化は最外区間の終了時にまとめて行う** (code-reviewer MUST 2026-09-08):
# 区間中に即時無効化すると、to_dict が同一 Subsystem を複数回訪問する既存経路
# (_build 内の _params 確定と to_dict 本体の両方が子の to_dict を呼ぶ) で
# キャッシュが効かなくなり、ネスト深さに対して build 回数が指数化する。
# 遅延方式なら区間内はキャッシュが従来どおり効き、build 回数は線形のまま。
# ---------------------------------------------------------------------------
_SERIALIZATION_STATE: ContextVar[list[Callable[[], None]] | None] = ContextVar(
    "flode_serialization_build", default=None
)


@contextmanager
def serialization_build() -> Iterator[None]:
    """「シリアライズ目的の ``_build()``」区間を宣言する context manager。

    区間内では ``in_serialization_build()`` が ``True`` を返し、ユーザーコードの
    exec を伴うブロック (``PythonFunction``) は build を skip する。
    区間中に ``register_serialization_invalidation`` で登録された無効化
    callback は、**最外区間の終了時** (元例外があってもその伝播前、まだ区間内の
    状態で) にまとめて実行される (ネストした区間は素通しで、登録は最外区間に
    集約される)。

    不変条件: callback は **副作用のない状態リセットに限る** (``_build()`` を
    誘発してはならない)。callback は区間内で実行されるため、万一 build を
    誘発しても exec は抑止されるが、設計としては禁止とする。callback の例外は
    ログに記録した上で握りつぶし、**全件を必ず実行**して元の例外を維持する。
    """
    if _SERIALIZATION_STATE.get() is not None:
        # 既に区間内 (ネスト): 新しい区間を張らず素通し
        yield
        return
    pending: list[Callable[[], None]] = []
    token = _SERIALIZATION_STATE.set(pending)
    try:
        yield
    finally:
        try:
            for invalidate in pending:
                try:
                    invalidate()
                except Exception:  # noqa: BLE001 - 全件実行し元の例外を維持する
                    _logger.exception("serialization invalidation callback failed (continuing)")
        finally:
            _SERIALIZATION_STATE.reset(token)


def in_serialization_build() -> bool:
    """現在シリアライズ目的の build 区間内かどうか。"""
    return _SERIALIZATION_STATE.get() is not None


def register_serialization_invalidation(invalidate: Callable[[], None]) -> None:
    """区間終了時に実行する無効化 callback を登録する (区間外では no-op)。"""
    pending = _SERIALIZATION_STATE.get()
    if pending is not None:
        pending.append(invalidate)


def _normalize_port_shapes(
    port_shapes: tuple[tuple[int, ...], ...] | list[tuple[int, ...]] | None,
    n_ports: int,
    side: str,
) -> tuple[tuple[int, ...], ...]:
    """``port_shapes_in`` / ``port_shapes_out`` を tuple-of-tuples に正規化する。

    Args:
        port_shapes: ユーザー指定の port shapes、または ``None`` (= 全 SM-A scalar)。
        n_ports: 期待ポート数 (``n_inputs`` または ``n_outputs``)。
        side: エラーメッセージ用 ("in" / "out")。

    Returns:
        ``tuple[tuple[int, ...], ...]`` 形式 (常に長さ ``n_ports``)。

    Raises:
        BlockSpecError: 長さ不一致、shape の要素が int でない、負の dim 等。
    """
    if port_shapes is None:
        return tuple(_SCALAR_SHAPE for _ in range(n_ports))
    if not isinstance(port_shapes, (list, tuple)):
        raise BlockSpecError(
            f"port_shapes_{side}: must be a sequence of shapes, got {type(port_shapes).__name__}"
        )
    if len(port_shapes) != n_ports:
        port_count_name = "n_inputs" if side == "in" else "n_outputs"
        raise BlockSpecError(
            f"port_shapes_{side}: length {len(port_shapes)} does not match "
            f"{port_count_name}={n_ports}"
        )
    normalized: list[tuple[int, ...]] = []
    for i, shape in enumerate(port_shapes):
        if not isinstance(shape, (list, tuple)):
            raise BlockSpecError(
                f"port_shapes_{side}[{i}]: must be a tuple of ints (got {type(shape).__name__})"
            )
        dims: list[int] = []
        for j, d in enumerate(shape):
            if not isinstance(d, (int, np.integer)) or isinstance(d, bool):
                raise BlockSpecError(
                    f"port_shapes_{side}[{i}][{j}]: each dim must be an int (got "
                    f"{type(d).__name__})"
                )
            d_int = int(d)
            if d_int < 0:
                raise BlockSpecError(
                    f"port_shapes_{side}[{i}][{j}]: dim must be non-negative, got {d_int}"
                )
            dims.append(d_int)
        normalized.append(tuple(dims))
    return tuple(normalized)


class Block:
    """全ブロックの基底クラス。

    Attributes:
        id: ブロック識別子。`None` の場合は ``Simulator.add`` で自動採番される。
        n_inputs: 入力ポート数。
        n_outputs: 出力ポート数。
        n_states: 状態次元数 (連続/離散とも n_states に集約)。
        direct_feedthrough: True なら入力 ``u`` が出力 ``y`` に直接影響する。
            False のブロック (Integrator, UnitDelay 等) が代数ループを切る。
        sample_time: ``None`` または ``0.0`` で連続、``> 0`` で離散周期 [s]、
            ``-1.0`` で上流のレートに同期 (ビルド時に解決。上流に離散レートが
            なければ離散専用ブロックはエラー)、``"dt"``
            (:data:`BASE_CLOCK_SAMPLE_TIME`) で基準クロック (Simulator.dt) に
            同期 (SPEC-0030)。
        x0: 初期状態 (shape ``(n_states,)``)。
        input_sources: 各入力ポートの接続元 ``(Block, output_idx)``。``None`` は未接続。
        port_shapes_in: 各入力ポートの shape (``tuple[tuple[int, ...], ...]``)。
            default は全 ``()`` (rank-0 scalar、SM-A 互換)。ADR-0017 SM-B。
        port_shapes_out: 各出力ポートの shape。同様 default 全 ``()``。

    Note:
        ADR-0017 SM-B: ベクトルポートを使うブロックは ``port_shapes_in`` /
        ``port_shapes_out`` を明示的に指定し、``output_v`` をオーバーライドする。
        SM-A (scalar-only) ブロックは default のままで動作 (``output`` のみ実装)。
    """

    #: D-4 (ADR-0077 / SPEC-0028 Q11): 全入力ポートに要求する dtype。
    #: ``None`` = 要求なし。連続系 / 離散 LTI ブロックが ``"float64"`` を宣言し、
    #: 型解決器 (``flode.core.dtypes``) が MRO 経由で読む (要求宣言の SSOT)。
    required_input_dtype: ClassVar[str | None] = None

    #: ADR-0002 §(2) 改訂 (v0.57.0→v0.58.0): ``sample_time=-1.0`` (上流に同期) が
    #: 上流に離散レートを見つけられなかったときの扱い。``True`` = 連続として
    #: 意味を持てない離散専用ブロック — **BlockSpecError** にする (連続扱いだと
    #: ``update()`` が呼ばれず無警告で凍結するため fail-closed。基準クロックで
    #: 動かしたい場合は ``sample_time="dt"`` を明示する)。``False`` (default) =
    #: 従来どおり連続 (None) に解決 — ``@block`` デコレータ製のポリモーフィック
    #: ブロック (ADR-0003: -1 + 連続上流 → 連続として動くのが意図された機能) と
    #: 無状態ブロックはこちら。
    requires_discrete_rate: ClassVar[bool] = False

    #: ADR-0078: サンプル時刻 ``t_k`` に記録 / ホールドされる出力を **update 前** の
    #: 状態から計算するブロック (「次状態」セマンティクス ``y_k = g(x_k)``、
    #: ``x_{k+1} = f(x_k, u_k)``; ``@block`` の離散ステートフルブロック)。``False``
    #: (default) は update 後の状態で出力を計算する (2-state 組込ブロックは
    #: update が表示側を変えないので無差別、Relay / RateLimiter 等の即時型
    #: 1-state ブロックは update 後の値が t_k の出力)。``PythonFunction`` が
    #: インスタンス単位で上書きするため ``ClassVar`` ではなく通常の属性。
    output_before_update: bool = False

    #: ``direct_feedthrough=False`` でも ``output()`` 時点で値が必要な **制御入力**
    #: ポートの index。スケジューラはこれらのポートだけを直達辺として依存グラフに
    #: 加え、パス 1 (出力計算) で値を組み立てる (データ経路は非直達のまま)。
    #: 用途: Enabled Subsystem の enable ポート (bug-fix 2026-09-13)。通常ブロック
    #: は空 tuple。``direct_feedthrough=True`` のブロックでは全ポートが直達なので
    #: 無視される。
    control_input_ports: tuple[int, ...] = ()

    def __init__(
        self,
        *,
        id: str | None = None,
        name: str | None = None,
        n_inputs: int = 1,
        n_outputs: int = 1,
        n_states: int = 0,
        direct_feedthrough: bool = True,
        sample_time: float | str | None = None,
        port_shapes_in: tuple[tuple[int, ...], ...] | list[tuple[int, ...]] | None = None,
        port_shapes_out: tuple[tuple[int, ...], ...] | list[tuple[int, ...]] | None = None,
    ) -> None:
        if id is not None and name is not None:
            raise BlockSpecError("id and name cannot both be set; use id (name is a Phase 0 alias)")
        resolved_id = id if id is not None else name
        if resolved_id is not None:
            # ADR-0071 §(3): 入口層で NFC 正規化してから検証・格納する
            if isinstance(resolved_id, str):
                resolved_id = normalize_block_id(resolved_id)
            validate_block_id(resolved_id)
        self._id: str | None = resolved_id

        if sample_time is not None:
            if isinstance(sample_time, str):
                # SPEC-0030 (v0.58.0): "dt" = 基準クロック (Simulator.dt) に同期
                if sample_time != BASE_CLOCK_SAMPLE_TIME:
                    raise BlockSpecError(
                        f"sample_time={sample_time!r} is invalid. The only string "
                        f"value is {BASE_CLOCK_SAMPLE_TIME!r} (sync to the base "
                        "clock dt). Numbers: None, 0.0 (continuous), >0 (discrete "
                        "period), -1.0 (inherited from upstream)."
                    )
            elif not isinstance(sample_time, (int, float)) or isinstance(sample_time, bool):
                # bool は int のサブクラスだが、True が黙って 1.0 秒周期になると
                # migration の静的判定 (bool 除外) と実行時が乖離する
                # (security SHOULD 2026-09-11)
                raise BlockSpecError(
                    f"sample_time must be a number, {BASE_CLOCK_SAMPLE_TIME!r} or "
                    f"None, got {type(sample_time).__name__}"
                )
            else:
                st = float(sample_time)
                if st < 0.0 and st != -1.0:
                    raise BlockSpecError(
                        f"sample_time={st} is invalid. Allowed: None, 0.0 (continuous), "
                        f">0 (discrete period), -1.0 (inherited from upstream), or "
                        f"{BASE_CLOCK_SAMPLE_TIME!r} (sync to the base clock dt)."
                    )
                sample_time = st

        self.n_inputs = n_inputs
        self.n_outputs = n_outputs
        self.n_states = n_states
        self.direct_feedthrough = direct_feedthrough
        self.sample_time: float | str | None = sample_time
        self.x0: npt.NDArray[Any] = np.zeros(n_states)
        self.input_sources: list[tuple[Block, int] | None] = [None] * n_inputs

        # ADR-0017 SM-B: port shapes (default 全 () = SM-A scalar)
        self.port_shapes_in: tuple[tuple[int, ...], ...] = _normalize_port_shapes(
            port_shapes_in, n_inputs, "in"
        )
        self.port_shapes_out: tuple[tuple[int, ...], ...] = _normalize_port_shapes(
            port_shapes_out, n_outputs, "out"
        )

        # ADR-0017 §(8) U3: ``output`` と ``output_v`` の両方を **leaf class で直接**
        # 定義するのは禁止 (実行時 check)。``cls.__dict__`` で直接定義されているか
        # 判定することで、Subsystem 等のフレームワーク内部実装が ``output`` を
        # override していても、leaf サブクラスが ``output_v`` のみを override した
        # ケースを誤検出しない (code-reviewer MUST 修正)。
        # ADR-0018 §(5): フレームワーク内部 class (``Inport`` / ``Outport`` 等) は
        # SM-A / SM-B の両 path で動くため両方 override が必要。``_skip_dual_api_check
        # = True`` を class 属性で立てて check を skip する (= 内部例外)。
        cls = type(self)
        if not getattr(cls, "_skip_dual_api_check", False):
            output_in_leaf = "output" in cls.__dict__
            output_v_in_leaf = "output_v" in cls.__dict__
            if output_in_leaf and output_v_in_leaf:
                raise BlockSpecError(
                    f"{cls.__name__}: must override either `output` (SM-A) or `output_v` (SM-B), "
                    f"not both. SM-A blocks should use `output` only; SM-B-aware blocks (e.g. "
                    f"Mux/Demux with vector ports) should use `output_v`."
                )

        self._resolved_sample_time: float | None = None
        self._step_ratio: int = 1
        # ``@block`` デコレータ生成 class がパラメータを格納する場所 (ADR-0003 §(5))。
        # 直接 ``Block`` 継承で書かれたブロックでは空のまま。Phase 2 JSON save/load
        # で参照予定。
        self._params: dict[str, Any] = {}

    @property
    def id(self) -> str | None:
        """ブロック識別子 (read-write)。

        Simulator に登録済みのブロックの ID を直接書き換えるのは未サポート。
        リネームは ``Simulator.rename(old, new)`` を使うこと。
        """
        return self._id

    @id.setter
    def id(self, value: str | None) -> None:
        if value is not None:
            # ADR-0071 §(3): 入口層で NFC 正規化してから検証・格納する
            if isinstance(value, str):
                value = normalize_block_id(value)
            validate_block_id(value)
        self._id = value

    @property
    def name(self) -> str | None:
        """Phase 0 後方互換 alias for ``id`` (read-only)。

        Phase 1 では deprecation 警告を出さない。Phase 2 リリース時に
        ``DeprecationWarning`` を発する判断を予定 (ADR-0004)。
        """
        return self._id

    def output(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        """SM-A scalar-port API でブロック出力 ``y(t, x, u)`` を計算する。

        各 input/output port が rank-0 scalar (= SM-A 互換、port_shapes 全 ``()``) の
        ブロックはこのメソッドをオーバーライドする。ベクトルポート (= SM-B、任意
        shape ndarray) を扱うブロックは代わりに ``output_v`` を実装する。

        Args:
            t: 現時刻。
            x: 現状態 (shape ``(n_states,)``)。状態を持たないブロックは空配列。
            u: 現入力 (shape ``(n_inputs,)``)。``direct_feedthrough=False`` のブロック
                では出力計算 1 パス目で ``u`` がゼロ埋めされる場合がある。

        Returns:
            出力ベクトル (shape ``(n_outputs,)``)。
        """
        raise NotImplementedError(f"{self.__class__.__name__}.output not implemented")

    def output_v(
        self,
        t: float,
        x: npt.NDArray[Any],
        u: tuple[npt.NDArray[Any], ...],
    ) -> tuple[npt.NDArray[Any], ...]:
        """SM-B vector-port API でブロック出力を計算する (ADR-0017 §(3))。

        各 input port が任意 shape ndarray を運ぶ vector-aware ブロック (Mux, Demux,
        将来の MIMO ブロック等) はこのメソッドをオーバーライドする。

        Default 実装は SM-A 互換 wrapper (ADR-0017 §(8) U1):
        ``u: tuple[ndarray, ...]`` を 1D ndarray に flatten し、既存 ``output`` を
        呼び、戻り値を tuple of rank-0 ndarrays に分解する。これにより全 SM-A
        ブロックは ``output`` のみ実装で動作する (改修ゼロ)。

        Args:
            t: 現時刻。
            x: 現状態 (shape ``(n_states,)``)。
            u: 各入力ポートの ndarray のタプル。``len(u) == n_inputs``、各 ``u[i]``
                の shape は ``port_shapes_in[i]``。

        Returns:
            各出力ポートの ndarray のタプル。``len(...) == n_outputs``、各要素の
            shape は ``port_shapes_out[i]``。
        """
        # SM-A wrapper: 全 port shape が () の場合のみ動作する。
        # SM-D Stage 1 (SPEC-0028): wrapper は dtype 保存パススルー — 入力は
        # np.stack (= np.result_type で 1 本化。全 float64 なら従来と bit 同一)、
        # 出力の float 強制も外す。予測 dtype への強制 cast は
        # Simulator._step_vector 側の 1 箇所に集約する (SSOT)。
        if len(u) > 0:
            u_flat = np.stack([np.asarray(ui).reshape(()) for ui in u])
        else:
            u_flat = np.zeros(0)
        x_arr = np.asarray(x, dtype=float)  # Q7: 状態は float64 固定
        y_flat = np.atleast_1d(np.asarray(self.output(t, x_arr, u_flat)))
        # ADR-0017 §(8) U1: ユーザーカスタム SM-A ブロックの実装ミス (n_outputs と
        # output() 戻り値 shape の不一致) を sandbox 化する。SM-A hot path
        # (`Simulator._step` 直呼び) ではこの check は走らないため、SM-B モードでの
        # 安全網として機能する (code-reviewer MUST 修正)。
        if y_flat.shape != (self.n_outputs,):
            raise BlockSpecError(
                f"{type(self).__name__}.output must return shape ({self.n_outputs},), "
                f"got {y_flat.shape}"
            )
        # 各出力 port を rank-0 ndarray として分解 (dtype はパススルー)
        return tuple(np.asarray(y_flat[i]) for i in range(self.n_outputs))

    def derivative(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        """連続状態の時間微分 ``x_dot(t, x, u)`` を返す。

        Default 実装は ``np.zeros(n_states)`` を返す。連続状態を持つブロックは
        オーバーライドする。``sample_time > 0`` の離散ブロックでは呼ばれない。
        """
        return np.zeros(self.n_states)

    def update(self, t: float, x: npt.NDArray[Any], u: npt.NDArray[Any]) -> npt.NDArray[Any]:
        """離散ブロックの状態更新 ``x_next = update(t, x, u)`` を返す。

        Args:
            t: 現サンプル時刻。
            x: 現状態 (shape ``(n_states,)``)。
            u: 現入力 (shape ``(n_inputs,)``)。

        Returns:
            次サンプル時刻の状態 (shape ``(n_states,)``)。

        Note:
            Default 実装は ``x`` をそのまま返す (組合せ論理のみの離散ブロック用)。
            実装側は **新しい ndarray を返す** こと。in-place 更新すると Simulator の
            double buffering が破綻する。
        """
        return x

    def advance(self, t: float, x: npt.NDArray[Any]) -> npt.NDArray[Any]:
        """サンプル時刻 ``t_k`` の冒頭で呼ばれる「シフト相」(ADR-0078)。

        ADR-0015 の 2-state 配置 (``x[:n]`` = 表示中の出力用状態、``x[n:]`` = 真の
        状態) を持つブロックは、ここで ``x[:n] ← x[n:]`` を行い「t_k で出力すべき
        値」を **update の入力評価より前に** 可視化する。Simulator はこの後で
        全ブロックの出力を計算して ``update(t_k, x, u_k)`` に渡すため、同時刻に
        発火する上流離散ブロックの出力 ``y_k`` が下流の更新に正しく届く。

        Args:
            t: 現サンプル時刻。
            x: 現状態 (shape ``(n_states,)``)。

        Returns:
            シフト後の状態 (shape ``(n_states,)``)。Default 実装は ``x`` を
            そのまま返す (1-state ブロック / 状態なしブロック用)。
        """
        return x

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self._id!r}>"

    def _build(self) -> None:
        """構造解析 (実行順、direct_feedthrough、状態 layout 等) を確定する hook。

        ``Simulator._execution_order`` がトポロジカル解析を始める前に呼ばれる。
        Default 実装は no-op。``Subsystem`` のように内部構造を持つブロックが
        override し、``self.direct_feedthrough`` / ``self.n_states`` / ``self.x0``
        等の値を **解析前に**確定する責務を持つ。
        """
        return

    def _set_port_shapes_in_for_build(
        self, shapes: tuple[tuple[int, ...], ...] | list[tuple[int, ...]]
    ) -> None:
        """ADR-0055 §論点 4: Goto/From 専用 build 時 shape 確定 hook。

        通常のブロックは ``__init__`` で ``port_shapes_in`` を静的宣言する
        (ADR-0017 §(1) 静的宣言原則)。``Goto`` / ``From`` のみ例外として、
        ``Simulator._resolve_goto_from_virtual_edges`` から本メソッドを呼んで
        build 時に shape を上書きする。**他のサブクラスから呼ばない**
        (= ADR-0017 原則の純粋性を 1 段だけ下げる Goto/From 専用 API)。

        正規化 + 長さ check は ``_normalize_port_shapes`` に委譲するため、
        ``n_inputs`` と長さが合わない場合は ``BlockSpecError``。
        """
        self.port_shapes_in = _normalize_port_shapes(shapes, self.n_inputs, "in")

    def _set_port_shapes_out_for_build(
        self, shapes: tuple[tuple[int, ...], ...] | list[tuple[int, ...]]
    ) -> None:
        """ADR-0055 §論点 4: Goto/From 専用 build 時 shape 確定 hook (out 側)。

        ``_set_port_shapes_in_for_build`` と対の API。本メソッドも Goto/From
        専用で、他のサブクラスからは呼ばない。
        """
        self.port_shapes_out = _normalize_port_shapes(shapes, self.n_outputs, "out")

    def to_dict(self) -> dict[str, Any]:
        """ブロックを JSON-serializable な辞書に変換する (ADR-0008 §(5))。

        各サブクラスは ``__init__`` で ``self._params`` にユーザー API キーワード
        引数を記録する責務を持つ。``@block`` デコレータ生成 class は
        ``ADR-0003 §(5)`` で既に ``_params`` を保持する。

        Returns:
            ``{"id": ..., "type": "module.ClassName", "params": {...}}``。

        Raises:
            ModelSerializationError: class が ``__main__`` モジュールで定義されている
                場合、または ``_params`` に JSON-serializable でない値が含まれる場合。
        """
        from .persistence import block_type_path, to_json_dict

        # ADR-0021 §(6): マスク Subsystem 内部の block は ``_unresolved_params``
        # (= placeholder ``"$Kp"`` を含む元の params) を持つ場合がある。round-trip 保証
        # のため to_dict ではこちらを優先する (= 解決済み具象値ではなく placeholder を JSON
        # に残す)。マスク外の通常 block では ``_unresolved_params`` 属性は付かない。
        # ``is not None`` で判定する (= ``{}`` でも空を意図して保存する将来の拡張に
        # 備える、code-reviewer MUST 修正)。
        unresolved = getattr(self, "_unresolved_params", None)
        params_for_json = unresolved if unresolved is not None else self._params
        out: dict[str, Any] = {
            "id": self._id,
            "type": block_type_path(self.__class__),
            "params": to_json_dict(params_for_json),
        }
        # ADR-0017 §(5) / SM-B: port_shapes は default 全 () (= SM-A scalar) のとき
        # 省略、SM-B-aware ブロック (どこか非 () の port shape) のときのみ JSON に
        # 出力する。ただしブロックの port_shapes が ``__init__`` の他パラメータ
        # (例: Mux の ``n``、Inport の ``port_shape``) から一意に決まる場合、JSON 側
        # で port_shapes を持つと重複・矛盾の元になるため、class 属性
        # ``_serialize_port_shapes = False`` で skip できる (Mux/Demux/Inport/Outport)。
        if getattr(type(self), "_serialize_port_shapes", True):
            scalar_shape: tuple[int, ...] = ()
            if any(s != scalar_shape for s in self.port_shapes_in):
                out["port_shapes_in"] = [list(s) for s in self.port_shapes_in]
            if any(s != scalar_shape for s in self.port_shapes_out):
                out["port_shapes_out"] = [list(s) for s in self.port_shapes_out]
        return out
