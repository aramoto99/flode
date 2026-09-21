"""信号面解決器 (signal plane resolver) — 形状 (shape) と dtype の build 時解決。

ADR-0079 (SM-T: tensor signal plane) D-1〜D-4 / D-11。SPEC-0027 / SPEC-0028 の
dtype 解決器 (旧 ``flode.core.dtypes``) に **shape の伝播を同じ不動点反復に
統合**したもの。モデルの各ポートが運ぶ ``(shape, dtype)`` を build 時に 1 回だけ
確定し、``Simulator`` はその結果 (plan) だけを見て実行経路を選ぶ。

鉄則:

- 型規則 / 形状規則の SSOT は本モジュール 1 箇所 (ADR-0077 §データ整合性 1、
  ADR-0079 D-6)。``flode.blocks`` / ``flode.core.block`` には規則を書かない
- 依存は stdlib + numpy のみ。ブロッククラスは **クラス名 (MRO 走査)** で分類し、
  ``flode.blocks`` / ``flode.subsystems`` を import しない
- 解決結果はブロックへ書き戻さない (D-2)。``port_shapes_in/out`` は「宣言」の
  ままで、推論された shape は ``Simulator`` の plan にだけ存在する
- 合流規則 (D-4) は **完全一致 + rank-0 スカラ拡張のみ**。numpy の一般
  broadcasting (``(3,)`` + ``(1,3)`` 等) は ``shape.broadcast_rejected`` で拒否する

二経路 (SPEC-0027 実装計画「矛盾 1」の解決):

- **full mode**: ``PythonFunction`` を含まないモデル。``sim._execution_order()``
  を使い、Goto/From 解決・代数ループ検出を享受する
- **static mode**: ``PythonFunction`` を含むモデル。``_build()`` が
  ユーザーコードを exec するため (pythonfunc.py) **一切 build せず**、
  登録順で不動点反復する。Goto/From は未解決 → ``unknown``、
  診断 ``dtype.static_fallback`` で縮退を明示する。これにより
  「エンジンはユーザーコードを実行しない」を構造的に保証する

``flode.core.dtypes`` は本モジュールの互換 re-export (ADR-0038)。
"""

from __future__ import annotations

import logging
import math
from collections import ChainMap, deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal, NamedTuple

import numpy as np
import numpy.typing as npt

from ..exceptions import AlgebraicLoopError, BlockSpecError, SignalShapeError

if TYPE_CHECKING:
    from .block import Block
    from .simulator import Simulator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 語彙 (D-1) と昇格 (D-2)
# ---------------------------------------------------------------------------

#: Stage 1 で導入予定の dtype 語彙 (昇格順)。``np.result_type`` について閉じている
#: (5×5 総当たりテストで固定、SPEC-0027 §1)。
DTYPE_VOCABULARY: Final[tuple[str, ...]] = ("bool", "uint8", "int32", "int64", "float64")

#: 内部センチネル =「静的規則では決められない」を表す格子の bottom。
#: D-1 の語彙を拡張するものではない。Stage 1 (SPEC-0028 Q5) では full mode の
#: 収束後に float64 へ materialize され、実行時には残らない (全域性 AC-3)。
UNKNOWN: Final[str] = "unknown"

#: Subsystem / PythonFunction island の内部 dtype (SPEC-0028 Q6)。
#: ``reject_nested_dtype_declarations`` の「island と一致する宣言は無害」判定は
#: この値に依存する — island の dtype を変える時は必ずここを更新すること
#: (リテラル直書きだと無言で fail-open になる、security NITS)。
ISLAND_DTYPE: Final[str] = "float64"

#: Stage 1 (SPEC-0028 Q1): ``dtype`` param の語彙。``"auto"`` = 宣言しない
#: (従来どおり float64 経路)。``"auto"`` 以外は D-1 の語彙 5 種と 1:1。
DTYPE_PARAM_VALUES: Final[tuple[str, ...]] = (
    "auto",
    "float64",
    "bool",
    "int32",
    "int64",
    "uint8",
)

#: Q7: 状態を float64 で保持したまま出力のみ cast する状態持ちブロック
#: (`dtype.state_via_float64` 診断の対象)。
_STATE_VIA_FLOAT64: Final[frozenset[str]] = frozenset(
    {"UnitDelay", "RateTransition", "ZeroOrderHoldDirect"}
)

#: SPEC-0028 §3.8: static mode の型解決中であることを示す ContextVar。
#: ``exec_block_source`` (pythonfunc.py) がこのフラグを見て exec を拒否する
#: (多層防御。呼び出し側の規律 = 二経路設計への構造的バックストップ)。
#: shape 解決も同じ区間で行う (ADR-0079 §(1) exec ガード)。
_RESOLVING_WITHOUT_USER_CODE: ContextVar[bool] = ContextVar(
    "flode_dtype_resolving_without_user_code", default=False
)


def in_static_dtype_resolution() -> bool:
    """static mode の型解決区間内かどうか (exec / eval ガードが参照する)。

    Note:
        ContextVar のため **新規スレッドには継承されない** (asyncio task /
        ``run_in_threadpool`` は Context コピーで継承される)。将来、解決処理を
        素の ``ThreadPoolExecutor`` 等へ逃がすとガードは静かに fail-open に
        なる — その場合は context を明示的に propagate すること
        (security SHOULD-2 2026-09-08)。
    """
    return _RESOLVING_WITHOUT_USER_CODE.get()


Direction = Literal["in", "out"]

#: 解決結果の突合キー (ADR-0077 §データ整合性 2: index 突合はブロック追加順で壊れる)。
PortKey = tuple[str, str, int]

#: ポートの shape (numpy と同じ tuple 表記。``()`` = rank-0 スカラ)。
Shape = tuple[int, ...]

#: rank-0 スカラ (SM-A 互換) の shape。
SCALAR_SHAPE: Final[Shape] = ()

#: ``Scope`` の列数 (全入力ポートの総要素数) がこれを超えると ``shape.large_vector``
#: (info) を出す (ADR-0079 §(8))。実行は止めない。
SCOPE_LARGE_VECTOR_COLUMNS: Final[int] = 64

#: REST payload の schema 識別子 (SPEC-0027 §5.2 → ADR-0079 §(9) で更新)。
#: frontend は旧 ``"dtypes.v1"`` と本値の両方を受容する。
SCHEMA_VERSION: Final[str] = "signals.v1"

#: 不動点反復の上限マージン (上限 = ``2 * len(blocks) + _ITERATION_MARGIN``)。
_ITERATION_MARGIN: Final[int] = 8

_VOCABULARY_SET: Final[frozenset[str]] = frozenset(DTYPE_VOCABULARY)


def promote(a: str, b: str) -> str:
    """2 つの dtype 名を numpy 昇格規則で結合する (D-2)。

    ``unknown`` は吸収されない bottom: ``promote(unknown, X) == X``。
    語彙外へ出た場合はそのままの名前を返す (語彙内への丸めと診断は
    呼び出し側 ``_promote_many`` が行う)。

    Note:
        Python スカラー (NEP 50 weak scalar) を混ぜない — 必ず dtype 名同士で
        ``np.result_type`` を呼ぶ (SPEC-0027 §2)。
    """
    if a == UNKNOWN:
        return b
    if b == UNKNOWN:
        return a
    return np.result_type(np.dtype(a), np.dtype(b)).name


def merge_shapes(a: Shape, b: Shape) -> Shape | None:
    """2 つの shape を合流規則 (ADR-0079 D-4) で結合する。

    許可されるのは **完全一致** と **rank-0 スカラ拡張** (``()`` と 1 種類の
    非 ``()``) のみ。結果は非 ``()`` 側。それ以外 (``(3,)`` と ``(1, 3)`` /
    ``(3,)`` と ``(4,)`` / ``(2, 3)`` と ``(3,)`` 等、numpy なら broadcasting で
    通る組合せを含む) は ``None`` (= 拒否) を返し、呼び出し側が
    ``shape.broadcast_rejected`` を出す。

    Args:
        a: shape (既知)。
        b: shape (既知)。

    Returns:
        合流後の shape。拒否なら ``None``。
    """
    if a == b:
        return a
    if a == SCALAR_SHAPE:
        return b
    if b == SCALAR_SHAPE:
        return a
    return None


def _matmul_shape(a: Shape, b: Shape) -> Shape | None:
    """``a @ b`` の結果 shape (rank 1 / 2 のみ、numpy ``matmul`` と同じ規則)。

    行列 ``Gain`` (``multiplication="matrix-Ku"`` / ``"matrix-uK"``) の出力 shape
    推論に使う。rank-0 を含む / rank 3 以上 / 内側次元の不一致は ``None``。
    """
    if len(a) == 0 or len(b) == 0 or len(a) > 2 or len(b) > 2:
        return None
    inner_a = a[-1]
    inner_b = b[0]
    if inner_a != inner_b:
        return None
    lead = a[:-1]  # (m,) または ()
    trail = b[1:]  # (p,) または ()
    return tuple(lead) + tuple(trail)


def _shape_payload(shape: Shape | None) -> list[int] | None:
    """REST payload 用の shape 表現 (未確定は ``None``)。"""
    return list(shape) if shape is not None else None


def _shape_str(shape: Shape | None) -> str:
    """診断メッセージ用の shape 表記 (``()`` は ``"() (scalar)"``)。"""
    if shape is None:
        return "unknown"
    if shape == SCALAR_SHAPE:
        return "() (scalar)"
    return str(shape)


def _float_to_int_scalar(v: float, info: Any) -> int:
    """float スカラーを決定的に整数へ写す (SPEC-0028 §2.2 / Q3)。

    nan → 0 / +inf → max / -inf → min の決定的飽和、有限値は
    「ゼロ方向切り捨て → Python int → モジュラ wrap」。numpy の生 ``astype`` は
    nan / inf / 表現域外で C 未定義動作のため使わない (決定性要件)。
    """
    if math.isnan(v):
        return 0
    if v == math.inf:
        return int(info.max)
    if v == -math.inf:
        return int(info.min)
    truncated = int(v)  # Python の int() = ゼロ方向切り捨て
    lo = int(info.min)
    span = int(info.max) - lo + 1
    return (truncated - lo) % span + lo


def cast_value(value: Any, target: str | np.dtype[Any]) -> npt.NDArray[Any]:
    """値を目標 dtype へ決定的に変換する (変換規則の SSOT、SPEC-0028 §2.2)。

    ``Cast`` / ``Constant`` の実変換と ``_step_vector`` の強制 cast の両方が
    これを呼ぶ (規則の二重実装を作らない — ``apply_value_semantics`` と同じ流儀)。

    規則 (Q3):

    - 任意 → float64: ``astype`` (拡大。int64 > 2^53 は numpy 準拠で精度を失う)
    - float → 整数: ゼロ方向切り捨て + モジュラ wrap。nan → 0 /
      +inf → ``iinfo.max`` / -inf → ``iinfo.min`` の決定的飽和
    - 整数 → 整数: モジュラ wrap (numpy の同種 ``astype`` と一致)
    - 任意 → bool: ``u != 0`` (nan も True。SPEC-0026 §確定事項 3 と同一規則)

    Args:
        value: スカラーまたは ndarray (**数値 dtype 前提**。object 配列は
            サポート外 — 呼び出し面は信号値のみ。security NIT-4 2026-09-08)。
        target: 目標 dtype (語彙 5 種のいずれか)。

    Returns:
        目標 dtype の ndarray (入力と同 shape)。
    """
    dt = np.dtype(target)
    arr = np.asarray(value)
    if arr.dtype == dt:
        return arr
    if dt.kind == "b":
        # nan != 0 は True → nan → True (ADR-0053 / SPEC-0026 と整合)
        return np.asarray(arr != 0)
    if dt.kind in "iu":
        if arr.dtype.kind == "f":
            info = np.iinfo(dt)
            lo = int(info.min)
            span = int(info.max) - lo + 1
            if span <= 2**53:
                # ベクトル化経路 (uint8 / int32 等: span が float64 で正確)。
                # np.mod (= C fmod + 符号調整) は「表現されている値」の正確な
                # 剰余を返すため、per-element の Python int 経路と厳密同値
                # (security SHOULD-3 2026-09-08: hot path の 2〜3 桁の定数倍を解消)
                flat = np.ravel(arr).astype(np.float64, copy=False)
                out_flat = np.empty(flat.shape, dtype=dt)
                nan_m = np.isnan(flat)
                pinf_m = np.isposinf(flat)
                ninf_m = np.isneginf(flat)
                finite_m = ~(nan_m | pinf_m | ninf_m)
                t = np.trunc(flat[finite_m])
                r = np.mod(t, float(span))  # exact、[0, span)
                out_flat[finite_m] = np.where(r > info.max, r - span, r).astype(dt)
                out_flat[nan_m] = 0
                out_flat[pinf_m] = info.max
                out_flat[ninf_m] = info.min
                return out_flat.reshape(arr.shape)
            # int64: span = 2^64 が float64 で表現できないため per-element
            # (Python 任意精度 int) で決定的に wrap する
            flat_list = [_float_to_int_scalar(float(v), info) for v in np.ravel(arr)]
            return np.asarray(flat_list, dtype=dt).reshape(arr.shape)
        # 整数/bool → 整数: numpy の astype はビット切り出し = モジュラ wrap で決定的
        return arr.astype(dt)
    # float64 (拡大変換)
    return arr.astype(dt)


