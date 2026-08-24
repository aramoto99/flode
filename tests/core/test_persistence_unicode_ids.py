"""ADR-0071 非 ASCII block id の永続化テスト。

- ``Simulator.save`` が ``ensure_ascii=False`` で生 UTF-8 を書くこと (§(7))
- load 時に id とその全参照が単一関数で NFC 正規化されること (§(3))
- ``normalize_model_ids`` の参照一括正規化 (layout / branch_waypoints /
  scope_settings / Subsystem params 再帰)
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from flode import Simulator
from flode.blocks import Constant, Gain
from flode.core.persistence import normalize_model_ids

# NFD の「がいん」(か U+304B + 結合濁点 U+3099 + いん)。ソース中では NFC と
# 見分けが付かないため、明示的にコードポイントから構築する。
_NFD_GAIN = "がいん"
_NFC_GAIN = unicodedata.normalize("NFC", _NFD_GAIN)  # がいん (合成済)


def _build_japanese_model() -> Simulator:
    sim = Simulator(t_end=1.0, dt=0.01)
    sim.add(Constant(value=2.0, id="入力"))
    sim.add(Gain(k=3.0, id="速度指令"))
    sim.connect("入力", "速度指令")
    return sim


def test_save_writes_raw_utf8(tmp_path: Path) -> None:
    """ADR-0071 §(7): 非 ASCII id を \\uXXXX エスケープせず生 UTF-8 で書く。"""
    path = tmp_path / "jp.flw.json"
    _build_japanese_model().save(path)
    text = path.read_text(encoding="utf-8")
    assert "速度指令" in text
    assert "\\u" not in text  # エスケープが混ざらない (GUI 保存経路とバイト一致)


def test_japanese_id_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "jp.flw.json"
    _build_japanese_model().save(path)
    sim2 = Simulator.load(path)
    g = sim2.get_block("速度指令")
    assert g.input_sources[0] is not None
    assert g.input_sources[0][0].id == "入力"
    sim2.run()  # 非 ASCII id を含むモデルが実行まで通ること (例外を出さない)


def test_from_dict_normalizes_nfd_ids_and_references(tmp_path: Path) -> None:
    """NFD 形の id / connections / layout キーが load で一括 NFC 正規化される。"""
    path = tmp_path / "base.flw.json"
    sim = Simulator(t_end=1.0, dt=0.01)
    sim.add(Constant(value=1.0, id="src"))
    sim.add(Gain(k=2.0, id="temp"))
    sim.connect("src", "temp")
    sim.save(path, layout={"src": {"x": 0, "y": 0}, "temp": {"x": 100, "y": 0}})

    data = json.loads(path.read_text(encoding="utf-8"))
    # "temp" を NFD の「がいん」に書き換える (macOS 由来テキスト混入の再現)
    data["blocks"][1]["id"] = _NFD_GAIN
    data["connections"][0]["dst"] = _NFD_GAIN
    data["layout"][_NFD_GAIN] = data["layout"].pop("temp")

    sim2 = Simulator.from_dict(data)
    # id は NFC で格納され、NFD の参照 (connections / layout) も追従している
    g = sim2.get_block(_NFC_GAIN)
    assert g.input_sources[0] is not None
    assert sim2.last_loaded_layout is not None
    assert _NFC_GAIN in sim2.last_loaded_layout
    assert _NFD_GAIN not in sim2.last_loaded_layout


def test_normalize_model_ids_all_reference_sections() -> None:
    """layout / branch_waypoints / scope_settings / Subsystem params の一括正規化。"""
    data = {
        "blocks": [
            {"id": _NFD_GAIN, "type": "flode.blocks.mathops.Gain", "params": {"k": 1}},
            {
                "id": "sub",
                "type": "flode.subsystems.Subsystem",
                "params": {
                    "blocks": [
                        {
                            "id": _NFD_GAIN,
                            "type": "flode.subsystems.Inport",
                            "params": {"port_idx": 0},
                        }
                    ],
                    "connections": [
                        {"src": _NFD_GAIN, "dst": _NFD_GAIN, "src_idx": 0, "dst_idx": 0}
                    ],
                    "layout": {_NFD_GAIN: {"x": 0, "y": 0}},
                    "branch_waypoints": {f"{_NFD_GAIN}:0": {"axis": "x", "pos": 1}},
                },
            },
        ],
        "connections": [{"src": _NFD_GAIN, "dst": "sub", "src_idx": 0, "dst_idx": 0}],
        "layout": {_NFD_GAIN: {"x": 0, "y": 0}},
        "branch_waypoints": {f"{_NFD_GAIN}:2": {"axis": "y", "pos": 5}},
        "scope_settings": {_NFD_GAIN: {"y_min": -1}},
    }
    out = normalize_model_ids(data)

    assert out["blocks"][0]["id"] == _NFC_GAIN
    assert out["connections"][0]["src"] == _NFC_GAIN
    assert list(out["layout"].keys()) == [_NFC_GAIN]
    assert list(out["branch_waypoints"].keys()) == [f"{_NFC_GAIN}:2"]
    assert list(out["scope_settings"].keys()) == [_NFC_GAIN]
    inner = out["blocks"][1]["params"]
    assert inner["blocks"][0]["id"] == _NFC_GAIN
    assert inner["connections"][0]["src"] == _NFC_GAIN
    assert list(inner["layout"].keys()) == [_NFC_GAIN]
    assert list(inner["branch_waypoints"].keys()) == [f"{_NFC_GAIN}:0"]
    # 入力 dict は破壊しない
    assert data["blocks"][0]["id"] == _NFD_GAIN


def test_normalize_model_ids_ascii_identity() -> None:
    """ASCII のみのモデルでは実質恒等 (値が変わらない)。"""
    data = {
        "blocks": [{"id": "Gain_0", "type": "t", "params": {}}],
        "connections": [{"src": "Gain_0", "dst": "Gain_0", "src_idx": 0, "dst_idx": 0}],
        "layout": {"Gain_0": {"x": 0, "y": 0}},
    }
    out = normalize_model_ids(data)
    assert out == data
