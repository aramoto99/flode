import { ReactFlowProvider } from "@xyflow/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getWorkspaceInfo } from "./api/filesApi";

import { ActivityBar } from "./components/ActivityBar";
import { BlockPalette } from "./components/BlockPalette";
import { Breadcrumb } from "./components/Breadcrumb";
import { CommandPalette } from "./components/CommandPalette";
import { DialogHost } from "./components/DialogHost";
import { DiagramCanvas } from "./components/DiagramCanvas";
import { FileBrowser } from "./components/FileBrowser";
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
import { findBlockTypeById } from "./lib/findBlockPath";
import { resolveBlocksAtPath } from "./lib/pathResolver";
import { makeWorkspaceLayoutKey } from "./lib/storageKeys";
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
  // v0.30.4: Inspector 横幅 (drag で変更)
  const inspectorWidth = useAppStore((s) => s.inspectorWidth);
  const setInspectorWidth = useAppStore((s) => s.setInspectorWidth);
  // ADR-0051 §(1) §(2): activity bar sidebar mode (= file / library / search)
  const sidebarMode = useAppStore((s) => s.sidebarMode);
  // v0.21.0: ``selectedFilePath`` 一本化 (= legacy selectedModelId 削除済、
  // ADR-0041 §論点 4-A)
  const hasOpenedModel = selectedFilePath !== null;
  const dirty = useAppStore((s) => s.dirty);

  // v3.14.14: 旧「Title bar (window chrome 風)」を撤去し、ブラウザのタブ
  // タイトルを動的更新する標準 idiom に統一する。version は StatusBar 右端で
  // 既に表示済み (= 重複) のため title bar からの削除で情報損失なし。
  useEffect(() => {
    const base = "flode";
    if (!hasOpenedModel) {
      document.title = base;
      return;
    }
    const name = selectedFilePath ?? "untitled";
    const prefix = dirty ? "● " : "";
    document.title = `${prefix}${name} — ${base}`;
  }, [hasOpenedModel, selectedFilePath, dirty]);

  // ADR-0019 §(5): debounce auto-save / Ctrl+S / beforeunload
  useAutoSave();
  // ADR-0041 §論点 11-A: 外部エディタ変更を 5 秒 polling で検知
  useExternalChangesPoll();
  // リファレンスツール風キーボードショートカット (Ctrl+T/A/C/V, Esc, Enter)
  useShortcuts();

  // ADR-0043 §論点 1-A / §論点 8-A: startup で workspace_info を fetch、
  // localStorage キーの suffix に使う hash を store に保存。Recent Files /
  // タブ復元 / Search panel が参照する。完了後、最後に開いていた active file
  // path (= localStorage `flode.last_active.<hash>`) を復元する。
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
        const lastKey = `flode.last_active.${info.hash}`;
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
    const key = `flode.last_active.${workspaceHash}`;
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
  // 復元 (+ 旧 ``flode.scope_split`` 片方向 migration)。``hasScopeBlocks`` は
  // モデルが Scope/XYGraph を持つかの構造的判定で、stored / legacy 両方なし時の
  // default tree 選定根拠。
  const loadWorkspaceLayout = useAppStore((s) => s.loadWorkspaceLayout);
  useEffect(() => {
    if (workspaceHash === null || activeTabFilePath === null) {
      // workspace 未確定 or タブ未選択時: default
      loadWorkspaceLayout(null, hasScopeBlocks);
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
    loadWorkspaceLayout(stored, hasScopeBlocks);
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
      <div className="grid h-full grid-rows-[auto_auto_auto_1fr_auto] bg-slate-50 font-sans text-[13px] text-slate-900">
        {/* Menu bar (v3.14.14: 旧 Title bar 撤去、document.title に移譲) */}
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
            // v0.30.4: 列 3 (main) と列 5 (Inspector) の境界に drag handle
            // (= 列 4) を追加して Inspector 横幅を drag 可変化。
            // v0.30.5: 境界線の visual width を 5px → 1px に縮小 (ユーザー要望)。
            // drag hit area は ResizeHandleX の overlay (= ±4px) で確保。
            // collapsed 時は handle を 0 px に潰す。
            // 6 列構成: activity bar / sidebar / sidebar-handle / main /
            //          inspector-handle / inspector
            gridTemplateColumns: `32px ${workspaceCollapsed ? "0px" : `${leftSidebarWidth}px`} ${workspaceCollapsed ? "0px" : "1px"} 1fr ${inspectorCollapsed ? "0px" : "1px"} ${inspectorCollapsed ? "24px" : `${inspectorWidth}px`}`,
          }}
        >
          {/* Column 0: Activity bar (ADR-0051 §(1)) */}
          <ActivityBar />

          {/* Column 1: Left sidebar (mode に応じた切替)。collapsed 時は内容
              のみ非表示にし、aside 自体は **column placeholder として常時描画**
              する (= v0.30.2 hotfix: 空にすると grid 子要素が左詰めになって
              main が列 2 = 0px に流れ込むバグ修正)。 */}
          {/* v0.30.5: sidebar の border-r を撤去 (= ResizeHandleX が境界の役割を
              担うため、二重境界線を排除) */}
          <aside className="flex min-h-0 flex-col overflow-hidden bg-white">
            {!workspaceCollapsed && sidebarMode === "file" && <FileBrowser />}
            {!workspaceCollapsed && sidebarMode === "library" && (
              <>
                <PanelHeader>{t("panel.library")}</PanelHeader>
                <div className="min-h-0 flex-1 overflow-hidden">
                  <BlockPalette />
                </div>
              </>
            )}
            {!workspaceCollapsed && sidebarMode === "search" && <SearchPanel />}
          </aside>

          {/* Column 2: 自前 drag handle (= 5 px wide grid column)。collapsed 時は
              不可視 (= 内側 grid template で 0 px) だが grid placeholder として常時
              描画 (= v0.30.2 hotfix と同じ理由)。 */}
          {workspaceCollapsed ? (
            <div aria-hidden="true" />
          ) : (
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
              // v0.42.x (ユーザー要望): Launcher (スタート画面カード) を撤去。
              // 新規/開くは MenuBar・FileBrowser に集約済みのため、未オープン時は
              // 控えめな空状態表示のみ (= 旧 EmptyState 相当に回帰)。
              <div className="flex flex-1 flex-col items-center justify-center gap-1 text-slate-400">
                <div className="text-[13px]">{t("app.empty.title")}</div>
                <div className="text-[11px]">{t("app.empty.hint_new")}</div>
              </div>
            )}
          </main>

          {/* Column 5: Inspector 左端の drag handle (v0.30.4)。
              v0.26.10 と同じ self-implemented horizontal handle、direction="right"
              で delta 反転 (= drag 右移動で Inspector 縮小)。collapsed 時は
              0 px placeholder で grid を維持。 */}
          {inspectorCollapsed ? (
            <div aria-hidden="true" />
          ) : (
            <ResizeHandleX
              value={inspectorWidth}
              onChange={setInspectorWidth}
              direction="right"
            />
          )}

          {/* Column 6: Inspector — 折りたたみ可能 (v0.26.5)。
              左 + center とは別 grid column (state-controlled width)。
              v0.30.2: ADR-0052 §(2) の 3 mode 切替を撤去、sidebar 単独に revert。
              v0.30.4: 横幅を drag で可変に。 */}
          {inspectorCollapsed ? (
            <aside
              className="flex min-h-0 cursor-pointer flex-col items-center bg-slate-50 hover:bg-slate-100"
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
            <aside className="flex min-h-0 flex-col overflow-hidden bg-white">
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

        {/* ADR-0043 §論点 5-A → ADR-0051 §(2-A): Search panel は sidebar
            mode に統合済 (= 列 1 内 inline)、overlay は廃止 */}

        {/* ADR-0044 §論点 6: floating Scope panel (= Scope ダブルクリックで開く)。
            v0.30.2: ダブルクリック挙動を float 即開きに revert (ユーザー要望) */}
        <ScopePanelContainer />

        {/* ADR-0044 §論点 4: per-Scope プロット設定 dialog (= gear アイコンで開く) */}
        <GlobalScopeSettingsDialog />

        {/* v0.29.0: コマンドパレット (Ctrl+Shift+P で open) */}
        <GlobalCommandPalette />

        {/* v0.32.0: グローバル dialog host (window.alert/confirm/prompt 置換)。
            Portal 的に fixed inset-0 で描画されるため grid 末尾でも OK。 */}
        <DialogHost />

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
  const editingModel = useAppStore((s) => s.editingModel);
  if (!editingScopeSettingsId) return null;
  // 対象ブロックが XYGraph なら XY 適応ダイアログ (= log/凡例/minor grid を隠す)。
  const blockType = editingModel
    ? findBlockTypeById(editingModel, editingScopeSettingsId)
    : null;
  const isXY = blockType?.endsWith(".XYGraph") ?? false;
  return (
    <ScopeSettingsDialog
      scopeId={editingScopeSettingsId}
      isXY={isXY}
      onClose={() => setEditingScopeSettingsId(null)}
    />
  );
}

function GlobalCommandPalette(): JSX.Element {
  const open = useAppStore((s) => s.commandPaletteOpen);
  const setOpen = useAppStore((s) => s.setCommandPaletteOpen);
  return <CommandPalette open={open} onClose={() => setOpen(false)} />;
}

// v0.30.2: ADR-0052 §(2) で追加した InspectorFloatPanel は撤去 (= sidebar 単独
// UX に revert)。Rnd / ParameterPanel import も unused に。

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
  direction = "left",
}: {
  value: number;
  onChange: (px: number) => void;
  /** v0.30.4: drag delta の符号。"left" = 左 sidebar (= 右に drag で拡大) /
   *  "right" = Inspector (= 右に drag で縮小、= 左に drag で拡大)。 */
  direction?: "left" | "right";
}): JSX.Element {
  const [dragging, setDragging] = useState(false);
  const startRef = useRef<{ x: number; baseline: number } | null>(null);

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>): void => {
    e.preventDefault();
    e.stopPropagation();
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
      // v0.30.4: direction="right" は右に drag → Inspector 縮小 (= delta 反転)
      const delta =
        direction === "right" ? -(me.clientX - s.x) : me.clientX - s.x;
      onChange(s.baseline + delta);
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
      aria-label={
        direction === "right" ? "Resize inspector" : "Resize left sidebar"
      }
      onPointerDown={onPointerDown}
      className={`relative z-20 h-full w-full cursor-col-resize select-none ${
        dragging ? "bg-blue-500" : "bg-slate-300 hover:bg-blue-400"
      }`}
    >
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

