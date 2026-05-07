// アプリ状態 store (ADR-0012 §(5)、ADR-0019 §(5) で編集状態 + auto-save 拡張)。

import { create } from "zustand";

import { resolvePortCounts } from "../lib/dynamicPorts";
import { applyAtPath } from "../lib/pathResolver";
import type {
  BlockEntry,
  BlockMetadata,
  ConnectionEntry,
  FlwModel,
  LayoutDict,
  MaskValuesDict,
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

  // ノード選択 (パラメータ編集 + 一括操作用)。複数選択対応。
  // ParameterPanel は ``selectedNodeIds.length === 1`` の時だけ表示する設計。
  selectedNodeIds: string[];
  selectedNodeId: string | null; // 互換性: selectedNodeIds.length === 1 のとき先頭、それ以外 null
  selectNode: (nodeId: string | null) => void;
  setSelectedNodeIds: (ids: readonly string[]) => void;
  toggleNodeSelection: (nodeId: string) => void;

  // エッジ選択 (= 矩形選択 / クリック選択 で React Flow が select イベントを発火する。
  // controlled mode では prop 経由で ``selected`` を渡し直さないと視覚反映されない)。
  selectedEdgeIds: string[];
  setSelectedEdgeIds: (ids: readonly string[]) => void;

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

  // ADR-0021 §(1): Subsystem ドリルダウン path
  editingPath: string[];
  setEditingPath: (path: string[]) => void;
  drilldownInto: (subsystemId: string) => void;
  drillUp: (depth?: number) => void;

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
      selectedNodeIds: [],
      selectedNodeId: null,
      selectedEdgeIds: [],
      simulationId: null,
      status: "idle",
      scopes: {},
      // モデル切り替えで編集状態をクリア (新モデルは ModelLoader で再 fetch)
      editingModel: null,
      dirty: false,
      editingPath: [],
    }),

  selectedNodeIds: [],
  selectedNodeId: null,
  selectNode: (nodeId) =>
    set({
      selectedNodeIds: nodeId === null ? [] : [nodeId],
      selectedNodeId: nodeId,
      // ノード選択を切り替えたらエッジ選択も解除 (= ParameterPanel の整合性)
      ...(nodeId === null ? { selectedEdgeIds: [] } : {}),
    }),
  setSelectedNodeIds: (ids) => {
    const arr = Array.from(new Set(ids));
    set({
      selectedNodeIds: arr,
      // ParameterPanel 表示用の単一 id (= 1 件選択時のみ)
      selectedNodeId: arr.length === 1 ? arr[0]! : null,
    });
  },
  toggleNodeSelection: (nodeId) =>
    set((state) => {
      const has = state.selectedNodeIds.includes(nodeId);
      const next = has
        ? state.selectedNodeIds.filter((id) => id !== nodeId)
        : [...state.selectedNodeIds, nodeId];
      return {
        selectedNodeIds: next,
        selectedNodeId: next.length === 1 ? next[0]! : null,
      };
    }),

  selectedEdgeIds: [],
  setSelectedEdgeIds: (ids) =>
    set({ selectedEdgeIds: Array.from(new Set(ids)) }),

  editingModel: null,
  setEditingModel: (model) => set({ editingModel: model }),
  applyEditingModel: (fn) => {
    const current = get().editingModel;
    if (!current) return;
    set({ editingModel: fn(current), dirty: true });
  },

  dirty: false,
  setDirty: (dirty) => set({ dirty }),

  editingPath: [],
  setEditingPath: (path) => set({ editingPath: path, selectedNodeId: null }),
  drilldownInto: (subsystemId) =>
    set((state) => ({
      editingPath: [...state.editingPath, subsystemId],
      selectedNodeId: null,
      selectedNodeIds: [],
    })),
  drillUp: (depth) =>
    set((state) => ({
      editingPath:
        depth === undefined
          ? state.editingPath.slice(0, -1)
          : state.editingPath.slice(0, depth),
      selectedNodeId: null,
      selectedNodeIds: [],
    })),

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
// ADR-0019 §(5) / ADR-0021 §(2) helper functions:
// editingModel の編集 API (現在 path 配下を更新する)
// ---------------------------------------------------------------------------

function currentPath(): readonly string[] {
  return useAppStore.getState().editingPath;
}

export function addBlockToEditing(
  block: BlockEntry,
  position: { x: number; y: number },
): void {
  const path = currentPath();
  useAppStore.getState().applyEditingModel((m) =>
    applyAtPath(m, path, (view) => ({
      blocks: [...view.blocks, block],
      connections: view.connections,
      layout: { ...view.layout, [block.id]: position },
    })),
  );
}

