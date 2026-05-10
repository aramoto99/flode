// シミュレーション開始 / 停止 + WebSocket ストリーミングを 1 か所に集約する hook。
// Toolbar の Run/Stop ボタンと SimulationControls の進捗表示で共通使用する。
//
// ADR-0041 §論点 5-A: ``selectedFilePath`` セット時は File API 経由 (= 保存 →
// model_path body で start)、それ以外は legacy ``selectedModelId`` 経由
// (= updateModel → model_id body で start)。

import { useEffect, useRef } from "react";

import {
  startSimulation,
  startSimulationByPath,
  stopSimulation,
  updateModel,
} from "../api/client";
import { putFileContent } from "../api/filesApi";
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
    const model = state.editingModel;
    if (!model) return;
    try {
      let simulationId: string;
      if (state.selectedFilePath !== null) {
        // ADR-0041 §論点 5-A: File API モード。Run 前に最新を保存 (= legacy 動線
        // と同じ「保存してから実行」セマンティクス、editingFileEtag を使った
        // 楽観ロックで race を検知)。
        const resp = await putFileContent(
          state.selectedFilePath,
          model,
          state.editingFileEtag ?? undefined,
        );
        state.setEditingFileMeta(resp.mtime, resp.etag);
        state.setDirty(false);
        const { simulation_id } = await startSimulationByPath(
          state.selectedFilePath,
        );
        simulationId = simulation_id;
      } else if (state.selectedModelId !== null) {
        // legacy ``--model-dir`` モード
        await updateModel(state.selectedModelId, model);
        state.setDirty(false);
        const { simulation_id } = await startSimulation(state.selectedModelId);
        simulationId = simulation_id;
      } else {
        // 未選択 (= editingModel あるが path / id どちらも未設定): no-op
        return;
      }
      startedSimulation(simulationId);
      const ws = streamSimulation(simulationId, handleStreamMessage);
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
