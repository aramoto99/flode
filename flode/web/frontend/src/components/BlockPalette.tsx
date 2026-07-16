// ADR-0019 §(3) + UI 刷新: ブロックパレット。
// 各エントリに block 種別固有の SVG glyph プレビューを表示する Library
// Browser 風の見た目。検索 + カテゴリ折りたたみ。drag-start で
// `application/pyflw-block-type` を data transfer に積む。
//
// ADR-0029: マスク Subsystem 集合を配布する `.flwlib.json` (= block library) を
// Block class registry の **下** に Libraries セクションとして表示する。drag-start
// では `application/pyflw-library-entry-ref` MIME で `{library, entry}` を運び、
// drop 経路 (DiagramCanvas) で個別 fetch + Inline 展開する。

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { listBlockMetadata, listLibraries } from "../api/client";
import { BlockGlyph } from "../lib/blockGlyphs";
import {
  localizeName,
  localizedDisplayName,
  localizedDocstringSummary,
  searchableDisplayNames,
} from "../lib/blockI18n";
import { buildDefaultParams } from "../lib/idGenerator";
import type {
  BlockMetadata,
  LibraryEntryMetadata,
  LibraryMetadata,
} from "../types/api";

// 重要: このリストは palette 表示の whitelist として働く (= 含まれない category
// のブロックは silently filter で除外される)。backend `_BUILTIN_METADATA` に新
// category を追加するときは、ここにも追加すること。CI ガード
// `tests/server/test_palette_category_order.py` が backend のカテゴリ集合 ⊆
// CATEGORY_ORDER であることを継続的に検証する。
const CATEGORY_ORDER = [
  "sources",
  "mathops",
  // SPEC-0012 / ADR-0059 (v5.5.0): 状態を持つ非線形要素 (Rate Limiter / Relay)。
  // 業界標準ツールと同じ「discontinuities」名。mathops の隣で「動的な非線形」を集約。
  "discontinuities",
  // SPEC-0008 / ADR-0059 (v5.1.0): 静的非線形マップ (math 近傍)
  "lookup",
  // SPEC-0009 / ADR-0059 (v5.2.0): 任意式評価 (math 近傍)
  "userfunc",
  "continuous",
  "discrete",
  "logic",
  "routing",
  "sinks",
  "subsystems",
  // ADR-0058: Subsystem 内部に置く境界ブロック (Inport / Outport / Trigger /
  // Enable) を集約した「control」カテゴリ。subsystems の直後に並べて palette
  // 上の位置を「Subsystem 関連の隣」にする。
  "control",
  "uncategorized",
] as const;

