"""``PythonFunction`` の静的ソース書き換えエンジン (SPEC-0024 / ADR-0074)。

GUI の「ポート数 / ポート名の編集」を、**コードを SSOT に保ったまま** 実現する:
Inspector の操作はここでソーステキストの最小 splice に翻訳され、書き換え後の
コードがモデルに保存される。``exec`` は一切しない (W1)。

設計の要点 (ADR-0074):

* **バイト領域で完結する** (:class:`_SourceBytes`)。``ast`` の ``col_offset`` は
  **UTF-8 バイトオフセット** なので、``code.encode("utf-8")`` した bytes 上で
  splice し、最後に 1 回だけ decode する。文字インデックスへの変換関数を
  作らない = 日本語コメント / 絵文字で位置がずれる余地が原理的にない
* **最小 diff** (W2)。編集対象スパン以外はバイト等価で保存される (コメント /
  docstring / 引用符 / 改行コード / インデントに触れない)
* **自己検証** (W3)。書き換え結果を必ず :func:`analyze_source` (唯一の導出者) で
  再解析し、要求した構造と一致し (E1)、要求していない構造を壊していない (E2)
  ことを確認してから返す。失敗時は :class:`PythonFunctionRewriteError` を投げ、
  **壊れたコードは決して返らない**
* **関数本体に触れない** (W4)。編集範囲はデコレータ引数と型注釈のみ。
  ポート数を減らして本体に ``u[2]`` 参照が残る等はユーザー責務 (実行時エラー)
* **patch セマンティクス** (W5)。``None`` の項目は書き換えない。ポート数変更時は
  既存のポート名列の長さも同じ書き換えで同期する (§2.6: 増 = 末尾に ``""``、減 = 末尾削除)
"""

from __future__ import annotations

import ast
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

from ..core.decorator import _resolve_port_names
from ..exceptions import (
    BlockSpecError,
    PythonFunctionRewriteError,
    PythonFunctionSourceError,
)
from .pythonfunc_source import (
    SourceSpec,
    _find_decorated_function,
    _is_block_decorator,
    analyze_source,
)

_logger = logging.getLogger("flode.blocks.pythonfunc_rewrite")

#: GUI / REST から編集できるポート数の上限 (SPEC-0024 §2.7)。DSL 自体には課さない
#: (= コードで書く分には制限しない)。キャンバスのハンドル等分配の実用限界と
#: 生成リテラル長 (DoS 面) の両方から。
MAX_PYTHON_FUNCTION_PORTS = 32

#: CPython の行区切り (``\r\n`` / ``\r`` / ``\n``)。``str.splitlines()`` は
#: form feed / U+2028 等でも分割してしまい ``ast`` の行番号と食い違うため使わない。
_LINE_BREAK_RE = re.compile(rb"\r\n|\r|\n")

#: 新規キーワードを挿入するときの順序 (SPEC §2.4)。
_KEYWORD_ORDER = ("inputs", "outputs", "input_names", "output_names")


# ---------------------------------------------------------------------------
# バイト領域の source map (ADR-0074 §論点 1)
# ---------------------------------------------------------------------------


class _SourceBytes:
    """UTF-8 bytes 上で ``ast`` ノードの位置をバイトオフセットに解決する。"""

    def __init__(self, code: str) -> None:
        self.data: bytes = code.encode("utf-8")
        starts = [0]
        for m in _LINE_BREAK_RE.finditer(self.data):
            starts.append(m.end())
        self._line_starts = starts

    def offset(self, lineno: int, col_offset: int) -> int:
        """(1 始まり行, UTF-8 バイト列) → 全体バイトオフセット。"""
        return self._line_starts[lineno - 1] + col_offset

    def span(self, node: ast.AST) -> tuple[int, int]:
        """ノードの [start, end) バイトスパン。"""
        end_lineno = getattr(node, "end_lineno", None)
        end_col = getattr(node, "end_col_offset", None)
        if end_lineno is None or end_col is None:
            raise PythonFunctionRewriteError(
                f"PythonFunction: AST node {type(node).__name__} has no end position; "
                f"cannot rewrite safely.",
                kind="unsupported",
            )
        return (
            self.offset(node.lineno, node.col_offset),  # type: ignore[attr-defined]
            self.offset(end_lineno, end_col),
        )

    def segment(self, node: ast.AST) -> bytes:
        start, end = self.span(node)
        return self.data[start:end]


