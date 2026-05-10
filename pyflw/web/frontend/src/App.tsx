import { ReactFlowProvider } from "@xyflow/react";
import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  Group as PanelGroup,
  Panel,
  Separator as PanelResizeHandle,
} from "react-resizable-panels";

import { getWorkspaceInfo } from "./api/filesApi";

import { BlockPalette } from "./components/BlockPalette";
import { Breadcrumb } from "./components/Breadcrumb";
import { DiagramCanvas } from "./components/DiagramCanvas";
import { FileBrowser } from "./components/FileBrowser";
import { MenuBar } from "./components/MenuBar";
import { ParameterPanel } from "./components/ParameterPanel";
import { ScopePanelContainer } from "./components/ScopePanelContainer";
import { ScopeSettingsDialog } from "./components/ScopeSettingsDialog";
import { ScopeView } from "./components/ScopeView";
import { SearchPanel } from "./components/SearchPanel";
import { SimulationControls } from "./components/SimulationControls";
import { StatusBar } from "./components/StatusBar";
import { TabStrip } from "./components/TabStrip";
import { ToastContainer } from "./components/Toast";
import { Toolbar } from "./components/Toolbar";
import { XYGraphView } from "./components/XYGraphView";
import { resolveBlocksAtPath } from "./lib/pathResolver";
import { useAutoSave } from "./lib/useAutoSave";
import { useExternalChangesPoll } from "./lib/useExternalChangesPoll";
import { useShortcuts } from "./lib/useShortcuts";
import { useAppStore } from "./store/appStore";

