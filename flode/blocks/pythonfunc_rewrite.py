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
import keyword
import logging
import math
import re
import unicodedata
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


def _code_for_log(code: str, max_lines: int = 20) -> str:
    """verify 失敗ログ用のソース縮約 (security-reviewer NIT-1: 全文をログに残さない)。

    ユーザーコードに秘密情報が書かれている可能性があるため、先頭 ``max_lines`` 行 +
    SHA-256 に縮める (回帰ケースの特定には digest とテスト再現で足りる)。
    """
    import hashlib

    lines = code.splitlines()
    head = "\n".join(lines[:max_lines])
    suffix = f"\n... ({len(lines) - max_lines} more lines)" if len(lines) > max_lines else ""
    digest = hashlib.sha256(code.encode("utf-8", "surrogatepass")).hexdigest()
    return f"{head}{suffix}\n[sha256={digest}]"


#: GUI / REST から編集できるポート数の上限 (SPEC-0024 §2.7)。DSL 自体には課さない
#: (= コードで書く分には制限しない)。キャンバスのハンドル等分配の実用限界と
#: 生成リテラル長 (DoS 面) の両方から。
MAX_PYTHON_FUNCTION_PORTS = 32

#: 書き換え結果のサイズ上限 (= introspect の入力上限と同じ 256 KiB)。長い tuple
#: 注釈の要素複製はポート数倍まで増幅しうるため、結果が入力上限を超える書き換えは
#: 拒否する (security-reviewer NIT-2: 再投入による多段増幅も 1 ホップで断つ)。
MAX_REWRITTEN_CODE_CHARS = 256 * 1024

#: GUI / REST から編集できるパラメータ (kw-only 引数) の個数上限 (SPEC-0025 §確定事項 8)。
#: ポート数上限と同じく GUI / REST の policy であり、DSL 自体には課さない。
MAX_PYTHON_FUNCTION_PARAMS = 32

#: パラメータ名の最大長 (SPEC-0025 P4)。
MAX_PARAM_NAME_LENGTH = 64

#: ``str`` 型 default の最大長 (SPEC-0025 §確定事項 8)。
MAX_PARAM_STR_DEFAULT_LENGTH = 256

#: UI から追加できるパラメータの型語彙 (SPEC-0025 §確定事項 9)。いずれも
#: :mod:`pythonfunc_source` の ``_ANNOTATION_NAMES`` の内側 = 静的解決できる。
PARAM_TYPE_NAMES = ("float", "int", "bool", "str")

_PARAM_PY_TYPES: dict[str, type] = {"float": float, "int": int, "bool": bool, "str": str}

#: パラメータ名の文字集合 (SPEC-0025 P2: **ASCII 限定**、§確定事項 3)。
#: CPython は識別子をトークナイズ時に NFKC 正規化するため、非 ASCII を許すと
#: 「ソースに書いた名前」と「AST から読み戻る名前」が食い違う経路が生まれる。
#: ASCII 限定にすることでその経路を設計上消す (P10)。
_PARAM_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: exec 名前空間に注入される名前 (``pythonfunc._exec_namespace``)。パラメータ名が
#: これらを shadow すると本体の ``np.array(...)`` 等が静かに壊れるため拒否する (P8)。
_INJECTED_GLOBAL_NAMES = frozenset({"block", "np", "npt"})

#: ``str`` default で拒否する Unicode カテゴリ (制御・改行・サロゲート類。
#: ポート名 (decorator の N4) と同じ基準)。
_FORBIDDEN_DEFAULT_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp", "Cs"})


@dataclass(frozen=True)
class AddParam:
    """末尾にキーワード専用パラメータを 1 つ足す (SPEC-0025 規則 AP)。

    Attributes:
        name: パラメータ名 (P1〜P9 + N-USED を満たすこと)。
        type: :data:`PARAM_TYPE_NAMES` のいずれか。
        default: default 値 (``type`` と整合する Python 値。default 必須 = §確定事項 10)。
    """

    name: str
    type: str
    default: float | int | bool | str


@dataclass(frozen=True)
class RemoveParam:
    """キーワード専用パラメータを 1 つ消す (規則 DP)。

    本体の残留参照は**検査しない** (SPEC-0025 §確定事項 2 / §機能要件 2.3)。
    残った参照は実行時に ``NameError`` → 既存の ``PythonFunctionEvalError`` 経路で
    block id + 行番号付きに報告される。
    """

    name: str


@dataclass(frozen=True)
class RenameParam:
    """パラメータ名を変える (W4-E)。``from`` が Python の予約語のため ``old`` / ``new``。"""

    old: str
    new: str


#: パラメータ編集の命令。ポート編集 (宣言的な目標値) と違い**命令列**なのは、
#: rename を remove + add と区別しないと ``user_params`` の値の引き継ぎが
#: 表現できないため (ADR-0075 §論点 5)。
ParamEdit = AddParam | RemoveParam | RenameParam

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


def _consume_trailing_separator(data: bytes, pos: int) -> int:
    """``pos`` から空白 → 任意のカンマ → 空白 → 同一行コメントを読み進めた終端を返す。

    デコレータのキーワード削除 (ADR-0074 §Amendments 2) とシグネチャの kw-only
    引数削除 (ADR-0075 DP-2 / DP-3) で共用する (規則を 2 箇所に書かない)。
    """
    n = len(data)
    i = pos
    while i < n and data[i : i + 1] in (b" ", b"\t"):
        i += 1
    if i < n and data[i : i + 1] == b",":
        i += 1
        while i < n and data[i : i + 1] in (b" ", b"\t"):
            i += 1
    if i < n and data[i : i + 1] == b"#":
        while i < n and data[i : i + 1] not in (b"\n", b"\r"):
            i += 1
    return i


