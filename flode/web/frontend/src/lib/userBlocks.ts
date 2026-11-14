// ADR-0081 §8-B: ユーザーブロック (ワークスペース blocks/・config dirs・config modules) を
// パレットに並べる規則。描画 (BlockPalette) から切り離した純粋関数で、単体テストで固定する。
//
// 並び:
//   1. 読み込み元ごとのセクション (組み込みより上): ワークスペース → dirs → modules
//      (同じ種類の中はサーバの返した順 = config の記述順)
//   2. セクション内: カテゴリ未宣言 ("") のブロックを直下に、宣言カテゴリをサブ見出し
//      (文字列の昇順、翻訳しない) で
//   3. 組み込みカテゴリ: ``categoryOrder`` の順。``categoryOrder`` に無いカテゴリは
//      ``uncategorized`` の直前に文字列の昇順で出す (無言で消さない)

import type {
  BlockMetadata,
  BlockParamSpec,
  BlockRegistryResponse,
  BlockSourceInfo,
  BlockSourceKind,
  Locale,
} from "../types/api";
import {
  cleanServerText,
  MAX_DESCRIPTION_CHARS,
  MAX_LABEL_CHARS,
  MAX_PATH_CHARS,
} from "./untrustedText";

/** 組み込みブロックの ``source`` (v2 以前のサーバは欠落 = 組み込み扱い)。 */
export const BUILTIN_SOURCE = "builtin";
/** 組み込み側の「その他」カテゴリ (``categoryOrder`` 外のカテゴリはこの直前に出す)。 */
export const UNCATEGORIZED = "uncategorized";
/** 表示名も型名も整形で空になったユーザーブロックの表示名。 */
const UNNAMED_BLOCK_LABEL = "?";

const SOURCE_KIND_RANK: Record<BlockSourceKind, number> = {
  workspace: 0,
  dir: 1,
  module: 2,
};

/**
 * ユーザーブロック (組み込み以外の読み込み元から来たブロック) か。
 *
 * @param block - registry の 1 要素 (``source`` だけを見る)。
 * @returns ``source`` が ``"builtin"`` 以外の文字列なら ``true``。
 */
export function isUserBlock(block: Pick<BlockMetadata, "source">): boolean {
  return typeof block.source === "string" && block.source !== BUILTIN_SOURCE;
}

/** カテゴリ 1 つ分のブロック (組み込みカテゴリ・ユーザーブロックのサブ見出しで共用)。 */
export interface CategoryGroup {
  /** 組み込みはカテゴリ id、ユーザーブロックは整形済みのカテゴリ文字列。 */
  category: string;
  blocks: BlockMetadata[];
}

/** 読み込み元 1 件のセクション。 */
export interface UserBlockSection {
  /** 読み込み元 id (``BlockMetadata.source``)。 */
  id: string;
  /** ``sources[]`` の情報。ブロックが ``sources`` に無い id を指す場合は ``null``。 */
  source: BlockSourceInfo | null;
  /** カテゴリ未宣言のブロック (セクション直下)。 */
  direct: BlockMetadata[];
  /** 宣言カテゴリのサブ見出し (カテゴリ文字列の昇順)。 */
  groups: CategoryGroup[];
  /** セクション内のブロック数 (``direct`` + 全 ``groups``)。 */
  count: number;
}

/** パレット全体の並び。 */
export interface PaletteLayout {
  userSections: UserBlockSection[];
  builtinGroups: CategoryGroup[];
}

