"""ADR-0004 ブロック ID 規則のテスト。"""

from __future__ import annotations

import logging

import pytest

from flode import (
    BlockSpecError,
    Simulator,
    UnknownBlockIdError,
)
from flode.blocks import Constant, Gain, Step


def test_auto_id_per_type_counter():
    sim = Simulator()
    g0 = sim.add(Gain())
    g1 = sim.add(Gain())
    g2 = sim.add(Gain())
    s0 = sim.add(Step())
    g3 = sim.add(Gain())

    assert g0.id == "Gain_0"
    assert g1.id == "Gain_1"
    assert g2.id == "Gain_2"
    assert s0.id == "Step_0"
    assert g3.id == "Gain_3"


def test_auto_id_skips_user_specified_collision():
    sim = Simulator()
    sim.add(Gain(id="Gain_0"))
    g_auto = sim.add(Gain())
    assert g_auto.id == "Gain_1"


def test_explicit_id_collision_raises():
    sim = Simulator()
    sim.add(Gain(id="motor"))
    with pytest.raises(BlockSpecError, match="already exists"):
        sim.add(Gain(id="motor"))


def test_invalid_id_characters():
    # ADR-0071: 日本語 (非 ASCII 文字) は valid になった。記号・空白は引き続き拒否
    bad_ids = ["1/m", "my block", "123abc", "x.y", "x-y", "a:b", ""]
    for bad in bad_ids:
        with pytest.raises(BlockSpecError):
            Gain(id=bad)


def test_japanese_id_ok():
    """ADR-0071: 日本語ブロック名を許容する。"""
    g = Gain(id="トルクゲイン")
    assert g.id == "トルクゲイン"


def test_id_normalized_to_nfc_at_entry():
    """ADR-0071 §(3): NFD 入力は入口層で NFC に正規化して格納される。"""
    nfd = "がいん"  # か + 結合濁点 U+3099 (NFD)
    g = Gain(id=nfd)
    assert g.id == "がいん"  # NFC 合成済
    assert g.id != nfd


def test_add_rejects_nfkc_confusable_id():
    """ADR-0071 §(2): 全角/半角違いの見た目類似 id の共存を拒否する。"""
    sim = Simulator()
    sim.add(Gain(id="Gain_1"))
    with pytest.raises(BlockSpecError, match="NFKC-equivalent"):
        sim.add(Gain(id="Gain_１"))  # 全角の１


def test_rename_rejects_nfkc_confusable_id():
    sim = Simulator()
    sim.add(Gain(id="ソクド"))
    sim.add(Gain(id="a"))
    with pytest.raises(BlockSpecError, match="NFKC-equivalent"):
        sim.rename("a", "ｿｸﾄﾞ")  # 半角カナ


def test_rename_normalizes_nfc():
    sim = Simulator()
    sim.add(Gain(id="a"))
    sim.rename("a", "がいん")  # NFD 入力
    assert "がいん" in sim._blocks_by_id  # NFC で格納される


def test_rename_updates_fold_index():
    """rename 後は旧 fold key が解放され、新 fold key が予約される。"""
    sim = Simulator()
    sim.add(Gain(id="ソクド"))
    sim.rename("ソクド", "トルク")
    # 旧 id の fold key が解放されたので半角カナ版を新規追加できる
    sim.add(Gain(id="ｿｸﾄﾞ"))
    with pytest.raises(BlockSpecError, match="NFKC-equivalent"):
        sim.add(Gain(id="ﾄﾙｸ"))


def test_auto_id_skips_fold_collision():
    """全角形 (Ｇａｉｎ＿０) が居ても自動採番は例外を出さずスキップする。"""
    sim = Simulator()
    sim.add(Gain(id="Ｇａｉｎ＿０"))  # fold key = "Gain_0"
    g = sim.add(Gain())
    assert g.id == "Gain_1"


def test_id_too_long():
    with pytest.raises(BlockSpecError, match="exceeds max length"):
        Gain(id="a" * 65)


def test_id_max_length_ok():
    g = Gain(id="a" * 64)
    assert g.id == "a" * 64


def test_python_keyword_id_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="flode.identifiers"):
        g = Gain(id="for")
    assert g.id == "for"
    assert any("Python keyword" in r.message for r in caplog.records)


def test_name_alias_phase0_compat():
    g = Gain(name="g")
    assert g.id == "g"
    assert g.name == "g"


def test_id_and_name_both_raise():
    with pytest.raises(BlockSpecError, match="both be set"):
        Gain(id="x", name="y")


def test_connect_by_id_string():
    sim = Simulator()
    sim.add(Constant(value=1.0, id="src"))
    sim.add(Gain(k=2.0, id="g"))
    sim.connect("src", "g")
    g = sim.get_block("g")
    assert g.input_sources[0] is not None
    assert g.input_sources[0][0].id == "src"


def test_connect_unknown_id_raises():
    sim = Simulator()
    sim.add(Gain(id="g"))
    with pytest.raises(UnknownBlockIdError):
        sim.connect("missing", "g")


def test_get_block_unknown_raises():
    sim = Simulator()
    with pytest.raises(UnknownBlockIdError):
        sim.get_block("missing")


def test_rename_preserves_connections():
    sim = Simulator()
    sim.add(Constant(value=3.0, id="c"))
    sim.add(Gain(k=2.0, id="g"))
    sim.connect("c", "g")
    sim.rename("c", "constant_input")

    g = sim.get_block("g")
    assert g.input_sources[0][0].id == "constant_input"
    assert "c" not in sim._blocks_by_id
    assert "constant_input" in sim._blocks_by_id


def test_rename_to_existing_raises():
    sim = Simulator()
    sim.add(Gain(id="a"))
    sim.add(Gain(id="b"))
    with pytest.raises(BlockSpecError, match="already exists"):
        sim.rename("a", "b")


def test_rename_unknown_raises():
    sim = Simulator()
    with pytest.raises(UnknownBlockIdError):
        sim.rename("missing", "newid")


def test_rename_invalid_id_raises():
    sim = Simulator()
    sim.add(Gain(id="a"))
    with pytest.raises(BlockSpecError):
        sim.rename("a", "1/bad")


def test_rename_same_id_noop():
    sim = Simulator()
    sim.add(Gain(id="a"))
    sim.rename("a", "a")
    assert "a" in sim._blocks_by_id


def test_auto_id_does_not_reuse_after_collision():
    """ユーザーが先に Gain_2 を取った後の自動採番が正しくスキップする。"""
    sim = Simulator()
    sim.add(Gain())
    sim.add(Gain(id="Gain_2"))
    g3 = sim.add(Gain())
    assert g3.id == "Gain_1"
    g4 = sim.add(Gain())
    assert g4.id == "Gain_3"
