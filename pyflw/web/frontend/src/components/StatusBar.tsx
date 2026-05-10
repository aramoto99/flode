// VS Code 風 status bar (画面下部)。
// model 名 / dirty / solver / sim 状態 / block 数 / current path を表示する。

import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { resolveBlocksAtPath } from "../lib/pathResolver";
import { useAppStore } from "../store/appStore";

export function StatusBar(): JSX.Element {
  const { t } = useTranslation();
  const selectedModelId = useAppStore((s) => s.selectedModelId);
  const selectedFilePath = useAppStore((s) => s.selectedFilePath);
  const editingModel = useAppStore((s) => s.editingModel);
  const editingPath = useAppStore((s) => s.editingPath);
  const dirty = useAppStore((s) => s.dirty);
  const status = useAppStore((s) => s.status);
  const progress = useAppStore((s) => s.progress);
  // ADR-0041 §論点 8-A: file path 優先表示、無ければ legacy model id を表示
  const displayName = selectedFilePath ?? selectedModelId;

  const stats = useMemo(() => {
    if (!editingModel) return null;
    try {
      const view = resolveBlocksAtPath(editingModel, editingPath);
      return {
        blocks: view.blocks.length,
        connections: view.connections.length,
        solver: editingModel.simulator.solver,
        tEnd: editingModel.simulator.t_end,
        dt: editingModel.simulator.dt,
      };
    } catch {
      return null;
    }
  }, [editingModel, editingPath]);

  const simStatusLabel = ((): string => {
    if (status === "running" && progress) {
      const pct = Math.min(
        100,
        Math.round((progress.current_t / progress.t_end) * 100),
      );
      return t("statusbar.running", {
        pct,
        t: progress.current_t.toFixed(2),
      });
    }
    if (status === "completed") return t("statusbar.completed");
    if (status === "stopped") return t("statusbar.stopped");
    if (status === "failed") return t("statusbar.failed");
    return t("statusbar.idle");
  })();

  const simStatusColor =
    status === "running"
      ? "bg-blue-600"
      : status === "completed"
        ? "bg-emerald-600"
        : status === "stopped"
          ? "bg-amber-600"
          : status === "failed"
            ? "bg-rose-600"
            : "bg-slate-500";

  return (
    <footer className="flex h-6 items-center gap-3 border-t border-slate-300 bg-slate-200 px-3 text-[11px] text-slate-700">
      {/* sim status */}
      <div className="flex items-center gap-1.5">
        <span className={`inline-block h-2 w-2 rounded-full ${simStatusColor}`} />
        <span className="font-medium">{simStatusLabel}</span>
      </div>

      <Sep />

      {/* model id / file path + dirty */}
      <span>
        {displayName ? (
          <>
            <span className="text-slate-500">{t("statusbar.label.file")}</span>{" "}
            <span className="font-mono" title={displayName}>
              {displayName}
            </span>
            {dirty && (
              <span
                className="ml-1 text-amber-600"
                title={t("statusbar.unsaved_dot_title")}
              >
                ●
              </span>
            )}
          </>
        ) : (
          <span className="text-slate-400">{t("statusbar.label.no_file")}</span>
        )}
      </span>

      <Sep />

      {/* path (drilldown) */}
      {editingPath.length > 0 && (
        <>
          <span>
            <span className="text-slate-500">{t("statusbar.label.scope")}</span>{" "}
            <span className="font-mono">{editingPath.join(" / ")}</span>
          </span>
          <Sep />
        </>
      )}

      {/* blocks / connections */}
      {stats && (
        <>
          <span>
            <span className="text-slate-500">{t("statusbar.label.blocks")}</span>{" "}
            <span className="font-mono">{stats.blocks}</span>
          </span>
          <span>
            <span className="text-slate-500">{t("statusbar.label.edges")}</span>{" "}
            <span className="font-mono">{stats.connections}</span>
          </span>

          <Sep />

          <span>
            <span className="text-slate-500">{t("statusbar.label.solver")}</span>{" "}
            <span className="font-mono">{stats.solver}</span>
          </span>
          <span>
            <span className="text-slate-500">{t("statusbar.label.t_end")}</span>{" "}
            <span className="font-mono">{stats.tEnd}</span>
          </span>
          <span>
            <span className="text-slate-500">{t("statusbar.label.dt")}</span>{" "}
            <span className="font-mono">{stats.dt}</span>
          </span>
        </>
      )}

      <div className="ml-auto flex items-center gap-3">
        <span className="text-slate-500">pyflw v{__APP_VERSION__}</span>
      </div>
    </footer>
  );
}

function Sep(): JSX.Element {
  return <div className="h-3 w-px bg-slate-300" />;
}
