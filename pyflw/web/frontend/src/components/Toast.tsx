// ADR-0030: グローバル toast container + 個別 toast item。
// `<App>` ルート直下に 1 つ mount。``useToastStore()`` 経由で entries を読み、
// fixed bottom-center で重ねる。severity ごとに色 / icon / a11y 属性を出し分ける。

import { useTranslation } from "react-i18next";

import {
  dismissToast,
  type ToastItem,
  type ToastSeverity,
  useToastStore,
} from "../store/toastStore";

/** severity → Tailwind class table。色 / 縁取り / 文字色をまとめて管理する。 */
const SEVERITY_STYLES: Record<ToastSeverity, string> = {
  info: "bg-slate-700 text-white ring-slate-500",
  success: "bg-emerald-600 text-white ring-emerald-400",
  warning: "bg-amber-600 text-white ring-amber-400",
  // ADR-0030 §Risks #1: 既存 DiagramCanvas の rose-600 + bottom-center を踏襲
  // (= warning と error で色を分けつつ、error は既存 UI に視覚的に揃える)。
  error: "bg-rose-600 text-white ring-rose-400",
};

/** severity → ARIA role / aria-live。warning / error は assertive で即時通知。 */
function ariaForSeverity(severity: ToastSeverity): {
  role: "status" | "alert";
  ariaLive: "polite" | "assertive";
} {
  if (severity === "warning" || severity === "error") {
    return { role: "alert", ariaLive: "assertive" };
  }
  return { role: "status", ariaLive: "polite" };
}

export function ToastContainer(): JSX.Element {
  const { t } = useTranslation();
  const toasts = useToastStore((s) => s.toasts);
  // ARIA live region は **常に DOM に存在** する必要がある (= AT が監視対象として
  // 認識するのは最初の paint 時点)。toasts が空のときも region を出して中身だけ
  // 制御する (code-reviewer SHOULD 修正、iOS VoiceOver 等の旧 AT 互換性のため)。
  return (
    <div
      role="region"
      aria-label={t("toast.region")}
      aria-relevant="additions"
      // region 自体にも aria-live=polite を付け、AT に常時監視を要求する
      // (= 個別 toast の role=alert/status は子要素に持たせる)。
      aria-live="polite"
      className="pointer-events-none fixed bottom-5 left-1/2 z-50 flex -translate-x-1/2 flex-col items-center gap-2"
    >
      {toasts.map((item) => (
        <ToastView key={item.id} item={item} />
      ))}
    </div>
  );
}

function ToastView({ item }: { item: ToastItem }): JSX.Element {
  const { t } = useTranslation();
  const { role, ariaLive } = ariaForSeverity(item.severity);
  return (
    <div
      role={role}
      // WAI-ARIA 1.2 §6.6.1: ``role=alert`` は ``aria-live=assertive`` を、
      // ``role=status`` は ``aria-live=polite`` を暗黙的に持つ。明示している
      // のは JAWS 旧版 / iOS VoiceOver 等で role の暗黙値が読まれない実装が
      // あるため意図的な冗長 (code-reviewer SHOULD 解説)。``aria-atomic`` も
      // 同様に role の暗黙値だが、AT 互換性のため明示する。
      aria-live={ariaLive}
      aria-atomic="true"
      className={`pointer-events-auto flex max-w-md items-center gap-2 rounded-md px-3.5 py-2 text-xs font-medium shadow-lg ring-1 ${SEVERITY_STYLES[item.severity]}`}
    >
      <SeverityIcon severity={item.severity} />
      <span className="whitespace-pre-wrap">{item.message}</span>
      <button
        type="button"
        onClick={() => dismissToast(item.id)}
        aria-label={t("toast.dismiss")}
        className="ml-1 rounded p-0.5 text-white/80 hover:bg-white/15 hover:text-white focus:outline-none focus:ring-1 focus:ring-white/50"
      >
        <svg
          viewBox="0 0 24 24"
          className="h-3.5 w-3.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </button>
    </div>
  );
}

function SeverityIcon({ severity }: { severity: ToastSeverity }): JSX.Element {
  // svg は aria-hidden で a11y tree から消す (= 文言で同じ情報を伝える)
  const common = {
    viewBox: "0 0 24 24",
    className: "h-4 w-4 shrink-0",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2.5,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
  if (severity === "success") {
    return (
      <svg {...common}>
        <polyline points="20 6 9 17 4 12" />
      </svg>
    );
  }
  if (severity === "info") {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="16" x2="12" y2="12" />
        <line x1="12" y1="8" x2="12.01" y2="8" />
      </svg>
    );
  }
  // warning / error
  return (
    <svg {...common}>
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="8" x2="12" y2="12" />
      <line x1="12" y1="16" x2="12.01" y2="16" />
    </svg>
  );
}
