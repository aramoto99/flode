"""ADR-0056 §B-1 / §C: 構造化エラー protocol の単体テスト。

カバレッジ:
  * ``classify_exception``: Phase 1 全カテゴリ + unknown fallback + shape_mismatch
    の wording 検出 (= numpy 2.x wording 固定)
  * ``build_failure_payload``: 全 field の充足、AlgebraicLoopError の block_ids
    展開、_current_block 抽出、duration_sec の有/無
  * ``_truncate_traceback``: ``max_lines`` 超過時に末尾を残す
"""

from __future__ import annotations

import numpy as np
import pytest

from flode.exceptions import (
    AlgebraicLoopError,
    BlockSpecError,
    ModelLoadError,
    SolverError,
)
from flode.server.errors import (
    _truncate_traceback,
    build_failure_payload,
    classify_exception,
)


class _DummyBlock:
    """``simulator._current_block`` テスト用の最小ブロック。"""

    def __init__(self, *, id: str = "blk_1", name: str | None = "Divide1") -> None:
        self.id = id
        self.name = name


class _DummySimulator:
    def __init__(self, *, current_block: _DummyBlock | None) -> None:
        self._current_block = current_block


# ---------------------------------------------------------------------------
# classify_exception
# ---------------------------------------------------------------------------


def test_classify_algebraic_loop() -> None:
    exc = AlgebraicLoopError("loop detected", block_ids=["a", "b"])
    c = classify_exception(exc)
    assert c.category == "algebraic_loop"
    assert c.template_key == "error.algebraic_loop"


def test_classify_divide_by_zero() -> None:
    exc = ZeroDivisionError("float division by zero")
    c = classify_exception(exc)
    assert c.category == "divide_by_zero"


def test_classify_solver_failure() -> None:
    exc = SolverError("Solver failed at t=[0.1, 0.2]: max_step exceeded")
    c = classify_exception(exc)
    assert c.category == "solver_failure"


def test_classify_block_spec_error_is_start_validation() -> None:
    exc = BlockSpecError("invalid gain")
    assert classify_exception(exc).category == "start_validation"


def test_classify_model_load_error_is_start_validation() -> None:
    exc = ModelLoadError("bad json")
    assert classify_exception(exc).category == "start_validation"


def test_classify_numpy_shape_mismatch_is_shape_mismatch() -> None:
    """numpy 2.x wording (= ``operands could not be broadcast together with shapes ...``)
    を `"broadcast"` / `"shape"` 部分一致で拾えることを pin する (ADR-0056 §Risks U5)。
    """
    try:
        np.add(np.zeros(3), np.zeros(2))
    except ValueError as e:
        c = classify_exception(e)
        assert c.category == "shape_mismatch"
        assert c.template_key == "error.shape_mismatch"
    else:
        pytest.fail("numpy add did not raise ValueError for shape mismatch")


def test_classify_unknown_value_error_falls_back() -> None:
    """``ValueError`` でも message に shape/broadcast を含まなければ unknown。"""
    exc = ValueError("invalid literal for int()")
    assert classify_exception(exc).category == "unknown"


def test_classify_unknown_type_error() -> None:
    exc = TypeError("expected int")
    assert classify_exception(exc).category == "unknown"


# ---------------------------------------------------------------------------
# build_failure_payload
# ---------------------------------------------------------------------------


def test_payload_minimum_fields_all_present() -> None:
    exc = ZeroDivisionError("float division by zero")
    payload = build_failure_payload(exc, simulator=None, t=None)
    # 必須/任意の全 field が key としては存在することを保証 (= frontend 防御コード簡略化)。
    for key in (
        "category",
        "template_key",
        "template_args",
        "block_id",
        "block_ids",
        "block_type",
        "block_label",
        "t",
        "raw_message",
        "raw_traceback",
    ):
        assert key in payload, f"missing key: {key}"


def test_payload_duration_sec_only_when_provided() -> None:
    exc = ZeroDivisionError("x")
    p1 = build_failure_payload(exc, simulator=None, t=None)
    assert "duration_sec" not in p1
    p2 = build_failure_payload(exc, simulator=None, t=None, duration_sec=1.5)
    assert p2["duration_sec"] == 1.5


