"""SPEC-0024 / ADR-0074: 静的ソース書き換えエンジンのテスト。

最重要 (ADR §論点 1): ``_SourceBytes`` の位置解決が CPython の解釈と**全ノードで**
一致すること (= ``ast.get_source_segment`` 照合)。日本語コメント / CRLF / 絵文字を
含むソースで col_offset (UTF-8 バイトオフセット) の扱いがずれれば必ずここで落ちる。
"""

from __future__ import annotations

import ast

import pytest

from flode.blocks.pythonfunc_rewrite import (
    MAX_PYTHON_FUNCTION_PORTS,
    _SourceBytes,
    rewrite_source,
)
from flode.blocks.pythonfunc_source import analyze_source
from flode.exceptions import PythonFunctionRewriteError, PythonFunctionSourceError

# ---------------------------------------------------------------------------
# _SourceBytes × ast.get_source_segment の全ノード照合 (ADR-0074 §論点 1)
# ---------------------------------------------------------------------------

_TRICKY_SOURCES = {
    "ascii": '@block(inputs=2)\ndef f(t: float, u: "np.ndarray") -> float:\n    return 0.0\n',
    "japanese_comment": (
        "# 日本語のコメント（全角括弧つき）\n"
        "@block  # ここも日本語\n"
        "def f(t: float, u: tuple[float, float]) -> float:\n"
        "    # 途中の説明 ★\n"
        "    return u[0]\n"
    ),
    "japanese_docstring": (
        '@block(input_names=("速度指令", "負荷トルク"))\n'
        "def f(t: float, u: tuple[float, float]) -> float:\n"
        '    """日本語 docstring。改行も\n    含む。"""\n'
        "    return u[0]\n"
    ),
    "crlf": (
        "@block(states=1)\r\n"
        "def f(t: float, x: np.ndarray, u: float) -> tuple[float, np.ndarray]:\r\n"
        "    return x[0], np.array([u])\r\n"
    ),
    "cr_only": "@block\rdef f(t: float, u: float) -> float:\r    return u\r",
    "emoji_names": (
        '@block(input_names=("🚀 in", "２番"), output_names=("出 🎯",))\n'
        "def f(t: float, u: tuple[float, float]) -> float:\n"
        "    return u[0]\n"
    ),
    "form_feed_in_string": (
        "@block\ndef f(t: float, u: float) -> float:\n"
        '    s = "line1\\x0cline2\\u2028x"  # form feed / U+2028 は行ではない\n'
        "    return u\n"
    ),
    "multiline_decorator": (
        "@block(\n"
        "    inputs=3,  # コメント付き\n"
        "    outputs=2,\n"
        ")\n"
        "def f(t: float, u: np.ndarray) -> np.ndarray:\n"
        "    return u[:2]\n"
    ),
}


class TestSourceBytesAgreesWithCPython:
    @pytest.mark.parametrize("label", sorted(_TRICKY_SOURCES))
    def test_every_node_segment_matches_get_source_segment(self, label: str) -> None:
        code = _TRICKY_SOURCES[label]
        tree = ast.parse(code)
        source = _SourceBytes(code)
        checked = 0
        for node in ast.walk(tree):
            if not hasattr(node, "lineno") or getattr(node, "end_lineno", None) is None:
                continue
            expected = ast.get_source_segment(code, node)
            if expected is None:
                continue
            assert source.segment(node).decode("utf-8") == expected, (
                f"{label}: {type(node).__name__} at line {node.lineno}"
            )
            checked += 1
        assert checked > 0

    def test_keyword_nodes_have_positions(self) -> None:
        """ADR-0074 §Confidence 1 の guard: ast.keyword が位置属性を持つこと。"""
        tree = ast.parse('@block(inputs=2, input_names=("a", "b"))\ndef f(t, u):\n    return u\n')
        deco = tree.body[0].decorator_list[0]  # type: ignore[attr-defined]
        assert isinstance(deco, ast.Call)
        for kw in deco.keywords:
            assert getattr(kw, "lineno", None) is not None
            assert getattr(kw, "col_offset", None) is not None


# ---------------------------------------------------------------------------
# 表駆動: A (入力) / B (出力) / C (名前) 規則
# ---------------------------------------------------------------------------


def _spec(code: str):
    return analyze_source(code, block_id="pf")


def _rw(code: str, **edits):
    return rewrite_source(code, block_id="pf", **edits)


