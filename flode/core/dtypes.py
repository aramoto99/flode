"""SM-D Stage 0: 影の型伝播 (shadow dtype propagation) エンジン。

SPEC-0027 / ADR-0077 (D-1〜D-8)。モデルの各ポートが「SM-D 完成時に流れて
いるべき numpy dtype」を **実行せずに** 静的推論する。Stage 0 の鉄則:

- **挙動不変** (SPEC-0027 AC-1〜AC-6)。本モジュールは Simulator の実行経路から
  一切呼ばれず、読み取りのみ行う。診断が ``error`` でも build / run は止めない
- 型規則の SSOT は本モジュール 1 箇所 (ADR-0077 §データ整合性 1)。
  ``flode.blocks`` / ``flode.core.block`` には規則を書かない (実装計画 §3.1)
- 依存は stdlib + numpy のみ。ブロッククラスは **クラス名 (MRO 走査)** で分類し、
  ``flode.blocks`` / ``flode.subsystems`` を import しない

二経路 (実装計画「矛盾 1」の解決):

- **full mode**: ``PythonFunction`` を含まないモデル。``sim._execution_order()``
  を使い、Goto/From 解決・shape 検査・代数ループ検出を享受する
- **static mode**: ``PythonFunction`` を含むモデル。``_build()`` が
  ユーザーコードを exec するため (pythonfunc.py) **一切 build せず**、
  登録順で不動点反復する。Goto/From は未解決 → ``unknown``、
  診断 ``dtype.static_fallback`` で縮退を明示する。これにより
  「エンジンはユーザーコードを実行しない」を構造的に保証する
"""

from __future__ import annotations

import logging
import math
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal

import numpy as np
import numpy.typing as npt

from ..exceptions import AlgebraicLoopError, BlockSpecError

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

#: REST payload の schema 識別子 (SPEC-0027 §5.2)。
SCHEMA_VERSION: Final[str] = "dtypes.v1"

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
            flat_list = [
                _float_to_int_scalar(float(v), info) for v in np.ravel(arr)
            ]
            return np.asarray(flat_list, dtype=dt).reshape(arr.shape)
        # 整数/bool → 整数: numpy の astype はビット切り出し = モジュラ wrap で決定的
        return arr.astype(dt)
    # float64 (拡大変換)
    return arr.astype(dt)


# ---------------------------------------------------------------------------
# 診断 (SPEC-0027 §3.6 + 実装計画の dtype.static_fallback)
# ---------------------------------------------------------------------------

#: code → severity の対応表。severity は「Stage 1 でこの診断が実エラーに
#: 昇格するか」の予告 (Stage 0 では error でも build を止めない、Q4)。
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
}


@dataclass(frozen=True)
class DTypeDiagnostic:
    """型解決の構造化診断 1 件 (SPEC-0027 §3.6)。

    ``message`` は en 固定のフォールバック (i18n は ``code`` をキーに
    frontend 側で行う、ADR-0028)。
    """

    severity: str
    code: str
    message: str
    block_id: str | None = None
    direction: str | None = None
    port_index: int | None = None
    from_dtype: str | None = None
    to_dtype: str | None = None

    def to_payload(self) -> dict[str, Any]:
        """REST 用の JSON 互換 dict を返す。"""
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "block_id": self.block_id,
            "direction": self.direction,
            "port_index": self.port_index,
            "from_dtype": self.from_dtype,
            "to_dtype": self.to_dtype,
        }


@dataclass(frozen=True)
class DTypeSummary:
    """解決結果の集計 (ADR-0077 §再考トリガー 1 の判定材料)。"""

    total_ports: int
    by_dtype: Mapping[str, int]
    unresolved: int
    non_float_ports: int

    def to_payload(self) -> dict[str, Any]:
        """REST 用の JSON 互換 dict を返す。"""
        return {
            "total_ports": self.total_ports,
            "by_dtype": dict(self.by_dtype),
            "unresolved": self.unresolved,
            "non_float_ports": self.non_float_ports,
        }


