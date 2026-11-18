// ADR-0087: 配線のダブルクリック (信号名の編集) を、DOM の当たり判定ではなく幾何で判定する。
//
// ブロックの形が変わる (反転・ポート数) と、React Flow は handle を測り直すまで edge の要素を
// 描かない (1 フレーム消える)。その間のクリックは pane に当たるので、要素の listener や
// ``elementFromPoint`` では配線を拾えないことがある。そこで
// クリック位置 (flow 座標) と、各配線の経路 (``computeStepEdgePolyline`` = rubber-band 選択と
// 同じ幾何、手動分岐点 via を含む) との距離で、当たり判定幅以内の最も近い信号を選ぶ。

import type { Edge } from "@xyflow/react";

import { blockNodeToEndpoint, type BlockNode } from "./diagramConverter";
import { computeStepEdgePolyline, type Point } from "./edgeRectIntersect";

/** 配線の当たり判定の片側の幅 (画面 px)。BranchableEdge の overlay path の strokeWidth=20 の半分。 */
export const EDGE_HIT_HALF_WIDTH_PX = 10;

/** 判定に使う配線 1 本 (接続元の信号と flow 座標の経路)。 */
export interface EdgeHitGeometry {
  src: string;
  srcIdx: number;
  polyline: readonly Point[];
}

/** 判定から除くブロック本体の矩形 (flow 座標)。 */
export interface HitRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** 点と線分の距離。 */
function distanceToSegment(p: Point, a: Point, b: Point): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2));
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
}

/**
 * 点と折れ線の距離 (点が 1 つなら点との距離、空なら ``Infinity``)。
 *
 * @param p - 点 (flow 座標)。
 * @param polyline - 折れ線。
 */
export function distanceToPolyline(p: Point, polyline: readonly Point[]): number {
  if (polyline.length === 0) return Infinity;
  if (polyline.length === 1) return Math.hypot(p.x - polyline[0]!.x, p.y - polyline[0]!.y);
  let best = Infinity;
  for (let i = 1; i < polyline.length; i++) {
    best = Math.min(best, distanceToSegment(p, polyline[i - 1]!, polyline[i]!));
  }
  return best;
}

/**
 * 点の近くにある配線の信号を返す。ブロック本体の上なら ``null`` (ブロックのダブルクリックを奪わない)。
 * 距離が同じなら先の配線 (connections 順) を選ぶ。分岐した配線は幹線を共有するが、どれも同じ信号。
 *
 * @param point - クリック位置 (flow 座標)。
 * @param edges - 今のスコープの配線の幾何。
 * @param nodes - 今のスコープのブロック本体の矩形。
 * @param tolerance - 当たり判定の片側の幅 (flow 座標)。
 * @returns 信号 (無ければ ``null``)。
 */
export function findSignalAtPoint(
  point: Point,
  edges: readonly EdgeHitGeometry[],
  nodes: readonly HitRect[],
  tolerance: number,
): { src: string; srcIdx: number } | null {
  for (const r of nodes) {
    if (point.x >= r.x && point.x <= r.x + r.width && point.y >= r.y && point.y <= r.y + r.height) {
      return null;
    }
  }
  let best: EdgeHitGeometry | null = null;
  let bestDist = Infinity;
  for (const e of edges) {
    const d = distanceToPolyline(point, e.polyline);
    if (d <= tolerance && d < bestDist) {
      best = e;
      bestDist = d;
    }
  }
  return best === null ? null : { src: best.src, srcIdx: best.srcIdx };
}

/**
 * React Flow の node / edge から判定用の幾何を作る (rubber-band 選択と同じ式)。
 * 寸法が分からないブロックの配線は含めない。
 *
 * @param nodes - 今のスコープのブロック (DiagramCanvas の描画に使ったもの)。
 * @param edges - 今のスコープの配線 (``data.via`` = 手動分岐点を含む)。
 */
export function buildEdgeHitGeometry(
  nodes: readonly BlockNode[],
  edges: readonly Edge[],
): { edges: EdgeHitGeometry[]; nodes: HitRect[] } {
  const endpoints = new Map(nodes.map((n) => [n.id, blockNodeToEndpoint(n)] as const));
  const outEdges: EdgeHitGeometry[] = [];
  for (const e of edges) {
    const src = endpoints.get(e.source);
    const dst = endpoints.get(e.target);
    if (!src || !dst) continue;
    const srcIdx = Number(e.sourceHandle ?? 0);
    const via = (e.data as { via?: Point } | undefined)?.via;
    outEdges.push({
      src: e.source,
      srcIdx,
      polyline: computeStepEdgePolyline(src, srcIdx, dst, Number(e.targetHandle ?? 0), via),
    });
  }
  // ブロック本体の矩形は寸法だけで作る (ポート数が未確定で配線の端点が取れないブロックも除外する)
  const outNodes: HitRect[] = [];
  for (const n of nodes) {
    const width = n.width ?? (typeof n.data.shapeWidth === "number" ? n.data.shapeWidth : undefined);
    const height =
      n.height ?? (typeof n.data.shapeHeight === "number" ? n.data.shapeHeight : undefined);
    if (width === undefined || height === undefined) continue;
    outNodes.push({ x: n.position.x, y: n.position.y, width, height });
  }
  return { edges: outEdges, nodes: outNodes };
}
