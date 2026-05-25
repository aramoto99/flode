// ADR-0057 (改訂 2026-05-25): 分岐点 ● の解決 (自動算出 + 手動 1 軸拘束) の
// single source of truth。
//
// 同一 (source, sourceHandle) グループごとに:
//   - 手動 waypoint があれば、保存値 (幹線方向スカラ pos) を **幹線上に再構成**した
//     via 座標に ● を 1 個だけ打つ (= R1 拘束: ● は常に「線が分かれる点」)。
//   - 無ければ findJunctionPoints で自動 ● を算出する (v1 と同じ)。
//
// 描画 (BranchableEdge) / ● 算出 (JunctionDots) / rubber-band 交差判定の 3 系統は、
// 本モジュールが返す **同一の正規化済 via** を共有する (= 幾何 SSOT、ADR-0057 §改訂
// §(改訂-B) の via 集約)。via 生成ロジックを 1 箇所に閉じることで「via 正規化の漏れで
// ● が浮く」リスク (ADR-0057 §改訂 Risk 2) を構造的に防ぐ。

import type { Edge } from "@xyflow/react";

import {
  blockNodeToEndpoint,
  type BlockNode,
} from "./diagramConverter";
import {
  computeStepEdgePolyline,
  type EdgeEndpointNode,
  type Point,
} from "./edgeRectIntersect";
import { findJunctionPoints } from "./junctionDots";
import type { BranchWaypoint, BranchWaypointDict } from "../types/api";

/** 幹線方向の軸。"x" = 水平幹線 (Right/Left 出力)、"y" = 縦幹線 (Top/Bottom 出力)。 */
export type TrunkAxis = "x" | "y";

/** 分岐点 ● 1 個分の算出結果 (描画 + ドラッグ拘束に必要な幾何を同梱)。 */
export interface ResolvedJunctionDot {
  /** ● 描画座標 (flow、手動なら幹線上に再構成済)。 */
  x: number;
  y: number;
  /** 合成キー ``"<source block id>:<sourceHandle index>"``。 */
  groupKey: string;
  /** ``true`` で手動固定 (= waypoint 由来)。``false`` は自動計算。 */
  manual: boolean;
  /** 幹線方向の軸 (ドラッグ時の射影に使う)。 */
  axis: TrunkAxis;
  /** 幹線方向スカラの可動範囲 (clamp 用、`lo <= hi`)。 */
  lo: number;
  hi: number;
  /** source 出力点 (via 再構成・grab オフセット算出に使う)。 */
  sx: number;
  sy: number;
}

/**
 * source の出力ポート向きから幹線軸を導出する。
 *
 * 現状 pyflw の出力ハンドルは必ず水平 (Right、flipped で Left) のため常に "x" を
 * 返す (ADR-0057 §改訂 前提検証 改訂-1)。Top/Bottom 出力ポートが導入されたら "y"
 * を返す分岐を足す (= 縦幹線対応、将来送り)。
 */
export function outputAxis(_src: EdgeEndpointNode): TrunkAxis {
  // 出力は水平のみ (flipped でも Right↔Left でどちらも水平軸)。
  return "x";
}

/**
 * 保存 entry (新形 {axis,pos} or v1 旧形 {x,y}) を {axis,pos} に正規化する。
 *
 * v1 後方互換 (ADR-0057 §改訂 §(改訂-A)): 旧形 ``{x,y}`` は ``{ axis: "x", pos: x }``
 * とみなし ``y`` を楽観無視する (= 水平幹線として解釈)。新形 ``{axis,pos}`` はそのまま。
 *
 * @returns 正規化済の {axis,pos}。pos が有限でない / 解釈不能なら null。
 */
export function normalizeWaypointEntry(
  entry: BranchWaypoint | { x?: number; y?: number } | undefined | null,
): BranchWaypoint | null {
  if (entry == null) return null;
  const e = entry as Record<string, unknown>;
  // 新形 {axis,pos}
  if ((e.axis === "x" || e.axis === "y") && typeof e.pos === "number") {
    return Number.isFinite(e.pos) ? { axis: e.axis, pos: e.pos } : null;
  }
  // v1 旧形 {x,y} → axis "x"、pos = x (y は楽観無視)
  if (typeof e.x === "number" && Number.isFinite(e.x)) {
    return { axis: "x", pos: e.x };
  }
  return null;
}

/** 点の幹線軸方向スカラを取り出す ("x" なら p.x、"y" なら p.y)。 */
export function along(axis: TrunkAxis, p: { x: number; y: number }): number {
  return axis === "x" ? p.x : p.y;
}

/** ``pos`` を ``[lo, hi]`` にクランプし、幹線軸に応じた via 座標を再構成する。 */
export function reconstructVia(
  axis: TrunkAxis,
  pos: number,
  sx: number,
  sy: number,
  lo: number,
  hi: number,
): Point {
  const clamped = Math.min(hi, Math.max(lo, pos));
  return axis === "x" ? { x: clamped, y: sy } : { x: sx, y: clamped };
}

