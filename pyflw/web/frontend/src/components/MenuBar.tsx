// デスクトップ風 MenuBar (File / Edit / View / Simulation / Help)。
// Simulink + MATLAB の上部メニュー帯に倣う。今は File menu のみ実装、それ以外は
// 開いた瞬間に「(empty / coming soon)」を出す placeholder。

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  copyModel,
  createModel,
  deleteModel,
  listModels,
  nextUntitledName,
  updateModel,
} from "../api/client";
import {
  currentLanguage,
  setLanguage,
  type SupportedLanguage,
} from "../i18n";
import { useAppStore } from "../store/appStore";
import type { FlwModel } from "../types/api";
import {
  ConfirmDialog,
  OpenModelDialog,
  RenameDialog,
} from "./Modal";
import { ModelSettingsModal } from "./ModelSettingsModal";

type DialogKind =
  | { kind: "open" }
  | { kind: "save-as" }
  | { kind: "rename" }
  | { kind: "delete" }
  | { kind: "model-settings" }
  | null;

// ADR-0036 (v0.7) + ADR-0039 (v2.0、schema 0.8): 新規モデル作成時の初期
// schema_version。backend の ``CURRENT_SCHEMA_VERSION`` と揃える (= ズレが
// あっても backend `migrate_to_current` で自動補正されるが、無駄な変換を避ける)。
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
  // ADR-0024 §(4): View > Language サブメニュー用。値が現在言語と一致していれば
  // チェックマークを描画する。`language` 指定時は disabled / shortcut は無視。
  language?: SupportedLanguage;
}

