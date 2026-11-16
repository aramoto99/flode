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
    PARAM_SEARCH_ATTRIBUTE,
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
#: ポート数・ポート名が引数で変わることの宣言 (class 属性、``True`` のときだけ有効)。
DYNAMIC_PORTS_ATTRIBUTE = "block_dynamic_ports"
#: 文字列の列を表す型ラベル。フロントの ``STRING_LIST_TYPE_RE`` (``src/lib/paramEdit.ts``) と
#: 同じ規則にする (その引数を文字列リストとして編集するかどうかはフロントがこの規則で決めるため)。
_STRING_LIST_TYPE_RE = re.compile(
    r"(?:(?:typing|collections\.abc)\.)?(?:list|List|Sequence|tuple|Tuple)"
    r"\[\s*str\s*(?:,\s*\.\.\.\s*)?\]"
)


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


def _validated_names(raw: Any, label: str) -> tuple[str, ...]:
    """ポート名の列を検証して tuple にする (class 属性・インスタンス属性で同じ規則)。"""
    if isinstance(raw, str) or not isinstance(raw, Sequence):
        raise BlockSpecError(f"{label} must be a sequence of strings, got {raw!r}")
    names = tuple(raw)
    if not all(isinstance(n, str) for n in names):
        raise BlockSpecError(f"{label} must be a sequence of strings, got {raw!r}")
    return names


def _class_port_names(cls: type, attr: str, structure_field: str) -> tuple[str, ...]:
    """class 属性 (無ければ ``@block`` の構造宣言) のポート名 (長さは検査しない)。"""
    raw = getattr(cls, attr, None)
    if raw is None:
        structure = getattr(cls, "_flode_structure", None)
        raw = getattr(structure, structure_field, ()) if structure is not None else ()
    return _validated_names(raw, attr)


def _resolve_port_names(
    cls: type, attr: str, structure_field: str, n_ports: int
) -> tuple[str, ...]:
    names = _class_port_names(cls, attr, structure_field)
    if names and len(names) != n_ports:
        raise BlockSpecError(f"{attr} has {len(names)} names but the block has {n_ports} ports")
    return names


def has_dynamic_ports(cls: type) -> bool:
    """クラスが ``block_dynamic_ports = True`` を宣言しているか (継承する)。

    宣言したブロックは、引数ごとのインスタンスの ``n_inputs`` / ``n_outputs`` /
    ``port_shapes_*`` / ``input_names`` / ``output_names`` でポートが決まる。
    静的に読み (ユーザーのメタクラス / descriptor を実行しない)、真偽は ``is True`` だけ認める。
    """
    return inspect.getattr_static(cls, DYNAMIC_PORTS_ATTRIBUTE, False) is True


def is_string_list_type_label(type_label: str) -> bool:
    """型ラベルが文字列の列 (``list[str]`` / ``tuple[str, ...]`` / ``Sequence[str]`` 等) か。

    フロントの ``isStringListTypeLabel`` と同じ規則 (前後の空白は無視、``typing.`` /
    ``collections.abc.`` 付きも受ける)。

    Args:
        type_label: ``read_params`` の型ラベル。

    Returns:
        文字列の列なら ``True``。
    """
    return _STRING_LIST_TYPE_RE.fullmatch(type_label.strip()) is not None


def _is_string_list_value(value: Any) -> bool:
    return isinstance(value, list | tuple) and all(isinstance(v, str) for v in value)


def resolve_param_search(cls: type, params: Sequence[RawParam]) -> tuple[dict[str, str], list[str]]:
    """引数の値の検索の宣言 (``block_param_search``) を検証して、有効な対応だけを返す。

    宣言は ``inspect.getattr_static`` で読む (継承する。ユーザーのメタクラス / descriptor を
    実行しない)。誤りはブロックを拒否せず、その項目 (Mapping でなければ宣言全体) を無視して
    警告文を返す (ADR-0085 §1-D)。読み込み時と検索の要求時の両方で使う。

    有効な項目の条件:

    * キーがクラスの引数名で、その型ラベルが文字列の列 (:func:`is_string_list_type_label`)、
      既定値が文字列のリスト (tuple も可)
    * 値が文字列で、その名前の属性が ``classmethod`` か ``staticmethod``
      (インスタンスを作らずに呼べるもの)

    Args:
        cls: ``Block`` サブクラス。
        params: クラスの引数一覧 (``read_params`` の結果、既定値は JSON 往復済みでもよい)。

    Returns:
        ``({引数名: メソッド名}, [警告文])``。宣言が無ければ ``({}, [])``。
    """
    raw = inspect.getattr_static(cls, PARAM_SEARCH_ATTRIBUTE, None)
    if raw is None:
        return {}, []
    if not isinstance(raw, Mapping):
        return {}, [
            f"{PARAM_SEARCH_ATTRIBUTE} must be a dict of parameter name -> method name, "
            f"got {type(raw).__name__}; it is ignored"
        ]
    by_name = {p.name: p for p in params}
    methods: dict[str, str] = {}
    warnings: list[str] = []
    for key, method_name in raw.items():
        where = f"{PARAM_SEARCH_ATTRIBUTE}[{key!r}]"
        if not isinstance(key, str) or key not in by_name:
            warnings.append(f"{where}: the block has no parameter with this name; it is ignored")
            continue
        param = by_name[key]
        if not is_string_list_type_label(param.type_label) or not _is_string_list_value(
            param.default
        ):
            warnings.append(
                f"{where}: only a parameter annotated as list[str] whose default value is a list "
                f"of strings can be searched (annotation {param.type_label!r}); it is ignored"
            )
            continue
        if not isinstance(method_name, str):
            warnings.append(
                f"{where}: the value must be the name of a classmethod or staticmethod, "
                f"got {type(method_name).__name__}; it is ignored"
            )
            continue
        method = inspect.getattr_static(cls, method_name, None)
        if method is None:
            warnings.append(f"{where}: the class has no attribute {method_name!r}; it is ignored")
            continue
        if not isinstance(method, classmethod | staticmethod):
            warnings.append(
                f"{where}: {method_name!r} must be a classmethod or staticmethod (the search "
                f"runs without creating the block); it is ignored"
            )
            continue
        methods[key] = method_name
    return methods, warnings


