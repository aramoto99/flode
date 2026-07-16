// ADR-0043 §論点 5-A: ワークスペース内 検索パネル。
// ADR-0051 §(2-A) で **overlay → sidebar mode inline 描画** に refactor。
// activity bar (= ADR-0051 §(1)) で sidebar mode を ``search`` に切替するか、
// ``Ctrl+P`` / ``Ctrl+Shift+F`` shortcut で同時に mode 切替 + kind 設定。
//
// Search 結果クリックでファイルを開く (= ``openFileInTab``、Recent にも追加)。
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
import { dialog } from "../lib/dialogService";
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

export function SearchPanel(): JSX.Element {
  const { t } = useTranslation();
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

  // ADR-0051 §(2-A): Ctrl+P / Ctrl+Shift+F (= useShortcuts から dispatch) で
  // kind を切替えながら input に focus。sidebar mode は外側 (= App.tsx の
  // shortcut handler) で ``search`` に切替済の前提。
  useEffect(() => {
    const handler = (e: Event): void => {
      const ce = e as CustomEvent<{ kind: SearchKind }>;
      const k = ce.detail?.kind ?? "path";
      setState((s) => ({ ...s, kind: k }));
      // input が描画された後 focus (= microtask + RAF で確実に)
      requestAnimationFrame(() => inputRef.current?.focus());
    };
    window.addEventListener("pyflw:open-search", handler);
    return () => window.removeEventListener("pyflw:open-search", handler);
  }, []);

  // q / kind 変更 → debounced search (= 200ms)
  useEffect(() => {
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
  }, [state.q, state.kind]);

  const handleResultClick = async (path: string): Promise<void> => {
    try {
      const data = await getFileContent(path);
      openFileInTab(path, data.content, data.mtime, data.etag);
      if (workspaceHash) addRecentFile(workspaceHash, path);
      // ADR-0051 §(2-A): sidebar mode は維持 (= 連続検索 UX、ユーザーが
      // 明示的に file mode に戻すまで Search のまま)
    } catch (e) {
      console.error("Failed to open file from search:", path, e);
      await dialog.alert(
        t("filebrowser.open_failed", "Failed to open {{path}}: {{message}}", {
          path,
          message: (e as Error).message,
        }),
      );
    }
  };

  return (
    <div
      className="flex h-full w-full flex-col overflow-hidden bg-white"
      data-testid="sidebar-search-panel"
      aria-label={t("search.title", "Search")}
    >
      {/* ヘッダー (PanelHeader 風) */}
      <div className="flex h-6 shrink-0 items-center border-b border-slate-200 bg-slate-100 px-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        {t("activity.search")}
      </div>
      {/* 入力 + kind 切替 */}
      <div className="flex flex-col gap-1 border-b border-slate-200 p-2">
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
          className="w-full border border-slate-400 bg-white px-1.5 py-0.5 text-[11px] text-slate-800 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        <div className="flex overflow-hidden border border-slate-300 text-[10px]">
          <button
            type="button"
            onClick={() => setState((s) => ({ ...s, kind: "path" }))}
            className={`flex-1 px-1.5 py-0.5 ${state.kind === "path" ? "bg-blue-600 text-white" : "bg-slate-50 text-slate-600 hover:bg-slate-100"}`}
          >
            {t("search.kind_path", "Path")}
          </button>
          <button
            type="button"
            onClick={() => setState((s) => ({ ...s, kind: "content" }))}
            className={`flex-1 px-1.5 py-0.5 ${state.kind === "content" ? "bg-blue-600 text-white" : "bg-slate-50 text-slate-600 hover:bg-slate-100"}`}
          >
            {t("search.kind_content", "Content")}
          </button>
        </div>
      </div>
      {/* 結果 list */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {state.error && (
          <div className="px-2 py-1 text-[11px] text-rose-600">
            {t("search.error", "Error")}: {state.error}
          </div>
        )}
        {state.loading && (
          <div className="px-2 py-1 text-[11px] text-slate-500">
            {t("search.loading", "Searching...")}
          </div>
        )}
        {!state.loading && state.q.trim() === "" && (
          <div className="px-2 py-3 text-center text-[11px] text-slate-400">
            {t("search.hint", "Type to search.")}
          </div>
        )}
        {!state.loading &&
          state.q.trim() !== "" &&
          state.results.length === 0 &&
          !state.error && (
            <div className="px-2 py-3 text-center text-[11px] text-slate-500">
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
                  className="flex w-full flex-col items-start gap-0.5 border-b border-slate-100 px-2 py-1 text-left hover:bg-blue-50"
                >
                  <span className="font-mono text-[11px] text-slate-800">
                    {r.path}
                    {r.line_no !== undefined && (
                      <span className="ml-1 text-slate-400">:{r.line_no}</span>
                    )}
                  </span>
                  {r.line_content && (
                    <span className="font-mono text-[10px] text-slate-500">
                      {r.line_content}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
        {state.truncated && (
          <div className="border-t border-slate-200 bg-slate-50 px-2 py-1 text-[10px] text-slate-500">
            {t("search.truncated", "Showing first {{n}} results.", {
              n: state.results.length,
            })}
          </div>
        )}
      </div>
    </div>
  );
}
