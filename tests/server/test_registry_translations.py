"""ADR-0028: Block class registry の i18n 翻訳テーブル検証。

``_BUILTIN_METADATA`` と ``_BLOCK_TRANSLATIONS`` の整合 + 各翻訳エントリの
形式 + ``build_metadata()`` / ``metadata_to_dict()`` での REST 同梱を検証する。
"""

from __future__ import annotations

import pytest

from flode.blocks.sources import Constant
from flode.server.registry import build_metadata, metadata_to_dict
from flode.server.registry_translations import (
    _BLOCK_TRANSLATIONS,
    SUPPORTED_LOCALES,
    all_registered_type_paths,
    get_translations,
)


def _builtin_type_paths() -> set[str]:
    """``registry._BUILTIN_METADATA`` のキー集合を取得する。"""
    from flode.server.registry import _BUILTIN_METADATA

    return set(_BUILTIN_METADATA.keys())


class TestTranslationCoverage:
    """``_BLOCK_TRANSLATIONS`` が ``_BUILTIN_METADATA`` の全エントリをカバー。"""

    def test_all_builtin_blocks_have_translations(self) -> None:
        builtin = _builtin_type_paths()
        translated = all_registered_type_paths()
        missing = builtin - translated
        extra = translated - builtin
        assert not missing, (
            f"_BLOCK_TRANSLATIONS is missing entries for: {sorted(missing)}. "
            "Add them to flode/server/registry_translations.py."
        )
        assert not extra, (
            f"_BLOCK_TRANSLATIONS has stale entries that are not in "
            f"_BUILTIN_METADATA: {sorted(extra)}. Remove them."
        )


class TestTranslationFormat:
    """各エントリが en/ja の display_name + docstring_summary を持つ。"""

    @pytest.mark.parametrize("type_path", sorted(_BLOCK_TRANSLATIONS.keys()))
    def test_all_translations_have_both_locales(self, type_path: str) -> None:
        entry = _BLOCK_TRANSLATIONS[type_path]
        for locale in SUPPORTED_LOCALES:
            assert locale in entry, f"{type_path}: missing locale {locale!r}"
            for field in ("display_name", "docstring_summary"):
                assert field in entry[locale], f"{type_path}.{locale}: missing field {field!r}"

    @pytest.mark.parametrize("type_path", sorted(_BLOCK_TRANSLATIONS.keys()))
    def test_translations_are_non_empty(self, type_path: str) -> None:
        """空文字列で翻訳漏れを誤魔化していないか。"""
        entry = _BLOCK_TRANSLATIONS[type_path]
        for locale in SUPPORTED_LOCALES:
            for field, value in entry[locale].items():
                assert isinstance(value, str), (
                    f"{type_path}.{locale}.{field}: expected str, got {type(value).__name__}"
                )
                assert value.strip(), f"{type_path}.{locale}.{field}: must be non-empty"

    def test_get_translations_unknown_returns_empty(self) -> None:
        """未登録の type_path は空 dict を返す (= フォールバック挙動の前提)。"""
        assert get_translations("nonexistent.module.Block") == {}


class TestBuildMetadataI18n:
    """``build_metadata()`` が i18n フィールドを含めて構築する。"""

    def test_build_metadata_constant(self) -> None:
        m = build_metadata(Constant)
        assert m.display_name_i18n == {
            "en": "Constant",
            "ja": "定数",
        }
        # SPEC-0026 (v0.53.0): output_type 追加に伴い summary を更新
        assert (
            m.docstring_summary_i18n["en"]
            == "Constant value source y(t) = value (output_type: float / int / bool)."
        )
        assert (
            m.docstring_summary_i18n["ja"]
            == "定数値ソース y(t) = value (output_type で float / int / bool)。"
        )

    def test_legacy_field_consistency(self) -> None:
        """``display_name`` / ``docstring_summary`` は en コピーになっている。"""
        m = build_metadata(Constant)
        assert m.display_name == m.display_name_i18n["en"]
        assert m.docstring_summary == m.docstring_summary_i18n["en"]


class TestMetadataToDict:
    """REST レスポンス JSON に i18n フィールドが含まれる。"""

    def test_dict_includes_i18n(self) -> None:
        m = build_metadata(Constant)
        d = metadata_to_dict(m)
        assert d["display_name_i18n"] == {"en": "Constant", "ja": "定数"}
        assert (
            d["docstring_summary_i18n"]["ja"]
            == "定数値ソース y(t) = value (output_type で float / int / bool)。"
        )
        # 旧 frontend 互換: display_name / docstring_summary も同梱
        assert d["display_name"] == "Constant"
        assert (
            d["docstring_summary"]
            == "Constant value source y(t) = value (output_type: float / int / bool)."
        )
