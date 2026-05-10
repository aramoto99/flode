// VS Code 風タブストリップ。Phase 3 では「現在開いているモデル 1 件のタブ」のみ表示。
// 複数モデル並列オープンは Phase 4+ 送り (= 同じ UI で拡張可能な箱だけ用意)。

import { useTranslation } from "react-i18next";

import { useAppStore } from "../store/appStore";

export function TabStrip(): JSX.Element {
  const { t } = useTranslation();
  const selectedModelId = useAppStore((s) => s.selectedModelId);
  const selectedFilePath = useAppStore((s) => s.selectedFilePath);
  const dirty = useAppStore((s) => s.dirty);
  const selectModel = useAppStore((s) => s.selectModel);
  const selectFilePath = useAppStore((s) => s.selectFilePath);
  const setEditingModel = useAppStore((s) => s.setEditingModel);
  const setDirty = useAppStore((s) => s.setDirty);

  // ADR-0041 §論点 8-A: file path 優先で basename 表示、無ければ legacy id 表示
  const fullDisplay = selectedFilePath ?? selectedModelId;
  const tabLabel = selectedFilePath
    ? selectedFilePath.split("/").pop() || selectedFilePath
    : selectedModelId;

  const handleClose = (): void => {
    if (selectedFilePath !== null) {
      selectFilePath(null);
    } else {
      selectModel(null);
    }
    setEditingModel(null);
    setDirty(false);
  };

  return (
    <div className="flex items-end border-b border-slate-300 bg-slate-200/60 pl-1 pt-1">
      {fullDisplay ? (
        <div className="group relative flex max-w-[260px] items-center gap-2 border-l border-r border-t border-slate-300 bg-white px-3 py-1 text-[12px]">
          <DocIcon />
          <span
            className="truncate font-medium text-slate-800"
            title={fullDisplay}
          >
            {tabLabel}
          </span>
          {dirty && (
            <span
              className="text-amber-500"
              title={t("tabstrip.unsaved_title")}
              aria-label={t("tabstrip.unsaved_title")}
            >
              ●
            </span>
          )}
          <button
            type="button"
            onClick={handleClose}
            title={t("tabstrip.close")}
            className="ml-1 flex h-4 w-4 items-center justify-center rounded text-slate-400 hover:bg-slate-200 hover:text-slate-700"
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
      ) : (
        <span className="px-3 py-1 text-[11px] text-slate-400">
          {t("tabstrip.no_file")}
        </span>
      )}
    </div>
  );
}

function DocIcon(): JSX.Element {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-3.5 w-3.5 shrink-0 text-blue-600"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  );
}
