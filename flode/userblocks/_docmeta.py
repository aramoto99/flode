"""ユーザーブロックのメタデータ解決 (docstring 解析と公開 class 属性、ADR-0081 §論点 7)。

純粋関数のみ (import やファイル走査をしない)。違反は ``BlockSpecError`` で知らせ、呼び出し側が
そのブロックだけの読み込みエラーにする。

解決順 (§7-A): 公開属性 (``block_*``) → 既存 private 属性 (``_block_category`` /
``_block_display_name`` / ``_param_enums``) → 既定。``block_category`` / ``block_choices`` /
``block_param_descriptions`` は継承する (getattr)。``block_display_name`` /
``block_description`` / ``block_hidden`` はそのクラス自身の ``__dict__`` だけを見る。
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..core.block_metadata import (
    validate_category,
    validate_choices,
    validate_param_descriptions,
    validate_text,
)
from ..exceptions import BlockSpecError

#: Google Style の引数節の見出し (``Args:`` と同義の ``Arguments:``)。
_ARGS_HEADERS: frozenset[str] = frozenset({"Args", "Arguments"})
_SECTION_HEADER_RE = re.compile(r"^(\w[\w ]*):\s*$")
#: ``name (type): text`` / ``name: text`` (``*args`` 等の記号付きは引数にならないので除く)。
#: 空白の繰り返しを隣り合わせない形にして、長い行でもバックトラックが線形に収まるようにする。
_ARG_ENTRY_RE = re.compile(r"^(\w+)\s*(?:\([^)]*\)\s*)?:\s*(.*)$")
#: これより長い行は見出し・引数エントリとして解析しない (説明の継続行としてだけ扱う)。
_MAX_DOC_LINE_CHARS = 1000
#: シグネチャから引数として扱わない名前 (``Block.__init__`` 共通の識別子)。
_NON_PARAM_NAMES: frozenset[str] = frozenset({"self", "id", "name"})
_ANY_TYPE_LABEL = "any"
_FALLBACK_LOCALE = "en"


@dataclass(frozen=True)
class RawParam:
    """クラスから読んだ引数 1 つ (JSON 往復前)。"""

    name: str
    type_label: str
    has_default: bool
    default: Any


@dataclass(frozen=True)
class DocInfo:
    """docstring の解析結果。"""

    summary: str
    args: Mapping[str, str]


@dataclass(frozen=True)
class ResolvedMetadata:
    """公開属性 / private 属性 / docstring から決めたメタデータ。"""

    display_name: str
    display_name_i18n: Mapping[str, str]
    description: str
    description_i18n: Mapping[str, str]
    docstring: str
    category: str | None
    choices: Mapping[str, tuple[str, ...]]
    param_descriptions: Mapping[str, str]
    #: 言語別に宣言された引数の説明 (引数名 → {言語: 説明})。``param_descriptions`` には
    #: その ``en`` (無ければ最初の値) が入る
    param_descriptions_i18n: Mapping[str, Mapping[str, str]]
    input_names: tuple[str, ...]
    output_names: tuple[str, ...]


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def parse_docstring(doc: str | None) -> DocInfo:
    """Google Style の docstring から 1 行目の説明と ``Args:`` 節の引数説明を取り出す。

    1 行目の規則は block registry の ``docstring_summary`` と同じ (最初の段落の最初の行)。
    ``Args:`` 節は ``name (type): text`` / ``name: text`` を読み、エントリより深いインデントの
    続く行を空白 1 つで連結する。節の見出しと同じかそれより浅いインデントの行で終わる。

    Args:
        doc: docstring (``None`` / 空なら空の結果)。

    Returns:
        ``DocInfo`` (説明と ``{引数名: 説明}``)。
    """
    if not doc:
        return DocInfo(summary="", args={})
    text = inspect.cleandoc(doc)
    summary = text.split("\n\n", 1)[0].split("\n")[0].strip()
    lines = text.split("\n")
    parts: dict[str, list[str]] = {}
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        header = (
            _SECTION_HEADER_RE.match(stripped) if len(stripped) <= _MAX_DOC_LINE_CHARS else None
        )
        if header is None or header.group(1) not in _ARGS_HEADERS:
            i += 1
            continue
        header_indent = _indent(lines[i])
        entry_indent: int | None = None
        current: str | None = None
        i += 1
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if not stripped:
                i += 1
                continue
            indent = _indent(line)
            if indent <= header_indent:
                break
            if entry_indent is None:
                entry_indent = indent
            entry = (
                _ARG_ENTRY_RE.match(stripped)
                if indent == entry_indent and len(stripped) <= _MAX_DOC_LINE_CHARS
                else None
            )
            if entry is not None:
                current = entry.group(1)
                parts[current] = [entry.group(2).strip()]
            elif current is not None and indent > entry_indent:
                parts[current].append(stripped)
            i += 1
        break
    args = {name: " ".join(t for t in texts if t) for name, texts in parts.items()}
    return DocInfo(summary=summary, args=args)


def own_docstring(cls: type) -> str:
    """クラス自身の docstring (継承しない、``inspect.cleandoc`` 済み)。"""
    doc = vars(cls).get("__doc__")
    return inspect.cleandoc(doc) if isinstance(doc, str) else ""


def _type_label(annotation: Any) -> str:
    if annotation is None or annotation is inspect.Parameter.empty:
        return _ANY_TYPE_LABEL
    if isinstance(annotation, type):
        return annotation.__name__
    return str(annotation).replace("typing.", "")


def _generated_params_spec(cls: type) -> Sequence[tuple[str, Any, Any, bool]] | None:
    """``@block`` 生成クラスの ``__init__`` をそのまま使うクラスなら、その引数仕様を返す。"""
    for owner in cls.__mro__:
        if "_flode_params_spec" in vars(owner):
            init = vars(owner).get("__init__")
            if init is not None and getattr(cls, "__init__", None) is init:
                spec: Sequence[tuple[str, Any, Any, bool]] = vars(owner)["_flode_params_spec"]
                return spec
            return None
    return None


def read_params(cls: type) -> list[RawParam]:
    """クラスの引数一覧を読む (``@block`` 生成クラスは宣言、それ以外は ``__init__`` のシグネチャ)。

    Args:
        cls: ``Block`` サブクラス。

    Returns:
        引数の一覧 (宣言順)。``self`` / ``id`` / ``name`` / ``*args`` / ``**kwargs`` は除く。

    Raises:
        BlockSpecError: シグネチャが取得できない。
    """
    generated = _generated_params_spec(cls)
    if generated is not None:
        return [
            RawParam(
                name=pname,
                type_label=_type_label(ptype),
                has_default=not required,
                default=default,
            )
            for pname, default, ptype, required in generated
        ]
    try:
        signature = inspect.signature(cls)
    except (TypeError, ValueError) as e:
        raise BlockSpecError(f"cannot read the signature of {cls.__name__}: {e}") from e
    out: list[RawParam] = []
    for pname, param in signature.parameters.items():
        if pname in _NON_PARAM_NAMES or param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        has_default = param.default is not inspect.Parameter.empty
        out.append(
            RawParam(
                name=pname,
                type_label=_type_label(param.annotation),
                has_default=has_default,
                default=param.default if has_default else None,
            )
        )
    return out


def _localized(value: Any, *, field: str, owner: str) -> tuple[str, dict[str, str]]:
    """``str`` または ``{locale: str}`` を検証し、(旧フィールド用の文字列, i18n) に分ける (S3)。"""
    validated = validate_text(value, field=field, owner=owner)
    if isinstance(validated, str):
        return validated, {}
    return validated.get(_FALLBACK_LOCALE, next(iter(validated.values()))), validated


def _resolve_port_names(
    cls: type, attr: str, structure_field: str, n_ports: int
) -> tuple[str, ...]:
    raw = getattr(cls, attr, None)
    if raw is None:
        structure = getattr(cls, "_flode_structure", None)
        raw = getattr(structure, structure_field, ()) if structure is not None else ()
    if isinstance(raw, str) or not isinstance(raw, Sequence):
        raise BlockSpecError(f"{attr} must be a sequence of strings, got {raw!r}")
    names = tuple(raw)
    if not all(isinstance(n, str) for n in names):
        raise BlockSpecError(f"{attr} must be a sequence of strings, got {raw!r}")
    if names and len(names) != n_ports:
        raise BlockSpecError(f"{attr} has {len(names)} names but the block has {n_ports} ports")
    return names


def resolve_metadata(
    cls: type, params: Mapping[str, Any], *, n_inputs: int, n_outputs: int
) -> ResolvedMetadata:
    """クラスの公開属性・private 属性・docstring からメタデータを決める。

    宣言の検証は ``@block`` と同じ関数 (``flode.core.block_metadata``) を使う。

    Args:
        cls: ``Block`` サブクラス。
        params: ``{引数名: JSON 往復済みの既定値}`` (選択肢の既定値検査に使う)。
        n_inputs: 既定値でインスタンス化したときの入力ポート数 (ポート名の長さ検査)。
        n_outputs: 同出力ポート数。

    Returns:
        解決済みのメタデータ。

    Raises:
        BlockSpecError: 宣言が不正 (カテゴリが空、選択肢のキーが引数でない、既定値が
            選択肢に無い、表示名の型違い、ポート名の数が合わない等)。
    """
    owner = cls.__name__
    category = getattr(cls, "block_category", None)
    if category is None:
        category = getattr(cls, "_block_category", None)
    if category is not None:
        category = validate_category(category, owner=owner)

    docstring = own_docstring(cls)
    doc = parse_docstring(docstring)
    doc_args = doc.args
    if not doc_args and "__init__" in vars(cls):
        doc_args = parse_docstring(getattr(vars(cls)["__init__"], "__doc__", None)).args

    own = vars(cls)
    display_raw = own.get("block_display_name")
    if display_raw is None:
        display_raw = getattr(cls, "_block_display_name", None) or owner
    display_name, display_i18n = _localized(display_raw, field="display_name", owner=owner)

    description_raw = own.get("block_description")
    description_i18n: dict[str, str] = {}
    if description_raw is None:
        description = doc.summary
    else:
        description, description_i18n = _localized(
            description_raw, field="description", owner=owner
        )

    choices_raw = getattr(cls, "block_choices", None)
    if choices_raw is None:
        choices_raw = getattr(cls, "_param_enums", None)
    choices = validate_choices(choices_raw, params, owner=owner) if choices_raw is not None else {}

    # docstring の Args: は t / u 等の引数以外も書くので、引数名に一致するものだけ採る
    descriptions = {k: v for k, v in doc_args.items() if k in params}
    descriptions_i18n: dict[str, dict[str, str]] = {}
    explicit = getattr(cls, "block_param_descriptions", None)
    if explicit is not None:
        for pname, text in validate_param_descriptions(explicit, params, owner=owner).items():
            if isinstance(text, str):
                descriptions[pname] = text
            else:
                descriptions[pname] = text.get(_FALLBACK_LOCALE, next(iter(text.values())))
                descriptions_i18n[pname] = dict(text)

    return ResolvedMetadata(
        display_name=display_name,
        display_name_i18n=display_i18n,
        description=description,
        description_i18n=description_i18n,
        docstring=docstring,
        category=category,
        choices=choices,
        param_descriptions=descriptions,
        param_descriptions_i18n=descriptions_i18n,
        input_names=_resolve_port_names(cls, "block_input_names", "input_names", n_inputs),
        output_names=_resolve_port_names(cls, "block_output_names", "output_names", n_outputs),
    )
