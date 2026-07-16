// デスクトップ風 MenuBar (File / Edit / View / Simulation / Settings / Help)。
// 業界標準ブロック線図ツール + 数値計算 IDE の上部メニュー帯に倣う。
//
// v0.21.0 (ADR-0041 §論点 4-A): legacy ``--model-dir`` / ``selectedModelId``
// 経路を撤去、File API (= ``selectedFilePath``) 一本化。File メニューは New /
// Open / Save / Save As / Close / Delete を全て File API 経由で操作する。
//
// v0.42.0: Edit / View メニューを新設、Simulation に Run / Stop を追加。
// ショートカット・コマンドパレット限定だった実装済み機能をメニューバーから
// 発見できるようにする (= メニューバーは機能の全カタログ、という desktop 文法)。

import { useReactFlow } from "@xyflow/react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";

import {
  deleteFile,
  getFileContent,
  putFileContent,
} from "../api/filesApi";
import {
  currentLanguage,
  setLanguage,
  type SupportedLanguage,
} from "../i18n";
import { cleanupUntitled } from "../lib/commands";
import { emptyModel } from "../lib/emptyModel";
import {
  clearRecentFiles,
  readRecentFiles,
  removeRecentFile,
} from "../lib/recentFiles";
import { dialog } from "../lib/dialogService";
import { useSimulation } from "../lib/useSimulation";
import {
  copySelectionToClipboard,
  pasteClipboard,
  removeBlockFromEditing,
  selectAllInScope,
  toggleBlockFlipped,
  useAppStore,
} from "../store/appStore";
import { KeyboardShortcutsDialog, SaveAsPathDialog } from "./Modal";
import { ModelSettingsModal } from "./ModelSettingsModal";

type DialogKind =
  | { kind: "save-as-path" }
  | { kind: "model-settings" }
  | { kind: "shortcuts" }
  | null;

interface MenuItemSpec {
  label: string;
  shortcut?: string;
  onClick?: () => void;
  disabled?: boolean;
  destructive?: boolean;
  divider?: boolean;
  // Settings > Language サブメニュー用 (現在言語と一致時に ✓ 表示)
  language?: SupportedLanguage;
}

