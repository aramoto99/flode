// アイコンツールバー (Simulink / VS Code 風)。
// 左: file actions (Save / Undo / Redo placeholder)
// 中: zoom controls
// 右: simulation (Run / Stop)

import { useReactFlow } from "@xyflow/react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { putFileContent } from "../api/filesApi";
import { parseToolbarTEnd } from "../lib/timeUtil";
import { useSimulation } from "../lib/useSimulation";
import { updateSimulatorConfig, useAppStore } from "../store/appStore";

export function Toolbar(): JSX.Element {
  const { t } = useTranslation();
  const reactFlow = useReactFlow();
  const queryClient = useQueryClient();

  // v0.21.0 (ADR-0041 §論点 4-A): legacy ``selectedModelId`` 経路は削除済。
  // 保存先は常に ``selectedFilePath`` 配下の File API。
  const selectedFilePath = useAppStore((s) => s.selectedFilePath);
  const editingFileEtag = useAppStore((s) => s.editingFileEtag);
  const setEditingFileMeta = useAppStore((s) => s.setEditingFileMeta);
  const editingModel = useAppStore((s) => s.editingModel);
  const dirty = useAppStore((s) => s.dirty);
  const setDirty = useAppStore((s) => s.setDirty);
  const status = useAppStore((s) => s.status);

  const { run, stop } = useSimulation();

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!editingModel) throw new Error("no model");
      if (selectedFilePath === null) throw new Error("no file selected");
      const resp = await putFileContent(
        selectedFilePath,
        editingModel,
        editingFileEtag ?? undefined,
      );
      setEditingFileMeta(resp.mtime, resp.etag);
      setDirty(false);
      await queryClient.invalidateQueries({ queryKey: ["files-tree"] });
    },
  });

  const hasModel = selectedFilePath !== null;
  const isRunning = status === "running";

  // v0.20.0: Undo / Redo
  // ``useAppStore`` の購読は state 値を必要 → past/future の **長さ** を購読して
  // re-render を触媒する (= ボタンの disabled 状態を反映するため)。
  const canUndo = useAppStore((s) => s.history.past.length > 0);
  const canRedo = useAppStore((s) => s.history.future.length > 0);
  const undo = useAppStore((s) => s.undo);
  const redo = useAppStore((s) => s.redo);

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
      <ToolButton
        title={t("toolbar.undo")}
        disabled={!hasModel || !canUndo}
        onClick={() => undo()}
      >
        <UndoIcon />
      </ToolButton>
      <ToolButton
        title={t("toolbar.redo")}
        disabled={!hasModel || !canRedo}
        onClick={() => redo()}
      >
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
// ``editingModel.simulator.t_end`` を直接購読 + 編集する入力フィールド。
// ADR-0042 §論点 5-A: ``"inf"`` (case-insensitive) を受け入れて Stop ボタンまで
// 走らせる unbounded run を実現する。不正値 (空 / NaN / 負 / 未対応 string) は
// store に書かず draft をリセット。autosave は applyEditingModel 内で立つ。
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
    if (tEnd === undefined) {
      setDraft("");
    } else {
      setDraft(String(tEnd));
    }
  }, [tEnd]);

  const commit = (): void => {
    const parsed = parseToolbarTEnd(draft);
    if (parsed === null) {
      // 不正値は draft をリセット (= 旧値を表示し直す)
      setDraft(tEnd === undefined ? "" : String(tEnd));
      return;
    }
    if (parsed !== tEnd) updateSimulatorConfig({ t_end: parsed });
  };

  return (
    <label
      title={t("toolbar.stop_time_tooltip")}
      className="ml-1 mr-1 flex items-center gap-1 text-[11px] text-slate-700"
    >
      <span className="font-medium">{t("toolbar.stop_time")}</span>
      {/* type="text" + inputMode="decimal" にしているのは:
          1) Simulink ツールバーの Stop Time にスピナー (上下矢印) は無いため
          2) ``type="number"`` のスピナーは UX を分断する (= マウスで誤操作で
             値が変わる、矩形がブラウザごとに違う見た目)
          3) commit ソフトウェア検証 (Number(draft)) で十分
          ModelSettingsModal の NumberInput とも揃える。 */}
      <input
        type="text"
        inputMode="decimal"
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
