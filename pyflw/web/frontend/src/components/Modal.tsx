// 軽量 modal 群 (専用ライブラリを足さない最小限実装)。
// Open / Rename / Confirm の 3 用途を 1 ファイルにまとめる。
// 共通動作: Escape で cancel、外クリックで cancel、Enter で primary action。

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { dialog } from "../lib/dialogService";

interface ModalShellProps {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  width?: string;
}

export function ModalShell({ title, onClose, children, width = "w-[420px]" }: ModalShellProps): JSX.Element {
  const { t } = useTranslation();
  useEffect(() => {
    const handler = (e: KeyboardEvent): void => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className={`${width} rounded-lg border border-slate-200 bg-white shadow-2xl`}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2.5">
          <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 transition-colors hover:text-slate-700"
            aria-label={t("modal.close")}
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SaveAsPathDialog (ADR-0041 §論点 10-A 簡易版)
// ---------------------------------------------------------------------------

interface SaveAsPathDialogProps {
  /** 既定値 (例: "controllers/pid_copy.flw.json") */
  defaultValue: string;
  /** 既存 path との衝突判定 (= 上書き確認は OS dialog 互換で別途 confirm) */
  existingPaths?: readonly string[];
  primaryLabel: string;
  onConfirm: (newPath: string) => void;
  onClose: () => void;
}

/**
 * File API モードの Save As 用 path 入力ダイアログ。``window.prompt`` の置換。
 *
 * v0.19.0 では単純な text input のみ。FileBrowser 込みの mini-dialog
 * (= ADR §論点 10-A 完全版) は v0.20.0 以降で検討。
 */
export function SaveAsPathDialog({
  defaultValue,
  existingPaths = [],
  primaryLabel,
  onConfirm,
  onClose,
}: SaveAsPathDialogProps): JSX.Element {
  const { t } = useTranslation();
  const [value, setValue] = useState(defaultValue);
  const trimmed = value.trim();
  // 妥当性: 空 / null byte / 制御文字 / 先頭 ``/`` / ``\`` を弾く (= backend 側
  // ``resolve_workspace_path`` でも検証されるが、UX としては入力時点で示す)
  const invalid =
    trimmed.length === 0 ||
    /[\x00-\x1f\\]/.test(trimmed) ||
    trimmed.startsWith("/");
  const conflict = !invalid && existingPaths.includes(trimmed);
  // 上書き確認: conflict は warning 表示、submit 時に confirm する
  const disabled = invalid;

  const handleSubmit = async (): Promise<void> => {
    if (disabled) return;
    if (conflict) {
      const ok = await dialog.confirm(
        t("modal.save_as.overwrite_confirm", {
          defaultValue: `Overwrite "${trimmed}"?`,
          path: trimmed,
        }),
        { variant: "danger" },
      );
      if (!ok) return;
    }
    onConfirm(trimmed);
  };

  return (
    <ModalShell
      title={t("modal.save_as.title", { defaultValue: "Save As" })}
      onClose={onClose}
    >
      <div className="flex flex-col gap-2 p-4">
        <label className="flex flex-col gap-1 text-xs text-slate-600">
          {t("modal.save_as.label", {
            defaultValue: "Workspace-relative path (POSIX, e.g. controllers/foo.flw.json):",
          })}
          <input
            autoFocus
            type="text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onFocus={(e) => {
              // 既定値の拡張子前 stem を選択 (= JupyterLab 流儀)
              const ext = defaultValue.lastIndexOf(".flw.json");
              const stemEnd = ext > 0 ? ext : defaultValue.length;
              e.target.setSelectionRange(0, stemEnd);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !disabled) void handleSubmit();
            }}
            spellCheck={false}
            className="rounded-md border border-slate-300 bg-slate-50 px-2.5 py-1.5 font-mono text-sm focus:border-blue-500 focus:bg-white focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </label>
        {invalid && trimmed.length > 0 && (
          <span className="text-[11px] text-rose-600">
            {t("modal.save_as.invalid", {
              defaultValue:
                "Path contains forbidden characters (backslash, control chars, leading slash).",
            })}
          </span>
        )}
        {!invalid && conflict && (
          <span className="text-[11px] text-amber-600">
            {t("modal.save_as.conflict", {
              defaultValue:
                'A file already exists at this path. Submitting will ask for overwrite confirmation.',
            })}
          </span>
        )}
      </div>
      <div className="flex justify-end gap-2 border-t border-slate-100 bg-slate-50/50 px-3 py-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded-md px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-200"
        >
          {t("modal.button.cancel")}
        </button>
        <button
          type="button"
          onClick={() => void handleSubmit()}
          disabled={disabled}
          className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:bg-slate-300"
        >
          {primaryLabel}
        </button>
      </div>
    </ModalShell>
  );
}

