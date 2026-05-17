"""Block class registry (ADR-0019 §(1)).

サーバ起動時に ``pyflw.blocks`` / ``pyflw.subsystems`` 以下の ``Block`` サブクラスを
``pkgutil.walk_packages`` で列挙し、各クラスのメタデータ + default port shape を
組み立てた registry を構築する。

メタデータ取得方針 (ADR-0019 §(2) META-A の実用版):
  1. 各クラスに ``_block_category`` / ``_block_display_name`` / ``_block_icon``
     の class attribute があればそれを優先する
  2. 無ければ built-in 33 ブロック向けの中央テーブル ``_BUILTIN_METADATA`` を fallback
     として使う
  3. それも無ければ ``uncategorized`` カテゴリ + class 名から派生した default

これによりコア 33 クラスはコード変更なしで category / icon が解決でき、
かつサードパーティ拡張は ``_block_*`` class 属性で自己定義できる (= ADR-0019 §(2)
META-A の精神を尊重しつつ実装コストを抑える)。

v0.33.0: 旧 per-block color field を撤廃。category 増加時の palette 管理コスト
削減 + 色覚多様性配慮 + design system 整合のため。glyph 色は frontend 側で
slate-600 一色固定。
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from dataclasses import dataclass, field
from typing import Any

from ..core.block import Block
from ..core.persistence import (
    _DEFAULT_ALLOWED_PREFIXES,
    _extra_allowed_prefixes,
    block_type_path,
    to_json_value,
)
from ..exceptions import BlockSpecError

_logger = logging.getLogger("pyflw.registry")


@dataclass
class ParamSpec:
    """Block ``__init__`` の単一パラメータの仕様 (registry response の要素)。

    ``enum_values`` (v0.15.0 / ADR-0039 follow-up): ``str`` 型 param のうち、
    block class が ``_param_enums = {param_name: tuple[str, ...]}`` を class
    attribute として宣言している場合、その許容値を一覧で frontend に流す。
    frontend は ``<select>`` プルダウンで render する (= 自由入力でなく enum
    選択にして UX 改善 + 不正値混入防止)。``None`` のとき従来の ``<input>``。
    """

    name: str
    type: str
    default: Any | None = None
    has_default: bool = False
    description: str = ""
    enum_values: list[str] | None = None


@dataclass
class BlockMetadata:
    """1 つの Block class の registry エントリ (ADR-0019 §1.2、ADR-0021 §(5)、ADR-0028)。

    ADR-0028 §Decision §1: ``display_name`` / ``docstring_summary`` の en/ja 翻訳を
    ``display_name_i18n`` / ``docstring_summary_i18n`` に同梱する。既存
    ``display_name`` / ``docstring_summary`` は en コピーとして維持され、旧 frontend
    が壊れない (= 後方互換)。
    """

    type_path: str
    display_name: str
    category: str
    icon: str
    # v0.33.0: per-block の color フィールドを撤廃。
    # 旧版では category 単位で色を hardcode していたが、(1) category が
    # 増えたときの palette 管理コスト (2) 色覚多様性への配慮 (3) Property
    # Inspector 風 design system との整合 を理由に廃止。glyph 色は
    # frontend 側で slate-600 固定。
    docstring_summary: str
    docstring_full: str
    params_spec: list[ParamSpec]
    default_n_inputs: int
    default_n_outputs: int
    port_shapes_in_default: list[list[int]]
    port_shapes_out_default: list[list[int]]
    tags: list[str] = field(default_factory=list)
    # ADR-0021 §(5): GUI ドリルダウン / マスクパラメータ可否のヒント
    is_container: bool = False
    mask_capable: bool = False
    # ADR-0028: locale → field → str の翻訳テーブル。``_BLOCK_TRANSLATIONS`` 未登録の
    # type_path では空 dict (= 旧 ``display_name`` / ``docstring_summary`` のみ提供)。
    display_name_i18n: dict[str, str] = field(default_factory=dict)
    docstring_summary_i18n: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Built-in metadata table (ADR-0019 §(2))
# ---------------------------------------------------------------------------
#
# (category, display_name, icon) のタプル。
# class attribute (`_block_category` 等) が定義されていればそちらが優先。
# v0.33.0: 旧 4 番目要素 (= per-block color) を撤廃。BlockMetadata.color 自体を
# 削除したため、frontend 側の glyph は slate-600 一色で描画される。
_BUILTIN_METADATA: dict[str, tuple[str, str, str]] = {
    # sources
    "pyflw.blocks.sources.Constant": ("sources", "Constant", "sources.constant"),
    "pyflw.blocks.sources.Step": ("sources", "Step", "sources.step"),
    "pyflw.blocks.sources.Sine": ("sources", "Sine", "sources.sine"),
    "pyflw.blocks.sources.Ramp": ("sources", "Ramp", "sources.ramp"),
    "pyflw.blocks.sources.Clock": ("sources", "Clock", "sources.clock"),
    "pyflw.blocks.sources.PulseGenerator": ("sources", "Pulse Generator", "sources.pulse"),
    # math
    "pyflw.blocks.mathops.Gain": ("mathops", "Gain", "math.gain"),
    "pyflw.blocks.mathops.Sum": ("mathops", "Sum", "math.sum"),
    # v0.35.0: Add (= Sum の矩形版、signs 文字列で符号指定)
    "pyflw.blocks.mathops.Add": ("mathops", "Add", "math.add"),
    "pyflw.blocks.mathops.Product": ("mathops", "Product", "math.product"),
    "pyflw.blocks.mathops.Saturation": ("mathops", "Saturation", "math.saturation"),
    "pyflw.blocks.mathops.Abs": ("mathops", "Abs", "math.abs"),
    "pyflw.blocks.mathops.Sign": ("mathops", "Sign", "math.sign"),
    "pyflw.blocks.mathops.MinMax": ("mathops", "MinMax", "math.minmax"),
    "pyflw.blocks.mathops.Divide": ("mathops", "Divide", "math.divide"),
    # SPEC-0002 / ADR-0053 (v0.36.0): Phase 2 送り Math 系 5 ブロック第 1 弾
    "pyflw.blocks.mathops.MathFunction": ("mathops", "Math Function", "math.mathfunction"),
    "pyflw.blocks.mathops.TrigFunction": ("mathops", "Trig Function", "math.trigfunction"),
    "pyflw.blocks.mathops.DeadZone": ("mathops", "Dead Zone", "math.deadzone"),
    "pyflw.blocks.mathops.CompareToConstant": (
        "mathops",
        "Compare To Constant",
        "math.comparetoconstant",
    ),
    "pyflw.blocks.mathops.CompareToZero": (
        "mathops",
        "Compare To Zero",
        "math.comparetozero",
    ),
    # continuous
    "pyflw.blocks.continuous.Integrator": ("continuous", "Integrator", "cont.integrator"),
    "pyflw.blocks.continuous.Derivative": ("continuous", "Derivative", "cont.derivative"),
    "pyflw.blocks.continuous.TransferFunction": ("continuous", "Transfer Fcn", "cont.tf"),
    "pyflw.blocks.continuous.StateSpace": ("continuous", "State Space", "cont.ss"),
    "pyflw.blocks.continuous.MimoTransferFunction": (
        "continuous",
        "MIMO TF",
        "cont.mimo_tf",
    ),
    # discrete
    "pyflw.blocks.discrete.UnitDelay": ("discrete", "Unit Delay", "disc.unit_delay"),
    "pyflw.blocks.discrete.DiscreteIntegrator": (
        "discrete",
        "Discrete Integrator",
        "disc.integrator",
    ),
    "pyflw.blocks.discrete.ZeroOrderHoldDirect": ("discrete", "ZOH", "disc.zoh_direct"),
    "pyflw.blocks.discrete.RateTransition": (
        "discrete",
        "Rate Transition",
        "disc.rate_transition",
    ),
    "pyflw.blocks.discrete.DiscreteStateSpace": (
        "discrete",
        "Discrete State Space",
        "disc.ss",
    ),
    "pyflw.blocks.discrete.DiscreteTransferFunction": (
        "discrete",
        "Discrete Transfer Fcn",
        "disc.tf",
    ),
    # logic
    "pyflw.blocks.logic.RelationalOperator": ("logic", "Relational", "logic.relational"),
    "pyflw.blocks.logic.LogicalOperator": ("logic", "Logical", "logic.logical"),
    # routing
    "pyflw.blocks.routing.Switch": ("routing", "Switch", "routing.switch"),
    "pyflw.blocks.routing.Mux": ("routing", "Mux", "routing.mux"),
    "pyflw.blocks.routing.Demux": ("routing", "Demux", "routing.demux"),
    # sinks
    "pyflw.blocks.sinks.Scope": ("sinks", "Scope", "sinks.scope"),
    "pyflw.blocks.sinks.Display": ("sinks", "Display", "sinks.display"),
    "pyflw.blocks.sinks.XYGraph": ("sinks", "XY Graph", "sinks.xygraph"),
    "pyflw.blocks.sinks.Terminator": ("sinks", "Terminator", "sinks.terminator"),
    # subsystems
    "pyflw.subsystems.subsystem.Subsystem": (
        "subsystems",
        "Subsystem",
        "subsys.subsystem",
    ),
    "pyflw.subsystems.triggered.TriggeredSubsystem": (
        "subsystems",
        "Triggered Subsystem",
        "subsys.triggered",
    ),
    "pyflw.subsystems.ports.Inport": ("subsystems", "Inport", "subsys.inport"),
    "pyflw.subsystems.ports.Outport": ("subsystems", "Outport", "subsys.outport"),
}


# ``cls()`` を引数なしで呼ぶと失敗するクラスの default factory 引数 (ADR-0019 §Risks #2)。
# class attribute ``_default_factory_args`` でも上書き可能。
_BUILTIN_DEFAULT_ARGS: dict[str, dict[str, Any]] = {
    "pyflw.blocks.continuous.TransferFunction": {
        "numerator": [1.0],
        "denominator": [1.0, 1.0],
    },
    "pyflw.blocks.continuous.StateSpace": {
        "A": [[0.0]],
        "B": [[1.0]],
        "C": [[1.0]],
        "D": [[0.0]],
    },
    "pyflw.blocks.continuous.MimoTransferFunction": {
        "numerators": [[[1.0]]],
        "denominator": [1.0, 1.0],
    },
    "pyflw.blocks.discrete.DiscreteStateSpace": {
        "A": [[0.0]],
        "B": [[1.0]],
        "C": [[1.0]],
        "D": [[0.0]],
        "sample_time": 0.1,
    },
    "pyflw.blocks.discrete.DiscreteTransferFunction": {
        "numerator": [1.0],
        "denominator": [1.0, 1.0],
        "sample_time": 0.1,
    },
    "pyflw.blocks.discrete.UnitDelay": {"sample_time": 0.1},
    "pyflw.blocks.discrete.DiscreteIntegrator": {"sample_time": 0.1},
    "pyflw.blocks.discrete.ZeroOrderHoldDirect": {"sample_time": 0.1},
    # ADR-0036: RateTransition は input_sample_time / output_sample_time が
    # 必須引数で同値禁止のため、明示の異なるレート組み合わせを default に
    "pyflw.blocks.discrete.RateTransition": {
        "input_sample_time": 0.1,
        "output_sample_time": 0.2,
    },
    "pyflw.blocks.routing.Mux": {"n": 2},
    "pyflw.blocks.routing.Demux": {"n": 2},
    "pyflw.subsystems.ports.Inport": {"port_idx": 0},
    "pyflw.subsystems.ports.Outport": {"port_idx": 0},
    # ADR-0039 (v2.0): Subsystem / TriggeredSubsystem の n_inputs / n_outputs は
    # 派生 property に格上げ (= コンストラクタ引数廃止)。``_default_factory_args``
    # も不要 — 第 1 試行の TypeError → 第 2 試行 ``cls()`` という無駄な経路を避ける
    # ため、エントリ自体を削除する。
}


# ---------------------------------------------------------------------------
# Walk + introspect
# ---------------------------------------------------------------------------


def _format_annotation(ann: Any) -> str:
    """``inspect`` の annotation を string label に変換 (ADR-0019 §Open Question 4)。"""
    if ann is inspect.Parameter.empty:
        return "any"
    if isinstance(ann, type):
        return ann.__name__
    return str(ann).replace("typing.", "")


def _build_params_spec(cls: type) -> list[ParamSpec]:
    """``cls.__init__`` のシグネチャから ``params_spec`` を構築する。

    ``self`` / ``id`` / ``name`` / ``*`` / ``**kwargs`` 等は除外。default 値が
    JSON-serializable でない (= `to_json_value` が raise) 場合は ``default=None``
    に fallback (= ブロック全体は registry に残す)。

    シグネチャに default が無い required param (``Mux(n: int)``,
    ``Subsystem(n_inputs: int, n_outputs: int)`` 等) は、``_default_factory_args``
    class attribute または中央テーブル ``_BUILTIN_DEFAULT_ARGS`` の値を
    ``has_default=True`` の代替として使う。これがないとフロント側で「ドロップ時の
    params が 0 になる」事故 (= ``Mux(n=0)`` で配置されてしまう) が起きる。
    """
    sig = inspect.signature(cls)
    type_path = block_type_path(cls)
    factory_args: dict[str, Any] = (
        getattr(cls, "_default_factory_args", None) or _BUILTIN_DEFAULT_ARGS.get(type_path) or {}
    )
    # ADR-0039 follow-up (v0.15.0): block class が ``_param_enums`` を class attribute
    # として宣言していれば、それを ParamSpec.enum_values に流し込む。frontend
    # ParameterPanel は enum_values あれば ``<select>`` で render する。
    param_enums: dict[str, tuple[str, ...]] = getattr(cls, "_param_enums", {}) or {}
    out: list[ParamSpec] = []
    for name, param in sig.parameters.items():
        if name in ("self", "id", "name"):
            continue
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        sig_has_default = param.default is not inspect.Parameter.empty
        has_default = sig_has_default
        default: Any = None
        if sig_has_default and param.default is not None:
            try:
                default = to_json_value(param.default)
            except Exception:  # noqa: BLE001
                _logger.debug(
                    "registry: cannot serialize default for %s.%s; using None",
                    cls.__name__,
                    name,
                )
                default = None
        elif not sig_has_default and name in factory_args:
            # required param に factory fallback がある場合は has_default 扱い。
            try:
                default = to_json_value(factory_args[name])
                has_default = True
            except Exception:  # noqa: BLE001
                _logger.debug(
                    "registry: cannot serialize factory default for %s.%s; using None",
                    cls.__name__,
                    name,
                )
        enum_values: list[str] | None = None
        if name in param_enums:
            enum_values = list(param_enums[name])
        out.append(
            ParamSpec(
                name=name,
                type=_format_annotation(param.annotation),
                has_default=has_default,
                default=default,
                enum_values=enum_values,
            )
        )
    return out


def _instantiate_for_introspection(cls: type) -> Block | None:
    """``cls`` の default factory を試行する。失敗時は ``None``。

    1. class attr ``_default_factory_args``
    2. 中央テーブル ``_BUILTIN_DEFAULT_ARGS``
    3. 引数なし ``cls()``
    の順に試す。``BlockSpecError`` / ``TypeError`` / ``ValueError`` は捕捉して None。
    """
    type_path = block_type_path(cls)
    factory_args: dict[str, Any] | None = getattr(cls, "_default_factory_args", None)
    if factory_args is None:
        factory_args = _BUILTIN_DEFAULT_ARGS.get(type_path)
    candidates: list[dict[str, Any]] = []
    if factory_args is not None:
        candidates.append(factory_args)
    candidates.append({})
    for kwargs in candidates:
        try:
            return cls(**kwargs)  # type: ignore[no-any-return]
        except (BlockSpecError, TypeError, ValueError) as e:
            _logger.debug(
                "registry: default factory failed for %s with %r: %s",
                type_path,
                kwargs,
                e,
            )
    return None


def _derive_tags(blk: Block | None) -> list[str]:
    """default インスタンスから tag 集合を派生する (ADR-0019 §1.2)。"""
    tags: list[str] = []
    if blk is None:
        return ["unknown"]
    sm_b = any(s != () for s in blk.port_shapes_in) or any(s != () for s in blk.port_shapes_out)
    tags.append("sm_b" if sm_b else "sm_a")
    if blk.n_states > 0:
        tags.append("stateful")
    if blk.n_inputs == 0 and blk.n_outputs > 0:
        tags.append("source")
    if blk.n_inputs > 0 and blk.n_outputs == 0:
        tags.append("sink")
    return tags


def _resolve_metadata_fallback(cls: type) -> tuple[str, str, str]:
    """class attribute → built-in テーブル → default の順でメタを解決する。

    v0.33.0: 旧 4th 戻り値 (per-block color) を撤廃。詳細は BlockMetadata の
    docstring 参照。
    """
    type_path = block_type_path(cls)
    fallback = _BUILTIN_METADATA.get(type_path)
    category = getattr(cls, "_block_category", None) or (
        fallback[0] if fallback else "uncategorized"
    )
    display_name = getattr(cls, "_block_display_name", None) or (
        fallback[1] if fallback else cls.__name__
    )
    icon = getattr(cls, "_block_icon", None) or (fallback[2] if fallback else "default")
    return category, display_name, icon


def build_metadata(cls: type) -> BlockMetadata:
    """1 つの Block サブクラスから ``BlockMetadata`` を構築する (ADR-0019、ADR-0028)。"""
    # 遅延 import で循環回避 (subsystem.py は core.block / core.persistence に依存)
    from ..subsystems import Subsystem
    from .registry_translations import SUPPORTED_LOCALES, get_translations

    type_path = block_type_path(cls)
    category, display_name, icon = _resolve_metadata_fallback(cls)
    docstring = inspect.getdoc(cls) or ""
    docstring_summary = docstring.split("\n\n", 1)[0].split("\n")[0] if docstring else ""

    blk = _instantiate_for_introspection(cls)

    # ADR-0021 §(5): Subsystem サブクラスは drill-down + mask の対象。
    is_container = issubclass(cls, Subsystem)

    tags = _derive_tags(blk)
    if is_container and "container" not in tags:
        tags.append("container")

    # ADR-0028: registry_translations の i18n テーブルを参照。``en`` 値が
    # 登録されていればそれを ``display_name`` / ``docstring_summary`` (= 旧フィールド、
    # en コピーとして残す) にも反映 (= 後方互換 + en 表示の正規化)。3rd-party 拡張
    # 等で未登録の場合は class attribute / inspect.getdoc() のフォールバックを使う。
    translations = get_translations(type_path)
    display_name_i18n: dict[str, str] = {}
    docstring_summary_i18n: dict[str, str] = {}
    for locale in SUPPORTED_LOCALES:
        entry = translations.get(locale)
        if not entry:
            continue
        if "display_name" in entry:
            display_name_i18n[locale] = entry["display_name"]
        if "docstring_summary" in entry:
            docstring_summary_i18n[locale] = entry["docstring_summary"]

    # 旧フィールド (= 後方互換、en コピー) を i18n テーブル en で正規化する。
    if "en" in display_name_i18n:
        display_name = display_name_i18n["en"]
    if "en" in docstring_summary_i18n:
        docstring_summary = docstring_summary_i18n["en"]

    return BlockMetadata(
        type_path=type_path,
        display_name=display_name,
        category=category,
        icon=icon,
        docstring_summary=docstring_summary,
        docstring_full=docstring,
        params_spec=_build_params_spec(cls),
        default_n_inputs=blk.n_inputs if blk else 0,
        default_n_outputs=blk.n_outputs if blk else 0,
        port_shapes_in_default=([list(s) for s in blk.port_shapes_in] if blk else []),
        port_shapes_out_default=([list(s) for s in blk.port_shapes_out] if blk else []),
        tags=tags,
        is_container=is_container,
        mask_capable=is_container,  # Phase 3 では Subsystem のみ mask 宣言可
        display_name_i18n=display_name_i18n,
        docstring_summary_i18n=docstring_summary_i18n,
    )


def _walk_block_classes() -> list[type]:
    """allowlist (`pyflw.*` + 拡張 prefix) 配下の ``Block`` サブクラスを収集する。"""
    found: list[type] = []
    seen: set[type] = set()
    prefixes = list(_DEFAULT_ALLOWED_PREFIXES) + sorted(_extra_allowed_prefixes)

    for prefix in prefixes:
        # prefix 末尾 "." を取り除いて root module を import
        root_name = prefix.rstrip(".")
        try:
            root = importlib.import_module(root_name)
        except ImportError as e:
            _logger.warning("registry: cannot import root module %r for walk: %s", root_name, e)
            continue
        if not hasattr(root, "__path__"):
            # 単一ファイル module → そのまま class 列挙
            modules: list[str] = [root_name]
        else:
            modules = [root_name]
            for module_info in pkgutil.walk_packages(root.__path__, prefix=root_name + "."):
                modules.append(module_info.name)

        for mod_name in modules:
            try:
                mod = importlib.import_module(mod_name)
            except Exception as e:  # noqa: BLE001
                _logger.warning("registry: skipping module %r (import failed: %s)", mod_name, e)
                continue
            for _name, obj in inspect.getmembers(mod, inspect.isclass):
                if (
                    issubclass(obj, Block)
                    and obj is not Block
                    and obj.__module__ == mod_name
                    and obj not in seen
                ):
                    found.append(obj)
                    seen.add(obj)
    return found


def build_block_registry() -> list[BlockMetadata]:
    """allowlist 配下の Block サブクラスから registry を構築する。"""
    classes = _walk_block_classes()
    registry: list[BlockMetadata] = []
    for cls in classes:
        try:
            registry.append(build_metadata(cls))
        except Exception as e:  # noqa: BLE001
            _logger.warning("registry: skipping %r (metadata build failed: %s)", cls.__name__, e)
    # canonical 順 = type_path 昇順 (= 起動 ↔ テストの安定性)
    registry.sort(key=lambda m: m.type_path)
    return registry


def metadata_to_dict(
    meta: BlockMetadata, *, include_full_docstring: bool = False
) -> dict[str, Any]:
    """``BlockMetadata`` を JSON-serializable dict に変換する (ADR-0019、ADR-0028)。"""
    out: dict[str, Any] = {
        "type_path": meta.type_path,
        "display_name": meta.display_name,
        # ADR-0028: i18n フィールドを REST 同梱。frontend (blockI18n.ts) が
        # currentLanguage() で値を選択する。空 dict の場合 frontend は旧
        # ``display_name`` / ``docstring_summary`` にフォールバックする。
        "display_name_i18n": dict(meta.display_name_i18n),
        "category": meta.category,
        "icon": meta.icon,
        "docstring_summary": meta.docstring_summary,
        "docstring_summary_i18n": dict(meta.docstring_summary_i18n),
        "params_spec": [
            {
                "name": p.name,
                "type": p.type,
                "has_default": p.has_default,
                "default": p.default,
                "description": p.description,
                # ADR-0039 follow-up (v0.15.0): enum 候補が指定されている param のみ
                # 流す。``None`` のときキー自体を出さず、payload を膨らませない。
                **({"enum_values": p.enum_values} if p.enum_values is not None else {}),
            }
            for p in meta.params_spec
        ],
        "default_n_inputs": meta.default_n_inputs,
        "default_n_outputs": meta.default_n_outputs,
        "port_shapes_in_default": meta.port_shapes_in_default,
        "port_shapes_out_default": meta.port_shapes_out_default,
        "tags": meta.tags,
        "is_container": meta.is_container,
        "mask_capable": meta.mask_capable,
    }
    if include_full_docstring:
        out["docstring_full"] = meta.docstring_full
    return out


# ---------------------------------------------------------------------------
# resolve_port_shapes (POST /api/v1/blocks/resolve-port-shapes)
# ---------------------------------------------------------------------------


@dataclass
class ResolvedPortShapes:
    n_inputs: int
    n_outputs: int
    port_shapes_in: list[list[int]]
    port_shapes_out: list[list[int]]


def resolve_port_shapes(type_path: str, params: dict[str, Any]) -> ResolvedPortShapes:
    """与えた params で ``cls(**params)`` した結果の port shapes を返す。

    Args:
        type_path: ``"pyflw.blocks.Gain"`` 等の dotted path。
        params: ``__init__`` に渡す kwargs。

    Returns:
        ``ResolvedPortShapes``。

    Raises:
        BlockSpecError: ``cls`` の解決失敗、または ``__init__`` での例外。
    """
    from ..core.persistence import resolve_block_class

    cls = resolve_block_class(type_path)
    try:
        instance = cls(**params)
    except (TypeError, ValueError, BlockSpecError) as e:
        raise BlockSpecError(f"Cannot instantiate {type_path!r} with params {params!r}: {e}") from e
    return ResolvedPortShapes(
        n_inputs=instance.n_inputs,
        n_outputs=instance.n_outputs,
        port_shapes_in=[list(s) for s in instance.port_shapes_in],
        port_shapes_out=[list(s) for s in instance.port_shapes_out],
    )