@dataclass(frozen=True)
class DTypeResolution:
    """型解決の結果 (不変)。``ports`` は ``(block_id, direction, port_index)`` キー。"""

    ports: Mapping[PortKey, str]
    diagnostics: tuple[DTypeDiagnostic, ...]
    summary: DTypeSummary

    def out_dtype(self, block_id: str, port_index: int) -> str:
        """出力ポートの推論 dtype を返す (未知キーは ``KeyError``)。"""
        return self.ports[(block_id, "out", port_index)]

    def in_dtype(self, block_id: str, port_index: int) -> str:
        """入力ポートの推論 dtype (D-4 自動昇格後) を返す。"""
        return self.ports[(block_id, "in", port_index)]

    def to_payload(self) -> dict[str, Any]:
        """REST レスポンス (``dtypes.v1``) を返す。ports は決定的 sort。"""
        return {
            "schema_version": SCHEMA_VERSION,
            "ports": [
                {
                    "block_id": key[0],
                    "direction": key[1],
                    "port_index": key[2],
                    "dtype": self.ports[key],
                }
                for key in sorted(self.ports)
            ],
            "diagnostics": [d.to_payload() for d in self.diagnostics],
            "summary": self.summary.to_payload(),
        }


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

#: クラス名 → 分類。lookup は MRO 走査 (サブクラスは親の規則を継承)。
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

#: promote_except_control の制御入力ポート index (出力 dtype に寄与しない)。
_CONTROL_PORT_INDEX: Final[Mapping[str, int]] = {"Switch": 1, "MultiportSwitch": 0}

#: SPEC-0026 の ``output_type`` (値の意味論) → shadow dtype の写像 (Q1:
#: 実行意味を再解釈するのではなく推論のヒントとしてのみ参照)。
_OUTPUT_TYPE_MAP: Final[Mapping[str, str]] = {
    "float": "float64",
    "int": "int64",
    "bool": "bool",
}


def _block_id(block: Block) -> str:
    """突合キー用の block id (Simulator 登録済みなら必ず str)。"""
    bid = block.id
    return bid if bid is not None else "<unassigned>"


def _mro_names(block: Block) -> tuple[str, ...]:
    """block のクラス MRO 上のクラス名一覧。"""
    return tuple(cls.__name__ for cls in type(block).__mro__)


def _classify(block: Block) -> tuple[Category, bool]:
    """ブロックを分類する。戻り値は ``(category, rule_missing)``。"""
    for name in _mro_names(block):
        category = _CLASSIFICATION.get(name)
        if category is not None:
            return category, False
    return "promote", True


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
    """promote_except_control の制御入力 index (該当なしは None)。"""
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
    ``False`` なら ``run()`` は解決器を呼ばず従来経路へ落ちる (AC-1 の構造的保証)。
    ネスト Subsystem 内部は見ない (Q6: island のため内部宣言は Stage 1 では効かない)。
    """
    for b in sim.blocks:
        if str(b._params.get("dtype", "auto")) != "auto":
            return True
    return False


def reject_nested_dtype_declarations(sim: Simulator) -> None:
    """Subsystem 内部の ``dtype`` 宣言を fail-closed に拒否する (security MUST-1)。

    Stage 1 の pre-filter (`has_declared_dtype`) は root のみを見るため、
    Subsystem 内部の宣言は解決器を通らない。一方でブロック自身の ``output()``
    は ``dtype`` を単体で適用するため、放置すると「予測 (float64 island) と
    実行値 (内部で wrap 済み) が無警告で乖離」する — AC-2 の破れ。
    Stage 1 では内部宣言そのものを未対応としてエラーにする
    (内部の型伝播は Stage 2、SPEC-0028 Q6)。

    Raises:
        BlockSpecError: ネストしたブロックに ``dtype != "auto"`` がある。
    """

    def _scan(blocks: Iterable[Block], owner_id: str | None) -> None:
        for b in blocks:
            if owner_id is not None and str(b._params.get("dtype", "auto")) != "auto":
                raise BlockSpecError(
                    f"dtype declaration on block {b.id!r} inside Subsystem "
                    f"{owner_id!r} is not supported in this release: the "
                    "Subsystem boundary is a float64 island (SPEC-0028 Q6) and "
                    "inner declarations would silently diverge from the "
                    "resolved dtypes. Move the Cast/Constant with dtype to the "
                    "top level, or remove its dtype.",
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
# 解決アルゴリズム (SPEC-0027 §3.3)
# ---------------------------------------------------------------------------

DiagSink = Callable[[DTypeDiagnostic], None]


def _diag(code: str, message: str, **kwargs: Any) -> DTypeDiagnostic:
    """severity を code から引いて診断を組み立てる。"""
    return DTypeDiagnostic(
        severity=_SEVERITY_BY_CODE[code], code=code, message=message, **kwargs
    )


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


def _gather_raw_inputs(block: Block, out_of: Mapping[PortKey, str]) -> list[str]:
    """各入力ポートの上流出力 dtype (未接続 / 未解決は unknown)。

    From ブロック (full mode で ``_resolved_goto`` 解決済み) は対応 Goto の
    入力 dtype を仮想入力として持つ。
    """
    raw: list[str] = []
    for i in range(block.n_inputs):
        src = block.input_sources[i]
        if src is None:
            raw.append(UNKNOWN)
        else:
            src_block, src_idx = src
            raw.append(out_of.get((_block_id(src_block), "out", src_idx), UNKNOWN))
    resolved_goto = getattr(block, "_resolved_goto", None)
    if resolved_goto is not None and resolved_goto.n_inputs > 0:
        # From の仮想入力 = 対応 Goto の上流出力 (反復中の out_of には
        # out ポートしか無いため、Goto の input_sources を直接辿る)。
        # Note: static mode では通常未設定 → unknown だが、同一 Simulator で
        # 事前に run() 等 (正当な build) を済ませていると _resolved_goto が
        # 残存し、static mode でも Goto/From が解決されることがある (無害)。
        goto_src = resolved_goto.input_sources[0]
        if goto_src is None:
            raw.append(UNKNOWN)
        else:
            raw.append(
                out_of.get((_block_id(goto_src[0]), "out", goto_src[1]), UNKNOWN)
            )
    return raw


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
        # Stage 1 (SPEC-0028 Q1): 新 param `dtype` が最優先。"auto" 以外は
        # 宣言そのものが出力 dtype (実変換、恒等ではない)。
        declared = str(block._params.get("dtype", "auto"))
        if declared != "auto":
            return [declared] * n_out
        output_type = block._params.get("output_type", "float")
        mapped = _OUTPUT_TYPE_MAP.get(str(output_type), "float64")
        if str(output_type) == "float" and block.n_inputs > 0:
            # Cast("float") は恒等 (SPEC-0026 §確定事項 2) → 入力 pass-through
            return [_promote_many(in_dtypes, sink, _block_id(block))] * n_out
        return [mapped] * n_out
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


ResolveMode = Literal["auto", "full", "static"]


def _resolve_impl(sim: Simulator, *, mode: ResolveMode = "auto") -> DTypeResolution:
    """二経路の振り分け (例外の診断化は ``resolve_dtypes`` 側)。

    - **full mode** = Stage 1 意味論 (SPEC-0028): opaque は float64 island (Q6)、
      収束後の unknown は float64 へ materialize (Q5 = 全域性 AC-3)
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
        # (REST 経路では resolve_dtypes の catch-all が dtype.build_failed に変換)
        reject_nested_dtype_declarations(sim)
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