def test_payload_block_extracted_from_simulator() -> None:
    block = _DummyBlock(id="div_1", name="Divide1")
    sim = _DummySimulator(current_block=block)
    exc = ZeroDivisionError("x")
    payload = build_failure_payload(exc, simulator=sim, t=1.234)
    assert payload["block_id"] == "div_1"
    assert payload["block_ids"] == ["div_1"]
    assert payload["block_label"] == "Divide1"
    assert payload["block_type"] is not None
    assert payload["block_type"].endswith("_DummyBlock")
    assert payload["t"] == 1.234
    # template_args は block_label / t を含む
    assert payload["template_args"].get("block_label") == "Divide1"
    assert payload["template_args"].get("t") == 1.234


def test_payload_block_label_fallback_to_id_when_name_empty() -> None:
    block = _DummyBlock(id="div_1", name=None)
    sim = _DummySimulator(current_block=block)
    payload = build_failure_payload(ZeroDivisionError("x"), simulator=sim, t=None)
    assert payload["block_label"] == "div_1"


def test_payload_algebraic_loop_expands_block_ids() -> None:
    """``AlgebraicLoopError`` は ``block_ids`` 属性を payload に展開する。"""
    exc = AlgebraicLoopError("loop", block_ids=["a", "b", "c"])
    payload = build_failure_payload(exc, simulator=None, t=None)
    assert payload["block_ids"] == ["a", "b", "c"]
    assert payload["block_id"] == "a"  # 主因 = 先頭
    assert payload["block_label"] == "a"  # label も fallback
    assert payload["template_args"]["block_labels"] == ["a", "b", "c"]


def test_payload_shape_mismatch_extracts_shapes() -> None:
    """``template_args.shapes`` に shape 文字列が入る (best-effort)。"""
    try:
        np.add(np.zeros(3), np.zeros(2))
    except ValueError as e:
        payload = build_failure_payload(e, simulator=None, t=None)
        # numpy 2.x の wording 由来で ``(3,) vs (2,)`` 形式の shapes を含む。
        assert "shapes" in payload["template_args"]
        assert "3" in payload["template_args"]["shapes"]
        assert "2" in payload["template_args"]["shapes"]


def test_payload_solver_failure_extracts_reason() -> None:
    exc = SolverError("Solver failed at t=[0.1, 0.2]: max_step exceeded")
    payload = build_failure_payload(exc, simulator=None, t=None)
    assert payload["template_args"]["reason"] == "max_step exceeded"


def test_payload_unknown_includes_raw_message_in_template_args() -> None:
    exc = RuntimeError("some weird error")
    payload = build_failure_payload(exc, simulator=None, t=None)
    assert payload["category"] == "unknown"
    assert "raw_message" in payload["template_args"]
    assert payload["template_args"]["raw_message"].startswith("RuntimeError:")


def test_payload_start_validation_includes_message_in_template_args() -> None:
    """回帰: ``error.start_validation`` テンプレートは ``{{message}}`` を参照するが、
    例外由来の build_failure_payload 経路で ``template_args["message"]`` が抜けて
    UI に ``{{message}}`` が literal 表示されていた (2026-05-20 報告)。
    """
    exc = BlockSpecError("Block 'div': invalid signs '*x'")
    payload = build_failure_payload(exc, simulator=None, t=None)
    assert payload["category"] == "start_validation"
    assert payload["template_args"].get("message") == "Block 'div': invalid signs '*x'"


def test_payload_model_load_error_includes_message() -> None:
    exc = ModelLoadError("Unknown block type: flode.blocks.nonexistent.Foo")
    payload = build_failure_payload(exc, simulator=None, t=None)
    assert payload["category"] == "start_validation"
    assert payload["template_args"]["message"] == "Unknown block type: flode.blocks.nonexistent.Foo"


def test_payload_picks_up_exception_block_id() -> None:
    """ADR-0056: ブロック単位の raise (= From/Goto 解決) は例外に block_id を載せる。

    ``_current_block`` 未設定でも payload の block_id / block_ids / block_label に
    展開され、UI のジャンプ対象になる (label は id へフォールバック)。
    """
    exc = BlockSpecError(
        "From 'From_0'(tag='aa') in scope <root>: no matching Goto found",
        block_id="From_0",
    )
    payload = build_failure_payload(exc, simulator=None, t=None)
    assert payload["block_id"] == "From_0"
    assert payload["block_ids"] == ["From_0"]
    assert payload["block_label"] == "From_0"
    # start_validation テンプレートは message を持つ
    assert "From_0" in payload["template_args"]["message"]