/** 文字列の昇順 (code point 順、ロケールに依存しない決定的な順)。 */
function compareStrings(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/**
 * 読み込み元を「ワークスペース → dirs → modules」の順に並べる (同じ種類はサーバの順のまま)。
 *
 * @param sources - ``GET /blocks`` の ``sources``。
 * @returns 並べ替えた新しい配列。
 */
export function orderSources(sources: readonly BlockSourceInfo[]): BlockSourceInfo[] {
  return sources
    .map((s, index) => ({ s, index }))
    .sort((a, b) => {
      const rank =
        (SOURCE_KIND_RANK[a.s.kind] ?? Number.MAX_SAFE_INTEGER) -
        (SOURCE_KIND_RANK[b.s.kind] ?? Number.MAX_SAFE_INTEGER);
      return rank !== 0 ? rank : a.index - b.index;
    })
    .map(({ s }) => s);
}

/**
 * i18next の言語タグ (``"ja-JP"`` 等) を registry の locale に寄せる (``ja*`` → ``"ja"``、
 * それ以外 → ``"en"``。``i18n.currentLanguage`` と同じ規則)。
 */
export function toLocale(tag: string | undefined): Locale {
  return (tag ?? "").toLowerCase().startsWith("ja") ? "ja" : "en";
}

/**
 * ユーザーブロックの表示名 (整形済み)。``display_name_i18n[lang]`` → ``display_name`` →
 * 型名の順にフォールバックする (整形で空になったものは飛ばす)。
 *
 * @param block - registry の 1 要素 (ユーザーブロック)。
 * @param lang - 表示言語。
 * @returns 空にならない表示名。
 */
export function userBlockDisplayName(block: BlockMetadata, lang: Locale): string {
  return (
    cleanServerText(block.display_name_i18n?.[lang], MAX_LABEL_CHARS) ||
    cleanServerText(block.display_name, MAX_LABEL_CHARS) ||
    cleanServerText(block.type_path, MAX_PATH_CHARS) ||
    UNNAMED_BLOCK_LABEL
  );
}

/**
 * ユーザーブロックの選択肢 (``enum_values``) の表示ラベル (値と同じ順)。
 *
 * 値はそのまま保存するが、表示は整形する。整形すると空になるもの・他と同じ表示に
 * なるもの (``"a<RLO>b"`` と ``"ab"``、上限で切った先頭が同じもの) は区別できないので、
 * ``JSON.stringify`` した値を同じ上限で切ったものに替え、それでも重複すれば
 * 位置番号 (``#1`` 始まり) を付ける。
 *
 * @param values - 選択肢の値。
 * @returns 互いに異なり空でない表示ラベル。
 */
export function choiceLabels(values: readonly string[]): string[] {
  const cleaned = values.map((v) => cleanServerText(v, MAX_LABEL_CHARS));
  const counts = new Map<string, number>();
  for (const c of cleaned) counts.set(c, (counts.get(c) ?? 0) + 1);
  const labels = values.map((v, i) => {
    const c = cleaned[i] ?? "";
    return c !== "" && counts.get(c) === 1
      ? c
      : cleanServerText(JSON.stringify(v), MAX_LABEL_CHARS);
  });
  const seen = new Map<string, number>();
  for (const l of labels) seen.set(l, (seen.get(l) ?? 0) + 1);
  return labels.map((l, i) => ((seen.get(l) ?? 0) > 1 || l === "" ? `${l} #${i + 1}` : l));
}

/**
 * ユーザーブロックの 1 行説明 (整形済み、無ければ ``""``)。
 *
 * @param block - registry の 1 要素 (ユーザーブロック)。
 * @param lang - 表示言語。
 * @returns 説明文。
 */
export function userBlockDescription(block: BlockMetadata, lang: Locale): string {
  return (
    cleanServerText(block.docstring_summary_i18n?.[lang], MAX_DESCRIPTION_CHARS) ||
    cleanServerText(block.docstring_summary, MAX_DESCRIPTION_CHARS)
  );
}

/**
 * ユーザーブロックの引数の説明 (整形済み、無ければ ``""``)。``description_i18n[lang]`` →
 * ``description`` の順 (ブロックの説明と同じ規則)。
 *
 * @param spec - registry の引数 1 つ (未定義なら ``""``)。
 * @param lang - 表示言語。
 * @returns 説明文。
 */
export function userParamDescription(
  spec: BlockParamSpec | undefined,
  lang: Locale,
): string {
  return (
    cleanServerText(spec?.description_i18n?.[lang], MAX_DESCRIPTION_CHARS) ||
    cleanServerText(spec?.description, MAX_DESCRIPTION_CHARS)
  );
}

/** ユーザーブロックのカテゴリ (整形済み。未宣言・整形で空になったものは ``""``)。 */
export function userBlockCategory(block: BlockMetadata): string {
  return cleanServerText(block.category, MAX_LABEL_CHARS);
}

function groupByCategory(
  blocks: readonly BlockMetadata[],
  categoryOf: (b: BlockMetadata) => string,
  nameOf: (b: BlockMetadata) => string,
): Map<string, BlockMetadata[]> {
  const grouped = new Map<string, BlockMetadata[]>();
  for (const b of blocks) {
    const key = categoryOf(b);
    const list = grouped.get(key);
    if (list) list.push(b);
    else grouped.set(key, [b]);
  }
  for (const list of grouped.values()) {
    list.sort((a, b) => nameOf(a).localeCompare(nameOf(b)));
  }
  return grouped;
}

function builtinGroups(
  blocks: readonly BlockMetadata[],
  categoryOrder: readonly string[],
  nameOf: (b: BlockMetadata) => string,
): CategoryGroup[] {
  // 組み込みでカテゴリが空のもの (通常は無い) は「その他」に寄せる
  const grouped = groupByCategory(
    blocks,
    (b) => (b.category === "" ? UNCATEGORIZED : b.category),
    nameOf,
  );
  const known = categoryOrder.filter((c) => c !== UNCATEGORIZED);
  const extras = [...grouped.keys()]
    .filter((c) => !categoryOrder.includes(c))
    .sort(compareStrings);
  return [...known, ...extras, UNCATEGORIZED]
    .filter((c) => (grouped.get(c)?.length ?? 0) > 0)
    .map((c) => ({ category: c, blocks: grouped.get(c) ?? [] }));
}

function userSection(
  id: string,
  source: BlockSourceInfo | null,
  blocks: readonly BlockMetadata[],
  nameOf: (b: BlockMetadata) => string,
): UserBlockSection {
  const grouped = groupByCategory(blocks, userBlockCategory, nameOf);
  const groups = [...grouped.keys()]
    .filter((c) => c !== "")
    .sort(compareStrings)
    .map((c) => ({ category: c, blocks: grouped.get(c) ?? [] }));
  return {
    id,
    source,
    direct: grouped.get("") ?? [],
    groups,
    count: blocks.length,
  };
}

/**
 * パレットの並び (ユーザーブロックのセクション + 組み込みカテゴリ) を作る。
 *
 * セクションは ``sources`` にある読み込み元ごとに作り、ブロックが 0 件でも返す
 * (「読み込み元はあるがブロックが無い」を 1 行で示すため)。ただし検索中 (``filtering``)
 * はヒットの無いセクションを除く。``sources`` に無い読み込み元を指すブロックは、
 * その id のセクションを末尾に足して出す (無言で消さない)。
 *
 * @param registry - ``GET /blocks`` の応答 (``sources`` だけを見る)。
 * @param blocks - 表示対象のブロック (検索で絞り込み済み)。
 * @param options.categoryOrder - 組み込みカテゴリの表示順。
 * @param options.filtering - 検索中か。
 * @param options.nameOf - カテゴリ内の並び替えに使う表示名。
 * @returns セクションと組み込みカテゴリの並び。
 */
export function buildPaletteLayout(
  registry: Pick<BlockRegistryResponse, "sources">,
  blocks: readonly BlockMetadata[],
  options: {
    categoryOrder: readonly string[];
    filtering: boolean;
    nameOf: (b: BlockMetadata) => string;
  },
): PaletteLayout {
  const userBlocks = new Map<string, BlockMetadata[]>();
  const builtin: BlockMetadata[] = [];
  for (const b of blocks) {
    if (isUserBlock(b)) {
      const id = b.source as string;
      const list = userBlocks.get(id);
      if (list) list.push(b);
      else userBlocks.set(id, [b]);
    } else {
      builtin.push(b);
    }
  }

  const sections: UserBlockSection[] = [];
  const seen = new Set<string>();
  for (const source of orderSources(registry.sources ?? [])) {
    if (seen.has(source.id)) continue;
    seen.add(source.id);
    sections.push(
      userSection(source.id, source, userBlocks.get(source.id) ?? [], options.nameOf),
    );
  }
  for (const [id, list] of userBlocks) {
    if (seen.has(id)) continue;
    seen.add(id);
    sections.push(userSection(id, null, list, options.nameOf));
  }

  return {
    userSections: sections.filter(
      (s) => s.count > 0 || (s.source !== null && !options.filtering),
    ),
    builtinGroups: builtinGroups(builtin, options.categoryOrder, options.nameOf),
  };
}
