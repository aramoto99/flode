"""SPEC-0024 / ADR-0074: 静的ソース書き換えエンジンのテスト。

最重要 (ADR §論点 1): ``_SourceBytes`` の位置解決が CPython の解釈と**全ノードで**
一致すること (= ``ast.get_source_segment`` 照合)。日本語コメント / CRLF / 絵文字を
含むソースで col_offset (UTF-8 バイトオフセット) の扱いがずれれば必ずここで落ちる。
"""

from __future__ import annotations

import ast

import pytest

from flode.blocks.pythonfunc_rewrite import (
    MAX_PARAM_NAME_LENGTH,
    MAX_PARAM_STR_DEFAULT_LENGTH,
    MAX_PYTHON_FUNCTION_PORTS,
    AddParam,
    RemoveParam,
    RenameParam,
    RetypeParam,
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


# ---------------------------------------------------------------------------
# SPEC-0025 / ADR-0075: パラメータ (kw-only 引数) の追加 / 削除
# ---------------------------------------------------------------------------

KW1 = "@block\ndef f(t: float, u: float, *, kp: float = 1.0) -> float:\n    return u * kp\n"
KW3 = (
    "@block\n"
    'def f(t: float, u: float, *, a: float = 1.0, b: int = 2, c: str = "x") -> float:\n'
    "    return u * a\n"
)


class TestParamAdd:
    def test_ap1_appends_after_last_kwonly(self) -> None:
        new = _rw(KW1, params=[AddParam(name="gain", type="float", default=2.0)])
        assert "*, kp: float = 1.0, gain: float = 2.0)" in new
        assert _spec(new).params_spec[-1] == ("gain", 2.0, float, False)

    def test_ap2_no_kwonly_inserts_star(self) -> None:
        new = _rw(SCALAR_IN, params=[AddParam(name="gain", type="float", default=1.0)])
        assert "def f(t: float, u: float, *, gain: float = 1.0) -> float:" in new
        assert _spec(new).params_spec == (("gain", 1.0, float, False),)

    def test_ap2_anchor_after_positional_default(self) -> None:
        # V19: アンカーは `arg` の end ではなく default 式の end (構文破壊の回帰)
        code = "@block\ndef f(t: float, u: float = 0.0) -> float:\n    return u\n"
        new = _rw(code, params=[AddParam(name="gain", type="float", default=1.0)])
        assert "u: float = 0.0, *, gain: float = 1.0)" in new
        assert _spec(new).params_spec == (("gain", 1.0, float, False),)

    def test_ap2_after_positional_only_slash(self) -> None:
        code = "@block\ndef f(t: float, u: float, /) -> float:\n    return u\n"
        new = _rw(code, params=[AddParam(name="gain", type="float", default=1.0)])
        assert "u: float, /, *, gain: float = 1.0)" in new

    def test_ap1_multiline_trailing_comma_and_comment(self) -> None:
        code = (
            "@block\n"
            "def f(\n"
            "    t: float,\n"
            "    u: float,\n"
            "    *,\n"
            "    kp: float = 1.0,  # gain\n"
            ") -> float:\n"
            "    return u * kp\n"
        )
        new = _rw(code, params=[AddParam(name="g2", type="int", default=3)])
        assert "kp: float = 1.0, g2: int = 3,  # gain" in new
        assert [p[0] for p in _spec(new).params_spec] == ["kp", "g2"]

    def test_port_edit_and_param_add_in_one_batch(self) -> None:
        # ADR-0075 V9: 注釈置換 [s, e) と同位置 e へのゼロ幅挿入は共存できる
        new = _rw(SCALAR_IN, inputs=2, params=[AddParam(name="gain", type="float", default=1.0)])
        assert "u: tuple[float, float], *, gain: float = 1.0" in new
        s = _spec(new)
        assert s.n_inputs == 2
        assert s.params_spec == (("gain", 1.0, float, False),)


class TestParamRemove:
    def test_dp1_middle_forward_delete(self) -> None:
        new = _rw(KW3, params=[RemoveParam(name="b")])
        assert '*, a: float = 1.0, c: str = "x")' in new
        assert [p[0] for p in _spec(new).params_spec] == ["a", "c"]

    def test_dp2_last_with_remaining(self) -> None:
        new = _rw(KW3, params=[RemoveParam(name="c")])
        assert "*, a: float = 1.0, b: int = 2)" in new
        assert [p[0] for p in _spec(new).params_spec] == ["a", "b"]

    def test_dp3_only_kwonly_removes_star(self) -> None:
        new = _rw(KW1, params=[RemoveParam(name="kp")])
        assert "def f(t: float, u: float) -> float:" in new
        assert _spec(new).params_spec == ()

    def test_dp3_keeps_slash_marker(self) -> None:
        code = "@block\ndef f(t: float, u: float, /, *, kp: float = 1.0) -> float:\n    return u\n"
        new = _rw(code, params=[RemoveParam(name="kp")])
        assert "def f(t: float, u: float, /) -> float:" in new

    def test_dp3_multiline_keeps_previous_comment(self) -> None:
        code = (
            "@block\n"
            "def f(t: float, u: float,  # keep this\n"
            "      *, kp: float = 1.0) -> float:\n"
            "    return u\n"
        )
        new = _rw(code, params=[RemoveParam(name="kp")])
        assert "# keep this" in new
        assert "kp" not in new
        assert _spec(new).params_spec == ()

    def test_remove_ignores_body_reference(self) -> None:
        # 受入基準 (x) / §確定事項 2: 残留参照があっても無警告で適用、本体は不変
        new = _rw(KW1, params=[RemoveParam(name="kp")])
        assert "return u * kp" in new
        assert _spec(new).params_spec == ()

    def test_remove_missing_rejected(self) -> None:
        with pytest.raises(PythonFunctionRewriteError, match="no parameter named"):
            _rw(KW1, params=[RemoveParam(name="nope")])

    def test_remove_x0_rejected_when_stateful(self) -> None:
        code = (
            "@block(states=1)\n"
            "def f(t: float, x: np.ndarray, u: float, *, x0: float = 0.0) "
            "-> tuple[float, np.ndarray]:\n"
            "    return x[0], np.array([u])\n"
        )
        with pytest.raises(PythonFunctionRewriteError, match="x0"):
            _rw(code, params=[RemoveParam(name="x0")])


class TestParamNameValidation:
    @pytest.mark.parametrize(
        "bad",
        ["", "1a", "ゲイン", "def", "has space", "a" * (MAX_PARAM_NAME_LENGTH + 1)],
    )
    def test_p1_to_p4_rejected(self, bad: str) -> None:
        with pytest.raises(PythonFunctionRewriteError):
            _rw(SCALAR_IN, params=[AddParam(name=bad, type="float", default=1.0)])

    def test_soft_keyword_allowed(self) -> None:
        new = _rw(SCALAR_IN, params=[AddParam(name="match", type="int", default=0)])
        assert _spec(new).params_spec[0][0] == "match"

    def test_p5_existing_param_conflict(self) -> None:
        with pytest.raises(PythonFunctionRewriteError, match="already exists"):
            _rw(KW1, params=[AddParam(name="kp", type="float", default=1.0)])

    @pytest.mark.parametrize("taken", ["u", "f"])
    def test_p6_p7_signature_names_rejected(self, taken: str) -> None:
        with pytest.raises(PythonFunctionRewriteError, match="already used"):
            _rw(SCALAR_IN, params=[AddParam(name=taken, type="float", default=1.0)])

    def test_n_used_body_local_rejected(self) -> None:
        code = "@block\ndef f(t: float, u: float) -> float:\n    tmp = u\n    return tmp\n"
        with pytest.raises(PythonFunctionRewriteError, match="already used"):
            _rw(code, params=[AddParam(name="tmp", type="float", default=1.0)])

    def test_n_used_builtin_shadow_rejected(self) -> None:
        code = "@block\ndef f(t: float, u: float) -> float:\n    return min(u, 1.0)\n"
        with pytest.raises(PythonFunctionRewriteError, match="already used"):
            _rw(code, params=[AddParam(name="min", type="float", default=1.0)])

    @pytest.mark.parametrize("injected", ["np", "npt", "block"])
    def test_p8_injected_globals_rejected(self, injected: str) -> None:
        # `block` はデコレータの `Name` として関数内に現れるため N-USED が先に拒否する
        # (P8 と重複被覆。どちらでも安全側)
        with pytest.raises(PythonFunctionRewriteError, match="shadow|already used"):
            _rw(SCALAR_IN, params=[AddParam(name=injected, type="float", default=1.0)])

    def test_p8_module_level_binding_rejected(self) -> None:
        code = "K = 2.0\n\n@block\ndef f(t: float, u: float) -> float:\n    return u\n"
        with pytest.raises(PythonFunctionRewriteError, match="shadow"):
            _rw(code, params=[AddParam(name="K", type="float", default=1.0)])

    def test_p9_x0_reserved_when_stateful(self) -> None:
        with pytest.raises(PythonFunctionRewriteError, match="reserved"):
            _rw(STATEFUL, params=[AddParam(name="x0", type="float", default=0.0)])


class TestParamDefaultLiterals:
    """生成リテラルの決定性 (ADR-0075 §論点 5)。E3 が round-trip まで検査する。"""

    def test_float_from_int_gets_decimal_point(self) -> None:
        new = _rw(SCALAR_IN, params=[AddParam(name="g", type="float", default=1)])
        assert "g: float = 1.0" in new
        assert _spec(new).params_spec[0][1] == 1.0

    def test_float_exponent_form(self) -> None:
        new = _rw(SCALAR_IN, params=[AddParam(name="g", type="float", default=1e20)])
        assert "g: float = 1e+20" in new
        assert _spec(new).params_spec[0][1] == 1e20

    def test_float_negative_zero(self) -> None:
        new = _rw(SCALAR_IN, params=[AddParam(name="g", type="float", default=-0.5)])
        assert "g: float = -0.5" in new

    @pytest.mark.parametrize("bad", [float("inf"), float("nan")])
    def test_float_non_finite_rejected(self, bad: float) -> None:
        with pytest.raises(PythonFunctionRewriteError, match="finite"):
            _rw(SCALAR_IN, params=[AddParam(name="g", type="float", default=bad)])

    def test_bool_literal(self) -> None:
        new = _rw(SCALAR_IN, params=[AddParam(name="flag", type="bool", default=True)])
        assert "flag: bool = True" in new
        assert _spec(new).params_spec[0][1] is True

    def test_bool_passed_as_int_rejected(self) -> None:
        with pytest.raises(PythonFunctionRewriteError, match="int"):
            _rw(SCALAR_IN, params=[AddParam(name="n", type="int", default=True)])

    def test_str_escaping(self) -> None:
        new = _rw(SCALAR_IN, params=[AddParam(name="s", type="str", default='a"b\\c')])
        assert 's: str = "a\\"b\\\\c"' in new
        assert _spec(new).params_spec[0][1] == 'a"b\\c'

    def test_str_control_char_rejected(self) -> None:
        with pytest.raises(PythonFunctionRewriteError, match="control"):
            _rw(SCALAR_IN, params=[AddParam(name="s", type="str", default="a\nb")])

    def test_str_too_long_rejected(self) -> None:
        long = "x" * (MAX_PARAM_STR_DEFAULT_LENGTH + 1)
        with pytest.raises(PythonFunctionRewriteError, match="at most"):
            _rw(SCALAR_IN, params=[AddParam(name="s", type="str", default=long)])

    def test_unknown_type_rejected(self) -> None:
        with pytest.raises(PythonFunctionRewriteError, match="type must be one of"):
            _rw(SCALAR_IN, params=[AddParam(name="g", type="list", default=1.0)])


class TestParamRetype:
    """SPEC-0025 Amendment (2026-09-04): 型変更 = 注釈 + default の同時書き換え。
    default / 設定値は「変換できれば引き継ぐ」(ユーザー確認)。"""

    def test_float_to_int_truncates_default(self) -> None:
        code = (
            "@block\ndef f(t: float, u: float, *, kp: float = 1.5) -> float:\n    return u * kp\n"
        )
        new = _rw(code, params=[RetypeParam(name="kp", type="int")])
        assert "kp: int = 1" in new
        assert "return u * kp" in new  # 本体は不変
        assert _spec(new).params_spec == (("kp", 1, int, False),)

    def test_int_to_float(self) -> None:
        code = "@block\ndef f(t: float, u: float, *, n: int = 3) -> float:\n    return u\n"
        new = _rw(code, params=[RetypeParam(name="n", type="float")])
        assert "n: float = 3.0" in new
        assert _spec(new).params_spec == (("n", 3.0, float, False),)

    def test_float_to_str_stringifies(self) -> None:
        new = _rw(KW1, params=[RetypeParam(name="kp", type="str")])
        assert 'kp: str = "1.0"' in new
        assert _spec(new).params_spec == (("kp", "1.0", str, False),)

    def test_str_to_float_parses(self) -> None:
        code = '@block\ndef f(t: float, u: float, *, s: str = "2.5") -> float:\n    return u\n'
        new = _rw(code, params=[RetypeParam(name="s", type="float")])
        assert "s: float = 2.5" in new

    def test_unconvertible_resets_to_standard(self) -> None:
        code = '@block\ndef f(t: float, u: float, *, s: str = "abc") -> float:\n    return u\n'
        new = _rw(code, params=[RetypeParam(name="s", type="float")])
        assert "s: float = 0.0" in new
        # bool へは他型から暗黙変換しない
        new2 = _rw(KW1, params=[RetypeParam(name="kp", type="bool")])
        assert "kp: bool = False" in new2

    def test_unannotated_param_gets_annotation(self) -> None:
        code = "@block\ndef f(t: float, u: float, *, k=1.0) -> float:\n    return u * k\n"
        new = _rw(code, params=[RetypeParam(name="k", type="int")])
        # 最小 diff: 元の `=` の詰め書きは保存される (注釈挿入 + default 置換のみ)
        assert "k: int=1" in new
        assert _spec(new).params_spec == (("k", 1, int, False),)

    def test_required_param_changes_annotation_only(self) -> None:
        code = "@block\ndef f(t: float, u: float, *, k: float) -> float:\n    return u * k\n"
        new = _rw(code, params=[RetypeParam(name="k", type="str")])
        assert "k: str)" in new
        assert _spec(new).params_spec == (("k", None, str, True),)

    def test_same_type_is_noop(self) -> None:
        assert _rw(KW1, params=[RetypeParam(name="kp", type="float")]) == KW1

    def test_x0_rejected_when_stateful(self) -> None:
        code = (
            "@block(states=1)\n"
            "def f(t: float, x: np.ndarray, u: float, *, x0: float = 0.0) "
            "-> tuple[float, np.ndarray]:\n"
            "    return x[0], np.array([u])\n"
        )
        with pytest.raises(PythonFunctionRewriteError, match="x0"):
            _rw(code, params=[RetypeParam(name="x0", type="int")])

    def test_unknown_type_rejected(self) -> None:
        with pytest.raises(PythonFunctionRewriteError, match="type must be one of"):
            _rw(KW1, params=[RetypeParam(name="kp", type="list")])

    def test_port_edit_combination_allowed(self) -> None:
        # retype は本体に触れないので rename と違いポート編集と併用できる
        new = _rw(KW1, inputs=2, params=[RetypeParam(name="kp", type="int")])
        s = _spec(new)
        assert s.n_inputs == 2
        assert s.params_spec == (("kp", 1, int, False),)

    def test_minimal_diff_japanese_comment(self) -> None:
        code = (
            "@block\n"
            "def f(t: float, u: float, *, kp: float = 1.5) -> float:\n"
            "    # 日本語コメント ★\n"
            "    return u * kp\n"
        )
        new = _rw(code, params=[RetypeParam(name="kp", type="int")])
        assert "# 日本語コメント ★" in new
        assert new.endswith("    return u * kp\n")


class TestParamMisc:
    def test_empty_param_list_is_noop(self) -> None:
        assert _rw(SCALAR_IN, params=[]) == SCALAR_IN

    def test_rename_must_be_sole_edit(self) -> None:
        # ADR-0075 §論点 2-D: E4a の証明を単純命題に保つため、rename × ポート編集は拒否
        with pytest.raises(PythonFunctionRewriteError, match="only edit"):
            _rw(KW1, inputs=2, params=[RenameParam(old="kp", new="gain")])

    def test_params_accepts_exactly_one_edit(self) -> None:
        # security-reviewer SHOULD: 複数 op は AP-2 の `*` 二重挿入等で自己検証落ちし
        # 「rewrite rules のバグ」の ERROR ログ (ユーザーコード付き) を誤発火するため、
        # REST と同じく常に 1 命令の契約として拒否する
        with pytest.raises(PythonFunctionRewriteError, match="exactly one edit"):
            _rw(
                KW1,
                params=[
                    RenameParam(old="kp", new="gain"),
                    AddParam(name="q", type="int", default=1),
                ],
            )
        with pytest.raises(PythonFunctionRewriteError, match="exactly one edit"):
            _rw(
                SCALAR_IN,
                params=[
                    AddParam(name="a", type="float", default=1.0),
                    AddParam(name="b", type="float", default=1.0),
                ],
            )

    def test_float_default_huge_int_rejected_not_crashed(self) -> None:
        # security-reviewer MUST: 巨大 int → float の OverflowError を契約例外に変換
        with pytest.raises(PythonFunctionRewriteError, match="float range"):
            _rw(SCALAR_IN, params=[AddParam(name="g", type="float", default=10**400)])

    def test_int_default_digit_limit(self) -> None:
        # security-reviewer SHOULD: int default に桁数上限 (str の 256 と対称)
        with pytest.raises(PythonFunctionRewriteError, match="digits"):
            _rw(SCALAR_IN, params=[AddParam(name="g", type="int", default=10**40)])
        new = _rw(SCALAR_IN, params=[AddParam(name="g", type="int", default=-(10**31))])
        assert _spec(new).params_spec[0][1] == -(10**31)

    def test_every_ast_node_type_is_classified(self) -> None:
        """規則 G の網羅性 guard: 新しい Python 版で AST ノードが増えたら CI で赤くする
        (ADR-0075 V24)。拒否側 (_RENAME_DENIED_NODE_NAMES) に分類するだけでも緑に戻せる。
        """
        import flode.blocks.pythonfunc_rewrite as rw

        all_nodes = {
            v.__name__ for v in vars(ast).values() if isinstance(v, type) and issubclass(v, ast.AST)
        }
        classified = (
            rw._RENAME_ALLOWED_NODE_NAMES
            | rw._RENAME_DENIED_NODE_NAMES
            | rw._RENAME_IGNORED_NODE_NAMES
        )
        missing = all_nodes - classified
        assert not missing, f"classify these AST nodes for rename (rule G): {sorted(missing)}"

    def test_minimal_diff_japanese_comment_preserved(self) -> None:
        code = (
            "@block\n"
            "def f(t: float, u: float) -> float:  # 日本語コメント\n"
            "    # 本体の説明 ★\n"
            "    return u\n"
        )
        new = _rw(code, params=[AddParam(name="gain", type="float", default=1.0)])
        assert "# 日本語コメント" in new
        assert "# 本体の説明 ★" in new
        assert new.endswith("    return u\n")


# ---------------------------------------------------------------------------
# SPEC-0025 / ADR-0075: rename のスコープ解析 (S1〜S10、規則 G / U1〜U8)
# ---------------------------------------------------------------------------


def _kp_func(body: str) -> ast.FunctionDef:
    indented = "\n".join("    " + line if line else "" for line in body.splitlines())
    code = f"@block\ndef f(t: float, u: float, *, kp: float = 1.0) -> float:\n{indented}\n"
    tree = ast.parse(code)
    return next(n for n in tree.body if isinstance(n, ast.FunctionDef))


def _occurrences(body: str, name: str = "kp"):
    import flode.blocks.pythonfunc_rewrite as rw

    return rw._plan_rename_occurrences(_kp_func(body), name, "pf")


class TestRenameScopeRules:
    """occurrence 数 = シグネチャの `arg` 1 個 + 本体で対象を指す `Name` の数。"""

    def test_s1_load_store_del_all_counted(self) -> None:
        occ = _occurrences("kp = kp + u\ndel kp\nreturn t")
        assert len(occ) == 1 + 3  # arg + (Store, Load, Del)

    def test_s2_for_and_with_targets(self) -> None:
        occ = _occurrences("for kp in [u]:\n    pass\nreturn kp")
        assert len(occ) == 1 + 2

    def test_s3_lambda_shadow_untouched(self) -> None:
        occ = _occurrences("g = lambda kp: kp + 1\nreturn g(u)")
        assert len(occ) == 1  # arg のみ (lambda 内は shadow)

    def test_s3_inner_def_shadow_untouched(self) -> None:
        occ = _occurrences("def inner():\n    kp = 2.0\n    return kp\nreturn inner()")
        assert len(occ) == 1

    def test_s4_closure_counted(self) -> None:
        occ = _occurrences("def inner():\n    return kp * 2\nreturn inner()")
        assert len(occ) == 1 + 1

    def test_s5_inner_default_evaluated_in_outer_scope(self) -> None:
        # `def inner(kp=kp)` の default の kp は F のパラメータ。本体の kp は shadow
        occ = _occurrences("def inner(kp=kp):\n    return kp\nreturn inner()")
        assert len(occ) == 1 + 1

    def test_s6_only_outermost_iter_counted(self) -> None:
        occ = _occurrences("vals = [kp for kp in kp]\nreturn float(len(vals))")
        assert len(occ) == 1 + 1  # 最外 iter の kp だけ

    def test_s7_second_iter_in_comp_scope(self) -> None:
        occ = _occurrences("vals = [y for kp in [u] for y in [kp]]\nreturn float(len(vals))")
        assert len(occ) == 1  # comp が kp を束縛 → 2 番目の iter は shadow

    def test_s8_comprehension_walrus_binds_outer(self) -> None:
        occ = _occurrences("vals = [(kp := float(x)) for x in [u]]\nreturn kp")
        assert len(occ) == 1 + 2  # walrus target + return の Load

    def test_comp_without_binding_counts_references(self) -> None:
        occ = _occurrences("vals = [kp * x for x in [u]]\nreturn vals[0]")
        assert len(occ) == 1 + 1

    def test_missing_param_rejected(self) -> None:
        with pytest.raises(PythonFunctionRewriteError, match="no keyword-only"):
            _occurrences("return u", name="nope")


class TestRenameRejections:
    @pytest.mark.parametrize(
        ("label", "body"),
        [
            ("u1_global", "global kp\nreturn u"),
            ("u1_nonlocal_inner", "def inner():\n    nonlocal kp\nreturn u"),
            ("u2_import", "import os as kp\nreturn u"),
            ("u3_except_as", "try:\n    pass\nexcept ValueError as kp:\n    pass\nreturn u"),
            ("u4_match_capture", "match u:\n    case kp:\n        pass\nreturn kp"),
            ("u5_fstring", 'msg = f"{kp}"\nreturn u'),
            ("u6_locals", "d = locals()\nreturn kp"),
            ("u6_eval", 'v = eval("kp")\nreturn u'),
            ("u7_classdef", "class C:\n    pass\nreturn kp"),
            ("g_a_nested_def_named_target", "def kp():\n    return 1.0\nreturn u"),
        ],
    )
    def test_rejected_constructs(self, label: str, body: str) -> None:
        with pytest.raises(PythonFunctionRewriteError) as ei:
            _occurrences(body)
        assert ei.value.kind == "unsupported"

    def test_fstring_without_target_allowed(self) -> None:
        occ = _occurrences('msg = f"{u}"\nreturn kp')
        assert len(occ) == 1 + 1

    def test_global_of_other_name_allowed(self) -> None:
        occ = _occurrences("global other\nreturn kp")
        assert len(occ) == 1 + 1


# ---------------------------------------------------------------------------
# SPEC-0025 / ADR-0075: rename の splice と E4a / E4b
# ---------------------------------------------------------------------------


class TestParamRename:
    def test_basic_rename_signature_and_body(self) -> None:
        new = _rw(KW1, params=[RenameParam(old="kp", new="gain")])
        assert "*, gain: float = 1.0" in new
        assert "return u * gain" in new
        assert "kp" not in new
        s = _spec(new)
        assert s.params_spec == (("gain", 1.0, float, False),)

    def test_rename_preserves_default_type_required_and_order(self) -> None:
        new = _rw(KW3, params=[RenameParam(old="b", new="count")])
        assert [p[0] for p in _spec(new).params_spec] == ["a", "count", "c"]
        assert _spec(new).params_spec[1] == ("count", 2, int, False)

    def test_rename_closure_reference(self) -> None:
        code = (
            "@block\n"
            "def f(t: float, u: float, *, kp: float = 1.0) -> float:\n"
            "    def inner():\n"
            "        return kp * 2\n"
            "    return inner() + u\n"
        )
        new = _rw(code, params=[RenameParam(old="kp", new="gain")])
        assert "return gain * 2" in new

    def test_rename_leaves_shadowed_strings_attributes_kwargs(self) -> None:
        code = (
            "@block\n"
            "def f(t: float, u: float, *, kp: float = 1.0) -> float:\n"
            '    label = "kp stays"  # kp in comment stays\n'
            "    g = lambda kp: kp + 1\n"
            "    d = dict(kp=1)\n"
            "    return u * kp + g(t) + d.get('kp', 0)\n"
        )
        new = _rw(code, params=[RenameParam(old="kp", new="gain")])
        assert '"kp stays"' in new
        assert "# kp in comment stays" in new
        assert "lambda kp: kp + 1" in new
        assert "dict(kp=1)" in new
        assert "d.get('kp', 0)" in new
        assert "return u * gain" in new
        assert "*, gain: float = 1.0" in new

    def test_rename_minimal_diff_japanese_and_crlf(self) -> None:
        code = (
            "@block\r\n"
            "def f(t: float, u: float, *, kp: float = 1.0) -> float:\r\n"
            "    # 日本語の説明 ★\r\n"
            "    return u * kp\r\n"
        )
        new = _rw(code, params=[RenameParam(old="kp", new="gain")])
        assert "# 日本語の説明 ★" in new
        assert "\r\n" in new
        assert "return u * gain" in new

    def test_rename_noop_when_same_name(self) -> None:
        assert _rw(KW1, params=[RenameParam(old="kp", new="kp")]) == KW1

    def test_rename_missing_param_rejected(self) -> None:
        with pytest.raises(PythonFunctionRewriteError, match="no parameter named"):
            _rw(KW1, params=[RenameParam(old="nope", new="gain")])

    def test_rename_x0_rejected_when_stateful(self) -> None:
        code = (
            "@block(states=1)\n"
            "def f(t: float, x: np.ndarray, u: float, *, x0: float = 0.0) "
            "-> tuple[float, np.ndarray]:\n"
            "    return x[0], np.array([u])\n"
        )
        with pytest.raises(PythonFunctionRewriteError, match="x0"):
            _rw(code, params=[RenameParam(old="x0", new="init")])

    def test_rename_capture_rejected_by_n_used(self) -> None:
        code = (
            "@block\n"
            "def f(t: float, u: float, *, kp: float = 1.0) -> float:\n"
            "    gain = 2.0\n"
            "    return u * kp * gain\n"
        )
        with pytest.raises(PythonFunctionRewriteError, match="already used"):
            _rw(code, params=[RenameParam(old="kp", new="gain")])


class TestRenameSelfVerification:
    """E4a / E4b: planner を壊しても壊れたコードは決して返らない (ADR-0075 §論点 2)。"""

    def test_e4a_detects_extra_change_beyond_plan(self, monkeypatch) -> None:
        """splice が計画外のバイト (文字列リテラル) まで書き換えたら E4a が落とす。"""
        import flode.blocks.pythonfunc_rewrite as rw

        code = (
            "@block\n"
            "def f(t: float, u: float, *, kp: float = 1.0) -> float:\n"
            '    label = "kp"\n'
            "    return u * kp\n"
        )
        original = rw._rename_splices

        def broken(source, occurrences, old, new, block_id):
            splices = original(source, occurrences, old, new, block_id)
            # 文字列リテラル "kp" の中身も書き換える (構文は壊れない = E1〜E3 は通る)
            pos = source.data.find(b'"kp"') + 1
            splices.append(rw._Splice(pos, pos + 2, b"xx"))
            return splices

        monkeypatch.setattr(rw, "_rename_splices", broken)
        with pytest.raises(PythonFunctionRewriteError, match="differs from the plan") as ei:
            _rw(code, params=[RenameParam(old="kp", new="gain")])
        assert ei.value.kind == "spec"
        assert ei.value.reason == "rewrite_verify_rename_mismatch"

    def test_e4b_detects_missed_closure_occurrence(self, monkeypatch) -> None:
        """planner が閉包参照を取りこぼす = 計画と実差分が同じ誤りを含み E4a は通る。
        E4b (symtable 同型性) だけがこれを捕まえる。"""
        import flode.blocks.pythonfunc_rewrite as rw

        code = (
            "@block\n"
            "def f(t: float, u: float, *, kp: float = 1.0) -> float:\n"
            "    def inner():\n"
            "        return kp * 2\n"
            "    return inner() + u\n"
        )
        original = rw._plan_rename_occurrences

        def forgetful(func_def, old, block_id):
            occurrences = original(func_def, old, block_id)
            # 閉包 (入れ子スコープ内) の Name を 1 つ落とす
            kept = [n for n in occurrences if not (isinstance(n, ast.Name) and n.lineno >= 4)]
            assert len(kept) < len(occurrences)
            return kept

        monkeypatch.setattr(rw, "_plan_rename_occurrences", forgetful)
        with pytest.raises(PythonFunctionRewriteError, match="binding structure") as ei:
            _rw(code, params=[RenameParam(old="kp", new="gain")])
        assert ei.value.kind == "spec"
        assert ei.value.reason == "rewrite_verify_rename_mismatch"


class TestRenameGuardAssumptions:
    """ADR-0075 §Confidence の未検証事項を固定する guard (G1 / G3)。"""

    GUARD_SRC = (
        "@block\n"
        "def f(t: float, u: float, *, kp: float = 1.0) -> float:\n"
        "    g1 = lambda a: a + kp\n"
        "    g2 = lambda b: b - kp\n"
        "    def inner():\n"
        "        return kp\n"
        "    vals = [kp * x for x in [u]]\n"
        "    return g1(u) + g2(u) + inner() + vals[0]\n"
    )

    def test_g1_symtable_children_order_deterministic(self) -> None:
        import symtable

        def flatten(table):
            out = [(str(table.get_type()), table.get_name(), table.get_lineno())]
            for child in table.get_children():
                out.extend(flatten(child))
            return out

        t1 = symtable.symtable(self.GUARD_SRC, "<g1>", "exec")
        t2 = symtable.symtable(self.GUARD_SRC, "<g1>", "exec")
        assert flatten(t1) == flatten(t2)
        # rename 前後でもスコープ列 (type, name, lineno) が一致すること
        renamed = self.GUARD_SRC.replace("kp", "gain")
        t3 = symtable.symtable(renamed, "<g1>", "exec")
        assert [(t, n) for t, n, _ in flatten(t1)] == [(t, n) for t, n, _ in flatten(t3)]

    def test_g3_ast_dump_deterministic(self) -> None:
        tree = ast.parse(self.GUARD_SRC)
        assert ast.dump(tree) == ast.dump(ast.parse(self.GUARD_SRC))

    def test_rename_via_engine_on_guard_source(self) -> None:
        # 2 つの lambda (同名スコープ) + 入れ子 def + comprehension の複合形で
        # E4b の同時再帰が偽陽性を出さないこと
        new = _rw(self.GUARD_SRC, params=[RenameParam(old="kp", new="gain")])
        assert "lambda a: a + gain" in new
        assert "lambda b: b - gain" in new
        assert "return gain" in new
        assert "[gain * x for x in [u]]" in new
