"""ブロックのメタデータ (パレット / Inspector 用) の公開属性名と検証規則 (ADR-0081 §論点 7-A)。

``@block`` デコレータの引数と、``Block`` サブクラスに直接書かれた公開 class 属性
(``block_*``) の両方に **同じ規則** を適用するための唯一の置き場。検証関数は純粋関数で、
違反はすべて :class:`~flode.exceptions.BlockSpecError` で送出する。
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from ..exceptions import BlockSpecError

#: ``@block`` が生成クラスに書き込むメタデータ属性 (class 形ではフィールド名として予約)。
METADATA_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "block_category",
        "block_display_name",
        "block_description",
        "block_choices",
        "block_param_descriptions",
        "block_input_names",
        "block_output_names",
    }
)

#: パレットに出さない印 (ADR-0081 P1)。そのクラス自身の ``__dict__`` だけを見る。
HIDDEN_ATTRIBUTE = "block_hidden"

#: :func:`validate_choices` の ``params`` で「既定値なし (必須引数)」を表す値。
NO_DEFAULT: Any = inspect.Parameter.empty


def validate_category(value: Any, *, owner: str) -> str:
    """カテゴリ名を検証する。

    Args:
        value: カテゴリ名の候補。
        owner: エラーメッセージに出すブロック (関数 / クラス) 名。

    Returns:
        ``value`` (空白だけでない ``str``)。

    Raises:
        BlockSpecError: ``str`` でない、または空・空白のみ。
    """
    if not isinstance(value, str) or not value.strip():
        raise BlockSpecError(f"category of {owner!r} must be a non-empty str, got {value!r}")
    return value


def validate_text(value: Any, *, field: str, owner: str) -> str | dict[str, str]:
    """表示名 / 説明 (``display_name`` / ``description``) を検証する。

    Args:
        value: 空でない ``str``、または言語コード → 空でない ``str`` の空でない Mapping
            (``{"ja": ..., "en": ...}``)。
        field: エラーメッセージに出す項目名 (``"display_name"`` 等)。
        owner: エラーメッセージに出すブロック名。

    Returns:
        ``str`` はそのまま、Mapping は ``dict`` のコピー。

    Raises:
        BlockSpecError: 上記の形でない (空文字・空白のみ・空 Mapping・非 ``str`` のキー / 値)。
    """
    if isinstance(value, str):
        if value.strip():
            return value
    elif isinstance(value, Mapping) and value:
        if all(
            isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip()
            for k, v in value.items()
        ):
            return dict(value)
    raise BlockSpecError(
        f"{field} of {owner!r} must be a non-empty str or a non-empty mapping of "
        f'language code to str (e.g. {{"ja": ..., "en": ...}}), got {value!r}'
    )


def validate_choices(
    choices: Any, params: Mapping[str, Any], *, owner: str
) -> dict[str, tuple[str, ...]]:
    """選択肢の宣言 (パラメータ名 → 候補文字列の列) を検証する。

    Args:
        choices: パラメータ名 → 候補の列の Mapping。
        params: ブロックのパラメータ名 → 既定値。既定値の無い (必須) 引数は
            :data:`NO_DEFAULT` (= ``inspect.Parameter.empty``) を値にする。
        owner: エラーメッセージに出すブロック名。

    Returns:
        パラメータ名 → 候補の ``tuple`` (入力のコピー)。

    Raises:
        BlockSpecError: Mapping でない / キーが ``params`` に無い / 候補が空・非 ``str``・
            ``str`` そのもの (列でない)・重複 / 既定値が候補に含まれない。
    """
    if not isinstance(choices, Mapping):
        raise BlockSpecError(
            f"choices of {owner!r} must be a mapping of parameter name to a sequence "
            f"of str, got {type(choices).__name__}"
        )
    resolved: dict[str, tuple[str, ...]] = {}
    for pname, options in choices.items():
        if pname not in params:
            raise BlockSpecError(
                f"choices of {owner!r} names {pname!r}, which is not a parameter; "
                f"parameters: {list(params)}"
            )
        if (
            isinstance(options, str)
            or not isinstance(options, Sequence)
            or not options
            or not all(isinstance(o, str) for o in options)
        ):
            raise BlockSpecError(
                f"choices[{pname!r}] of {owner!r} must be a non-empty sequence of str "
                f'(e.g. ["fast", "slow"]), got {options!r}'
            )
        candidates = tuple(options)
        if len(set(candidates)) != len(candidates):
            raise BlockSpecError(
                f"choices[{pname!r}] of {owner!r} has duplicate candidates {list(candidates)}"
            )
        default = params[pname]
        if default is not NO_DEFAULT and default not in candidates:
            raise BlockSpecError(
                f"the default value {default!r} of parameter {pname!r} of {owner!r} is "
                f"not among its choices {list(candidates)}"
            )
        resolved[pname] = candidates
    return resolved


def validate_param_descriptions(
    descriptions: Any, param_names: Iterable[str], *, owner: str
) -> dict[str, str | dict[str, str]]:
    """パラメータの説明 (パラメータ名 → 説明文) を検証する。

    説明文は ``str``、または ``display_name`` / ``description`` と同じ言語コード → ``str``
    の Mapping (``{"ja": ..., "en": ...}``、Inspector が表示言語で選ぶ)。

    Args:
        descriptions: パラメータ名 → 説明文の Mapping。
        param_names: ブロックのパラメータ名。
        owner: エラーメッセージに出すブロック名。

    Returns:
        入力の ``dict`` コピー (言語別の Mapping も ``dict`` にコピーする)。

    Raises:
        BlockSpecError: Mapping でない / キーが ``param_names`` に無い / 値が ``str`` でも
            言語別の Mapping (空でない ``str`` → 空でない ``str``) でもない。
    """
    if not isinstance(descriptions, Mapping):
        raise BlockSpecError(
            f"param_descriptions of {owner!r} must be a mapping of parameter name to "
            f"str, got {type(descriptions).__name__}"
        )
    names = list(param_names)
    validated: dict[str, str | dict[str, str]] = {}
    for pname, text in descriptions.items():
        if pname not in names:
            raise BlockSpecError(
                f"param_descriptions of {owner!r} names {pname!r}, which is not a "
                f"parameter; parameters: {names}"
            )
        if isinstance(text, str):
            validated[pname] = text
        elif isinstance(text, Mapping):
            validated[pname] = validate_text(
                text, field=f"param_descriptions[{pname!r}]", owner=owner
            )
        else:
            raise BlockSpecError(
                f"param_descriptions[{pname!r}] of {owner!r} must be a str or a mapping of "
                f'language code to str (e.g. {{"ja": ..., "en": ...}}), '
                f"got {type(text).__name__}"
            )
    return validated
