// ブロック線図の慣例「分岐点 (junction / branch point) に ● を打つ」を実現する
// 純粋幾何ロジック。
//
// このツールの分岐は「同一出力ポートから複数の独立 edge を引く」方式
// (``BranchableEdge``) のため、線が重なって途中で分かれる「分岐点」に
// マーカーは描かれていなかった。本モジュールは **同一 source ポートグループ
// の edge polyline 群** を受け取り、線が実際に分かれる座標 (= mid-wire の
// 分岐点) を算出する。無関係な信号同士の交差 (crossover) は同一グループに
// 入らないため ● は出ない (= 慣例どおり「交差 ≠ 接続」)。
//
// polyline は ``computeStepEdgePolyline`` (= 描画 edge と同一の 90° 折れ線、
// ``borderRadius=0``) を共有して作る前提。これにより ● 位置が実際の配線と
// 一致する。

import type { Point } from "./edgeRectIntersect";

/** 分岐点座標を dedupe する際の丸め精度 (flow px)。
 *  浮動小数誤差で同一点が複数 ● に分裂しない程度に丸める。 */
export const JUNCTION_DEDUP_PRECISION = 0.5;

/** 方向ベクトル比較・長さ判定の許容誤差 (flow px)。 */
const EPS = 1e-6;

/** 単位方向ベクトル比較の許容誤差。step polyline の方向ベクトルは
 *  ``(±1, 0)`` / ``(0, ±1)`` に限定されるため 1e-3 で十分に分離できる。 */
const DIR_EPS = 1e-3;

interface Vec {
  x: number;
  y: number;
}

function sub(a: Point, b: Point): Vec {
  return { x: a.x - b.x, y: a.y - b.y };
}

function len(v: Vec): number {
  return Math.hypot(v.x, v.y);
}

/** ``from`` → ``to`` の単位方向ベクトル。長さ 0 (退化セグメント) なら null。 */
function unitDir(from: Point, to: Point): Vec | null {
  const v = sub(to, from);
  const l = len(v);
  if (l < EPS) return null;
  return { x: v.x / l, y: v.y / l };
}

function sameDir(a: Vec, b: Vec): boolean {
  return Math.abs(a.x - b.x) < DIR_EPS && Math.abs(a.y - b.y) < DIR_EPS;
}

/**
 * 始点を共有する 2 つの polyline が「重なり区間を抜けて初めて方向が分かれる」
 * 点を返す。
 *
 * 軸並行 step polyline を前提に、両者を始点から同時に走査し、各ステップで
 * 進行方向が一致する限り短い側のセグメント長だけ進める。方向が分かれた地点が
 * 分岐点 (= ● を打つ座標)。一方が他方の (方向的) prefix のまま尽きた場合は
 * 短い側の終点 (= tap 点) を返す。
 *
 * @param a 1 本目の polyline (2 点以上)。``a[0]`` は ``b[0]`` と同一座標である想定。
 * @param b 2 本目の polyline (2 点以上)。
 * @returns 分岐点。判定不能 / 完全一致 (重複接続) の場合は null。
 */
function pairDivergence(
  a: readonly Point[],
  b: readonly Point[],
): Point | null {
  if (a.length < 2 || b.length < 2) return null;
  let ia = 0;
  let ib = 0;
  let cur: Point = a[0];
  while (ia < a.length - 1 && ib < b.length - 1) {
    const da = unitDir(cur, a[ia + 1]);
    if (da === null) {
      ia++;
      continue;
    }
    const db = unitDir(cur, b[ib + 1]);
    if (db === null) {
      ib++;
      continue;
    }
    if (!sameDir(da, db)) return cur; // ここで分岐
    const la = len(sub(a[ia + 1], cur));
    const lb = len(sub(b[ib + 1], cur));
    if (Math.abs(la - lb) < EPS) {
      // 同じ頂点で両者が折れる (まだ重なり継続)
      cur = a[ia + 1];
      ia++;
      ib++;
    } else if (la < lb) {
      // a が先に頂点に到達。cur は b セグメント上に乗ったまま次へ。
      cur = a[ia + 1];
      ia++;
    } else {
      cur = b[ib + 1];
      ib++;
    }
  }
  // 両者が同時に尽きた = 完全一致 polyline (= 重複接続)。分岐点が無いため
  // ターゲット座標に ● を打たないよう null を返す。
  if (ia === a.length - 1 && ib === b.length - 1) return null;
  // 片方だけ尽きた = 一方が他方の (方向的) prefix。短い側の終点を tap 点として返す。
  return cur;
}

/**
 * 同一 source ポートから出る複数 edge の polyline 群から、分岐点 (● を打つ
 * 座標) の一覧を返す。
 *
 * 全ペアの分岐点を集めて dedupe する。3 分岐が trunk から別々の位置で枝分かれ
 * する場合は分岐点が 2 つ返る (= 最後の 1 本は枝分かれ先がないため ● 不要)。
 *
 * @param polylines 同一 source グループの edge polyline 群 (各 2 点以上、
 *   先頭点が全て同一 source 座標である想定)。
 * @returns 分岐点座標 (dedupe + ``JUNCTION_DEDUP_PRECISION`` で丸め済み)。
 *   グループが 1 本以下なら空配列。
 */
export function findJunctionPoints(
  polylines: readonly (readonly Point[])[],
): Point[] {
  if (polylines.length < 2) return [];
  const out: Point[] = [];
  const seen = new Set<string>();
  for (let i = 0; i < polylines.length; i++) {
    for (let j = i + 1; j < polylines.length; j++) {
      const p = pairDivergence(polylines[i], polylines[j]);
      if (p === null) continue;
      // 退化入力で NaN / Infinity が混入しても DOM に不正座標を渡さない。
      if (!Number.isFinite(p.x) || !Number.isFinite(p.y)) continue;
      const rx = Math.round(p.x / JUNCTION_DEDUP_PRECISION);
      const ry = Math.round(p.y / JUNCTION_DEDUP_PRECISION);
      const key = `${rx},${ry}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({
        x: rx * JUNCTION_DEDUP_PRECISION,
        y: ry * JUNCTION_DEDUP_PRECISION,
      });
    }
  }
  return out;
}
