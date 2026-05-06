// アプリ状態 store (ADR-0012 §(5)、ADR-0019 §(5) で編集状態 + auto-save 拡張)。

import { create } from "zustand";

import type {
  BlockEntry,
  ConnectionEntry,
  FlwModel,
  LayoutDict,
  SimulationStatus,
  StreamMessage,
} from "../types/api";

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

  // ADR-0019 §(5): 編集中モデル (=PUT する前の最新) を保持。
  // null のときは「読み取りモード」(従来の Phase 2 と同じ TanStack Query キャッシュ)。
  editingModel: FlwModel | null;
  setEditingModel: (model: FlwModel | null) => void;
  applyEditingModel: (
    fn: (current: FlwModel) => FlwModel,
  ) => void;

  // ADR-0019 §(5): dirty flag と debounce 用 timer
  dirty: boolean;
  setDirty: (dirty: boolean) => void;

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

export const useAppStore = create<AppState>((set, get) => ({
  selectedModelId: null,
  selectModel: (modelId) =>
    set({
      selectedModelId: modelId,
      selectedNodeId: null,
      simulationId: null,
      status: "idle",
      scopes: {},
      // モデル切り替えで編集状態をクリア (新モデルは ModelLoader で再 fetch)
      editingModel: null,
      dirty: false,
    }),

  selectedNodeId: null,
  selectNode: (nodeId) => set({ selectedNodeId: nodeId }),

  editingModel: null,
  setEditingModel: (model) => set({ editingModel: model }),
  applyEditingModel: (fn) => {
    const current = get().editingModel;
    if (!current) return;
    set({ editingModel: fn(current), dirty: true });
  },

  dirty: false,
  setDirty: (dirty) => set({ dirty }),

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

// ---------------------------------------------------------------------------
// ADR-0019 §(5) helper functions: editingModel の編集 API (DiagramCanvas 等から呼ぶ)
// ---------------------------------------------------------------------------

export function addBlockToEditing(
  block: BlockEntry,
  position: { x: number; y: number },
): void {
  useAppStore.getState().applyEditingModel((m) => ({
    ...m,
    blocks: [...m.blocks, block],
    layout: { ...(m.layout ?? {}), [block.id]: position },
  }));
}

export function removeBlockFromEditing(blockId: string): void {
  useAppStore.getState().applyEditingModel((m) => {
    const blocks = m.blocks.filter((b) => b.id !== blockId);
    const connections = m.connections.filter(
      (c) => c.src !== blockId && c.dst !== blockId,
    );
    const layout = { ...(m.layout ?? {}) };
    delete layout[blockId];
    return { ...m, blocks, connections, layout };
  });
}

export function updateBlockPosition(
  blockId: string,
  position: { x: number; y: number },
): void {
  useAppStore.getState().applyEditingModel((m) => ({
    ...m,
    layout: { ...(m.layout ?? {}), [blockId]: position },
  }));
}

export function updateBlocksLayout(layout: LayoutDict): void {
  useAppStore.getState().applyEditingModel((m) => ({ ...m, layout }));
}

export function addConnectionToEditing(conn: ConnectionEntry): void {
  useAppStore.getState().applyEditingModel((m) => {
    // ADR-0019 §4.3: 同一 (dst, dst_idx) への上書き接続 (古い edge を削除)
    const filtered = m.connections.filter(
      (c) => !(c.dst === conn.dst && c.dst_idx === conn.dst_idx),
    );
    return { ...m, connections: [...filtered, conn] };
  });
}

export function removeConnectionFromEditing(
  src: string,
  src_idx: number,
  dst: string,
  dst_idx: number,
): void {
  useAppStore.getState().applyEditingModel((m) => ({
    ...m,
    connections: m.connections.filter(
      (c) =>
        !(c.src === src && c.src_idx === src_idx && c.dst === dst && c.dst_idx === dst_idx),
    ),
  }));
}

export function updateBlockParams(
  blockId: string,
  params: Record<string, unknown>,
): void {
  useAppStore.getState().applyEditingModel((m) => ({
    ...m,
    blocks: m.blocks.map((b) =>
      b.id === blockId ? { ...b, params } : b,
    ),
  }));
}
