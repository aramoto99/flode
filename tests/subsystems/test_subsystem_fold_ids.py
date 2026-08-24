"""``Subsystem.add`` の NFKC fold 突合テスト (ADR-0071 §(2))。

``Simulator.add`` と同じく、Subsystem 内部スコープでも「見た目が近く実体が違う
id」(全角/半角違い等) の共存を拒否することを検証する (test-writer が発見した
スコープギャップの修正、SPEC-0022)。
"""

from __future__ import annotations

import pytest

from flode import BlockSpecError
from flode.blocks import Gain
from flode.subsystems import Subsystem


def test_subsystem_add_rejects_nfkc_confusable_id() -> None:
    sub = Subsystem(id="Sub_0")
    sub.add(Gain(id="Gain_1"))
    with pytest.raises(BlockSpecError, match="NFKC-equivalent"):
        sub.add(Gain(id="Gain_１"))  # 全角の１


def test_subsystem_add_rejects_halfwidth_fullwidth_kana_pair() -> None:
    sub = Subsystem(id="Sub_0")
    sub.add(Gain(id="ソクド"))
    with pytest.raises(BlockSpecError, match="NFKC-equivalent"):
        sub.add(Gain(id="ｿｸﾄﾞ"))


def test_subsystem_auto_id_skips_fold_collision() -> None:
    sub = Subsystem(id="Sub_0")
    sub.add(Gain(id="Ｇａｉｎ＿０"))  # fold key = "Gain_0"
    g = sub.add(Gain())
    assert g.id == "Gain_1"


def test_subsystem_fold_index_consistent_with_blocks_by_id() -> None:
    sub = Subsystem(id="Sub_0")
    sub.add(Gain(id="速度"))
    sub.add(Gain(id="Gain_0"))
    assert len(sub._inner_folded_ids) == len(sub._inner_blocks_by_id)
    assert set(sub._inner_folded_ids.values()) == set(sub._inner_blocks_by_id.keys())
