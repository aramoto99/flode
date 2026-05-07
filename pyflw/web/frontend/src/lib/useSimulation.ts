// シミュレーション開始 / 停止 + WebSocket ストリーミングを 1 か所に集約する hook。
// Toolbar の Run/Stop ボタンと SimulationControls の進捗表示で共通使用する。

import { useEffect, useRef } from "react";

import {
  startSimulation,
  stopSimulation,
  updateModel,
} from "../api/client";
import { streamSimulation } from "../api/stream";
import { useAppStore } from "../store/appStore";

export function useSimulation(): {
  run: () => Promise<void>;
  stop: () => Promise<void>;
} {
  const wsRef = useRef<WebSocket | null>(null);
  const status = useAppStore((s) => s.status);
  const simulationId = useAppStore((s) => s.simulationId);
  const startedSimulation = useAppStore((s) => s.startedSimulation);
  const handleStreamMessage = useAppStore((s) => s.handleStreamMessage);

  // アンマウント or 終了状態で WS を閉じる
  useEffect(() => {
    return () => {
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, []);
  useEffect(() => {
    if (status === "completed" || status === "stopped" || status === "failed") {
      wsRef.current?.close();
      wsRef.current = null;
    }
  }, [status]);

  const run = async (): Promise<void> => {
    const state = useAppStore.getState();
    const id = state.selectedModelId;
    const model = state.editingModel;
    if (!id) return;
    try {
      // Run 前に最新を保存 (auto-save の debounce で未送信の可能性に対処)
      if (model) {
        await updateModel(id, model);
        state.setDirty(false);
      }
      const { simulation_id } = await startSimulation(id);
      startedSimulation(simulation_id);
      const ws = streamSimulation(simulation_id, handleStreamMessage);
      wsRef.current?.close();
      wsRef.current = ws;
    } catch (e) {
      console.error("Failed to start simulation", e);
    }
  };

  const stop = async (): Promise<void> => {
    if (!simulationId) return;
    try {
      await stopSimulation(simulationId);
    } catch (e) {
      console.error("Failed to stop simulation", e);
    }
  };

  return { run, stop };
}