# ---------------------------------------------------------------------------
# 診断 (SPEC-0027 §3.6 + 実装計画の dtype.static_fallback + ADR-0079 §(8))
# ---------------------------------------------------------------------------

#: code → severity の対応表。``error`` は実行経路 (``resolve_for_execution``) で
#: 実行拒否に昇格する。``shape.*`` は ADR-0079 §(8) の表。
_SEVERITY_BY_CODE: Final[Mapping[str, str]] = {
    "dtype.implicit_widening": "info",
    "dtype.non_float_signal": "info",
    "dtype.unresolved": "warning",
    "dtype.rule_missing": "info",
    "dtype.narrowing_required": "error",
    "dtype.out_of_vocabulary": "warning",
    "dtype.iteration_limit": "warning",
    "dtype.build_failed": "error",
    "dtype.internal_error": "error",
    "dtype.static_fallback": "info",
    # -- Stage 1 (SPEC-0028) --
    "dtype.opaque_float64_island": "info",
    "dtype.defaulted_to_float64": "info",
    "dtype.state_via_float64": "info",
    # -- SM-T Stage 1 (ADR-0079 §(8)) --
    "shape.mismatch": "error",
    "shape.broadcast_rejected": "error",
    "shape.opaque_scalar_island": "error",
    "shape.control_port_not_scalar": "error",
    # ADR-0079 の表では error だが、full mode では materialize により決して
    # 残らず、static mode (build なし) の「まだ分からない」は dtype.unresolved
    # と同じく warning が実態に合う (ADR-0079 Amendments に記録)。
    "shape.unresolved": "warning",
    "shape.defaulted_to_scalar": "info",
    "shape.large_vector": "info",
}


@dataclass(frozen=True)
class SignalDiagnostic:
    """信号面解決の構造化診断 1 件 (SPEC-0027 §3.6 / ADR-0079 §(8))。

    ``message`` は en 固定のフォールバック (i18n は ``code`` をキーに
    frontend 側で行う、ADR-0028)。``expected_shape`` / ``actual_shape`` は
    ``shape.*`` 診断だけが埋める (dtype 診断では ``None``)。
    """

    severity: str
    code: str
    message: str
    block_id: str | None = None
    direction: str | None = None
    port_index: int | None = None
    from_dtype: str | None = None
    to_dtype: str | None = None
    expected_shape: Shape | None = None
    actual_shape: Shape | None = None

    def to_payload(self) -> dict[str, Any]:
        """REST 用の JSON 互換 dict を返す (shape は list、無ければ ``None``)。"""
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "block_id": self.block_id,
            "direction": self.direction,
            "port_index": self.port_index,
            "from_dtype": self.from_dtype,
            "to_dtype": self.to_dtype,
            "expected_shape": (
                list(self.expected_shape) if self.expected_shape is not None else None
            ),
            "actual_shape": list(self.actual_shape) if self.actual_shape is not None else None,
        }


#: 互換 alias (SPEC-0027 / SPEC-0028 時代の名前、ADR-0038)。
DTypeDiagnostic = SignalDiagnostic


@dataclass(frozen=True)
class SignalSummary:
    """解決結果の集計 (ADR-0077 §再考トリガー 1 / ADR-0079 §(1) の判定材料)。

    ``unresolved`` は dtype が ``unknown`` のまま残ったポート数 (static mode のみ
    非 0)。``max_rank`` / ``vector_ports`` は shape 集計 (未確定は数えない)。
    """

    total_ports: int
    by_dtype: Mapping[str, int]
    unresolved: int
    non_float_ports: int
    max_rank: int = 0
    vector_ports: int = 0

    def to_payload(self) -> dict[str, Any]:
        """REST 用の JSON 互換 dict を返す。"""
        return {
            "total_ports": self.total_ports,
            "by_dtype": dict(self.by_dtype),
            "unresolved": self.unresolved,
            "non_float_ports": self.non_float_ports,
            "max_rank": self.max_rank,
            "vector_ports": self.vector_ports,
        }


DTypeSummary = SignalSummary


class PortSignal(NamedTuple):
    """1 ポートの解決済み信号面 ``(shape, dtype)``。"""

    shape: Shape | None
    dtype: str


@dataclass(frozen=True)
class SignalResolution:
    """信号面解決の結果 (不変)。``ports`` / ``shapes`` は ``(block_id, direction,
    port_index)`` キー。

    ``ports`` の値は dtype 名 (SPEC-0027 以来の互換 API)、``shapes`` の値は
    解決済み shape (static mode で未確定なら ``None``)。両方を 1 つにまとめた
    ``signal(key)`` も提供する。
    """

    ports: Mapping[PortKey, str]
    diagnostics: tuple[SignalDiagnostic, ...]
    summary: SignalSummary
    shapes: Mapping[PortKey, Shape | None] = field(default_factory=dict)
    #: ADR-0079 §(6) D-8: Subsystem ごとの内部スコープの解決結果 (key = Subsystem の
    #: block id、ネストは ``inner`` の ``inner``)。root のキー空間は不変。
    inner: Mapping[str, SignalResolution] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.shapes and self.ports:
            # 旧 API (ports のみ) で構築された場合は全ポート未確定として扱う
            object.__setattr__(self, "shapes", dict.fromkeys(self.ports, None))

    def out_dtype(self, block_id: str, port_index: int) -> str:
        """出力ポートの推論 dtype を返す (未知キーは ``KeyError``)。"""
        return self.ports[(block_id, "out", port_index)]

    def in_dtype(self, block_id: str, port_index: int) -> str:
        """入力ポートの推論 dtype (D-4 自動昇格後) を返す。"""
        return self.ports[(block_id, "in", port_index)]

    def out_shape(self, block_id: str, port_index: int) -> Shape | None:
        """出力ポートの推論 shape を返す (未知キーは ``KeyError``)。"""
        return self.shapes[(block_id, "out", port_index)]

    def in_shape(self, block_id: str, port_index: int) -> Shape | None:
        """入力ポートの推論 shape (合流 / 宣言検査後) を返す。"""
        return self.shapes[(block_id, "in", port_index)]

    def signal(self, key: PortKey) -> PortSignal:
        """``(shape, dtype)`` をまとめて返す。"""
        return PortSignal(self.shapes[key], self.ports[key])

    def to_payload(self) -> dict[str, Any]:
        """REST レスポンス (``signals.v1``) を返す。ports は決定的 sort。

        各 port entry は SPEC-0027 の ``dtype`` に加えて ``shape`` (list、
        未確定なら ``None``) を additive に持つ (ADR-0079 §(9))。
        """
        return {
            "schema_version": SCHEMA_VERSION,
            "ports": [
                {
                    "block_id": key[0],
                    "direction": key[1],
                    "port_index": key[2],
                    "dtype": self.ports[key],
                    "shape": _shape_payload(self.shapes.get(key)),
                }
                for key in sorted(self.ports)
            ],
            "diagnostics": [d.to_payload() for d in self.diagnostics],
            "summary": self.summary.to_payload(),
            # ADR-0079 §(6): Subsystem 内部スコープ (Inspector が editingPath で辿る)
            "inner": {sub_id: res.to_payload() for sub_id, res in sorted(self.inner.items())},
        }


DTypeResolution = SignalResolution


# ---------------------------------------------------------------------------
# ブロック分類 (SPEC-0027 §3.5 + 実装計画「矛盾 3」の追加 4 クラス)
# ---------------------------------------------------------------------------

Category = Literal[
    "bool_out",
    "param_typed",
    "int_out",
    "float_out",
    "promote",
    "promote_except_control",
    "fanout",
    "sink",
    "opaque",
]

#: クラス名 → dtype 分類。lookup は MRO 走査 (サブクラスは親の規則を継承)。
#: builtin クラス名の重複ゼロは TestCoverageGuard が CI で保証する。
_CLASSIFICATION: Final[Mapping[str, Category]] = {
    # -- 入力によらず bool --
    "RelationalOperator": "bool_out",
    "LogicalOperator": "bool_out",
    "CompareToConstant": "bool_out",
    "CompareToZero": "bool_out",
    # -- _params から決まる --
    "Constant": "param_typed",
    "Cast": "param_typed",
    # -- 入力によらず int64 --
    "Rounding": "int_out",
    # -- 入力によらず float64 --
    "Integrator": "float_out",
    "StateSpace": "float_out",
    "TransferFunction": "float_out",
    "MimoTransferFunction": "float_out",
    "Derivative": "float_out",
    "Divide": "float_out",
    "MathFunction": "float_out",
    "TrigFunction": "float_out",
    "DeadZone": "float_out",
    "Saturation": "float_out",
    "Gain": "float_out",
    "Reduce": "float_out",
    "DotProduct": "float_out",
    "MatrixMultiply": "float_out",
    "Fcn": "float_out",
    "LookupTable1D": "float_out",
    "LookupTable2D": "float_out",
    "LookupTableND": "float_out",
    "Prelookup": "float_out",
    "InterpolationUsingPrelookup": "float_out",
    "RateLimiter": "float_out",
    "Relay": "float_out",
    "TransportDelay": "float_out",
    "DiscreteIntegrator": "float_out",
    "DiscreteStateSpace": "float_out",
    "DiscreteTransferFunction": "float_out",
    "Step": "float_out",
    "Sine": "float_out",
    "Ramp": "float_out",
    "Clock": "float_out",
    "PulseGenerator": "float_out",
    "RandomSource": "float_out",
    # -- 全入力の np.result_type (既定規則) --
    "Sum": "promote",
    "Add": "promote",
    "Product": "promote",
    "Abs": "promote",
    "Sign": "promote",
    "MinMax": "promote",
    "Mux": "promote",
    "Merge": "promote",
    "Goto": "promote",
    "From": "promote",
    "UnitDelay": "promote",
    "RateTransition": "promote",
    "ZeroOrderHoldDirect": "promote",
    "Inport": "promote",
    "Outport": "promote",
    # -- 制御入力を除いた promote --
    "Switch": "promote_except_control",
    "MultiportSwitch": "promote_except_control",
    # -- 入力 dtype を全出力に配る --
    "Demux": "fanout",
    # -- 出力なし --
    "Scope": "sink",
    "Display": "sink",
    "XYGraph": "sink",
    "Terminator": "sink",
    "Trigger": "sink",
    "Enable": "sink",
    # -- Stage 0 では規則を書き切れない (Q4: float64 と偽らず unknown) --
    "Subsystem": "opaque",
    "PythonFunction": "opaque",
}

