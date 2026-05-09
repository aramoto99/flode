// アプリ状態 store (ADR-0012 §(5)、ADR-0019 §(5) で編集状態 + auto-save 拡張)。

import { create } from "zustand";

import {
  getNumberParam,
  INPORT_TYPE,
  OUTPORT_TYPE,
  TRIGGERED_SUBSYSTEM_TYPE,
} from "../lib/blockTypes";
import { resolvePortCounts } from "../lib/dynamicPorts";
import { applyAtPath, resolveBlocksAtPath } from "../lib/pathResolver";
import {
  appendBatch as appendScopeBatchSoA,
  createBuffer as createScopeBuffer,
  type ScopeBuffer,
} from "../lib/scopeBuffer";
import type {
  BlockEntry,
  BlockMetadata,
  ConnectionEntry,
  FlwModel,
  LayoutDict,
  MaskValuesDict,
  SimulationStatus,
  SimulatorConfig,
  StreamMessage,
} from "../types/api";

// ADR-0023 §Decision §(3): ScopeBuffer は ``../lib/scopeBuffer`` に SoA 実装を抽出。
// ここでは re-export して既存 import (= ScopeView / XYGraphView / BlockNodeView 経由) を
// 壊さないように維持する。
export type { ScopeBuffer };

/** Ctrl+C で蓄えるブロック群のコピー (Ctrl+V でオフセット位置に貼り付け)。 */
export interface ClipboardPayload {
  blocks: BlockEntry[];
  connections: ConnectionEntry[];
  layout: LayoutDict; // 元 id → 元位置 (paste 時に位相平均から bbox 中心を計算する基準)
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

  // クリップボード (Ctrl+C / Ctrl+V のための in-memory バッファ、cross-window 永続化なし)。
  clipboard: ClipboardPayload | null;
  setClipboard: (cb: ClipboardPayload | null) => void;

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
      clipboard: null,
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

