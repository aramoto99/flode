import { ReactFlowProvider } from "@xyflow/react";
import { useEffect, useMemo, useRef, useState } from "react";
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
  const inspectorCollapsed = useAppStore((s) => s.inspectorCollapsed);
  const setInspectorCollapsed = useAppStore((s) => s.setInspectorCollapsed);
  const leftSidebarWidth = useAppStore((s) => s.leftSidebarWidth);
  const setLeftSidebarWidth = useAppStore((s) => s.setLeftSidebarWidth);
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

  // v0.26.12: Display 以外で実体のある Scope / XYGraph のリスト。
  // PanelGroup を常時描画 + scope エリアは ``hasVisibleScopes`` でのみ描画 (=
  // DiagramCanvas を remount させずビューポートを保持するため)。
  const visibleScopeEntries = useMemo(
    () =>
      Object.entries(scopes).filter(([id]) => {
        const t = blockTypeById.get(id) ?? "";
        return !t.endsWith(".Display");
      }),
    [scopes, blockTypeById],
  );
  const hasVisibleScopes = visibleScopeEntries.length > 0;

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

        {/* Main 3-column area (v0.26.10: 左 sidebar 横幅は manual drag handle で
            管理、grid template columns に直接埋め込む。react-resizable-panels の
            horizontal は grid 内で動作不安定だったので自前実装に切替)。 */}
        <div
          className="grid min-h-0 overflow-hidden"
          style={{
            gridTemplateColumns: `${leftSidebarWidth}px 5px 1fr ${inspectorCollapsed ? "24px" : "280px"}`,
          }}
        >
          {/* Left: Workspace tree (top) + Library palette (bottom) */}
          <aside className="flex min-h-0 flex-col overflow-hidden border-r border-slate-300 bg-white">
            {workspaceCollapsed ? (
              // 折りたたみ時: FileBrowser 24 px header + Library が残り全部
              <>
                <div className="flex min-h-0 flex-col overflow-hidden border-b border-slate-300">
                  <FileBrowser />
                </div>
                <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                  <PanelHeader>{t("panel.library")}</PanelHeader>
                  <div className="min-h-0 flex-1 overflow-hidden">
                    <BlockPalette />
                  </div>
                </div>
              </>
            ) : (
              // 展開時: drag-resizable な縦分割 (v0.26.6、react-resizable-panels)
              <PanelGroup
                orientation="vertical"
                id="pyflw.workspace_library_split"
                className="flex-1"
              >
                {/* v0.26.7: minSize を pixel 指定 (= ヘッダー 24 px より下に縮まない)。
                    v4 の minSize は CSS 単位文字列を受ける ("32px" / "2rem" 等)。 */}
                <Panel defaultSize={40} minSize="48px">
                  <div className="flex h-full min-h-0 flex-col overflow-hidden">
                    <FileBrowser />
                  </div>
                </Panel>
                <PanelResizeHandle className="group relative z-10 h-0.5 cursor-row-resize bg-slate-300 transition-colors hover:bg-blue-400 data-[resize-handle-state=drag]:bg-blue-500">
                  <div className="absolute inset-x-0 -top-1 -bottom-1" />
                </PanelResizeHandle>
                <Panel defaultSize={60} minSize="48px">
                  <div className="flex h-full min-h-0 flex-col overflow-hidden">
                    <PanelHeader>{t("panel.library")}</PanelHeader>
                    <div className="min-h-0 flex-1 overflow-hidden">
                      <BlockPalette />
                    </div>
                  </div>
                </Panel>
              </PanelGroup>
            )}
          </aside>

          {/* v0.26.10: 自前 drag handle (= 5 px wide grid column)。
              pointer-down で window-level の pointermove / pointerup を取得し、
              ローカル state を更新せず store action を呼ぶ。React Flow との
              競合は z-index + cursor + capture で確実に勝つ。 */}
          <ResizeHandleX
            value={leftSidebarWidth}
            onChange={setLeftSidebarWidth}
          />

          {/* Center: canvas + sim controls + scopes (drag-resizable split, ADR-0044 §論点 2).
              v0.26.12: PanelGroup を **常時描画** に変更。Scope の有無で
              ``<DiagramCanvas/>`` の親要素 (``<PanelGroup>`` vs ``<div>``) を
              切り替えていた旧実装では、シミュレーション開始で scopes が空 → 非空に
              変わった瞬間に React が DiagramCanvas をアンマウント→再マウントし、
              ``<ReactFlow fitView>`` が再発火してユーザーのズーム / pan が
              リセットされる問題があった。Panel 0 (= canvas) を一貫して同じ位置に
              保つことで React の reconciliation がインスタンスを維持し、ビューポートが
              保持される。Scope の有無に応じて handle + 下 Panel を後置 sibling として
              条件付きで足し引きするが、Panel 0 は影響を受けない。 */}
          <main className="flex min-h-0 flex-col overflow-hidden bg-slate-100">
            {hasOpenedModel ? (
              <>
                <Breadcrumb />
                <PanelGroup
                  orientation="vertical"
                  id="pyflw.scope_split"
                  className="flex-1 border-b border-slate-300"
                >
                  <Panel id="canvas" minSize={20} defaultSize={hasVisibleScopes ? 60 : 100}>
                    <div className="h-full bg-white">
                      <DiagramCanvas />
                    </div>
                  </Panel>
                  {hasVisibleScopes && (
                    <>
                      <PanelResizeHandle className="group relative z-10 h-0.5 cursor-row-resize bg-slate-300 transition-colors hover:bg-blue-400 data-[resize-handle-state=drag]:bg-blue-500">
                        <div className="absolute inset-x-0 -top-1 -bottom-1" />
                      </PanelResizeHandle>
                      <Panel id="scopes" minSize={10} defaultSize={40}>
                        <div className="flex h-full flex-col gap-2 overflow-y-auto bg-white p-2">
                          {visibleScopeEntries.map(([scopeId, buffer]) => {
                            const blockType = blockTypeById.get(scopeId) ?? "";
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
                    </>
                  )}
                </PanelGroup>
                <SimulationControls modelId={selectedFilePath ?? ""} />
              </>
            ) : (
              <EmptyState />
            )}
          </main>

          {/* Right: Inspector — 折りたたみ可能 (v0.26.5)。
              左 + center とは別 grid column (state-controlled width)。 */}
          {inspectorCollapsed ? (
            <aside
              className="flex min-h-0 cursor-pointer flex-col items-center border-l border-slate-300 bg-slate-50 hover:bg-slate-100"
              onClick={() => setInspectorCollapsed(false)}
              title={t("panel.inspector.expand", "Show Inspector")}
              role="button"
              aria-label={t("panel.inspector.expand", "Show Inspector")}
            >
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setInspectorCollapsed(false);
                }}
                className="flex h-6 w-6 items-center justify-center text-slate-500 hover:text-slate-800"
                title={t("panel.inspector.expand", "Show Inspector")}
              >
                <svg
                  viewBox="0 0 24 24"
                  className="h-3.5 w-3.5"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <polyline points="15 18 9 12 15 6" />
                </svg>
              </button>
              <div className="flex-1 [writing-mode:vertical-rl] py-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                {t("panel.inspector")}
              </div>
            </aside>
          ) : (
            <aside className="flex min-h-0 flex-col overflow-hidden border-l border-slate-300 bg-white">
              <div className="flex h-6 items-center border-b border-slate-200 bg-slate-100 pl-2 pr-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                <span className="flex-1">{t("panel.inspector")}</span>
                <button
                  type="button"
                  onClick={() => setInspectorCollapsed(true)}
                  className="flex h-5 w-5 items-center justify-center rounded text-slate-500 hover:bg-slate-200 hover:text-slate-800"
                  title={t("panel.inspector.collapse", "Hide Inspector")}
                  aria-label={t("panel.inspector.collapse", "Hide Inspector")}
                >
                  <svg
                    viewBox="0 0 24 24"
                    className="h-3 w-3"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <polyline points="9 18 15 12 9 6" />
                  </svg>
                </button>
              </div>
              <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
                {hasOpenedModel ? (
                  <ParameterPanel modelId={selectedFilePath ?? ""} />
                ) : (
                  <div className="p-3 text-[11px] text-slate-400">
                    {t("app.inspector.locked")}
                  </div>
                )}
              </div>
            </aside>
          )}
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

/**
 * v0.26.10: 自前の horizontal drag handle (= grid column として 5 px 確保)。
 *
 * pointer-down で ``setPointerCapture`` し window-level の pointermove /
 * pointerup を bind。React Flow に pointer event を奪われないよう ``z-10`` +
 * ``cursor-col-resize`` を付与。``onChange`` は座標差分で呼ばれ、store action
 * 内で min/max クランプ + localStorage 永続化。
 */
function ResizeHandleX({
  value,
  onChange,
}: {
  value: number;
  onChange: (px: number) => void;
}): JSX.Element {
  const [dragging, setDragging] = useState(false);
  const startRef = useRef<{ x: number; baseline: number } | null>(null);

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>): void => {
    e.preventDefault();
    e.stopPropagation();
    // code-reviewer SHOULD: setPointerCapture で高速 drag + window 外への
    // ポインタ離脱でも pointerup を取りこぼさないように。
    try {
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    } catch {
      // 古いブラウザ等で setPointerCapture が無い場合は window listener にフォールバック
    }
    startRef.current = { x: e.clientX, baseline: value };
    setDragging(true);
    const move = (me: PointerEvent): void => {
      const s = startRef.current;
      if (!s) return;
      onChange(s.baseline + (me.clientX - s.x));
    };
    const up = (): void => {
      startRef.current = null;
      setDragging(false);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
  };

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize left sidebar"
      onPointerDown={onPointerDown}
      className={`relative z-20 h-full w-full cursor-col-resize select-none ${
        dragging ? "bg-blue-500" : "bg-slate-300 hover:bg-blue-400"
      }`}
    >
      {/* 透明な広いヒットエリア (= 左右 ±4 px) で確実に掴める */}
      <div className="absolute inset-y-0 -left-1 -right-1" />
    </div>
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
