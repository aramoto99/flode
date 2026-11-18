"""信号名 (``signal_names``, ADR-0087) の backend 側の扱いのテスト。

信号名は GUI だけが使う付加情報で、backend は構築前に全スコープから取り除く。
取り除くときに名前の規則 (SPEC-0038 D6) を検査し、違反の件数だけを警告に出す。
"""

from __future__ import annotations

import copy
import json
import logging
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from flode import Simulator
from flode.core.persistence import (
    GUI_ONLY_SCOPE_KEYS,
    MAX_SIGNAL_NAME_CHARS,
    is_valid_signal_name,
    normalize_model_ids,
    strip_gui_only_scope_keys,
)

_NFC_ID = unicodedata.normalize("NFC", "ゲイン")
_NFD_ID = unicodedata.normalize("NFD", "ゲイン")


def _inner(k: object, signal_names: dict[str, Any] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {
        "blocks": [
            {"id": "i", "type": "flode.subsystems.ports.Inport", "params": {"port_idx": 0}},
            {"id": "g", "type": "flode.blocks.mathops.Gain", "params": {"k": k}},
            {"id": "o", "type": "flode.subsystems.ports.Outport", "params": {"port_idx": 0}},
        ],
        "connections": [
            {"src": "i", "src_idx": 0, "dst": "g", "dst_idx": 0},
            {"src": "g", "src_idx": 0, "dst": "o", "dst_idx": 0},
        ],
    }
    if signal_names is not None:
        params["signal_names"] = signal_names
    return {"id": "inner", "type": "flode.subsystems.subsystem.Subsystem", "params": params}


def _outer(inner: dict[str, Any], *, masked: bool) -> dict[str, Any]:
    params: dict[str, Any] = {
        "blocks": [
            {"id": "i", "type": "flode.subsystems.ports.Inport", "params": {"port_idx": 0}},
            inner,
            {"id": "o", "type": "flode.subsystems.ports.Outport", "params": {"port_idx": 0}},
        ],
        "connections": [
            {"src": "i", "src_idx": 0, "dst": "inner", "dst_idx": 0},
            {"src": "inner", "src_idx": 0, "dst": "o", "dst_idx": 0},
        ],
    }
    if masked:
        params["mask_params"] = [{"name": "Kp", "type": "float", "default": 1.0}]
        params["mask_values"] = {"Kp": 3.0}
    return {"id": "outer", "type": "flode.subsystems.subsystem.Subsystem", "params": params}


def _model(outer: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "0.15",
        "simulator": {
            "t_end": 0.05,
            "dt": 0.01,
            "solver": "RK45",
            "rtol": 1e-6,
            "atol": 1e-9,
            "dt_base": None,
        },
        "blocks": [
            {"id": "c", "type": "flode.blocks.sources.Constant", "params": {"value": 1.0}},
            outer,
            {"id": "sc", "type": "flode.blocks.sinks.Scope", "params": {"n_inputs": 1}},
        ],
        "connections": [
            {"src": "c", "src_idx": 0, "dst": "outer", "dst_idx": 0},
            {"src": "outer", "src_idx": 0, "dst": "sc", "dst_idx": 0},
        ],
    }


def _run_values(data: dict[str, Any]) -> np.ndarray:
    sim = Simulator.from_dict(data)
    sim.run()
    return np.asarray(sim.get_block("sc").values)


# --- 名前の規則 (D6) ---------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["a", "左脚の力", "x" * MAX_SIGNAL_NAME_CHARS, "  padded  ", "é", "😀", "$Kp", "a b"],
    ids=["ascii", "japanese", "max-length", "padded", "combining", "emoji", "dollar", "space"],
)
def test_valid_signal_names(value: str) -> None:
    assert is_valid_signal_name(value)


@pytest.mark.parametrize(
    "value",
    [
        1,
        None,
        ["a"],
        "",
        "   ",
        "x" * (MAX_SIGNAL_NAME_CHARS + 1),
        "a\nb",
        "a\rb",
        "a\tb",
        "a\x00b",
        "a b",
        "a b",
        "a\ud800b",
    ],
    ids=[
        "int",
        "none",
        "list",
        "empty",
        "blank",
        "too-long",
        "lf",
        "cr",
        "tab",
        "nul",
        "line-sep",
        "para-sep",
        "lone-surrogate",
    ],
)
def test_invalid_signal_names(value: object) -> None:
    assert not is_valid_signal_name(value)