@dataclass(frozen=True)
class _Splice:
    """バイト範囲 ``[start, end)`` を ``replacement`` に置き換える 1 操作。"""

    start: int
    end: int
    replacement: bytes


def _apply_splices(source: _SourceBytes, splices: Sequence[_Splice]) -> str:
    """非重複を検証しつつ splice を適用し、UTF-8 decode して返す (唯一のテキスト操作点)。"""
    ordered = sorted(splices, key=lambda s: (s.start, s.end))
    out: list[bytes] = []
    cursor = 0
    for s in ordered:
        if s.start < cursor or s.end < s.start or s.end > len(source.data):
            raise PythonFunctionRewriteError(
                "PythonFunction: internal splice overlap/out-of-range; refusing to rewrite.",
                kind="unsupported",
            )
        out.append(source.data[cursor : s.start])
        out.append(s.replacement)
        cursor = s.end
    out.append(source.data[cursor:])
    return b"".join(out).decode("utf-8")


# ---------------------------------------------------------------------------
# デコレータ / 注釈の編集 (ADR-0074 §論点 2)
# ---------------------------------------------------------------------------


def _escape_port_name(name: str) -> str:
    """ダブルクォート固定の Python 文字列リテラル用エスケープ (SPEC §2.5)。

    ``repr`` は引用符の選択が値依存で diff が安定しないため使わない。制御文字は
    DSL (N4) で禁止済みなので ``\\`` と ``"`` だけを面倒みれば十分だが、万一
    紛れ込んでも自己検証 (再解析の N4) が拒否する。
    """
    return name.replace("\\", "\\\\").replace('"', '\\"')


def _names_tuple_literal(names: Sequence[str]) -> str:
    """常に tuple + ダブルクォートの決定的リテラル。1 要素は ``("a",)``。"""
    inner = ", ".join(f'"{_escape_port_name(n)}"' for n in names)
    if len(names) == 1:
        inner += ","
    return f"({inner})"


class _DecoratorEditor:
    """``@block`` デコレータのキーワード集合操作 → splice 列。"""

    def __init__(self, source: _SourceBytes, deco: ast.expr) -> None:
        self._source = source
        self._deco = deco
        self._call = deco if isinstance(deco, ast.Call) else None
        self._kwargs: dict[str, ast.keyword] = {}
        if self._call is not None:
            for kw in self._call.keywords:
                if kw.arg is not None:
                    self._kwargs[kw.arg] = kw
        self._pending_inserts: list[tuple[str, str]] = []
        self.splices: list[_Splice] = []

    def has(self, name: str) -> bool:
        return name in self._kwargs

    def set_value(self, name: str, literal_text: str) -> None:
        """既存キーワードの値リテラルを置換、無ければ挿入予約する。"""
        kw = self._kwargs.get(name)
        if kw is None:
            self._pending_inserts.append((name, literal_text))
            return
        start, end = self._source.span(kw.value)
        self.splices.append(_Splice(start, end, literal_text.encode("utf-8")))

    def remove(self, name: str) -> None:
        """キーワードを削除する (C-3)。区切りカンマも一緒に除く。"""
        kw = self._kwargs.get(name)
        if kw is None or self._call is None:
            return
        kw_start = self._keyword_start(kw)
        kw_end = self._source.span(kw.value)[1]
        remaining = [k for k in self._call.keywords if k is not kw and k.arg is not None]
        if not remaining and not self._pending_inserts:
            # 最後のキーワードを消す → `@block(...)` を裸の `@block` に戻す (可逆)
            func_end = self._source.span(self._call.func)[1]
            call_end = self._source.span(self._call)[1]
            self.splices.append(_Splice(func_end, call_end, b""))
            return
        index = self._call.keywords.index(kw)
        if index > 0:
            # 直前のキーワード終端から自分の終端まで (= 手前のカンマ + 空白 + 自分)
            prev_end = self._source.span(self._call.keywords[index - 1].value)[1]
            self.splices.append(_Splice(prev_end, kw_end, b""))
        else:
            # 先頭 → 自分の始端から次のキーワード名の始端まで (= 自分 + 後ろのカンマ + 空白)
            next_start = self._keyword_start(self._call.keywords[index + 1])
            self.splices.append(_Splice(kw_start, next_start, b""))

    def _keyword_start(self, kw: ast.keyword) -> int:
        lineno = getattr(kw, "lineno", None)
        col = getattr(kw, "col_offset", None)
        if lineno is None or col is None:
            # ADR-0074 §Confidence 1 のフォールバック: 値の始端から後方に `arg=` を探す
            value_start = self._source.span(kw.value)[0]
            head = self._source.data[:value_start]
            m = re.search(re.escape((kw.arg or "").encode("utf-8")) + rb"\s*=\s*$", head)
            if m is None:
                raise PythonFunctionRewriteError(
                    f"PythonFunction: cannot locate keyword {kw.arg!r} in source.",
                    kind="unsupported",
                )
            return m.start()
        return self._source.offset(lineno, col)

    def flush_inserts(self) -> None:
        """予約済みの新規キーワードを規定順で 1 回の splice にまとめて挿入する。"""
        if not self._pending_inserts:
            return
        ordered = sorted(self._pending_inserts, key=lambda item: _KEYWORD_ORDER.index(item[0]))
        text = ", ".join(f"{name}={literal}" for name, literal in ordered)
        if self._call is None:
            # 裸の `@block` → `@block(<...>)`
            end = self._source.span(self._deco)[1]
            self.splices.append(_Splice(end, end, f"({text})".encode()))
        elif self._call.keywords:
            # 末尾キーワードの値の end 直後に挿入 (SPEC §2.4 の ADR 訂正:
            # 「閉じ括弧の直前」だと trailing comma で `, ,` になり壊れる)
            last = self._call.keywords[-1]
            anchor = self._source.span(last.value)[1]
            self.splices.append(_Splice(anchor, anchor, f", {text}".encode()))
        else:
            # `@block()` (空括弧) → 閉じ括弧の直前に挿入
            call_end = self._source.span(self._call)[1]
            self.splices.append(_Splice(call_end - 1, call_end - 1, text.encode("utf-8")))
        self._pending_inserts.clear()


