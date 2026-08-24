"""``normalize_model_ids`` の不正形データへの耐性テスト (ADR-0071 §(3))。

``tests/core/test_persistence_unicode_ids.py`` は正常形データの一括正規化を
網羅済み。本ファイルは「壊れた / 想定外の shape の dict が来ても例外にならず、
正規化できる箇所だけ正規化して残りは素通しする」ことを検証する
(load 時の防御的実装の回帰ガード)。
"""

from __future__ import annotations

import unicodedata

from flode.core.persistence import normalize_model_ids

# ソースファイルは通常 NFC で保存されるため、リテラルではなく明示的に
# unicodedata.normalize("NFD", ...) で構築する (test_persistence_unicode_ids.py と同じ注意)。
_NFC_GAIN = "がいん"
_NFD_GAIN = unicodedata.normalize("NFD", _NFC_GAIN)  # か + 結合濁点 (U+3099) + いん


def test_blocks_list_with_non_dict_element_does_not_crash() -> None:
    """``blocks`` 内に dict でない要素 (文字列 / None) が混じっても例外にならない。"""
    data = {
        "blocks": [
            {"id": _NFD_GAIN, "type": "flode.blocks.mathops.Gain", "params": {}},
            "not_a_block",
            None,
            42,
        ],
    }
    out = normalize_model_ids(data)
    assert out["blocks"][0]["id"] == _NFC_GAIN
    # 不正形要素はそのまま素通し (identity)
    assert out["blocks"][1] == "not_a_block"
    assert out["blocks"][2] is None
    assert out["blocks"][3] == 42


def test_block_entry_without_id_key_does_not_crash() -> None:
    """``id`` キーが存在しない block entry でも KeyError にならない。"""
    data = {"blocks": [{"type": "flode.blocks.mathops.Gain", "params": {}}]}
    out = normalize_model_ids(data)
    assert out["blocks"][0] == {"type": "flode.blocks.mathops.Gain", "params": {}}


def test_branch_waypoints_key_without_colon_left_untouched() -> None:
    """``:`` を含まない不正形 waypoint キーは正規化せずそのまま残す。"""
    data = {
        "branch_waypoints": {
            "malformed_key_no_colon": {"axis": "x", "pos": 1},
            f"{_NFD_GAIN}:0": {"axis": "y", "pos": 2},
        },
    }
    out = normalize_model_ids(data)
    assert "malformed_key_no_colon" in out["branch_waypoints"]
    assert out["branch_waypoints"]["malformed_key_no_colon"] == {"axis": "x", "pos": 1}
    assert f"{_NFC_GAIN}:0" in out["branch_waypoints"]
    assert f"{_NFD_GAIN}:0" not in out["branch_waypoints"]


def test_subsystem_params_blocks_null_skips_recursion_without_crash() -> None:
    """Subsystem の ``params.blocks`` が ``null`` (registry default) でも例外にならない。

    実運用では ``resolve_block_class`` 前に ``registry`` から default で
    ``blocks: None`` が来るケースがある (frontend ``buildDefaultParams`` の
    docstring参照)。normalize_model_ids はこの params を単に素通しする。
    """
    data = {
        "blocks": [
            {
                "id": "sub",
                "type": "flode.subsystems.Subsystem",
                "params": {"blocks": None, "connections": None},
            },
        ],
    }
    out = normalize_model_ids(data)
    assert out["blocks"][0]["id"] == "sub"
    assert out["blocks"][0]["params"] == {"blocks": None, "connections": None}


def test_connections_list_with_non_dict_element_does_not_crash() -> None:
    data = {
        "connections": [
            {"src": _NFD_GAIN, "dst": "x", "src_idx": 0, "dst_idx": 0},
            "not_a_connection",
            None,
        ],
    }
    out = normalize_model_ids(data)
    assert out["connections"][0]["src"] == _NFC_GAIN
    assert out["connections"][1] == "not_a_connection"
    assert out["connections"][2] is None


def test_top_level_blocks_none_does_not_crash() -> None:
    """``blocks`` キー自体が ``None`` / 欠落でも normalize_model_ids は安全に動作する。"""
    data: dict = {"blocks": None, "connections": None, "layout": None}
    out = normalize_model_ids(data)
    assert out["blocks"] is None
    assert out["connections"] is None
    assert out["layout"] is None


def test_missing_optional_sections_does_not_crash() -> None:
    """``layout`` / ``branch_waypoints`` / ``scope_settings`` が丸ごと欠落していても動く。"""
    data = {"blocks": [{"id": "a", "type": "t", "params": {}}]}
    out = normalize_model_ids(data)
    assert out["blocks"][0]["id"] == "a"
    assert "layout" not in out
    assert "branch_waypoints" not in out


def test_non_dict_input_returns_identity() -> None:
    """``data`` 自体が dict でない場合はそのまま返す (呼び出し側の防御)。"""
    assert normalize_model_ids(None) is None  # type: ignore[arg-type]
    assert normalize_model_ids("not_a_model") == "not_a_model"  # type: ignore[arg-type]