def test_length_is_counted_after_nfc() -> None:
    """結合文字は NFC で 1 コードポイントになるなら 1 文字と数える。"""
    decomposed = "é" * MAX_SIGNAL_NAME_CHARS  # NFC で "é" * 64
    assert len(decomposed) > MAX_SIGNAL_NAME_CHARS
    assert is_valid_signal_name(decomposed)


def test_max_chars_is_64() -> None:
    assert MAX_SIGNAL_NAME_CHARS == 64


# --- strip_gui_only_scope_keys ----------------------------------------------


def test_signal_names_is_a_gui_only_key() -> None:
    assert "signal_names" in GUI_ONLY_SCOPE_KEYS


def test_strip_removes_signal_names_at_every_scope() -> None:
    inner = _inner(2.0, {"g:0": "gain out"})
    outer = _outer(inner, masked=False)
    outer["params"]["signal_names"] = {"inner:0": "inner out"}
    data = _model(outer)
    data["signal_names"] = {"c:0": "const"}

    out = strip_gui_only_scope_keys(data)

    assert "signal_names" not in out
    outer_params = out["blocks"][1]["params"]
    assert "signal_names" not in outer_params
    assert "signal_names" not in outer_params["blocks"][1]["params"]


def test_strip_valid_names_emits_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    data = _model(_outer(_inner(2.0, {"g:0": "ok"}), masked=False))
    data["signal_names"] = {"c:0": "名前"}

    with caplog.at_level(logging.WARNING, logger="flode"):
        strip_gui_only_scope_keys(data)

    assert not [r for r in caplog.records if "signal_names" in r.getMessage()]


def test_strip_warns_invalid_names_with_count_and_path(caplog: pytest.LogCaptureFixture) -> None:
    secret = "y" * (MAX_SIGNAL_NAME_CHARS + 1)
    inner = _inner(2.0, {"g:0": 5, "i:0": secret, "o:0": "a\nb", "g:1": "fine"})
    data = _model(_outer(inner, masked=False))
    data["signal_names"] = {"c:0": "ok", "bad-key": "x"}

    with caplog.at_level(logging.WARNING, logger="flode"):
        strip_gui_only_scope_keys(data)

    messages = [r.getMessage() for r in caplog.records if "signal_names" in r.getMessage()]
    assert len(messages) == 2
    inner_msg = next(m for m in messages if "outer/inner" in m)
    assert "3" in inner_msg
    top_msg = next(m for m in messages if m is not inner_msg)
    assert "1" in top_msg
    # 値そのものはログに出さない (長さ増幅を避ける)
    assert all(secret not in m for m in messages)


def test_key_with_trailing_newline_is_counted_invalid(caplog: pytest.LogCaptureFixture) -> None:
    """``"c:0\\n"`` は正しいキーではない (frontend も無視する)。"""
    data = _model(_outer(_inner(2.0), masked=False))
    data["signal_names"] = {"c:0\n": "x"}

    with caplog.at_level(logging.WARNING, logger="flode"):
        strip_gui_only_scope_keys(data)

    assert any("signal_names" in r.getMessage() for r in caplog.records)


def test_strip_warns_when_signal_names_is_not_a_dict(caplog: pytest.LogCaptureFixture) -> None:
    data = _model(_outer(_inner(2.0), masked=False))
    data["signal_names"] = ["not", "a", "dict"]

    with caplog.at_level(logging.WARNING, logger="flode"):
        out = strip_gui_only_scope_keys(data)

    assert "signal_names" not in out
    assert any("signal_names" in r.getMessage() for r in caplog.records)


# --- Simulator.from_dict / run -----------------------------------------------