#: promote_except_control / select の制御入力ポート index (出力に寄与しない)。
_CONTROL_PORT_INDEX: Final[Mapping[str, int]] = {"Switch": 1, "MultiportSwitch": 0}

#: shape 規則の分類 (ADR-0079 D-6: 規則はこの表 1 箇所)。
#:
#: - ``elementwise``: 全入力を D-4 合流規則で結合した shape を全出力に (要素ごと演算)
#: - ``gain``: ``Gain`` — ``multiplication`` と ``k`` の shape から決まる
#: - ``select``: 制御ポート (``_CONTROL_PORT_INDEX``、無ければ制御なし) は ``()``
#:   固定、データポートは **同一 shape** を要求し、それを出力する (Switch / Merge)
#: - ``fanout``: 入力 0 (From は仮想入力) の shape を全出力へ透過 (Goto / From)
#: - ``declared``: ``port_shapes_in/out`` の宣言がそのまま規則 (Mux / Demux /
#:   Inport / Outport / スカラ専用の状態・ソース・lookup 系 / 規則未登録クラス)。
#:   宣言と異なる上流 shape は ``shape.mismatch``
#: - ``opaque``: ユーザーコード境界 (Subsystem / PythonFunction / Fcn / ``@block``)。
#:   Stage 1 は入出力とも ``()`` を要求し、ベクトル流入は ``shape.opaque_scalar_island``
#: - ``state``: ベクトル状態ブロック (``VectorStateMixin``、ADR-0079 §(5) 7a')。
#:   ``x0`` が rank-0 なら状態 shape = 入力の合流 shape (スカラ拡張)、非 rank-0 なら
#:   入力は ``()`` か ``x0`` の shape に一致。出力 shape = 状態 shape
#: - ``subsystem``: 階層再帰 (ADR-0079 §(6) D-8)。外側 in shape を内部 Inport に注入して
#:   内部スコープを再帰解決し、内部 Outport の in shape を外側 out shape にする。
#:   enable / trigger slot は ``()`` 固定
#: - ``reduce``: 入力は合流規則で検査し (Reduce は 1 入力、DotProduct は同 shape 2 入力)、
#:   出力は常に ``()`` (ADR-0079 Stage 3、SPEC-0031 F-5.3)
#: - ``matmul``: 2 入力の行列積 ``u0 @ u1`` (``_matmul_shape``)。両方 ``()`` なら ``()``、
#:   片方だけ ``()`` / 内側次元不一致は ``shape.mismatch``
#: - ``sink``: 任意 shape を受理 (Scope / Display / Terminator)
#: - ``sink_scalar``: ``()`` のみ受理 (XYGraph / Trigger / Enable)
ShapeCategory = Literal[
    "elementwise",
    "gain",
    "select",
    "fanout",
    "declared",
    "inferred",
    "state",
    "subsystem",
    "reduce",
    "matmul",
    "opaque",
    "sink",
    "sink_scalar",
]

#: クラス名 → shape 分類。lookup は MRO 走査。``ElementwiseMixin`` を載せることで
#: ``flode.blocks._elementwise`` を継承するクラス (拡張ブロック含む) が自動的に
#: 要素ごと規則になる。builtin 全クラスの網羅は TestShapeCoverageGuard が保証する。
_SHAPE_RULES: Final[Mapping[str, ShapeCategory]] = {
    # -- 要素ごと演算 (blocks/_elementwise.py の mixin と Stage 1 の 17 クラス) --
    "ElementwiseMixin": "elementwise",
    "Sum": "elementwise",
    "Add": "elementwise",
    "Product": "elementwise",
    "Divide": "elementwise",
    "Saturation": "elementwise",
    "DeadZone": "elementwise",
    "Abs": "elementwise",
    "Sign": "elementwise",
    "MinMax": "elementwise",
    "MathFunction": "elementwise",
    "TrigFunction": "elementwise",
    "Rounding": "elementwise",
    "Cast": "elementwise",
    "RelationalOperator": "elementwise",
    "LogicalOperator": "elementwise",
    "CompareToConstant": "elementwise",
    "CompareToZero": "elementwise",
    # -- 行列 / 要素ごとゲイン --
    "Gain": "gain",
    # -- 要素縮約 / 線形代数 (Stage 3) --
    "Reduce": "reduce",
    "DotProduct": "reduce",
    "MatrixMultiply": "matmul",
    # -- 選択 (制御ポート () 固定、データポート同一 shape) --
    "Switch": "select",
    "MultiportSwitch": "select",
    "Merge": "select",
    # -- 透過 --
    "Goto": "fanout",
    "From": "fanout",
    # -- 宣言どおり (shape を変えるブロックと、スカラ専用の状態 / ソース系) --
    "Mux": "declared",
    "Demux": "declared",
    # Inport の出力は _resolve_graph の seed (外側 in shape / 明示宣言)、Outport は
    # 任意 shape を受け、明示宣言との一致は _SubsystemResolver が検査する (§(6))
    "Inport": "declared",
    "Outport": "sink",
    "Constant": "declared",
    "Step": "declared",
    "Sine": "declared",
    "Ramp": "declared",
    "Clock": "declared",
    "PulseGenerator": "declared",
    "RandomSource": "declared",
    "StateSpace": "declared",
    "TransferFunction": "declared",
    "MimoTransferFunction": "declared",
    # lookup 系は Stage 3 から要素ごと (blocks/lookup.py の _eval スカラ核を vectorize)
    "LookupTable1D": "elementwise",
    "LookupTable2D": "elementwise",
    "LookupTableND": "elementwise",
    "Prelookup": "elementwise",
    "InterpolationUsingPrelookup": "elementwise",
    "Relay": "declared",
    "TransportDelay": "declared",
    "DiscreteStateSpace": "declared",
    "DiscreteTransferFunction": "declared",
    # -- ベクトル状態 (blocks/_vector_state.py の mixin と Stage 2 の 7 クラス) --
    "VectorStateMixin": "state",
    "Integrator": "state",
    "Derivative": "state",
    "UnitDelay": "state",
    "DiscreteIntegrator": "state",
    "RateTransition": "state",
    "ZeroOrderHoldDirect": "state",
    "RateLimiter": "state",
    # -- 階層再帰 (Stage 2) --
    "Subsystem": "subsystem",
    # -- ユーザーコード境界 (宣言 API があれば declared、無ければ () の island) --
    "PythonFunction": "opaque",
    "Fcn": "opaque",
    # -- シンク --
    "Scope": "sink",
    "Display": "sink",
    "Terminator": "sink",
    "XYGraph": "sink_scalar",
    "Trigger": "sink_scalar",
    "Enable": "sink_scalar",
}

#: shape の起点 (宣言以外): ブロックの **パラメータ** が非 ``()`` shape を生む条件。
#: ``has_shape_source`` の pre-filter が読む (ADR-0079 §(1) ``_SHAPE_SOURCES``)。
#: 宣言 (``port_shapes_in/out`` の非 ``()``) は表に載せず ``has_shape_source`` が
#: 直接走査する。
_SHAPE_SOURCES: Final[Mapping[str, Callable[[Block], bool]]] = {
    "Gain": lambda b: np.ndim(getattr(b, "k", 0.0)) > 0,
    # ADR-0079 §(5): 非 rank-0 の x0 を持つ状態ブロック
    "VectorStateMixin": lambda b: tuple(getattr(b, "_x0_shape", ())) != (),
    # ADR-0079 Stage 3 (SPEC-0031 #18): 配列 value / shape 付き乱数 (宣言でも拾えるが
    # 起点一覧を SSOT にする、Risk 5)
    "Constant": lambda b: np.ndim(getattr(b, "value", 0.0)) > 0,
    "RandomSource": lambda b: tuple(getattr(b, "shape", ())) != (),
}


def _block_id(block: Block) -> str:
    """突合キー用の block id (Simulator 登録済みなら必ず str)。"""
    bid = block.id
    return bid if bid is not None else "<unassigned>"


def _mro_names(block: Block) -> tuple[str, ...]:
    """block のクラス MRO 上のクラス名一覧。"""
    return tuple(cls.__name__ for cls in type(block).__mro__)


def _classify(block: Block) -> tuple[Category, bool]:
    """ブロックを dtype 分類する。戻り値は ``(category, rule_missing)``。"""
    for name in _mro_names(block):
        category = _CLASSIFICATION.get(name)
        if category is not None:
            return category, False
    return "promote", True


def _classify_shape(block: Block) -> ShapeCategory:
    """ブロックを shape 分類する (ADR-0079 D-6)。

    ユーザーコード境界 (``@block`` 生成クラス = ``_flode_structure`` を持つ、
    ``PythonFunction`` / ``Fcn``) は宣言 API (ADR-0079 §(3) 6c) の有無で決まる:
    ``infer_output_shapes`` hook があれば ``inferred``、非 ``()`` の
    ``port_shapes_in/out`` 宣言があれば ``declared``、無ければ ``opaque``
    (= 入出力とも ``()`` の island)。
    規則未登録クラスは **宣言どおり** (``declared``) — ``port_shapes_in/out`` を
    静的宣言する ADR-0017 の契約そのもので、宣言が全 ``()`` のカスタム SM-A
    ブロックにベクトルが流入すれば ``shape.mismatch`` になる (fail-closed)。
    """
    names = _mro_names(block)
    user_code = hasattr(type(block), "_flode_structure") or "PythonFunction" in names
    if user_code:
        if callable(getattr(block, "infer_output_shapes", None)):
            return "inferred"
        declared = any(s != SCALAR_SHAPE for s in block.port_shapes_in) or any(
            s != SCALAR_SHAPE for s in block.port_shapes_out
        )
        return "declared" if declared else "opaque"
    for name in names:
        category = _SHAPE_RULES.get(name)
        if category is not None:
            return category
    return "declared"


def _required_input_dtype(block: Block, *, island: bool) -> str | None:
    """D-4: ブロックが全入力ポートに要求する dtype (要求なしは None)。

    要求の SSOT は Stage 1 (SPEC-0028 Q11) から **ブロッククラスの
    ``required_input_dtype`` ClassVar** (連続系 5 + 離散 LTI 3 が
    ``"float64"`` を宣言)。``island=True`` (full mode = Stage 1 意味論) では
    opaque 分類 (Subsystem / PythonFunction) も境界で float64 を要求する (Q6)。
    """
    declared = getattr(type(block), "required_input_dtype", None)
    if isinstance(declared, str):
        return declared
    if island and _classify(block)[0] == "opaque":
        return "float64"
    return None


def _control_port_index(block: Block) -> int | None:
    """promote_except_control / select の制御入力 index (該当なしは None)。"""
    for name in _mro_names(block):
        idx = _CONTROL_PORT_INDEX.get(name)
        if idx is not None:
            return idx
    return None


def _contains_python_function(blocks: Iterable[Block]) -> bool:
    """PythonFunction を再帰的に検出する (Subsystem は ``_inner_blocks`` を duck-typing)。

    この関数が **full mode (= 実行時と同じ、exec しうる ``_build()``) への唯一の門番**である
    (security-reviewer 指摘)。前提: ``Subsystem.__init__`` / ``_from_dict`` は
    ``_inner_blocks`` を **eager に構築**する (遅延化されると検出漏れ = fail-open
    になる)。この前提は JSON roundtrip テストで不変条件として固定している。
    実行時の二重ガード (exec 側 ContextVar) は AC-2 (blocks 無変更) の制約により
    Stage 1 送り (SPEC-0027 §引き継ぎ)。
    """
    for b in blocks:
        if "PythonFunction" in _mro_names(b):
            return True
        inner = getattr(b, "_inner_blocks", None)
        # `is not None` (空 list でも再帰) — iter_python_functions の `if inner:`
        # より安全側に倒す意図的な差分。
        if inner is not None and _contains_python_function(inner):
            return True
    return False


