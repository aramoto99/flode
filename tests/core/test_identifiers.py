"""``flode.core.identifiers`` のテスト (ADR-0071 ケース表駆動)。

共有ケース表 ``tests/data/block_id_cases.json`` を読み、``validate_block_id`` の
判定が表と一致することを検証する。同じ表を frontend
(``flode/web/frontend/tests/blockIdValidation.test.ts``) も読むため、Python /
TypeScript の検証規則の乖離はどちらかのテストが落ちることで検出される
(ADR-0071 §(9))。
"""

from __future__ import annotations

import json
import logging
import unicodedata
from pathlib import Path

import pytest

from flode.core.identifiers import (
    fold_block_id,
    normalize_block_id,
    validate_block_id,
    validate_model_id,
)
from flode.exceptions import BlockSpecError

_CASES_PATH = Path(__file__).resolve().parents[1] / "data" / "block_id_cases.json"
_TABLE = json.loads(_CASES_PATH.read_text(encoding="utf-8"))


def _case_id(case: dict) -> str:
    # pytest の表示用 id。制御文字を含むケースがあるので repr で潰す
    return repr(case["id"])[:40]


@pytest.mark.parametrize("case", _TABLE["cases"], ids=_case_id)
def test_validate_block_id_matches_case_table(case: dict) -> None:
    if case["valid"]:
        validate_block_id(case["id"])  # raise しないこと
    else:
        with pytest.raises(BlockSpecError):
            validate_block_id(case["id"])


@pytest.mark.parametrize(
    "case",
    [c for c in _TABLE["cases"] if c.get("keyword")],
    ids=_case_id,
)
def test_keyword_ids_warn_but_pass(case: dict, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="flode.identifiers"):
        validate_block_id(case["id"])
    assert any("keyword" in r.message.lower() for r in caplog.records)


@pytest.mark.parametrize("pair", _TABLE["fold_conflicts"], ids=lambda p: repr(p["a"]))
def test_fold_conflicts_collide(pair: dict) -> None:
    assert fold_block_id(pair["a"]) == fold_block_id(pair["b"])


@pytest.mark.parametrize("pair", _TABLE["fold_distinct"], ids=lambda p: repr(p["a"]))
def test_fold_distinct_do_not_collide(pair: dict) -> None:
    assert fold_block_id(pair["a"]) != fold_block_id(pair["b"])


def test_normalize_block_id_nfc() -> None:
    nfd = "がいん"  # か + 結合濁点 + いん
    nfc = normalize_block_id(nfd)
    assert nfc == "がいん"  # がいん (合成済)
    assert unicodedata.is_normalized("NFC", nfc)
    # NFC 済み文字列は恒等
    assert normalize_block_id("速度指令") == "速度指令"
    assert normalize_block_id("Gain_0") == "Gain_0"


def test_normalized_nfd_input_becomes_valid() -> None:
    """述語としては NFD は invalid だが、入口層の normalize 後は valid (ADR-0071 §(3))。"""
    nfd = "がいん"
    with pytest.raises(BlockSpecError):
        validate_block_id(nfd)
    validate_block_id(normalize_block_id(nfd))


def test_fold_is_comparison_only_not_identity() -> None:
    """fold key は比較専用で、NFC 形と異なりうる (保存しない、ADR-0071 §(2))。"""
    assert fold_block_id("Ｇａｉｎ") == "Gain"
    assert normalize_block_id("Ｇａｉｎ") == "Ｇａｉｎ"


def test_validate_block_id_non_string() -> None:
    with pytest.raises(BlockSpecError, match="must be a string"):
        validate_block_id(123)  # type: ignore[arg-type]


def test_charset_error_suggests_underscore_for_space() -> None:
    """空白拒否のエラーメッセージが代替案 (`_`) を提示する (ADR-0071 §Consequences)。"""
    with pytest.raises(BlockSpecError, match="_"):
        validate_block_id("速度 指令")


def test_validate_model_id_unchanged_ascii_only() -> None:
    """``validate_model_id`` は ADR-0071 の対象外 (ASCII のまま、ADR-0071 §(3))。"""
    validate_model_id("my-model_1")
    with pytest.raises(BlockSpecError):
        validate_model_id("速度モデル")
