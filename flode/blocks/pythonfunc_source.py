"""``PythonFunction`` 用の静的ソース解析器 (SPEC-0023 / ADR-0073 §論点 1, 2-E)。

ユーザーが書いた ``@block`` 形の Python ソースから、**``exec`` せずに**
ブロック構造 (ポート数 / 状態数 / 直達 / sample_time / パラメータ宣言) を導出する。

設計の要点 (ADR-0073 §論点 1):

* ``@block`` の推論規則 (:mod:`flode.core.decorator`) を **再実装しない**。
  AST から「シグネチャだけ同型の stub 関数」を組み立て、本物の :func:`flode.block`
  に渡す。stub の本体は一度も呼ばれない。推論エンジンは 1 本のまま =
  ``@block`` を直接使った場合と結果が構造的に一致する
* 型注釈の評価は :func:`_eval_annotation` の **極小語彙** で行う。``Call`` ノードは
  一切許可しないので、評価によってコードが実行されることは原理的に無い
* 語彙外の注釈・非リテラルのデコレータ引数・class 形は
  :class:`~flode.exceptions.PythonFunctionSourceError` で拒否し、逃げ道
  (``@block(inputs=N, outputs=M, states=K)`` で明示) を案内する

本モジュールは ``__init__`` (ロード時) と introspect REST の両方から呼ばれる
**唯一の構造導出者 (SSOT)** である。
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass
from types import FunctionType
from typing import Any

import numpy as np
import numpy.typing as npt

from ..core.block import Block
from ..core.decorator import block
from ..exceptions import BlockSpecError, PythonFunctionSourceError

#: ``exec`` / ``compile`` に渡す擬似ファイル名の接頭辞 (SPEC-0023 §6 の表記)。
SOURCE_FILENAME_PREFIX = "<pythonfunction:"

#: ``exec`` 名前空間の ``__name__``。``__main__`` を避け (``if __name__ == "__main__"``
#: の誤発火と ``block_type_path`` の ``__main__`` 拒否を同時に回避)、かつ import
#: 不能な文字列にして万一 type_path として使われても fail closed にする。
GENERATED_MODULE_NAME = "flode.blocks.pythonfunc.<generated>"

_ESCAPE_HATCH_HINT = (
    "Hint: declare the structure explicitly with "
    "@block(inputs=N, outputs=M, states=K) so that type-annotation inference is not needed."
)

# 型注釈の解決語彙 (ADR-0073 §論点 2-E)。ここに無い名前は評価せず素直に拒否する。
_ANNOTATION_NAMES: dict[str, Any] = {
    "float": float,
    "int": int,
    "bool": bool,
    "str": str,
    "tuple": tuple,
    "Any": Any,
    "None": None,
}
_ANNOTATION_ATTRS: dict[tuple[str, str], Any] = {
    ("np", "float64"): np.float64,
    ("np", "ndarray"): np.ndarray,
    ("np", "dtype"): np.dtype,
    ("numpy", "float64"): np.float64,
    ("numpy", "ndarray"): np.ndarray,
    ("numpy", "dtype"): np.dtype,
    ("npt", "NDArray"): npt.NDArray,
    ("typing", "Any"): Any,
}
_DECORATOR_NAME = "block"


@dataclass(frozen=True)
class SourceSpec:
    """静的解析で確定した ``PythonFunction`` の構造 (= ``@block`` の推論結果と同形)。

    Attributes:
        func_name: デコレートされた関数名。
        n_inputs: 入力ポート数。
        n_outputs: 出力ポート数。
        n_states: 状態次元数。
        direct_feedthrough: 直達フラグ。
        sample_time: ``None`` / ``0.0`` (連続)、``> 0`` (離散)、``-1.0`` (継承)。
        params_spec: ``(name, default, type, required)`` のタプル列
            (= 生成 class の ``_flode_params_spec`` と同形)。
        lineno: デコレート対象関数の ``def`` 行 (1 始まり)。
        input_names: 入力ポート名 (SPEC-0024)。空 tuple = 全ポート無名。
        output_names: 出力ポート名。
        has_u_arg: 関数が ``u`` 引数を持つか (= GUI の入力数編集可否判定)。
    """

    func_name: str
    n_inputs: int
    n_outputs: int
    n_states: int
    direct_feedthrough: bool
    sample_time: float | str | None
    params_spec: tuple[tuple[str, Any, Any, bool], ...]
    lineno: int
    input_names: tuple[str, ...] = ()
    output_names: tuple[str, ...] = ()
    has_u_arg: bool = True


class _UnresolvedAnnotation(Exception):
    """語彙外の型注釈 (内部用。呼び出し側で ``PythonFunctionSourceError`` に変換する)。"""


def source_filename(block_id: str | None) -> str:
    """``compile`` / ``exec`` / traceback で使う擬似ファイル名を返す。"""
    return f"{SOURCE_FILENAME_PREFIX}{block_id if block_id is not None else 'unnamed'}>"


def analyze_source(code: str, *, block_id: str | None = None) -> SourceSpec:
    """ソース文字列から ``exec`` せずに構造を導出する (SSOT)。

    手順:

    1. ``compile(code, ..., "exec")`` で構文検証 (実行はしない)
    2. ``ast.parse`` → top-level の ``@block`` 付き ``def`` を **1 個だけ** 特定
    3. デコレータのキーワード引数を ``ast.literal_eval`` で解決
    4. 引数の型注釈を :func:`_eval_annotation`、default を ``ast.literal_eval`` で解決
    5. stub 関数を組み立て、本物の :func:`flode.block` に渡す
    6. 生成 class の ``_flode_structure`` / ``_flode_params_spec`` から
       :class:`SourceSpec` を組む

    Args:
        code: ユーザーソース (``@block`` 形の関数定義を 1 つ含む)。
        block_id: エラーメッセージ / 擬似ファイル名に使うブロック ID。

    Returns:
        :class:`SourceSpec`。

    Raises:
        PythonFunctionSourceError: 構文エラー (``kind="syntax"``)、または
            静的解析で受理できないソース (``kind="spec"``)。``@block`` 自身の
            推論エラー (``BlockSpecError``) もこの型に包み直す。
    """
    if not isinstance(code, str):
        raise PythonFunctionSourceError(
            f"PythonFunction: code must be a str, got {type(code).__name__}",
            block_id=block_id,
        )
    filename = source_filename(block_id)
    try:
        compile(code, filename, "exec")
        tree = ast.parse(code, filename=filename)
    except SyntaxError as e:
        raise PythonFunctionSourceError(
            f"PythonFunction: syntax error: {e.msg}",
            kind="syntax",
            lineno=e.lineno,
            col=e.offset,
            block_id=block_id,
        ) from e

    func_def = _find_decorated_function(tree, block_id)
    decorator_kwargs = _decorator_kwargs(func_def, block_id)

    try:
        stub = _build_stub(func_def)
    except _UnresolvedAnnotation as e:
        raise PythonFunctionSourceError(
            f"PythonFunction: cannot resolve type annotation {e!s} statically "
            f"(allowed: float, int, bool, str, tuple[...], np.float64, np.ndarray, "
            f"npt.NDArray[...], Any, None). {_ESCAPE_HATCH_HINT}",
            lineno=func_def.lineno,
            block_id=block_id,
        ) from e
    except ValueError as e:
        # ast.literal_eval が非リテラル default を拒否したケース
        raise PythonFunctionSourceError(
            f"PythonFunction: parameter defaults must be literals "
            f"(int / float / bool / str / None / tuple / list): {e}",
            lineno=func_def.lineno,
            block_id=block_id,
        ) from e

    try:
        cls: type[Block] = block(stub, **decorator_kwargs)
    except BlockSpecError as e:
        # ``@block`` 自身の推論 / 検証エラー。メッセージは decorator.py のものを
        # そのまま使う (= Python API で ``@block`` を直接使った時と同一文面)。
        raise PythonFunctionSourceError(
            f"PythonFunction: {e}", lineno=func_def.lineno, block_id=block_id
        ) from e

    structure = cls._flode_structure  # type: ignore[attr-defined]
    params_spec: tuple[tuple[str, Any, Any, bool], ...] = cls._flode_params_spec  # type: ignore[attr-defined]
    return SourceSpec(
        func_name=func_def.name,
        n_inputs=structure.n_inputs,
        n_outputs=structure.n_outputs,
        n_states=structure.n_states,
        direct_feedthrough=structure.direct_feedthrough,
        sample_time=structure.sample_time,
        params_spec=tuple(params_spec),
        lineno=func_def.lineno,
        input_names=structure.input_names,
        output_names=structure.output_names,
        has_u_arg=structure.has_u_arg,
    )


# ---------------------------------------------------------------------------
# AST walking
# ---------------------------------------------------------------------------


def _is_block_decorator(node: ast.expr) -> bool:
    """``@block`` / ``@block(...)`` / ``@flode.block`` / ``@flode.block(...)`` を判定する。"""
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Name):
        return target.id == _DECORATOR_NAME
    if isinstance(target, ast.Attribute):
        return target.attr == _DECORATOR_NAME
    return False


def _find_decorated_function(tree: ast.Module, block_id: str | None) -> ast.FunctionDef:
    """top-level の ``@block`` 付き ``def`` を 1 個だけ返す。0 個 / 2 個以上 / class 形は拒否。"""
    funcs: list[ast.FunctionDef] = []
    classes: list[ast.ClassDef] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if any(_is_block_decorator(d) for d in node.decorator_list):
                if isinstance(node, ast.AsyncFunctionDef):
                    raise PythonFunctionSourceError(
                        f"PythonFunction: @block target {node.name!r} must not be async",
                        lineno=node.lineno,
                        block_id=block_id,
                    )
                funcs.append(node)
        elif isinstance(node, ast.ClassDef) and any(
            _is_block_decorator(d) for d in node.decorator_list
        ):
            classes.append(node)
    if classes:
        raise PythonFunctionSourceError(
            f"PythonFunction: class-form @block ({classes[0].name!r}) is not supported in "
            f"PythonFunction; write a function-form @block instead "
            f"(SPEC-0023 / ADR-0073 §2-E).",
            lineno=classes[0].lineno,
            block_id=block_id,
        )
    if not funcs:
        raise PythonFunctionSourceError(
            "PythonFunction: no top-level @block-decorated function found. "
            "Write exactly one `@block` (or `@block(...)`) function at module level.",
            block_id=block_id,
        )
    if len(funcs) > 1:
        names = ", ".join(repr(f.name) for f in funcs)
        raise PythonFunctionSourceError(
            f"PythonFunction: expected exactly one @block function, found {len(funcs)} "
            f"({names}). One source defines one block.",
            lineno=funcs[1].lineno,
            block_id=block_id,
        )
    return funcs[0]


def _decorator_kwargs(func_def: ast.FunctionDef, block_id: str | None) -> dict[str, Any]:
    """``@block(...)`` のキーワード引数をリテラルとして解決する。"""
    for deco in func_def.decorator_list:
        if not _is_block_decorator(deco):
            continue
        if not isinstance(deco, ast.Call):
            return {}
        if deco.args:
            raise PythonFunctionSourceError(
                "PythonFunction: @block(...) takes keyword arguments only "
                "(e.g. @block(states=1, sample_time=0.1)).",
                lineno=deco.lineno,
                block_id=block_id,
            )
        kwargs: dict[str, Any] = {}
        for kw in deco.keywords:
            if kw.arg is None:
                raise PythonFunctionSourceError(
                    "PythonFunction: @block(**kwargs) cannot be analysed statically; "
                    "write the arguments literally.",
                    lineno=deco.lineno,
                    block_id=block_id,
                )
            try:
                kwargs[kw.arg] = ast.literal_eval(kw.value)
            except ValueError as e:
                raise PythonFunctionSourceError(
                    f"PythonFunction: @block argument {kw.arg!r} must be a literal "
                    f"(int / float / bool / str / None), got `{ast.unparse(kw.value)}`.",
                    lineno=deco.lineno,
                    block_id=block_id,
                ) from e
        return kwargs
    raise AssertionError("BUG: _decorator_kwargs called on a function without @block")


# ---------------------------------------------------------------------------
# Stub construction
# ---------------------------------------------------------------------------


def _eval_annotation(node: ast.expr) -> Any:
    """型注釈 AST を極小語彙で評価する。

    許可ノード: ``Name`` / ``Attribute`` (語彙表の組のみ) / ``Subscript`` / ``Tuple`` /
    ``Constant`` (``None`` / ``Ellipsis``)。**``Call`` は許可しない** = 評価による
    コード実行は起きない。語彙外は :class:`_UnresolvedAnnotation`。
    """
    if isinstance(node, ast.Constant):
        if node.value is None or node.value is Ellipsis:
            return node.value
        raise _UnresolvedAnnotation(repr(node.value))
    if isinstance(node, ast.Name):
        if node.id in _ANNOTATION_NAMES:
            return _ANNOTATION_NAMES[node.id]
        raise _UnresolvedAnnotation(node.id)
    if isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Name):
            key = (node.value.id, node.attr)
            if key in _ANNOTATION_ATTRS:
                return _ANNOTATION_ATTRS[key]
        raise _UnresolvedAnnotation(ast.unparse(node))
    if isinstance(node, ast.Subscript):
        base = _eval_annotation(node.value)
        index = _eval_annotation(node.slice)
        try:
            return base[index]
        except TypeError as e:
            raise _UnresolvedAnnotation(ast.unparse(node)) from e
    if isinstance(node, ast.Tuple):
        return tuple(_eval_annotation(elt) for elt in node.elts)
    raise _UnresolvedAnnotation(ast.unparse(node))


def _annotation_or_empty(node: ast.expr | None) -> Any:
    return inspect.Parameter.empty if node is None else _eval_annotation(node)


def _build_stub(func_def: ast.FunctionDef) -> FunctionType:
    """``func_def`` とシグネチャだけ同型の stub 関数を組み立てる (本体は呼ばれない)。"""
    args = func_def.args
    params: list[inspect.Parameter] = []
    annotations: dict[str, Any] = {}

    def _add(arg: ast.arg, kind: inspect._ParameterKind, default_node: ast.expr | None) -> None:
        annotation = _annotation_or_empty(arg.annotation)
        default: Any = inspect.Parameter.empty
        if default_node is not None:
            default = ast.literal_eval(default_node)
        params.append(inspect.Parameter(arg.arg, kind, default=default, annotation=annotation))
        if annotation is not inspect.Parameter.empty:
            annotations[arg.arg] = annotation

    positional = list(args.posonlyargs) + list(args.args)
    n_defaults = len(args.defaults)
    for i, arg in enumerate(positional):
        kind = (
            inspect.Parameter.POSITIONAL_ONLY
            if i < len(args.posonlyargs)
            else inspect.Parameter.POSITIONAL_OR_KEYWORD
        )
        default_idx = i - (len(positional) - n_defaults)
        default_node = args.defaults[default_idx] if default_idx >= 0 else None
        _add(arg, kind, default_node)
    if args.vararg is not None:
        _add(args.vararg, inspect.Parameter.VAR_POSITIONAL, None)
    for arg, default_node in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        _add(arg, inspect.Parameter.KEYWORD_ONLY, default_node)
    if args.kwarg is not None:
        _add(args.kwarg, inspect.Parameter.VAR_KEYWORD, None)

    return_annotation = _annotation_or_empty(func_def.returns)
    if return_annotation is not inspect.Parameter.empty:
        annotations["return"] = return_annotation

    def _stub(*_args: Any, **_kwargs: Any) -> Any:  # pragma: no cover - never called
        raise NotImplementedError("PythonFunction stub must never be called")

    stub = FunctionType(
        _stub.__code__,
        {"__name__": GENERATED_MODULE_NAME},
        name=func_def.name,
    )
    stub.__qualname__ = func_def.name
    stub.__doc__ = ast.get_docstring(func_def)
    stub.__annotations__ = annotations
    stub.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        params, return_annotation=return_annotation
    )
    return stub
