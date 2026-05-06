// ADR-0019 §(3): ブロックパレット UI。
// カテゴリ折りたたみ + 検索 + drag-start で `application/pyflw-block-type` を data
// transfer に積む。

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { listBlockMetadata } from "../api/client";
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

const CATEGORY_LABEL: Record<string, string> = {
  sources: "Sources",
  mathops: "Math",
  continuous: "Continuous",
  discrete: "Discrete",
  logic: "Logic",
  routing: "Routing",
  sinks: "Sinks",
  subsystems: "Subsystems",
  uncategorized: "Other",
};

export function BlockPalette(): JSX.Element {
  const { data, isLoading, error } = useQuery({
    queryKey: ["blocks-registry"],
    queryFn: listBlockMetadata,
    staleTime: 60 * 60 * 1000, // 1h
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
    event: React.DragEvent<HTMLLIElement>,
    block: BlockMetadata,
  ): void => {
    event.dataTransfer.setData("application/pyflw-block-type", block.type_path);
    event.dataTransfer.setData(
      "application/pyflw-default-params",
      JSON.stringify(buildDefaultParams(block.params_spec)),
    );
    event.dataTransfer.effectAllowed = "copy";
  };

  if (isLoading) {
    return (
      <div className="p-3 text-xs text-gray-500">Loading palette...</div>
    );
  }
  if (error) {
    return (
      <div className="p-3 text-xs text-red-600">
        Failed to load palette: {(error as Error).message}
      </div>
    );
  }
  if (!data) return <div />;

  const visibleCategories = CATEGORY_ORDER.filter(
    (c) => (blocksByCategory[c]?.length ?? 0) > 0,
  );
  const isFiltering = search.trim().length > 0;

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-gray-200 p-2">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search blocks..."
          className="w-full rounded border border-gray-300 px-2 py-1 text-xs focus:border-blue-500 focus:outline-none"
          aria-label="Search blocks"
        />
      </div>
      <div className="flex-1 overflow-y-auto">
        {visibleCategories.length === 0 ? (
          <div className="p-3 text-xs text-gray-500">No blocks match.</div>
        ) : (
          visibleCategories.map((cat) => {
            const isCollapsed = collapsed[cat] && !isFiltering;
            const blocks = blocksByCategory[cat] ?? [];
            return (
              <div key={cat} className="border-b border-gray-100">
                <button
                  type="button"
                  className="flex w-full items-center gap-1 bg-gray-50 px-2 py-1 text-left text-xs font-medium hover:bg-gray-100"
                  onClick={() =>
                    setCollapsed((prev) => ({ ...prev, [cat]: !prev[cat] }))
                  }
                  aria-expanded={!isCollapsed}
                >
                  <span className="w-3 text-gray-500">
                    {isCollapsed ? "▶" : "▼"}
                  </span>
                  <span>{CATEGORY_LABEL[cat] ?? cat}</span>
                  <span className="ml-auto text-[10px] text-gray-400">
                    {blocks.length}
                  </span>
                </button>
                {!isCollapsed && (
                  <ul>
                    {blocks.map((b) => (
                      <li
                        key={b.type_path}
                        draggable
                        onDragStart={(e) => handleDragStart(e, b)}
                        className="flex cursor-grab items-center gap-2 px-3 py-1 text-xs hover:bg-blue-50 active:cursor-grabbing"
                        title={b.docstring_summary || b.type_path}
                      >
                        <span
                          className="inline-block h-2 w-2 rounded-full"
                          style={{ backgroundColor: b.color }}
                          aria-hidden
                        />
                        <span className="flex-1 truncate">
                          {b.display_name}
                        </span>
                        {b.tags.includes("sm_b") && (
                          <span className="rounded bg-cyan-100 px-1 text-[9px] uppercase text-cyan-700">
                            SM-B
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
