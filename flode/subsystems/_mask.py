"""Mask parameter placeholder substitution (ADR-0021 §(6))。

Subsystem の内部 block ``params`` に埋め込まれた ``"$Kp"`` 形式の placeholder
文字列を、外側 ``Subsystem.mask_values`` に基づいて実値に置換する純粋関数群。

Phase 3 では:
  - placeholder は **完全一致 string `"$<identifier>"`** のみ (式 / interpolation
    なし)。`"$Kp + $Ki"` のような式は Phase 4 で別 ADR
  - 識別子は ADR-0004 と同じ ``[A-Za-z_][A-Za-z0-9_]*``
  - 識別子が ``mask_values`` に無ければ ``BlockSpecError``
  - 値は ``mask_values[id]`` をそのまま代入 (型変換なし)。型整合は ``Subsystem._build``
    の port_shape check で間接的に検証
"""

from __future__ import annotations

import re
from typing import Any

from ..exceptions import BlockSpecError

_IDENTIFIER_PATTERN = r"[A-Za-z_][A-Za-z0-9_]*"
_PLACEHOLDER_RE = re.compile(rf"^\$({_IDENTIFIER_PATTERN})$")
_IDENTIFIER_RE = re.compile(rf"^{_IDENTIFIER_PATTERN}$")


def is_placeholder(value: Any) -> bool:
    """``value`` が placeholder 文字列 (``"$<id>"``) なら True。"""
    return isinstance(value, str) and bool(_PLACEHOLDER_RE.match(value))


def extract_placeholder_name(value: str) -> str | None:
    """``"$Kp"`` から ``"Kp"`` を取り出す。マッチしないとき ``None``。"""
    m = _PLACEHOLDER_RE.match(value)
    return m.group(1) if m else None


def substitute_placeholders(params: dict[str, Any], mask_values: dict[str, Any]) -> dict[str, Any]:
    """``params`` 内の placeholder を ``mask_values`` で置換した新 dict を返す。

    ネストした dict / list / tuple も再帰的に処理する。``params`` 自体は変更しない。
    使用された placeholder の識別子が ``mask_values`` に無ければ ``BlockSpecError``。

    Args:
        params: 置換対象の params 辞書 (Block の ``_params`` 想定)。
        mask_values: 置換に使う ``{name: value}`` 辞書。

    Returns:
        新しい params 辞書。placeholder が含まれない場合は元と内容上等しい新 dict。

    Raises:
        BlockSpecError: 未定義の placeholder 識別子が見つかった場合。
    """
    result = _substitute_value(params, mask_values)
    assert isinstance(result, dict)  # 入力 dict → 出力 dict (型 narrowing)
    return result


def _substitute_value(value: Any, mask_values: dict[str, Any]) -> Any:
    if isinstance(value, str):
        name = extract_placeholder_name(value)
        if name is None:
            return value
        if name not in mask_values:
            raise BlockSpecError(
                f"Unresolved mask placeholder ${name!s}: identifier not declared in "
                f"mask_values (declared: {sorted(mask_values)})"
            )
        return mask_values[name]
    if isinstance(value, dict):
        return {k: _substitute_value(v, mask_values) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_value(v, mask_values) for v in value]
    if isinstance(value, tuple):
        return tuple(_substitute_value(v, mask_values) for v in value)
    return value


def collect_placeholder_names(params: dict[str, Any]) -> set[str]:
    """``params`` 内で参照されている全 placeholder 識別子を返す (重複なし)。

    Subsystem の build 時に「宣言 mask_params に対し未参照」「未宣言の参照」の
    両方向を検出するために使う。
    """
    names: set[str] = set()
    _collect(params, names)
    return names


def _collect(value: Any, names: set[str]) -> None:
    if isinstance(value, str):
        n = extract_placeholder_name(value)
        if n is not None:
            names.add(n)
    elif isinstance(value, dict):
        for v in value.values():
            _collect(v, names)
    elif isinstance(value, list | tuple):
        for v in value:
            _collect(v, names)


def normalize_mask_params(
    spec: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """``mask_params`` 宣言の形式を正規化する (Phase 3 では type=scalar のみ)。

    各 entry: ``{"name": str, "type": "float"|"int"|"bool", "default": Any,
                "description": str}``。
    余分なキーは破棄、必須キーが欠落 / 不正なら ``BlockSpecError``。

    Args:
        spec: ``Subsystem.__init__`` に渡された ``mask_params``。

    Returns:
        正規化済み list (空 list / None は ``None``)。

    Raises:
        BlockSpecError: 不正な type / 名前 / 構造。
    """
    if spec is None:
        return None
    if not isinstance(spec, list):
        raise BlockSpecError(f"mask_params must be a list of dicts, got {type(spec).__name__}")
    if len(spec) == 0:
        return None
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, entry in enumerate(spec):
        if not isinstance(entry, dict):
            raise BlockSpecError(f"mask_params[{i}] must be a dict, got {type(entry).__name__}")
        name = entry.get("name")
        if not isinstance(name, str) or not _IDENTIFIER_RE.match(name):
            raise BlockSpecError(
                f"mask_params[{i}].name must be a valid identifier "
                f"(letters/digits/underscore, leading non-digit), got {name!r}"
            )
        if name in seen:
            raise BlockSpecError(f"mask_params[{i}].name {name!r} is duplicated")
        seen.add(name)
        type_ = entry.get("type")
        if type_ not in ("float", "int", "bool"):
            raise BlockSpecError(
                f"mask_params[{i}].type must be 'float'/'int'/'bool' "
                f"(scalar only in Phase 3, ADR-0021 §(7)), got {type_!r}"
            )
        normalized: dict[str, Any] = {
            "name": name,
            "type": type_,
            "default": entry.get("default"),
            "description": str(entry.get("description", "")),
        }
        out.append(normalized)
    return out
