// デスクトップ風 MenuBar (File / View / Simulation / Help)。
// 業界標準ブロック線図ツール + 数値計算 IDE の上部メニュー帯に倣う。
//
// v0.21.0 (ADR-0041 §論点 4-A): legacy ``--model-dir`` / ``selectedModelId``
// 経路を撤去、File API (= ``selectedFilePath``) 一本化。File メニューは New /
// Open / Save / Save As / Close / Delete を全て File API 経由で操作する。

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
import {
  clearRecentFiles,
  readRecentFiles,
  removeRecentFile,
} from "../lib/recentFiles";
import { dialog } from "../lib/dialogService";
import { useAppStore } from "../store/appStore";
import type { FlwModel } from "../types/api";
import { KeyboardShortcutsDialog, SaveAsPathDialog } from "./Modal";
import { ModelSettingsModal } from "./ModelSettingsModal";

type DialogKind =
  | { kind: "save-as-path" }
  | { kind: "model-settings" }
  | { kind: "shortcuts" }
  | null;

// ADR-0036 (v0.7) + ADR-0039 (v2.0、schema 0.8): 新規モデル作成時の初期
// schema_version。
const CURRENT_SCHEMA_VERSION = "0.8";

function emptyModel(name: string): FlwModel {
  return {
    schema_version: CURRENT_SCHEMA_VERSION,
    metadata: { name, tool: "pyflw GUI" },
    simulator: {
      t_end: 10.0,
      dt: 0.01,
      solver: "RK45",
      rtol: 1e-3,
      atol: 1e-6,
      dt_base: null,
    },
    blocks: [],
    connections: [],
    layout: {},
  };
}

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
    // ユーザーに明示要求 (Launcher と同じ挙動)。
    const input = await dialog.prompt(
      t("launcher.prompt_new", "New file name (.flw.json):"),
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

  // Open は FileBrowser の tree クリックで担当 (= legacy OpenModelDialog 撤去)
  const handleOpen = (): void => {
    setOpenMenu(null);
    // TODO(v3.x): File API 版 OpenModelDialog (= mini FileBrowser tree) を
    // 実装する案 (ADR-0041 §論点 10-A 完全版)。現状は左サイドバーの
    // FileBrowser から直接 tree を辿って開く UX に集約。
  };

  const handleSave = (): void => {
    setOpenMenu(null);
    // useAutoSave の Ctrl+S handler が File API 経由で flush する。本ハンドラは
    // メニュークリックで明示的に flush する場合のみ動かす — ただし dirty なら
    // すでに 500ms debounce で auto-save される、メニューからの即時保存も
    // useAutoSave を経由させる方が二重保存を避けられる。
    // 簡略化: 何もせず、ユーザーが Ctrl+S を使う方向に誘導する。実装は
    // useAutoSave 側の keydown handler を維持。
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
      // preventDefault で pyflw を優先。selectedFilePath は空依存 useEffect の
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

  const handleRemoveRecent = (path: string): void => {
    if (!workspaceHash) return;
    removeRecentFile(workspaceHash, path);
    setRecentRev((r) => r + 1);
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
    { label: t("menu.file.open"), onClick: handleOpen, disabled: true },
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
  ];
  void handleRemoveRecent; // 個別削除は v3.x 以降の UI 拡張で再導入

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

  // Simulation メニュー
  const simulationItems: MenuItemSpec[] = [
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
