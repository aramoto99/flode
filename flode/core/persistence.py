"""JSON 永続化ヘルパー (ADR-0008)。

``Simulator.save`` / ``Simulator.load`` の内部実装と、ブロック type の動的解決、
パラメータの JSON-serializable 変換、``schema_version`` migration をまとめる。

Phase 2 では ``schema_version = "0.1"`` のみサポート。Subsystem 導入時 (ADR-0009)
に ``"0.2"`` を追加し、``_MIGRATIONS`` registry に変換関数を登録する。
"""

from __future__ import annotations

import importlib
import logging
import math
import numbers
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import numpy as np

from ..exceptions import (
    ModelLoadError,
    ModelSerializationError,
    SchemaVersionError,
    UnknownBlockTypeError,
)
from .identifiers import normalize_block_id

if TYPE_CHECKING:
    from .block import Block


CURRENT_SCHEMA_VERSION = "0.10"
# 「migration を通さずそのまま受け入れるバージョン」の一覧。CURRENT のみを置く。
# 旧バージョン (e.g. "0.1") は ``_MIGRATIONS`` 経由で常に CURRENT に変換される。
# 将来 "0.3" を CURRENT にするとき、"0.2" を SUPPORTED に残せば追加の migration
# 処理を介さずに受け入れる挙動が選べる。
SUPPORTED_SCHEMA_VERSIONS = (CURRENT_SCHEMA_VERSION,)

# ADR-0020 §(1): layout entry の型。block_id → {"x": float, "y": float}。
# `LayoutDict` = レイアウト全体 (top-level または Subsystem 内部の `params.layout`)。
# v0.15.0: optional ``"flipped": bool`` を許容 (= リファレンスツールの Flip Block 相当)。
LayoutDict = dict[str, dict[str, float | bool]]


# allowlist: ロード時にここで列挙した module prefix のいずれかに属する class のみ
# 解決を許可する (任意の `os.system` 等を import するセキュリティリスクを避ける)。
# サードパーティ拡張は ``register_block_module(prefix)`` で追加する。
_DEFAULT_ALLOWED_PREFIXES: tuple[str, ...] = ("flode.",)
_extra_allowed_prefixes: set[str] = set()


def register_block_module(prefix: str) -> None:
    """``Simulator.load`` でブロック class 解決を許可する追加 module prefix を登録する。

    例: ``register_block_module("myapp.blocks.")`` を呼んでおくと、JSON 内の
    ``"type": "myapp.blocks.MyBlock"`` がロード可能になる。

    Args:
        prefix: ``importlib.import_module`` に渡す module 名の prefix
            (例: ``"myapp."``)。末尾の ``"."`` を含めて指定する。
    """
    if not isinstance(prefix, str) or not prefix:
        raise ModelLoadError(f"Module prefix must be a non-empty string, got {prefix!r}")
    _extra_allowed_prefixes.add(prefix)


def reset_block_module_allowlist() -> None:
    """``register_block_module`` で追加した prefix をすべてクリアする (テスト用)。"""
    _extra_allowed_prefixes.clear()


def _is_allowed_module(module_name: str) -> bool:
    if any(module_name.startswith(p) for p in _DEFAULT_ALLOWED_PREFIXES):
        return True
    return any(module_name.startswith(p) for p in _extra_allowed_prefixes)


def parse_t_end(raw: Any) -> float:
    """``simulator.t_end`` 入力値を ``float`` (有限値または ``math.inf``) に変換する。

    ADR-0042 §論点 4 / §論点 7-A: JSON 永続化は前方互換のため
    ``"inf"`` 文字列リテラル単一を採用。本関数は **case-insensitive で
    ``"inf"`` のみ** を受け入れ、``"+inf"`` / ``"-inf"`` / ``"infinity"``
    / ``"∞"`` / ``"NaN"`` 等は ``ModelLoadError`` で拒否する。

    Args:
        raw: ``int`` / ``float`` / ``str``。``bool`` は弾く (``isinstance(True, int)``
            の罠を避ける)。

    Returns:
        有限の正値、または ``math.inf``。

    Raises:
        ModelLoadError: 受け入れ可能でない型・値 (例: 負の数、``NaN``、``-inf``、
            未対応の文字列、空文字)。
    """
    if isinstance(raw, bool):
        raise ModelLoadError(f"Invalid t_end: expected number or 'inf', got bool ({raw!r})")
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized == "inf":
            return math.inf
        raise ModelLoadError(
            f"Invalid t_end string {raw!r}: only 'inf' (case-insensitive) is "
            f"accepted as the unbounded sentinel. '+inf' / 'infinity' / '∞' "
            f"are intentionally rejected (ADR-0042 §4)."
        )
    if isinstance(raw, numbers.Real):
        value = float(raw)
        if math.isnan(value):
            raise ModelLoadError("Invalid t_end: NaN")
        if value == -math.inf:
            raise ModelLoadError(
                "Invalid t_end: -inf is rejected (only positive 'inf' is "
                "accepted as the unbounded sentinel, ADR-0042 §4)"
            )
        if value <= 0.0:
            raise ModelLoadError(f"Invalid t_end: must be positive, got {value!r}")
        return value
    raise ModelLoadError(
        f"Invalid t_end type: expected number or 'inf' string, got {type(raw).__name__} ({raw!r})"
    )


