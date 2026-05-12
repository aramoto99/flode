import { ReactFlowProvider } from "@xyflow/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Rnd } from "react-rnd";

import { getWorkspaceInfo } from "./api/filesApi";

import { ActivityBar } from "./components/ActivityBar";
import { BlockPalette } from "./components/BlockPalette";
import { Breadcrumb } from "./components/Breadcrumb";
import { CommandPalette } from "./components/CommandPalette";
import { DiagramCanvas } from "./components/DiagramCanvas";
import { FileBrowser } from "./components/FileBrowser";
import { Launcher } from "./components/Launcher";
import { MenuBar } from "./components/MenuBar";
import { ParameterPanel } from "./components/ParameterPanel";
import { ScopePanelContainer } from "./components/ScopePanelContainer";
import { ScopeSettingsDialog } from "./components/ScopeSettingsDialog";
import { SearchPanel } from "./components/SearchPanel";
import { SimulationControls } from "./components/SimulationControls";
import { StatusBar } from "./components/StatusBar";
import { TabStrip } from "./components/TabStrip";
import { ToastContainer } from "./components/Toast";
import { Toolbar } from "./components/Toolbar";
import { WorkspaceSplit } from "./components/WorkspaceSplit";
import { resolveBlocksAtPath } from "./lib/pathResolver";
import {
  LEGACY_SCOPE_SPLIT_KEY,
  makeWorkspaceLayoutKey,
} from "./lib/storageKeys";
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
  // ADR-0051 §(1) §(2): activity bar sidebar mode (= file / library / search)
  const sidebarMode = useAppStore((s) => s.sidebarMode);
  // ADR-0052 §(2) Stage 3: Inspector dock mode (sidebar / pane / float)
  const inspectorDockMode = useAppStore((s) => s.inspectorDockMode);
  const setInspectorDockMode = useAppStore((s) => s.setInspectorDockMode);
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

  // 各 scope_id がどのブロック type かを引くためのマップ (現スコープ内のみ)。
  // ``block.id`` (= 例: ``Scope_1``) は表示名兼識別子なので、pane タイトルは
  // ``scope_id`` をそのまま使う (= BlockEntry に separate な name フィールドなし)。
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
  // ADR-0045 §(1): WorkspaceSplit 内で scope:<id> 葉に独立分離 / scopes-stack
  // 葉に縦並べ。
  const visibleScopeEntries = useMemo(
    () =>
      Object.entries(scopes).filter(([id]) => {
        const t = blockTypeById.get(id) ?? "";
        return !t.endsWith(".Display");
      }),
    [scopes, blockTypeById],
  );

  // ADR-0045 §(3-C): モデルが Scope/XYGraph ブロックを構造的に持つかどうか。
  // ``visibleScopeEntries`` は scope buffer データ依存 (= sim 開始までは空) なので、
  // 初期 SplitTree 選定の根拠としては editingModel.blocks の方が確実。
  const hasScopeBlocks = useMemo(() => {
    if (!editingModel) return false;
    try {
      const view = resolveBlocksAtPath(editingModel, editingPath);
      return view.blocks.some(
        (b) => b.type.endsWith(".Scope") || b.type.endsWith(".XYGraph"),
      );
    } catch {
      return false;
    }
  }, [editingModel, editingPath]);

  // ADR-0045 §(6): React Portal で DiagramCanvas を WorkspaceSplit の Diagram
  // slot div に投影する。useState の setter は安定 (= React 保証) なので
  // ref callback としてそのまま渡せる。
  const [diagramPortalEl, setDiagramPortalEl] =
    useState<HTMLDivElement | null>(null);

  // ADR-0045 §(3-C) §(3-D): モデル切替 / 起動時に SplitTree を localStorage から
  // 復元 (+ 旧 ``pyflw.scope_split`` 片方向 migration)。``hasScopeBlocks`` は
  // モデルが Scope/XYGraph を持つかの構造的判定で、stored / legacy 両方なし時の
  // default tree 選定根拠。
  const loadWorkspaceLayout = useAppStore((s) => s.loadWorkspaceLayout);
  useEffect(() => {
    if (workspaceHash === null || activeTabFilePath === null) {
      // workspace 未確定 or タブ未選択時: default
      loadWorkspaceLayout(null, null, hasScopeBlocks);
      return;
    }
    const newKey = makeWorkspaceLayoutKey(workspaceHash, activeTabFilePath);
    const stored = (() => {
      try {
        return window.localStorage.getItem(newKey);
      } catch {
        return null;
      }
    })();
    const legacy = (() => {
      try {
        return window.localStorage.getItem(LEGACY_SCOPE_SPLIT_KEY);
      } catch {
        return null;
      }
    })();
    loadWorkspaceLayout(stored, legacy, hasScopeBlocks);
    // hasScopeBlocks は依存配列から **意図的に除外**: モデル内でブロック追加 /
    // 削除が起きても layout を勝手にリセットしない (= ユーザーが手で組んだ
    // SplitTree を維持)。モデル切替時のみ初期化したい。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceHash, activeTabFilePath, loadWorkspaceLayout]);

  // ADR-0045 §(6): ``setDiagramPortalEl`` (= useState setter) は React により
  // 識別性が保証されるため、``useCallback`` ラップ不要でそのまま WorkspaceSplit の
  // ref callback に渡せる (= code-reviewer §SHOULD #3)。

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

        {/* Main 5-column area (ADR-0051 §(1): 列 0 = activity bar 新規追加)
            v0.26.10: 左 sidebar 横幅は manual drag handle で管理、grid template
            columns に直接埋め込む。react-resizable-panels の horizontal は
            grid 内で動作不安定だったので自前実装に切替。
            ADR-0051 §(1): 列 0 = activity bar (32 px 固定幅)、列 1 = sidebar
            (mode に応じて FileBrowser / BlockPalette / SearchPanel 切替)、列 2
            = 5 px drag handle、列 3 = main、列 4 = Inspector (折りたたみ 2 値)。
            workspaceCollapsed 時は列 1 を 0 px に潰し、activity bar のみ表示。 */}
        <div
          className="grid min-h-0 overflow-hidden"
          style={{
            gridTemplateColumns: `32px ${workspaceCollapsed ? "0px" : `${leftSidebarWidth}px`} ${workspaceCollapsed ? "0px" : "5px"} 1fr ${
              // ADR-0052 §(2) Stage 3: sidebar mode 以外は列 4 を 0 px に潰す
              // (= pane mode は WorkspaceSplit に統合、float mode は Rnd で
              // overlay 描画、列 4 は描画コストゼロ)
              inspectorDockMode !== "sidebar"
                ? "0px"
                : inspectorCollapsed
                  ? "24px"
                  : "280px"
            }`,
          }}
        >
          {/* Column 0: Activity bar (ADR-0051 §(1)) */}
          <ActivityBar />

          {/* Column 1: Left sidebar (mode に応じた切替、collapsed 時は非表示) */}
          {!workspaceCollapsed && (
            <aside className="flex min-h-0 flex-col overflow-hidden border-r border-slate-300 bg-white">
              {sidebarMode === "file" && <FileBrowser />}
              {sidebarMode === "library" && (
                <>
                  <PanelHeader>{t("panel.library")}</PanelHeader>
                  <div className="min-h-0 flex-1 overflow-hidden">
                    <BlockPalette />
                  </div>
                </>
              )}
              {sidebarMode === "search" && <SearchPanel />}
            </aside>
          )}

          {/* Column 2: 自前 drag handle (= 5 px wide grid column、collapsed 時は非表示)。
              v0.26.10: pointer-down で window-level の pointermove / pointerup を
              取得し、ローカル state を更新せず store action を呼ぶ。React Flow との
              競合は z-index + cursor + capture で確実に勝つ。 */}
          {!workspaceCollapsed && (
            <ResizeHandleX
              value={leftSidebarWidth}
              onChange={setLeftSidebarWidth}
            />
          )}

          {/* Center: canvas + sim controls + scopes
              ADR-0045 §(1) §(6): v0.26.12 の「Panel id="canvas" 常時描画 +
              scope を sibling 条件付き足し引き」を ``<WorkspaceSplit>`` に
              置換。SplitTree を再帰的に PanelGroup + Panel に展開し、Diagram
              + scope:<id> + scopes-stack の任意配置を可能に。DiagramCanvas は
              ``<ReactFlowProvider>`` 直下に常時 mount + React Portal で
              WorkspaceSplit 内の Diagram slot div に投影することで、SplitTree
              再構造でも viewport が保持される (= v0.26.12 規律継承)。 */}
          <main className="flex min-h-0 flex-col overflow-hidden bg-slate-100">
            {hasOpenedModel ? (
              <>
                <Breadcrumb />
                <div className="flex-1 min-h-0 border-b border-slate-300">
                  <WorkspaceSplit
                    setDiagramSlot={setDiagramPortalEl}
                    visibleScopeEntries={visibleScopeEntries}
                    blockTypeById={blockTypeById}
                    hasScopeBlocks={hasScopeBlocks}
                  />
                </div>
                <SimulationControls modelId={selectedFilePath ?? ""} />
              </>
            ) : (
              // ADR-0051 §(3): 旧 EmptyState を Launcher に置換 (= New / Open
              // tile + Recent 上位 5 件、`EmptyState` 関数は撤去)
              <Launcher />
            )}
          </main>

          {/* Right: Inspector — 折りたたみ可能 (v0.26.5)。
              ADR-0052 §(2) Stage 3: inspectorDockMode === "sidebar" のときだけ
              列 4 を描画 (= pane / float では非表示、WorkspaceSplit or Rnd 経由)。
              左 + center とは別 grid column (state-controlled width)。 */}
          {inspectorDockMode !== "sidebar" ? null : inspectorCollapsed ? (
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
              <div className="flex h-6 items-center gap-1 border-b border-slate-200 bg-slate-100 pl-2 pr-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                <span className="flex-1">{t("panel.inspector")}</span>
                {/* ADR-0052 §(2) Stage 3: Inspector mode 切替 select。
                    既存 SELECT_CLS 風スタイル、segment 風 button は使わない。 */}
                <select
                  value={inspectorDockMode}
                  onChange={(e) =>
                    setInspectorDockMode(
                      e.target.value as "sidebar" | "pane" | "float",
                    )
                  }
                  title={t("workspace.inspector.mode.label")}
                  aria-label={t("workspace.inspector.mode.label")}
                  className="border border-slate-300 bg-white px-1 py-0 text-[10px] text-slate-700 focus:border-blue-500 focus:outline-none"
                >
                  <option value="sidebar">
                    {t("workspace.inspector.mode.sidebar")}
                  </option>
                  <option value="pane">
                    {t("workspace.inspector.mode.pane")}
                  </option>
                  <option value="float">
                    {t("workspace.inspector.mode.float")}
                  </option>
                </select>
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

        {/* ADR-0043 §論点 5-A → ADR-0051 §(2-A): Search panel は sidebar
            mode に統合済 (= 列 1 内 inline)、overlay は廃止 */}

        {/* ADR-0044 §論点 6: floating Scope panel (= Scope ダブルクリックで開く)。
            ADR-0052 §(3) Stage 3: 役割再定義済 (= detach 経由のみ float 化、
            ダブルクリックは docked split 昇格に変更) */}
        <ScopePanelContainer />

        {/* ADR-0052 §(2) Stage 3: Inspector Float mode で Rnd 描画 */}
        {hasOpenedModel && inspectorDockMode === "float" && (
          <InspectorFloatPanel
            onClose={() => setInspectorDockMode("sidebar")}
          />
        )}

        {/* ADR-0044 §論点 4: per-Scope プロット設定 dialog (= gear アイコンで開く) */}
        <GlobalScopeSettingsDialog />

        {/* v0.29.0: コマンドパレット (Ctrl+Shift+P で open) */}
        <GlobalCommandPalette />

        {/* ADR-0045 §(6): DiagramCanvas を ReactFlowProvider 直下に常時 mount。
            実体 DOM は WorkspaceSplit 内の Diagram slot div に React Portal で
            投影される (= SplitTree 再構造で slot DOM 位置が変わっても、
            DiagramCanvas の React tree 位置は不変のため viewport / nodes /
            edges 等の internal state は維持)。モデル未選択時は portal 不要
            なので mount しない。 */}
        {hasOpenedModel && <DiagramCanvas portalTarget={diagramPortalEl} />}
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

function GlobalCommandPalette(): JSX.Element {
  const open = useAppStore((s) => s.commandPaletteOpen);
  const setOpen = useAppStore((s) => s.setCommandPaletteOpen);
  return <CommandPalette open={open} onClose={() => setOpen(false)} />;
}

/** ADR-0052 §(2) Stage 3: Inspector を float mode で表示する Rnd wrapper。
 * ScopePanelContainer (= ADR-0044 react-rnd) と同じ pattern を再利用。
 * geometry は localStorage に永続化 (= workspaceHash 単位、ADR-0044 と同様)。 */
function InspectorFloatPanel({ onClose }: { onClose: () => void }): JSX.Element {
  const { t } = useTranslation();
  const selectedFilePath = useAppStore((s) => s.selectedFilePath);
  return (
    <Rnd
      default={{ x: 200, y: 120, width: 320, height: 480 }}
      minWidth={240}
      minHeight={240}
      bounds="window"
      dragHandleClassName="inspector-float-drag-handle"
      style={{ zIndex: 50, pointerEvents: "auto" }}
      className="rounded border border-slate-400 bg-white shadow-2xl overflow-hidden"
      data-testid="inspector-float-panel"
    >
      <div className="flex h-full w-full flex-col">
        <div className="inspector-float-drag-handle flex h-6 cursor-move items-center border-b border-slate-200 bg-slate-100 pl-2 pr-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          <span className="flex-1">{t("panel.inspector")}</span>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("panel.inspector.collapse", "Hide Inspector")}
            title={t("panel.inspector.collapse", "Hide Inspector")}
            className="flex h-5 w-5 items-center justify-center text-slate-500 hover:bg-slate-200 hover:text-slate-800"
          >
            <svg
              viewBox="0 0 24 24"
              className="h-3 w-3"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <ParameterPanel modelId={selectedFilePath ?? ""} />
        </div>
      </div>
    </Rnd>
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

// ADR-0051 §(3): 旧 EmptyState は Launcher に置換、本関数は撤去
