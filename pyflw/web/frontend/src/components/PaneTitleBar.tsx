// ADR-0045 §(1) 必須スコープ + §(9) 用語規約: WorkspaceSplit 内の各 pane に
// 表示するタイトルバー。左にタイトル、右に「split right (左右分割)」「split
// down (上下分割)」「unsplit (分割解除)」アクションボタン。
//
// デザインは ``App.tsx:PanelHeader`` (h-6、border-b、bg-slate-100、uppercase
// tracking-wider) を踏襲し、Property Inspector primitives と整合させる。
// 大型 icon button / pill button は使わない (= memory `feedback_simulink_native_ui`)。

import { useTranslation } from "react-i18next";

interface PaneTitleBarProps {
  /** pane のタイトル文字列 (= i18n 後の表示用)。 */
  title: string;
  /** split right (= 左右分割、新 pane を右に) アクション。``null`` で hide。 */
  onSplitRight: (() => void) | null;
  /** split down (= 上下分割、新 pane を下に) アクション。``null`` で hide。 */
  onSplitDown: (() => void) | null;
  /** unsplit (= 分割解除、この pane を閉じる) アクション。``null`` で hide
   * (= tree 内最後の葉なら閉じられないため hide)。 */
  onUnsplit: (() => void) | null;
}

export function PaneTitleBar({
  title,
  onSplitRight,
  onSplitDown,
  onUnsplit,
}: PaneTitleBarProps): JSX.Element {
  const { t } = useTranslation();
  return (
    <div className="flex h-6 shrink-0 items-center justify-between border-b border-slate-200 bg-slate-100 pl-2 pr-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
      <span className="truncate" title={title}>
        {title}
      </span>
      <div className="flex items-center gap-0.5">
        {onSplitRight !== null && (
          <PaneActionButton
            label={t("workspace.split.right")}
            onClick={onSplitRight}
          >
            {/* split right icon: 縦の bar 1 本 + 右に +、Tailwind SVG */}
            <svg
              viewBox="0 0 16 16"
              className="h-3 w-3"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            >
              <rect x="1.5" y="2" width="13" height="12" />
              <line x1="8" y1="2" x2="8" y2="14" />
            </svg>
          </PaneActionButton>
        )}
        {onSplitDown !== null && (
          <PaneActionButton
            label={t("workspace.split.down")}
            onClick={onSplitDown}
          >
            <svg
              viewBox="0 0 16 16"
              className="h-3 w-3"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            >
              <rect x="2" y="1.5" width="12" height="13" />
              <line x1="2" y1="8" x2="14" y2="8" />
            </svg>
          </PaneActionButton>
        )}
        {onUnsplit !== null && (
          <PaneActionButton
            label={t("workspace.unsplit")}
            onClick={onUnsplit}
          >
            <svg
              viewBox="0 0 16 16"
              className="h-3 w-3"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            >
              <line x1="4" y1="4" x2="12" y2="12" />
              <line x1="12" y1="4" x2="4" y2="12" />
            </svg>
          </PaneActionButton>
        )}
      </div>
    </div>
  );
}

function PaneActionButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}): JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className="flex h-5 w-5 items-center justify-center text-slate-500 hover:bg-slate-200 hover:text-slate-800"
    >
      {children}
    </button>
  );
}
