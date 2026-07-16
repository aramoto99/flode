// VS Code 風タブストリップ (ADR-0043 §論点 2 / §論点 6)。
// v0.23.0 で N タブ対応 (= 旧 1 タブ固定から拡張)。``tabs[]`` を順番に描画し、
// active を highlight、middle-click でタブ閉じ、Ctrl+Tab / Ctrl+Shift+Tab で
// 切替 (= グローバル keydown は ``App.tsx`` 側に置く)。
// v0.21.0 (ADR-0041 §論点 4-A): legacy ``selectedModelId`` 削除済、file path 一本化。

import { useTranslation } from "react-i18next";

import { useAppStore } from "../store/appStore";

export function TabStrip(): JSX.Element {
  const { t } = useTranslation();
  const tabs = useAppStore((s) => s.tabs);
  const activeTabFilePath = useAppStore((s) => s.activeTabFilePath);
  const selectedFilePath = useAppStore((s) => s.selectedFilePath);
  const dirty = useAppStore((s) => s.dirty);
  const switchTab = useAppStore((s) => s.switchTab);
  const closeTab = useAppStore((s) => s.closeTab);
  const selectFilePath = useAppStore((s) => s.selectFilePath);
  const setEditingModel = useAppStore((s) => s.setEditingModel);
  const setDirty = useAppStore((s) => s.setDirty);

  // ADR-0043 §論点 2: tabs[] が空でも selectedFilePath が non-null な「legacy
  // load」状態をフォールバック表示 (= 後方互換、useShortcuts 等が直接
  // selectFilePath を呼んだ場合)。
  const showLegacyTab = tabs.length === 0 && selectedFilePath !== null;

  const handleCloseLegacy = (): void => {
    selectFilePath(null);
    setEditingModel(null);
    setDirty(false);
  };

  const handleTabMouseDown = (
    e: React.MouseEvent<HTMLDivElement>,
    path: string,
  ): void => {
    // middle-click (= button === 1) でタブ閉じ
    if (e.button === 1) {
      e.preventDefault();
      closeTab(path);
    }
  };

  return (
    <div
      className="flex items-end overflow-x-auto border-b border-slate-300 bg-slate-200/60 pl-1 pt-1"
      role="tablist"
    >
      {showLegacyTab && (
        <TabItem
          path={selectedFilePath!}
          isActive={true}
          isDirty={dirty}
          onClick={() => {
            // legacy 単一タブ → no-op
          }}
          onClose={handleCloseLegacy}
          onMouseDown={() => {
            /* legacy: middle-click でも close handler を呼ぶ */
          }}
          unsavedTitle={t("tabstrip.unsaved_title")}
          closeTitle={t("tabstrip.close")}
        />
      )}
      {tabs.map((tab) => {
        const isActive = tab.filePath === activeTabFilePath;
        // active tab だけ "live" な dirty を反映、それ以外は snapshot 内 dirty
        const tabDirty = isActive ? dirty : tab.dirty;
        return (
          <TabItem
            key={tab.filePath}
            path={tab.filePath}
            isActive={isActive}
            isDirty={tabDirty}
            onClick={() => {
              if (!isActive) switchTab(tab.filePath);
            }}
            onClose={() => closeTab(tab.filePath)}
            onMouseDown={(e) => handleTabMouseDown(e, tab.filePath)}
            unsavedTitle={t("tabstrip.unsaved_title")}
            closeTitle={t("tabstrip.close")}
          />
        );
      })}
      {tabs.length === 0 && !showLegacyTab && (
        <span className="px-3 py-1 text-[11px] text-slate-400">
          {t("tabstrip.no_file")}
        </span>
      )}
    </div>
  );
}

interface TabItemProps {
  path: string;
  isActive: boolean;
  isDirty: boolean;
  onClick: () => void;
  onClose: () => void;
  onMouseDown: (e: React.MouseEvent<HTMLDivElement>) => void;
  unsavedTitle: string;
  closeTitle: string;
}

function TabItem({
  path,
  isActive,
  isDirty,
  onClick,
  onClose,
  onMouseDown,
  unsavedTitle,
  closeTitle,
}: TabItemProps): JSX.Element {
  const label = path.split("/").pop() || path;
  // ADR-0052 §(1) Stage 3: タブを drag できるようにする (= drag-to-split-tab)。
  // dataTransfer に FLODE_TAB_REF_MIME = filePath を載せ、WorkspaceSplit の
  // drop target がそれを受け取って split / タブ追加を実行する。
  const onDragStart = (e: React.DragEvent<HTMLDivElement>): void => {
    // 動的 import を避けるため import 文を top-level で。runtime constant。
    e.dataTransfer.setData("application/x-flode-tab-ref", path);
    e.dataTransfer.effectAllowed = "move";
  };
  return (
    <div
      role="tab"
      aria-selected={isActive}
      draggable
      onDragStart={onDragStart}
      onClick={onClick}
      onMouseDown={onMouseDown}
      className={`group relative flex max-w-[260px] cursor-pointer items-center gap-2 border-l border-r border-t px-3 py-1 text-[12px] ${
        isActive
          ? "border-slate-300 bg-white text-slate-800"
          : "border-transparent bg-slate-100 text-slate-600 hover:bg-slate-50"
      }`}
    >
      <DocIcon active={isActive} />
      <span className="truncate font-medium" title={path}>
        {label}
      </span>
      {isDirty && (
        <span
          className="text-amber-500"
          title={unsavedTitle}
          aria-label={unsavedTitle}
        >
          ●
        </span>
      )}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onClose();
        }}
        title={closeTitle}
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
  );
}

function DocIcon({ active }: { active: boolean }): JSX.Element {
  return (
    <svg
      viewBox="0 0 24 24"
      className={`h-3.5 w-3.5 shrink-0 ${active ? "text-blue-600" : "text-slate-400"}`}
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
