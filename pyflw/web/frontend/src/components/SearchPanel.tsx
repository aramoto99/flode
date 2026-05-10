// ADR-0043 §論点 5-A: ワークスペース内 検索パネル。
//
// VSCode 風の overlay panel として実装 (= 左サイドバーに専用タブを差し込む案は
// 既存 layout への影響が大きいので保留、MVP は overlay)。Ctrl+P / Ctrl+Shift+F
// で開く (= ``useShortcuts`` から ``window.dispatchEvent("pyflw:open-search",
// {detail: {kind}})``)。Escape / 外側クリックで閉じる。
//
// 結果クリックでファイルを開く (= ``openFileInTab``、Recent にも追加)。
// content kind の場合は line_no も保持するが、現状はファイル全体を開くだけ
// (= 行ジャンプは将来 enhancement)。

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type SearchKind,
  type SearchResultEntry,
  getFileContent,
  searchFiles,
} from "../api/filesApi";
import { addRecentFile } from "../lib/recentFiles";
import { useAppStore } from "../store/appStore";

interface SearchState {
  q: string;
  kind: SearchKind;
  results: SearchResultEntry[];
  truncated: boolean;
  loading: boolean;
  error: string | null;
}

const _DEFAULT_LIMIT = 100;

export function SearchPanel(): JSX.Element | null {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<SearchState>({
    q: "",
    kind: "path",
    results: [],
    truncated: false,
    loading: false,
    error: null,
  });
  const inputRef = useRef<HTMLInputElement>(null);

  const openFileInTab = useAppStore((s) => s.openFileInTab);
  const workspaceHash = useAppStore((s) => s.workspaceHash);

  // ADR-0043 §論点 5-A: Ctrl+P / Ctrl+Shift+F (= useShortcuts から dispatch) で
  // panel を開く。kind は detail から取得、フォーカスを input に飛ばす。
  useEffect(() => {
    const handler = (e: Event): void => {
      const ce = e as CustomEvent<{ kind: SearchKind }>;
      const k = ce.detail?.kind ?? "path";
      setOpen(true);
      setState((s) => ({ ...s, kind: k, q: "", results: [], error: null }));
      // input が描画された後 focus (= microtask + RAF で確実に)
      requestAnimationFrame(() => inputRef.current?.focus());
    };
    window.addEventListener("pyflw:open-search", handler);
    return () => window.removeEventListener("pyflw:open-search", handler);
  }, []);

  // Escape で close
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent): void => {
      if (e.key === "Escape") {
        e.preventDefault();
        setOpen(false);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open]);

  // q / kind 変更 → debounced search (= 200ms)
  useEffect(() => {
    if (!open) return;
    const trimmed = state.q.trim();
    if (trimmed.length === 0) {
      setState((s) => ({ ...s, results: [], truncated: false, error: null }));
      return;
    }
    const handle = window.setTimeout(() => {
      void (async () => {
        setState((s) => ({ ...s, loading: true, error: null }));
        try {
          const resp = await searchFiles(trimmed, state.kind, _DEFAULT_LIMIT);
          setState((s) => ({
            ...s,
            results: resp.results,
            truncated: resp.truncated,
            loading: false,
          }));
        } catch (e) {
          setState((s) => ({
            ...s,
            loading: false,
            error: (e as Error).message,
          }));
        }
      })();
    }, 200);
    return () => window.clearTimeout(handle);
  }, [state.q, state.kind, open]);

  const handleResultClick = async (path: string): Promise<void> => {
    try {
      const data = await getFileContent(path);
      openFileInTab(path, data.content, data.mtime, data.etag);
      if (workspaceHash) addRecentFile(workspaceHash, path);
      setOpen(false);
    } catch (e) {
      console.error("Failed to open file from search:", path, e);
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-slate-900/30 pt-20"
      onClick={() => setOpen(false)}
    >
      <div
        className="w-[640px] max-w-[90vw] overflow-hidden rounded-lg border border-slate-300 bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={t("search.title", "Search")}
      >
        <div className="flex items-center gap-2 border-b border-slate-200 px-3 py-2">
          <input
            ref={inputRef}
            type="text"
            value={state.q}
            onChange={(e) => setState((s) => ({ ...s, q: e.target.value }))}
            placeholder={
              state.kind === "path"
                ? t("search.placeholder_path", "Search files by path...")
                : t("search.placeholder_content", "Search files by content...")
            }
            className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none"
          />
          <div className="flex overflow-hidden rounded border border-slate-300 text-[11px]">
            <button
              type="button"
              onClick={() => setState((s) => ({ ...s, kind: "path" }))}
              className={`px-2 py-1 ${state.kind === "path" ? "bg-blue-600 text-white" : "bg-slate-50 text-slate-600 hover:bg-slate-100"}`}
            >
              {t("search.kind_path", "Path")}
            </button>
            <button
              type="button"
              onClick={() => setState((s) => ({ ...s, kind: "content" }))}
              className={`px-2 py-1 ${state.kind === "content" ? "bg-blue-600 text-white" : "bg-slate-50 text-slate-600 hover:bg-slate-100"}`}
            >
              {t("search.kind_content", "Content")}
            </button>
          </div>
        </div>
        <div className="max-h-[400px] overflow-y-auto">
          {state.error && (
            <div className="px-3 py-2 text-[12px] text-rose-600">
              {t("search.error", "Error")}: {state.error}
            </div>
          )}
          {state.loading && (
            <div className="px-3 py-2 text-[12px] text-slate-500">
              {t("search.loading", "Searching...")}
            </div>
          )}
          {!state.loading && state.q.trim() === "" && (
            <div className="px-3 py-4 text-center text-[12px] text-slate-400">
              {t("search.hint", "Type to search.")}
            </div>
          )}
          {!state.loading && state.q.trim() !== "" && state.results.length === 0 && !state.error && (
            <div className="px-3 py-4 text-center text-[12px] text-slate-500">
              {t("search.no_result", "No matches.")}
            </div>
          )}
          {state.results.length > 0 && (
            <ul>
              {state.results.map((r, i) => (
                <li key={`${r.path}:${r.line_no ?? i}`}>
                  <button
                    type="button"
                    onClick={() => void handleResultClick(r.path)}
                    className="flex w-full flex-col items-start gap-0.5 border-b border-slate-100 px-3 py-1.5 text-left hover:bg-blue-50"
                  >
                    <span className="font-mono text-[12px] text-slate-800">
                      {r.path}
                      {r.line_no !== undefined && (
                        <span className="ml-1 text-slate-400">
                          :{r.line_no}
                        </span>
                      )}
                    </span>
                    {r.line_content && (
                      <span className="font-mono text-[11px] text-slate-500">
                        {r.line_content}
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {state.truncated && (
            <div className="border-t border-slate-200 bg-slate-50 px-3 py-1 text-[11px] text-slate-500">
              {t("search.truncated", "Showing first {{n}} results.", {
                n: state.results.length,
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
