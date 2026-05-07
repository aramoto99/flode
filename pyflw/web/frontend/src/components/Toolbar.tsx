// アイコンツールバー (Simulink / VS Code 風)。
// 左: file actions (Save / Undo / Redo placeholder)
// 中: zoom controls
// 右: simulation (Run / Stop)

import { useReactFlow } from "@xyflow/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { updateModel } from "../api/client";
import { useSimulation } from "../lib/useSimulation";
import { useAppStore } from "../store/appStore";

export function Toolbar(): JSX.Element {
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
        title="Save (Ctrl+S)"
        disabled={!hasModel || !dirty || saveMutation.isPending}
        onClick={() => saveMutation.mutate()}
      >
        <SaveIcon />
      </ToolButton>
      <ToolButton title="Undo (Phase 4)" disabled>
        <UndoIcon />
      </ToolButton>
      <ToolButton title="Redo (Phase 4)" disabled>
        <RedoIcon />
      </ToolButton>

      <Divider />

      {/* Group: Zoom */}
      <ToolButton
        title="Zoom In"
        disabled={!hasModel}
        onClick={() => reactFlow.zoomIn()}
      >
        <ZoomInIcon />
      </ToolButton>
      <ToolButton
        title="Zoom Out"
        disabled={!hasModel}
        onClick={() => reactFlow.zoomOut()}
      >
        <ZoomOutIcon />
      </ToolButton>
      <ToolButton
        title="Fit to View"
        disabled={!hasModel}
        onClick={() => reactFlow.fitView({ padding: 0.2 })}
      >
        <FitIcon />
      </ToolButton>

      <div className="flex-1" />

      {/* Group: Simulation */}
      <ToolButton
        title="Run Simulation"
        disabled={!hasModel || isRunning}
        onClick={() => void run()}
        accent="run"
      >
        <RunIcon />
      </ToolButton>
      <ToolButton
        title="Stop Simulation"
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
