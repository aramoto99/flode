// ADR-0051 §(3): Workspace JupyterLab Stage 2 = Launcher。
// ファイル未選択時 (= ``hasOpenedModel === false``) に表示される画面。
// 旧 ``EmptyState`` (= 単純な「ファイルが開かれていません」メッセージ) を置換。
//
// 構成:
// - Start セクション = New / Open の 2 tile (= 小型 SecondaryButton)
// - Recent セクション = ``readRecentFiles(workspaceHash)`` 上位 5 件の list
//   - クリックで該当ファイルを開く
//   - 「Show all...」リンクで sidebar mode を `file` に切替
//
// **a11y**: tile / list item とも `<button>` ベース、`aria-label` 付き。
// **design system**: memory `feedback_simulink_native_ui` に従い、大型カード /
// pill button は禁止。Property Inspector primitives 寄りの shape (= 60〜80 px
// 幅 + 32 px 高さの 小型ボタン)。

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";

import {
  getFileContent,
  nextUntitledFilePath,
  putFileContent,
} from "../api/filesApi";
import { readRecentFiles } from "../lib/recentFiles";
import { useAppStore } from "../store/appStore";
import type { FlwModel } from "../types/api";

// ADR-0036 + ADR-0039 (= MenuBar.tsx と同期): 新規モデル schema_version。
const CURRENT_SCHEMA_VERSION = "0.8";

function emptyModel(name: string): FlwModel {
  return {
    schema_version: CURRENT_SCHEMA_VERSION,
    metadata: { name, created_at: new Date().toISOString(), tool: "pyflw" },
    simulator: {
      t_end: 10,
      dt: 0.01,
      solver: "RK45",
      rtol: 1e-6,
      atol: 1e-9,
      dt_base: null,
    },
    blocks: [],
    connections: [],
    layout: {},
  };
}

const RECENT_DISPLAY_LIMIT = 5;

export function Launcher(): JSX.Element {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const workspaceHash = useAppStore((s) => s.workspaceHash);
  const openFileInTab = useAppStore((s) => s.openFileInTab);
  const setSidebarMode = useAppStore((s) => s.setSidebarMode);
  const setWorkspaceCollapsed = useAppStore((s) => s.setWorkspaceCollapsed);

  // Recent は workspaceHash の変化で再読み込み (= 別ワークスペースに切替時に
  // Recent も切替)、initial load + workspaceHash 変化のたびに refresh
  const [recent, setRecent] = useState<string[]>([]);
  useEffect(() => {
    if (!workspaceHash) {
      setRecent([]);
      return;
    }
    setRecent(readRecentFiles(workspaceHash).slice(0, RECENT_DISPLAY_LIMIT));
  }, [workspaceHash]);

  const handleNew = async (): Promise<void> => {
    try {
      const path = await nextUntitledFilePath();
      const empty = emptyModel(path.replace(/\.flw\.json$/, ""));
      await putFileContent(path, empty);
      const data = await getFileContent(path);
      openFileInTab(path, data.content, data.mtime, data.etag);
      await queryClient.invalidateQueries({ queryKey: ["files-tree"] });
    } catch (e) {
      console.error("Launcher: New file failed:", e);
      window.alert(`Create failed: ${(e as Error).message}`);
    }
  };

  const handleOpen = (): void => {
    // FileBrowser に遷移 (= activity bar Search mode の挙動と同じく、
    // sidebar mode を file に切替 + sidebar を open)
    setSidebarMode("file");
    setWorkspaceCollapsed(false);
  };

  const handleOpenRecent = async (path: string): Promise<void> => {
    try {
      const data = await getFileContent(path);
      openFileInTab(path, data.content, data.mtime, data.etag);
    } catch (e) {
      console.error("Launcher: Open recent failed:", path, e);
      window.alert(`Open failed: ${(e as Error).message}`);
    }
  };

  return (
    <div
      className="flex h-full w-full items-center justify-center bg-slate-50"
      data-testid="launcher"
    >
      <div className="flex w-full max-w-md flex-col gap-4 border border-slate-300 bg-white p-6 text-[12px] text-slate-700 shadow-sm">
        {/* タイトル */}
        <div className="flex items-baseline gap-2">
          <span className="text-[16px] font-semibold tracking-tight text-slate-800">
            pyflw
          </span>
          <span className="text-[11px] text-slate-400">v{__APP_VERSION__}</span>
        </div>

        {/* Start セクション */}
        <section>
          <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            {t("launcher.section.start")}
          </div>
          <div className="flex gap-2">
            <LauncherTile
              label={t("launcher.tile.new")}
              onClick={() => void handleNew()}
              testid="launcher-tile-new"
            />
            <LauncherTile
              label={t("launcher.tile.open")}
              onClick={handleOpen}
              testid="launcher-tile-open"
            />
          </div>
        </section>

        {/* Recent セクション */}
        <section>
          <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            {t("launcher.section.recent")}
          </div>
          {recent.length === 0 ? (
            <div className="text-[11px] text-slate-400">
              {t("launcher.recent.empty")}
            </div>
          ) : (
            <ul role="list" className="flex flex-col">
              {recent.map((path) => (
                <li key={path}>
                  <button
                    type="button"
                    onClick={() => void handleOpenRecent(path)}
                    className="flex w-full items-center px-1 py-1 text-left font-mono text-[11px] text-slate-700 hover:bg-slate-100"
                    title={path}
                  >
                    <span className="truncate">{path}</span>
                  </button>
                </li>
              ))}
              <li>
                <button
                  type="button"
                  onClick={handleOpen}
                  className="mt-1 self-start text-[11px] text-blue-600 hover:underline"
                >
                  {t("launcher.recent.show_all")}
                </button>
              </li>
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}

function LauncherTile({
  label,
  onClick,
  testid,
}: {
  label: string;
  onClick: () => void;
  testid: string;
}): JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      data-testid={testid}
      className="flex h-8 min-w-[70px] items-center justify-center border border-slate-400 bg-white px-3 text-[11px] text-slate-700 hover:bg-slate-100"
    >
      {label}
    </button>
  );
}