def _annotation_elements(node: ast.expr) -> list[ast.expr] | None:
    """``tuple[...]`` 注釈なら要素ノードの list、それ以外 (スカラー等) は ``None``。"""
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "tuple"
    ):
        inner = node.slice
        return list(inner.elts) if isinstance(inner, ast.Tuple) else [inner]
    return None


def _rewrite_count_annotation(
    source: _SourceBytes, node: ast.expr, target: int, *, what: str
) -> _Splice | None:
    """スカラー / ``tuple[...]`` 注釈をポート数 ``target`` に合わせる (A-2 / A-3)。

    Returns:
        splice (no-op なら ``None``)。

    Raises:
        PythonFunctionRewriteError: 注釈の形が規則の対象外 (= 受理契約の内側では
            起きないはずだが、防御的に unsupported とする)。
    """
    elements = _annotation_elements(node)
    start, end = source.span(node)
    if elements is None:
        # スカラー注釈 (float / int / np.float64 等)
        if isinstance(node, ast.Name | ast.Attribute):
            if target == 1:
                return None
            seg = source.segment(node).decode("utf-8")
            text = "tuple[" + ", ".join([seg] * target) + "]"
            return _Splice(start, end, text.encode("utf-8"))
        raise PythonFunctionRewriteError(
            f"PythonFunction: cannot adjust the {what} annotation "
            f"`{source.segment(node).decode('utf-8', 'replace')}`; edit the code directly.",
            kind="unsupported",
            lineno=getattr(node, "lineno", None),
        )
    if target == len(elements):
        return None
    if target == 1:
        # `tuple[T1, ...]` → 第 1 要素のテキストに置換 (スカラーへ戻す)
        return _Splice(start, end, source.segment(elements[0]))
    segs = [source.segment(e).decode("utf-8") for e in elements]
    if target > len(segs):
        segs = segs + [segs[-1]] * (target - len(segs))
    else:
        segs = segs[:target]
    text = "tuple[" + ", ".join(segs) + "]"
    return _Splice(start, end, text.encode("utf-8"))


# ---------------------------------------------------------------------------
# 公開 API
# ---------------------------------------------------------------------------