def _extend_back_over_separator(data: bytes, pos: int) -> int:
    """``pos`` の直前が同一行の「空白 + カンマ + 空白」だけなら、その始端を返す。

    改行やコメントを跨ぐ場合 (= 複数行形で直前要素が別行) は拡張せず ``pos`` を
    そのまま返す (前方の trailing comment を巻き込まないため)。コメントは行末まで
    続くため、カンマより前に同一行でコメントが現れることはない。
    """
    i = pos
    while i > 0 and data[i - 1 : i] in (b" ", b"\t"):
        i -= 1
    if i > 0 and data[i - 1 : i] == b",":
        i -= 1
        while i > 0 and data[i - 1 : i] in (b" ", b"\t"):
            i -= 1
        return i
    return pos


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
        """キーワードを削除する (C-3)。区切りカンマも一緒に除く。

        ADR-0074 §論点 2(d): **消す側を選ぶ**。削除対象より前にある保持キーワードの
        trailing comment を巻き込まないため、後続キーワードが在れば前方
        (``[kw_start, 次キーワードの始端)``) を消し、末尾キーワードのときだけ
        ``[kw_start, 自分のカンマ/コメントの終端)`` を消す (直前キーワードの
        カンマは trailing comma として残る = 合法)。
        """
        kw = self._kwargs.get(name)
        if kw is None or self._call is None:
            return
        kw_start = self._keyword_start(kw)
        kw_end = self._source.span(kw.value)[1]
        remaining = [k for k in self._call.keywords if k is not kw and k.arg is not None]
        if not remaining and not self._pending_inserts:
            # 最後の 1 個を消す → `@block(...)` を裸の `@block` に戻す (可逆)
            func_end = self._source.span(self._call.func)[1]
            call_end = self._source.span(self._call)[1]
            self.splices.append(_Splice(func_end, call_end, b""))
            return
        index = self._call.keywords.index(kw)
        if index < len(self._call.keywords) - 1:
            # 後続キーワードあり → 自分の始端から次キーワード名の始端まで
            # (= 自分 + 自分のカンマ + 自分の trailing comment + 空白)。
            # 前方 (保持されるキーワードのコメント) には一切触れない。
            next_start = self._keyword_start(self._call.keywords[index + 1])
            self.splices.append(_Splice(kw_start, next_start, b""))
        else:
            # 末尾キーワード → 自分と、直後のカンマ / 同一行の trailing comment を消す。
            # 直前キーワードとの間が同一行の「空白 + カンマ + 空白」だけ (コメント・
            # 改行なし) なら区切りカンマも後方に消し `@block(inputs=2)` の形に戻す。
            # 改行やコメントを挟む複数行形では触れず、直前キーワードのカンマを
            # trailing comma として残す (Python の呼び出しで合法)。
            end = _consume_trailing_separator(self._source.data, kw_end)
            start = _extend_back_over_separator(self._source.data, kw_start)
            self.splices.append(_Splice(start, end, b""))

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
# パラメータ (kw-only 引数) の編集 (SPEC-0025 / ADR-0075)
# ---------------------------------------------------------------------------


