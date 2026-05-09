"""JSON 永続化ヘルパー (ADR-0008)。

``Simulator.save`` / ``Simulator.load`` の内部実装と、ブロック type の動的解決、
パラメータの JSON-serializable 変換、``schema_version`` migration をまとめる。

Phase 2 では ``schema_version = "0.1"`` のみサポート。Subsystem 導入時 (ADR-0009)
に ``"0.2"`` を追加し、``_MIGRATIONS`` registry に変換関数を登録する。
"""

from __future__ import annotations

import importlib
import logging
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

if TYPE_CHECKING:
    from .block import Block


CURRENT_SCHEMA_VERSION = "0.8"
# 「migration を通さずそのまま受け入れるバージョン」の一覧。CURRENT のみを置く。
# 旧バージョン (e.g. "0.1") は ``_MIGRATIONS`` 経由で常に CURRENT に変換される。
# 将来 "0.3" を CURRENT にするとき、"0.2" を SUPPORTED に残せば追加の migration
# 処理を介さずに受け入れる挙動が選べる。
SUPPORTED_SCHEMA_VERSIONS = (CURRENT_SCHEMA_VERSION,)

# ADR-0020 §(1): layout entry の型。block_id → {"x": float, "y": float}。
# `LayoutDict` = レイアウト全体 (top-level または Subsystem 内部の `params.layout`)。
# v0.15.0: optional ``"flipped": bool`` を許容 (= Simulink の Flip Block 相当)。
LayoutDict = dict[str, dict[str, float | bool]]


# allowlist: ロード時にここで列挙した module prefix のいずれかに属する class のみ
# 解決を許可する (任意の `os.system` 等を import するセキュリティリスクを避ける)。
# サードパーティ拡張は ``register_block_module(prefix)`` で追加する。
_DEFAULT_ALLOWED_PREFIXES: tuple[str, ...] = ("pyflw.",)
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
    """完全修飾名 ``"pyflw.blocks.Gain"`` から ``Block`` サブクラスを解決する。

    セキュリティのため、``pyflw.*`` および ``register_block_module`` で登録済みの
    prefix に属する class のみ許可する。この allowlist 外の type_path は
    ``importlib.import_module`` を呼ばずに即拒否する。
    """
    from .block import Block as _Block  # 遅延 import (循環回避)

    if not isinstance(type_path, str) or "." not in type_path:
        raise UnknownBlockTypeError(
            f"Block type must be a fully-qualified class path "
            f"(e.g. 'pyflw.blocks.Gain'), got {type_path!r}"
        )
    module_name, class_name = type_path.rsplit(".", 1)
    if not _is_allowed_module(module_name + "."):
        # prefix 一致は trailing "." を含めて評価する (e.g. "pyflw" は許容しないが
        # "pyflw.blocks" は "pyflw." prefix にマッチ)
        if not _is_allowed_module(module_name):
            raise UnknownBlockTypeError(
                f"Block type {type_path!r} is not in an allowed module prefix. "
                f"Default allowlist: {_DEFAULT_ALLOWED_PREFIXES}, "
                f"extra: {sorted(_extra_allowed_prefixes)}. "
                f"Use `pyflw.core.persistence.register_block_module(prefix)` to "
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
    logger = logging.getLogger("pyflw.persistence.migrate_0_7_to_0_8")
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
            if old_n_inputs is not None and old_n_inputs != expected_n_inputs:
                logger.warning(
                    "Subsystem %s: legacy n_inputs=%s does not match inner Inport "
                    "count=%s; using inner count after migration (ADR-0039)",
                    path,
                    old_n_inputs,
                    expected_n_inputs,
                )
            if old_n_outputs is not None and old_n_outputs != expected_n_outputs:
                logger.warning(
                    "Subsystem %s: legacy n_outputs=%s does not match inner Outport "
                    "count=%s; using inner count after migration (ADR-0039)",
                    path,
                    old_n_outputs,
                    expected_n_outputs,
                )

            # ネスト Subsystem を再帰的に処理
            _strip_subsystem_port_fields_recursive(inner_blocks, parent_path=path)


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


# Built-in migrations を _MIGRATIONS に登録する関数 (テストの reset 後に再登録可能)
def _register_builtin_migrations() -> None:
    _MIGRATIONS[("0.1", "0.2")] = _builtin_migrate_0_1_to_0_2
    _MIGRATIONS[("0.2", "0.3")] = _builtin_migrate_0_2_to_0_3
    _MIGRATIONS[("0.3", "0.4")] = _builtin_migrate_0_3_to_0_4
    _MIGRATIONS[("0.4", "0.5")] = _builtin_migrate_0_4_to_0_5
    _MIGRATIONS[("0.5", "0.6")] = _builtin_migrate_0_5_to_0_6
    _MIGRATIONS[("0.6", "0.7")] = _builtin_migrate_0_6_to_0_7
    _MIGRATIONS[("0.7", "0.8")] = _builtin_migrate_0_7_to_0_8


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
    """``schema_version`` を確認し、必要なら最新版にマイグレートして返す。"""
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
    return data