def has_declared_dtype(sim: Simulator) -> bool:
    """モデルが SM-D (実 dtype 実行) を使うか — D-6 振り分け判定の SSOT (SPEC-0028 §3.1)。

    root スコープの ``_params["dtype"]`` を O(V) で走査するだけの pre-filter。
    ``False`` かつ ``has_shape_source`` も ``False`` なら ``run()`` は解決器を
    呼ばず従来経路へ落ちる (AC-1 の構造的保証)。
    ネスト Subsystem 内部は見ない (Q6: island のため内部宣言は Stage 1 では効かない)。
    """
    for b in sim.blocks:
        if str(b._params.get("dtype", "auto")) != "auto":
            return True
    return False


def has_shape_source(sim: Simulator) -> bool:
    """モデルに非 ``()`` shape の起点があるか — 経路選択の pre-filter (ADR-0079 §(1))。

    ``port_shapes_in/out`` 宣言と ``_SHAPE_SOURCES`` のパラメータ条件 (行列 /
    ベクトル ``Gain.k``、非 rank-0 の ``x0`` 等) を O(V) で走査する。Stage 2
    (ADR-0079 §(6)) からは Subsystem の内部ブロックも再帰的に見る (内部だけに
    起点があるモデルも plan 経路で実行する)。起点が 1 つもなければ推論結果も
    全 ``()`` になる (非 ``()`` は起点からしか生まれない) ため、``False`` の
    モデルを解決器なしで SM-A path に流しても健全。
    """
    return _any_shape_source(sim.blocks)


def _any_shape_source(blocks: Iterable[Block]) -> bool:
    for b in blocks:
        if any(s != SCALAR_SHAPE for s in b.port_shapes_in):
            return True
        if any(s != SCALAR_SHAPE for s in b.port_shapes_out):
            return True
        for name in _mro_names(b):
            predicate = _SHAPE_SOURCES.get(name)
            if predicate is not None:
                if predicate(b):
                    return True
                break
        inner = getattr(b, "_inner_blocks", None)
        if inner is not None and _any_shape_source(inner):
            return True
    return False


def reject_nested_dtype_declarations(sim: Simulator) -> None:
    """Subsystem 内部の**非 float64** ``dtype`` 宣言を fail-closed に拒否する
    (security MUST-1)。

    Stage 1 の pre-filter (`has_declared_dtype`) は root のみを見るため、
    Subsystem 内部の宣言は解決器を通らない。一方でブロック自身の ``output()``
    は ``dtype`` を単体で適用するため、放置すると「予測 (float64 island) と
    実行値 (内部で wrap 済み) が無警告で乖離」する — AC-2 の破れ。
    Stage 1 では内部宣言そのものを未対応としてエラーにする
    (内部の型伝播は Stage 2、SPEC-0028 Q6)。

    例外として ``dtype == "float64"`` は許す (v0.56.0): island 内はもともと
    全経路 float64 なので、float64 宣言は予測とも実行値とも完全一致し乖離が
    生じない。v0.56.0 の Cast は常に ``dtype`` を宣言する (既定 "float64")
    ため、これを拒否すると Subsystem 内に Cast を置けなくなり、旧
    ``Cast(output_type="float")`` を含むモデルの 0.12 migration も壊れる。

    Raises:
        BlockSpecError: ネストしたブロックに ``dtype`` が ``"auto"`` /
            ``"float64"`` 以外で宣言されている。
    """

    def _scan(blocks: Iterable[Block], owner_id: str | None) -> None:
        for b in blocks:
            declared = str(b._params.get("dtype", "auto"))
            if owner_id is not None and declared not in ("auto", ISLAND_DTYPE):
                raise BlockSpecError(
                    f"dtype declaration {declared!r} on block {b.id!r} inside "
                    f"Subsystem {owner_id!r} is not supported in this release: "
                    "the Subsystem boundary is a float64 island (SPEC-0028 Q6) "
                    "and inner non-float64 declarations would silently diverge "
                    "from the resolved dtypes. Move the Cast/Constant with "
                    "dtype to the top level, or use dtype='float64'.",
                    block_id=b.id,
                )
            inner = getattr(b, "_inner_blocks", None)
            if inner is not None:
                _scan(inner, _block_id(b))

    _scan(sim.blocks, None)


def _static_order(blocks: Sequence[Block]) -> list[Block]:
    """build を一切呼ばない擬似トポロジ順 (static mode 用、SHOULD-2 対応)。

    ``input_sources`` (接続情報のみ、build 不要) で Kahn 法を回す。登録順で
    処理すると不動点反復が O(V²) になるため、依存順に並べて数パスで収束させる。
    循環に含まれるブロックは登録順のまま末尾に残す (収束は反復側が担保)。
    """
    ids = {id(b) for b in blocks}
    indeg: dict[int, int] = {id(b): 0 for b in blocks}
    dependents: dict[int, list[Block]] = {id(b): [] for b in blocks}
    for b in blocks:
        for src in b.input_sources:
            if src is not None and id(src[0]) in ids:
                indeg[id(b)] += 1
                dependents[id(src[0])].append(b)
    queue: deque[Block] = deque(b for b in blocks if indeg[id(b)] == 0)
    order: list[Block] = []
    seen: set[int] = set()
    while queue:
        b = queue.popleft()
        if id(b) in seen:
            continue
        seen.add(id(b))
        order.append(b)
        for d in dependents[id(b)]:
            indeg[id(d)] -= 1
            if indeg[id(d)] == 0:
                queue.append(d)
    for b in blocks:
        if id(b) not in seen:
            order.append(b)
    return order


# ---------------------------------------------------------------------------
# 解決アルゴリズム (SPEC-0027 §3.3 + ADR-0079 §(1))
# ---------------------------------------------------------------------------

DiagSink = Callable[[SignalDiagnostic], None]


def _diag(code: str, message: str, **kwargs: Any) -> SignalDiagnostic:
    """severity を code から引いて診断を組み立てる。"""
    return SignalDiagnostic(severity=_SEVERITY_BY_CODE[code], code=code, message=message, **kwargs)


def _promote_many(dtypes: Sequence[str], sink: DiagSink | None, block_id: str) -> str:
    """複数入力の昇格。語彙外に出たら float64 に丸め、診断を出す (SPEC-0027 §1)。"""
    result = UNKNOWN
    for d in dtypes:
        result = promote(result, d)
    if result != UNKNOWN and result not in _VOCABULARY_SET:
        if sink is not None:
            sink(
                _diag(
                    "dtype.out_of_vocabulary",
                    f"Promotion result {result!r} at block {block_id!r} is outside "
                    f"the Stage 0 vocabulary; rounded to float64.",
                    block_id=block_id,
                    from_dtype=result,
                    to_dtype="float64",
                )
            )
        logger.debug("dtype.out_of_vocabulary block_id=%s result=%s", block_id, result)
        return "float64"
    return result


def _upstream_sources(block: Block) -> list[tuple[Block, int] | None]:
    """各入力ポートの上流 ``(block, out_idx)`` (未接続は None)。From は対応 Goto の上流を
    **仮想入力** として末尾に追加する (dtype / shape 共通の走査規則)。"""
    sources: list[tuple[Block, int] | None] = []
    for i in range(block.n_inputs):
        src = block.input_sources[i]
        sources.append(None if src is None else (src[0], src[1]))
    resolved_goto = getattr(block, "_resolved_goto", None)
    if resolved_goto is not None and resolved_goto.n_inputs > 0:
        # From の仮想入力 = 対応 Goto の上流出力 (反復中の out_of には
        # out ポートしか無いため、Goto の input_sources を直接辿る)。
        # Note: static mode では通常未設定 → unknown だが、同一 Simulator で
        # 事前に run() 等 (正当な build) を済ませていると _resolved_goto が
        # 残存し、static mode でも Goto/From が解決されることがある (無害)。
        goto_src = resolved_goto.input_sources[0]
        sources.append(None if goto_src is None else (goto_src[0], goto_src[1]))
    return sources


def _gather_raw_inputs(block: Block, lookup: Callable[[Block, int], str | None]) -> list[str]:
    """各入力ポートの上流出力 dtype (未接続 / 未解決は unknown)。

    上流 ``(block, out_idx)`` の解決は ``lookup`` に委ねる (``_resolve_graph`` のスコープ
    判定: 現スコープ → Subsystem 内部 (外側の From が内部の Goto を参照する
    ADR-0079 D-n) → 上位スコープ)。
    """
    return [
        UNKNOWN if s is None else (lookup(s[0], s[1]) or UNKNOWN) for s in _upstream_sources(block)
    ]


def _gather_raw_shapes(
    block: Block, lookup: Callable[[Block, int], Shape | None]
) -> list[Shape | None]:
    """各入力ポートの上流出力 shape (未接続 / 未解決は ``None``)。``lookup`` は
    :func:`_gather_raw_inputs` と同じ。"""
    return [None if s is None else lookup(s[0], s[1]) for s in _upstream_sources(block)]


def _infer_outputs(
    block: Block,
    category: Category,
    in_dtypes: Sequence[str],
    sink: DiagSink | None,
    *,
    island: bool = False,
) -> list[str]:
    """分類規則で出力 dtype を決める (SPEC-0027 §3.5 + SPEC-0028 Q1/Q6)。"""
    n_out = block.n_outputs
    if category == "bool_out":
        return ["bool"] * n_out
    if category == "int_out":
        return ["int64"] * n_out
    if category == "float_out":
        return ["float64"] * n_out
    if category == "param_typed":
        # v0.56.0 (output_type 撤去後): `dtype` のみが型宣言。Cast は常に宣言
        # (auto なし)、Constant の "auto" = 未宣言 = float64 定数。
        declared = str(block._params.get("dtype", "auto"))
        if declared != "auto":
            return [declared] * n_out
        return ["float64"] * n_out
    if category == "promote_except_control":
        control = _control_port_index(block)
        data = [d for i, d in enumerate(in_dtypes) if i != control]
        return [_promote_many(data, sink, _block_id(block))] * n_out
    if category == "fanout":
        first = in_dtypes[0] if in_dtypes else UNKNOWN
        return [first] * n_out
    if category == "sink":
        return [UNKNOWN] * n_out
    if category == "opaque":
        # Q6 (Stage 1): full mode では float64 island。static mode は Stage 0 の
        # unknown を維持 (float64 と偽らない — 測定装置としての誠実さ)。
        return (["float64"] if island else [UNKNOWN]) * n_out
    # promote (既定規則)
    return [_promote_many(in_dtypes, sink, _block_id(block))] * n_out


def _apply_input_requirement(
    block: Block,
    raw: Sequence[str],
    sink: DiagSink | None,
    required: str | None,
) -> list[str]:
    """D-4: 要求 dtype への自動昇格。縮小は error 診断を出す (Stage 1 の
    実行経路では ``resolve_for_execution`` が ``BlockSpecError`` に昇格する)。"""
    if required is None:
        return list(raw)
    applied: list[str] = []
    for i, d in enumerate(raw):
        if d == UNKNOWN or d == required:
            applied.append(d)
            continue
        widened = promote(d, required)
        if widened == required:
            applied.append(required)
            if sink is not None:
                sink(
                    _diag(
                        "dtype.implicit_widening",
                        f"Input {block.id!r}.in[{i}] widened from {d} to {required} "
                        f"(block requires {required}).",
                        block_id=block.id,
                        direction="in",
                        port_index=i,
                        from_dtype=d,
                        to_dtype=required,
                    )
                )
        else:
            # 縮小が必要 (Stage 0 語彙では通常発生しない防御経路)。
            # 実際の縮小は行わず、Stage 1 で build エラーに昇格する予告を出す。
            applied.append(d)
            if sink is not None:
                sink(
                    _diag(
                        "dtype.narrowing_required",
                        f"Input {block.id!r}.in[{i}] carries {d} but the block "
                        f"requires {required}; narrowing must be made explicit "
                        f"with a Cast (build error from Stage 1).",
                        block_id=block.id,
                        direction="in",
                        port_index=i,
                        from_dtype=d,
                        to_dtype=required,
                    )
                )
    return applied