// ---------------------------------------------------------------------------
// DirtyConfirmDialog (ADR-0041 §論点 9-A)
// ---------------------------------------------------------------------------

interface DirtyConfirmDialogProps {
  /** 現在編集中のファイル path / id (= 失われる可能性のある変更の対象) */
  currentName: string;
  /** これから開こうとしているファイル */
  nextName: string;
  /** 「破棄して開く」を選んだ場合に呼ばれる */
  onDiscard: () => void;
  /** 「保存して開く」を選んだ場合に呼ばれる (= 保存処理は呼び出し側で実装) */
  onSaveAndOpen: () => void;
  /** ダイアログ自体を閉じる (= キャンセル) */
  onClose: () => void;
}

/**
 * dirty 状態で別ファイルを開こうとしたときの 3-button 確認モーダル。
 * ``window.confirm`` の 2-button 版を置換。
 */
export function DirtyConfirmDialog({
  currentName,
  nextName,
  onDiscard,
  onSaveAndOpen,
  onClose,
}: DirtyConfirmDialogProps): JSX.Element {
  const { t } = useTranslation();
  return (
    <ModalShell
      title={t("modal.dirty_confirm.title", {
        defaultValue: "Unsaved changes",
      })}
      onClose={onClose}
    >
      <div className="p-4 text-sm text-slate-700">
        <p className="mb-2">
          {t("modal.dirty_confirm.message", {
            defaultValue:
              'You have unsaved changes in "{{currentName}}". Open "{{nextName}}" anyway?',
            currentName,
            nextName,
          })}
        </p>
      </div>
      <div className="flex justify-end gap-2 border-t border-slate-100 bg-slate-50/50 px-3 py-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded-md px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-200"
        >
          {t("modal.button.cancel")}
        </button>
        <button
          type="button"
          onClick={onDiscard}
          className="rounded-md bg-rose-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-700"
        >
          {t("modal.dirty_confirm.discard", {
            defaultValue: "Discard changes",
          })}
        </button>
        <button
          type="button"
          onClick={onSaveAndOpen}
          className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
        >
          {t("modal.dirty_confirm.save_and_open", {
            defaultValue: "Save & Open",
          })}
        </button>
      </div>
    </ModalShell>
  );
}

// ---------------------------------------------------------------------------
// AboutDialog (v0.20.0)
// ---------------------------------------------------------------------------

interface AboutDialogProps {
  onClose: () => void;
}

/**
 * pyflw の About ダイアログ (= MenuBar Help > About から開く)。
 * バージョン / GitHub link / license をシンプルに表示。
 */
export function AboutDialog({ onClose }: AboutDialogProps): JSX.Element {
  const { t } = useTranslation();
  return (
    <ModalShell
      title={t("modal.about.title", { defaultValue: "About pyflw" })}
      onClose={onClose}
      width="w-[400px]"
    >
      <div className="flex flex-col gap-3 p-5 text-sm text-slate-700">
        <div className="flex items-center gap-3">
          <div className="text-3xl font-bold tracking-tight text-blue-600">
            pyflw
          </div>
          <div className="font-mono text-sm text-slate-500">
            v{__APP_VERSION__}
          </div>
        </div>
        <p className="text-[12px] text-slate-600">
          {t("modal.about.description", {
            defaultValue:
              "Block-diagram dynamic system simulator (Simulink-inspired).",
          })}
        </p>
        <div className="flex flex-col gap-1 text-[12px]">
          <a
            href="https://github.com/aramoto99/pyflw"
            target="_blank"
            rel="noreferrer"
            className="text-blue-600 hover:underline"
          >
            github.com/aramoto99/pyflw
          </a>
          <span className="text-slate-500">
            {t("modal.about.license", { defaultValue: "MIT License" })}
          </span>
        </div>
      </div>
      <div className="flex justify-end border-t border-slate-100 bg-slate-50/50 px-3 py-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
        >
          {t("modal.button.close", { defaultValue: "Close" })}
        </button>
      </div>
    </ModalShell>
  );
}

