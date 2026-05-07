// デスクトップ風 MenuBar (File / Edit / View / Simulation / Help)。
// Simulink + MATLAB の上部メニュー帯に倣う。今は File menu のみ実装、それ以外は
// 開いた瞬間に「(empty / coming soon)」を出す placeholder。

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  copyModel,
  createModel,
  deleteModel,
  listModels,
  nextUntitledName,
  updateModel,
} from "../api/client";
import { useAppStore } from "../store/appStore";
import type { FlwModel } from "../types/api";
import {
  ConfirmDialog,
  OpenModelDialog,
  RenameDialog,
} from "./Modal";

type DialogKind =
  | { kind: "open" }
  | { kind: "save-as" }
  | { kind: "rename" }
  | { kind: "delete" }
  | null;

function emptyModel(name: string): FlwModel {
  return {
    schema_version: "0.6",
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
}

export function MenuBar(): JSX.Element {
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
    { label: "New", shortcut: "Ctrl+N", onClick: handleNew },
    { label: "Open…", shortcut: "Ctrl+O", onClick: handleOpen },
    { label: "", divider: true },
    {
      label: "Save",
      shortcut: "Ctrl+S",
      onClick: handleSave,
      disabled: !hasModel,
    },
    { label: "Save As…", onClick: handleSaveAs, disabled: !hasModel },
    { label: "Rename…", onClick: handleRename, disabled: !hasModel },
    { label: "", divider: true },
    { label: "Close", onClick: handleClose, disabled: !hasModel },
    {
      label: "Delete…",
      onClick: handleDelete,
      disabled: !hasModel,
      destructive: true,
    },
  ];
  // Edit / View / Simulation / Help は placeholder (Phase 4+)
  const placeholder: MenuItemSpec[] = [
    { label: "(no actions yet)", disabled: true },
  ];

  return (
    <div
      ref={ref}
      className="flex items-center gap-px border-b border-slate-300 bg-slate-100 px-1 text-[12px] text-slate-700"
    >
      <Menu
        label="File"
        open={openMenu === "File"}
        onToggle={() => setOpenMenu((m) => (m === "File" ? null : "File"))}
        onHover={() => openMenu && setOpenMenu("File")}
        items={fileItems}
      />
      <Menu
        label="Edit"
        open={openMenu === "Edit"}
        onToggle={() => setOpenMenu((m) => (m === "Edit" ? null : "Edit"))}
        onHover={() => openMenu && setOpenMenu("Edit")}
        items={placeholder}
      />
      <Menu
        label="View"
        open={openMenu === "View"}
        onToggle={() => setOpenMenu((m) => (m === "View" ? null : "View"))}
        onHover={() => openMenu && setOpenMenu("View")}
        items={placeholder}
      />
      <Menu
        label="Simulation"
        open={openMenu === "Simulation"}
        onToggle={() =>
          setOpenMenu((m) => (m === "Simulation" ? null : "Simulation"))
        }
        onHover={() => openMenu && setOpenMenu("Simulation")}
        items={placeholder}
      />
      <Menu
        label="Help"
        open={openMenu === "Help"}
        onToggle={() => setOpenMenu((m) => (m === "Help" ? null : "Help"))}
        onHover={() => openMenu && setOpenMenu("Help")}
        items={placeholder}
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
          title="Save As"
          defaultValue={`${selectedModelId}_copy`}
          forbiddenIds={models}
          primaryLabel="Save As"
          onConfirm={(newName) => performSaveAs.mutate(newName)}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog?.kind === "rename" && selectedModelId && (
        <RenameDialog
          title="Rename Model"
          defaultValue={selectedModelId}
          forbiddenIds={models.filter((m) => m !== selectedModelId)}
          primaryLabel="Rename"
          onConfirm={(newName) => performRename.mutate(newName)}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog?.kind === "delete" && selectedModelId && (
        <ConfirmDialog
          title="Delete Model"
          message={`Permanently delete "${selectedModelId}.flw.json"?`}
          primaryLabel="Delete"
          destructive
          onConfirm={() => performDelete.mutate()}
          onClose={() => setDialog(null)}
        />
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
}

function Menu({ label, open, onToggle, onHover, items }: MenuProps): JSX.Element {
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
                <span>{item.label}</span>
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