/** source 出力点 (sx, sy) を computeStepEdgePolyline と同じ式で求める。 */
function sourceOutputPoint(src: EdgeEndpointNode, srcHandleIdx: number): Point {
  const flipped = src.flipped ?? false;
  const sx = src.position.x + (flipped ? 0 : src.width);
  const sy =
    src.position.y + ((srcHandleIdx + 1) * src.height) / (src.nOutputs + 1);
  return { x: sx, y: sy };
}

/** target の入力辺の幹線方向座標 (水平なら左辺 tx、縦なら上下辺 ty) を求める。 */
function targetTrunkCoord(
  dst: EdgeEndpointNode,
  dstHandleIdx: number,
  axis: TrunkAxis,
): number {
  const flipped = dst.flipped ?? false;
  if (axis === "x") {
    return dst.position.x + (flipped ? dst.width : 0);
  }
  // 縦幹線 (将来): 入力辺の Y。現状到達しない。
  return dst.position.y + ((dstHandleIdx + 1) * dst.height) / (dst.nInputs + 1);
}

/**
 * nodes / edges / 手動 waypoint から、現スコープの全分岐点 ● と、手動グループの
 * 正規化済 via を算出する。
 *
 * @returns
 *   - ``dots``: 描画する ● 一覧 (手動/自動、各ドラッグ幾何付き)。
 *   - ``vias``: 手動グループの groupKey → 正規化済 via {x,y} (edge 描画への注入用)。
 */
export function resolveJunctions(
  nodes: BlockNode[],
  edges: Edge[],
  waypoints: BranchWaypointDict,
): { dots: ResolvedJunctionDot[]; vias: Map<string, Point> } {
  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  // (source, sourceHandle) でグルーピング (永続キーと同形の合成キー)。
  const groups = new Map<string, Edge[]>();
  for (const e of edges) {
    const srcIdx = Number(e.sourceHandle ?? 0);
    const key = `${e.source}:${srcIdx}`;
    const arr = groups.get(key);
    if (arr) arr.push(e);
    else groups.set(key, [e]);
  }

  const dots: ResolvedJunctionDot[] = [];
  const vias = new Map<string, Point>();

  for (const [groupKey, group] of groups) {
    if (group.length < 2) continue;
    const first = group[0]!;
    const srcNode = nodeById.get(first.source);
    if (!srcNode) continue;
    const srcEp = blockNodeToEndpoint(srcNode);
    if (!srcEp) continue;
    const srcIdx = Number(first.sourceHandle ?? 0);
    const { x: sx, y: sy } = sourceOutputPoint(srcEp, srcIdx);
    const axis = outputAxis(srcEp);

    // クランプ範囲: source 端 〜 最も近い target 端 (幹線方向)。
    let nearestTarget = Infinity;
    const targetEps: { ep: EdgeEndpointNode; idx: number }[] = [];
    for (const e of group) {
      const dstNode = nodeById.get(e.target);
      if (!dstNode) continue;
      const dstEp = blockNodeToEndpoint(dstNode);
      if (!dstEp) continue;
      const dstIdx = Number(e.targetHandle ?? 0);
      nearestTarget = Math.min(nearestTarget, targetTrunkCoord(dstEp, dstIdx, axis));
      targetEps.push({ ep: dstEp, idx: dstIdx });
    }
    if (targetEps.length < 2) continue; // 端点が解決できない枝が多いと分岐成立せず
    const srcCoord = along(axis, { x: sx, y: sy });
    const lo = Math.min(srcCoord, nearestTarget);
    const hi = Math.max(srcCoord, nearestTarget);

    // 手動グループ (waypoint エントリが存在) は、値の妥当性に関わらず自動算出を
    // スキップする (= v1 から継承した「手動エントリ存在 → auto を一切抑制」方針)。
    // 不正値 (非有限) は ● を打たないが auto には戻さない (= 二重表示防止)。
    const rawEntry = waypoints[groupKey];
    if (rawEntry !== undefined) {
      const norm = normalizeWaypointEntry(rawEntry);
      if (norm) {
        // 幹線上に再構成 + クランプした via に ● 1 個。
        const via = reconstructVia(norm.axis, norm.pos, sx, sy, lo, hi);
        if (Number.isFinite(via.x) && Number.isFinite(via.y)) {
          vias.set(groupKey, via);
          dots.push({
            x: via.x,
            y: via.y,
            groupKey,
            manual: true,
            axis: norm.axis,
            lo,
            hi,
            sx,
            sy,
          });
        }
      }
      continue;
    }

    // 自動: 描画と同一幾何の polyline から分岐点を算出。
    const polylines: Point[][] = [];
    for (const { ep, idx } of targetEps) {
      polylines.push(computeStepEdgePolyline(srcEp, srcIdx, ep, idx));
    }
    for (const p of findJunctionPoints(polylines)) {
      dots.push({
        x: p.x,
        y: p.y,
        groupKey,
        manual: false,
        axis,
        lo,
        hi,
        sx,
        sy,
      });
    }
  }
  return { dots, vias };
}
