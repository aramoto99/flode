"""``Simulator`` の fold index (``_folded_ids``) 整合性テスト (ADR-0071 §(2))。

``tests/test_block_id.py`` は fold 衝突の拒否そのものを検証済み。本ファイルは
**rename 連鎖 / rename 失敗後の状態不変 / ``_folded_ids`` と ``_blocks_by_id``
の不変条件**という、より境界的なケースを補強する (ADR-0071 §Confidence 未検証 4)。
"""

from __future__ import annotations

import pytest

from flode import BlockSpecError, Simulator, UnknownBlockIdError
from flode.blocks import Constant, Gain
from flode.core.identifiers import fold_block_id
from flode.subsystems import Subsystem


def _assert_fold_index_consistent(sim: Simulator) -> None:
    """``_folded_ids`` と ``_blocks_by_id`` の不変条件をまとめて検証する。

    不変条件: 両辞書の要素数が一致し、``_folded_ids`` の全 value が
    ``_blocks_by_id`` に存在し、各 value の fold key が対応する key と一致する。
    """
    assert len(sim._folded_ids) == len(sim._blocks_by_id)
    for fold_key, nfc_id in sim._folded_ids.items():
        assert nfc_id in sim._blocks_by_id
        assert fold_block_id(nfc_id) == fold_key
    # 逆方向: 全登録済み block の fold key が _folded_ids に存在すること
    for block_id in sim._blocks_by_id:
        assert fold_block_id(block_id) in sim._folded_ids
        assert sim._folded_ids[fold_block_id(block_id)] == block_id


def test_fold_index_consistent_after_multiple_adds() -> None:
    sim = Simulator()
    sim.add(Gain(id="a"))
    sim.add(Gain())  # auto id
    sim.add(Constant(value=1.0, id="速度指令"))
    sim.add(Gain())  # auto id (2nd Gain)
    _assert_fold_index_consistent(sim)
    assert len(sim._blocks_by_id) == 4


def test_fold_index_consistent_through_rename_chain() -> None:
    """A → B → C と連鎖 rename しても、旧 key が残留しない。"""
    sim = Simulator()
    sim.add(Gain(id="A"))
    sim.rename("A", "B")
    _assert_fold_index_consistent(sim)
    assert "A" not in sim._blocks_by_id
    assert fold_block_id("A") not in sim._folded_ids

    sim.rename("B", "C")
    _assert_fold_index_consistent(sim)
    assert "B" not in sim._blocks_by_id
    assert fold_block_id("B") not in sim._folded_ids
    assert "C" in sim._blocks_by_id

    # 解放された旧 fold key ("A" 相当) を新規ブロックが再利用できる
    sim.add(Gain(id="A"))
    _assert_fold_index_consistent(sim)
    assert len(sim._blocks_by_id) == 2


def test_state_unchanged_after_rename_duplicate_failure() -> None:
    """rename が完全一致重複で失敗しても、旧 id の登録状態は一切変化しない。"""
    sim = Simulator()
    sim.add(Gain(id="a"))
    sim.add(Gain(id="b"))
    before_blocks = dict(sim._blocks_by_id)
    before_folded = dict(sim._folded_ids)

    with pytest.raises(BlockSpecError, match="already exists"):
        sim.rename("a", "b")

    assert sim._blocks_by_id == before_blocks
    assert sim._folded_ids == before_folded
    _assert_fold_index_consistent(sim)
    # "a" は依然として解決できる (rename が部分適用されていない)
    assert sim.get_block("a").id == "a"


def test_state_unchanged_after_rename_confusable_failure() -> None:
    """NFKC fold 衝突で rename が失敗しても、fold index が部分的に壊れない。"""
    sim = Simulator()
    sim.add(Gain(id="ソクド"))
    sim.add(Gain(id="a"))
    before_blocks = dict(sim._blocks_by_id)
    before_folded = dict(sim._folded_ids)

    with pytest.raises(BlockSpecError, match="NFKC-equivalent"):
        sim.rename("a", "ｿｸﾄﾞ")  # 半角カナ (ソクド と fold 衝突)

    assert sim._blocks_by_id == before_blocks
    assert sim._folded_ids == before_folded
    _assert_fold_index_consistent(sim)


def test_state_unchanged_after_rename_invalid_charset_failure() -> None:
    """文字集合違反で rename が失敗しても登録状態は不変。"""
    sim = Simulator()
    sim.add(Gain(id="a"))
    before_blocks = dict(sim._blocks_by_id)
    before_folded = dict(sim._folded_ids)

    with pytest.raises(BlockSpecError):
        sim.rename("a", "1bad")

    assert sim._blocks_by_id == before_blocks
    assert sim._folded_ids == before_folded


def test_state_unchanged_after_rename_unknown_id_failure() -> None:
    sim = Simulator()
    sim.add(Gain(id="a"))
    before_blocks = dict(sim._blocks_by_id)
    before_folded = dict(sim._folded_ids)

    with pytest.raises(UnknownBlockIdError):
        sim.rename("missing", "b")

    assert sim._blocks_by_id == before_blocks
    assert sim._folded_ids == before_folded


def test_rename_back_to_original_fold_key_after_intermediate_rename() -> None:
    """A→B→(全角 A) と辿っても、B が解放されていれば衝突しない。"""
    sim = Simulator()
    sim.add(Gain(id="Gain_1"))
    sim.rename("Gain_1", "Gain_2")
    # 解放された "Gain_1" の fold key を全角形で再取得できる
    sim.rename("Gain_2", "Ｇａｉｎ＿１")
    _assert_fold_index_consistent(sim)
    assert "Ｇａｉｎ＿１" in sim._blocks_by_id
    assert fold_block_id("Ｇａｉｎ＿１") == "Gain_1"


def test_subsystem_inner_scope_independent_from_simulator_top_level() -> None:
    """Subsystem 内部ブロックの名前空間は Simulator 直下と独立している (ADR-0071 §(2))。

    同じ id 文字列がトップレベルと Subsystem 内部で共存でき、Simulator の
    ``_folded_ids`` は Subsystem 内部の登録を一切追跡しない。
    """
    sim = Simulator()
    top = sim.add(Gain(id="Gain_1"))

    sub = Subsystem(id="Sub_0")
    inner = sub.add(Gain(id="Gain_1"))  # トップレベルと同名だが別スコープ
    sim.add(sub)

    _assert_fold_index_consistent(sim)
    # Simulator の登録数は top-level ブロックのみ (Sub_0 の内部は含まない)
    assert set(sim._blocks_by_id) == {"Gain_1", "Sub_0"}
    assert sim.get_block("Gain_1") is top
    assert sub.get_block("Gain_1") is inner
    assert top is not inner