export default function App(): JSX.Element {
  const { t } = useTranslation();
  const selectedFilePath = useAppStore((s) => s.selectedFilePath);
  const scopes = useAppStore((s) => s.scopes);
  const editingModel = useAppStore((s) => s.editingModel);
  const editingPath = useAppStore((s) => s.editingPath);
  // v0.20.4: Workspace 折りたたみで grid-rows を切替 (= collapsed 時 header 24px
  // のみ、それ以外は 40% 表示)
  const workspaceCollapsed = useAppStore((s) => s.workspaceCollapsed);
  // v0.21.0: ``selectedFilePath`` 一本化 (= legacy selectedModelId 削除済、
  // ADR-0041 §論点 4-A)
  const hasOpenedModel = selectedFilePath !== null;
  const displayName = selectedFilePath ?? "untitled";

  // ADR-0019 §(5): debounce auto-save / Ctrl+S / beforeunload
  useAutoSave();
  // ADR-0041 §論点 11-A: 外部エディタ変更を 5 秒 polling で検知
  useExternalChangesPoll();
  // Simulink 風キーボードショートカット (Ctrl+T/A/C/V, Esc, Enter)
  useShortcuts();

  // ADR-0043 §論点 1-A / §論点 8-A: startup で workspace_info を fetch、
  // localStorage キーの suffix に使う hash を store に保存。Recent Files /
  // タブ復元 / Search panel が参照する。完了後、最後に開いていた active file
  // path (= localStorage `pyflw.last_active.<hash>`) を復元する。
  const setWorkspaceInfo = useAppStore((s) => s.setWorkspaceInfo);
  const openFileInTab = useAppStore((s) => s.openFileInTab);
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const info = await getWorkspaceInfo();
        if (cancelled) return;
        setWorkspaceInfo(info.hash, info.absolute_path);

        // 最後に開いていた active file を復元 (ADR-0043 §論点 8-A)
        const lastKey = `pyflw.last_active.${info.hash}`;
        const lastPath = window.localStorage.getItem(lastKey);
        if (!lastPath) return;
        // 既に store に何か開いていたら復元しない (= ユーザーが手動で何か
        // 開いた直後に restore が走るのを避ける)
        if (useAppStore.getState().selectedFilePath !== null) return;
        try {
          const { getFileContent } = await import("./api/filesApi");
          const data = await getFileContent(lastPath);
          if (cancelled) return;
          openFileInTab(lastPath, data.content, data.mtime, data.etag);
        } catch (e) {
          // 復元失敗 (= 削除された / アクセス不能) は黙って無視、key も削除
          console.warn("Failed to restore last active file:", lastPath, e);
          window.localStorage.removeItem(lastKey);
        }
      } catch (e) {
        console.warn("Failed to fetch workspace_info:", e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [setWorkspaceInfo, openFileInTab]);

  // ADR-0043 §論点 8-A: active file 変更時に localStorage に永続化 (= 次回 startup で復元)
  const activeTabFilePath = useAppStore((s) => s.activeTabFilePath);
  const workspaceHash = useAppStore((s) => s.workspaceHash);
  useEffect(() => {
    if (!workspaceHash) return;
    const key = `pyflw.last_active.${workspaceHash}`;
    if (activeTabFilePath) {
      try {
        window.localStorage.setItem(key, activeTabFilePath);
      } catch {
        // quota / private mode は黙って無視
      }
    } else {
      try {
        window.localStorage.removeItem(key);
      } catch {
        // 同上
      }
    }
  }, [activeTabFilePath, workspaceHash]);

  // 各 scope_id がどのブロック type かを引くためのマップ (現スコープ内のみ)
  const blockTypeById = useMemo(() => {
    if (!editingModel) return new Map<string, string>();
    try {
      const view = resolveBlocksAtPath(editingModel, editingPath);
      const m = new Map<string, string>();
      for (const b of view.blocks) m.set(b.id, b.type);
      return m;
    } catch {
      return new Map<string, string>();
    }
  }, [editingModel, editingPath]);

  return (
    <ReactFlowProvider>
      <div className="grid h-full grid-rows-[auto_auto_auto_auto_1fr_auto] bg-slate-50 font-sans text-[13px] text-slate-900">
        {/* Title bar (window chrome 風) */}
        <div className="flex items-center justify-between border-b border-slate-300 bg-slate-700 px-3 py-1 text-[11px] text-slate-100">
          <div className="flex items-center gap-2">
            <span className="font-semibold tracking-tight">pyflw</span>
            <span className="text-slate-400">—</span>
            <span className="text-slate-300">{displayName}</span>
          </div>
          <span className="text-slate-400">v{__APP_VERSION__}</span>
        </div>

        {/* Menu bar */}
        <MenuBar />

        {/* Toolbar */}
        <Toolbar />

        {/* Tab strip */}
        <TabStrip />

        {/* Main 3-column area */}
        <div className="grid min-h-0 grid-cols-[240px_1fr_280px] overflow-hidden">
          {/* Left: Workspace tree (top) + Library palette (bottom)
              v0.20.4: workspace 折りたたみ時は header (24px) のみで残り全部
              palette、展開時は 40%/60% で分割 */}
          <aside
            className={`grid min-h-0 overflow-hidden border-r border-slate-300 bg-white ${
              workspaceCollapsed
                ? "grid-rows-[24px_1fr]"
                : "grid-rows-[40%_60%]"
            }`}
          >
            {/* ADR-0041 §論点 7-A: workspace tree (`.flw.json` を直接開ける、JupyterLab 流儀) */}
            <div className="flex min-h-0 flex-col overflow-hidden border-b border-slate-300">
              <FileBrowser />
            </div>
            {/* Library palette (Phase 3 で導入、ADR-0019) */}
            <div className="flex min-h-0 flex-col overflow-hidden">
              <PanelHeader>{t("panel.library")}</PanelHeader>
              <div className="min-h-0 flex-1 overflow-hidden">
                <BlockPalette />
              </div>
            </div>
          </aside>

          {/* Center: canvas + sim controls + scopes (drag-resizable split, ADR-0044 §論点 2) */}
          <main className="flex min-h-0 flex-col overflow-hidden bg-slate-100">
            {hasOpenedModel ? (
              <>
                <Breadcrumb />
                {Object.entries(scopes).filter(([id]) => {
                  const t = blockTypeById.get(id) ?? "";
                  return !t.endsWith(".Display");
                }).length > 0 ? (
                  <PanelGroup
                    orientation="vertical"
                    id="pyflw.scope_split"
                    className="flex-1 border-b border-slate-300"
                  >
                    <Panel defaultSize={60} minSize={20}>
                      <div className="h-full bg-white">
                        <DiagramCanvas />
                      </div>
                    </Panel>
                    <PanelResizeHandle className="h-1 bg-slate-200 hover:bg-blue-300 transition-colors" />
                    <Panel defaultSize={40} minSize={10}>
                      <div className="flex h-full flex-col gap-2 overflow-y-auto bg-white p-2">
                        {Object.entries(scopes).map(([scopeId, buffer]) => {
                          const blockType = blockTypeById.get(scopeId) ?? "";
                          if (blockType.endsWith(".Display")) return null;
                          if (blockType.endsWith(".XYGraph")) {
                            return (
                              <XYGraphView
                                key={scopeId}
                                scopeId={scopeId}
                                buffer={buffer}
                              />
                            );
                          }
                          return (
                            <ScopeView
                              key={scopeId}
                              scopeId={scopeId}
                              buffer={buffer}
                            />
                          );
                        })}
                      </div>
                    </Panel>
                  </PanelGroup>
                ) : (
                  <div className="flex-1 border-b border-slate-300 bg-white">
                    <DiagramCanvas />
                  </div>
                )}
                <SimulationControls modelId={selectedFilePath ?? ""} />
              </>
            ) : (
              <EmptyState />
            )}
          </main>

          {/* Right: Inspector */}
          <aside className="flex min-h-0 flex-col overflow-y-auto border-l border-slate-300 bg-white">
            <PanelHeader>{t("panel.inspector")}</PanelHeader>
            {hasOpenedModel ? (
              <ParameterPanel modelId={selectedFilePath ?? ""} />
            ) : (
              <div className="p-3 text-[11px] text-slate-400">
                {t("app.inspector.locked")}
              </div>
            )}
          </aside>
        </div>

        {/* Status bar */}
        <StatusBar />

        {/* ADR-0030: グローバル toast container (fixed positioning なので grid 末尾でも OK)。 */}
        <ToastContainer />

        {/* ADR-0043 §論点 5-A: Search panel (Ctrl+P / Ctrl+Shift+F で開く) */}
        <SearchPanel />

        {/* ADR-0044 §論点 6: floating Scope panel (= Scope ダブルクリックで開く) */}
        <ScopePanelContainer />

        {/* ADR-0044 §論点 4: per-Scope プロット設定 dialog (= gear アイコンで開く) */}
        <GlobalScopeSettingsDialog />
      </div>
    </ReactFlowProvider>
  );
}

function GlobalScopeSettingsDialog(): JSX.Element | null {
  const editingScopeSettingsId = useAppStore((s) => s.editingScopeSettingsId);
  const setEditingScopeSettingsId = useAppStore(
    (s) => s.setEditingScopeSettingsId,
  );
  if (!editingScopeSettingsId) return null;
  return (
    <ScopeSettingsDialog
      scopeId={editingScopeSettingsId}
      onClose={() => setEditingScopeSettingsId(null)}
    />
  );
}

function PanelHeader({ children }: { children: React.ReactNode }): JSX.Element {
  return (
    <div className="flex h-6 items-center border-b border-slate-200 bg-slate-100 px-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
      {children}
    </div>
  );
}

function EmptyState(): JSX.Element {
  const { t } = useTranslation();
  return (
    <div className="flex flex-1 items-center justify-center bg-slate-50">
      <div className="max-w-sm rounded border border-slate-200 bg-white px-6 py-5 text-center text-[12px] text-slate-600">
        <div className="mb-2 font-semibold text-slate-700">{t("app.empty.title")}</div>
        <div className="text-slate-500">
          {t("app.empty.hint_new")}
          <br />
          {t("app.empty.hint_open")}
        </div>
      </div>
    </div>
  );
}
