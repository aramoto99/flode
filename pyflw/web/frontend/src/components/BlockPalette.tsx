// ADR-0019 §(3) + UI 刷新: ブロックパレット。
// 各エントリに block 種別固有の SVG glyph プレビューを表示する Simulink Library
// Browser 風の見た目。検索 + カテゴリ折りたたみ。drag-start で
// `application/pyflw-block-type` を data transfer に積む。

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { listBlockMetadata } from "../api/client";
import { BlockGlyph } from "../lib/blockGlyphs";
import { buildDefaultParams } from "../lib/idGenerator";
import type { BlockMetadata } from "../types/api";

const CATEGORY_ORDER = [
  "sources",
  "mathops",
  "continuous",
  "discrete",
  "logic",
  "routing",
  "sinks",
  "subsystems",
  "uncategorized",
] as const;

export function BlockPalette(): JSX.Element {
  const { t } = useTranslation();
  const { data, isLoading, error } = useQuery({
    queryKey: ["blocks-registry"],
    queryFn: listBlockMetadata,
    staleTime: 60 * 60 * 1000,
  });
  const [search, setSearch] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const blocksByCategory = useMemo(() => {
    if (!data) return {} as Record<string, BlockMetadata[]>;
    const filter = search.trim().toLowerCase();
    const filtered = data.blocks.filter((b) => {
      if (!filter) return true;
      return (
        b.display_name.toLowerCase().includes(filter) ||
        b.category.toLowerCase().includes(filter) ||
        b.tags.some((t) => t.toLowerCase().includes(filter))
      );
    });
    const grouped: Record<string, BlockMetadata[]> = {};
    for (const b of filtered) {
      const key = b.category;
      if (!grouped[key]) grouped[key] = [];
      grouped[key]!.push(b);
    }
    for (const list of Object.values(grouped)) {
      list.sort((a, b) => a.display_name.localeCompare(b.display_name));
    }
    return grouped;
  }, [data, search]);

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
        {visibleCategories.length === 0 ? (
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
                    {blocks.map((b) => (
                      <div
                        key={b.type_path}
                        draggable
                        onDragStart={(e) => handleDragStart(e, b)}
                        className="group flex cursor-grab flex-col items-center gap-0.5 rounded-md border border-transparent px-1 py-1.5 text-center hover:border-blue-300 hover:bg-blue-50/50 active:cursor-grabbing"
                        title={
                          b.docstring_summary
                            ? `${b.display_name} — ${b.docstring_summary}`
                            : b.display_name
                        }
                      >
                        <div
                          className="flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 bg-white p-1 transition-colors group-hover:border-blue-400"
                          style={{ color: b.color }}
                        >
                          <BlockGlyph typePath={b.type_path} />
                        </div>
                        <div className="w-full truncate text-[10px] font-medium text-slate-700">
                          {b.display_name}
                        </div>
                        {b.tags.includes("sm_b") && (
                          <span className="rounded bg-cyan-100 px-1 text-[8px] uppercase tracking-wide text-cyan-700">
                            SM-B
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