def test_block_spec_error_block_id_defaults_none() -> None:
    """block_id を渡さない既存の raise は従来どおり (= None)。"""
    exc = BlockSpecError("some validation error")
    assert exc.block_id is None
    payload = build_failure_payload(exc, simulator=None, t=None)
    assert payload["block_id"] is None
    assert payload["block_ids"] == []


def test_payload_raw_traceback_can_be_suppressed() -> None:
    payload = build_failure_payload(
        ZeroDivisionError("x"),
        simulator=None,
        t=None,
        include_traceback=False,
    )
    assert payload["raw_traceback"] is None


# ---------------------------------------------------------------------------
# _truncate_traceback
# ---------------------------------------------------------------------------


def test_truncate_traceback_keeps_short_input_unchanged() -> None:
    tb = "line1\nline2\nline3"
    assert _truncate_traceback(tb, max_lines=10) == tb


def test_truncate_traceback_keeps_tail_when_too_long() -> None:
    tb = "\n".join(f"line{i}" for i in range(100))
    truncated = _truncate_traceback(tb, max_lines=10)
    lines = truncated.splitlines()
    # 先頭 1 行は省略マーカー、続く 10 行が末尾。
    assert lines[0].startswith("...")
    assert "earlier lines truncated" in lines[0]
    assert lines[-1] == "line99"
    assert len(lines) == 11  # marker + 10 tail lines


# ---------------------------------------------------------------------------
# SPEC-0023 / ADR-0073 §論点 6: PythonFunction 専用カテゴリ
# ---------------------------------------------------------------------------


def test_classify_python_function_eval_error() -> None:
    from flode.exceptions import PythonFunctionEvalError

    c = classify_exception(PythonFunctionEvalError("PythonFunction[pf]: ZeroDivisionError: x"))
    assert c.category == "python_function_error"
    assert c.template_key == "error.python_function_error"


def test_classify_python_blocks_disabled_precedes_block_spec_error() -> None:
    """``PythonBlocksDisabledError`` は BlockSpecError のサブクラスだが専用カテゴリに落ちる。"""
    from flode.exceptions import PythonBlocksDisabledError

    c = classify_exception(PythonBlocksDisabledError("disabled", block_id="pf"))
    assert c.category == "python_function_disabled"
    # 通常の BlockSpecError は従来どおり
    assert classify_exception(BlockSpecError("x")).category == "start_validation"


def test_payload_python_function_error_has_line_info_and_user_traceback() -> None:
    from flode.exceptions import PythonFunctionEvalError

    exc = PythonFunctionEvalError(
        "PythonFunction[pf]: ZeroDivisionError: division by zero (line 5)",
        lineno=5,
        source_line="        return 1 / 0",
        user_traceback='  File "<pythonfunction:pf>", line 5, in bad\n    return 1 / 0\nZeroDivisionError: division by zero',
        block_id="pf",
    )
    payload = build_failure_payload(exc, simulator=_DummySimulator(current_block=None), t=0.06)
    assert payload["category"] == "python_function_error"
    assert payload["block_id"] == "pf"
    assert payload["block_ids"] == ["pf"]
    args = payload["template_args"]
    assert args["lineno"] == 5
    assert args["source_line"] == "return 1 / 0"
    assert args["block_label"] == "pf"
    assert "ZeroDivisionError" in args["message"]
    # flode 内部フレームではなくユーザーフレームだけの traceback
    assert payload["raw_traceback"].startswith('  File "<pythonfunction:pf>"')
    assert "errors.py" not in payload["raw_traceback"]


def test_payload_python_function_error_without_line_info() -> None:
    from flode.exceptions import PythonFunctionEvalError

    exc = PythonFunctionEvalError("PythonFunction[pf]: RuntimeError: boom", block_id="pf")
    payload = build_failure_payload(exc, include_traceback=False)
    assert payload["template_args"]["lineno"] == "?"
    assert payload["template_args"]["source_line"] == ""
    assert payload["raw_traceback"] is None


def test_payload_python_blocks_disabled_includes_message() -> None:
    from flode.exceptions import PythonBlocksDisabledError

    exc = PythonBlocksDisabledError("PythonFunction[pf]: disabled (bind 0.0.0.0)", block_id="pf")
    payload = build_failure_payload(exc, include_traceback=False)
    assert payload["category"] == "python_function_disabled"
    assert payload["template_args"]["message"].endswith("(bind 0.0.0.0)")
    assert payload["template_args"]["block_label"] == "pf"
    assert payload["block_id"] == "pf"