export function MenuBar(): JSX.Element {
  const { t, i18n: _i18n } = useTranslation();
  // ADR-0024: useTranslation を購読することで changeLanguage 後に再 render される。
  // ``currentLanguage()`` は BCP47 タグ (例 ``en-US``) を ``en``/``ja`` に正規化する。
  const lang = currentLanguage();
  void _i18n; // 購読のためだけに参照
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [dialog, setDialog] = useState<DialogKind>(null);
  const ref = useRef<HTMLDivElement>(null);

  const selectedModelId = useAppStore((s) => s.selectedModelId);
  const selectModel = useAppStore((s) => s.selectModel);
  const setEditingModel = useAppStore((s) => s.setEditingModel);
  const setDirty = useAppStore((s) => s.setDirty);
  const editingModel = useAppStore((s) => s.editingModel);

  const queryClient = useQueryClient();
  const { data: modelsList } = useQuery({
    queryKey: ["models"],
    queryFn: listModels,
  });
  const models = modelsList?.models ?? [];

  useEffect(() => {
    const handler = (e: MouseEvent): void => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpenMenu(null);
      }
    };
    if (openMenu) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [openMenu]);

  // ---- File actions ----
  const newMutation = useMutation({
    mutationFn: async () => {
      const name = await nextUntitledName();
      const resp = await createModel(emptyModel(name));
      return resp.model_id;
    },
    onSuccess: async (newId) => {
      await queryClient.invalidateQueries({ queryKey: ["models"] });
      selectModel(newId);
    },
  });

  const performSaveAs = useMutation({
    mutationFn: (newName: string) => {
      if (!selectedModelId) throw new Error("No current model");
      return copyModel(selectedModelId, newName, { deleteOriginal: false });
    },
    onSuccess: async (newId) => {
      await queryClient.invalidateQueries({ queryKey: ["models"] });
      selectModel(newId);
      setDialog(null);
    },
  });

  const performRename = useMutation({
    mutationFn: (newName: string) => {
      if (!selectedModelId) throw new Error("No current model");
      return copyModel(selectedModelId, newName, { deleteOriginal: true });
    },
    onSuccess: async (newId) => {
      await queryClient.invalidateQueries({ queryKey: ["models"] });
      selectModel(newId);
      setDialog(null);
    },
  });

  const performDelete = useMutation({
    mutationFn: () => {
      if (!selectedModelId) throw new Error("No current model");
      return deleteModel(selectedModelId);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["models"] });
      selectModel(null);
      setEditingModel(null);
      setDirty(false);
      setDialog(null);
    },
  });

  const handleNew = (): void => {
    setOpenMenu(null);
    newMutation.mutate();
  };
  const handleOpen = (): void => {
    setOpenMenu(null);
    setDialog({ kind: "open" });
  };
  const handleSave = async (): Promise<void> => {
    setOpenMenu(null);
    if (!selectedModelId || !editingModel) return;
    await updateModel(selectedModelId, editingModel);
    setDirty(false);
    await queryClient.invalidateQueries({
      queryKey: ["model", selectedModelId],
    });
  };
  const handleSaveAs = (): void => {
    setOpenMenu(null);
    if (!selectedModelId) return;
    setDialog({ kind: "save-as" });
  };
  const handleRename = (): void => {
    setOpenMenu(null);
    if (!selectedModelId) return;
    setDialog({ kind: "rename" });
  };
  const handleDelete = (): void => {
    setOpenMenu(null);
    if (!selectedModelId) return;
    setDialog({ kind: "delete" });
  };
  const handleClose = (): void => {
    setOpenMenu(null);
    selectModel(null);
    setEditingModel(null);
    setDirty(false);
  };

  // ---- keyboard shortcuts: Ctrl+N / Ctrl+O ----
  useEffect(() => {
    const handler = (e: KeyboardEvent): void => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "n") {
        e.preventDefault();
        handleNew();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "o") {
        e.preventDefault();
        handleOpen();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const hasModel = selectedModelId !== null;

  // ---- Menu definitions ----
  const fileItems: MenuItemSpec[] = [
    { label: t("menu.file.new"), shortcut: "Ctrl+N", onClick: handleNew },
    { label: t("menu.file.open"), shortcut: "Ctrl+O", onClick: handleOpen },
    { label: "", divider: true },
    {
      label: t("menu.file.save"),
      shortcut: "Ctrl+S",
      onClick: handleSave,
      disabled: !hasModel,
    },
    { label: t("menu.file.save_as"), onClick: handleSaveAs, disabled: !hasModel },
    { label: t("menu.file.rename"), onClick: handleRename, disabled: !hasModel },
    { label: "", divider: true },
    { label: t("menu.file.close"), onClick: handleClose, disabled: !hasModel },
    {
      label: t("menu.file.delete"),
      onClick: handleDelete,
      disabled: !hasModel,
      destructive: true,
    },
  ];
  // Edit / Help は placeholder (Phase 4+ で項目追加予定)
  const placeholder: MenuItemSpec[] = [
    { label: t("menu.placeholder.empty"), disabled: true },
  ];
  // Simulation メニュー: v0.16.0 で Model Settings 追加。
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
  // ADR-0024 §(4): View メニューに Language の見出し行 + English / 日本語 を置く。
  // 見出しはクリック不可 (= disabled) で、項目をグルーピングする視覚 hint。
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
        label={t("menu.edit")}
        open={openMenu === "Edit"}
        onToggle={() => setOpenMenu((m) => (m === "Edit" ? null : "Edit"))}
        onHover={() => openMenu && setOpenMenu("Edit")}
        items={placeholder}
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
        items={placeholder}
        currentLang={lang}
      />

      {/* dialogs */}
      {dialog?.kind === "open" && (
        <OpenModelDialog
          models={models}
          currentId={selectedModelId}
          onOpen={(id) => {
            selectModel(id);
            setDialog(null);
          }}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog?.kind === "save-as" && selectedModelId && (
        <RenameDialog
          title={t("menu.file.save_as")}
          defaultValue={`${selectedModelId}_copy`}
          forbiddenIds={models}
          primaryLabel={t("modal.button.save_as")}
          onConfirm={(newName) => performSaveAs.mutate(newName)}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog?.kind === "rename" && selectedModelId && (
        <RenameDialog
          title={t("menu.file.rename")}
          defaultValue={selectedModelId}
          forbiddenIds={models.filter((m) => m !== selectedModelId)}
          primaryLabel={t("modal.button.rename")}
          onConfirm={(newName) => performRename.mutate(newName)}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog?.kind === "delete" && selectedModelId && (
        <ConfirmDialog
          title={t("modal.delete.title")}
          message={t("modal.delete.message", { name: selectedModelId })}
          primaryLabel={t("modal.button.delete")}
          destructive
          onConfirm={() => performDelete.mutate()}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog?.kind === "model-settings" && (
        <ModelSettingsModal onClose={() => setDialog(null)} />
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