SCALAR_IN = "@block\ndef f(t: float, u: float) -> float:\n    return u\n"
TUPLE2_IN = "@block\ndef f(t: float, u: tuple[float, float]) -> float:\n    return u[0] + u[1]\n"
KW_IN = (
    "@block(inputs=4, outputs=2)\ndef f(t: float, u: np.ndarray) -> np.ndarray:\n    return u[:2]\n"
)
NO_U = "@block\ndef f(t: float) -> float:\n    return t\n"
NO_RET_ANN = "@block\ndef f(t: float, u: float):\n    return u\n"
STATEFUL = (
    "@block(states=1)\n"
    "def f(t: float, x: np.ndarray, u: float) -> tuple[float, npt.NDArray[Any]]:\n"
    "    return x[0], np.array([u])\n"
)


class TestInputRules:
    def test_a1_keyword_literal_replaced(self) -> None:
        new = _rw(KW_IN, inputs=7)
        assert "inputs=7" in new
        assert _spec(new).n_inputs == 7
        assert "np.ndarray" in new  # 注釈には触れない

    def test_a2_scalar_to_tuple(self) -> None:
        new = _rw(SCALAR_IN, inputs=3)
        assert "u: tuple[float, float, float]" in new
        assert _spec(new).n_inputs == 3

    def test_a2_scalar_noop_for_one(self) -> None:
        assert _rw(SCALAR_IN, inputs=1) == SCALAR_IN  # バイト等価 no-op

    def test_a2_preserves_scalar_spelling(self) -> None:
        code = "@block\ndef f(t: float, u: np.float64) -> float:\n    return float(u)\n"
        new = _rw(code, inputs=2)
        assert "tuple[np.float64, np.float64]" in new

    def test_a3_tuple_grow_and_shrink(self) -> None:
        grown = _rw(TUPLE2_IN, inputs=4)
        assert "tuple[float, float, float, float]" in grown
        back = _rw(grown, inputs=2)
        assert "tuple[float, float]" in back
        assert _spec(back).n_inputs == 2

    def test_a3_heterogeneous_tuple_duplicates_last(self) -> None:
        code = "@block\ndef f(t: float, u: tuple[float, int]) -> float:\n    return u[0]\n"
        new = _rw(code, inputs=3)
        assert "tuple[float, int, int]" in new

    def test_a3_tuple_to_scalar(self) -> None:
        new = _rw(TUPLE2_IN, inputs=1)
        assert "u: float" in new
        assert "tuple[" not in new.split("->")[0].split("u:")[1]
        assert _spec(new).n_inputs == 1

    def test_a4_no_u_rejected(self) -> None:
        with pytest.raises(PythonFunctionRewriteError, match="no `u` parameter"):
            _rw(NO_U, inputs=1)

    @pytest.mark.parametrize("bad", [0, -1, MAX_PYTHON_FUNCTION_PORTS + 1, True])
    def test_range_rejected(self, bad) -> None:
        with pytest.raises(PythonFunctionRewriteError):
            _rw(SCALAR_IN, inputs=bad)


class TestOutputRules:
    def test_b1_keyword(self) -> None:
        new = _rw(KW_IN, outputs=5)
        assert "outputs=5" in new
        assert _spec(new).n_outputs == 5

    def test_b2_return_annotation(self) -> None:
        new = _rw(SCALAR_IN, outputs=3)
        assert "-> tuple[float, float, float]" in new
        assert _spec(new).n_outputs == 3

    def test_b3_stateful_first_element_only(self) -> None:
        new = _rw(STATEFUL, outputs=2)
        assert "tuple[tuple[float, float], npt.NDArray[Any]]" in new
        s = _spec(new)
        assert s.n_outputs == 2
        assert s.n_states == 1  # 状態ベクトル側は不変

    def test_b4_no_annotation_inserts_keyword(self) -> None:
        new = _rw(NO_RET_ANN, outputs=2)
        assert "@block(outputs=2)" in new
        assert _spec(new).n_outputs == 2

    def test_m0_always_rejected(self) -> None:
        with pytest.raises(PythonFunctionRewriteError):
            _rw(SCALAR_IN, outputs=0)