def serialize_t_end(t_end: float) -> float | str:
    """``Simulator.t_end`` を JSON-serializable な値に変換する (ADR-0042 §論点 4)。

    ``math.inf`` → ``"inf"``、有限値 → ``float`` のまま。
    """
    if math.isinf(t_end):
        return "inf"
    return float(t_end)


def to_json_value(value: Any) -> Any:
    """ブロックパラメータ値を JSON-serializable な値に変換する (ADR-0008 §(3))。

    対応:
      * ``bool``, ``str``, ``None`` → そのまま
      * ``numbers.Integral`` (bool 除く) → ``int``
      * ``numbers.Real`` (bool 除く) → ``float``
      * ``npt.NDArray[Any]`` → 再帰的に ``list``
      * ``list`` / ``tuple`` → 各要素を再帰変換した ``list``
      * ``dict`` → キーを ``str`` に変換、値を再帰変換
      * 上記以外 → ``ModelSerializationError``
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        return float(value)
    if isinstance(value, np.ndarray):
        # ``ndarray.tolist()`` は再帰的に Python ネイティブ型 (float/int/bool) に
        # 変換するため、追加の to_json_value 再帰は不要。
        return value.tolist()
    if isinstance(value, list | tuple):
        return [to_json_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_json_value(v) for k, v in value.items()}
    raise ModelSerializationError(
        f"Cannot serialize value of type {type(value).__name__!r} "
        f"({value!r}) to JSON. Supported types: bool, int, float, str, None, "
        f"list, tuple, dict, npt.NDArray[Any]."
    )


def to_json_dict(params: dict[str, Any]) -> dict[str, Any]:
    """``_params`` 辞書を再帰的に JSON-serializable に変換する。"""
    return {str(k): to_json_value(v) for k, v in params.items()}


def block_type_path(cls: type) -> str:
    """``Block`` サブクラスの完全修飾名を返す (ADR-0008 §BT-A)。

    ``__main__`` モジュールで定義された class は永続化不可なので警告を兼ねた
    例外を投げる (ロード側でモジュール解決できないため)。
    """
    module = cls.__module__
    if module == "__main__":
        raise ModelSerializationError(
            f"Block class {cls.__name__!r} is defined in __main__ and cannot be "
            f"persisted. Move the definition into an importable module."
        )
    return f"{module}.{cls.__name__}"


def resolve_block_class(type_path: str) -> type:
    """完全修飾名 ``"flode.blocks.Gain"`` から ``Block`` サブクラスを解決する。

    セキュリティのため、``flode.*`` および ``register_block_module`` で登録済みの
    prefix に属する class のみ許可する。この allowlist 外の type_path は
    ``importlib.import_module`` を呼ばずに即拒否する。
    """
    from .block import Block as _Block  # 遅延 import (循環回避)

    if not isinstance(type_path, str) or "." not in type_path:
        raise UnknownBlockTypeError(
            f"Block type must be a fully-qualified class path "
            f"(e.g. 'flode.blocks.Gain'), got {type_path!r}"
        )
    module_name, class_name = type_path.rsplit(".", 1)
    if not _is_allowed_module(module_name + "."):
        # prefix 一致は trailing "." を含めて評価する (e.g. "flode" は許容しないが
        # "flode.blocks" は "flode." prefix にマッチ)
        if not _is_allowed_module(module_name):
            raise UnknownBlockTypeError(
                f"Block type {type_path!r} is not in an allowed module prefix. "
                f"Default allowlist: {_DEFAULT_ALLOWED_PREFIXES}, "
                f"extra: {sorted(_extra_allowed_prefixes)}. "
                f"Use `flode.core.persistence.register_block_module(prefix)` to "
                f"add a third-party prefix."
            )
    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        raise UnknownBlockTypeError(
            f"Cannot import module {module_name!r} for block type {type_path!r}: {e}"
        ) from e
    try:
        cls = getattr(module, class_name)
    except AttributeError as e:
        raise UnknownBlockTypeError(
            f"Module {module_name!r} has no attribute {class_name!r}"
        ) from e
    if not isinstance(cls, type) or not issubclass(cls, _Block):
        raise UnknownBlockTypeError(f"{type_path!r} is not a Block subclass (got {cls!r})")
    return cls


def normalize_layout(layout: object) -> LayoutDict | None:
    """ADR-0020 §(1)(8): 任意の layout 入力を canonical な ``LayoutDict`` に変換する。

    各 entry は ``{"x": float, "y": float}`` を必須とし、optional ``"w"`` / ``"h"`` を
    含めても良い (= ノードサイズ永続化、初期は ADR-0020 §(2) で Phase 4+ 送りとされて
    いたが GUI ユーザー要望で先行投入)。それ以外のキーは破棄、値は ``int | float`` を
    ``float`` に強制変換する。

    Args:
        layout: 正規化対象の任意の値。``None`` または空 dict のとき ``None`` を返す。

    Returns:
        正規化済みの ``LayoutDict``、または ``None`` (layout 無し)。

    Raises:
        ModelLoadError: ``layout`` が ``dict[str, dict]`` の形式でない、x/y が欠落、
            または x/y/w/h が数値変換不可能な場合。
    """
    if layout is None:
        return None
    if not isinstance(layout, dict):
        raise ModelLoadError(f"layout must be a dict[str, dict], got {type(layout).__name__}")
    if not layout:
        return None
    out: LayoutDict = {}
    for key, value in layout.items():
        if not isinstance(key, str):
            raise ModelLoadError(f"layout key must be a str (block id), got {key!r}")
        if not isinstance(value, dict):
            raise ModelLoadError(
                f"layout[{key!r}] must be a dict with x / y, got {type(value).__name__}"
            )
        if "x" not in value or "y" not in value:
            raise ModelLoadError(f"layout[{key!r}] must contain both 'x' and 'y', got {value!r}")
        try:
            x = float(value["x"])
            y = float(value["y"])
        except (TypeError, ValueError) as e:
            raise ModelLoadError(f"layout[{key!r}] has non-numeric x/y: {value!r}") from e
        entry: dict[str, float | bool] = {"x": x, "y": y}
        for size_key in ("w", "h"):
            if size_key in value:
                try:
                    sv = float(value[size_key])
                except (TypeError, ValueError) as e:
                    raise ModelLoadError(
                        f"layout[{key!r}].{size_key} has non-numeric value: {value[size_key]!r}"
                    ) from e
                if sv > 0:
                    entry[size_key] = sv
        # v0.15.0: GUI 左右反転フラグ。bool 以外は無視 (= 古い model でも安全に
        # ロード)、True のときのみ JSON に保存 (= byte-identical を維持)。
        if value.get("flipped") is True:
            entry["flipped"] = True
        out[key] = entry
    return out


def serialize_connections(blocks: list[Block]) -> list[dict[str, Any]]:
    """全ブロックの ``input_sources`` から JSON 用の結線リストを構築する。"""
    out: list[dict[str, Any]] = []
    for b in blocks:
        for dst_idx, src in enumerate(b.input_sources):
            if src is None:
                continue
            src_block, src_idx = src
            out.append(
                {
                    "src": src_block.id,
                    "src_idx": int(src_idx),
                    "dst": b.id,
                    "dst_idx": int(dst_idx),
                }
            )
    return out


# Migration registry: (from_version, to_version) -> 変換関数
_MIGRATIONS: dict[tuple[str, str], Callable[[dict[str, Any]], dict[str, Any]]] = {}


def _builtin_migrate_0_1_to_0_2(data: dict[str, Any]) -> dict[str, Any]:
    """ADR-0009 §(8): 0.1 → 0.2。0.1 ファイルは Subsystem を含まないため、
    ``schema_version`` 文字列の更新のみで OK。"""
    out = dict(data)
    out["schema_version"] = "0.2"
    return out


def _builtin_migrate_0_2_to_0_3(data: dict[str, Any]) -> dict[str, Any]:
    """ADR-0015 §(4): 0.2 → 0.3。

    全離散ブロック (``UnitDelay``, ``DiscreteIntegrator``, ``DiscreteStateSpace``,
    ``DiscreteTransferFunction``) の内部 ``n_states`` が augmentation で 2 倍化
    したが、JSON 表現では ``x0`` を **scalar (UnitDelay/DiscreteIntegrator) または
    shape-(n,) (DiscreteStateSpace/DiscreteTransferFunction) のまま維持** する設計
    (Block 内部の ``__init__`` で ``[x0, x0]`` / ``concat([x0, x0])`` に展開する) な
    ので、JSON 側の変換は ``schema_version`` 文字列の更新のみで完結する。Subsystem
    内部の離散ブロックも同じ Block class を使うため再帰的処理は不要。

    旧 v0.5.0〜v0.12.0 で含まれていた `ZeroOrderHold` (legacy) は ADR-0033 (v0.13.0)
    で削除済。schema 0.2/0.3 ファイルに `ZeroOrderHold` type が含まれていれば、
    ``resolve_block_class`` 段階で ``UnknownBlockTypeError`` が発生する (= load 拒否)。
    """
    out = dict(data)
    out["schema_version"] = "0.3"
    return out


def _builtin_migrate_0_3_to_0_4(data: dict[str, Any]) -> dict[str, Any]:
    """ADR-0017 §(7): 0.3 → 0.4。

    SM-B (ベクトルポート) 信号モデル導入。``port_shapes_in`` / ``port_shapes_out``
    フィールドが Block JSON entry に **optional** 追加された。0.3 ファイルにはこれらの
    フィールドはなく、Block.__init__ で ``port_shapes_in/out=None`` (= 全 ``()`` = SM-A
    互換) として扱われるため、JSON 側の変換は ``schema_version`` 文字列更新のみ。
    """
    out = dict(data)
    out["schema_version"] = "0.4"
    return out


def _builtin_migrate_0_4_to_0_5(data: dict[str, Any]) -> dict[str, Any]:
    """ADR-0020 §(6): 0.4 → 0.5。

    レイアウト永続化フィールド ``layout`` を top-level に optional 追加。0.4 ファイル
    には ``layout`` キーが存在しないが、本 migration は ``schema_version`` 文字列の
    更新のみで成立する (load 側で ``layout`` 欠落 = 全 block auto-layout fallback と
    解釈)。Subsystem 内部 ``params.layout`` も同じく optional のため再帰的処理は不要。
    """
    out = dict(data)
    out["schema_version"] = "0.5"
    return out


def _builtin_migrate_0_5_to_0_6(data: dict[str, Any]) -> dict[str, Any]:
    """ADR-0021 §(8): 0.5 → 0.6。

    Subsystem entry に optional な ``mask_params`` / ``mask_values`` を追加。0.5
    ファイルにはマスク関連キーが無く、本 migration は ``schema_version`` 文字列更新
    のみ (load 側で mask_params 欠落 = マスクなし Subsystem として解釈)。
    """
    out = dict(data)
    out["schema_version"] = "0.6"
    return out


def _builtin_migrate_0_6_to_0_7(data: dict[str, Any]) -> dict[str, Any]:
    """ADR-0036 §(4): 0.6 → 0.7。

    新規 block type ``pyflw.blocks.discrete.RateTransition`` を導入 (= マルチ
    レート明示変換)。Phase 5b 後半 (= ADR-0036 v0.16.1) で
    ``pyflw.subsystems.triggered.TriggeredSubsystem`` も追加予定。

    既存 0.6 ファイルにはこれらの新 type_path は出現しないため、本 migration は
    ``schema_version`` 文字列の更新のみで完結する。新 type_path が現れない 0.6
    モデルは意味論変化なしで 0.7 に上がる (= 0.6 ファイルは 100% 互換)。
    """
    out = dict(data)
    out["schema_version"] = "0.7"
    return out


# ``TriggeredSubsystem`` class は v0.38.0 で削除済 (ADR-0058 §論点 9)。
# 本 tuple は 0.7 → 0.8 migration が旧 JSON 内の **文字列マッチ** で旧型 entry
# を検出するためのリテラルとして残置 (= class import ではなく文字列のみ参照、
# 古い flw.json をロードしても migration が機能する保証)。
# NOTE: schema <=0.9 のファイルは旧プロジェクト名の ``pyflw.*`` FQN を含むため、
# これらのリテラルは意図的に ``pyflw`` のまま (0.9 → 0.10 migration が flode に変換)。
_SUBSYSTEM_TYPES_FOR_MIGRATION: tuple[str, ...] = (
    "pyflw.subsystems.subsystem.Subsystem",
    "pyflw.subsystems.triggered.TriggeredSubsystem",
)


def _strip_subsystem_port_fields_recursive(
    blocks: list[dict[str, Any]] | None,
    *,
    parent_path: str = "<root>",
) -> None:
    """ADR-0039 0.7 → 0.8 用のヘルパ。

    ``blocks`` 内の Subsystem (含む TriggeredSubsystem) を再帰的にたどって、
    ``params`` から ``n_inputs`` / ``n_outputs`` / ``port_shapes_in`` /
    ``port_shapes_out`` フィールドを **in-place で削除**する。削除前に内部
    Inport / Outport 数との一致を確認し、不一致なら ``logger.warning``。
    内部 Inport 数が真実なので migration 後の値はそちらに従う (= フィールド
    消失で自動同期)。
    """
    logger = logging.getLogger("flode.persistence.migrate_0_7_to_0_8")
    if not blocks:
        return
    for entry in blocks:
        if not isinstance(entry, dict):
            continue
        block_type = entry.get("type")
        params = entry.get("params")
        if not isinstance(params, dict):
            continue
        if block_type in _SUBSYSTEM_TYPES_FOR_MIGRATION:
            inner_blocks = params.get("blocks") or []
            inport_count = sum(
                1
                for b in inner_blocks
                if isinstance(b, dict) and b.get("type") == "pyflw.subsystems.ports.Inport"
            )
            outport_count = sum(
                1
                for b in inner_blocks
                if isinstance(b, dict) and b.get("type") == "pyflw.subsystems.ports.Outport"
            )
            # TriggeredSubsystem は trigger 入力分 +1 が n_inputs に乗る
            expected_n_inputs = (
                inport_count + 1
                if block_type == "pyflw.subsystems.triggered.TriggeredSubsystem"
                else inport_count
            )
            expected_n_outputs = outport_count

            old_n_inputs = params.pop("n_inputs", None)
            old_n_outputs = params.pop("n_outputs", None)
            params.pop("port_shapes_in", None)
            params.pop("port_shapes_out", None)

            entry_id = entry.get("id", "<no-id>")
            path = f"{parent_path}/{entry_id}"
            # NOTE: id は検証前 (migration は normalize/validate より先に走る) の
            # ため %r でエスケープして log injection (改行入り id) を防ぐ
            if old_n_inputs is not None and old_n_inputs != expected_n_inputs:
                logger.warning(
                    "Subsystem %r: legacy n_inputs=%s does not match inner Inport "
                    "count=%s; using inner count after migration (ADR-0039)",
                    path,
                    old_n_inputs,
                    expected_n_inputs,
                )
            if old_n_outputs is not None and old_n_outputs != expected_n_outputs:
                logger.warning(
                    "Subsystem %r: legacy n_outputs=%s does not match inner Outport "
                    "count=%s; using inner count after migration (ADR-0039)",
                    path,
                    old_n_outputs,
                    expected_n_outputs,
                )

            # ネスト Subsystem を再帰的に処理
            _strip_subsystem_port_fields_recursive(inner_blocks, parent_path=path)


# ADR-0058: TriggeredSubsystem の旧 type_path / migration 後の Subsystem type_path /
# 新規 Trigger control block の type_path。文字列として 3 箇所で参照されるので定数化。
# NOTE: _NEW_* も意図的に旧プロジェクト名 ``pyflw.*`` のまま — 0.8 → 0.9 は pyflw FQN
# の世界で完結し、続く 0.9 → 0.10 がチェーン内で flode FQN に書き換える。
_OLD_TRIGGERED_SUBSYSTEM_TYPE = "pyflw.subsystems.triggered.TriggeredSubsystem"
_NEW_SUBSYSTEM_TYPE = "pyflw.subsystems.subsystem.Subsystem"
_NEW_TRIGGER_BLOCK_TYPE = "pyflw.subsystems.control_blocks.Trigger"


def _convert_triggered_subsystem_recursive(
    blocks: list[dict[str, Any]] | None,
    *,
    parent_path: str = "<root>",
) -> None:
    """ADR-0058 0.8 → 0.9 用のヘルパ。``blocks`` を再帰的にたどり、
    ``TriggeredSubsystem`` を ``Subsystem`` + 内部 ``Trigger`` block に変換する。

    変換ルール (ADR-0058 §論点 6):
        - ``type`` を ``Subsystem`` に書き換え
        - ``params.trigger_mode`` を取り出し、内部 ``blocks`` 末尾に
          ``Trigger(trigger_type=<旧 trigger_mode>)`` の entry を append
        - 新 ``Trigger`` block の id は ``f"{parent_id}_trigger"`` (衝突時は連番)
        - 旧 ``params.trigger_mode`` を削除
        - 内部 ``params.blocks`` を再帰処理 (= ネスト Subsystem 内の旧型も変換)

    数値挙動: 変換後の Subsystem + Trigger は旧 TriggeredSubsystem と同じ semantics
    で動作する (ADR-0058 §論点 6 確定、`is_trigger_edge` は移植・公開化済)。
    """
    logger = logging.getLogger("flode.persistence.migrate_0_8_to_0_9")
    if not blocks:
        return
    for entry in blocks:
        if not isinstance(entry, dict):
            continue
        block_type = entry.get("type")
        params = entry.get("params")
        if not isinstance(params, dict):
            continue
        if block_type == _OLD_TRIGGERED_SUBSYSTEM_TYPE:
            entry_id = entry.get("id", "unknown")
            path = f"{parent_path}/{entry_id}"
            trigger_mode = params.pop("trigger_mode", "rising")
            # ``setdefault`` で元 list object への参照を維持しつつ、欠損時に空 list を
            # 自動補完 (NITS 2: ``params.get("blocks") or [] + append + 再代入`` の
            # 冗長パターンを簡素化)。
            inner = params.setdefault("blocks", [])
            # ADR-0058 §論点 6: 内部 Trigger の id は決定的 ``{parent_id}_trigger``
            # で、衝突した場合のみ counter を後置する。
            existing_ids: set[str] = set()
            for b in inner:
                if isinstance(b, dict):
                    bid = b.get("id")
                    if isinstance(bid, str):
                        existing_ids.add(bid)
            trigger_id = f"{entry_id}_trigger"
            counter = 0
            while trigger_id in existing_ids:
                counter += 1
                trigger_id = f"{entry_id}_trigger_{counter}"
            inner.append(
                {
                    "id": trigger_id,
                    "type": _NEW_TRIGGER_BLOCK_TYPE,
                    "params": {"trigger_type": trigger_mode},
                }
            )
            entry["type"] = _NEW_SUBSYSTEM_TYPE
            logger.debug(
                # id は検証前のため %r で log injection を防ぐ
                "Subsystem %r: converted TriggeredSubsystem (trigger_mode=%r) → "
                "Subsystem + Trigger block id=%r (ADR-0058 schema 0.9 migration)",
                path,
                trigger_mode,
                trigger_id,
            )
        # ネスト Subsystem の内部 blocks も再帰処理 (Subsystem に変換済の entry も含む)
        inner_blocks = params.get("blocks")
        if isinstance(inner_blocks, list):
            _convert_triggered_subsystem_recursive(
                inner_blocks, parent_path=f"{parent_path}/{entry.get('id', '<no-id>')}"
            )


def _builtin_migrate_0_8_to_0_9(data: dict[str, Any]) -> dict[str, Any]:
    """ADR-0058: 0.8 → 0.9。

    旧 ``pyflw.subsystems.triggered.TriggeredSubsystem`` を新
    ``pyflw.subsystems.subsystem.Subsystem`` + 内部 ``Trigger`` block に変換する。
    識別の真実源を class 名から内部 control block に変える設計変更
    (ADR-0058 §論点 6 / §論点 11)。

    数値挙動への影響: なし (= ``is_trigger_edge`` semantics は ADR-0036 から不変、
    state freeze ロジックも同等。SPEC-0007 §非機能要件「数値完全不変」を満たす)。
    """
    out = dict(data)
    _convert_triggered_subsystem_recursive(out.get("blocks"))
    out["schema_version"] = "0.9"
    return out


def _builtin_migrate_0_7_to_0_8(data: dict[str, Any]) -> dict[str, Any]:
    """ADR-0039: 0.7 → 0.8。

    Subsystem の ``n_inputs`` / ``n_outputs`` / ``port_shapes_in`` /
    ``port_shapes_out`` を **派生 property** に格上げ (= JSON フィールドから
    削除)。本 migration は再帰的に Subsystem entry を走査し、これら 4
    フィールドを params から除く。値が内部 Inport / Outport 数と不一致なら
    warning 1 度。

    数値挙動への影響: なし (= フィールド消失だけ、内部 Inport / Outport の数と
    port_idx 連番は維持される)。
    """
    out = dict(data)
    # blocks フィールド (top-level) と Subsystem 内部 params.blocks の両方に
    # 同じロジックを再帰適用
    _strip_subsystem_port_fields_recursive(out.get("blocks"))
    out["schema_version"] = "0.8"
    return out


# schema <=0.9 のブロック型 FQN prefix。プロジェクト名変更 (pyflw → flode) 前の
# ファイルを検出する **文字列マッチ専用** リテラルで、意図的に旧名のまま。
_OLD_FQN_PREFIX = "pyflw."
_NEW_FQN_PREFIX = "flode."


def _rename_block_type_prefix_recursive(
    blocks: list[dict[str, Any]] | None,
    *,
    parent_path: str = "<root>",
) -> None:
    """0.9 → 0.10 用のヘルパ。``blocks`` を再帰的にたどり、``type`` の
    ``pyflw.`` prefix を ``flode.`` に **in-place で書き換える**。

    サードパーティ prefix (例 ``myapp.blocks.X``) や非 str の ``type`` は
    変更しない。ネスト Subsystem は ``params.blocks`` を再帰処理する。
    """
    logger = logging.getLogger("flode.persistence.migrate_0_9_to_0_10")
    if not blocks:
        return
    for entry in blocks:
        if not isinstance(entry, dict):
            continue
        block_type = entry.get("type")
        if isinstance(block_type, str) and block_type.startswith(_OLD_FQN_PREFIX):
            new_type = _NEW_FQN_PREFIX + block_type[len(_OLD_FQN_PREFIX) :]
            entry["type"] = new_type
            logger.debug(
                # id は検証前のため %r で log injection を防ぐ
                "Block %r/%r: renamed type %r -> %r (schema 0.10 migration)",
                parent_path,
                entry.get("id", "<no-id>"),
                block_type,
                new_type,
            )
        params = entry.get("params")
        if isinstance(params, dict):
            inner_blocks = params.get("blocks")
            if isinstance(inner_blocks, list):
                _rename_block_type_prefix_recursive(
                    inner_blocks,
                    parent_path=f"{parent_path}/{entry.get('id', '<no-id>')}",
                )


def _builtin_migrate_0_9_to_0_10(data: dict[str, Any]) -> dict[str, Any]:
    """プロジェクト名変更 (pyflw → flode): 0.9 → 0.10。

    ブロック型 FQN の ``pyflw.`` prefix を ``flode.`` に書き換える
    (ネスト Subsystem 含む)。あわせて ``metadata.tool`` の ``pyflw`` も
    ``flode`` に更新する。フィールド構成・数値挙動への影響: なし。
    """
    out = dict(data)
    _rename_block_type_prefix_recursive(out.get("blocks"))
    meta = out.get("metadata")
    if isinstance(meta, dict):
        tool = meta.get("tool")
        if isinstance(tool, str) and tool.startswith("pyflw"):
            out["metadata"] = {**meta, "tool": "flode" + tool[len("pyflw") :]}
    out["schema_version"] = "0.10"
    return out


# Built-in migrations を _MIGRATIONS に登録する関数 (テストの reset 後に再登録可能)
def _register_builtin_migrations() -> None:
    _MIGRATIONS[("0.1", "0.2")] = _builtin_migrate_0_1_to_0_2
    _MIGRATIONS[("0.2", "0.3")] = _builtin_migrate_0_2_to_0_3
    _MIGRATIONS[("0.3", "0.4")] = _builtin_migrate_0_3_to_0_4
    _MIGRATIONS[("0.4", "0.5")] = _builtin_migrate_0_4_to_0_5
    _MIGRATIONS[("0.5", "0.6")] = _builtin_migrate_0_5_to_0_6
    _MIGRATIONS[("0.6", "0.7")] = _builtin_migrate_0_6_to_0_7
    _MIGRATIONS[("0.7", "0.8")] = _builtin_migrate_0_7_to_0_8
    _MIGRATIONS[("0.8", "0.9")] = _builtin_migrate_0_8_to_0_9
    _MIGRATIONS[("0.9", "0.10")] = _builtin_migrate_0_9_to_0_10


_register_builtin_migrations()


def register_migration(
    from_version: str, to_version: str
) -> Callable[
    [Callable[[dict[str, Any]], dict[str, Any]]],
    Callable[[dict[str, Any]], dict[str, Any]],
]:
    """``schema_version`` migration 関数を registry に登録するデコレータ。"""

    def decorator(
        fn: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> Callable[[dict[str, Any]], dict[str, Any]]:
        _MIGRATIONS[(from_version, to_version)] = fn
        return fn

    return decorator


def migrate_to_current(data: dict[str, Any]) -> dict[str, Any]:
    """``schema_version`` を確認し、必要なら最新版にマイグレートして返す。

    ADR-0058 §論点 10: 1 段以上の migration を適用したら、戻り値に
    ``_migrated_from`` メタを付与する (= 呼び出し側が「保存時に新 schema になる」
    旨を UI 通知 / dirty flag 設定に使う)。元データに既に ``_migrated_from`` が
    あっても上書きする (= migration 連鎖時は最古バージョンを記録)。

    Note:
        ``_migrated_from`` キーは **migration が走ったときだけ** 戻り値に存在する。
        現バージョンファイルをロードしたときは含まれない。呼び出し側は必ず
        ``data.get("_migrated_from")`` で参照すること (= ``data["_migrated_from"]``
        での参照は KeyError を起こす)。Simulator.load / frontend loadModel での
        消費後は ``data`` から削除する (= save 時に metadata として書き戻さない)。
    """
    if "schema_version" not in data:
        raise ModelLoadError("Missing required key 'schema_version' in JSON model")
    version = data["schema_version"]
    if not isinstance(version, str):
        raise ModelLoadError(f"schema_version must be a string, got {type(version).__name__}")
    if version == CURRENT_SCHEMA_VERSION:
        return data
    if version in SUPPORTED_SCHEMA_VERSIONS:
        return data  # 互換性のあるサポートバージョン

    # 異なるが migration 可能?
    original_version = version
    cur = version
    visited: set[str] = {cur}
    while cur != CURRENT_SCHEMA_VERSION:
        next_step = next((to for (frm, to) in _MIGRATIONS if frm == cur), None)
        if next_step is None:
            raise SchemaVersionError(
                f"Unsupported schema_version {version!r}. "
                f"Supported: {SUPPORTED_SCHEMA_VERSIONS}, "
                f"current: {CURRENT_SCHEMA_VERSION!r}. "
                f"No migration registered from {cur!r}."
            )
        if next_step in visited:
            raise SchemaVersionError(f"Migration cycle detected at {next_step!r}; aborting")
        data = _MIGRATIONS[(cur, next_step)](data)
        visited.add(next_step)
        cur = next_step
    # ADR-0058 §論点 10: migration を 1 段以上経た data に元バージョンを記録。
    # 呼び出し側 (Simulator.load / frontend loadModel) はこのキーを見て dirty flag
    # を立てる / toast を出すかを決める。
    data["_migrated_from"] = original_version
    return data


def _normalize_waypoint_key(key: str) -> str:
    """``"<block id>:<src_idx>"`` 合成キー (ADR-0057) の id 部のみ NFC 正規化する。"""
    if ":" not in key:
        return key  # 不正形。後段の検証に委ねてここでは触らない
    prefix, idx = key.rsplit(":", 1)
    return f"{normalize_block_id(prefix)}:{idx}"


def _normalize_block_entry_ids(entry: Any) -> Any:
    if not isinstance(entry, dict):
        return entry
    out = dict(entry)
    if isinstance(out.get("id"), str):
        out["id"] = normalize_block_id(out["id"])
    params = out.get("params")
    # Subsystem: ``params`` 自体が blocks / connections / layout /
    # branch_waypoints を持つネストしたモデル構造 (ADR-0009 / 0020 / 0057)
    if isinstance(params, dict) and isinstance(params.get("blocks"), list):
        out["params"] = normalize_model_ids(params)
    return out


def _normalize_connection_entry_ids(entry: Any) -> Any:
    if not isinstance(entry, dict):
        return entry
    out = dict(entry)
    for key in ("src", "dst"):
        if isinstance(out.get(key), str):
            out[key] = normalize_block_id(out[key])
    return out


def normalize_model_ids(data: dict[str, Any]) -> dict[str, Any]:
    """モデル dict 内の block id とその参照を一括で NFC 正規化する (ADR-0071 §(3))。

    対象 (存在するもののみ): ``blocks[].id`` / ``connections[].src`` / ``.dst`` /
    ``layout`` キー / ``branch_waypoints`` キーの id 部 / ``scope_settings`` キー。
    Subsystem の ``params`` (ネストした blocks / connections / layout /
    branch_waypoints) にも再帰する。

    macOS のファイルシステム由来テキスト等で NFD 形が混入した場合、id とその
    参照 (結線・layout キー) の**片方だけ**正規化すると参照が切れるため、必ず
    この単一関数で全参照を同時に正規化する。ASCII のみのモデルでは恒等変換。

    Args:
        data: parsed JSON のモデル dict (top-level または Subsystem の params)。

    Returns:
        正規化済みの新しい dict (入力は変更しない)。dict 以外はそのまま返す。
    """
    if not isinstance(data, dict):
        return data
    out = dict(data)
    if isinstance(out.get("blocks"), list):
        out["blocks"] = [_normalize_block_entry_ids(b) for b in out["blocks"]]
    if isinstance(out.get("connections"), list):
        out["connections"] = [_normalize_connection_entry_ids(c) for c in out["connections"]]
    for dict_key in ("layout", "scope_settings"):
        section = out.get(dict_key)
        if isinstance(section, dict):
            normalized_section = {
                (normalize_block_id(k) if isinstance(k, str) else k): v for k, v in section.items()
            }
            # NFD と NFC が併存するキーは正規化で衝突し後勝ちで片方が消える。
            # silent にせず観測点を残す (ADR-0071 §(12)-2)
            if len(normalized_section) != len(section):
                logging.getLogger("flode.persistence.normalize_ids").warning(
                    "normalize_model_ids: %d %r key(s) collided after NFC "
                    "normalization and were dropped (visually identical keys "
                    "with different normalization forms)",
                    len(section) - len(normalized_section),
                    dict_key,
                )
            out[dict_key] = normalized_section
    waypoints = out.get("branch_waypoints")
    if isinstance(waypoints, dict):
        normalized_waypoints = {
            (_normalize_waypoint_key(k) if isinstance(k, str) else k): v
            for k, v in waypoints.items()
        }
        if len(normalized_waypoints) != len(waypoints):
            logging.getLogger("flode.persistence.normalize_ids").warning(
                "normalize_model_ids: %d 'branch_waypoints' key(s) collided "
                "after NFC normalization and were dropped",
                len(waypoints) - len(normalized_waypoints),
            )
        out["branch_waypoints"] = normalized_waypoints
    return out