@pytest.mark.parametrize(
    ("masked", "k", "expected"),
    [(False, 2.0, 2.0), (True, "$Kp", 3.0)],
    ids=["plain", "masked_outer"],
)
@pytest.mark.parametrize("where", ["top", "outer", "inner", "all"])
def test_model_with_signal_names_loads_and_runs_identically(
    masked: bool, k: object, expected: float, where: str
) -> None:
    """名前 (マスクの placeholder に見える ``"$Kp"`` を含む) は結果に影響しない。"""
    plain = _model(_outer(_inner(k), masked=masked))
    named = copy.deepcopy(plain)
    outer_params = named["blocks"][1]["params"]
    inner_params = outer_params["blocks"][1]["params"]
    if where in ("top", "all"):
        named["signal_names"] = {"c:0": "$Kp", "outer:0": "出力"}
    if where in ("outer", "all"):
        outer_params["signal_names"] = {"inner:0": "$Kp"}
    if where in ("inner", "all"):
        inner_params["signal_names"] = {"g:0": "$Kp", "i:0": "$Undeclared"}

    values = _run_values(named)

    np.testing.assert_allclose(values[:, 0], expected)
    np.testing.assert_array_equal(values, _run_values(plain))


def test_invalid_names_do_not_fail_loading(caplog: pytest.LogCaptureFixture) -> None:
    inner = _inner(2.0, {"g:0": 12, "i:0": "z" * 65, "o:0": "line\nbreak"})
    data = _model(_outer(inner, masked=False))
    data["signal_names"] = {"c:0": None}

    with caplog.at_level(logging.WARNING, logger="flode"):
        values = _run_values(data)

    np.testing.assert_allclose(values[:, 0], 2.0)
    assert any("signal_names" in r.getMessage() for r in caplog.records)


def test_from_dict_does_not_mutate_input() -> None:
    data = _model(_outer(_inner(2.0, {"g:0": "n"}), masked=False))
    data["signal_names"] = {"c:0": "n"}
    before = copy.deepcopy(data)

    Simulator.from_dict(data)

    assert data == before


def test_save_does_not_write_signal_names(tmp_path: Path) -> None:
    """D7: Python 側では扱わないので ``Simulator.save`` には残らない。"""
    data = _model(_outer(_inner(2.0, {"g:0": "n"}), masked=False))
    data["signal_names"] = {"c:0": "n"}
    path = tmp_path / "m.flw.json"

    Simulator.from_dict(data).save(path)

    assert "signal_names" not in path.read_text(encoding="utf-8")


def test_save_bytes_unchanged_for_model_without_names(tmp_path: Path) -> None:
    """名前を付けないモデルは保存結果が今までと同じ (名前付きと同じバイト列になる)。"""
    plain = _model(_outer(_inner(2.0), masked=False))
    named = copy.deepcopy(plain)
    named["signal_names"] = {"c:0": "n"}
    a, b = tmp_path / "a.flw.json", tmp_path / "b.flw.json"

    Simulator.from_dict(plain).save(a)
    Simulator.from_dict(named).save(b)

    assert a.read_bytes() == b.read_bytes()
    assert "signal_names" not in json.loads(a.read_text(encoding="utf-8"))


# --- normalize_model_ids -----------------------------------------------------


def test_normalize_model_ids_normalizes_signal_name_keys() -> None:
    data = {
        "blocks": [
            {"id": _NFD_ID, "type": "flode.blocks.mathops.Gain", "params": {"k": 1}},
            {
                "id": "sub",
                "type": "flode.subsystems.Subsystem",
                "params": {
                    "blocks": [],
                    "connections": [],
                    "signal_names": {f"{_NFD_ID}:0": "inner"},
                },
            },
        ],
        "connections": [],
        "signal_names": {f"{_NFD_ID}:1": "top", "plain:0": "p"},
    }

    out = normalize_model_ids(data)

    assert out["signal_names"] == {f"{_NFC_ID}:1": "top", "plain:0": "p"}
    assert out["blocks"][1]["params"]["signal_names"] == {f"{_NFC_ID}:0": "inner"}
    # 入力 dict は変えない
    assert list(data["signal_names"]) == [f"{_NFD_ID}:1", "plain:0"]


def test_normalize_model_ids_warns_on_signal_name_key_collision(
    caplog: pytest.LogCaptureFixture,
) -> None:
    data = {
        "blocks": [],
        "connections": [],
        "signal_names": {f"{_NFD_ID}:0": "a", f"{_NFC_ID}:0": "b"},
    }

    with caplog.at_level(logging.WARNING, logger="flode"):
        out = normalize_model_ids(data)

    assert len(out["signal_names"]) == 1
    assert any("signal_names" in r.getMessage() for r in caplog.records)
