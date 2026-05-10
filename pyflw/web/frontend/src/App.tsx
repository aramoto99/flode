import { ReactFlowProvider } from "@xyflow/react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { BlockPalette } from "./components/BlockPalette";
import { Breadcrumb } from "./components/Breadcrumb";
import { DiagramCanvas } from "./components/DiagramCanvas";
import { FileBrowser } from "./components/FileBrowser";
import { MenuBar } from "./components/MenuBar";
import { ParameterPanel } from "./components/ParameterPanel";
import { ScopeView } from "./components/ScopeView";
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
  const selectedModelId = useAppStore((s) => s.selectedModelId);
  const selectedFilePath = useAppStore((s) => s.selectedFilePath);
  const scopes = useAppStore((s) => s.scopes);
  const editingModel = useAppStore((s) => s.editingModel);
  const editingPath = useAppStore((s) => s.editingPath);
  // ADR-0041 §論点 8-A: ``selectedFilePath`` か ``selectedModelId`` のどちらかが
  // セットされていればモデルが開かれている扱い。1 セッション 1 経路の前提
  // なので両者は ``selectFilePath`` / ``selectModel`` 内で相互排他。
  const hasOpenedModel = selectedModelId !== null || selectedFilePath !== null;
  const displayName = selectedFilePath ?? selectedModelId ?? "untitled";

  // ADR-0019 §(5): debounce auto-save / Ctrl+S / beforeunload
  useAutoSave();
  // ADR-0041 §論点 11-A: 外部エディタ変更を 5 秒 polling で検知
  useExternalChangesPoll();
  // Simulink 風キーボードショートカット (Ctrl+T/A/C/V, Esc, Enter)
  useShortcuts();

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
          {/* Left: Workspace tree (top) + Library palette (bottom) */}
          <aside className="grid min-h-0 grid-rows-[40%_60%] overflow-hidden border-r border-slate-300 bg-white">
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

          {/* Center: canvas + sim controls + scopes */}
          <main className="flex min-h-0 flex-col overflow-hidden bg-slate-100">
            {hasOpenedModel ? (
              <>
                <Breadcrumb />
                <div className="flex-1 border-b border-slate-300 bg-white">
                  <DiagramCanvas modelId={selectedModelId} />
                </div>
                {/* ADR-0041 §論点 5-A (v0.18.0): legacy `selectedModelId` /
                    File API `selectedFilePath` どちらのモードでも表示。
                    ``useSimulation`` 内部で経路を分岐する。 */}
                <SimulationControls
                  modelId={selectedModelId ?? selectedFilePath ?? ""}
                />
                {Object.entries(scopes).length > 0 && (
                  <div className="flex flex-col gap-2 overflow-y-auto border-t border-slate-300 bg-white p-2">
                    {Object.entries(scopes).map(([scopeId, buffer]) => {
                      const blockType = blockTypeById.get(scopeId) ?? "";
                      // Display は block face に live 表示 → bottom panel には出さない
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
                )}
              </>
            ) : (
              <EmptyState />
            )}
          </main>

          {/* Right: Inspector */}
          <aside className="flex min-h-0 flex-col overflow-y-auto border-l border-slate-300 bg-white">
            <PanelHeader>{t("panel.inspector")}</PanelHeader>
            {hasOpenedModel ? (
              <ParameterPanel modelId={selectedModelId ?? selectedFilePath ?? ""} />
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
      </div>
    </ReactFlowProvider>
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
