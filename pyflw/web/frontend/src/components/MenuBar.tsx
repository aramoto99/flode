// デスクトップ風 MenuBar (File / View / Simulation / Help)。
// Simulink + MATLAB の上部メニュー帯に倣う。
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
  nextUntitledFilePath,
  putFileContent,
} from "../api/filesApi";
import {
  currentLanguage,
  setLanguage,
  type SupportedLanguage,
} from "../i18n";
import { useAppStore } from "../store/appStore";
import type { FlwModel } from "../types/api";
import {
  AboutDialog,
  KeyboardShortcutsDialog,
  SaveAsPathDialog,
} from "./Modal";
import { ModelSettingsModal } from "./ModelSettingsModal";

type DialogKind =
  | { kind: "save-as-path" }
  | { kind: "model-settings" }
  | { kind: "about" }
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
  // ADR-0024 §(4): View > Language サブメニュー用
  language?: SupportedLanguage;
}

export function MenuBar(): JSX.Element {
  const { t, i18n: _i18n } = useTranslation();
  const lang = currentLanguage();
  void _i18n;
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [dialog, setDialog] = useState<DialogKind>(null);
  const ref = useRef<HTMLDivElement>(null);

  const selectedFilePath = useAppStore((s) => s.selectedFilePath);
  const selectFilePath = useAppStore((s) => s.selectFilePath);
  const setEditingModel = useAppStore((s) => s.setEditingModel);
  const setEditingFileMeta = useAppStore((s) => s.setEditingFileMeta);
  const setDirty = useAppStore((s) => s.setDirty);
  const editingModel = useAppStore((s) => s.editingModel);

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
    try {
      const path = await nextUntitledFilePath();
      const empty = emptyModel(path.replace(/\.flw\.json$/, ""));
      await putFileContent(path, empty);
      const data = await getFileContent(path);
      selectFilePath(path);
      setEditingModel(data.content);
      setEditingFileMeta(data.mtime, data.etag);
      setDirty(false);
      await queryClient.invalidateQueries({ queryKey: ["files-tree"] });
    } catch (e) {
      console.error("New file failed:", e);
      window.alert(`Create failed: ${(e as Error).message}`);
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
    setDialog({ kind: "save-as-path" });
  };

  const performSaveAsPath = async (newPath: string): Promise<void> => {
    if (!editingModel) {
      setDialog(null);
      return;
    }
    try {
      const resp = await putFileContent(newPath, editingModel);
      const data = await getFileContent(newPath);
      selectFilePath(newPath);
      setEditingModel(data.content);
      setEditingFileMeta(resp.mtime, resp.etag);
      setDirty(false);
      await queryClient.invalidateQueries({ queryKey: ["files-tree"] });
      setDialog(null);
    } catch (e) {
      console.error("Save As failed:", e);
      window.alert(`Save As failed: ${(e as Error).message}`);
    }
  };

  const handleDelete = async (): Promise<void> => {
    setOpenMenu(null);
    if (selectedFilePath === null) return;
    const ok = window.confirm(
      t("filebrowser.confirm_delete", "Delete {{path}}?", {
        path: selectedFilePath,
      }),
    );
    if (!ok) return;
    try {
      await deleteFile(selectedFilePath);
      selectFilePath(null);
      setEditingModel(null);
      setDirty(false);
      await queryClient.invalidateQueries({ queryKey: ["files-tree"] });
    } catch (e) {
      console.error("Delete failed:", e);
      window.alert(`Delete failed: ${(e as Error).message}`);
    }
  };

  const handleClose = (): void => {
    setOpenMenu(null);
    selectFilePath(null);
    setEditingModel(null);
    setDirty(false);
  };

  // ---- keyboard shortcuts: Ctrl+N ----
  // Ctrl+O は legacy Open dialog 用だったが v0.21.0 で削除済 → 現状は無効。
  // Ctrl+S は useAutoSave 側で扱う。
  useEffect(() => {
    const handler = (e: KeyboardEvent): void => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "n") {
        e.preventDefault();
        void handleNew();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const hasModel = selectedFilePath !== null;

  // ---- Menu definitions ----
  const fileItems: MenuItemSpec[] = [
    { label: t("menu.file.new"), shortcut: "Ctrl+N", onClick: () => void handleNew() },
    { label: t("menu.file.open"), shortcut: "Ctrl+O", onClick: handleOpen, disabled: true },
    { label: "", divider: true },
    {
      label: t("menu.file.save"),
      shortcut: "Ctrl+S",
      onClick: handleSave,
      disabled: !hasModel,
    },
    { label: t("menu.file.save_as"), onClick: handleSaveAs, disabled: !hasModel },
    { label: "", divider: true },
    { label: t("menu.file.close"), onClick: handleClose, disabled: !hasModel },
    {
      label: t("menu.file.delete"),
      onClick: () => void handleDelete(),
      disabled: !hasModel,
      destructive: true,
    },
  ];

  // v0.20.0: Help メニュー
  const helpItems: MenuItemSpec[] = [
    {
      label: t("menu.help.about", { defaultValue: "About pyflw" }),
      onClick: () => {
        setOpenMenu(null);
        setDialog({ kind: "about" });
      },
    },
    {
      label: t("menu.help.documentation", { defaultValue: "Documentation" }),
      onClick: () => {
        setOpenMenu(null);
        window.open(
          "https://github.com/aramoto99/pyflw",
          "_blank",
          "noopener,noreferrer",
        );
      },
    },
    {
      label: t("menu.help.shortcuts", { defaultValue: "Keyboard shortcuts" }),
      onClick: () => {
        setOpenMenu(null);
        setDialog({ kind: "shortcuts" });
      },
    },
  ];

  // Simulation メニュー
  const simulationItems: MenuItemSpec[] = [
    {
      label: t("menu.simulation.model_settings"),
      onClick: () => {
        setOpenMenu(null);
        setDialog({ kind: "model-settings" });
      },
      disabled: !hasModel,
    },
  ];

  // ADR-0024 §(4): View > Language
  const viewItems: MenuItemSpec[] = [
    { label: t("menu.view.language"), disabled: true },
    {
      label: t("menu.view.language.en"),
      language: "en",
      onClick: () => {
        setOpenMenu(null);
        void setLanguage("en");
      },
    },
    {
      label: t("menu.view.language.ja"),
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
        label={t("menu.view")}
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
        label={t("menu.help")}
        open={openMenu === "Help"}
        onToggle={() => setOpenMenu((m) => (m === "Help" ? null : "Help"))}
        onHover={() => openMenu && setOpenMenu("Help")}
        items={helpItems}
        currentLang={lang}
      />

      {/* dialogs */}
      {dialog?.kind === "save-as-path" && selectedFilePath && (
        <SaveAsPathDialog
          defaultValue={selectedFilePath.replace(
            /(\.flw\.json)?$/,
            "_copy.flw.json",
          )}
          primaryLabel={t("modal.button.save_as")}
          onConfirm={(newPath) => void performSaveAsPath(newPath)}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog?.kind === "model-settings" && (
        <ModelSettingsModal onClose={() => setDialog(null)} />
      )}
      {dialog?.kind === "about" && (
        <AboutDialog onClose={() => setDialog(null)} />
      )}
      {dialog?.kind === "shortcuts" && (
        <KeyboardShortcutsDialog onClose={() => setDialog(null)} />
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
