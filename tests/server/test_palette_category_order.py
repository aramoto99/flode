"""ADR-0019 / ADR-0028 follow-up: backend `_BUILTIN_METADATA` と frontend
側 (palette CATEGORY_ORDER / blockGlyphs.tsx GLYPHS / i18n keys) の整合性
CI ガード。

背景 (2026-06-02): SPEC-0008 / SPEC-0009 で新カテゴリ ``lookup`` /
``userfunc`` を ``_BUILTIN_METADATA`` に追加した際に、frontend 側 3 箇所
(palette CATEGORY_ORDER / blockGlyphs.tsx GLYPHS / i18n) のうち i18n だけは
更新したが、CATEGORY_ORDER と GLYPHS の更新を 2 回連続で見落とし、
新ブロックが palette から silently 除外され、generic fallback グリフで描画
される事故が発生した。本テストは backend 側にブロック / カテゴリを追加した
ときに frontend 側 3 箇所の更新漏れを CI で検知する。
"""

from __future__ import annotations

import re
from pathlib import Path


def _frontend_root() -> Path:
    return Path(__file__).parents[2] / "flode" / "web" / "frontend" / "src"


def _parse_category_order(tsx_path: Path) -> list[str]:
    """`const CATEGORY_ORDER = [ ... ] as const;` を text-parse で抽出する。

    TypeScript パーサを CI に持ち込まないための軽量実装。引用符の囲いと
    コメント (``// ...``) を扱う。本テストの寿命を超えて TSX 構文が変化したら
    ここを更新する。
    """
    text = tsx_path.read_text(encoding="utf-8")
    match = re.search(
        r"const\s+CATEGORY_ORDER\s*=\s*\[(.*?)\]\s*as\s+const\s*;",
        text,
        re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"CATEGORY_ORDER definition not found in {tsx_path}")
    body = match.group(1)
    # `// ...` コメントを除去
    body = re.sub(r"//[^\n]*", "", body)
    # 引用符内の category 名を抽出 (シングル / ダブル両対応)
    return re.findall(r"[\"']([^\"']+)[\"']", body)


def test_backend_categories_subset_of_palette_category_order() -> None:
    """backend `_BUILTIN_METADATA` の category 集合 ⊆ frontend CATEGORY_ORDER。

    backend 側にカテゴリを追加するときに frontend 側 whitelist への追加を忘れ
    ないようにする CI ガード。
    """
    from flode.server.registry import _BUILTIN_METADATA

    backend_categories = {meta[0] for meta in _BUILTIN_METADATA.values()}

    tsx_path = _frontend_root() / "components" / "BlockPalette.tsx"
    frontend_order = _parse_category_order(tsx_path)
    frontend_categories = set(frontend_order)

    missing = backend_categories - frontend_categories
    assert not missing, (
        f"BlockPalette.tsx CATEGORY_ORDER is missing backend categories: "
        f"{sorted(missing)}. Add them to "
        f"`flode/web/frontend/src/components/BlockPalette.tsx` `CATEGORY_ORDER` "
        f"array (and rebuild the frontend bundle)."
    )


def test_palette_category_i18n_keys_exist_for_all_categories() -> None:
    """各 CATEGORY_ORDER エントリに対応する ja/en 翻訳キーが存在する。

    新カテゴリを CATEGORY_ORDER に足したが ``palette.category.{name}`` を
    i18n に書き忘れる事故を防ぐ。
    """
    import json

    tsx_path = _frontend_root() / "components" / "BlockPalette.tsx"
    frontend_order = _parse_category_order(tsx_path)

    for locale in ("en", "ja"):
        locale_path = _frontend_root() / "i18n" / "locales" / f"{locale}.json"
        translations = json.loads(locale_path.read_text(encoding="utf-8"))
        for category in frontend_order:
            key = f"palette.category.{category}"
            assert key in translations, (
                f"i18n {locale}.json missing key {key!r} (referenced from "
                f"BlockPalette.tsx CATEGORY_ORDER). Add it to "
                f"`flode/web/frontend/src/i18n/locales/{locale}.json`."
            )


def _parse_glyph_entries(tsx_path: Path) -> set[str]:
    """``blockGlyphs.tsx`` の ``GLYPHS`` map から登録済 type_path を抽出する。

    text-parse で ``"flode.blocks.foo.Bar": SomeGlyph,`` 形式の行を拾う。
    """
    text = tsx_path.read_text(encoding="utf-8")
    # `"flode.blocks.lookup.LookupTable1D": LookupTable1DGlyph,` 等
    # `"flode.subsystems.ports.Inport": InportGlyph,` も拾うため flode\. 始まりにする
    return set(re.findall(r'"(flode\.[^"]+)":\s*\w+Glyph', text))


def test_all_builtin_blocks_have_glyph_entries() -> None:
    """backend `_BUILTIN_METADATA` の全 type_path が ``GLYPHS`` map に登録済。

    未登録は ``GlyphFallback`` (薄い汎用 rect) に落ち、ブロック識別性が
    失われる。SPEC-0008 / SPEC-0009 で発生した glyph 登録漏れ事故 (新ブロックが
    全て同じ generic icon になる) を CI で検知する。
    """
    from flode.server.registry import _BUILTIN_METADATA

    tsx_path = _frontend_root() / "lib" / "blockGlyphs.tsx"
    glyph_entries = _parse_glyph_entries(tsx_path)
    backend_type_paths = set(_BUILTIN_METADATA.keys())

    missing = backend_type_paths - glyph_entries
    assert not missing, (
        f"blockGlyphs.tsx GLYPHS is missing entries for: {sorted(missing)}. "
        f"Add a `*Glyph` React component and register it in `GLYPHS` "
        f"(see `flode/web/frontend/src/lib/blockGlyphs.tsx`). Without an "
        f"entry, the block falls back to `GlyphFallback` (a generic faint "
        f"rectangle) and loses visual identity."
    )
