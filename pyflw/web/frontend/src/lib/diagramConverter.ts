// JSON モデルと React Flow の Node/Edge との変換 (ADR-0012 §(4))。
// ADR-0020: model.layout があればそれを優先、無ければ auto-layout (grid) で fallback。
// ADR-0019 §(3) + 視覚化バグ修正 (2026-05-07): 単なる "default" ノードでは
// ``data.label`` 以外を描画しないため空白になる。registry metadata から色 / port 数 /
// is_container を吸い上げてカスタムノード ``BlockNodeView`` で描画する。

import type { Edge, Node } from "@xyflow/react";

import { getBlockShape } from "./blockShapes";
import { resolvePortCounts } from "./dynamicPorts";
import type { BlockMetadata, FlwModel, LayoutDict, LayoutEntry } from "../types/api";

export interface BlockNodeData extends Record<string, unknown> {
  blockType: string;
  params: Record<string, unknown>;
  // registry から流し込む表示メタ (BlockNodeView が読む)
  color?: string;
  nInputs?: number;
  nOutputs?: number;
  isContainer?: boolean;
}

export type BlockNode = Node<BlockNodeData>;

/** Grid auto-layout (Simulink 風に左→右の横向きフロー)。
 *  ブロックがコンパクト (~80×40) になったので grid pitch も狭めて密に並べる。 */
const GRID_CELL_WIDTH = 120;
const GRID_CELL_HEIGHT = 80;
const GRID_COLUMNS = 8;

function gridFallback(idx: number): LayoutEntry {
  return {
    x: (idx % GRID_COLUMNS) * GRID_CELL_WIDTH,
    y: Math.floor(idx / GRID_COLUMNS) * GRID_CELL_HEIGHT,
  };
}

export function modelToDiagram(
  model: FlwModel,
  registry?: ReadonlyMap<string, BlockMetadata>,
): {
  nodes: BlockNode[];
  edges: Edge[];
} {
  const layout = model.layout ?? {};
  const nodes: BlockNode[] = model.blocks.map((b, idx) => {
    const pos = layout[b.id] ?? gridFallback(idx);
    const meta = registry?.get(b.type);
    // ADR-0019: ブロック type ごとに外形サイズが異なる (三角・円・バー・台形・矩形)。
    // ノードの bounding box は **shape のみ**。ID ラベルは BlockNodeView が absolute で
    // ノード境界の外に描く (= NodeResizer の枠線 / handle が shape のみを囲むように)。
    const baseShape = getBlockShape(b.type);
    // 動的 port (Sum.signs / Mux.n / Subsystem.n_inputs 等) を反映した実 port 数
    const ports = resolvePortCounts(b.type, b.params, meta);
    // 同じ shape kind でも port 数が増えたら高さを伸ばす (ハンドルが密集して重ならない
    // ように)。各ハンドルは ~7px、最低 12px ピッチを確保する。
    const maxPorts = Math.max(ports.nInputs, ports.nOutputs);
    const minHeightForPorts = maxPorts * 12 + 8;
    // ユーザーが NodeResizer で手動リサイズした値が layout にあれば優先する
    // (= ADR-0020 §(2) で Phase 4+ 送りとしていた node サイズ永続化)。
    const layoutEntry = layout[b.id];
    const userW = layoutEntry?.w;
    const userH = layoutEntry?.h;
    const computedH = Math.max(baseShape.height, minHeightForPorts);
    const shape = {
      ...baseShape,
      width: userW ?? baseShape.width,
      height: userH != null ? userH : computedH,
    };
    return {
      id: b.id,
      position: { x: pos.x, y: pos.y },
      data: {
        blockType: b.type,
        params: b.params,
        color: meta?.color,
        nInputs: ports.nInputs,
        nOutputs: ports.nOutputs,
        isContainer: meta?.is_container ?? false,
        // BlockNodeView 内で SVG / handle 配置を計算するための実寸を渡す。width も
        // 必須 (= layout.w でリサイズされた値を BlockNodeView に伝える)。
        shapeWidth: shape.width,
        shapeHeight: shape.height,
      },
      type: "blockNode",
      width: shape.width,
      height: shape.height,
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
