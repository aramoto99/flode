// JSON モデルと React Flow の Node/Edge との変換 (ADR-0012 §(4))。
// ADR-0020: model.layout があればそれを優先、無ければ auto-layout (grid) で fallback。

import type { Edge, Node } from "@xyflow/react";

import type { FlwModel, LayoutDict, LayoutEntry } from "../types/api";

export interface BlockNodeData extends Record<string, unknown> {
  blockType: string;
  params: Record<string, unknown>;
}

export type BlockNode = Node<BlockNodeData>;

/** Grid auto-layout の 1 セル幅・高 (ADR-0012 §(4)、Phase 2 から踏襲)。 */
const GRID_CELL_WIDTH = 200;
const GRID_CELL_HEIGHT = 120;
const GRID_COLUMNS = 4;

function gridFallback(idx: number): LayoutEntry {
  return {
    x: (idx % GRID_COLUMNS) * GRID_CELL_WIDTH,
    y: Math.floor(idx / GRID_COLUMNS) * GRID_CELL_HEIGHT,
  };
}

export function modelToDiagram(model: FlwModel): {
  nodes: BlockNode[];
  edges: Edge[];
} {
  const layout = model.layout ?? {};
  const nodes: BlockNode[] = model.blocks.map((b, idx) => {
    const pos = layout[b.id] ?? gridFallback(idx);
    return {
      id: b.id,
      position: { x: pos.x, y: pos.y },
      data: {
        blockType: b.type,
        params: b.params,
      },
      type: "default",
      width: 160,
      height: 60,
    };
  });
  const edges: Edge[] = model.connections.map((c, idx) => ({
    id: `e${idx}-${c.src}-${c.dst}`,
    source: c.src,
    target: c.dst,
    sourceHandle: String(c.src_idx),
    targetHandle: String(c.dst_idx),
  }));
  return { nodes, edges };
}

/**
 * 現在の React Flow Node 配列から ADR-0020 layout dict を構築する。
 * 保存 (PUT /api/v1/models/{id}) 時に呼び出して `model.layout` に同梱する。
 *
 * @param nodes - 現在の React Flow ノード配列。
 * @returns block id → `{x, y}` の `LayoutDict`。空配列なら空 dict。
 */
export function nodesToLayout(nodes: readonly BlockNode[]): LayoutDict {
  const out: LayoutDict = {};
  for (const n of nodes) {
    out[n.id] = { x: n.position.x, y: n.position.y };
  }
  return out;
}
