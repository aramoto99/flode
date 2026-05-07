// シミュレーション進捗バー。Run/Stop は Toolbar の icon button に集約済み。
// ここでは「実行中なら status + progress を細い帯で表示」のみに絞る (= 隠せる UI)。

import { useTranslation } from "react-i18next";

import { useAppStore } from "../store/appStore";

export function SimulationControls(_props: {
  modelId: string;
}): JSX.Element | null {
  const { t } = useTranslation();
  const status = useAppStore((s) => s.status);
  const progress = useAppStore((s) => s.progress);

  if (status === "idle") return null;

  const ratio =
    progress && progress.t_end > 0 ? progress.current_t / progress.t_end : 0;

  const statusColor =
    status === "running"
      ? "bg-blue-600"
      : status === "completed"
        ? "bg-emerald-600"
        : status === "stopped"
          ? "bg-amber-600"
          : "bg-rose-600";

  // ADR-0024: 状態ラベルを翻訳経由で取得。``status`` の型が将来拡張された場合でも
  // 安全な fallback として raw 値を返す (= 既存挙動を保ちつつ exhaustive check 漏れ
  // を防ぐ)。
  const statusLabel: string = ((): string => {
    if (status === "running") {
      return t("statusbar.running", {
        pct: Math.round(ratio * 100),
        t: progress?.current_t.toFixed(2) ?? "0",
      });
    }
    if (status === "completed") return t("statusbar.completed");
    if (status === "stopped") return t("statusbar.stopped");
    if (status === "failed") return t("statusbar.failed");
    return status;
  })();

  return (
    <div className="flex items-center gap-2 border-t border-slate-300 bg-slate-100 px-2 py-1 text-[11px] text-slate-700">
      <span
        className={`inline-block h-2 w-2 rounded-full ${statusColor}`}
        aria-hidden
      />
      <span className="font-medium tracking-wide">{statusLabel}</span>
      {progress && (
        <>
          <div className="ml-2 h-1.5 flex-1 overflow-hidden border border-slate-300 bg-white">
            <div
              className="h-full bg-blue-500 transition-all"
              style={{ width: `${Math.min(100, ratio * 100).toFixed(1)}%` }}
            />
          </div>
          <span className="font-mono text-[10px] tabular-nums text-slate-600">
            t={progress.current_t.toFixed(3)} / {progress.t_end.toFixed(3)}
          </span>
        </>
      )}
    </div>
  );
}