class TestNameRules:
    def test_c2_insert_keyword_bare_decorator(self) -> None:
        new = _rw(TUPLE2_IN, input_names=["速度指令", ""])
        assert '@block(input_names=("速度指令", ""))' in new
        assert _spec(new).input_names == ("速度指令", "")

    def test_c2_insert_after_existing_keywords(self) -> None:
        code = "@block(states=1)\ndef f(t: float, x: np.ndarray, u: float) -> tuple[float, np.ndarray]:\n    return x[0], np.array([u])\n"
        new = _rw(code, input_names=["in"])
        assert '@block(states=1, input_names=("in",))' in new  # 1 要素は末尾カンマ

    def test_c1_replace_existing(self) -> None:
        code = '@block(input_names=("a", "b"))\ndef f(t: float, u: tuple[float, float]) -> float:\n    return u[0]\n'
        new = _rw(code, input_names=["x", "y"])
        assert '("x", "y")' in new and '"a"' not in new

    def test_c3_all_empty_removes_keyword(self) -> None:
        code = '@block(input_names=("a", "b"))\ndef f(t: float, u: tuple[float, float]) -> float:\n    return u[0]\n'
        new = _rw(code, input_names=["", ""])
        assert "input_names" not in new
        assert "@block\n" in new  # 最後のキーワード削除で裸の @block に戻る (可逆)

    def test_c3_keyword_removed_others_kept(self) -> None:
        code = '@block(inputs=2, input_names=("a", "b"))\ndef f(t: float, u: np.ndarray) -> float:\n    return u[0]\n'
        new = _rw(code, input_names=["", ""])
        assert "input_names" not in new
        assert "@block(inputs=2)" in new

    def test_escape_quote_and_backslash(self) -> None:
        new = _rw(SCALAR_IN, input_names=['a"b\\c'])
        assert '("a\\"b\\\\c",)' in new
        assert _spec(new).input_names == ('a"b\\c',)

    def test_length_mismatch_rejected(self) -> None:
        with pytest.raises(PythonFunctionRewriteError, match="must match exactly"):
            _rw(TUPLE2_IN, input_names=["only-one"])

    def test_names_length_checked_against_new_count(self) -> None:
        new = _rw(TUPLE2_IN, inputs=3, input_names=["a", "b", "c"])
        s = _spec(new)
        assert s.n_inputs == 3
        assert s.input_names == ("a", "b", "c")


class TestCountNameSync:
    """§2.6: ポート数変更が既存の名前列の長さも同じ書き換えで同期する。"""

    NAMED2 = '@block(input_names=("a", "b"))\ndef f(t: float, u: tuple[float, float]) -> float:\n    return u[0]\n'

    def test_grow_appends_unnamed(self) -> None:
        new = _rw(self.NAMED2, inputs=3)
        assert _spec(new).input_names == ("a", "b", "")

    def test_shrink_truncates(self) -> None:
        new = _rw(self.NAMED2, inputs=1)
        assert _spec(new).input_names == ("a",)

    def test_shrink_count_only_keeps_explicit_empty_keyword(self) -> None:
        """W5: names を明示編集しない構造編集では、既存キーワードを削除せず長さ同期のみ。"""
        code = '@block(input_names=("", "b"))\ndef f(t: float, u: tuple[float, float]) -> float:\n    return u[0]\n'
        new = _rw(code, inputs=1)
        assert 'input_names=("",)' in new  # 全空でもキーワードは残す (削除は明示編集時のみ)
        assert _spec(new).n_inputs == 1
        # 明示編集で全空にしたときは C-3 でキーワード削除 (可逆)
        removed = _rw(new, input_names=[""])
        assert "input_names" not in removed


class TestMinimalDiff:
    def test_japanese_comments_and_body_untouched(self) -> None:
        code = _TRICKY_SOURCES["japanese_comment"]
        new = _rw(code, inputs=3)
        # 注釈スパン以外はバイト等価 (コメント・本体・改行はそのまま)
        assert "# 日本語のコメント（全角括弧つき）" in new
        assert "# ここも日本語" in new
        assert "# 途中の説明 ★" in new
        assert new.endswith("    return u[0]\n")
        assert _spec(new).n_inputs == 3

    def test_crlf_preserved(self) -> None:
        new = _rw(_TRICKY_SOURCES["crlf"], outputs=2)
        assert "\r\n" in new and "\n\n" not in new.replace("\r\n", "")
        assert _spec(new).n_outputs == 2

    def test_multiline_decorator_with_trailing_comma(self) -> None:
        new = _rw(_TRICKY_SOURCES["multiline_decorator"], input_names=["a", "b", "c"])
        s = _spec(new)
        assert s.input_names == ("a", "b", "c")
        assert "# コメント付き" in new  # デコレータ内コメントも保存

    def test_noop_request_returns_identical_source(self) -> None:
        code = _TRICKY_SOURCES["japanese_docstring"]
        assert _rw(code, inputs=2, input_names=["速度指令", "負荷トルク"]) == code


