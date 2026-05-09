// アイコンツールバー (Simulink / VS Code 風)。
// 左: file actions (Save / Undo / Redo placeholder)
// 中: zoom controls
// 右: simulation (Run / Stop)

import { useReactFlow } from "@xyflow/react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { updateModel } from "../api/client";
import { useSimulation } from "../lib/useSimulation";
import { updateSimulatorConfig, useAppStore } from "../store/appStore";

export function Toolbar(): JSX.Element {
  const { t } = useTranslation();
  const reactFlow = useReactFlow();
  const queryClient = useQueryClient();

  const selectedModelId = useAppStore((s) => s.selectedModelId);
  const editingModel = useAppStore((s) => s.editingModel);
  const dirty = useAppStore((s) => s.dirty);
  const setDirty = useAppStore((s) => s.setDirty);
  const status = useAppStore((s) => s.status);

  const { run, stop } = useSimulation();

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!selectedModelId || !editingModel) throw new Error("no model");
      await updateModel(selectedModelId, editingModel);
      setDirty(false);
      await queryClient.invalidateQueries({
        queryKey: ["model", selectedModelId],
      });
    },
  });

  const hasModel = selectedModelId !== null;
  const isRunning = status === "running";

  return (
    <div className="flex items-center gap-0.5 border-b border-slate-300 bg-slate-50 px-1.5 py-0.5">
      {/* Group: File */}
      <ToolButton
        title={t("toolbar.save")}
        disabled={!hasModel || !dirty || saveMutation.isPending}
        onClick={() => saveMutation.mutate()}
      >
        <SaveIcon />
      </ToolButton>
      <ToolButton title={t("toolbar.undo")} disabled>
        <UndoIcon />
      </ToolButton>
      <ToolButton title={t("toolbar.redo")} disabled>
        <RedoIcon />
      </ToolButton>

      <Divider />

      {/* Group: Zoom */}
      <ToolButton
        title={t("toolbar.zoom_in")}
        disabled={!hasModel}
        onClick={() => reactFlow.zoomIn()}
      >
        <ZoomInIcon />
      </ToolButton>
      <ToolButton
        title={t("toolbar.zoom_out")}
        disabled={!hasModel}
        onClick={() => reactFlow.zoomOut()}
      >
        <ZoomOutIcon />
      </ToolButton>
      <ToolButton
        title={t("toolbar.fit")}
        disabled={!hasModel}
        onClick={() => reactFlow.fitView({ padding: 0.2 })}
      >
        <FitIcon />
      </ToolButton>

      <div className="flex-1" />

      {/* Group: Simulation — Simulink 風に Run の **直前** に Stop time を置く。 */}
      <StopTimeInput disabled={!hasModel} />
      <ToolButton
        title={t("toolbar.run")}
        disabled={!hasModel || isRunning}
        onClick={() => void run()}
        accent="run"
      >
        <RunIcon />
      </ToolButton>
      <ToolButton
        title={t("toolbar.stop")}
        disabled={!isRunning}
        onClick={() => void stop()}
        accent="stop"
      >
        <StopIcon />
      </ToolButton>
    </div>
  );
}

// ---------------------------------------------------------------------------
// StopTimeInput: Simulink ツールバー右側にある Stop Time フィールド相当。
// ``editingModel.simulator.t_end`` を直接購読 + 編集する数値入力。
// 不正値 (空 / NaN / 負) は store に書かず draft のみ更新 → 確定 (blur or Enter)
// 時に弾く。autosave (= dirty フラグ) は applyEditingModel 内で立つ。
// ---------------------------------------------------------------------------
interface StopTimeInputProps {
  disabled: boolean;
}