def _resolve_graph(
    sim: Simulator,
    blocks: list[Block],
    order: list[Block],
    *,
    island: bool,
    static: bool,
) -> DTypeResolution:
    """不動点反復 + 最終パスの本体。``island`` = Stage 1 意味論 (Q5/Q6/Q7)。"""
    diagnostics: list[DTypeDiagnostic] = []
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
    for b in blocks:
        for j in range(b.n_outputs):
            out_of[(_block_id(b), "out", j)] = UNKNOWN

    max_iterations = 2 * len(blocks) + _ITERATION_MARGIN
    converged = False
    for _ in range(max_iterations):
        changed = False
        for b in order:
            raw = _gather_raw_inputs(b, out_of)
            category, _missing = _classify(b)
            required = _required_input_dtype(b, island=island)
            in_dtypes = _apply_input_requirement(b, raw, None, required)
            for j, d in enumerate(
                _infer_outputs(b, category, in_dtypes, None, island=island)
            ):
                key = (_block_id(b), "out", j)
                if out_of[key] != d:
                    out_of[key] = d
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

    # --- Q5 materialize (full mode のみ): 収束後に残った unknown を float64 へ ---
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

    # --- 最終パス: in ポート確定 + 診断収集 ---
    sink: DiagSink = diagnostics.append
    ports: dict[PortKey, str] = dict(out_of)
    for b in order:
        raw = _gather_raw_inputs(b, out_of)
        category, rule_missing = _classify(b)
        required = _required_input_dtype(b, island=island)
        in_dtypes = _apply_input_requirement(b, raw, sink, required)
        # 仮想入力 (From の Goto 参照) は in ポートとして数えない
        for i in range(b.n_inputs):
            d_in = in_dtypes[i]
            if b.input_sources[i] is None:
                sink(
                    _diag(
                        "dtype.unresolved",
                        f"Input {_block_id(b)!r}.in[{i}] is unconnected; "
                        "its dtype is unknown.",
                        block_id=_block_id(b),
                        direction="in",
                        port_index=i,
                    )
                )
                if island and d_in == UNKNOWN:
                    # Q5: 未接続入力もゼロ埋め実行のため float64 (要求があれば要求)
                    d_in = required if required is not None else "float64"
            ports[(_block_id(b), "in", i)] = d_in
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
        _infer_outputs(b, category, in_dtypes, sink, island=island)

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
    summary = DTypeSummary(
        total_ports=len(ports),
        by_dtype=by_dtype,
        unresolved=unresolved,
        non_float_ports=non_float,
    )
    return DTypeResolution(
        ports=ports, diagnostics=tuple(diagnostics), summary=summary
    )