def rewrite_source(
    code: str,
    *,
    inputs: int | None = None,
    outputs: int | None = None,
    input_names: Sequence[str] | None = None,
    output_names: Sequence[str] | None = None,
    block_id: str | None = None,
) -> str:
    """``@block`` 形ソースのポート構造を書き換えた新しいソースを返す (SPEC-0024)。

    patch セマンティクス: ``None`` の項目は書き換えない。ポート数を変更するとき、
    既存のポート名列は同じ書き換えで長さを同期する (§2.6)。要求がすべて現状と
    一致する場合は **入力をバイト等価のまま** 返す。

    Args:
        code: 現在のソース (受理契約 ADR-0073 §2-E の内側であること)。
        inputs: 目標入力ポート数 (1..32。``u`` 引数の無い関数では指定不可)。
        outputs: 目標出力ポート数 (1..32)。
        input_names: 入力ポート名列 (長さは **編集後の** 入力数と完全一致)。
        output_names: 出力ポート名列。
        block_id: エラーメッセージ用。

    Returns:
        書き換え後のソース。自己検証 (再解析 + 構造突合) 済み。

    Raises:
        PythonFunctionSourceError: ``code`` がそもそも受理契約外 (構文エラー等)。
        PythonFunctionRewriteError: 書き換え不能 (``kind="unsupported"``) /
            範囲外 (同)、または自己検証失敗 (``kind="verify"``、バグの兆候として
            ERROR ログに元コードを残す)。**いずれの場合も元コードは不変**。
    """
    old_spec = analyze_source(code, block_id=block_id)

    target_inputs = _validated_count(inputs, "inputs", old_spec, block_id)
    target_outputs = _validated_count(outputs, "outputs", old_spec, block_id)
    final_inputs = target_inputs if target_inputs is not None else old_spec.n_inputs
    final_outputs = target_outputs if target_outputs is not None else old_spec.n_outputs

    final_input_names = _plan_names(
        input_names, old_spec.input_names, final_inputs, role="input_names", block_id=block_id
    )
    final_output_names = _plan_names(
        output_names, old_spec.output_names, final_outputs, role="output_names", block_id=block_id
    )

    expected = replace(
        old_spec,
        n_inputs=final_inputs,
        n_outputs=final_outputs,
        input_names=final_input_names,
        output_names=final_output_names,
    )

    source = _SourceBytes(code)
    tree = ast.parse(code)
    func_def = _find_decorated_function(tree, block_id)
    deco = next(d for d in func_def.decorator_list if _is_block_decorator(d))
    editor = _DecoratorEditor(source, deco)
    splices: list[_Splice] = list()

    # --- 入力数 (A 規則) ---
    if target_inputs is not None and target_inputs != old_spec.n_inputs:
        if editor.has("inputs"):
            editor.set_value("inputs", str(target_inputs))  # A-1
        else:
            u_node = _u_annotation_node(func_def, old_spec)
            sp = _rewrite_count_annotation(source, u_node, target_inputs, what="input")
            if sp is not None:
                splices.append(sp)

    # --- 出力数 (B 規則) ---
    if target_outputs is not None and target_outputs != old_spec.n_outputs:
        if editor.has("outputs"):
            editor.set_value("outputs", str(target_outputs))  # B-1
        elif func_def.returns is not None:
            node = func_def.returns
            if old_spec.n_states > 0:
                elements = _annotation_elements(node)
                if elements is None or len(elements) != 2:
                    raise PythonFunctionRewriteError(
                        f"PythonFunction[{block_id}]: stateful return annotation is not "
                        f"`tuple[<out>, ndarray]`; cannot rewrite outputs.",
                        kind="unsupported",
                        lineno=getattr(node, "lineno", None),
                        block_id=block_id,
                    )
                node = elements[0]  # B-3: 第 1 要素のみ調整、状態ベクトル側は不変
            sp = _rewrite_count_annotation(source, node, target_outputs, what="output")
            if sp is not None:
                splices.append(sp)
        else:
            editor.set_value("outputs", str(target_outputs))  # B-4: キーワード挿入

    # --- ポート名 (C 規則 + §2.6 同期) ---
    _plan_name_keyword(editor, "input_names", old_spec.input_names, final_input_names)
    _plan_name_keyword(editor, "output_names", old_spec.output_names, final_output_names)

    editor.flush_inserts()
    splices.extend(editor.splices)

    if not splices:
        return code  # 完全 no-op (バイト等価)

    new_code = _apply_splices(source, splices)

    # --- 自己検証 (W3): 唯一の導出者に読み直させる ---
    try:
        new_spec = analyze_source(new_code, block_id=block_id)
    except PythonFunctionSourceError as e:
        _logger.error(
            "PythonFunction rewrite self-verification failed (re-analysis) for block %r: %s\n"
            "--- original code ---\n%s\n--- rewritten (DISCARDED) ---\n%s",
            block_id,
            e,
            code,
            new_code,
        )
        raise PythonFunctionRewriteError(
            f"PythonFunction[{block_id}]: rewrite produced source that no longer parses "
            f"({e}); the original code is unchanged. This is a bug in the rewrite rules.",
            kind="verify",
            block_id=block_id,
        ) from e
    if replace(new_spec, lineno=old_spec.lineno) != replace(expected, lineno=old_spec.lineno):
        _logger.error(
            "PythonFunction rewrite self-verification failed (structure mismatch) for "
            "block %r: expected %r, got %r\n--- original code ---\n%s",
            block_id,
            expected,
            new_spec,
            code,
        )
        raise PythonFunctionRewriteError(
            f"PythonFunction[{block_id}]: rewritten source does not match the requested "
            f"structure; the original code is unchanged. This is a bug in the rewrite rules.",
            kind="verify",
            block_id=block_id,
        )
    return new_code


