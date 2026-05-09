// 軽量 modal 群 (専用ライブラリを足さない最小限実装)。
// Open / Rename / Confirm の 3 用途を 1 ファイルにまとめる。
// 共通動作: Escape で cancel、外クリックで cancel、Enter で primary action。

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

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
// OpenModelDialog
// ---------------------------------------------------------------------------

interface OpenModelDialogProps {
  models: readonly string[];
  currentId: string | null;
  onOpen: (id: string) => void;
  onClose: () => void;
}

export function OpenModelDialog({
  models,
  currentId,
  onOpen,
  onClose,
}: OpenModelDialogProps): JSX.Element {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const filtered = models.filter((m) =>
    m.toLowerCase().includes(search.trim().toLowerCase()),
  );

  return (
    <ModalShell title={t("modal.open.title")} onClose={onClose}>
      <div className="p-3">
        <input
          autoFocus
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t("modal.open.filter")}
          className="w-full rounded-md border border-slate-300 bg-slate-50 px-2.5 py-1.5 text-xs placeholder:text-slate-400 focus:border-blue-500 focus:bg-white focus:outline-none focus:ring-1 focus:ring-blue-500"
          onKeyDown={(e) => {
            if (e.key === "Enter" && filtered.length > 0) {
              onOpen(filtered[0]!);
            }
          }}
        />
      </div>
      <div className="max-h-80 overflow-y-auto px-1.5 pb-2">
        {filtered.length === 0 ? (
          <div className="p-4 text-center text-xs text-slate-500">
            {models.length === 0
              ? t("modal.open.no_models")
              : t("modal.open.no_match")}
          </div>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {filtered.map((m) => (
              <li key={m}>
                <button
                  type="button"
                  onClick={() => onOpen(m)}
                  className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm transition-colors ${
                    currentId === m
                      ? "bg-blue-50 font-medium text-blue-800"
                      : "text-slate-700 hover:bg-slate-100"
                  }`}
                >
                  <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 shrink-0 text-slate-400" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                  </svg>
                  <span className="truncate">{m}</span>
                  {currentId === m && (
                    <span className="ml-auto text-[10px] uppercase tracking-wide text-blue-500">
                      {t("modal.open.current")}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </ModalShell>
  );
}

// ---------------------------------------------------------------------------
// RenameDialog (Rename / Save As 兼用)
// ---------------------------------------------------------------------------

interface RenameDialogProps {
  title: string;
  defaultValue: string;
  forbiddenIds?: readonly string[]; // 既存 id は重複防止
  primaryLabel: string;
  onConfirm: (newName: string) => void;
  onClose: () => void;
}

export function RenameDialog({
  title,
  defaultValue,
  forbiddenIds = [],
  primaryLabel,
  onConfirm,
  onClose,
}: RenameDialogProps): JSX.Element {
  const { t } = useTranslation();
  const [value, setValue] = useState(defaultValue);
  const trimmed = value.trim();
  const conflict =
    trimmed !== defaultValue && forbiddenIds.includes(trimmed);
  const invalid = trimmed.length === 0 || /[^A-Za-z0-9_\-.]/.test(trimmed);
  const disabled = invalid || conflict;

  return (
    <ModalShell title={title} onClose={onClose}>
      <div className="flex flex-col gap-2 p-4">
        <label className="flex flex-col gap-1 text-xs text-slate-600">
          {t("modal.rename.label")}
          <input
            autoFocus
            type="text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onFocus={(e) => e.target.select()}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !disabled) onConfirm(trimmed);
            }}
            className="rounded-md border border-slate-300 bg-slate-50 px-2.5 py-1.5 text-sm focus:border-blue-500 focus:bg-white focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </label>
        {invalid && (
          <span className="text-[11px] text-rose-600">
            {t("modal.rename.invalid")}
          </span>
        )}
        {!invalid && conflict && (
          <span className="text-[11px] text-rose-600">
            {t("modal.rename.conflict", { name: trimmed })}
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
          onClick={() => onConfirm(trimmed)}
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
// ConfirmDialog
// ---------------------------------------------------------------------------

interface ConfirmDialogProps {
  title: string;
  message: string;
  primaryLabel: string;
  destructive?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

export function ConfirmDialog({
  title,
  message,
  primaryLabel,
  destructive = false,
  onConfirm,
  onClose,
}: ConfirmDialogProps): JSX.Element {
  const { t } = useTranslation();
  return (
    <ModalShell title={title} onClose={onClose}>
      <div className="p-4 text-sm text-slate-700">{message}</div>
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
          onClick={onConfirm}
          className={`rounded-md px-3 py-1.5 text-xs font-medium text-white ${
            destructive
              ? "bg-rose-600 hover:bg-rose-700"
              : "bg-blue-600 hover:bg-blue-700"
          }`}
        >
          {primaryLabel}
        </button>
      </div>
    </ModalShell>
  );
}