def _identifiers_used_in_function(func_def: ast.FunctionDef) -> set[str]:
    """関数内で**識別子として**現れる名前の集合 (N-USED、ADR-0075 §論点 1)。

    新しい名前がここに含まれるなら追加 / rename を拒否する。P6 (位置引数名) /
    P7 (関数名) の上位互換であり、builtins の shadow (``min`` 等を本体で使っている
    のに同名パラメータを足す) と rename 時の名前捕獲を同じ規則で塞ぐ。
    ``Attribute.attr`` / ``keyword.arg`` / 文字列は含めない (識別子の名前空間ではない)。
    無関係な内側スコープのローカル名も含む過剰側の近似だが、安全であり
    「関数内で既に使われている」というメッセージで説明できる。
    """
    used: set[str] = set()
    for node in ast.walk(func_def):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.arg):
            used.add(node.arg)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            used.add(node.name)
        elif isinstance(node, ast.alias):
            used.add((node.asname or node.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name is not None:
            used.add(node.name)
        elif isinstance(node, ast.Global | ast.Nonlocal):
            used.update(node.names)
        elif isinstance(node, ast.MatchAs | ast.MatchStar) and node.name is not None:
            used.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest is not None:
            used.add(node.rest)
    return used


def _module_level_bindings(tree: ast.Module, func_def: ast.FunctionDef) -> set[str]:
    """module レベルで束縛されうる名前の集合 (P8)。

    ``@block`` 関数以外の top-level 文を丸ごと走査する (他の module 関数の内側
    ローカルも含む過剰側の近似。安全側に倒す)。
    """
    bound: set[str] = set()
    for stmt in tree.body:
        if stmt is func_def:
            continue
        for node in ast.walk(stmt):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
                bound.add(node.id)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                bound.add(node.name)
            elif isinstance(node, ast.alias):
                bound.add((node.asname or node.name).split(".")[0])
            elif isinstance(node, ast.ExceptHandler) and node.name is not None:
                bound.add(node.name)
    return bound


def _validate_new_param_name(
    name: str,
    *,
    spec_params: Sequence[tuple[str, object, object, bool]],
    n_states: int,
    func_def: ast.FunctionDef,
    tree: ast.Module,
    block_id: str | None,
) -> None:
    """新しい名前 (追加 / rename 先) の検証 P1〜P9 + N-USED (SPEC-0025 §機能要件 1)。

    P1〜P4 (body 非依存の静的規則) は REST 層が先に 400 で弾くが、Python API から
    直接呼ばれる経路を裸にしないためここでも検証する (二重ゲート。ADR-0075 §論点 5)。
    """
    if not isinstance(name, str) or not _PARAM_NAME_RE.match(name):
        raise PythonFunctionRewriteError(
            f"PythonFunction[{block_id}]: parameter name must be an ASCII identifier "
            f"([A-Za-z_][A-Za-z0-9_]*), got {name!r}",
            kind="unsupported",
            reason="rewrite_param_invalid_name",
            block_id=block_id,
        )
    if keyword.iskeyword(name):
        raise PythonFunctionRewriteError(
            f"PythonFunction[{block_id}]: parameter name {name!r} is a Python keyword",
            kind="unsupported",
            reason="rewrite_param_invalid_name",
            block_id=block_id,
        )
    if len(name) > MAX_PARAM_NAME_LENGTH:
        raise PythonFunctionRewriteError(
            f"PythonFunction[{block_id}]: parameter name must be at most "
            f"{MAX_PARAM_NAME_LENGTH} characters, got {len(name)}",
            kind="unsupported",
            reason="rewrite_param_invalid_name",
            block_id=block_id,
        )
    if n_states > 0 and name == "x0":
        raise PythonFunctionRewriteError(
            f"PythonFunction[{block_id}]: `x0` is reserved for the initial state when states > 0",
            kind="unsupported",
            reason="rewrite_param_name_conflict",
            block_id=block_id,
        )
    if any(p[0] == name for p in spec_params):
        raise PythonFunctionRewriteError(
            f"PythonFunction[{block_id}]: a parameter named {name!r} already exists",
            kind="unsupported",
            reason="rewrite_param_name_conflict",
            block_id=block_id,
        )
    if name in _identifiers_used_in_function(func_def):
        raise PythonFunctionRewriteError(
            f"PythonFunction[{block_id}]: the name {name!r} is already used inside "
            f"the function; choose a different name",
            kind="unsupported",
            reason="rewrite_param_name_conflict",
            block_id=block_id,
        )
    if name in _INJECTED_GLOBAL_NAMES or name in _module_level_bindings(tree, func_def):
        raise PythonFunctionRewriteError(
            f"PythonFunction[{block_id}]: the name {name!r} would shadow a module-level "
            f"or injected binding (block / np / npt); choose a different name",
            kind="unsupported",
            reason="rewrite_param_name_conflict",
            block_id=block_id,
        )


def _param_default_literal(edit: AddParam, block_id: str | None) -> tuple[str, object]:
    """default 値の決定的リテラルと、E3 用の期待値 (coerce 済み) を返す。

    ``repr`` の揺れに依存しない形に固定する (ADR-0075 §論点 5): float は常に
    小数点か指数を含む形 (``literal_eval`` で要求値に round-trip する)、str は
    ダブルクォート + ``\\`` ``"`` のみエスケープ。期待値を要求値 (coerce 済み) に
    することで「生成リテラルが元の値に戻ること」まで E3 の検査対象になる。
    """
    v = edit.default
    if edit.type == "bool":
        if not isinstance(v, bool):
            raise PythonFunctionRewriteError(
                f"PythonFunction[{block_id}]: default for a bool parameter must be a "
                f"bool, got {v!r}",
                kind="unsupported",
                block_id=block_id,
            )
        return ("True" if v else "False", v)
    if edit.type == "int":
        if isinstance(v, bool) or not isinstance(v, int):
            raise PythonFunctionRewriteError(
                f"PythonFunction[{block_id}]: default for an int parameter must be an "
                f"int, got {v!r}",
                kind="unsupported",
                block_id=block_id,
            )
        return (str(v), v)
    if edit.type == "float":
        if isinstance(v, bool) or not isinstance(v, int | float):
            raise PythonFunctionRewriteError(
                f"PythonFunction[{block_id}]: default for a float parameter must be a "
                f"number, got {v!r}",
                kind="unsupported",
                block_id=block_id,
            )
        f = float(v)
        if not math.isfinite(f):
            raise PythonFunctionRewriteError(
                f"PythonFunction[{block_id}]: default for a float parameter must be "
                f"finite, got {f!r}",
                kind="unsupported",
                block_id=block_id,
            )
        text = repr(f)
        if "." not in text and "e" not in text and "E" not in text:
            text += ".0"
        return (text, f)
    if edit.type == "str":
        if not isinstance(v, str):
            raise PythonFunctionRewriteError(
                f"PythonFunction[{block_id}]: default for a str parameter must be a str, got {v!r}",
                kind="unsupported",
                block_id=block_id,
            )
        if len(v) > MAX_PARAM_STR_DEFAULT_LENGTH:
            raise PythonFunctionRewriteError(
                f"PythonFunction[{block_id}]: str default must be at most "
                f"{MAX_PARAM_STR_DEFAULT_LENGTH} characters, got {len(v)}",
                kind="unsupported",
                block_id=block_id,
            )
        if any(unicodedata.category(ch) in _FORBIDDEN_DEFAULT_CATEGORIES for ch in v):
            raise PythonFunctionRewriteError(
                f"PythonFunction[{block_id}]: str default must not contain control or "
                f"line-separator characters",
                kind="unsupported",
                block_id=block_id,
            )
        return (f'"{_escape_port_name(v)}"', v)
    raise PythonFunctionRewriteError(
        f"PythonFunction[{block_id}]: parameter type must be one of "
        f"{', '.join(PARAM_TYPE_NAMES)}, got {edit.type!r}",
        kind="unsupported",
        block_id=block_id,
    )


class _SignatureEditor:
    """関数シグネチャの kw-only 引数の追加 / 削除 → splice 列 (SPEC-0025 規則 AP / DP)。

    ``*`` / ``/`` は AST にノードを持たないため、**2 つの AST ノードのスパンに
    挟まれた領域だけ**をバイト走査する。受理契約 (``*args`` / ``**kwargs`` 禁止 =
    ``core/decorator.py`` の VAR_POSITIONAL / VAR_KEYWORD 拒否) により、この領域には
    空白 / 改行 / 行継続 / コメント / カンマ / ``/`` / ``*`` しか現れない
    (式・文字列は必ず arg / annotation / default ノードのスパンの内側にある)。
    **受理契約を緩めるときは `_DecoratorEditor` のカンマ探索と併せてここも見直すこと**
    (ADR-0075 §Consequences)。
    """

    def __init__(
        self, source: _SourceBytes, func_def: ast.FunctionDef, block_id: str | None
    ) -> None:
        self._source = source
        self._args = func_def.args
        self._block_id = block_id
        self.splices: list[_Splice] = []

    def _elem_end(self, arg: ast.arg, default: ast.expr | None) -> int:
        """要素の終端 = default 式の end (無ければ ``arg`` の end = 注釈込み)。

        AP のアンカーを ``arg`` の end にすると ``u: float = 0.0`` で
        ``= 1.0 = 0.0`` という構文破壊になる (SPEC §2.1 / ADR-0075 V19)。
        """
        node: ast.AST = default if default is not None else arg
        return self._source.span(node)[1]

    def _last_positional_end(self) -> int:
        positional = list(self._args.posonlyargs) + list(self._args.args)
        if not positional:
            # AP-3: 受理契約上あり得ない (最低 t がある)。防御的に拒否
            raise PythonFunctionRewriteError(
                f"PythonFunction[{self._block_id}]: function has no positional "
                f"parameters; cannot edit keyword-only parameters.",
                kind="unsupported",
                block_id=self._block_id,
            )
        default = self._args.defaults[-1] if self._args.defaults else None
        return self._elem_end(positional[-1], default)

    def _scan_separators(self, start: int) -> dict[bytes, int]:
        """``start`` から separator 領域を走査し、``*`` / ``/`` の位置を返す。"""
        data = self._source.data
        n = len(data)
        found: dict[bytes, int] = {}
        i = start
        while i < n:
            b = data[i : i + 1]
            if b in (b" ", b"\t", b"\r", b"\n", b"\\", b","):
                i += 1
            elif b == b"#":
                while i < n and data[i : i + 1] not in (b"\n", b"\r"):
                    i += 1
            elif b in (b"*", b"/") and b not in found:
                found[b] = i
                i += 1
            else:
                break
        return found

    def add(self, name: str, type_name: str, default_literal: str) -> None:
        """AP-1 / AP-2: 末尾に ``name: type = default`` を挿入する。"""
        a = self._args
        if a.kwonlyargs:
            # AP-1: 末尾 kw-only 要素 (default 込み) の直後
            anchor = self._elem_end(a.kwonlyargs[-1], a.kw_defaults[-1])
            text = f", {name}: {type_name} = {default_literal}"
        else:
            # AP-2: 末尾位置引数 (default 込み) の直後。`/` があればその直後
            p = self._last_positional_end()
            found = self._scan_separators(p)
            slash = found.get(b"/")
            anchor = slash + 1 if slash is not None else p
            text = f", *, {name}: {type_name} = {default_literal}"
        self.splices.append(_Splice(anchor, anchor, text.encode("utf-8")))

    def remove(self, name: str) -> None:
        """DP-1 / DP-2 / DP-3: kw-only 引数を 1 つ消す (消す側を選ぶ規則)。"""
        a = self._args
        index = next((i for i, arg in enumerate(a.kwonlyargs) if arg.arg == name), None)
        if index is None:
            raise PythonFunctionRewriteError(
                f"PythonFunction[{self._block_id}]: no keyword-only parameter named "
                f"{name!r} to remove.",
                kind="unsupported",
                reason="rewrite_param_not_found",
                block_id=self._block_id,
            )
        arg = a.kwonlyargs[index]
        arg_start = self._source.span(arg)[0]
        elem_end = self._elem_end(arg, a.kw_defaults[index])
        data = self._source.data
        if index < len(a.kwonlyargs) - 1:
            # DP-1: 前方削除 (自分 + 自分の default + カンマ + trailing comment。
            # 前方の保持要素には一切触れない)
            next_start = self._source.span(a.kwonlyargs[index + 1])[0]
            self.splices.append(_Splice(arg_start, next_start, b""))
        elif len(a.kwonlyargs) > 1:
            # DP-2: 末尾 kw-only (他に kw-only が残る)。自分 + 直後カンマ + 同一行
            # コメントを消し、直前要素と同一行に空白のみで隣接するときだけ前方カンマも消す
            end = _consume_trailing_separator(data, elem_end)
            start = _extend_back_over_separator(data, arg_start)
            self.splices.append(_Splice(start, end, b""))
        else:
            # DP-3: 唯一の kw-only → `*` セパレータごと消す (`def f(t, u, *)` は
            # SyntaxError)。始端を `*` にする (直前カンマから始めると前方の trailing
            # comment を巻き込む)。`/` は必ず `*` より前にあり削除範囲に入らない
            p = self._last_positional_end()
            found = self._scan_separators(p)
            star = found.get(b"*")
            if star is None:
                raise PythonFunctionRewriteError(
                    f"PythonFunction[{self._block_id}]: cannot locate the `*` separator "
                    f"in the signature; edit the code directly.",
                    kind="unsupported",
                    block_id=self._block_id,
                )
            end = _consume_trailing_separator(data, elem_end)
            start = _extend_back_over_separator(data, star)
            self.splices.append(_Splice(start, end, b""))


def _plan_param_edits(
    source: _SourceBytes,
    tree: ast.Module,
    func_def: ast.FunctionDef,
    old_spec: SourceSpec,
    params: Sequence[ParamEdit] | None,
    block_id: str | None,
) -> tuple[list[_Splice], tuple[tuple[str, object, object, bool], ...]]:
    """パラメータ編集命令列 → (splice 列, E3 用の期待 ``params_spec``)。

    期待値は命令を順に適用した姿。検証 (P/N-USED) も命令適用後の状態に対して行う。
    """
    if not params:
        return [], old_spec.params_spec
    editor = _SignatureEditor(source, func_def, block_id)
    expected: list[tuple[str, object, object, bool]] = list(old_spec.params_spec)
    for edit in params:
        if isinstance(edit, AddParam):
            if len(expected) >= MAX_PYTHON_FUNCTION_PARAMS:
                raise PythonFunctionRewriteError(
                    f"PythonFunction[{block_id}]: at most {MAX_PYTHON_FUNCTION_PARAMS} "
                    f"parameters can be declared via the UI.",
                    kind="unsupported",
                    reason="rewrite_param_limit",
                    block_id=block_id,
                )
            literal, coerced = _param_default_literal(edit, block_id)
            _validate_new_param_name(
                edit.name,
                spec_params=expected,
                n_states=old_spec.n_states,
                func_def=func_def,
                tree=tree,
                block_id=block_id,
            )
            editor.add(edit.name, edit.type, literal)
            expected.append((edit.name, coerced, _PARAM_PY_TYPES[edit.type], False))
        elif isinstance(edit, RemoveParam):
            if old_spec.n_states > 0 and edit.name == "x0":
                raise PythonFunctionRewriteError(
                    f"PythonFunction[{block_id}]: `x0` binds the initial state and "
                    f"cannot be removed while states > 0.",
                    kind="unsupported",
                    reason="rewrite_param_name_conflict",
                    block_id=block_id,
                )
            index = next((i for i, p in enumerate(expected) if p[0] == edit.name), None)
            if index is None:
                raise PythonFunctionRewriteError(
                    f"PythonFunction[{block_id}]: no parameter named {edit.name!r}.",
                    kind="unsupported",
                    reason="rewrite_param_not_found",
                    block_id=block_id,
                )
            editor.remove(edit.name)
            del expected[index]
        elif isinstance(edit, RenameParam):
            # SPEC-0025 W4-E。スコープ解析 + E4a/E4b と一体で実装する (ADR-0075
            # commit 2〜3)。それまでは保守的に拒否する
            raise PythonFunctionRewriteError(
                f"PythonFunction[{block_id}]: parameter rename is not supported yet.",
                kind="unsupported",
                reason="rewrite_rename_unsupported_construct",
                block_id=block_id,
            )
        else:  # 型上は到達しない (防御)
            raise PythonFunctionRewriteError(
                f"PythonFunction[{block_id}]: unknown parameter edit {edit!r}.",
                kind="unsupported",
                block_id=block_id,
            )
    return editor.splices, tuple(expected)


# ---------------------------------------------------------------------------
# rename のスコープ解析 (SPEC-0025 W4-E / ADR-0075 §論点 1・4)
# ---------------------------------------------------------------------------

#: 規則 G (fail-closed allowlist): rename の planner が走査してよい AST ノード型。
#: ここに**無い**ノード型に出会ったら rename 全体を拒否する。新しい Python 版で
#: ノードが増えたら ``test_every_ast_node_type_is_classified`` が CI で赤くなり、
#: 「分類してから対応する」ことを強制する (ADR-0075 V24)。クラスではなく名前文字列で
#: 持つのは、版によって存在しないクラスがあるため。
_RENAME_ALLOWED_NODE_NAMES = frozenset(
    {
        # 文
        "FunctionDef",
        "AsyncFunctionDef",
        "Return",
        "Delete",
        "Assign",
        "AugAssign",
        "AnnAssign",
        "For",
        "AsyncFor",
        "While",
        "If",
        "With",
        "AsyncWith",
        "Raise",
        "Try",
        "TryStar",
        "Assert",
        "Import",
        "ImportFrom",
        "Global",
        "Nonlocal",
        "Expr",
        "Pass",
        "Break",
        "Continue",
        "Match",
        # 式
        "BoolOp",
        "NamedExpr",
        "BinOp",
        "UnaryOp",
        "Lambda",
        "IfExp",
        "Dict",
        "Set",
        "ListComp",
        "SetComp",
        "DictComp",
        "GeneratorExp",
        "Await",
        "Yield",
        "YieldFrom",
        "Compare",
        "Call",
        "FormattedValue",
        "JoinedStr",
        "Constant",
        "Attribute",
        "Subscript",
        "Starred",
        "Name",
        "List",
        "Tuple",
        "Slice",
        # 補助ノード
        "comprehension",
        "arguments",
        "arg",
        "keyword",
        "alias",
        "withitem",
        "ExceptHandler",
        "match_case",
        "MatchValue",
        "MatchSingleton",
        "MatchSequence",
        "MatchMapping",
        "MatchClass",
        "MatchStar",
        "MatchAs",
        "MatchOr",
        # 演算子 / context (identifier を持たない葉)
        "And",
        "Or",
        "Add",
        "Sub",
        "Mult",
        "MatMult",
        "Div",
        "Mod",
        "Pow",
        "LShift",
        "RShift",
        "BitOr",
        "BitXor",
        "BitAnd",
        "FloorDiv",
        "Invert",
        "Not",
        "UAdd",
        "USub",
        "Eq",
        "NotEq",
        "Lt",
        "LtE",
        "Gt",
        "GtE",
        "Is",
        "IsNot",
        "In",
        "NotIn",
        "Load",
        "Store",
        "Del",
    }
)

#: 出会ったら**無条件で** rename を拒否するノード型。``ClassDef`` は U7 (class
#: スコープの名前解決規則は関数と違う)。PEP 695 (3.12+) の type parameter 構文と
#: t-string (3.14+) は規則 G-b / G-c (規則を持たないので保守的に拒否)。
_RENAME_DENIED_NODE_NAMES = frozenset(
    {
        "ClassDef",
        "TypeAlias",
        "TypeVar",
        "ParamSpec",
        "TypeVarTuple",
        "TemplateStr",
        "Interpolation",
    }
)

#: 分類ガードの対象外: 抽象基底 / module 専用 / ``ast.parse`` が生成しない
#: 非推奨エイリアス。関数内の走査に現れることは無い。
_RENAME_IGNORED_NODE_NAMES = frozenset(
    {
        "AST",
        "mod",
        "stmt",
        "expr",
        "expr_context",
        "boolop",
        "operator",
        "unaryop",
        "cmpop",
        "excepthandler",
        "pattern",
        "type_param",
        "type_ignore",
        "Module",
        "Interactive",
        "Expression",
        "FunctionType",
        "TypeIgnore",
        "Num",
        "Str",
        "Bytes",
        "NameConstant",
        "Ellipsis",
        "Index",
        "ExtSlice",
        "AugLoad",
        "AugStore",
        "Param",
        "Suite",
        "slice",
    }
)

#: U6: 名前による動的アクセス。これらが関数内で参照されていたら rename の意味が
#: 静的に追えないため拒否する。
_DYNAMIC_ACCESS_NAMES = frozenset({"locals", "globals", "vars", "eval", "exec"})


def _reject_rename(message: str, node: ast.AST | None, block_id: str | None) -> None:
    raise PythonFunctionRewriteError(
        f"PythonFunction[{block_id}]: cannot rename the parameter from the UI: "
        f"{message}. Edit the code directly.",
        kind="unsupported",
        reason="rewrite_rename_unsupported_construct",
        lineno=getattr(node, "lineno", None),
        block_id=block_id,
    )


def _guard_rename_constructs(func_def: ast.FunctionDef, target: str, block_id: str | None) -> None:
    """規則 G + U1〜U7 + G-a: rename を拒否すべき構文を関数全体から検出する。

    U8 (occurrence のバイト列照合) は splice 側 (:func:`_rename_splices`) で行う。
    """
    for node in ast.walk(func_def):
        type_name = type(node).__name__
        if type_name in _RENAME_DENIED_NODE_NAMES:
            _reject_rename(f"the function contains a `{type_name}` construct", node, block_id)
        if type_name not in _RENAME_ALLOWED_NODE_NAMES:
            # 規則 G: 未分類ノード = 新しい / 未知の構文。fail closed
            _reject_rename(f"unrecognised syntax node `{type_name}`", node, block_id)
        if isinstance(node, ast.Global | ast.Nonlocal):
            if target in node.names:  # U1
                _reject_rename(f"`{target}` appears in a global/nonlocal statement", node, block_id)
        elif isinstance(node, ast.alias):
            if (node.asname or node.name).split(".")[0] == target:  # U2
                _reject_rename(f"an import binds the name `{target}`", node, block_id)
        elif isinstance(node, ast.ExceptHandler):
            if node.name == target:  # U3
                _reject_rename(f"`except ... as {target}` binds the name", node, block_id)
        elif isinstance(node, ast.MatchAs | ast.MatchStar):
            if node.name == target:  # U4
                _reject_rename(f"a match pattern captures `{target}`", node, block_id)
        elif isinstance(node, ast.MatchMapping):
            if node.rest == target:  # U4
                _reject_rename(f"a match pattern captures `{target}`", node, block_id)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node is not func_def and node.name == target:  # G-a
                _reject_rename(f"a nested function is named `{target}`", node, block_id)
        elif isinstance(node, ast.JoinedStr):
            # U5: f-string 内ノードの位置情報は 3.11 で不正確 (PEP 701 は 3.12+)。
            # 版依存挙動を作らないため、対象名を参照する f-string は一律拒否
            if any(isinstance(n, ast.Name) and n.id == target for n in ast.walk(node)):
                _reject_rename(f"an f-string references `{target}`", node, block_id)
        elif isinstance(node, ast.Name):
            if node.id in _DYNAMIC_ACCESS_NAMES:  # U6
                _reject_rename(
                    f"the function uses `{node.id}` (dynamic name access)", node, block_id
                )


class _ScopeAnalyzer:
    """rename 対象を指す ``ast.Name`` を S1〜S10 で列挙する (ADR-0075 §論点 1)。

    規則の根拠 (言語リファレンス / PEP):

    * S3/S4 (shadowing / 閉包): 入れ子スコープが対象名を**束縛しない**ときだけ、
      その中の参照は囲むスコープ (= パラメータ) を指す
    * S5: 入れ子 def / lambda の default 式・デコレータ・注釈は**定義時に囲む
      スコープで評価**される
    * S6: comprehension の**最外の iter だけ**は囲むスコープで評価される
    * S8 (PEP 572): comprehension 内の walrus は**囲むスコープに束縛**する

    誤りは E4b (`symtable` 同型性検査) が捕まえるため、壊れたコードが返ることは
    ない (「編集できない」形で表面化する。ADR-0075 §Consequences)。
    """

    def __init__(self, target: str) -> None:
        self._target = target
        self.occurrences: list[ast.Name] = []

    # --- 束縛判定 -----------------------------------------------------------

    def _function_binds(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> bool:
        """入れ子の関数スコープが対象名を束縛するか (S3 の判定)。"""
        a = node.args
        all_args = [*a.posonlyargs, *a.args, *a.kwonlyargs]
        if a.vararg is not None:
            all_args.append(a.vararg)
        if a.kwarg is not None:
            all_args.append(a.kwarg)
        if any(arg.arg == self._target for arg in all_args):
            return True
        body: list[ast.AST] = list(node.body) if isinstance(node.body, list) else [node.body]
        return any(self._binds_in_block(n) for n in body)

    def _binds_in_block(self, node: ast.AST) -> bool:
        """このスコープ内で対象名が束縛されるか。入れ子スコープの内側には入らない
        (ただし comprehension 内の walrus は PEP 572 によりこのスコープに束縛される)。

        walrus をさらに内側の lambda が持つ形も「束縛あり」と過剰判定しうるが、
        その場合は該当参照が rename されず E4b が拒否する = 安全側 (壊れない)。
        """
        if isinstance(node, ast.Name):
            return isinstance(node.ctx, ast.Store | ast.Del) and node.id == self._target
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            return False
        if isinstance(node, ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp):
            return any(
                isinstance(n, ast.NamedExpr)
                and isinstance(n.target, ast.Name)
                and n.target.id == self._target
                for n in ast.walk(node)
            )
        return any(self._binds_in_block(c) for c in ast.iter_child_nodes(node))

    # --- occurrence 収集 -----------------------------------------------------

    def visit_in_scope(self, node: ast.AST, *, active: bool) -> None:
        """``active`` = この位置の ``Name(target)`` が対象パラメータを指すか。"""
        if isinstance(node, ast.Name):
            if active and node.id == self._target:
                self.occurrences.append(node)
            return
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            # S5: デコレータ / 注釈 / default は囲むスコープで評価される
            for deco in node.decorator_list:
                self.visit_in_scope(deco, active=active)
            a = node.args
            annotated = [*a.posonlyargs, *a.args, *a.kwonlyargs]
            if a.vararg is not None:
                annotated.append(a.vararg)
            if a.kwarg is not None:
                annotated.append(a.kwarg)
            for arg in annotated:
                if arg.annotation is not None:
                    self.visit_in_scope(arg.annotation, active=active)
            if node.returns is not None:
                self.visit_in_scope(node.returns, active=active)
            for default in [*a.defaults, *[d for d in a.kw_defaults if d is not None]]:
                self.visit_in_scope(default, active=active)
            inner_active = active and not self._function_binds(node)  # S3 / S4
            for stmt in node.body:
                self.visit_in_scope(stmt, active=inner_active)
            return
        if isinstance(node, ast.Lambda):
            a = node.args
            for default in [*a.defaults, *[d for d in a.kw_defaults if d is not None]]:
                self.visit_in_scope(default, active=active)  # S5
            inner_active = active and not self._function_binds(node)
            self.visit_in_scope(node.body, active=inner_active)
            return
        if isinstance(node, ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp):
            self._visit_comprehension(node, active=active)
            return
        for child in ast.iter_child_nodes(node):
            self.visit_in_scope(child, active=active)

    def _visit_comprehension(
        self,
        node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
        *,
        active: bool,
    ) -> None:
        gens = node.generators
        # S6: 最外の iter だけは囲むスコープで評価される
        self.visit_in_scope(gens[0].iter, active=active)
        # comp スコープが対象名を束縛するか = いずれかの for ターゲットに現れるか。
        # (walrus で comp の iteration 変数を再束縛する形は SyntaxError なので考えない)
        comp_binds = any(
            isinstance(n, ast.Name) and n.id == self._target
            for g in gens
            for n in ast.walk(g.target)
        )
        inner_active = active and not comp_binds  # S7
        for i, gen in enumerate(gens):
            if i > 0:
                self.visit_in_scope(gen.iter, active=inner_active)
            self.visit_in_scope(gen.target, active=inner_active)
            for cond in gen.ifs:
                self.visit_in_scope(cond, active=inner_active)
        if isinstance(node, ast.DictComp):
            self.visit_in_scope(node.key, active=inner_active)
            self.visit_in_scope(node.value, active=inner_active)
        else:
            self.visit_in_scope(node.elt, active=inner_active)


def _plan_rename_occurrences(
    func_def: ast.FunctionDef, old: str, block_id: str | None
) -> list[ast.Name | ast.arg]:
    """対象パラメータを指す occurrence (シグネチャの ``arg`` 1 個 + 本体の ``Name``)
    を返す。規則 G / U1〜U7 に触れる構文があれば例外 (SPEC-0025 §機能要件 3)。
    """
    _guard_rename_constructs(func_def, old, block_id)
    target_arg = next((a for a in func_def.args.kwonlyargs if a.arg == old), None)
    if target_arg is None:
        raise PythonFunctionRewriteError(
            f"PythonFunction[{block_id}]: no keyword-only parameter named {old!r}.",
            kind="unsupported",
            reason="rewrite_param_not_found",
            block_id=block_id,
        )
    analyzer = _ScopeAnalyzer(old)
    for stmt in func_def.body:
        analyzer.visit_in_scope(stmt, active=True)
    return [target_arg, *analyzer.occurrences]


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
    params: Sequence[ParamEdit] | None = None,
    block_id: str | None = None,
) -> str:
    """``@block`` 形ソースのポート / パラメータ構造を書き換えた新しいソースを返す
    (SPEC-0024 / SPEC-0025)。

    patch セマンティクス: ``None`` の項目は書き換えない。ポート数を変更するとき、
    既存のポート名列は同じ書き換えで長さを同期する (§2.6)。要求がすべて現状と
    一致する場合は **入力をバイト等価のまま** 返す。すべての編集は 1 つの splice
    バッチ + 1 回の自己検証で処理される (中間状態を作らない)。

    Args:
        code: 現在のソース (受理契約 ADR-0073 §2-E の内側であること)。
        inputs: 目標入力ポート数 (1..32。``u`` 引数の無い関数では指定不可)。
        outputs: 目標出力ポート数 (1..32)。
        input_names: 入力ポート名列 (長さは **編集後の** 入力数と完全一致)。
        output_names: 出力ポート名列。
        params: パラメータ編集の命令列 (:class:`AddParam` / :class:`RemoveParam` /
            :class:`RenameParam`)。命令列なのはポート編集 (宣言的) と違い
            rename と remove+add を区別する必要があるため (ADR-0075 §論点 5)。
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

    source = _SourceBytes(code)
    tree = ast.parse(code)
    func_def = _find_decorated_function(tree, block_id)
    deco = next(d for d in func_def.decorator_list if _is_block_decorator(d))
    editor = _DecoratorEditor(source, deco)

    param_splices, expected_params = _plan_param_edits(
        source, tree, func_def, old_spec, params, block_id
    )
    splices: list[_Splice] = list(param_splices)

    expected = replace(
        old_spec,
        n_inputs=final_inputs,
        n_outputs=final_outputs,
        input_names=final_input_names,
        output_names=final_output_names,
        params_spec=expected_params,
    )

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
    if len(new_code) > MAX_REWRITTEN_CODE_CHARS:
        raise PythonFunctionRewriteError(
            f"PythonFunction[{block_id}]: the rewritten source would exceed "
            f"{MAX_REWRITTEN_CODE_CHARS} characters; reduce the annotation size or "
            f"declare the structure with @block(inputs=N, outputs=M) instead.",
            kind="unsupported",
            block_id=block_id,
        )

    # --- 自己検証 (W3): 唯一の導出者に読み直させる ---
    try:
        new_spec = analyze_source(new_code, block_id=block_id)
    except PythonFunctionSourceError as e:
        _logger.error(
            "PythonFunction rewrite self-verification failed (re-analysis) for block %r: %s\n"
            "--- original code (truncated) ---\n%s\n--- rewritten (DISCARDED, truncated) ---\n%s",
            block_id,
            e,
            _code_for_log(code),
            _code_for_log(new_code),
        )
        raise PythonFunctionRewriteError(
            f"PythonFunction[{block_id}]: rewrite produced source that no longer parses "
            f"({e}); the original code is unchanged. This is a bug in the rewrite rules.",
            kind="spec",  # wire 語彙は 3 値のまま (ADR-0074 §論点 3)。内部細分は reason
            reason="rewrite_verify_syntax",
            block_id=block_id,
        ) from e
    if replace(new_spec, lineno=old_spec.lineno) != replace(expected, lineno=old_spec.lineno):
        _logger.error(
            "PythonFunction rewrite self-verification failed (structure mismatch) for "
            "block %r: expected %r, got %r\n--- original code (truncated) ---\n%s",
            block_id,
            expected,
            new_spec,
            _code_for_log(code),
        )
        raise PythonFunctionRewriteError(
            f"PythonFunction[{block_id}]: rewritten source does not match the requested "
            f"structure; the original code is unchanged. This is a bug in the rewrite rules.",
            kind="spec",
            reason="rewrite_verify_mismatch",
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
    # W5 (patch セマンティクス): names を明示要求していない編集では、既存の名前列を
    # **長さ同期するだけ** に留める。code-reviewer SHOULD: 明示的に書かれた
    # 全空 tuple (`input_names=("", "")`) を、構造だけの編集で勝手に削除しない
    # (全空 → キーワード削除の C-3 collapse は、名前を明示編集したときだけ適用)。
    if not current:
        return ()
    if len(current) > final_count:
        return current[:final_count]
    return current + ("",) * (final_count - len(current))


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
