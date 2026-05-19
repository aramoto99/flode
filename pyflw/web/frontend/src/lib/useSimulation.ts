// シミュレーション開始 / 停止 + WebSocket ストリーミングを 1 か所に集約する hook。
// Toolbar の Run/Stop ボタンと SimulationControls の進捗表示で共通使用する。
//
// v0.21.0 (ADR-0041 §論点 4-A): legacy ``selectedModelId`` / ``--model-dir`` /
// ``startSimulation(model_id)`` 経路は削除済。``selectedFilePath`` セット時のみ
// File API 経路 (= 保存 → model_path body で start) で動く。

import { useEffect, useRef } from "react";

import { ApiError, startSimulationByPath, stopSimulation } from "../api/client";
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
    if (state.selectedFilePath === null) return;
    try {
      // Run 前に最新を保存 (= 「保存してから実行」セマンティクス、editingFileEtag
      // を使った楽観ロックで race を検知)。
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
      startedSimulation(simulation_id);
      const ws = streamSimulation(simulation_id, handleStreamMessage);
      wsRef.current?.close();
      wsRef.current = ws;
    } catch (e) {
      console.error("Failed to start simulation", e);
      // ADR-0056 §F3: start REST が構造化 detail (= FailurePayload) を返した場合、
      // Error tab に表示するため lastFailure にセットする。それ以外 (= 通信エラー
      // 等) は generic な FailurePayload を組み立てる (= 起動失敗 source 固定)。
      const setLastFailure = useAppStore.getState().setLastFailure;
      if (e instanceof ApiError && e.structured !== null) {
        setLastFailure(e.structured, "start");
      } else {
        const msg = e instanceof Error ? e.message : String(e);
        setLastFailure(
          {
            category: "unknown",
            template_key: "error.unknown",
            template_args: { raw_message: msg },
            block_id: null,
            block_ids: [],
            block_type: null,
            block_label: null,
            t: null,
            raw_message: msg,
            raw_traceback: null,
          },
          "start",
        );
      }
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