class TestSelfVerification:
    def test_broken_planner_never_returns_broken_code(self, monkeypatch) -> None:
        """W3: splice が壊れたコードを作っても、返らずに verify エラーになる。"""
        import flode.blocks.pythonfunc_rewrite as rw

        def _bad_annotation(source, node, target, *, what):  # noqa: ARG001
            start, end = source.span(node)
            return rw._Splice(start, end, b"tuple[")  # わざと構文を壊す

        monkeypatch.setattr(rw, "_rewrite_count_annotation", _bad_annotation)
        with pytest.raises(PythonFunctionRewriteError, match="no longer parses") as ei:
            _rw(SCALAR_IN, inputs=2)
        # wire 語彙は 3 値のまま (ADR-0074 §論点 3)。内部細分は reason に持つ
        assert ei.value.kind == "spec"
        assert ei.value.reason == "rewrite_verify_syntax"

    def test_structure_mismatch_detected(self, monkeypatch) -> None:
        """E1/E2: 構文は正しいが構造が要求とずれた場合も拒否される。"""
        import flode.blocks.pythonfunc_rewrite as rw

        def _wrong_annotation(source, node, target, *, what):  # noqa: ARG001
            start, end = source.span(node)
            return rw._Splice(start, end, b"tuple[float, float, float, float]")  # 常に 4

        monkeypatch.setattr(rw, "_rewrite_count_annotation", _wrong_annotation)
        with pytest.raises(PythonFunctionRewriteError, match="does not match") as ei:
            _rw(SCALAR_IN, inputs=2)
        assert ei.value.kind == "spec"
        assert ei.value.reason == "rewrite_verify_mismatch"

    def test_unaccepted_source_raises_source_error(self) -> None:
        with pytest.raises(PythonFunctionSourceError):
            rewrite_source("def f(t, u):\n    return u\n", inputs=2)


class TestSecurityHardening:
    """security-reviewer (v0.50.0) 対応の回帰テスト。"""

    def test_lone_surrogate_name_rejected_as_spec_error(self) -> None:
        """SHOULD-1: 孤立サロゲート (Cs) は UTF-8 encode 不能 → N4 で拒否。"""
        with pytest.raises(PythonFunctionRewriteError, match="control/format") as ei:
            _rw(SCALAR_IN, input_names=["\ud800"])
        assert ei.value.kind == "spec"

    def test_lone_surrogate_rejected_in_dsl(self) -> None:
        from flode import block
        from flode.exceptions import BlockSpecError

        with pytest.raises(BlockSpecError, match="control/format"):

            @block(input_names=("\ud800",))
            def f(t: float, u: float) -> float:
                return u

    def test_rewritten_code_size_cap(self) -> None:
        """NIT-2: 増幅結果が 256 KiB を超える書き換えは unsupported で拒否 (元コード不変)。"""
        big_elem = "tuple[" + ", ".join(["float"] * 1500) + "]"  # 約 10.5 KB の要素
        code = (
            f"@block\ndef f(t: float, u: tuple[{big_elem}, {big_elem}]) -> float:\n    return 0.0\n"
        )
        with pytest.raises(PythonFunctionRewriteError, match="exceed") as ei:
            _rw(code, inputs=32)
        assert ei.value.kind == "unsupported"


class TestKeywordRemovalPreservesComments:
    """code-reviewer MUST: 削除対象より前の保持キーワードの trailing comment を壊さない。"""

    MULTILINE = (
        "@block(\n"
        "    inputs=2,  # note about inputs, keep this\n"
        '    input_names=("a", "b"),  # remove this one\n'
        "    outputs=1,\n"
        ")\n"
        "def f(t: float, u: np.ndarray) -> np.ndarray:\n"
        "    return u[:1]\n"
    )

    def test_middle_removal_keeps_previous_comment(self) -> None:
        new = _rw(self.MULTILINE, input_names=["", ""])
        assert "input_names" not in new
        assert "# note about inputs, keep this" in new  # 保持キーワードのコメント無傷
        assert "# remove this one" not in new  # 削除対象のコメントは一緒に消える
        assert "outputs=1" in new
        assert _spec(new).input_names == ()

    def test_last_removal_keeps_previous_comment(self) -> None:
        code = (
            "@block(\n"
            "    inputs=2,  # keep this comment\n"
            '    input_names=("a", "b"),  # goes away\n'
            ")\n"
            "def f(t: float, u: np.ndarray) -> float:\n"
            "    return u[0]\n"
        )
        new = _rw(code, input_names=["", ""])
        assert "input_names" not in new
        assert "# keep this comment" in new
        assert "# goes away" not in new
        assert _spec(new).n_inputs == 2  # trailing comma が残っても合法・構造不変

    def test_single_line_last_removal(self) -> None:
        code = '@block(inputs=2, input_names=("a", "b"))\ndef f(t: float, u: np.ndarray) -> float:\n    return u[0]\n'
        new = _rw(code, input_names=["", ""])
        assert "input_names" not in new
        assert "inputs=2" in new
        assert _spec(new).n_inputs == 2