# ---------------------------------------------------------------------------
# shape 規則 (ADR-0079 §(1) / D-4 / D-6)
# ---------------------------------------------------------------------------

_MISMATCH_HINT: Final[str] = (
    "numpy-style broadcasting is not applied; adapt the signal explicitly "
    "(Mux/Demux for scalar<->vector, or a vector-aware block)."
)


def _merge_many_shapes(
    shapes: Sequence[Shape | None], sink: DiagSink | None, block: Block
) -> Shape | None:
    """複数入力の合流 (D-4)。未確定 (``None``) は無視する。

    拒否された組合せは ``shape.broadcast_rejected`` を出し ``None`` を返す
    (full mode では後段の materialize が ``()`` に落とすが、error 級診断が
    立つため実行には至らない)。
    """
    result: Shape | None = None
    for i, s in enumerate(shapes):
        if s is None:
            continue
        if result is None:
            result = s
            continue
        merged = merge_shapes(result, s)
        if merged is None:
            if sink is not None:
                sink(
                    _diag(
                        "shape.broadcast_rejected",
                        f"Block {block.id!r} ({type(block).__name__}) receives "
                        f"incompatible input shapes {_shape_str(result)} and "
                        f"{_shape_str(s)} (input port {i}); only identical shapes "
                        f"or a rank-0 scalar with one vector shape can be combined. "
                        + _MISMATCH_HINT,
                        block_id=block.id,
                        direction="in",
                        port_index=i,
                        expected_shape=result,
                        actual_shape=s,
                    )
                )
            return None
        result = merged
    return result


def _select_data_indices(block: Block) -> tuple[int | None, list[int]]:
    """select 分類の ``(制御ポート index, データポート index 一覧)``。"""
    control = _control_port_index(block)
    data = [i for i in range(block.n_inputs) if i != control]
    return control, data


def _check_in_shapes(
    block: Block,
    category: ShapeCategory,
    raw: Sequence[Shape | None],
    sink: DiagSink | None,
) -> list[Shape | None]:
    """入力ポートの shape 検査と「実効 in shape」の決定 (最終パスで ``sink`` 付き)。

    戻り値は ``n_inputs`` 個 (From の仮想入力は含めない)。未接続 / 未確定は
    ``None`` のまま返し、呼び出し側が materialize する。``declared`` / ``opaque`` /
    ``select`` では未接続ポートにも「そのブロックが期待する shape」を返す
    (= ``_step_vector`` のゼロ埋めがその shape で行われる)。
    """
    n_in = block.n_inputs
    raw_in = list(raw[:n_in])
    bid = block.id

    if category in ("elementwise", "gain", "fanout", "sink", "inferred", "reduce", "matmul"):
        # reduce の合流検査は _infer_out_shapes (_merge_many_shapes) が、matmul の
        # 内側次元検査は _matmul_out_shape が行う
        return raw_in

    if category == "select":
        control, data = _select_data_indices(block)
        effective: list[Shape | None] = list(raw_in)
        if control is not None and raw_in[control] not in (None, SCALAR_SHAPE):
            if sink is not None:
                sink(
                    _diag(
                        "shape.control_port_not_scalar",
                        f"Control input {bid!r}.in[{control}] of "
                        f"{type(block).__name__} must be a scalar, got shape "
                        f"{_shape_str(raw_in[control])}. Select one element with "
                        f"Demux (or use a scalar control signal).",
                        block_id=bid,
                        direction="in",
                        port_index=control,
                        expected_shape=SCALAR_SHAPE,
                        actual_shape=raw_in[control],
                    )
                )
            effective[control] = SCALAR_SHAPE
        uniform: Shape | None = None
        for i in data:
            s = raw_in[i]
            if s is None:
                continue
            if uniform is None:
                uniform = s
            elif s != uniform:
                if sink is not None:
                    sink(
                        _diag(
                            "shape.mismatch",
                            f"Data inputs of {type(block).__name__} {bid!r} must "
                            f"share one shape: in[{data[0]}] is "
                            f"{_shape_str(uniform)} but in[{i}] is {_shape_str(s)}. "
                            + _MISMATCH_HINT,
                            block_id=bid,
                            direction="in",
                            port_index=i,
                            expected_shape=uniform,
                            actual_shape=s,
                        )
                    )
        for i in data:
            if raw_in[i] is None:
                effective[i] = uniform
        return effective

    if category == "state":
        x0_shape = _x0_shape_of(block)
        if x0_shape == SCALAR_SHAPE:
            # 7a': 状態 shape は入力の合流 shape (elementwise と同じ受理)
            return raw_in
        effective_state: list[Shape | None] = []
        for i, s in enumerate(raw_in):
            if s is not None and s != SCALAR_SHAPE and s != x0_shape and sink is not None:
                sink(
                    _diag(
                        "shape.mismatch",
                        f"Input {bid!r}.in[{i}] of {type(block).__name__} receives "
                        f"shape {_shape_str(s)} but x0 has shape {_shape_str(x0_shape)}; "
                        f"a vector x0 fixes the state shape, so the input must be a "
                        f"scalar or exactly {_shape_str(x0_shape)}. Use Mux/Demux to "
                        f"adapt the signal, or pass a scalar x0.",
                        block_id=bid,
                        direction="in",
                        port_index=i,
                        expected_shape=x0_shape,
                        actual_shape=s,
                    )
                )
            effective_state.append(x0_shape if s is None else s)
        return effective_state

    if category == "subsystem":
        inports, _outports = _inner_ports(block)
        _n_data, enable_idx, trigger_idx = _subsystem_slots(block)
        effective_sub: list[Shape | None] = list(raw_in)
        for i, s in enumerate(raw_in):
            if i in (enable_idx, trigger_idx):
                # ADR-0079 §(6): Trigger / Enable の制御 slot は () 固定
                if s is not None and s != SCALAR_SHAPE and sink is not None:
                    kind = "enable" if i == enable_idx else "trigger"
                    sink(
                        _diag(
                            "shape.control_port_not_scalar",
                            f"Control input {bid!r}.in[{i}] ({kind} port of "
                            f"Subsystem) must be a scalar, got shape {_shape_str(s)}. "
                            f"Select one element with Demux.",
                            block_id=bid,
                            direction="in",
                            port_index=i,
                            expected_shape=SCALAR_SHAPE,
                            actual_shape=s,
                        )
                    )
                effective_sub[i] = SCALAR_SHAPE
                continue
            inport = inports.get(i)
            declared_in = getattr(inport, "port_shape", None) if inport is not None else None
            if declared_in is None:
                continue  # 継承: 外側 shape をそのまま内部へ
            declared_in = tuple(declared_in)
            if s is not None and s != declared_in and sink is not None:
                sink(
                    _diag(
                        "shape.mismatch",
                        f"Input {bid!r}.in[{i}] receives shape {_shape_str(s)} but the "
                        f"inner Inport {getattr(inport, 'id', None)!r} declares "
                        f"port_shape={_shape_str(declared_in)}. Remove the declaration "
                        f"to inherit the outer shape, or adapt with Mux/Demux.",
                        block_id=bid,
                        direction="in",
                        port_index=i,
                        expected_shape=declared_in,
                        actual_shape=s,
                    )
                )
            effective_sub[i] = declared_in
        return effective_sub

    if category == "sink_scalar":
        for i, s in enumerate(raw_in):
            if s is not None and s != SCALAR_SHAPE and sink is not None:
                sink(
                    _diag(
                        "shape.mismatch",
                        f"Input {bid!r}.in[{i}] of {type(block).__name__} receives "
                        f"shape {_shape_str(s)} but this block accepts scalar "
                        f"signals only. Use a Demux block to select one element.",
                        block_id=bid,
                        direction="in",
                        port_index=i,
                        expected_shape=SCALAR_SHAPE,
                        actual_shape=s,
                    )
                )
        return [SCALAR_SHAPE] * n_in

    if category == "opaque":
        for i, s in enumerate(raw_in):
            declared = block.port_shapes_in[i]
            if sink is not None:
                if declared != SCALAR_SHAPE:
                    sink(
                        _diag(
                            "shape.opaque_scalar_island",
                            f"Block {bid!r} ({type(block).__name__}) declares a "
                            f"vector input port in[{i}] with shape "
                            f"{_shape_str(declared)}; vector ports across a "
                            f"Subsystem / user-code boundary arrive in Stage 2 "
                            f"(ADR-0079). In this release the boundary is scalar.",
                            block_id=bid,
                            direction="in",
                            port_index=i,
                            expected_shape=SCALAR_SHAPE,
                            actual_shape=declared,
                        )
                    )
                elif s is not None and s != SCALAR_SHAPE:
                    sink(
                        _diag(
                            "shape.opaque_scalar_island",
                            f"Input {bid!r}.in[{i}] of {type(block).__name__} "
                            f"receives shape {_shape_str(s)}, but Subsystem / "
                            f"PythonFunction / Fcn / @block boundaries accept "
                            f"scalar signals only in this release (vector "
                            f"boundaries arrive in Stage 2, ADR-0079). Insert a "
                            f"Demux before the boundary and a Mux after it.",
                            block_id=bid,
                            direction="in",
                            port_index=i,
                            expected_shape=SCALAR_SHAPE,
                            actual_shape=s,
                        )
                    )
        return [SCALAR_SHAPE] * n_in

    # declared: 宣言 shape がそのまま契約 (旧 Simulator._check_port_shapes の意味論)
    effective_declared: list[Shape | None] = []
    for i, s in enumerate(raw_in):
        declared = block.port_shapes_in[i]
        if s is not None and s != declared and sink is not None:
            if declared == SCALAR_SHAPE:
                detail = (
                    "this block accepts scalar signals only (SISO TransferFunction / "
                    "DiscreteTransferFunction, Relay, TransportDelay and the time "
                    "sources stay scalar, ADR-0079 D-10). Use a Demux block to select "
                    "one element, or a vector-aware block (StateSpace for MIMO)."
                )
            else:
                detail = (
                    f"this port is declared as {_shape_str(declared)}. "
                    f"Use Mux/Demux to adapt the signal; " + _MISMATCH_HINT
                )
            sink(
                _diag(
                    "shape.mismatch",
                    f"Input {bid!r}.in[{i}] receives shape {_shape_str(s)} but "
                    f"expects {_shape_str(declared)}: " + detail,
                    block_id=bid,
                    direction="in",
                    port_index=i,
                    expected_shape=declared,
                    actual_shape=s,
                )
            )
        effective_declared.append(declared)
    return effective_declared


def _inner_ports(sub: Block) -> tuple[dict[int, Block], dict[int, Block]]:
    """Subsystem の内部 Inport / Outport を ``port_idx`` で引く (build 不要、MRO 名判定)。"""
    inports: dict[int, Block] = {}
    outports: dict[int, Block] = {}
    for b in getattr(sub, "_inner_blocks", ()):
        names = _mro_names(b)
        idx = getattr(b, "port_idx", None)
        if not isinstance(idx, int):
            continue
        if "Inport" in names:
            inports[idx] = b
        elif "Outport" in names:
            outports[idx] = b
    return inports, outports


def _subsystem_slots(sub: Block) -> tuple[int, int | None, int | None]:
    """``(データ Inport 数, enable slot, trigger slot)`` — ADR-0058 の slot 順序
    ``[data..., enable, trigger]`` を build なしで再現する。"""
    inner = list(getattr(sub, "_inner_blocks", ()))
    n_data = sum(1 for b in inner if "Inport" in _mro_names(b))
    has_enable = any("Enable" in _mro_names(b) for b in inner)
    has_trigger = any("Trigger" in _mro_names(b) for b in inner)
    enable_idx = n_data if has_enable else None
    trigger_idx = (n_data + (1 if has_enable else 0)) if has_trigger else None
    return n_data, enable_idx, trigger_idx