export function MenuBar(): JSX.Element {
  const { t, i18n: _i18n } = useTranslation();
  const lang = currentLanguage();
  void _i18n;
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  // v0.32.0: dialogService の `dialog` import と shadowing しないよう
  // ローカル state は `modal` / `setModal` に rename。
  const [modal, setModal] = useState<DialogKind>(null);
  const ref = useRef<HTMLDivElement>(null);

  const selectedFilePath = useAppStore((s) => s.selectedFilePath);
  const selectFilePath = useAppStore((s) => s.selectFilePath);
  const openFileInTab = useAppStore((s) => s.openFileInTab);
  const closeTab = useAppStore((s) => s.closeTab);
  const setEditingModel = useAppStore((s) => s.setEditingModel);
  const setDirty = useAppStore((s) => s.setDirty);
  const editingModel = useAppStore((s) => s.editingModel);
  const workspaceHash = useAppStore((s) => s.workspaceHash);
  // v0.42.0: Edit / View / Simulation メニュー用の購読。
  // 選択配列は boolean に落として購読する (= 選択変更のたびに MenuBar 全体が
  // 再レンダーされるのを防ぐ。zustand は Object.is 比較)。
  const hasSelection = useAppStore((s) => s.selectedNodeIds.length > 0);
  const hasEdgeSelection = useAppStore((s) => s.selectedEdgeIds.length > 0);
  const canUndo = useAppStore((s) => s.canUndo());
  const canRedo = useAppStore((s) => s.canRedo());
  const hasClipboard = useAppStore((s) => s.clipboard !== null);
  const simStatus = useAppStore((s) => s.status);
  const reactFlow = useReactFlow();
  const { run: runSimulation, stop: stopSimulation } = useSimulation();
  // ADR-0043 §論点 4: Recent Files の再読込トリガー (= recent 変更時に再描画)
  const [recentRev, setRecentRev] = useState(0);
  const recentFiles =
    workspaceHash !== null ? readRecentFiles(workspaceHash) : [];
  void recentRev; // recentRev が変わると再 read される (= deps trigger)

  const queryClient = useQueryClient();

  useEffect(() => {
    const handler = (e: MouseEvent): void => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpenMenu(null);
      }
    };
    if (openMenu) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [openMenu]);

  // ---- File actions (= File API 一本化) ----

  const handleNew = async (): Promise<void> => {
    setOpenMenu(null);
    // v0.31.1: 自動連番 (= nextUntitledFilePath) を廃止、prompt でファイル名を
    // ユーザーに明示要求 (FileBrowser の新規作成と同じ挙動)。
    const input = await dialog.prompt(
      t("filebrowser.prompt_new_file", "New file name (.flw.json):"),
      { defaultValue: "untitled.flw.json" },
    );
    if (!input) return;
    const name = input.endsWith(".flw.json") ? input : `${input}.flw.json`;
    const fileBrowserCwd = useAppStore.getState().fileBrowserCwd;
    const path = fileBrowserCwd ? `${fileBrowserCwd}/${name}` : name;
    try {
      const empty = emptyModel(name.replace(/\.flw\.json$/, ""));
      await putFileContent(path, empty);
      const data = await getFileContent(path);
      // ADR-0043 §論点 2: tab に追加 + active 化を 1 アクションで
      openFileInTab(path, data.content, data.mtime, data.etag);
      await queryClient.invalidateQueries({ queryKey: ["files-tree"] });
    } catch (e) {
      console.error("New file failed:", e);
      await dialog.alert(`Create failed: ${(e as Error).message}`);
    }
  };

  // 開く操作の実体は FileBrowser (= legacy OpenModelDialog は v0.21.0 撤去)。
  // メニューからはサイドバーの FileBrowser を開いてフォーカスを渡す。
  const handleOpen = (): void => {
    setOpenMenu(null);
    const state = useAppStore.getState();
    state.setSidebarMode("file");
    if (state.workspaceCollapsed) state.setWorkspaceCollapsed(false);
  };

  const handleSave = (): void => {
    setOpenMenu(null);
    // 保存の実体は useAutoSave の Ctrl+S handler (= 楽観ロック + 二重 PUT 防止
    // を一元管理)。CommandPalette の file.save と同じく synthetic keydown で
    // 同じ経路に乗せる (= メニューからも実際に即時 flush される)。
    window.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "s",
        ctrlKey: true,
        bubbles: true,
        cancelable: true,
      }),
    );
  };

  const handleSaveAs = (): void => {
    setOpenMenu(null);
    if (selectedFilePath === null) return;
    setModal({ kind: "save-as-path" });
  };

  const performSaveAsPath = async (newPath: string): Promise<void> => {
    if (!editingModel) {
      setModal(null);
      return;
    }
    try {
      const resp = await putFileContent(newPath, editingModel);
      const data = await getFileContent(newPath);
      // ADR-0043 §論点 2: Save As は新しい tab を開く挙動 (= VSCode 流儀、
      // 元 tab は dirty/未保存のまま残す)。ユーザーが必要なら元 tab を閉じる。
      openFileInTab(newPath, data.content, resp.mtime, resp.etag);
      await queryClient.invalidateQueries({ queryKey: ["files-tree"] });
      setModal(null);
    } catch (e) {
      console.error("Save As failed:", e);
      await dialog.alert(`Save As failed: ${(e as Error).message}`);
    }
  };

  const handleDelete = async (): Promise<void> => {
    setOpenMenu(null);
    if (selectedFilePath === null) return;
    const ok = await dialog.confirm(
      t("filebrowser.confirm_delete", "Delete {{path}}?", {
        path: selectedFilePath,
      }),
      { variant: "danger" },
    );
    if (!ok) return;
    try {
      await deleteFile(selectedFilePath);
      // ADR-0043 §論点 2: closeTab で隣接 tab に切替 or 全閉じ
      const state = useAppStore.getState();
      if (state.tabs.some((t) => t.filePath === selectedFilePath)) {
        closeTab(selectedFilePath);
      } else {
        selectFilePath(null);
        setEditingModel(null);
        setDirty(false);
      }
      await queryClient.invalidateQueries({ queryKey: ["files-tree"] });
    } catch (e) {
      console.error("Delete failed:", e);
      await dialog.alert(`Delete failed: ${(e as Error).message}`);
    }
  };

  const handleClose = (): void => {
    setOpenMenu(null);
    if (selectedFilePath === null) return;
    const state = useAppStore.getState();
    if (state.tabs.some((t) => t.filePath === selectedFilePath)) {
      closeTab(selectedFilePath);
    } else {
      selectFilePath(null);
      setEditingModel(null);
      setDirty(false);
    }
  };

  // ---- keyboard shortcuts: Ctrl+N / Ctrl+Shift+S ----
  // Ctrl+O は legacy Open dialog 用だったが v0.21.0 で削除済 → 現状は無効
  // (Help ダイアログからも撤去済、開く導線は FileBrowser / Ctrl+P に集約)。
  // Ctrl+S は useAutoSave 側で扱う (= Shift 無しの "s")。
  useEffect(() => {
    const handler = (e: KeyboardEvent): void => {
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === "n") {
        e.preventDefault();
        void handleNew();
        return;
      }
      // Ctrl+Shift+S = Save As。一部ブラウザの "ページを保存" 等と重複するため
      // preventDefault で flode を優先。selectedFilePath は空依存 useEffect の
      // stale closure を避けるため getState() で最新値を読む。
      if (
        (e.ctrlKey || e.metaKey) &&
        e.shiftKey &&
        e.key.toLowerCase() === "s"
      ) {
        // ファイル未選択なら何もしない。preventDefault より前で return し、
        // ブラウザ既定 (ページを保存) を塞いだまま無反応になるのを避ける。
        if (useAppStore.getState().selectedFilePath === null) return;
        e.preventDefault();
        setOpenMenu(null);
        setModal({ kind: "save-as-path" });
        return;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
    // setOpenMenu / setModal は stable な useState setter、可変な selectedFilePath は
    // getState() で都度最新を読むため、Save As 分岐に stale closure は生じない。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const hasModel = selectedFilePath !== null;

  // ADR-0043 §論点 4: Recent ファイルを開く (= openFileInTab + move-to-front)
  const handleOpenRecent = async (path: string): Promise<void> => {
    setOpenMenu(null);
    if (!workspaceHash) return;
    try {
      const data = await getFileContent(path);
      openFileInTab(path, data.content, data.mtime, data.etag);
      const { addRecentFile } = await import("../lib/recentFiles");
      addRecentFile(workspaceHash, path);
      setRecentRev((r) => r + 1);
    } catch (e) {
      console.error("Failed to open recent file:", path, e);
      await dialog.alert(
        t("recent.open_failed", "Failed to open: {{path}}", { path }),
      );
      // 開けないファイルは prune
      removeRecentFile(workspaceHash, path);
      setRecentRev((r) => r + 1);
    }
  };

  const handleClearRecent = (): void => {
    if (!workspaceHash) return;
    clearRecentFiles(workspaceHash);
    setRecentRev((r) => r + 1);
    setOpenMenu(null);
  };

  // ---- Menu definitions ----
  // ADR-0043 §論点 4: Recent Files を File menu に inline 展開。最大 10 件、
  // 末尾に Clear Recent。空なら "(No recent)" 表示で disabled。
  const recentItems: MenuItemSpec[] = recentFiles.length > 0
    ? [
        ...recentFiles.map<MenuItemSpec>((path) => ({
          label: path,
          onClick: () => void handleOpenRecent(path),
        })),
        { label: "", divider: true },
        {
          label: t("menu.file.clear_recent", "Clear Recent"),
          onClick: handleClearRecent,
        },
      ]
    : [
        {
          label: t("menu.file.no_recent", "(No recent files)"),
          disabled: true,
        },
      ];

  const fileItems: MenuItemSpec[] = [
    { label: t("menu.file.new"), shortcut: "Ctrl+N", onClick: () => void handleNew() },
    { label: t("menu.file.open"), onClick: handleOpen },
    { label: "", divider: true },
    // ADR-0043 §論点 4: Recent Files セクション
    { label: t("menu.file.recent", "Recent Files"), disabled: true },
    ...recentItems,
    { label: "", divider: true },
    {
      label: t("menu.file.save"),
      shortcut: "Ctrl+S",
      onClick: handleSave,
      disabled: !hasModel,
    },
    {
      label: t("menu.file.save_as"),
      shortcut: "Ctrl+Shift+S",
      onClick: handleSaveAs,
      disabled: !hasModel,
    },
    { label: "", divider: true },
    { label: t("menu.file.close"), onClick: handleClose, disabled: !hasModel },
    {
      label: t("menu.file.delete"),
      onClick: () => void handleDelete(),
      disabled: !hasModel,
      destructive: true,
    },
    { label: "", divider: true },
    {
      label: t("menu.file.cleanup_untitled", "Clean Up Untitled Files…"),
      onClick: () => {
        setOpenMenu(null);
        void cleanupUntitled();
      },
    },
  ];

  // v0.42.0: Edit メニュー。実体は useShortcuts / store action と同一経路。
  const hasAnySelection = hasSelection || hasEdgeSelection;
  const editItems: MenuItemSpec[] = [
    {
      label: t("menu.edit.undo", "Undo"),
      shortcut: "Ctrl+Z",
      disabled: !canUndo,
      onClick: () => {
        setOpenMenu(null);
        useAppStore.getState().undo();
      },
    },
    {
      label: t("menu.edit.redo", "Redo"),
      shortcut: "Ctrl+Shift+Z / Ctrl+Y",
      disabled: !canRedo,
      onClick: () => {
        setOpenMenu(null);
        useAppStore.getState().redo();
      },
    },
    { label: "", divider: true },
    {
      label: t("menu.edit.cut", "Cut"),
      shortcut: "Ctrl+X",
      disabled: !hasSelection,
      onClick: () => {
        setOpenMenu(null);
        // useShortcuts の Ctrl+X と同一手順 (copy → block 削除 → 選択解除)
        copySelectionToClipboard();
        const state = useAppStore.getState();
        for (const id of state.selectedNodeIds) removeBlockFromEditing(id);
        state.selectNode(null);
      },
    },
    {
      label: t("menu.edit.copy", "Copy"),
      shortcut: "Ctrl+C",
      disabled: !hasSelection,
      onClick: () => {
        setOpenMenu(null);
        copySelectionToClipboard();
      },
    },
    {
      label: t("menu.edit.paste", "Paste"),
      shortcut: "Ctrl+V",
      disabled: !hasClipboard,
      onClick: () => {
        setOpenMenu(null);
        pasteClipboard();
      },
    },
    {
      label: t("menu.edit.delete", "Delete"),
      shortcut: "Del",
      disabled: !hasAnySelection,
      onClick: () => {
        setOpenMenu(null);
        // Delete キーと同一経路 (= ReactFlow の change pipeline 経由で
        // onNodesChange / onEdgesChange の remove 処理に乗せる)。
        void reactFlow.deleteElements({
          nodes: reactFlow.getNodes().filter((n) => n.selected),
          edges: reactFlow.getEdges().filter((e) => e.selected),
        });
      },
    },
    { label: "", divider: true },
    {
      label: t("menu.edit.select_all", "Select All"),
      shortcut: "Ctrl+A",
      disabled: !hasModel,
      onClick: () => {
        setOpenMenu(null);
        selectAllInScope();
      },
    },
    {
      label: t("menu.edit.flip", "Flip Block"),
      shortcut: "Ctrl+I",
      disabled: !hasSelection,
      onClick: () => {
        setOpenMenu(null);
        for (const id of useAppStore.getState().selectedNodeIds) {
          toggleBlockFlipped(id);
        }
      },
    },
  ];

  // v0.42.0: View メニュー。ズーム / サイドバー / 検索 / パレット / ペイン操作。
  const viewItems: MenuItemSpec[] = [
    {
      label: t("menu.view.zoom_in", "Zoom In"),
      onClick: () => {
        setOpenMenu(null);
        void reactFlow.zoomIn();
      },
    },
    {
      label: t("menu.view.zoom_out", "Zoom Out"),
      onClick: () => {
        setOpenMenu(null);
        void reactFlow.zoomOut();
      },
    },
    {
      label: t("menu.view.fit", "Fit View"),
      onClick: () => {
        setOpenMenu(null);
        void reactFlow.fitView();
      },
    },
    { label: "", divider: true },
    {
      label: t("menu.view.toggle_sidebar", "Toggle Sidebar"),
      shortcut: "Ctrl+B",
      onClick: () => {
        setOpenMenu(null);
        const s = useAppStore.getState();
        s.setWorkspaceCollapsed(!s.workspaceCollapsed);
      },
    },
    {
      label: t("menu.view.sidebar_file", "Explorer"),
      shortcut: "Ctrl+Shift+E",
      onClick: () => {
        setOpenMenu(null);
        const s = useAppStore.getState();
        s.setSidebarMode("file");
        if (s.workspaceCollapsed) s.setWorkspaceCollapsed(false);
      },
    },
    {
      label: t("menu.view.sidebar_library", "Block Library"),
      onClick: () => {
        setOpenMenu(null);
        const s = useAppStore.getState();
        s.setSidebarMode("library");
        if (s.workspaceCollapsed) s.setWorkspaceCollapsed(false);
      },
    },
    {
      label: t("menu.view.search_path", "Search Files"),
      shortcut: "Ctrl+P",
      onClick: () => {
        setOpenMenu(null);
        const s = useAppStore.getState();
        s.setSidebarMode("search");
        if (s.workspaceCollapsed) s.setWorkspaceCollapsed(false);
        window.dispatchEvent(
          new CustomEvent("flode:open-search", { detail: { kind: "path" } }),
        );
      },
    },
    {
      label: t("menu.view.search_content", "Search in Files"),
      shortcut: "Ctrl+Shift+F",
      onClick: () => {
        setOpenMenu(null);
        const s = useAppStore.getState();
        s.setSidebarMode("search");
        if (s.workspaceCollapsed) s.setWorkspaceCollapsed(false);
        window.dispatchEvent(
          new CustomEvent("flode:open-search", { detail: { kind: "content" } }),
        );
      },
    },
    { label: "", divider: true },
    {
      label: t("menu.view.command_palette", "Command Palette"),
      shortcut: "Ctrl+Shift+P",
      onClick: () => {
        setOpenMenu(null);
        useAppStore.getState().setCommandPaletteOpen(true);
      },
    },
    {
      label: t("menu.view.toggle_inspector", "Toggle Inspector"),
      onClick: () => {
        setOpenMenu(null);
        const s = useAppStore.getState();
        s.setInspectorCollapsed(!s.inspectorCollapsed);
      },
    },
    {
      label: t("menu.view.zen", "Zen Mode"),
      shortcut: "Ctrl+K Z",
      onClick: () => {
        setOpenMenu(null);
        // useShortcuts の Ctrl+K Z と同一 (sidebar + inspector を一括開閉)
        const s = useAppStore.getState();
        const isZen = s.workspaceCollapsed && s.inspectorCollapsed;
        s.setWorkspaceCollapsed(!isZen);
        s.setInspectorCollapsed(!isZen);
      },
    },
    { label: "", divider: true },
    {
      label: t("menu.view.split_right", "Split Right"),
      shortcut: "Ctrl+\\",
      disabled: !hasModel,
      onClick: () => {
        setOpenMenu(null);
        const s = useAppStore.getState();
        const path = s.activeTabFilePath;
        if (!path) return;
        s.splitPane("diagram", "horizontal", `tab:${path}`, "after");
      },
    },
    {
      label: t("menu.view.split_down", "Split Down"),
      shortcut: "Ctrl+K Ctrl+\\",
      disabled: !hasModel,
      onClick: () => {
        setOpenMenu(null);
        const s = useAppStore.getState();
        const path = s.activeTabFilePath;
        if (!path) return;
        s.splitPane("diagram", "vertical", `tab:${path}`, "after");
      },
    },
  ];

  // v0.20.0: Help メニュー
  const helpItems: MenuItemSpec[] = [
    {
      label: t("menu.help.shortcuts", { defaultValue: "Keyboard shortcuts" }),
      onClick: () => {
        setOpenMenu(null);
        setModal({ kind: "shortcuts" });
      },
    },
  ];

  // Simulation メニュー (v0.42.0: Run / Stop を追加 — Toolbar / Ctrl+T と同一経路)
  const simulationItems: MenuItemSpec[] = [
    {
      label: t("menu.simulation.run", "Run"),
      shortcut: "Ctrl+T / F9",
      disabled: !hasModel || simStatus === "running",
      onClick: () => {
        setOpenMenu(null);
        void runSimulation();
      },
    },
    {
      label: t("menu.simulation.stop", "Stop"),
      shortcut: "Ctrl+Shift+T",
      disabled: simStatus !== "running",
      onClick: () => {
        setOpenMenu(null);
        void stopSimulation();
      },
    },
    { label: "", divider: true },
    {
      label: t("menu.simulation.model_settings"),
      onClick: () => {
        setOpenMenu(null);
        setModal({ kind: "model-settings" });
      },
      disabled: !hasModel,
    },
  ];

  // 設定メニュー (アプリ全体に関わる設定。Language が現状唯一の項目)
  const settingsItems: MenuItemSpec[] = [
    { label: t("menu.settings.language"), disabled: true },
    {
      label: t("menu.settings.language.en"),
      language: "en",
      onClick: () => {
        setOpenMenu(null);
        void setLanguage("en");
      },
    },
    {
      label: t("menu.settings.language.ja"),
      language: "ja",
      onClick: () => {
        setOpenMenu(null);
        void setLanguage("ja");
      },
    },
  ];

  return (
    <div
      ref={ref}
      className="flex items-center gap-px border-b border-slate-300 bg-slate-100 px-1 text-[12px] text-slate-700"
    >
      <Menu
        label={t("menu.file")}
        open={openMenu === "File"}
        onToggle={() => setOpenMenu((m) => (m === "File" ? null : "File"))}
        onHover={() => openMenu && setOpenMenu("File")}
        items={fileItems}
        currentLang={lang}
      />
      <Menu
        label={t("menu.edit", "Edit")}
        open={openMenu === "Edit"}
        onToggle={() => setOpenMenu((m) => (m === "Edit" ? null : "Edit"))}
        onHover={() => openMenu && setOpenMenu("Edit")}
        items={editItems}
        currentLang={lang}
      />
      <Menu
        label={t("menu.view", "View")}
        open={openMenu === "View"}
        onToggle={() => setOpenMenu((m) => (m === "View" ? null : "View"))}
        onHover={() => openMenu && setOpenMenu("View")}
        items={viewItems}
        currentLang={lang}
      />
      <Menu
        label={t("menu.simulation")}
        open={openMenu === "Simulation"}
        onToggle={() =>
          setOpenMenu((m) => (m === "Simulation" ? null : "Simulation"))
        }
        onHover={() => openMenu && setOpenMenu("Simulation")}
        items={simulationItems}
        currentLang={lang}
      />
      <Menu
        label={t("menu.settings")}
        open={openMenu === "Settings"}
        onToggle={() =>
          setOpenMenu((m) => (m === "Settings" ? null : "Settings"))
        }
        onHover={() => openMenu && setOpenMenu("Settings")}
        items={settingsItems}
        currentLang={lang}
      />
      <Menu
        label={t("menu.help")}
        open={openMenu === "Help"}
        onToggle={() => setOpenMenu((m) => (m === "Help" ? null : "Help"))}
        onHover={() => openMenu && setOpenMenu("Help")}
        items={helpItems}
        currentLang={lang}
      />

      {/* dialogs */}
      {modal?.kind === "save-as-path" && selectedFilePath && (
        <SaveAsPathDialog
          defaultValue={selectedFilePath.replace(
            /(\.flw\.json)?$/,
            "_copy.flw.json",
          )}
          primaryLabel={t("modal.button.save_as")}
          onConfirm={(newPath) => void performSaveAsPath(newPath)}
          onClose={() => setModal(null)}
        />
      )}
      {modal?.kind === "model-settings" && (
        <ModelSettingsModal onClose={() => setModal(null)} />
      )}
      {modal?.kind === "shortcuts" && (
        <KeyboardShortcutsDialog onClose={() => setModal(null)} />
      )}
    </div>
  );
}

interface MenuProps {
  label: string;
  open: boolean;
  onToggle: () => void;
  onHover: () => void;
  items: readonly MenuItemSpec[];
  /** Language item のチェックマーク描画用 (現在言語と一致時に ✓)。 */
  currentLang: SupportedLanguage;
}

function Menu({
  label,
  open,
  onToggle,
  onHover,
  items,
  currentLang,
}: MenuProps): JSX.Element {
  return (
    <div className="relative">
      <button
        type="button"
        onClick={onToggle}
        onMouseEnter={onHover}
        className={`px-2.5 py-1 transition-colors ${
          open
            ? "bg-blue-600 text-white"
            : "hover:bg-slate-200"
        }`}
      >
        {label}
      </button>
      {open && (
        <div
          role="menu"
          className="absolute left-0 top-full z-30 min-w-[200px] border border-slate-300 bg-white py-0.5 shadow-md"
        >
          {items.map((item, i) =>
            item.divider ? (
              <div key={i} className="my-0.5 border-t border-slate-200" />
            ) : (
              <button
                key={i}
                type="button"
                onClick={item.onClick}
                disabled={item.disabled}
                className={`flex w-full items-center justify-between gap-4 px-3 py-1 text-left text-[12px] ${
                  item.disabled
                    ? "text-slate-400"
                    : item.destructive
                      ? "text-rose-600 hover:bg-rose-50"
                      : "text-slate-700 hover:bg-blue-600 hover:text-white"
                }`}
              >
                <span className="flex items-center gap-1.5">
                  {item.language && (
                    <span
                      aria-hidden
                      className={
                        item.language === currentLang
                          ? "text-blue-600"
                          : "text-transparent"
                      }
                    >
                      ✓
                    </span>
                  )}
                  <span>{item.label}</span>
                </span>
                {item.shortcut && (
                  <span
                    className={`font-mono text-[10px] ${
                      item.disabled ? "text-slate-300" : "text-slate-400"
                    }`}
                  >
                    {item.shortcut}
                  </span>
                )}
              </button>
            ),
          )}
        </div>
      )}
    </div>
  );
}