def _empty_resolution(diagnostic: DTypeDiagnostic) -> DTypeResolution:
    """build 失敗 / 内部エラー時の空結果。"""
    return DTypeResolution(
        ports={},
        diagnostics=(diagnostic,),
        summary=DTypeSummary(
            total_ports=0, by_dtype={}, unresolved=0, non_float_ports=0
        ),
    )


#: 実行不能を意味する診断 code (severity error に加えて実行時は致命扱い、SPEC-0028 §3.5)。
_FATAL_EXECUTION_CODES: Final[frozenset[str]] = frozenset(
    {
        "dtype.narrowing_required",
        "dtype.out_of_vocabulary",
        "dtype.iteration_limit",
    }
)


def resolve_for_execution(sim: Simulator) -> DTypeResolution:
    """実行用の型解決 (``run()`` 経路、SPEC-0028 §3.2 / §3.4)。

    常に full mode で解決し、error 級または実行不能を意味する診断を
    ``BlockSpecError`` (ADR-0056、``block_id`` 付き) に昇格する。build 例外
    (代数ループ等) はそのまま伝播する — dtype 宣言モデルは型解決の成功が
    実行の前提であり、Stage 0 の「例外を握り潰す」AC-5 は適用しない。
    """
    res = _resolve_impl(sim, mode="full")
    for d in res.diagnostics:
        if d.severity == "error" or d.code in _FATAL_EXECUTION_CODES:
            raise BlockSpecError(
                f"dtype resolution failed: [{d.code}] {d.message}",
                block_id=d.block_id,
            )
    return res


def resolve_dtypes(sim: Simulator, *, mode: ResolveMode = "auto") -> DTypeResolution:
    """モデルの型解決を行う (公開エントリ。SPEC-0027 / SPEC-0028)。

    どんな入力でも例外を送出しない (SPEC-0027 AC-5):

    - build 失敗 (代数ループ / port shape 不整合 等) → ``dtype.build_failed``
    - 予期しない内部例外 → ``dtype.internal_error``

    Args:
        sim: 解決対象の ``Simulator``。モデル定義は変更しないが、full mode では
            ``_execution_order()`` 経由で run 経路と同一の build 副作用
            (mask 解決 / Goto-From 仮想エッジ確定 等) が起きる。この副作用は
            冪等で、run 結果は bit 単位で不変 (AC-3 テストで固定)。

    Args (追加):
        mode: ``"auto"`` (既定 — PythonFunction を含むモデルのみ static) /
            ``"full"`` / ``"static"`` の強制指定 (SPEC-0028 §5.1)。

    Returns:
        ``DTypeResolution`` (ports / diagnostics / summary)。
    """
    try:
        return _resolve_impl(sim, mode=mode)
    except (AlgebraicLoopError, BlockSpecError) as exc:
        logger.debug("dtype.build_failed: %s", exc)
        return _empty_resolution(
            _diag(
                "dtype.build_failed",
                f"Model build failed before dtype resolution: {exc}",
                block_id=getattr(exc, "block_id", None),
            )
        )
    except Exception as exc:  # noqa: BLE001 - AC-5 の受け皿 (SPEC-0027 §3.6)
        logger.warning(
            "dtype.internal_error block_id=None code=dtype.internal_error: %r", exc
        )
        # 例外本文はクライアントに返さない (任意例外の受け皿のため、将来
        # OSError 等でサーバ内部パスが混入しうる)。詳細はサーバログのみ。
        # 一方 build_failed (AlgebraicLoopError / BlockSpecError) はモデル由来の
        # ドメイン情報だけで構成され既存 route でも露出しているため本文を返す。
        return _empty_resolution(
            _diag(
                "dtype.internal_error",
                f"Unexpected engine error ({type(exc).__name__}); "
                "details in the server log.",
            )
        )