def _inferred_out_shapes(
    block: Block, in_shapes: Sequence[Shape | None], sink: DiagSink | None
) -> list[Shape | None]:
    """``infer_output_shapes(in_shapes)`` hook (ADR-0079 §(3) 6c) を呼ぶ。

    未確定の入力は ``()`` として渡す (hook は確定 shape だけを見る)。戻り値は
    ``n_outputs`` 個の shape。hook の例外・不正な戻り値は ``shape.unresolved``
    (error 級ではないが full mode では materialize されず) ではなく、実装ミス
    として ``BlockSpecError`` にする。
    """
    n_in = block.n_inputs
    concrete = tuple(s if s is not None else SCALAR_SHAPE for s in in_shapes[:n_in])
    hook = block.infer_output_shapes  # type: ignore[attr-defined]
    try:
        result = hook(concrete)
    except BlockSpecError:
        raise
    except Exception as e:  # noqa: BLE001 - ユーザー hook の例外を仕様違反として包む
        raise BlockSpecError(
            f"Block {block.id!r} ({type(block).__name__}).infer_output_shapes raised "
            f"{type(e).__name__}: {e}",
            block_id=block.id,
        ) from e
    try:
        shapes = [tuple(int(d) for d in s) for s in result]
    except TypeError as e:
        raise BlockSpecError(
            f"Block {block.id!r}.infer_output_shapes must return a sequence of shapes "
            f"(tuples of int), got {result!r}",
            block_id=block.id,
        ) from e
    if len(shapes) != block.n_outputs:
        raise BlockSpecError(
            f"Block {block.id!r}.infer_output_shapes returned {len(shapes)} shape(s), "
            f"expected {block.n_outputs}",
            block_id=block.id,
        )
    return list(shapes)


def _x0_shape_of(block: Block) -> Shape:
    """ベクトル状態ブロックの ``x0`` 宣言 shape (``()`` = スカラ拡張可)。"""
    return tuple(int(d) for d in getattr(block, "_x0_shape", ()))


def _state_out_shape(
    block: Block, in_shapes: Sequence[Shape | None], sink: DiagSink | None
) -> Shape | None:
    """``state`` 規則の出力 shape (= 実効 state shape、ADR-0079 §(5) 7a')。"""
    x0_shape = _x0_shape_of(block)
    if x0_shape != SCALAR_SHAPE:
        return x0_shape
    # rank-0 の x0: 入力の合流 shape に従う (未確定なら None → materialize で ())
    return _merge_many_shapes(in_shapes, sink, block)


def _gain_out_shape(block: Block, in_shape: Shape | None, sink: DiagSink | None) -> Shape | None:
    """``Gain`` の出力 shape (``multiplication`` × ``k`` の shape、ADR-0079 §(3))。

    契約: ``in_shape is None`` (未確定) のとき elementwise は ``k`` の shape を先読み
    できるが、行列モードは ``None`` を返す。full mode の最終パスは未確定を ``()`` に
    materialize してから本関数を再度呼ぶので、行列モードの未接続入力は
    ``_matmul_shape(k, ())`` の失敗として **error 級** (``shape.mismatch``) になる
    (info の ``shape.defaulted_to_scalar`` だけで実行に進ませない)。
    """
    k_shape: Shape = tuple(int(d) for d in np.shape(getattr(block, "k", 0.0)))
    mode = str(getattr(block, "multiplication", "elementwise"))
    if mode == "elementwise":
        if in_shape is None:
            return k_shape if k_shape != SCALAR_SHAPE else None
        merged = merge_shapes(k_shape, in_shape)
        if merged is None and sink is not None:
            sink(
                _diag(
                    "shape.mismatch",
                    f"Gain {block.id!r}: elementwise gain k with shape "
                    f"{_shape_str(k_shape)} cannot multiply an input of shape "
                    f"{_shape_str(in_shape)}; k must be a scalar or match the "
                    f"input shape exactly. For a matrix product use "
                    f"multiplication='matrix-Ku' / 'matrix-uK'.",
                    block_id=block.id,
                    direction="in",
                    port_index=0,
                    expected_shape=k_shape,
                    actual_shape=in_shape,
                )
            )
        return merged
    if in_shape is None:
        return None
    result = (
        _matmul_shape(k_shape, in_shape)
        if mode == "matrix-Ku"
        else _matmul_shape(in_shape, k_shape)
    )
    if result is None and sink is not None:
        expr = "k @ u" if mode == "matrix-Ku" else "u @ k"
        sink(
            _diag(
                "shape.mismatch",
                f"Gain {block.id!r}: multiplication={mode!r} computes {expr} but k "
                f"has shape {_shape_str(k_shape)} and the input has shape "
                f"{_shape_str(in_shape)}; the inner dimensions must agree and "
                f"both operands must be rank 1 or 2 (use a Mux to build the "
                f"input vector).",
                block_id=block.id,
                direction="in",
                port_index=0,
                expected_shape=k_shape,
                actual_shape=in_shape,
            )
        )
    return result


def _matmul_out_shape(
    block: Block, in_shapes: Sequence[Shape | None], sink: DiagSink | None
) -> Shape | None:
    """``MatrixMultiply`` の出力 shape (``u0 @ u1``、ADR-0079 Stage 3)。

    両入力が既知になるまで ``None``。両方 ``()`` はスカラ積で ``()``。片方だけ ``()``
    や内側次元の不一致は ``shape.mismatch`` (最終パスで ``()`` に materialize された
    未接続入力も同じ経路で error 級になる)。
    """
    a = in_shapes[0] if len(in_shapes) > 0 else None
    b = in_shapes[1] if len(in_shapes) > 1 else None
    if a is None or b is None:
        return None
    if a == SCALAR_SHAPE and b == SCALAR_SHAPE:
        return SCALAR_SHAPE
    result = _matmul_shape(a, b)
    if result is None and sink is not None:
        sink(
            _diag(
                "shape.mismatch",
                f"MatrixMultiply {block.id!r}: cannot compute u0 @ u1 for shapes "
                f"{_shape_str(a)} and {_shape_str(b)}; both operands must be rank 1 "
                f"or 2 with matching inner dimensions (use Mux to build the vectors, "
                f"or Gain for a scalar factor).",
                block_id=block.id,
                direction="in",
                port_index=1,
                expected_shape=a,
                actual_shape=b,
            )
        )
    return result


def _infer_out_shapes(
    block: Block,
    category: ShapeCategory,
    in_shapes: Sequence[Shape | None],
    sink: DiagSink | None,
) -> list[Shape | None]:
    """shape 規則で出力 shape を決める (未確定は ``None``)。

    ``in_shapes`` は ``_gather_raw_shapes`` の生の列 (From の仮想入力を含む)。
    """
    n_out = block.n_outputs
    if n_out == 0:
        return []
    if category == "elementwise":
        return [_merge_many_shapes(in_shapes, sink, block)] * n_out
    if category == "gain":
        first = in_shapes[0] if in_shapes else None
        return [_gain_out_shape(block, first, sink)] * n_out
    if category == "select":
        _control, data = _select_data_indices(block)
        known = [in_shapes[i] for i in data if in_shapes[i] is not None]
        return [known[0] if known else None] * n_out
    if category == "fanout":
        first = in_shapes[0] if in_shapes else None
        return [first] * n_out
    if category == "state":
        return [_state_out_shape(block, in_shapes, sink)] * n_out
    if category == "inferred":
        return _inferred_out_shapes(block, in_shapes, sink)
    if category == "reduce":
        # 入力の合流検査 (診断込み) だけ行い、出力は常にスカラ
        _merge_many_shapes(in_shapes, sink, block)
        return [SCALAR_SHAPE] * n_out
    if category == "matmul":
        return [_matmul_out_shape(block, in_shapes, sink)] * n_out
    if category == "subsystem":
        # 階層再帰は _resolve_graph が _resolve_subsystem で行う (ここは到達しない)
        raise BlockSpecError(
            f"internal error: subsystem {block.id!r} must be resolved via _resolve_subsystem"
        )
    if category == "opaque":
        return [SCALAR_SHAPE] * n_out
    if category in ("sink", "sink_scalar"):
        return [None] * n_out
    # declared
    return list(block.port_shapes_out)


def _scope_columns(in_shapes: Sequence[Shape]) -> int:
    """Scope / Display の記録列数 (全入力ポートの総要素数、C order 列展開)。"""
    return int(sum(int(np.prod(s, dtype=np.int64)) for s in in_shapes))


def _sink_diagnostics(block: Block, in_shapes: Sequence[Shape], sink: DiagSink) -> None:
    """Scope / Display の labels 整合と大ベクトル警告 (ADR-0079 §(4))。"""
    labels = getattr(block, "labels", None)
    if not isinstance(labels, list):
        return
    columns = _scope_columns(in_shapes)
    if len(labels) not in (block.n_inputs, columns):
        sink(
            _diag(
                "shape.mismatch",
                f"{type(block).__name__} {block.id!r}: {len(labels)} label(s) given "
                f"but the inputs expand to {columns} column(s) ({block.n_inputs} "
                f"port(s)); pass one label per port or one per column.",
                block_id=block.id,
            )
        )
    if columns > SCOPE_LARGE_VECTOR_COLUMNS:
        sink(
            _diag(
                "shape.large_vector",
                f"{type(block).__name__} {block.id!r} records {columns} columns "
                f"(> {SCOPE_LARGE_VECTOR_COLUMNS}); plotting / WebSocket batches "
                f"may become slow.",
                block_id=block.id,
            )
        )


ResolveMode = Literal["auto", "full", "static"]


def _resolve_impl(sim: Simulator, *, mode: ResolveMode = "auto") -> SignalResolution:
    """二経路の振り分け (例外の診断化は ``resolve_signals`` 側)。

    - **full mode** = Stage 1 意味論 (SPEC-0028): opaque は float64 island (Q6)、
      収束後の unknown は float64 / ``()`` へ materialize (Q5 = 全域性 AC-3)
    - **static mode** = Stage 0 意味論を維持 (PythonFunction を含むモデルの
      REST / GUI 経路。``_build()`` せず、island / materialize も行わない)。
      解決中は exec ガード (SPEC-0028 §3.8) を立てる
    """
    blocks = list(sim.blocks)
    if mode == "auto":
        # NIT (security 2026-09-08): 検出自体も exec ガード区間で行う —
        # _inner_blocks が将来遅延化されても検出時の exec を fail-closed にする
        detect_token = _RESOLVING_WITHOUT_USER_CODE.set(True)
        try:
            static_mode = _contains_python_function(blocks)
        finally:
            _RESOLVING_WITHOUT_USER_CODE.reset(detect_token)
    else:
        static_mode = mode == "static"

    if not static_mode:
        # security MUST-1 (2026-09-08): ネスト dtype 宣言は fail-closed に拒否
        # (REST 経路では resolve_signals の catch-all が dtype.build_failed に変換)
        reject_nested_dtype_declarations(sim)
        # ADR-0079 D-11: トポロジカル順 (代数ループ検出) の **後** に解決する。
        order = sim._execution_order()
        return _resolve_graph(sim, blocks, order, island=True, static=False)

    guard_token = _RESOLVING_WITHOUT_USER_CODE.set(True)
    try:
        # static mode: _build() はユーザーコードを exec するため一切呼ばない。
        # 順序は input_sources だけで作る擬似トポロジ順 (build 不要)。
        order = _static_order(blocks)
        return _resolve_graph(sim, blocks, order, island=False, static=True)
    finally:
        _RESOLVING_WITHOUT_USER_CODE.reset(guard_token)