def resolve_instance_port_names(
    cls: type, instance: Any, *, strict: bool
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """ポート数が引数で変わるブロック (``block_dynamic_ports``) のポート名をインスタンスから決める。

    方向ごとに、インスタンス属性 ``input_names`` / ``output_names`` (``None`` / 無しなら未宣言)
    を優先し、未宣言なら class の ``block_input_names`` / ``block_output_names`` を使う。

    Args:
        cls: ``Block`` サブクラス。
        instance: ``cls(**params)`` のインスタンス (属性の読み出しはユーザーコードを通る)。
        strict: ``True`` なら class のポート名の数がインスタンスのポート数と合わないときに
            ``BlockSpecError`` (読み込み時の既定値インスタンスの検査)。``False`` なら無名にする
            (引数を変えてポート数が変わった場合)。

    Returns:
        ``(入力ポート名, 出力ポート名)`` (空 = 無名)。

    Raises:
        BlockSpecError: ポート名が文字列の列でない、またはインスタンス属性のポート名の数が
            ポート数と合わない (``strict`` に関係なく)。
    """
    resolved: list[tuple[str, ...]] = []
    for inst_attr, cls_attr, structure_field, n_ports in (
        ("input_names", "block_input_names", "input_names", int(instance.n_inputs)),
        ("output_names", "block_output_names", "output_names", int(instance.n_outputs)),
    ):
        raw = getattr(instance, inst_attr, None)
        if raw is not None:
            names = _validated_names(raw, f"the instance attribute {inst_attr}")
            if names and len(names) != n_ports:
                raise BlockSpecError(
                    f"the instance attribute {inst_attr} has {len(names)} names but the "
                    f"block has {n_ports} ports"
                )
        else:
            names = _class_port_names(cls, cls_attr, structure_field)
            if names and len(names) != n_ports:
                if strict:
                    raise BlockSpecError(
                        f"{cls_attr} has {len(names)} names but the block has {n_ports} ports"
                    )
                names = ()
        resolved.append(names)
    return resolved[0], resolved[1]


def port_names_for_instance(cls: type, instance: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """任意の引数で作ったインスタンスのポート名 (数が合わない class のポート名は無名にする)。

    ``block_dynamic_ports`` を宣言したクラスは ``resolve_instance_port_names`` (非厳密)、
    それ以外は class のポート名だけを見る (インスタンス属性は読まない = 従来どおり)。

    Raises:
        BlockSpecError: ポート名が文字列の列でない等 (``resolve_instance_port_names`` と同じ)。
    """
    if has_dynamic_ports(cls):
        return resolve_instance_port_names(cls, instance, strict=False)
    resolved: list[tuple[str, ...]] = []
    for cls_attr, structure_field, n_ports in (
        ("block_input_names", "input_names", int(instance.n_inputs)),
        ("block_output_names", "output_names", int(instance.n_outputs)),
    ):
        names = _class_port_names(cls, cls_attr, structure_field)
        resolved.append(names if len(names) == n_ports else ())
    return resolved[0], resolved[1]


def resolve_metadata(
    cls: type,
    params: Mapping[str, Any],
    *,
    n_inputs: int,
    n_outputs: int,
    instance: Any = None,
) -> ResolvedMetadata:
    """クラスの公開属性・private 属性・docstring からメタデータを決める。

    宣言の検証は ``@block`` と同じ関数 (``flode.core.block_metadata``) を使う。

    Args:
        cls: ``Block`` サブクラス。
        params: ``{引数名: JSON 往復済みの既定値}`` (選択肢の既定値検査に使う)。
        n_inputs: 既定値でインスタンス化したときの入力ポート数 (ポート名の長さ検査)。
        n_outputs: 同出力ポート数。
        instance: 既定値のインスタンス。``block_dynamic_ports`` を宣言したクラスでは、
            ポート名をこのインスタンスから決める (``resolve_instance_port_names``、
            数の検査は厳密)。``None`` なら class 属性だけを見る。

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

    if instance is not None and has_dynamic_ports(cls):
        input_names, output_names = resolve_instance_port_names(cls, instance, strict=True)
    else:
        input_names = _resolve_port_names(cls, "block_input_names", "input_names", n_inputs)
        output_names = _resolve_port_names(cls, "block_output_names", "output_names", n_outputs)

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
        input_names=input_names,
        output_names=output_names,
    )