  // Phase 3: in-app クリップボード (= cross-window で persist する必要は今のところ
  // ない、シンプルな in-memory の単一バッファ)。
  clipboard: null,
  setClipboard: (cb) => set({ clipboard: cb }),

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
      const current = state.scopes[scope_id] ?? createScopeBuffer();
      return {
        scopes: {
          ...state.scopes,
          [scope_id]: appendScopeBatchSoA(current, times, values),
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
        // appendScopeBatch ロジックを再利用 (= 同じ SoA 追記パスを通すことで
        // 整合性管理が 1 か所に集約される)。
        get().appendScopeBatch(msg.scope_id, msg.times, msg.values);
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
  const isInport = block.type === INPORT_TYPE;
  const isOutport = block.type === OUTPORT_TYPE;
  const isPort = isInport || isOutport;

  useAppStore.getState().applyEditingModel((m) => {
    let updated = m;

    // (1) path 配下に block を追加。Inport / Outport なら port_idx を内部の
    //     既存同種 count に上書き (= 連番採番、_build 検証と整合)。
    //     ADR-0039: 親 Subsystem の n_inputs / n_outputs は派生 property のため、
    //     ここで明示的に +1 する処理は不要 (= 内部 Inport を追加するだけで
    //     `dynamicPorts.resolvePortCounts` が自動派生する)。
    updated = applyAtPath(updated, path, (view) => {
      let inserted = block;
      if (isPort) {
        const sameTypeCount = view.blocks.filter(
          (b) => b.type === block.type,
        ).length;
        inserted = {
          ...block,
          params: { ...block.params, port_idx: sameTypeCount },
        };
      }
      return {
        blocks: [...view.blocks, inserted],
        connections: view.connections,
        layout: { ...view.layout, [inserted.id]: position },
      };
    });

    // (2) ADR-0036 §(2): TriggeredSubsystem の trigger 接続 (= 末尾固定 slot) は
    //     内部 Inport 追加で +1 シフトする必要あり (派生 property 化と独立、
    //     ADR-0039 §Decision §(7) で残すと確定)。
    //     旧 trigger dst_idx = (旧 internal Inport count) → 新 dst_idx = +1
    if (isInport && path.length > 0) {
      const parentPath = path.slice(0, -1);
      const parentSubId = path[path.length - 1]!;
      updated = applyAtPath(updated, parentPath, (view) => {
        const parentBlock = view.blocks.find((b) => b.id === parentSubId);
        if (!parentBlock) {
          console.warn(
            `[appStore] addBlockToEditing: parent subsystem "${parentSubId}" not found at path`,
            path,
          );
          return view;
        }
        if (parentBlock.type !== TRIGGERED_SUBSYSTEM_TYPE) {
          return view; // 通常 Subsystem は追従不要 (= 派生 property)
        }
        // 旧 trigger dst_idx を内部 Inport 数 (追加前) から計算する。
        // 追加後の inner blocks には新 Inport が含まれるので、count - 1 で旧値を得る。
        const innerBlocks = (parentBlock.params as { blocks?: BlockEntry[] }).blocks ?? [];
        const oldInportCount =
          innerBlocks.filter((b) => b.type === INPORT_TYPE).length - 1;
        const oldTriggerIdx = oldInportCount;
        let triggerFound = false;
        const newConnections = view.connections.map((c) => {
          if (c.dst === parentSubId && c.dst_idx === oldTriggerIdx) {
            triggerFound = true;
            return { ...c, dst_idx: c.dst_idx + 1 };
          }
          return c;
        });
        if (!triggerFound && oldTriggerIdx >= 0) {
          console.warn(
            `[appStore] TriggeredSubsystem "${parentSubId}" has no trigger connection ` +
              `at dst_idx=${oldTriggerIdx}. trigger slot may be inconsistent.`,
          );
        }
        return {
          blocks: view.blocks,
          connections: newConnections,
          layout: view.layout,
        };
      });
    }

    return updated;
  });
}

export function removeBlockFromEditing(blockId: string): void {
  const path = currentPath();

  useAppStore.getState().applyEditingModel((m) => {
    // 削除対象 block の type / port_idx を先に特定 (= path 配下 view を覗いて
    // Inport / Outport なら親同期が必要かどうかを決める)
    let target: BlockEntry | undefined;
    try {
      const view = resolveBlocksAtPath(m, path);
      target = view.blocks.find((b) => b.id === blockId);
    } catch (err) {
      // path 不整合は通常 onNodesChange の race で発生し得る。エラーを握り潰さず
      // 警告を残して no-op で返す (= code-reviewer SHOULD-3)。
      console.error(
        "[appStore] removeBlockFromEditing: failed to resolve path",
        path,
        err,
      );
      target = undefined;
    }
    if (!target) return m;
    const targetType = target.type;

    const isInport = targetType === INPORT_TYPE;
    const isOutport = targetType === OUTPORT_TYPE;
    const isPort = isInport || isOutport;
    const targetParams = target.params as Record<string, unknown>;
    const rawPortIdx = targetParams.port_idx;
    const removedPortIdx =
      isPort && typeof rawPortIdx === "number" && Number.isFinite(rawPortIdx)
        ? rawPortIdx
        : undefined;

    let updated = m;

    // (1) path 配下から block 削除 + 関連 connection 削除 + 残った同種 port の
    //     port_idx 連番再割り当 (削除した port_idx より大きいものを -1)
    updated = applyAtPath(updated, path, (view) => {
      const blocks = view.blocks
        .filter((b) => b.id !== blockId)
        .map((b) => {
          if (removedPortIdx === undefined || b.type !== targetType) return b;
          const idx = getNumberParam(
            b.params as Record<string, unknown>,
            "port_idx",
            -1,
          );
          if (idx > removedPortIdx) {
            return { ...b, params: { ...b.params, port_idx: idx - 1 } };
          }
          return b;
        });
      const connections = view.connections.filter(
        (c) => c.src !== blockId && c.dst !== blockId,
      );
      const layout = { ...view.layout };
      delete layout[blockId];
      return { blocks, connections, layout };
    });

    // (2) 親階層 connections のシフト/削除のみ実行 (= ADR-0039: 親
    //     n_inputs / n_outputs は派生 property のため明示的な -1 は不要)。
    //     port_idx 連番再割り当てに伴って親階層の dst_idx (Inport) / src_idx
    //     (Outport) を追従させる。TriggeredSubsystem の trigger 接続も
    //     `dst_idx > removedPortIdx` のシフトで自動的に末尾を保つ。
    if (isPort && path.length > 0 && removedPortIdx !== undefined) {
      const parentPath = path.slice(0, -1);
      const parentSubId = path[path.length - 1]!;
      updated = applyAtPath(updated, parentPath, (view) => {
        const parentBlock = view.blocks.find((b) => b.id === parentSubId);
        if (!parentBlock) {
          console.warn(
            `[appStore] removeBlockFromEditing: parent subsystem "${parentSubId}" not found at path`,
            path,
          );
          return view;
        }
        const newConnections = view.connections
          .filter((c) => {
            if (
              isInport &&
              c.dst === parentSubId &&
              c.dst_idx === removedPortIdx
            )
              return false;
            if (
              isOutport &&
              c.src === parentSubId &&
              c.src_idx === removedPortIdx
            )
              return false;
            return true;
          })
          .map((c) => {
            if (
              isInport &&
              c.dst === parentSubId &&
              c.dst_idx > removedPortIdx
            ) {
              return { ...c, dst_idx: c.dst_idx - 1 };
            }
            if (
              isOutport &&
              c.src === parentSubId &&
              c.src_idx > removedPortIdx
            ) {
              return { ...c, src_idx: c.src_idx - 1 };
            }
            return c;
          });
        return {
          blocks: view.blocks,
          connections: newConnections,
          layout: view.layout,
        };
      });
    }

    return updated;
  });
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

/**
 * v0.16.0: モデル全体の simulator config (= t_end / dt / solver / rtol / atol /
 * dt_base) を patch する。Subsystem 内部のドリルダウンに関わらず、トップレベル
 * モデルの ``simulator`` フィールドを更新する (= simulator は単一スコープ)。
 *
 * autosave に乗せるため ``applyEditingModel`` 経由で書き込む。
 */
export function updateSimulatorConfig(patch: Partial<SimulatorConfig>): void {
  useAppStore.getState().applyEditingModel((m) => ({
    ...m,
    simulator: { ...m.simulator, ...patch },
  }));
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

/**
 * v0.15.0: ブロックの左右反転フラグをトグルする (Simulink の "Flip Block" 相当)。
 * ``layout[blockId].flipped`` を反転、純粋な GUI metadata で backend 計算には
 * 影響しない。``layout`` entry が無ければ作る。
 */
export function toggleBlockFlipped(blockId: string): void {
  const path = currentPath();
  useAppStore.getState().applyEditingModel((m) =>
    applyAtPath(m, path, (view) => {
      const prev = view.layout[blockId];
      const newFlipped = !(prev?.flipped ?? false);
      const next = {
        ...view.layout,
        [blockId]: {
          x: prev?.x ?? 0,
          y: prev?.y ?? 0,
          ...(prev?.w !== undefined ? { w: prev.w } : {}),
          ...(prev?.h !== undefined ? { h: prev.h } : {}),
          // ``true`` のときだけ書き込む = false に戻したら field を消す (= JSON
          // byte-identical 維持、normalize_layout も同じ方針)。
          ...(newFlipped ? { flipped: true } : {}),
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

// ---------------------------------------------------------------------------
// 全選択 / コピー / 貼り付け (Simulink Ctrl+A / Ctrl+C / Ctrl+V)
// ---------------------------------------------------------------------------

/**
 * 現在 path 配下のすべての node + edge を選択状態にする。
 * 入力フォーカス中は呼び出し側で抑制する想定 (= テキスト編集中の Ctrl+A は
 * テキスト全選択として OS / ブラウザが扱うべき)。
 */
export function selectAllInScope(): void {
  const state = useAppStore.getState();
  const model = state.editingModel;
  if (!model) return;
  let view;
  try {
    view = resolveBlocksAtPath(model, state.editingPath);
  } catch {
    return;
  }
  state.setSelectedNodeIds(view.blocks.map((b) => b.id));
  // edge id 規則 = modelToDiagram の "e{idx}-{src}-{dst}" と一致させる
  state.setSelectedEdgeIds(
    view.connections.map((c, idx) => `e${idx}-${c.src}-${c.dst}`),
  );
}

/**
 * 選択中の block + そのブロック間に閉じる connection を clipboard に保存する。
 * 既存 layout も込みで保存し、paste 時にレイアウトを忠実に再現する。
 */
export function copySelectionToClipboard(): void {
  const state = useAppStore.getState();
  const model = state.editingModel;
  if (!model || state.selectedNodeIds.length === 0) return;
  let view;
  try {
    view = resolveBlocksAtPath(model, state.editingPath);
  } catch {
    return;
  }
  const selectedSet = new Set(state.selectedNodeIds);
  const blocks = view.blocks
    .filter((b) => selectedSet.has(b.id))
    .map((b) => ({ ...b, params: deepClone(b.params) }));
  // 選択ブロック同士の connection だけコピー (= 切れた配線の貼り付けは不自然)
  const connections = view.connections.filter(
    (c) => selectedSet.has(c.src) && selectedSet.has(c.dst),
  );
  const layout: LayoutDict = {};
  for (const id of selectedSet) {
    const e = view.layout[id];
    if (e) layout[id] = { ...e };
  }
  state.setClipboard({ blocks, connections, layout });
}

/**
 * Clipboard の中身を現在 path / オフセットで貼り付け。新しい block id を生成し、
 * connection の src/dst を新 id にリマップする。貼り付け後、貼り付けた block 群を
 * 選択状態にする。
 */
export function pasteClipboard(offset = { x: 20, y: 20 }): void {
  const state = useAppStore.getState();
  const cb = state.clipboard;
  if (!cb || cb.blocks.length === 0) return;
  const path = state.editingPath;

  const idMap = new Map<string, string>();
  let pastedIds: string[] = [];

  state.applyEditingModel((m) =>
    applyAtPath(m, path, (view) => {
      const existingIds = new Set(view.blocks.map((b) => b.id));
      // ID 採番: generateUniqueId と同じく "{typeName}_{i}" を空きまでスキャン。
      // store の独立性のため inline 実装。
      const allocateId = (orig: string): string => {
        const typeName = orig.split("_")[0] ?? orig;
        for (let i = 0; i < 10000; i++) {
          const candidate = `${typeName}_${i}`;
          if (!existingIds.has(candidate)) {
            existingIds.add(candidate);
            return candidate;
          }
        }
        throw new Error(`Cannot allocate id for paste from ${orig}`);
      };

      const newBlocks: BlockEntry[] = [];
      for (const b of cb.blocks) {
        const newId = allocateId(b.id);
        idMap.set(b.id, newId);
        newBlocks.push({ ...b, id: newId, params: deepClone(b.params) });
      }
      pastedIds = newBlocks.map((b) => b.id);

      const newConnections = cb.connections
        .map((c) => {
          const src = idMap.get(c.src);
          const dst = idMap.get(c.dst);
          if (!src || !dst) return null;
          return { ...c, src, dst };
        })
        .filter((c): c is ConnectionEntry => c !== null);

      const newLayout: LayoutDict = { ...view.layout };
      for (const [oldId, entry] of Object.entries(cb.layout)) {
        const newId = idMap.get(oldId);
        if (!newId) continue;
        newLayout[newId] = {
          ...entry,
          x: entry.x + offset.x,
          y: entry.y + offset.y,
        };
      }

      return {
        blocks: [...view.blocks, ...newBlocks],
        connections: [...view.connections, ...newConnections],
        layout: newLayout,
      };
    }),
  );

  // 貼り付けた block 群を選択 (Simulink でも Ctrl+V 直後は新規分が選択される)
  if (pastedIds.length > 0) {
    state.setSelectedNodeIds(pastedIds);
  }
}

function deepClone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T;
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