function StopTimeInput({ disabled }: StopTimeInputProps): JSX.Element {
  const { t } = useTranslation();
  const tEnd = useAppStore((s) => s.editingModel?.simulator.t_end);
  const [draft, setDraft] = useState<string>("");

  // store の値が変わったら draft を同期 (= 別タブで開いたモデル切替時 etc.)
  useEffect(() => {
    setDraft(tEnd === undefined ? "" : String(tEnd));
  }, [tEnd]);

  const commit = (): void => {
    const v = Number(draft);
    if (!Number.isFinite(v) || v <= 0) {
      // 不正値は draft をリセット
      setDraft(tEnd === undefined ? "" : String(tEnd));
      return;
    }
    if (v !== tEnd) updateSimulatorConfig({ t_end: v });
  };

  return (
    <label
      title={t("toolbar.stop_time_tooltip")}
      className="ml-1 mr-1 flex items-center gap-1 text-[11px] text-slate-700"
    >
      <span className="font-medium">{t("toolbar.stop_time")}</span>
      {/* min/step は意図的に省略: 0 を含む不正値はソフトウェア側 (commit) で
          弾く方針に統一 (HTML 属性と JS 検証を同居させると 0 のスピナー値が
          下限通過時にリセットされて UX が混乱するため)。 */}
      <input
        type="number"
        step="any"
        value={draft}
        disabled={disabled}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            (e.target as HTMLInputElement).blur();
          }
        }}
        className="h-6 w-16 rounded border border-slate-300 px-1.5 text-right font-mono text-[11px] tabular-nums text-slate-800 focus:border-blue-500 focus:outline-none disabled:bg-slate-100 disabled:text-slate-400"
        data-testid="toolbar-stop-time"
        aria-label={t("toolbar.stop_time")}
      />
    </label>
  );
}

// ---------------------------------------------------------------------------
// ToolButton primitive
// ---------------------------------------------------------------------------

interface ToolButtonProps {
  title: string;
  onClick?: () => void;
  disabled?: boolean;
  children: React.ReactNode;
  accent?: "run" | "stop";
}

function ToolButton({
  title,
  onClick,
  disabled,
  children,
  accent,
}: ToolButtonProps): JSX.Element {
  const accentClass =
    accent === "run"
      ? "text-emerald-700 hover:bg-emerald-100"
      : accent === "stop"
        ? "text-rose-600 hover:bg-rose-100"
        : "text-slate-700 hover:bg-slate-200";
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={`flex h-7 w-7 items-center justify-center rounded transition-colors ${
        disabled ? "text-slate-300" : accentClass
      }`}
    >
      {children}
    </button>
  );
}

function Divider(): JSX.Element {
  return <div className="mx-0.5 h-5 w-px bg-slate-300" />;
}

// ---------------------------------------------------------------------------
// Icons (16×16)
// ---------------------------------------------------------------------------

const SVG_PROPS = {
  width: 16,
  height: 16,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

function SaveIcon(): JSX.Element {
  return (
    <svg {...SVG_PROPS}>
      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
      <polyline points="17 21 17 13 7 13 7 21" />
      <polyline points="7 3 7 8 15 8" />
    </svg>
  );
}

function UndoIcon(): JSX.Element {
  return (
    <svg {...SVG_PROPS}>
      <polyline points="3 7 3 13 9 13" />
      <path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-9 5" />
    </svg>
  );
}

function RedoIcon(): JSX.Element {
  return (
    <svg {...SVG_PROPS}>
      <polyline points="21 7 21 13 15 13" />
      <path d="M3 17a9 9 0 0 1 9-9 9 9 0 0 1 9 5" />
    </svg>
  );
}

function ZoomInIcon(): JSX.Element {
  return (
    <svg {...SVG_PROPS}>
      <circle cx="11" cy="11" r="7" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
      <line x1="11" y1="8" x2="11" y2="14" />
      <line x1="8" y1="11" x2="14" y2="11" />
    </svg>
  );
}

function ZoomOutIcon(): JSX.Element {
  return (
    <svg {...SVG_PROPS}>
      <circle cx="11" cy="11" r="7" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
      <line x1="8" y1="11" x2="14" y2="11" />
    </svg>
  );
}

function FitIcon(): JSX.Element {
  return (
    <svg {...SVG_PROPS}>
      <polyline points="4 14 4 20 10 20" />
      <polyline points="20 10 20 4 14 4" />
      <line x1="14" y1="10" x2="21" y2="3" />
      <line x1="3" y1="21" x2="10" y2="14" />
    </svg>
  );
}

function RunIcon(): JSX.Element {
  return (
    <svg {...SVG_PROPS} fill="currentColor">
      <polygon points="5 3 19 12 5 21 5 3" />
    </svg>
  );
}

function StopIcon(): JSX.Element {
  return (
    <svg {...SVG_PROPS} fill="currentColor">
      <rect x="6" y="6" width="12" height="12" rx="1" />
    </svg>
  );
}
