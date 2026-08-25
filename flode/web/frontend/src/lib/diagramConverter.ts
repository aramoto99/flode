// JSON モデルと React Flow の Node/Edge との変換 (ADR-0012 §(4))。
// ADR-0020: model.layout があればそれを優先、無ければ auto-layout (grid) で fallback。
// ADR-0019 §(3) + 視覚化バグ修正 (2026-05-07): 単なる "default" ノードでは
// ``data.label`` 以外を描画しないため空白になる。registry metadata から色 / port 数 /
// is_container を吸い上げてカスタムノード ``BlockNodeView`` で描画する。

import { MarkerType, type Edge, type Node } from "@xyflow/react";

import { getBlockShape } from "./blockShapes";
import { resolvePortCounts } from "./dynamicPorts";
import type { EdgeEndpointNode } from "./edgeRectIntersect";
import type { BlockMetadata, FlwModel, LayoutDict, LayoutEntry } from "../types/api";

// 業界標準ブロック線図ツール準拠: 連結線の終点に矢印 head を付けて「信号の流れ」を視覚化する。
// stroke は 1.5 で接地感を増す。``DiagramCanvas`` の ``defaultEdgeOptions``
// (= 新規 connect 時) からも import して同じ値を使う (= single source of truth、
// 値の drift 防止)。
export const DIAGRAM_EDGE_STROKE = "#1e293b"; // slate-800
export const DIAGRAM_EDGE_STYLE = {
  stroke: DIAGRAM_EDGE_STROKE,
  strokeWidth: 1.5,
};
export const DIAGRAM_MARKER_END = {
  type: MarkerType.ArrowClosed,
  color: DIAGRAM_EDGE_STROKE,
  width: 8,
  height: 8,
};
// v0.20.6: built-in "step" → custom "branchable" に変更。見た目は同じ (= 直角
// ステップ折れ線 + 矢印 head) を BranchableEdge 内で再現しつつ、edge mousedown
// で「既存配線から分岐」drag を発火できるようにする。
export const DIAGRAM_EDGE_TYPE = "branchable";

export interface BlockNodeData extends Record<string, unknown> {
  blockType: string;
  params: Record<string, unknown>;
  // registry から流し込む表示メタ (BlockNodeView が読む)
  color?: string;
  nInputs?: number;
  nOutputs?: number;
  isContainer?: boolean;
  // 業界標準ブロック線図ツール準拠: 接続済みのポートでは chevron ``>`` を抑制
  // (= edge 矢印 head と二重表示を回避)。``modelToDiagram`` が edges を走査して populate する。
  connectedInputs?: number[];
  connectedOutputs?: number[];
  // v0.15.0: ブロック左右反転フラグ (業界標準ブロック線図ツールの "Flip Block" 相当)。
  // layout entry の ``flipped`` から流す。BlockNodeView で port position を反転 + visual scaleX(-1)。
  flipped?: boolean;
}

export type BlockNode = Node<BlockNodeData>;

/** Grid auto-layout (業界標準ブロック線図ツール準拠の左→右の横向きフロー)。
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

  // 業界標準ブロック線図ツール準拠: 接続済み port (= edge の端点) には chevron ``>`` を
  // 表示しないため、各 block の接続済み input / output port_idx 集合を先に収集する。
  const connectedInBy = new Map<string, Set<number>>();
  const connectedOutBy = new Map<string, Set<number>>();
  for (const c of model.connections) {
    if (!connectedOutBy.has(c.src)) connectedOutBy.set(c.src, new Set());
    connectedOutBy.get(c.src)!.add(c.src_idx);
    if (!connectedInBy.has(c.dst)) connectedInBy.set(c.dst, new Set());
    connectedInBy.get(c.dst)!.add(c.dst_idx);
  }

  const nodes: BlockNode[] = model.blocks.map((b, idx) => {
    const pos = layout[b.id] ?? gridFallback(idx);
    const meta = registry?.get(b.type);
    // ADR-0019: ブロック type ごとに外形サイズが異なる (三角・円・バー・カプセル・五角形タグ・矩形)。
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
        // v0.33.0: per-block color は撤廃 (BlockNodeView 内で slate-600 固定)
        nInputs: ports.nInputs,
        nOutputs: ports.nOutputs,
        isContainer: meta?.is_container ?? false,
        // BlockNodeView 内で SVG / handle 配置を計算するための実寸を渡す。width も
        // 必須 (= layout.w でリサイズされた値を BlockNodeView に伝える)。
        shapeWidth: shape.width,
        shapeHeight: shape.height,
        connectedInputs: Array.from(connectedInBy.get(b.id) ?? []),
        connectedOutputs: Array.from(connectedOutBy.get(b.id) ?? []),
        flipped: layoutEntry?.flipped ?? false,
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
    // 業界標準ブロック線図ツール準拠: 90° 折れ線 (= step、smoothstep の角丸なし版)、
    // 黒系細線、終点矢印 head で「信号の流れ」を視覚化
    type: DIAGRAM_EDGE_TYPE,
    style: DIAGRAM_EDGE_STYLE,
    markerEnd: DIAGRAM_MARKER_END,
  }));
  return { nodes, edges };
}

/**
 * ``BlockNode`` から step edge polyline 計算用の ``EdgeEndpointNode`` を抽出する。
 *
 * ``modelToDiagram`` で ``width`` / ``height`` / ``nInputs`` / ``nOutputs`` は
 * 必ず populate されるが、``BlockNodeData`` が ``Record<string, unknown>`` 拡張の
 * ため TS 上は optional / unknown。ここで narrow し、未確定なら null を返す。
 *
 * rubber-band 選択 (``computeStepEdgePolyline`` で矩形交差判定) と分岐点 ●
 * 描画 (``JunctionDots``) の双方から共用する (= 端点幾何の single source of truth)。
 *
 * @param node 対象ブロックノード。
 * @returns 端点情報。寸法 / ポート数が未確定なら null。
 */
export function blockNodeToEndpoint(node: BlockNode): EdgeEndpointNode | null {
  const sw =
    typeof node.data.shapeWidth === "number" ? node.data.shapeWidth : undefined;
  const sh =
    typeof node.data.shapeHeight === "number"
      ? node.data.shapeHeight
      : undefined;
  const width = node.width ?? sw;
  const height = node.height ?? sh;
  const nInputs = node.data.nInputs;
  const nOutputs = node.data.nOutputs;
  if (
    width === undefined ||
    height === undefined ||
    nInputs === undefined ||
    nOutputs === undefined
  ) {
    return null;
  }
  return {
    position: node.position,
    width,
    height,
    nInputs,
    nOutputs,
    flipped: node.data.flipped,
  };
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
