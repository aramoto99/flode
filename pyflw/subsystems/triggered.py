"""Triggered Subsystem (ADR-0036, ADR-0058 で supersede)。

ADR-0036 で導入された ``TriggeredSubsystem`` は、ADR-0058 で「``Subsystem`` 内部に
``Trigger`` control block を配置する方式」に置き換えられた。本モジュールは
**deprecation 期間 (v3.x)** の互換性 shim:

- ``TriggeredSubsystem(trigger_mode=...)`` 呼び出しは ``__new__`` で ``Subsystem`` +
  内部 ``Trigger`` block を構築して返す factory (= 旧 API 経由でも新方式で動作する)。
- ``DeprecationWarning`` を出して移行を促す。
- ``_is_trigger_edge`` / ``TRIGGER_MODES`` は :mod:`pyflw.subsystems.control_blocks`
  の新 API への薄いラッパ / 別名として残す (= 旧 import path で動作する)。

v0.37.0 で本モジュール自体を削除する予定 (ADR-0058 §論点 9)。
"""

from __future__ import annotations

import logging
import warnings
from typing import Any, cast

from ..core.persistence import LayoutDict
from .control_blocks import Trigger, TriggerType, is_trigger_edge as _new_is_trigger_edge
from .subsystem import Subsystem

_logger = logging.getLogger("pyflw.subsystems.triggered")

#: ``trigger_mode`` で許される値 (= ADR-0036 当時の 3 値)。``function-call`` は
#: ADR-0058 の新 ``Trigger.trigger_type`` で受け皿だけ用意されたが、旧 API では
#: 提供しない (= API 後方互換)。
TRIGGER_MODES: tuple[str, ...] = ("rising", "falling", "either")


def _is_trigger_edge(prev: float, curr: float, mode: str) -> bool:
    """ADR-0036 §(3) trigger edge 判定の互換性 shim。

    新しい :func:`pyflw.subsystems.control_blocks.is_trigger_edge` を呼ぶ。
    semantics は ADR-0036 と完全同一 (NaN ガード、rising/falling/either 判定、
    unknown mode で ``BlockSpecError``)。v0.37.0 で削除予定。
    """
    return _new_is_trigger_edge(prev, curr, mode)


class TriggeredSubsystem(Subsystem):
    """Deprecated: ``Subsystem`` + 内部 ``Trigger`` block の factory (ADR-0058)。

    v0.21.0 から本クラスは **deprecation 期間の factory** に縮退した。``__new__`` で
    実際には :class:`Subsystem` インスタンスを返し、内部に :class:`Trigger` block を
    追加する。``DeprecationWarning`` を出す。v0.37.0 で削除予定。

    旧 API:
        ``TriggeredSubsystem(trigger_mode="rising", ...)``

    新 API (推奨):
        ``Subsystem(blocks=[..., Trigger(trigger_type="rising")], ...)``

    schema 0.8 → 0.9 migration (``_builtin_migrate_0_8_to_0_9``) が古い JSON を
    自動変換するため、JSON 経由のロードでは本クラスの ``__new__`` は通常呼ばれない
    (= Python API 直接呼び出しの互換性のためだけに残す)。

    Args:
        trigger_mode: ``"rising"`` (default) / ``"falling"`` / ``"either"``。新
            ``Trigger.trigger_type`` に転送される。
        blocks / connections / id / name / layout / mask_params / mask_values:
            :class:`Subsystem` と同形。

    Raises:
        BlockSpecError: ``trigger_mode`` が ``TRIGGER_MODES`` 外 / 廃止引数指定。
    """

    # ADR-0058 §論点 6: 旧 trigger_mode の許容値は 3 種で v3 互換維持。
    # NITS 1: ``__new__`` が ``Subsystem`` instance を返すため、registry/Inspector
    # からは参照されない (= dead code に近い)。v0.37.0 削除予定。本クラス定義の
    # 整合性のために残置。
    _param_enums = {"trigger_mode": TRIGGER_MODES}

    def __new__(  # type: ignore[misc]  # 意図的に Subsystem を返す factory (ADR-0058 §論点 9)
        cls,
        blocks: list[Any] | None = None,
        connections: list[dict[str, Any]] | None = None,
        *,
        trigger_mode: str = "rising",
        id: str | None = None,
        name: str | None = None,
        layout: LayoutDict | None = None,
        mask_params: list[dict[str, Any]] | None = None,
        mask_values: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Subsystem:
        warnings.warn(
            "TriggeredSubsystem is deprecated since v0.21.0 and will be removed in "
            "v4.0.0. Use Subsystem(blocks=[..., Trigger(trigger_type=...)], ...) "
            "directly (= ADR-0058 §論点 9 deprecation). For JSON, schema 0.8 → 0.9 "
            "migration handles the conversion automatically.",
            DeprecationWarning,
            stacklevel=2,
        )
        # trigger_mode を新 Trigger.trigger_type に転送するため、TRIGGER_MODES
        # で検証 (= 旧 API 契約)。
        from ..exceptions import BlockSpecError

        if trigger_mode not in TRIGGER_MODES:
            raise BlockSpecError(
                f"TriggeredSubsystem: trigger_mode must be one of {TRIGGER_MODES}, "
                f"got {trigger_mode!r}"
            )

        # ADR-0058 §論点 9 (SHOULD 3): 旧 API は ``trigger_mode`` で Trigger を
        # 構築する経路。``blocks`` に Trigger を既に含めるのはエラー (= factory が
        # 二重に追加すると ``_build`` で「at most one Trigger」になり原因が
        # 分かりにくいため、ここで明示 reject)。
        if blocks is not None and any(isinstance(b, Trigger) for b in blocks):
            raise BlockSpecError(
                "TriggeredSubsystem: 'blocks' must not contain a Trigger instance "
                "when using the deprecated factory. Either remove the Trigger from "
                "'blocks' or migrate to Subsystem(blocks=[..., Trigger(...)])."
            )

        # 親 Subsystem を構築 (= ADR-0058 §論点 6: 旧 id → Subsystem.id にそのまま転送)
        sub = Subsystem(
            blocks=blocks,
            connections=connections,
            id=id,
            name=name,
            layout=layout,
            mask_params=mask_params,
            mask_values=mask_values,
            **kwargs,
        )
        # ADR-0058 §論点 6: 内部 Trigger の id は決定的 ``{parent_id}_trigger``
        # (Subsystem.id が None なら Trigger も auto-id に任せる)。
        sub_id = sub.id
        trigger_id = f"{sub_id}_trigger" if sub_id is not None else None
        # 検証済 trigger_mode (TRIGGER_MODES の 3 値) は TriggerType の subset。
        # mypy のため cast、実行時は上の TRIGGER_MODES 検証で保証済。
        sub.add(Trigger(trigger_type=cast(TriggerType, trigger_mode), id=trigger_id))
        return sub