export function BlockPalette(): JSX.Element {
  const { t, i18n } = useTranslation();
  const { data, isLoading, error } = useQuery({
    queryKey: ["blocks-registry"],
    queryFn: listBlockMetadata,
    staleTime: 60 * 60 * 1000,
  });
  // ADR-0029: Library registry も同様に長期 cache。drag-start 時には ref のみ
  // 運び、drop 経路で別 query が body を取りに行く。
  const { data: libraryData } = useQuery({
    queryKey: ["libraries-registry"],
    queryFn: listLibraries,
    staleTime: 60 * 60 * 1000,
  });
  const [search, setSearch] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  // ADR-0028: 言語切替時に block 表示名 / 検索結果が変わるため、``i18n.language`` を
  // useMemo の依存に含めて再計算する (registry 自体は 1 回 fetch + cache 維持)。
  const lang = i18n.language;
  const blocksByCategory = useMemo(() => {
    if (!data) return {} as Record<string, BlockMetadata[]>;
    const filter = search.trim().toLowerCase();
    const filtered = data.blocks.filter((b) => {
      if (!filter) return true;
      // 両言語 display_name + category + tags を検索対象に (ADR-0028 §(4))
      const names = searchableDisplayNames(b).map((s) => s.toLowerCase());
      if (names.some((n) => n.includes(filter))) return true;
      return (
        b.category.toLowerCase().includes(filter) ||
        b.tags.some((tag) => tag.toLowerCase().includes(filter))
      );
    });
    const grouped: Record<string, BlockMetadata[]> = {};
    for (const b of filtered) {
      const key = b.category;
      if (!grouped[key]) grouped[key] = [];
      grouped[key]!.push(b);
    }
    for (const list of Object.values(grouped)) {
      list.sort((a, b) =>
        localizedDisplayName(a).localeCompare(localizedDisplayName(b)),
      );
    }
    return grouped;
    // ``lang`` 変化で sort 順 / 検索ヒットが変わるため依存に追加
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, search, lang]);

  const handleDragStart = (
    event: React.DragEvent<HTMLDivElement>,
    block: BlockMetadata,
  ): void => {
    event.dataTransfer.setData("application/pyflw-block-type", block.type_path);
    event.dataTransfer.setData(
      "application/pyflw-default-params",
      JSON.stringify(
        buildDefaultParams(block.params_spec, { isContainer: block.is_container }),
      ),
    );
    event.dataTransfer.effectAllowed = "copy";
  };

  // ADR-0029: Library entry の drag-start。``application/pyflw-library-entry-ref``
  // で参照のみを運ぶ (body は drop 経路で fetch、= ペイロード削減)。
  const handleLibraryDragStart = (
    event: React.DragEvent<HTMLDivElement>,
    library: LibraryMetadata,
    entry: LibraryEntryMetadata,
  ): void => {
    event.dataTransfer.setData(
      "application/pyflw-library-entry-ref",
      JSON.stringify({ library: library.name, entry: entry.id }),
    );
    event.dataTransfer.effectAllowed = "copy";
  };

  /** 検索フィルタを library entry に適用する (両言語名 + library 名)。 */
  const filterLibraryEntry = (
    library: LibraryMetadata,
    entry: LibraryEntryMetadata,
  ): boolean => {
    const filter = search.trim().toLowerCase();
    if (!filter) return true;
    const candidates = [
      entry.id,
      entry.display_name,
      entry.display_name_i18n?.en ?? "",
      entry.display_name_i18n?.ja ?? "",
      library.name,
      library.display_name,
    ];
    return candidates.some((c) => c.toLowerCase().includes(filter));
  };

  if (isLoading) {
    return <div className="p-3 text-xs text-slate-500">{t("palette.loading")}</div>;
  }
  if (error) {
    return (
      <div className="p-3 text-xs text-rose-600">
        {t("palette.error", { message: (error as Error).message })}
      </div>
    );
  }
  if (!data) return <div />;

  const visibleCategories = CATEGORY_ORDER.filter(
    (c) => (blocksByCategory[c]?.length ?? 0) > 0,
  );
  const isFiltering = search.trim().length > 0;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-slate-200 p-2.5">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t("palette.search")}
          className="w-full rounded-md border border-slate-300 bg-slate-50 px-2.5 py-1.5 text-xs placeholder:text-slate-400 focus:border-blue-500 focus:bg-white focus:outline-none focus:ring-1 focus:ring-blue-500"
          aria-label={t("palette.search")}
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-1 py-1">
        {visibleCategories.length === 0 &&
        (libraryData?.libraries ?? []).every(
          (lib) => !lib.entries.some((e) => filterLibraryEntry(lib, e)),
        ) ? (
          <div className="p-3 text-xs text-slate-500">{t("palette.no_match")}</div>
        ) : (
          visibleCategories.map((cat) => {
            const isCollapsed = collapsed[cat] && !isFiltering;
            const blocks = blocksByCategory[cat] ?? [];
            return (
              <div key={cat} className="mb-1">
                <button
                  type="button"
                  className="flex w-full items-center gap-1 rounded-md px-2 py-1 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500 hover:bg-slate-100"
                  onClick={() =>
                    setCollapsed((prev) => ({ ...prev, [cat]: !prev[cat] }))
                  }
                  aria-expanded={!isCollapsed}
                >
                  <span className="w-3 text-slate-400">
                    {isCollapsed ? "▸" : "▾"}
                  </span>
                  <span>{t(`palette.category.${cat}` as const)}</span>
                  <span className="ml-auto rounded bg-slate-100 px-1.5 py-px text-[9px] text-slate-500">
                    {blocks.length}
                  </span>
                </button>
                {!isCollapsed && (
                  <div className="grid grid-cols-2 gap-1 px-1 pt-1">
                    {blocks.map((b) => {
                      // ADR-0028: 現在言語で表示名・docstring を取り出す。
                      // ``i18n.language`` 変化で本コンポーネントが再 render され、
                      // useMemo 経由で再計算されるため、ここはストレートに helper を呼ぶ。
                      const dispName = localizedDisplayName(b);
                      const summary = localizedDocstringSummary(b);
                      return (
                        <div
                          key={b.type_path}
                          draggable
                          onDragStart={(e) => handleDragStart(e, b)}
                          // v0.33.2: 角丸を撤廃して角ばった見た目に (ユーザー要望)
                          className="group flex cursor-grab flex-col items-center gap-0.5 border border-transparent px-1 py-1.5 text-center hover:border-blue-300 hover:bg-blue-50/50 active:cursor-grabbing"
                          title={summary ? `${dispName} — ${summary}` : dispName}
                        >
                          <div
                            // v0.33.0: per-block color 撤廃。glyph は CSS で
                            // slate-600 を継承 (= 全カテゴリ統一の中性色)。
                            className="flex h-9 w-9 items-center justify-center border border-slate-200 bg-white p-1 text-slate-600 transition-colors group-hover:border-blue-400"
                          >
                            <BlockGlyph typePath={b.type_path} />
                          </div>
                          <div className="w-full truncate text-[10px] font-medium text-slate-700">
                            {dispName}
                          </div>
                          {b.tags.includes("sm_b") && (
                            <span className="rounded bg-cyan-100 px-1 text-[8px] uppercase tracking-wide text-cyan-700">
                              SM-B
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })
        )}
        {/* ADR-0029: Libraries セクション。組み込み + ユーザー定義の `.flwlib.json` を
            一覧表示する。各 entry は drag で `application/pyflw-library-entry-ref` を運ぶ。 */}
        {(libraryData?.libraries ?? []).map((library) => {
          const libCatKey = `lib::${library.name}`;
          const isCollapsed = collapsed[libCatKey] && !isFiltering;
          const visibleEntries = library.entries.filter((e) =>
            filterLibraryEntry(library, e),
          );
          if (visibleEntries.length === 0) return null;
          const libDispName = localizeName(library, library.name);
          return (
            <div key={libCatKey} className="mb-1">
              <button
                type="button"
                // v0.33.1: 旧版は Library セクション (= .flwlib.json 由来) を
                // violet で囲って built-in と区別していたが、per-block color
                // 撤廃の流れに合わせて Library 側も slate 系 (built-in と同じ)
                // に統一。区別は「Library · 名前」プレフィクスと「LIB」バッジで
                // 視認する。
                className="flex w-full items-center gap-1 rounded-md px-2 py-1 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500 hover:bg-slate-100"
                onClick={() =>
                  setCollapsed((prev) => ({
                    ...prev,
                    [libCatKey]: !prev[libCatKey],
                  }))
                }
                aria-expanded={!isCollapsed}
              >
                <span className="w-3 text-slate-400">
                  {isCollapsed ? "▸" : "▾"}
                </span>
                <span>
                  {t("palette.library_prefix", { defaultValue: "Library" })} ·{" "}
                  {libDispName}
                </span>
                <span className="ml-auto rounded bg-slate-100 px-1.5 py-px text-[9px] text-slate-500">
                  {visibleEntries.length}
                </span>
              </button>
              {!isCollapsed && (
                <div className="grid grid-cols-2 gap-1 px-1 pt-1">
                  {visibleEntries.map((entry) => {
                    const dispName = localizeName(entry, entry.id);
                    return (
                      <div
                        key={`${library.name}::${entry.id}`}
                        draggable
                        onDragStart={(e) =>
                          handleLibraryDragStart(e, library, entry)
                        }
                        // v0.33.2: 角丸撤廃 (built-in と同じ)
                        className="group flex cursor-grab flex-col items-center gap-0.5 border border-transparent px-1 py-1.5 text-center hover:border-blue-300 hover:bg-blue-50/50 active:cursor-grabbing"
                        title={dispName}
                      >
                        <div className="flex h-9 w-9 items-center justify-center border border-slate-200 bg-white p-1 text-slate-600 transition-colors group-hover:border-blue-400">
                          <BlockGlyph typePath="pyflw.subsystems.subsystem.Subsystem" />
                        </div>
                        <div className="w-full truncate text-[10px] font-medium text-slate-700">
                          {dispName}
                        </div>
                        <span className="rounded bg-slate-100 px-1 text-[8px] uppercase tracking-wide text-slate-500">
                          LIB
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