class _SubsystemResolver:
    """Subsystem 内部スコープの再帰解決 (ADR-0079 §(6) D-8、8a: 外 → 内 → 外 の 1 パス)。

    外側の反復が Subsystem に到達するたびに、その時点の外側 in shape で内部を
    解決する。入力 shape が同じなら結果も同じなので、``(id(sub), in_shapes)`` で
    キャッシュして反復コストを抑える。最終パスの結果が ``results`` に残る。
    """

    def __init__(self, sim: Simulator, *, island: bool, static: bool) -> None:
        self.sim = sim
        self.island = island
        self.static = static
        self.results: dict[str, SignalResolution] = {}
        self._cache: dict[tuple[int, tuple[Shape | None, ...]], SignalResolution] = {}
        # bug-fix 2026-09-21 (ADR-0079 D-n): 内部ブロック id() → その内部スコープの最新の
        # 解決結果。外側の From が内部の Goto を参照するとき、内部の out shape / dtype を
        # ここから引く (反復ごとに更新され、最終パスでは最終結果を指す)
        self._latest_by_block: dict[int, SignalResolution] = {}

    def owns(self, block: Block) -> bool:
        """``block`` が (既に解決された) いずれかの Subsystem 内部スコープに属するか。"""
        return id(block) in self._latest_by_block

    def inner_out_shape(self, block: Block, port_idx: int) -> Shape | None:
        """内部スコープに属する ``block`` の出力 shape (未解決なら ``None``)。"""
        res = self._latest_by_block.get(id(block))
        if res is None:
            return None
        return res.shapes.get((_block_id(block), "out", port_idx))

    def inner_out_dtype(self, block: Block, port_idx: int) -> str | None:
        """内部スコープに属する ``block`` の出力 dtype (未解決なら ``None``)。"""
        res = self._latest_by_block.get(id(block))
        if res is None:
            return None
        return res.ports.get((_block_id(block), "out", port_idx))

    def resolve(
        self,
        sub: Block,
        in_shapes: Sequence[Shape | None],
        outer_shapes: Mapping[PortKey, Shape | None],
        sink: DiagSink | None,
    ) -> list[Shape | None]:
        """内部を解決し、外側の出力 shape (Outport の in shape) を返す。"""
        inports, outports = _inner_ports(sub)
        n_data, _e, _t = _subsystem_slots(sub)
        key = (id(sub), tuple(in_shapes[:n_data]))
        res = self._cache.get(key)
        inner_blocks = list(getattr(sub, "_inner_blocks", ()))
        if res is None:
            exec_order = getattr(sub, "_exec_order", None)
            order = (
                list(exec_order)
                if (not self.static and exec_order is not None)
                else _static_order(inner_blocks)
            )
            seeds: dict[int, Shape | None] = {}
            for idx, inport in inports.items():
                declared = getattr(inport, "port_shape", None)
                if declared is not None:
                    seeds[id(inport)] = tuple(declared)
                elif idx < len(in_shapes):
                    seeds[id(inport)] = in_shapes[idx]
                else:
                    seeds[id(inport)] = None
            res = _resolve_graph(
                self.sim,
                inner_blocks,
                order,
                island=self.island,
                static=self.static,
                inport_seeds=seeds,
                outer_shapes=outer_shapes,
                force_float64=True,
                sub_resolver=self,
            )
            self._cache[key] = res
        for inner in inner_blocks:
            self._latest_by_block[id(inner)] = res
        if sink is not None:
            # 最終パス: この Subsystem の内部結果を公開 (診断は内部側に残す)
            self.results[_block_id(sub)] = res
        out: list[Shape | None] = []
        for port_idx in range(sub.n_outputs):
            outport = outports.get(port_idx)
            if outport is None:
                out.append(None)
                continue
            s_out = res.shapes.get((_block_id(outport), "in", 0))
            declared_out = getattr(outport, "port_shape", None)
            if declared_out is not None:
                declared_out = tuple(declared_out)
                if s_out is not None and s_out != declared_out and sink is not None:
                    sink(
                        _diag(
                            "shape.mismatch",
                            f"Outport {_block_id(outport)!r} of Subsystem {sub.id!r} declares "
                            f"port_shape={_shape_str(declared_out)} but its inner source "
                            f"resolves to {_shape_str(s_out)}. Remove the declaration to "
                            f"inherit, or adapt with Mux/Demux inside the subsystem.",
                            block_id=sub.id,
                            direction="out",
                            port_index=port_idx,
                            expected_shape=declared_out,
                            actual_shape=s_out,
                        )
                    )
                s_out = declared_out
            out.append(s_out)
        return out


def _resolve_graph(
    sim: Simulator,
    blocks: list[Block],
    order: list[Block],
    *,
    island: bool,
    static: bool,
    inport_seeds: Mapping[int, Shape | None] | None = None,
    outer_shapes: Mapping[PortKey, Shape | None] | None = None,
    force_float64: bool = False,
    sub_resolver: _SubsystemResolver | None = None,
) -> SignalResolution:
    """不動点反復 + 最終パスの本体。``island`` = Stage 1 意味論 (Q5/Q6/Q7)。

    dtype と shape を **同じ反復** で更新する (ADR-0079 D-1)。診断は収束後の
    最終パスでのみ収集し、重複を避ける。

    Subsystem の内部スコープにも同じ関数を使う (ADR-0079 §(6)):
    ``inport_seeds`` は内部 Inport (``id()`` キー) の出力 shape (= 外側の in shape)、
    ``outer_shapes`` は外側スコープの解決済み shape (From が上位スコープの Goto を
    参照するときの検索先)、``force_float64`` は dtype island (SPEC-0028 Q6:
    内部 dtype は全ポート float64)。
    """
    diagnostics: list[SignalDiagnostic] = []
    if sub_resolver is None:
        sub_resolver = _SubsystemResolver(sim, island=island, static=static)
    seeds = inport_seeds or {}
    if static:
        diagnostics.append(
            _diag(
                "dtype.static_fallback",
                "Model contains PythonFunction; resolved without building "
                "(no user code executed). Goto/From links are unresolved and "
                "algebraic loops are not detected in this mode.",
            )
        )
        logger.debug("dtype.static_fallback: static resolution")

    # --- 反復 (診断は収束後の最終パスでのみ収集し、重複を避ける) ---
    out_of: dict[PortKey, str] = {}
    shape_of: dict[PortKey, Shape | None] = {}
    shape_cats: dict[int, ShapeCategory] = {}
    for b in blocks:
        shape_cats[id(b)] = _classify_shape(b)
        for j in range(b.n_outputs):
            out_of[(_block_id(b), "out", j)] = UNKNOWN
            shape_of[(_block_id(b), "out", j)] = None

    # 上位スコープの shape も検索対象にする (From → 上位 Goto の透過)
    shape_lookup: Mapping[PortKey, Shape | None] = (
        ChainMap(shape_of, dict(outer_shapes)) if outer_shapes else shape_of
    )
    # bug-fix 2026-09-21 (ADR-0079 D-n): 上流ブロックの所属スコープは **同一性** で判定する
    # (block id は スコープ内でしか一意でないため、外側にも同じ id があると id キーだけでは
    # 内部ブロックを取り違える)。現スコープ → Subsystem 内部 → 上位スコープの順。
    local_ids = {id(b) for b in blocks}

    def _upstream_shape(src: Block, idx: int) -> Shape | None:
        if id(src) in local_ids:
            return shape_of.get((_block_id(src), "out", idx))
        assert sub_resolver is not None
        if sub_resolver.owns(src):
            return sub_resolver.inner_out_shape(src, idx)
        return shape_lookup.get((_block_id(src), "out", idx))

    def _upstream_dtype(src: Block, idx: int) -> str | None:
        if id(src) in local_ids:
            return out_of.get((_block_id(src), "out", idx))
        assert sub_resolver is not None
        if sub_resolver.owns(src):
            return sub_resolver.inner_out_dtype(src, idx)
        # 上位スコープの dtype 表は持たない (内部は float64 island、SPEC-0028 Q6)
        return None

    def _out_shapes_for(
        b: Block, shape_cat: ShapeCategory, raw_shapes: list[Shape | None], sink: DiagSink | None
    ) -> list[Shape | None]:
        if id(b) in seeds and b.n_outputs == 1:
            # 内部 Inport: 外側 in shape (または明示宣言) を出力 shape にする
            return [seeds[id(b)]]
        if shape_cat == "subsystem":
            assert sub_resolver is not None
            in_eff = _check_in_shapes(b, shape_cat, raw_shapes, None)
            return sub_resolver.resolve(b, in_eff, shape_lookup, sink)
        return _infer_out_shapes(b, shape_cat, raw_shapes, sink)

    max_iterations = 2 * len(blocks) + _ITERATION_MARGIN
    converged = False
    for _ in range(max_iterations):
        changed = False
        for b in order:
            raw = _gather_raw_inputs(b, _upstream_dtype)
            category, _missing = _classify(b)
            required = _required_input_dtype(b, island=island)
            in_dtypes = _apply_input_requirement(b, raw, None, required)
            inferred = (
                ["float64"] * b.n_outputs
                if force_float64
                else _infer_outputs(b, category, in_dtypes, None, island=island)
            )
            for j, d in enumerate(inferred):
                key = (_block_id(b), "out", j)
                if out_of[key] != d:
                    out_of[key] = d
                    changed = True
            raw_shapes = _gather_raw_shapes(b, _upstream_shape)
            shape_cat = shape_cats[id(b)]
            # 入力側の検査 (_check_in_shapes) は診断付きの最終パスだけで行う
            for j, s in enumerate(_out_shapes_for(b, shape_cat, raw_shapes, None)):
                key = (_block_id(b), "out", j)
                if shape_of[key] != s:
                    shape_of[key] = s
                    changed = True
        if not changed:
            converged = True
            break
    if not converged:
        diagnostics.append(
            _diag(
                "dtype.iteration_limit",
                f"Fixed-point iteration hit the limit ({max_iterations}); "
                "returning the current partial result.",
            )
        )
        logger.debug("dtype.iteration_limit max_iterations=%d", max_iterations)

    # --- Q5 materialize (full mode のみ): 収束後に残った unknown を float64 / () へ ---
    if island:
        for key in sorted(out_of):
            if out_of[key] == UNKNOWN:
                out_of[key] = "float64"
                diagnostics.append(
                    _diag(
                        "dtype.defaulted_to_float64",
                        f"Output {key[0]!r}.out[{key[2]}] could not be inferred; "
                        "defaulted to float64 (totality, SPEC-0028 Q5).",
                        block_id=key[0],
                        direction="out",
                        port_index=key[2],
                        to_dtype="float64",
                    )
                )
        for key in sorted(shape_of, key=lambda k: (k[0], k[1], k[2])):
            if shape_of[key] is None:
                shape_of[key] = SCALAR_SHAPE
                diagnostics.append(
                    _diag(
                        "shape.defaulted_to_scalar",
                        f"Output {key[0]!r}.out[{key[2]}] has no upstream shape "
                        "source; defaulted to () (scalar, totality ADR-0079).",
                        block_id=key[0],
                        direction="out",
                        port_index=key[2],
                        expected_shape=SCALAR_SHAPE,
                    )
                )

    # --- 最終パス: in ポート確定 + 診断収集 ---
    sink: DiagSink = diagnostics.append
    ports: dict[PortKey, str] = dict(out_of)
    shapes: dict[PortKey, Shape | None] = dict(shape_of)
    for b in order:
        raw = _gather_raw_inputs(b, _upstream_dtype)
        category, rule_missing = _classify(b)
        required = _required_input_dtype(b, island=island)
        in_dtypes = _apply_input_requirement(b, raw, sink, required)
        if force_float64:
            in_dtypes = ["float64"] * len(in_dtypes)
        raw_shapes = _gather_raw_shapes(b, _upstream_shape)
        shape_cat = shape_cats[id(b)]
        in_shapes = _check_in_shapes(b, shape_cat, raw_shapes, sink)
        # 仮想入力 (From の Goto 参照) は in ポートとして数えない
        for i in range(b.n_inputs):
            d_in = in_dtypes[i]
            if b.input_sources[i] is None:
                sink(
                    _diag(
                        "dtype.unresolved",
                        f"Input {_block_id(b)!r}.in[{i}] is unconnected; its dtype is unknown.",
                        block_id=_block_id(b),
                        direction="in",
                        port_index=i,
                    )
                )
                if island and d_in == UNKNOWN:
                    # Q5: 未接続入力もゼロ埋め実行のため float64 (要求があれば要求)
                    d_in = required if required is not None else "float64"
            ports[(_block_id(b), "in", i)] = d_in
            s_in = in_shapes[i]
            if island and s_in is None:
                # 未接続 / 未確定の入力は () でゼロ埋め (全域性)
                s_in = SCALAR_SHAPE
            shapes[(_block_id(b), "in", i)] = s_in
        if rule_missing:
            sink(
                _diag(
                    "dtype.rule_missing",
                    f"Block {b.id!r} ({type(b).__name__}) has no classification "
                    "rule; resolved with the default promote rule.",
                    block_id=b.id,
                )
            )
        if category == "opaque":
            if island:
                sink(
                    _diag(
                        "dtype.opaque_float64_island",
                        f"Block {b.id!r} ({type(b).__name__}) is treated as a "
                        "float64 island in this release (SPEC-0028 Q6); internal "
                        "dtype propagation arrives in Stage 2.",
                        block_id=b.id,
                    )
                )
            else:
                sink(
                    _diag(
                        "dtype.unresolved",
                        f"Block {b.id!r} ({type(b).__name__}) is not resolved in "
                        "static mode; its outputs are reported as unknown.",
                        block_id=b.id,
                    )
                )
        if island and type(b).__name__ in _STATE_VIA_FLOAT64 and b.n_outputs > 0:
            out0 = out_of.get((_block_id(b), "out", 0), "float64")
            if out0 not in ("float64", UNKNOWN):
                sink(
                    _diag(
                        "dtype.state_via_float64",
                        f"Block {b.id!r} stores its state as float64 in this "
                        "release; int64 values beyond 2**53 lose precision "
                        "(SPEC-0028 Q7).",
                        block_id=b.id,
                        to_dtype=out0,
                    )
                )
        # 語彙外の丸め診断は _promote_many 経由で出るため再推論する
        if not force_float64:
            _infer_outputs(b, category, in_dtypes, sink, island=island)
        # 合流拒否 / Gain 次元不整合の診断も再推論で収集する。full mode では
        # 未接続 / 未確定の入力は () に materialize 済みなので、その **実効 shape**
        # で再推論する (例: 行列 Gain の未接続入力 = () は次元不整合 → error。
        # code-reviewer MUST 2026-09-21: 未接続を info で () に丸めて実行時
        # ValueError にしない)。Subsystem はここで内部結果を確定・公開する。
        final_raw: list[Shape | None] = (
            [s if s is not None else SCALAR_SHAPE for s in raw_shapes] if island else raw_shapes
        )
        _out_shapes_for(b, shape_cat, final_raw, sink)
        if shape_cat == "sink" and b.n_inputs > 0:
            known_in = [s if s is not None else SCALAR_SHAPE for s in in_shapes]
            _sink_diagnostics(b, known_in, sink)
        if shape_cat == "opaque" and any(s != SCALAR_SHAPE for s in b.port_shapes_out):
            for j, s_out in enumerate(b.port_shapes_out):
                if s_out != SCALAR_SHAPE:
                    sink(
                        _diag(
                            "shape.opaque_scalar_island",
                            f"Block {b.id!r} ({type(b).__name__}) declares a vector "
                            f"output port out[{j}] with shape {_shape_str(s_out)}; "
                            f"vector ports across a Subsystem / user-code boundary "
                            f"arrive in Stage 2 (ADR-0079).",
                            block_id=b.id,
                            direction="out",
                            port_index=j,
                            expected_shape=SCALAR_SHAPE,
                            actual_shape=s_out,
                        )
                    )
        if not island and any(
            shape_of.get((_block_id(b), "out", j)) is None for j in range(b.n_outputs)
        ):
            sink(
                _diag(
                    "shape.unresolved",
                    f"Block {b.id!r} ({type(b).__name__}) has output shapes that "
                    "cannot be determined in static mode (no build); reported as "
                    "unknown.",
                    block_id=b.id,
                )
            )

    for key in sorted(ports):
        block_id, direction, port_index = key
        dtype = ports[key]
        if direction == "out" and dtype not in (UNKNOWN, "float64"):
            sink(
                _diag(
                    "dtype.non_float_signal",
                    f"Output {block_id!r}.out[{port_index}] resolves to {dtype}.",
                    block_id=block_id,
                    direction="out",
                    port_index=port_index,
                    to_dtype=dtype,
                )
            )

    # --- 集計 ---
    by_dtype: dict[str, int] = {}
    unresolved = 0
    non_float = 0
    for dtype in ports.values():
        if dtype == UNKNOWN:
            unresolved += 1
            continue
        by_dtype[dtype] = by_dtype.get(dtype, 0) + 1
        if dtype != "float64":
            non_float += 1
    max_rank = 0
    vector_ports = 0
    for s in shapes.values():
        if s is None:
            continue
        max_rank = max(max_rank, len(s))
        if s != SCALAR_SHAPE:
            vector_ports += 1
    summary = SignalSummary(
        total_ports=len(ports),
        by_dtype=by_dtype,
        unresolved=unresolved,
        non_float_ports=non_float,
        max_rank=max_rank,
        vector_ports=vector_ports,
    )
    return SignalResolution(
        ports=ports,
        diagnostics=tuple(diagnostics),
        summary=summary,
        shapes=shapes,
        inner=dict(sub_resolver.results)
        if inport_seeds is None
        else _own_inner(sub_resolver, blocks),
    )