def _validated_count(
    value: int | None, role: str, spec: SourceSpec, block_id: str | None
) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise PythonFunctionRewriteError(
            f"PythonFunction[{block_id}]: {role} must be an int, got {value!r}",
            kind="unsupported",
            block_id=block_id,
        )
    if role == "inputs" and not spec.has_u_arg:
        raise PythonFunctionRewriteError(
            f"PythonFunction[{block_id}]: the function has no `u` parameter, so the "
            f"number of inputs is fixed at 0; add a `u` parameter in the code to "
            f"enable input editing.",
            kind="unsupported",
            block_id=block_id,
        )
    if not 1 <= value <= MAX_PYTHON_FUNCTION_PORTS:
        raise PythonFunctionRewriteError(
            f"PythonFunction[{block_id}]: {role} must be in 1..{MAX_PYTHON_FUNCTION_PORTS}, "
            f"got {value}",
            kind="unsupported",
            block_id=block_id,
        )
    return value


def _plan_names(
    requested: Sequence[str] | None,
    current: tuple[str, ...],
    final_count: int,
    *,
    role: str,
    block_id: str | None,
) -> tuple[str, ...]:
    """最終的なポート名列を決める。要求があれば検証、無ければ §2.6 の長さ同期。"""
    if requested is not None:
        try:
            resolved = _resolve_port_names(
                requested, final_count, role=role, owner_name=str(block_id)
            )
        except BlockSpecError as e:
            raise PythonFunctionRewriteError(
                f"PythonFunction[{block_id}]: {e}", kind="spec", block_id=block_id
            ) from e
        # C-3: 全要素が空文字 = 「全ポート無名」は空 tuple に正規化する
        # (= キーワード削除の対象。`input_names=("", "")` というノイズを書かない)
        return () if resolved and all(n == "" for n in resolved) else resolved
    if not current:
        return ()
    if len(current) > final_count:
        synced = current[:final_count]
    else:
        synced = current + ("",) * (final_count - len(current))
    return () if all(n == "" for n in synced) else synced


def _plan_name_keyword(
    editor: _DecoratorEditor, role: str, current: tuple[str, ...], final: tuple[str, ...]
) -> None:
    """C-1 / C-2 / C-3: キーワードの置換・挿入・削除を editor に積む。"""
    if final == current:
        return
    if not final:
        editor.remove(role)  # C-3 (全部空 → キーワード削除)
        return
    editor.set_value(role, _names_tuple_literal(final))  # C-1 / C-2


def _u_annotation_node(func_def: ast.FunctionDef, spec: SourceSpec) -> ast.expr:
    """``u`` 引数 (位置引数の最後、``t``/``x`` の後) の注釈ノードを返す。"""
    positional = list(func_def.args.posonlyargs) + list(func_def.args.args)
    # 受理契約: (t, u) または (t, x, u)。has_u_arg 確認済みなので末尾が u。
    u_arg = positional[-1]
    if u_arg.annotation is None:
        # 注釈なしで n_inputs が決まるのは inputs= 明示のときだけ (= A-1 で処理済み)。
        raise PythonFunctionRewriteError(
            f"PythonFunction: `{u_arg.arg}` has no annotation and no `inputs=` keyword; "
            f"cannot rewrite the input count.",
            kind="unsupported",
            lineno=u_arg.lineno,
        )
    return u_arg.annotation
