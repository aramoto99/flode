// ADR-0028 + ADR-0029: Block / Library i18n ヘルパ。
//
// `BlockMetadata.display_name_i18n` / `docstring_summary_i18n` (REST schema
// blocks.v2 で同梱、Phase 4 v0.11.0) や、``LibraryEntryMetadata.display_name_i18n``
// / ``description_i18n`` (REST schema libraries.v1、Phase 4 v0.11.1) から現在言語の
// 値を取り出す。schema 旧版 (= optional フィールド undefined) では既存 `display_name`
// にフォールバックする。
//
// 設計方針:
// - `currentLanguage()` (= ADR-0024 §(5) の i18next ラッパ) を再利用。新規 store
//   や状態を増やさない。
// - 言語切替時は i18next の `i18n.language` 変化で `useTranslation()` 経由の
//   再 render が発生し、`localizedDisplayName(b)` が新言語の値を返す。
//   registry 自体の再 fetch は不要 (= TanStack Query cache 互換)。
// - 検索 (`searchableDisplayNames`) は両言語の値を返し、ja 環境でも英語名で
//   ヒットさせる (Simulink 経験者向けセーフネット、ADR-0028 §(4))。

import { currentLanguage } from "../i18n";
import type { BlockMetadata, Locale } from "../types/api";

/** ``localizeName`` を呼べる任意オブジェクトの最小 shape (ADR-0029)。
 *  Block / Library / LibraryEntry のいずれにも適用できる generic 制約。 */
export interface LocalizedNamed {
  display_name?: string;
  display_name_i18n?: Partial<Record<Locale, string>>;
}

/** Block の表示名を現在 (またはユーザー指定) 言語で取得する。
 *
 * フォールバック chain:
 *   1. ``display_name_i18n[lang]`` (schema blocks.v2 同梱の翻訳)
 *   2. ``display_name`` (旧 schema 互換、サーバ側で en コピー)
 *   3. ``type_path`` (= 最終フォールバック、未登録 3rd-party 拡張など)
 *
 * @param block - REST `GET /api/v1/blocks` レスポンスの 1 要素。
 * @param lang - 取り出す locale。省略時は ``currentLanguage()``。
 * @returns 表示名文字列 (空にはならない)。
 */
export function localizedDisplayName(
  block: BlockMetadata,
  lang?: Locale,
): string {
  const l = lang ?? currentLanguage();
  // ``||`` を使うのは「空文字列も missing 扱い」にしたいため。``??`` だと
  // ``display_name = ""`` で空文字を返してしまい、UI が空白セルになる。
  return (
    block.display_name_i18n?.[l] ||
    block.display_name ||
    block.type_path
  );
}

/**
 * Library / LibraryEntry など、``LocalizedNamed`` 制約を満たす任意オブジェクトの
 * 表示名を現在言語で取得する generic 版 (ADR-0029)。
 *
 * **使い分け規約 (重要)**:
 * - ``BlockMetadata`` には必ず {@link localizedDisplayName} を使う (= ``type_path``
 *   フォールバック付き、引数 1 個)。
 * - ``LibraryMetadata`` / ``LibraryEntryMetadata`` (= block 以外) には本関数を使う
 *   (引数 2 個目に ``library.name`` / ``entry.id`` を渡す)。
 *
 * 混用すると ``BlockMetadata`` の ``type_path`` フォールバックが失われたり、
 * library のフォールバック識別子が空になったりして UX が崩れる。
 *
 * @param obj - 翻訳可能オブジェクト (Library / LibraryEntry 等)。
 * @param fallback - 両言語名が空のときの最終フォールバック (= entry.id / library.name)。
 * @param lang - 取り出す locale。省略時は ``currentLanguage()``。
 */
export function localizeName<T extends LocalizedNamed>(
  obj: T,
  fallback: string,
  lang?: Locale,
): string {
  const l = lang ?? currentLanguage();
  return obj.display_name_i18n?.[l] || obj.display_name || fallback;
}

/** Block の 1 行説明を現在言語で取得する (palette tooltip 等で利用)。
 *
 * フォールバック規約は :func:`localizedDisplayName` と統一: 空文字も missing 扱い
 * (= ``||``) で次フォールバックに進む。
 */
export function localizedDocstringSummary(
  block: BlockMetadata,
  lang?: Locale,
): string {
  const l = lang ?? currentLanguage();
  return (
    block.docstring_summary_i18n?.[l] ||
    block.docstring_summary ||
    ""
  );
}

/** Library entry の説明文 (= ``description_i18n``) を現在言語で取得する (ADR-0029)。
 *
 *  ``LibraryEntryMetadata`` / ``LibraryMetadata`` で ``description`` + ``description_i18n``
 *  を持つ shape に対し、空文字も missing 扱いで fallback する generic 関数。
 */
export function localizeDescription<
  T extends {
    description?: string;
    description_i18n?: Partial<Record<Locale, string>>;
  },
>(obj: T, lang?: Locale): string {
  const l = lang ?? currentLanguage();
  return obj.description_i18n?.[l] || obj.description || "";
}

/** 検索インデックス用に **両言語の表示名** + ``type_path`` 末尾名を返す。
 *
 * ja 環境で `"sum"` (英語名) を入力しても `"加算"` のブロックがヒットする
 * (= Simulink 経験者が日本語名を覚えていなくても見つけられる)。
 *
 * 重複排除済 (例: ``Mux`` の display_name が ja/en 同じ値の場合は 1 件)。
 */
export function searchableDisplayNames(block: BlockMetadata): string[] {
  const set = new Set<string>();
  const en = block.display_name_i18n?.en ?? block.display_name;
  const ja = block.display_name_i18n?.ja;
  if (en) set.add(en);
  if (ja) set.add(ja);
  // 末尾の class 名 (= "Constant" 等) も検索対象に: 旧 frontend で `display_name`
  // が空のブロックがあっても `type_path` の末尾でヒットさせる
  const tail = block.type_path.split(".").at(-1);
  if (tail) set.add(tail);
  return Array.from(set);
}
