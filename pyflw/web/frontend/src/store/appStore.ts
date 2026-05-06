// アプリ状態 store (ADR-0012 §(5))。Zustand でモデル選択・シミュレーション
// 状態・Scope ストリームを管理する。

import { create } from "zustand";

import type { SimulationStatus, StreamMessage } from "../types/api";

export interface ScopeBuffer {
  times: number[];
  values: number[][]; // [time_index][port_index]
}

interface AppState {
  selectedModelId: string | null;
  selectModel: (modelId: string | null) => void;

  // ノード選択 (パラメータ編集用、ADR-0012 §(3) ParameterPanel)
  selectedNodeId: string | null;
  selectNode: (nodeId: string | null) => void;

  // シミュレーション関連
  simulationId: string | null;
  status: SimulationStatus | "idle";
  progress: { current_t: number; t_end: number } | null;
  startedSimulation: (simId: string) => void;
  setStatus: (status: SimulationStatus | "idle") => void;
  setProgress: (current_t: number, t_end: number) => void;
  resetSimulation: () => void;

  // Scope データ (scope_id -> 時系列)
  scopes: Record<string, ScopeBuffer>;
  appendScopeBatch: (
    scope_id: string,
    times: number[],
    values: number[][],
  ) => void;
  resetScopes: () => void;

  // 受信ハンドラ (WebSocket メッセージから状態に反映)
  handleStreamMessage: (msg: StreamMessage) => void;
}

export const useAppStore = create<AppState>((set) => ({
  selectedModelId: null,
  selectModel: (modelId) =>
    set({
      selectedModelId: modelId,
      // モデル切替時にノード選択もクリア (前モデルの id が漏れないように)
      selectedNodeId: null,
      simulationId: null,
      status: "idle",
      scopes: {},
    }),

  selectedNodeId: null,
  selectNode: (nodeId) => set({ selectedNodeId: nodeId }),

  simulationId: null,
  status: "idle",
  progress: null,
  startedSimulation: (simId) =>
    set({ simulationId: simId, status: "running", progress: null, scopes: {} }),
  setStatus: (status) => set({ status }),
  setProgress: (current_t, t_end) => set({ progress: { current_t, t_end } }),
  resetSimulation: () =>
    set({ simulationId: null, status: "idle", progress: null }),

  scopes: {},
  // ``set((state) => ...)`` 関数形式でアトミックに前状態 → 新状態を組み立てる
  // (二重 ``get()`` 呼び出しによるスナップショットずれを回避: code-reviewer MUST)
  appendScopeBatch: (scope_id, times, values) =>
    set((state) => {
      const current = state.scopes[scope_id] ?? { times: [], values: [] };
      return {
        scopes: {
          ...state.scopes,
          [scope_id]: {
            times: [...current.times, ...times],
            values: [...current.values, ...values],
          },
        },
      };
    }),
  resetScopes: () => set({ scopes: {} }),

  handleStreamMessage: (msg) => {
    switch (msg.type) {
      case "progress":
        set({ progress: { current_t: msg.current_t, t_end: msg.t_end } });
        break;
      case "scope_batch":
        set((state) => {
          const current = state.scopes[msg.scope_id] ?? { times: [], values: [] };
          return {
            scopes: {
              ...state.scopes,
              [msg.scope_id]: {
                times: [...current.times, ...msg.times],
                values: [...current.values, ...msg.values],
              },
            },
          };
        });
        break;
      case "completed":
      case "stopped":
      case "failed":
        set({ status: msg.type });
        break;
      case "error":
        console.error("Simulation stream error:", msg.message);
        set({ status: "failed" });
        break;
    }
  },
}));
