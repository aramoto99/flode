// JSON モデルと React Flow の Node/Edge との変換 (ADR-0012 §(4))。
// レイアウトは Phase 2 では auto-layout (シンプルな grid) を採用。

import type { Edge, Node } from "@xyflow/react";

import type { FlwModel } from "../types/api";

export interface BlockNodeData extends Record<string, unknown> {
  blockType: string;
  params: Record<string, unknown>;
}

export type BlockNode = Node<BlockNodeData>;

export function modelToDiagram(model: FlwModel): {
  nodes: BlockNode[];
  edges: Edge[];
} {
  const nodes: BlockNode[] = model.blocks.map((b, idx) => ({
    id: b.id,
    position: {
      x: (idx % 4) * 200,
      y: Math.floor(idx / 4) * 120,
    },
    data: {
      blockType: b.type,
      params: b.params,
    },
    type: "default",
    width: 160,
    height: 60,
  }));
  const edges: Edge[] = model.connections.map((c, idx) => ({
    id: `e${idx}-${c.src}-${c.dst}`,
    source: c.src,
    target: c.dst,
    sourceHandle: String(c.src_idx),
    targetHandle: String(c.dst_idx),
  }));
  return { nodes, edges };
}
