// クイックブロック検索ポップアップ。空ペーンをダブルクリックで起動し、
// インクリメンタル検索で hit したブロックを Enter / クリックでカーソル位置に追加する。
// リファレンスツールの Quick Insert 機能に相当する操作。

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { listBlockMetadata } from "../api/client";
import { BlockGlyph } from "../lib/blockGlyphs";
import {
  localizedDisplayName,
  searchableDisplayNames,
} from "../lib/blockI18n";
import { generateUniqueId, buildDefaultParams } from "../lib/idGenerator";
import { resolveBlocksAtPath } from "../lib/pathResolver";
import { addBlockToEditing, useAppStore } from "../store/appStore";

interface QuickAddProps {
  /** ポップアップ画面座標 (clientX/clientY)。クリック位置周辺に置く。 */
  screenX: number;
  screenY: number;
  /** 追加するブロックのフロー座標 (= screenToFlowPosition で変換済み)。 */
  flowX: number;
  flowY: number;
  onClose: () => void;
}

const MAX_RESULTS = 24;

/** スコア付き fuzzy match。検索語の文字が順序通りに display_name に出現すればヒット。 */
function fuzzyScore(query: string, label: string): number | null {
  if (!query) return 0;
  const q = query.toLowerCase();
  const l = label.toLowerCase();
  // 連続マッチを優遇 (= "Sum" は "Sum" を最上位、 "Subsystem" を下位に)
  const direct = l.indexOf(q);
  if (direct >= 0) {
    // 完全一致を最優先、prefix を次点
    if (l === q) return 1000;
    if (direct === 0) return 500 - l.length;
    return 200 - direct - l.length * 0.1;
  }
  // 部分文字 fuzzy: q の各文字が順番に l に出れば OK
  let li = 0;
  for (const ch of q) {
    const found = l.indexOf(ch, li);
    if (found < 0) return null;
    li = found + 1;
  }
  return 50 - li;
}

export function QuickAdd({
  screenX,
  screenY,
  flowX,
  flowY,
  onClose,
}: QuickAddProps): JSX.Element | null {
  // ADR-0028: ``useTranslation`` 経由で ``i18n.language`` 変化を購読し、
  // 言語切替時に再 render される。表示文字列は ``localizedDisplayName(b)`` で
  // render 時に最新言語を読むため、useMemo の deps に lang を入れる必要は
  // ない (= 検索結果リスト itself は両言語 index で安定、表示だけが切り替わる)。
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [activeIdx, setActiveIdx] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ["blocks-registry"],
    queryFn: listBlockMetadata,
    staleTime: 60 * 60 * 1000,
  });

  // 起動時にフォーカス
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // クリック outside で閉じる
  useEffect(() => {
    const handler = (e: MouseEvent): void => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose]);

  const results = useMemo(() => {
    if (!data) return [];
    const scored: { score: number; meta: (typeof data.blocks)[number] }[] = [];
    for (const m of data.blocks) {
      // ADR-0028: 両言語の display_name で fuzzy 検索 (= ja 環境で "sum" 入力でも
      // "加算" がヒット、リファレンスツール経験者向けセーフネット)。スコアは最大値を採用。
      const candidates = searchableDisplayNames(m);
      let best: number | null = null;
      for (const cand of candidates) {
        const s = fuzzyScore(query.trim(), cand);
        if (s !== null && (best === null || s > best)) best = s;
      }
      if (best === null) continue;
      scored.push({ score: best, meta: m });
    }
    scored.sort((a, b) => b.score - a.score);
    return scored.slice(0, MAX_RESULTS).map((s) => s.meta);
    // 検索結果リストは両言語 index で安定 (= 言語切替で順番が変わらない)。
    // 表示文字列は下記 render の ``localizedDisplayName(m)`` が ``useTranslation``
    // 購読により言語切替時の再 render で更新する。
  }, [data, query]);

  // クエリが変わったら active を先頭に戻す
  useEffect(() => {
    setActiveIdx(0);
  }, [query]);

  const insert = (meta: (typeof results)[number]): void => {
    const state = useAppStore.getState();
    const model = state.editingModel;
    if (!model) return;
    let existingIds: Set<string>;
    try {
      const view = resolveBlocksAtPath(model, state.editingPath);
      existingIds = new Set(view.blocks.map((b) => b.id));
    } catch {
      return;
    }
    const newId = generateUniqueId(meta.type_path, existingIds);
    addBlockToEditing(
      {
        id: newId,
        type: meta.type_path,
        params: buildDefaultParams(meta.params_spec, {
          isContainer: meta.is_container,
        }),
      },
      { x: flowX, y: flowY },
    );
    state.selectNode(newId);
    onClose();
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>): void => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onClose();
    } else if (e.key === "Enter") {
      e.preventDefault();
      e.stopPropagation();
      const sel = results[activeIdx];
      if (sel) insert(sel);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, Math.max(0, results.length - 1)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(0, i - 1));
    }
  };

  // ポップアップ位置: 画面 4 端からはみ出さないようにクランプ
  // (右端 / 下端は popup サイズ + 8px 余白、左端 / 上端は 0 が下限)
  const POPUP_W = 320;
  const POPUP_H = 360;
  const left = Math.max(0, Math.min(screenX, window.innerWidth - POPUP_W - 8));
  const top = Math.max(0, Math.min(screenY, window.innerHeight - POPUP_H - 8));

  return (
    <div
      ref={containerRef}
      className="absolute z-40 flex flex-col overflow-hidden rounded-md border border-slate-300 bg-white text-[12px] shadow-2xl"
      style={{ left, top, width: POPUP_W, height: POPUP_H }}
      role="dialog"
      aria-label={t("quickadd.aria")}
    >
      <input
        ref={inputRef}
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder={t("quickadd.placeholder")}
        className="border-b border-slate-200 bg-slate-50 px-3 py-2 text-[12px] focus:bg-white focus:outline-none"
      />
      {isLoading ? (
        <div className="p-3 text-slate-500">{t("quickadd.loading")}</div>
      ) : results.length === 0 ? (
        <div className="p-3 text-slate-400">{t("quickadd.no_match")}</div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto py-0.5">
          {results.map((m, i) => (
            <button
              key={m.type_path}
              type="button"
              onMouseEnter={() => setActiveIdx(i)}
              onClick={() => insert(m)}
              className={`flex w-full items-center gap-2 px-2 py-1 text-left ${
                i === activeIdx
                  ? "bg-blue-600 text-white"
                  : "text-slate-700 hover:bg-slate-100"
              }`}
            >
              <div
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded border ${
                  i === activeIdx
                    ? "border-blue-300 bg-white/20"
                    : "border-slate-200 bg-white"
                }`}
                // v0.33.0: per-block color 撤廃、active 行は白、それ以外は slate-600 固定
                style={{ color: i === activeIdx ? "white" : "#475569" }}
              >
                <BlockGlyph typePath={m.type_path} />
              </div>
              <div className="min-w-0 flex-1 truncate">
                <span className="font-medium">{localizedDisplayName(m)}</span>
                <span
                  className={`ml-2 text-[10px] ${
                    i === activeIdx ? "text-blue-100" : "text-slate-400"
                  }`}
                >
                  {m.category}
                </span>
              </div>
            </button>
          ))}
        </div>
      )}
      <div className="border-t border-slate-200 bg-slate-50 px-2 py-1 text-[10px] text-slate-500">
        {t("quickadd.footer_hint")}
      </div>
    </div>
  );
}