def _own_inner(
    sub_resolver: _SubsystemResolver, blocks: list[Block]
) -> dict[str, SignalResolution]:
    """このスコープ直下の Subsystem の内部結果だけを取り出す (ネストは各階層が持つ)。"""
    own: dict[str, SignalResolution] = {}
    for b in blocks:
        bid = _block_id(b)
        if bid in sub_resolver.results and "Subsystem" in _mro_names(b):
            own[bid] = sub_resolver.results[bid]
    return own


def _empty_resolution(diagnostic: SignalDiagnostic) -> SignalResolution:
    """build 失敗 / 内部エラー時の空結果。"""
    return SignalResolution(
        ports={},
        diagnostics=(diagnostic,),
        summary=SignalSummary(total_ports=0, by_dtype={}, unresolved=0, non_float_ports=0),
        shapes={},
    )


#: 実行不能を意味する診断 code (severity error に加えて実行時は致命扱い、SPEC-0028 §3.5)。
_FATAL_EXECUTION_CODES: Final[frozenset[str]] = frozenset(
    {
        "dtype.narrowing_required",
        "dtype.out_of_vocabulary",
        "dtype.iteration_limit",
        "shape.mismatch",
        "shape.broadcast_rejected",
        "shape.opaque_scalar_island",
        "shape.control_port_not_scalar",
    }
)


def _collect_fatal(res: SignalResolution) -> list[SignalDiagnostic]:
    """error 級 / 実行不能 code の診断を、Subsystem 内部 (``inner``) も含めて集める。"""
    fatal = [
        d for d in res.diagnostics if d.severity == "error" or d.code in _FATAL_EXECUTION_CODES
    ]
    for sub_id, inner in sorted(res.inner.items()):
        for d in _collect_fatal(inner):
            fatal.append(
                SignalDiagnostic(
                    severity=d.severity,
                    code=d.code,
                    message=f"(inside Subsystem {sub_id!r}) {d.message}",
                    block_id=d.block_id,
                    direction=d.direction,
                    port_index=d.port_index,
                    from_dtype=d.from_dtype,
                    to_dtype=d.to_dtype,
                    expected_shape=d.expected_shape,
                    actual_shape=d.actual_shape,
                )
            )
    return fatal


def resolve_for_execution(sim: Simulator) -> SignalResolution:
    """実行用の信号面解決 (``run()`` 経路、SPEC-0028 §3.2 / §3.4、ADR-0079 D-11)。

    常に full mode で解決し、error 級または実行不能を意味する診断が 1 件でも
    あれば **全件を集めてから 1 回だけ** 例外を送出する:

    - shape 起因の診断を含む → ``SignalShapeError`` (``BlockSpecError`` の
      サブクラス、``diagnostics`` に全件、先頭の位置情報を属性に展開)
    - dtype のみ → ``BlockSpecError`` (従来どおり、``block_id`` 付き)

    build 例外 (代数ループ等) はそのまま伝播する — 宣言モデルは解決の成功が
    実行の前提であり、Stage 0 の「例外を握り潰す」AC-5 は適用しない。
    """
    res = _resolve_impl(sim, mode="full")
    fatal = _collect_fatal(res)
    if not fatal:
        return res
    first = fatal[0]
    lines = [f"[{d.code}] {d.message}" for d in fatal]
    if any(d.code.startswith("shape.") for d in fatal):
        header = f"signal shape resolution failed ({len(fatal)} error(s)):"
        raise SignalShapeError(
            header + "".join(f"\n  {line}" for line in lines),
            block_id=first.block_id,
            direction=first.direction,
            port_index=first.port_index,
            expected_shape=first.expected_shape,
            actual_shape=first.actual_shape,
            diagnostics=tuple(fatal),
        )
    message = f"dtype resolution failed: {lines[0]}"
    if len(lines) > 1:
        message += "".join(f"\n  {line}" for line in lines[1:])
    raise BlockSpecError(message, block_id=first.block_id)


def resolve_signals(sim: Simulator, *, mode: ResolveMode = "auto") -> SignalResolution:
    """モデルの信号面 (shape + dtype) 解決を行う (公開エントリ。ADR-0079 §(1))。

    どんな入力でも例外を送出しない (SPEC-0027 AC-5):

    - build 失敗 (代数ループ / port shape 不整合 等) → ``dtype.build_failed``
    - 予期しない内部例外 → ``dtype.internal_error``

    Args:
        sim: 解決対象の ``Simulator``。モデル定義は変更しないが、full mode では
            ``_execution_order()`` 経由で run 経路と同一の build 副作用
            (mask 解決 / Goto-From 仮想エッジ確定 等) が起きる。この副作用は
            冪等で、run 結果は bit 単位で不変 (AC-3 テストで固定)。
        mode: ``"auto"`` (既定 — PythonFunction を含むモデルのみ static) /
            ``"full"`` / ``"static"`` の強制指定 (SPEC-0028 §5.1)。

    Returns:
        ``SignalResolution`` (ports / shapes / diagnostics / summary)。
    """
    try:
        return _resolve_impl(sim, mode=mode)
    except (AlgebraicLoopError, BlockSpecError) as exc:
        logger.debug("dtype.build_failed: %s", exc)
        return _empty_resolution(
            _diag(
                "dtype.build_failed",
                f"Model build failed before signal resolution: {exc}",
                block_id=getattr(exc, "block_id", None),
            )
        )
    except Exception as exc:  # noqa: BLE001 - AC-5 の受け皿 (SPEC-0027 §3.6)
        logger.warning("dtype.internal_error block_id=None code=dtype.internal_error: %r", exc)
        # 例外本文はクライアントに返さない (任意例外の受け皿のため、将来
        # OSError 等でサーバ内部パスが混入しうる)。詳細はサーバログのみ。
        # 一方 build_failed (AlgebraicLoopError / BlockSpecError) はモデル由来の
        # ドメイン情報だけで構成され既存 route でも露出しているため本文を返す。
        return _empty_resolution(
            _diag(
                "dtype.internal_error",
                f"Unexpected engine error ({type(exc).__name__}); details in the server log.",
            )
        )


def resolve_dtypes(sim: Simulator, *, mode: ResolveMode = "auto") -> SignalResolution:
    """``resolve_signals`` の互換 alias (SPEC-0027 / SPEC-0028 の公開名、ADR-0038)。"""
    return resolve_signals(sim, mode=mode)
