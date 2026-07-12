// ADR-0051 §(1) §(2): Workspace convergence Stage 2 = 列 0 = activity bar。
// 列 1 (left sidebar) の中身を「File / Library / Search」の 3 mode で切替する
// アイコンバー。固定幅 32 px、上から下へ縦並びの icon button + 選択 mode に
// 左 2 px の青い accent bar。
//
// **a11y**: `<div role="tablist" aria-orientation="vertical">` + 各 button =
// `<button role="tab" aria-selected aria-label>`。ネイティブデスクトップ風 UI ガイド
// 規律: pill button / switch toggle / segmented control 禁止、シンプルな
// 縦並び icon button のみ。

import { useTranslation } from "react-i18next";

import { useAppStore } from "../store/appStore";

type SidebarMode = "file" | "library" | "search";

export function ActivityBar(): JSX.Element {
  const { t } = useTranslation();
  const sidebarMode = useAppStore((s) => s.sidebarMode);
  const setSidebarMode = useAppStore((s) => s.setSidebarMode);
  const workspaceCollapsed = useAppStore((s) => s.workspaceCollapsed);
  const setWorkspaceCollapsed = useAppStore((s) => s.setWorkspaceCollapsed);

  // ActivityBar icon click: sidebar が collapsed なら open + mode 切替、open なら
  // (1) 別 mode クリックで mode 切替 / (2) 現 mode クリックで sidebar 閉じる
  const onActivate = (mode: SidebarMode): void => {
    if (workspaceCollapsed) {
      setWorkspaceCollapsed(false);
      setSidebarMode(mode);
      return;
    }
    if (sidebarMode === mode) {
      // 同 mode 再クリック = sidebar を閉じる (VSCode 流)
      setWorkspaceCollapsed(true);
      return;
    }
    setSidebarMode(mode);
  };

  return (
    <nav
      role="tablist"
      aria-orientation="vertical"
      aria-label={t("activity.aria.tablist")}
      className="flex h-full w-full flex-col items-center border-r border-slate-300 bg-slate-100 py-1"
    >
      <ActivityBarButton
        mode="file"
        currentMode={sidebarMode}
        collapsed={workspaceCollapsed}
        label={t("activity.file")}
        onClick={() => onActivate("file")}
      >
        <FileIcon />
      </ActivityBarButton>
      <ActivityBarButton
        mode="library"
        currentMode={sidebarMode}
        collapsed={workspaceCollapsed}
        label={t("activity.library")}
        onClick={() => onActivate("library")}
      >
        <LibraryIcon />
      </ActivityBarButton>
      <ActivityBarButton
        mode="search"
        currentMode={sidebarMode}
        collapsed={workspaceCollapsed}
        label={t("activity.search")}
        onClick={() => onActivate("search")}
      >
        <SearchIcon />
      </ActivityBarButton>
    </nav>
  );
}

function ActivityBarButton({
  mode,
  currentMode,
  collapsed,
  label,
  onClick,
  children,
}: {
  mode: SidebarMode;
  currentMode: SidebarMode;
  collapsed: boolean;
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}): JSX.Element {
  // selected = sidebar 展開中 + 当該 mode が現在選択中
  const selected = !collapsed && currentMode === mode;
  return (
    <button
      type="button"
      role="tab"
      aria-selected={selected}
      aria-label={label}
      title={label}
      onClick={onClick}
      data-testid={`activity-bar-${mode}`}
      className={
        selected
          ? "relative flex h-8 w-8 items-center justify-center text-slate-800"
          : "relative flex h-8 w-8 items-center justify-center text-slate-500 hover:bg-slate-200 hover:text-slate-800"
      }
    >
      {selected && (
        // selected accent bar = 左 2 px の青い縦線 (= VSCode 風)
        <span
          aria-hidden="true"
          className="absolute left-0 top-1 bottom-1 w-0.5 bg-blue-600"
        />
      )}
      {children}
    </button>
  );
}

// Inline SVG icons (= heroicons / lucide 風)、外部依存追加なし

function FileIcon(): JSX.Element {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-4 w-4"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
      <polyline points="14 3 14 9 20 9" />
    </svg>
  );
}

function LibraryIcon(): JSX.Element {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-4 w-4"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="3" y="3" width="7" height="7" />
      <rect x="14" y="3" width="7" height="7" />
      <rect x="3" y="14" width="7" height="7" />
      <rect x="14" y="14" width="7" height="7" />
    </svg>
  );
}

function SearchIcon(): JSX.Element {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-4 w-4"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="11" cy="11" r="7" />
      <line x1="21" y1="21" x2="16.5" y2="16.5" />
    </svg>
  );
}