export function removeBlockFromEditing(blockId: string): void {
  const path = currentPath();
  useAppStore.getState().applyEditingModel((m) =>
    applyAtPath(m, path, (view) => {
      const blocks = view.blocks.filter((b) => b.id !== blockId);
      const connections = view.connections.filter(
        (c) => c.src !== blockId && c.dst !== blockId,
      );
      const layout = { ...view.layout };
      delete layout[blockId];
      return { blocks, connections, layout };
    }),
  );
}

export function updateBlockPosition(
  blockId: string,
  position: { x: number; y: number },
): void {
  const path = currentPath();
  useAppStore.getState().applyEditingModel((m) =>
    applyAtPath(m, path, (view) => {
      // 既存 entry の w/h を保持しつつ x/y のみ更新
      const prev = view.layout[blockId];
      const next = {
        ...view.layout,
        [blockId]: { ...prev, x: position.x, y: position.y },
      };
      return {
        blocks: view.blocks,
        connections: view.connections,
        layout: next,
      };
    }),
  );
}

export function updateBlockSize(
  blockId: string,
  size: { w: number; h: number },
): void {
  const path = currentPath();
  useAppStore.getState().applyEditingModel((m) =>
    applyAtPath(m, path, (view) => {
      const prev = view.layout[blockId];
      // 位置情報がまだ無い場合は (0,0) で fallback (= NodeResizer 作動時に必ず position は
      // 別途 onNodesChange でも書かれているので、ほぼ起きないケース)
      const next = {
        ...view.layout,
        [blockId]: {
          x: prev?.x ?? 0,
          y: prev?.y ?? 0,
          w: size.w,
          h: size.h,
        },
      };
      return {
        blocks: view.blocks,
        connections: view.connections,
        layout: next,
      };
    }),
  );
}

export function updateBlocksLayout(layout: LayoutDict): void {
  const path = currentPath();
  useAppStore.getState().applyEditingModel((m) =>
    applyAtPath(m, path, (view) => ({
      blocks: view.blocks,
      connections: view.connections,
      layout,
    })),
  );
}

export function addConnectionToEditing(conn: ConnectionEntry): void {
  const path = currentPath();
  useAppStore.getState().applyEditingModel((m) =>
    applyAtPath(m, path, (view) => {
      const filtered = view.connections.filter(
        (c) => !(c.dst === conn.dst && c.dst_idx === conn.dst_idx),
      );
      return {
        blocks: view.blocks,
        connections: [...filtered, conn],
        layout: view.layout,
      };
    }),
  );
}

export function removeConnectionFromEditing(
  src: string,
  src_idx: number,
  dst: string,
  dst_idx: number,
): void {
  const path = currentPath();
  useAppStore.getState().applyEditingModel((m) =>
    applyAtPath(m, path, (view) => ({
      blocks: view.blocks,
      connections: view.connections.filter(
        (c) =>
          !(
            c.src === src &&
            c.src_idx === src_idx &&
            c.dst === dst &&
            c.dst_idx === dst_idx
          ),
      ),
      layout: view.layout,
    })),
  );
}

export function updateBlockParams(
  blockId: string,
  params: Record<string, unknown>,
  registry?: ReadonlyMap<string, BlockMetadata>,
): void {
  const path = currentPath();
  useAppStore.getState().applyEditingModel((m) =>
    applyAtPath(m, path, (view) => {
      const target = view.blocks.find((b) => b.id === blockId);
      if (!target) return view;
      const newBlocks = view.blocks.map((b) =>
        b.id === blockId ? { ...b, params } : b,
      );
      // param 変更により port 数が減った場合、index out-of-range の edge を剪定する。
      const meta = registry?.get(target.type);
      const before = resolvePortCounts(target.type, target.params, meta);
      const after = resolvePortCounts(target.type, params, meta);
      let newConnections = view.connections;
      if (after.nInputs < before.nInputs || after.nOutputs < before.nOutputs) {
        newConnections = view.connections.filter((c) => {
          if (c.dst === blockId && c.dst_idx >= after.nInputs) return false;
          if (c.src === blockId && c.src_idx >= after.nOutputs) return false;
          return true;
        });
      }
      return {
        blocks: newBlocks,
        connections: newConnections,
        layout: view.layout,
      };
    }),
  );
}

// ADR-0021 §(9): Subsystem の mask_values 更新 (= ParameterPanel mask edit からの呼び出し)
export function updateSubsystemMaskValues(
  subsystemId: string,
  maskValues: MaskValuesDict,
): void {
  const path = currentPath();
  useAppStore.getState().applyEditingModel((m) =>
    applyAtPath(m, path, (view) => ({
      blocks: view.blocks.map((b) => {
        if (b.id !== subsystemId) return b;
        return {
          ...b,
          params: { ...b.params, mask_values: maskValues },
        };
      }),
      connections: view.connections,
      layout: view.layout,
    })),
  );
}
