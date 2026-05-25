// ブロック線図の慣例「分岐点 (junction / branch point) に ● を打つ」を描画する
// オーバーレイ。
//
// このツールの分岐は「同一出力ポートから複数の独立 edge を引く」方式
// (``BranchableEdge``) のため、線が重なって途中で分かれる分岐点にマーカーが
// 出ていなかった。本コンポーネントは React Flow store からライブの nodes /
// edges を購読し、同一 (source, sourceHandle) グループの edge polyline が実際に
// 分かれる座標 (= mid-wire の分岐点) を ``findJunctionPoints`` で求めて ● を
// 描く。無関係な信号同士の交差 (crossover) は同一グループに入らないため ● は
// 出ない (= 慣例どおり「交差 ≠ 接続」)。
//
// 座標は flow 座標系なので ``ViewportPortal`` 内に置いて pan / zoom に追従させる。
// nodes を store から取ることで、controlled mode のドラッグ中 (= ``onNodesChange``
// が毎フレーム store へ position を反映) も ● が配線に追従する。

import { useMemo } from "react";
import { useStore, ViewportPortal, type Edge } from "@xyflow/react";

import {
  blockNodeToEndpoint,
  DIAGRAM_EDGE_STROKE,
  type BlockNode,
} from "../lib/diagramConverter";
import { computeStepEdgePolyline, type Point } from "../lib/edgeRectIntersect";
import { findJunctionPoints } from "../lib/junctionDots";

/** 分岐点 ● の半径 (flow px)。配線 strokeWidth=1.5 に対し視認できる太さ。 */
const JUNCTION_DOT_RADIUS = 3;

/**
 * nodes / edges から全分岐点の座標を算出する。
 *
 * edge を ``(source, sourceHandle)`` でグルーピングし、2 本以上のグループのみ
 * 各 edge の step polyline を ``computeStepEdgePolyline`` (= 描画と同一幾何) で
 * 作って ``findJunctionPoints`` に渡す。
 */
function computeJunctionDots(nodes: BlockNode[], edges: Edge[]): Point[] {
  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  const groups = new Map<string, Edge[]>();
  for (const e of edges) {
    const key = `${e.source}::${e.sourceHandle ?? "0"}`;
    const arr = groups.get(key);
    if (arr) arr.push(e);
    else groups.set(key, [e]);
  }

  const dots: Point[] = [];
  for (const group of groups.values()) {
    if (group.length < 2) continue;
    const polylines: Point[][] = [];
    for (const e of group) {
      const src = nodeById.get(e.source);
      const dst = nodeById.get(e.target);
      if (!src || !dst) continue;
      const srcEp = blockNodeToEndpoint(src);
      const dstEp = blockNodeToEndpoint(dst);
      if (!srcEp || !dstEp) continue;
      const srcIdx = Number(e.sourceHandle ?? 0);
      const dstIdx = Number(e.targetHandle ?? 0);
      polylines.push(computeStepEdgePolyline(srcEp, srcIdx, dstEp, dstIdx));
    }
    dots.push(...findJunctionPoints(polylines));
  }
  return dots;
}

/**
 * 分岐点 ● を描画するオーバーレイ。``<ReactFlow>`` の子として配置する
 * (``ViewportPortal`` / ``useStore`` が React Flow context を要求するため)。
 */
export function JunctionDots(): JSX.Element | null {
  // controlled mode では store.nodes = 渡している nodes prop。ドラッグ中も
  // ライブ更新されるため ● が配線に追従する。
  const nodes = useStore((s) => s.nodes as BlockNode[]);
  const edges = useStore((s) => s.edges);

  const dots = useMemo(() => computeJunctionDots(nodes, edges), [nodes, edges]);
  if (dots.length === 0) return null;

  return (
    <ViewportPortal>
      {dots.map((p) => (
        <div
          // findJunctionPoints が dedupe 済みのため座標で一意。順序変化でも
          // 同一分岐点の <div> を React が再利用できる。
          key={`${p.x},${p.y}`}
          style={{
            position: "absolute",
            left: p.x,
            top: p.y,
            width: JUNCTION_DOT_RADIUS * 2,
            height: JUNCTION_DOT_RADIUS * 2,
            transform: "translate(-50%, -50%)",
            borderRadius: "50%",
            background: DIAGRAM_EDGE_STROKE,
            // 配線の hit area / mousedown 分岐を妨げない。
            pointerEvents: "none",
          }}
        />
      ))}
    </ViewportPortal>
  );
}
