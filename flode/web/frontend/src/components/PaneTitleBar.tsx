// ADR-0045 §(1) 必須スコープ + §(9) 用語規約: WorkspaceSplit 内の各 pane に
// 表示するタイトルバー。左にタイトル、右に「split right (左右分割)」「split
// down (上下分割)」「unsplit (分割解除)」アクションボタン。
//
// デザインは ``App.tsx:PanelHeader`` (h-6、border-b、bg-slate-100、uppercase
// tracking-wider) を踏襲し、Property Inspector primitives と整合させる。
// 大型 icon button / pill button は使わない (= ネイティブデスクトップ風 UI ガイド)。

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
  /** ADR-0052 §(3) Stage 3: detach (= float に切替) アクション。``null`` で hide。
   * Scope pane のみで提供 (= Inspector float は別 UI = App.tsx の Inspector
   * sidebar header で切替)。 */
  onDetach?: (() => void) | null;
  /** v0.27.1 UX-3: split 系ボタンを **hide ではなく disabled** で表示する。
   * onSplitRight / onSplitDown が ``null`` でも、本 prop が非 null なら button を
   * 描画して disabled + title=disabledReason に「なぜ押せないか」を出す。 */
  disabledSplitReason?: string | null;
}

export function PaneTitleBar({
  title,
  onSplitRight,
  onSplitDown,
  onUnsplit,
  onDetach,
  disabledSplitReason,
}: PaneTitleBarProps): JSX.Element {
  const { t } = useTranslation();
  // v0.27.1 UX-3: split 系は null でも disabled で描画する (= disabledSplitReason
  // が指定されていれば)。これにより「ボタンが存在するが押せない」UX で
  // ユーザーに「何故押せないか」を tooltip で伝える。
  const showSplitDisabled =
    disabledSplitReason !== undefined && disabledSplitReason !== null;
  return (
    <div className="flex h-6 shrink-0 items-center justify-between border-b border-slate-200 bg-slate-100 pl-2 pr-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
      <span className="truncate" title={title}>
        {title}
      </span>
      <div className="flex items-center gap-0.5">
        {(onSplitRight !== null || showSplitDisabled) && (
          <PaneActionButton
            label={t("workspace.split.right")}
            onClick={onSplitRight}
            disabledReason={onSplitRight === null ? disabledSplitReason ?? null : null}
          >
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
        {(onSplitDown !== null || showSplitDisabled) && (
          <PaneActionButton
            label={t("workspace.split.down")}
            onClick={onSplitDown}
            disabledReason={onSplitDown === null ? disabledSplitReason ?? null : null}
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
        {onDetach !== undefined && onDetach !== null && (
          <PaneActionButton
            label={t("workspace.detach")}
            onClick={onDetach}
            disabledReason={null}
          >
            {/* detach icon: 枠から斜め矢印が外に出る形 (= float に分離) */}
            <svg
              viewBox="0 0 16 16"
              className="h-3 w-3"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="2" y="6" width="8" height="8" />
              <polyline points="9 7 14 2" />
              <polyline points="10 2 14 2 14 6" />
            </svg>
          </PaneActionButton>
        )}
        {onUnsplit !== null && (
          <PaneActionButton
            label={t("workspace.unsplit")}
            onClick={onUnsplit}
            disabledReason={null}
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
  disabledReason,
  children,
}: {
  label: string;
  /** ``null`` でクリック不可。disabledReason と組み合わせて使う。 */
  onClick: (() => void) | null;
  /** v0.27.1 UX-3: disabled 時の理由テキスト (= tooltip)。``null`` で enabled。 */
  disabledReason: string | null;
  children: React.ReactNode;
}): JSX.Element {
  const isDisabled = onClick === null;
  return (
    <button
      type="button"
      onClick={onClick ?? undefined}
      disabled={isDisabled}
      title={isDisabled && disabledReason !== null ? disabledReason : label}
      aria-label={label}
      aria-disabled={isDisabled || undefined}
      className={
        isDisabled
          ? "flex h-5 w-5 cursor-not-allowed items-center justify-center text-slate-300"
          : "flex h-5 w-5 items-center justify-center text-slate-500 hover:bg-slate-200 hover:text-slate-800"
      }
    >
      {children}
    </button>
  );
}
