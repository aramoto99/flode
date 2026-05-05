// シミュレーション開始/停止 + 進捗表示。

import { useEffect, useRef } from "react";

import { startSimulation, stopSimulation } from "../api/client";
import { streamSimulation } from "../api/stream";
import { useAppStore } from "../store/appStore";

interface SimulationControlsProps {
  modelId: string;
}

export function SimulationControls({ modelId }: SimulationControlsProps): JSX.Element {
  const status = useAppStore((s) => s.status);
  const progress = useAppStore((s) => s.progress);
  const simulationId = useAppStore((s) => s.simulationId);
  const startedSimulation = useAppStore((s) => s.startedSimulation);
  const handleStreamMessage = useAppStore((s) => s.handleStreamMessage);
  const wsRef = useRef<WebSocket | null>(null);

  // アンマウント時に WS をクリーンアップ
  useEffect(() => {
    return () => {
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, []);

  // シミュレーションが終端状態 (completed / stopped / failed) になったら、
  // 開きっぱなしの WS を閉じる (code-reviewer SHOULD 修正)。サーバ側でも close
  // するが冪等性のため両方で対応。
  useEffect(() => {
    if (status === "completed" || status === "stopped" || status === "failed") {
      wsRef.current?.close();
      wsRef.current = null;
    }
  }, [status]);

  const onRun = async (): Promise<void> => {
    try {
      const { simulation_id } = await startSimulation(modelId);
      startedSimulation(simulation_id);
      const ws = streamSimulation(simulation_id, handleStreamMessage);
      wsRef.current?.close();
      wsRef.current = ws;
    } catch (e) {
      console.error("Failed to start simulation", e);
    }
  };

  const onStop = async (): Promise<void> => {
    if (!simulationId) return;
    try {
      await stopSimulation(simulationId);
    } catch (e) {
      console.error("Failed to stop simulation", e);
    }
  };

  const isRunning = status === "running";
  const ratio =
    progress && progress.t_end > 0 ? progress.current_t / progress.t_end : 0;

  return (
    <div className="flex flex-col gap-2 border-t border-gray-200 p-3">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onRun}
          disabled={isRunning}
          className="rounded bg-blue-600 px-3 py-1 text-sm font-medium text-white disabled:bg-gray-400"
        >
          Run
        </button>
        <button
          type="button"
          onClick={onStop}
          disabled={!isRunning}
          className="rounded bg-red-600 px-3 py-1 text-sm font-medium text-white disabled:bg-gray-400"
        >
          Stop
        </button>
        <span className="text-xs text-gray-600">status: {status}</span>
      </div>
      {progress && (
        <div className="space-y-1">
          <div className="h-2 overflow-hidden rounded bg-gray-200">
            <div
              className="h-full bg-blue-500 transition-all"
              style={{ width: `${Math.min(100, ratio * 100).toFixed(1)}%` }}
            />
          </div>
          <div className="text-xs text-gray-500">
            t = {progress.current_t.toFixed(3)} / {progress.t_end.toFixed(3)}
          </div>
        </div>
      )}
    </div>
  );
}