// ---------------------------------------------------------------------------
// KeyboardShortcutsDialog (v0.20.0)
// ---------------------------------------------------------------------------

interface ShortcutRow {
  keys: string;
  description: string;
}

interface KeyboardShortcutsDialogProps {
  onClose: () => void;
}

/**
 * 主要キーボードショートカット一覧モーダル (= Help > Keyboard shortcuts から
 * 開く)。``useShortcuts.ts`` の実装と一致させる。
 */
export function KeyboardShortcutsDialog({
  onClose,
}: KeyboardShortcutsDialogProps): JSX.Element {
  const { t } = useTranslation();

  const sections: { title: string; rows: ShortcutRow[] }[] = [
    {
      title: t("modal.shortcuts.section.file"),
      rows: [
        { keys: "Ctrl+N", description: t("modal.shortcuts.desc.new_file") },
        { keys: "Ctrl+O", description: t("modal.shortcuts.desc.open") },
        { keys: "Ctrl+S", description: t("modal.shortcuts.desc.save") },
        { keys: "Ctrl+Shift+S", description: t("modal.shortcuts.desc.save_as") },
      ],
    },
    {
      title: t("modal.shortcuts.section.edit"),
      rows: [
        { keys: "Ctrl+Z", description: t("modal.shortcuts.desc.undo") },
        { keys: "Ctrl+Shift+Z / Ctrl+Y", description: t("modal.shortcuts.desc.redo") },
        { keys: "Ctrl+X", description: t("modal.shortcuts.desc.cut") },
        { keys: "Ctrl+C", description: t("modal.shortcuts.desc.copy") },
        { keys: "Ctrl+V", description: t("modal.shortcuts.desc.paste") },
        { keys: "Ctrl+A", description: t("modal.shortcuts.desc.select_all") },
        { keys: "Delete / Backspace", description: t("modal.shortcuts.desc.delete") },
        { keys: "Ctrl+I", description: t("modal.shortcuts.desc.flip_block") },
      ],
    },
    {
      title: t("modal.shortcuts.section.navigation"),
      rows: [
        { keys: "Enter", description: t("modal.shortcuts.desc.drill_in") },
        { keys: "Esc", description: t("modal.shortcuts.desc.drill_up") },
        { keys: "F2", description: t("modal.shortcuts.desc.rename_file") },
      ],
    },
    {
      title: t("modal.shortcuts.section.connect", {
        defaultValue: "Connection",
      }),
      rows: [
        {
          keys: "Ctrl+Click block → Ctrl+Click block",
          description: t("modal.shortcuts.desc.auto_connect", {
            defaultValue: "Connect block A.out[0] → block B.in[0]",
          }),
        },
        {
          keys: "Drag from edge → Drop on block",
          description: t("modal.shortcuts.desc.drag_branch", {
            defaultValue:
              "Branch from any point on a wire to block.in[0] (Simulink-style)",
          }),
        },
        {
          keys: "Ctrl+Click edge → Ctrl+Click block",
          description: t("modal.shortcuts.desc.branch_connect", {
            defaultValue: "Branch from existing wire to block.in[0]",
          }),
        },
      ],
    },
    {
      title: t("modal.shortcuts.section.simulation"),
      rows: [
        { keys: "Ctrl+T / F9", description: t("modal.shortcuts.desc.run") },
        { keys: "Ctrl+Shift+T / Shift+F9", description: t("modal.shortcuts.desc.stop") },
      ],
    },
  ];

  return (
    <ModalShell
      title={t("modal.shortcuts.title", {
        defaultValue: "Keyboard shortcuts",
      })}
      onClose={onClose}
      width="w-[520px]"
    >
      <div className="flex max-h-[70vh] flex-col gap-4 overflow-y-auto p-5 text-[12px] text-slate-700">
        {sections.map((sec) => (
          <div key={sec.title}>
            <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
              {sec.title}
            </h3>
            <table className="w-full">
              <tbody>
                {sec.rows.map((r) => (
                  <tr key={r.keys} className="border-t border-slate-100">
                    <td className="w-[200px] py-1 pr-3 font-mono text-[11px] text-slate-600">
                      {r.keys}
                    </td>
                    <td className="py-1 text-slate-700">{r.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
      <div className="flex justify-end border-t border-slate-100 bg-slate-50/50 px-3 py-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
        >
          {t("modal.button.close", { defaultValue: "Close" })}
        </button>
      </div>
    </ModalShell>
  );
}

