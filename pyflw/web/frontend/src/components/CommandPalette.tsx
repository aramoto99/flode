// v0.29.0: コマンドパレット (Ctrl+Shift+P) modal。
//
// 上部に検索 input、下に command list を表示。↑/↓ で選択、Enter で実行、
// Esc で閉じる。modal 化は ADR-0030 の規律に従い `role="dialog"
// aria-modal="true"`。
//
// **a11y**: focus は input に固定、↑↓ で selected index 移動、選択 command の
// label を aria-live で読み上げる必要は無し (= 既存の Modal pattern と同水準)。

import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { listBlockMetadata } from "../api/client";
import {
  type Command,
  buildBlockAddCommands,
  buildCommandRegistry,
  buildRecentFileCommands,
  commandMatches,
  compareCategory,
} from "../lib/commands";
import { useAppStore } from "../store/appStore";

interface CommandPaletteProps {
  /** Modal の open/closed を制御する store action / state。 */
  open: boolean;
  onClose: () => void;
}

export function CommandPalette({
  open,
  onClose,
}: CommandPaletteProps): JSX.Element | null {
  const { t, i18n } = useTranslation();
  // i18next strict-typed ``t()`` は dynamic key を拒否するため、command の
  // labelKey / category key を動的に解決するヘルパー (= 22 個の key を union
  // 化するより runtime warning に任せる方が保守性が高い、ja/en の key 集合
  // 一致は既存 i18n.test.ts でカバー)
  const tDynamic = t as (key: string) => string;
  const [query, setQuery] = useState("");
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  // registry は static + dynamic Recent Files + dynamic Block Add の結合
  // (v0.29.1: Recent / v0.29.2: Block Add)。
  // 静的 registry は invokers 引数を撤去、synthetic keyboard event 経由で
  // 既存 shortcut path を再利用、複数 hook instance 化を避ける。
  const workspaceHash = useAppStore((s) => s.workspaceHash);
  // v0.29.2: block-registry を tanstack-query で fetch (= 60 min cache、
  // 既存 BlockPalette / DiagramCanvas と同じ queryKey で cache 共有)
  const { data: blockRegistry } = useQuery({
    queryKey: ["blocks-registry"],
    queryFn: listBlockMetadata,
    staleTime: 60 * 60 * 1000,
  });
  const registry = useMemo(() => {
    const staticCmds = buildCommandRegistry();
    const recentCmds = buildRecentFileCommands(workspaceHash, 10);
    const blockCmds = blockRegistry
      ? buildBlockAddCommands(blockRegistry.blocks)
      : [];
    return [...staticCmds, ...recentCmds, ...blockCmds];
    // open を deps に含めて、毎回 modal を開くタイミングで Recent を再読込。
    // i18n.language を deps に含めて、言語切替時に Block display_name が新言語で
    // 再 resolve される (= localizedDisplayName が currentLanguage を読む)。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceHash, blockRegistry, open, i18n.language]);

  // open 時に input focus + 検索リセット
  useEffect(() => {
    if (!open) return;
    setQuery("");
    setSelectedIdx(0);
    requestAnimationFrame(() => inputRef.current?.focus());
  }, [open]);

  // commands を label 解決 + 検索フィルタ + category ソート。
  // dynamicSuffix が指定されていれば "${t(labelKey)}: ${dynamicSuffix}" で連結。
  type Entry = { cmd: Command; label: string };
  const entries: Entry[] = useMemo(() => {
    const labeled: Entry[] = registry.map((cmd) => {
      const base = tDynamic(cmd.labelKey);
      const label = cmd.dynamicSuffix
        ? `${base}: ${cmd.dynamicSuffix}`
        : base;
      return { cmd, label };
    });
    const filtered = labeled.filter((e) =>
      commandMatches(e.cmd, e.label, query),
    );
    filtered.sort((a, b) => {
      const c = compareCategory(a.cmd.category, b.cmd.category);
      if (c !== 0) return c;
      return a.label.localeCompare(b.label);
    });
    return filtered;
  }, [registry, query, tDynamic]);

  // selectedIdx を entries 長以内に clamp (= filter で件数減ったとき外を指さない)
  useEffect(() => {
    if (selectedIdx >= entries.length) setSelectedIdx(Math.max(0, entries.length - 1));
  }, [entries.length, selectedIdx]);

  // 選択中行を可視範囲にスクロール
  useEffect(() => {
    const ul = listRef.current;
    if (!ul) return;
    const row = ul.querySelector<HTMLLIElement>(`li[data-idx="${selectedIdx}"]`);
    row?.scrollIntoView({ block: "nearest" });
  }, [selectedIdx]);

  const invokeAt = useCallback(
    async (idx: number): Promise<void> => {
      const entry = entries[idx];
      if (!entry) return;
      if (entry.cmd.enabled && !entry.cmd.enabled()) return;
      onClose();
      try {
        await entry.cmd.action();
      } catch (e) {
        console.error("CommandPalette action failed:", entry.cmd.id, e);
      }
    },
    [entries, onClose],
  );

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-slate-900/30 pt-16"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="w-[560px] max-w-[90vw] overflow-hidden border border-slate-400 bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={t("command.palette.title")}
        data-testid="command-palette"
      >
        {/* 検索 input */}
        <div className="border-b border-slate-200 px-2 py-1.5">
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIdx(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.preventDefault();
                onClose();
              } else if (e.key === "ArrowDown") {
                e.preventDefault();
                setSelectedIdx((i) => Math.min(entries.length - 1, i + 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setSelectedIdx((i) => Math.max(0, i - 1));
              } else if (e.key === "Enter") {
                e.preventDefault();
                void invokeAt(selectedIdx);
              }
            }}
            placeholder={t("command.palette.placeholder")}
            className="w-full border border-slate-300 bg-white px-2 py-1 text-[12px] text-slate-800 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            aria-label={t("command.palette.placeholder")}
          />
        </div>
        {/* command list */}
        <ul
          ref={listRef}
          role="listbox"
          aria-label={t("command.palette.title")}
          className="max-h-[400px] overflow-y-auto"
        >
          {entries.length === 0 && (
            <li className="px-3 py-4 text-center text-[12px] text-slate-400">
              {t("command.palette.no_match")}
            </li>
          )}
          {entries.map((entry, idx) => {
            const isSelected = idx === selectedIdx;
            const enabled = entry.cmd.enabled?.() ?? true;
            return (
              <li
                key={entry.cmd.id}
                data-idx={idx}
                role="option"
                aria-selected={isSelected}
                aria-disabled={!enabled || undefined}
              >
                <button
                  type="button"
                  onClick={() => void invokeAt(idx)}
                  onMouseEnter={() => setSelectedIdx(idx)}
                  disabled={!enabled}
                  className={`flex w-full items-center justify-between px-3 py-1 text-left text-[12px] ${
                    !enabled
                      ? "cursor-not-allowed text-slate-400"
                      : isSelected
                        ? "bg-blue-600 text-white"
                        : "text-slate-700 hover:bg-slate-100"
                  }`}
                  data-testid={`command-${entry.cmd.id}`}
                >
                  <span className="flex items-center gap-2 truncate">
                    <span
                      className={`text-[9px] font-semibold uppercase tracking-wider ${
                        isSelected ? "text-blue-100" : "text-slate-400"
                      }`}
                    >
                      {tDynamic(`command.category.${entry.cmd.category}`)}
                    </span>
                    <span className="truncate">{entry.label}</span>
                  </span>
                  {entry.cmd.shortcut && (
                    <span
                      className={`ml-3 shrink-0 font-mono text-[10px] ${
                        isSelected ? "text-blue-100" : "text-slate-400"
                      }`}
                    >
                      {entry.cmd.shortcut}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
