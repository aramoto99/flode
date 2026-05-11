// Simulink-style "auto-connect on edge" 検知ロジック (v0.26.0)。
//
// ブロックをエッジの上にドロップ / 移動したとき、ブロックの入力ポート 0 と
// 出力ポート 0 がエッジ路上に揃っていれば、自動でその場に接続する (= 元エッジを
// 削除し、source → block → target の 2 本に置き換える)。
//
// 前提:
//   - smooth-step (90°折れ線) edge を使う前提で、path は次の 3 セグメントから成る:
//     (sx, sy) → (midX, sy) → (midX, ty) → (tx, ty)
//     - sx === tx の縮退ケースは想定不要 (= 通常 source.right と target.left は別 x)
//   - 本実装は **block 入力 0 と出力 0 が同じ水平セグメント上にある場合のみ** splice。
//     vertical segment 上のケースは対象外 (= 縦に流れるエッジに横向きブロックを
//     刺すケースは稀、まずは横流れの典型シナリオを正しく処理する)。
//   - block は **SISO** (n_inputs=1, n_outputs=1) のみ対象。Multi-port は
//     ポート選択が曖昧なので skip (= 利用者が手動で接続する)。

import type { BlockMetadata } from "../types/api";
import { getBlockShape, type BlockShape } from "./blockShapes";
import { resolvePortCounts } from "./dynamicPorts";

/** マッチ判定の許容距離 (px)。block 中心と edge セグメントの y 差 / x 範囲の余裕。 */
export const SPLICE_TOLERANCE_PX = 10;

export interface BlockGeom {
  id: string;
  type: string;
  params: Record<string, unknown>;
  /** flow 座標における top-left (= editingModel.layout[id]) */
  x: number;
  y: number;
  /** layout で override されている場合のみ。none なら shape.width/height にフォールバック。 */
  w?: number;
  h?: number;
}

export interface EdgeGeom {
  src: string;
  src_idx: number;
  dst: string;
  dst_idx: number;
}

/** edge 1 本の判定結果。none = 該当なし。 */
export interface SpliceCandidate {
  /** 置き換える既存 edge */
  edge: EdgeGeom;
}

/**
 * Handle Y 座標を block.y からの絶対 px で返す。
 *
 * shape kind に応じて handle の top% が決まり、block の height と乗算する。
 * Triangle / Circle の出力は中央 (50%)、Bar / Trapezoid 等は等間隔。
 */
function inputHandleY(shape: BlockShape, h: number, idx: number, n: number): number {
  // BlockNodeView の inputHandlePosition と同じロジック (= 全 shape kind で
  // 左辺等間隔配置)。code-reviewer MUST 修正: 旧コードは shape kind ごとに
  // 同一式を返す dead if 分岐で、将来 BlockNodeView が shape 依存になった時に
  // ここの更新が漏れて auto-splice が誤判定する罠だったため統一。
  void shape;
  return ((idx + 1) * h) / (n + 1);
}

function outputHandleY(shape: BlockShape, h: number, idx: number, n: number): number {
  if (shape.kind === "triangle-r" || shape.kind === "circle") {
    return h / 2;
  }
  return ((idx + 1) * h) / (n + 1);
}

function blockEffectiveSize(
  shape: BlockShape,
  b: BlockGeom,
): { w: number; h: number } {
  return {
    w: b.w ?? shape.width,
    h: b.h ?? shape.height,
  };
}

/**
 * SISO block の input port 0 / output port 0 の絶対座標。
 *
 * 入力 port は block 左辺 (x = block.x)、出力 port は右辺 (x = block.x + w)。
 * 反転 (flipped) は本関数の呼び出し側で考慮不要 (= flipped 状態でも実際の
 * connection は backend semantic で扱われ、port_idx は固定。本 helper では
 * 「実 path との交点」だけを見るので、絵的反転は無関係)。
 */
export function blockSISOPorts(
  b: BlockGeom,
  nIn: number,
  nOut: number,
): {
  input: { x: number; y: number };
  output: { x: number; y: number };
} | null {
  if (nIn !== 1 || nOut !== 1) return null;
  const shape = getBlockShape(b.type);
  const { w, h } = blockEffectiveSize(shape, b);
  const inY = inputHandleY(shape, h, 0, nIn);
  const outY = outputHandleY(shape, h, 0, nOut);
  return {
    input: { x: b.x, y: b.y + inY },
    output: { x: b.x + w, y: b.y + outY },
  };
}

/**
 * smooth-step edge の source / target handle 絶対座標を返す。
 */
function edgeHandlePositions(
  src: BlockGeom,
  srcIdx: number,
  srcNIn: number,
  srcNOut: number,
  dst: BlockGeom,
  dstIdx: number,
  dstNIn: number,
  dstNOut: number,
): {
  source: { x: number; y: number };
  target: { x: number; y: number };
} {
  void srcNIn;
  void dstNOut;
  const srcShape = getBlockShape(src.type);
  const dstShape = getBlockShape(dst.type);
  const { w: sw, h: sh } = blockEffectiveSize(srcShape, src);
  const { h: dh } = blockEffectiveSize(dstShape, dst);
  const sy = src.y + outputHandleY(srcShape, sh, srcIdx, srcNOut);
  const ty = dst.y + inputHandleY(dstShape, dh, dstIdx, dstNIn);
  return {
    source: { x: src.x + sw, y: sy },
    target: { x: dst.x, y: ty },
  };
}

/**
 * point (px, py) が水平セグメント (y=segY, x ∈ [xMin, xMax]) の上にあるか。
 */
function onHorizontalSegment(
  px: number,
  py: number,
  segY: number,
  xMin: number,
  xMax: number,
  tol: number,
): boolean {
  if (Math.abs(py - segY) > tol) return false;
  return px >= xMin - tol && px <= xMax + tol;
}

/**
 * block が edge にスプライスできるか判定。
 *
 * smooth-step path = (sx,sy) → (midX,sy) → (midX,ty) → (tx,ty)
 * 水平セグメント 2 本 (source 側と target 側) のどちらかに block input/output が
 * ともに乗っていれば match。``sy === ty`` の縮退時は 1 本の水平線。
 */
export function blockOnEdge(
  blockInput: { x: number; y: number },
  blockOutput: { x: number; y: number },
  sourceHandle: { x: number; y: number },
  targetHandle: { x: number; y: number },
  tolerance: number = SPLICE_TOLERANCE_PX,
): boolean {
  const { x: sx, y: sy } = sourceHandle;
  const { x: tx, y: ty } = targetHandle;
  // block の input が出力側より右にあったら逆向き (= invalid)
  if (blockInput.x > blockOutput.x) return false;
  // source-side horizontal: y = sy, x ∈ [sx, midX]
  const midX = (sx + tx) / 2;
  const onSourceSide =
    onHorizontalSegment(blockInput.x, blockInput.y, sy, sx, midX, tolerance) &&
    onHorizontalSegment(
      blockOutput.x,
      blockOutput.y,
      sy,
      sx,
      midX,
      tolerance,
    );
  if (onSourceSide) return true;
  // target-side horizontal: y = ty, x ∈ [midX, tx]
  const onTargetSide =
    onHorizontalSegment(blockInput.x, blockInput.y, ty, midX, tx, tolerance) &&
    onHorizontalSegment(
      blockOutput.x,
      blockOutput.y,
      ty,
      midX,
      tx,
      tolerance,
    );
  if (onTargetSide) return true;
  // 縮退 (sy === ty): 単一水平線 y=sy, x∈[sx,tx]
  if (Math.abs(sy - ty) < tolerance) {
    return (
      onHorizontalSegment(
        blockInput.x,
        blockInput.y,
        sy,
        sx,
        tx,
        tolerance,
      ) &&
      onHorizontalSegment(
        blockOutput.x,
        blockOutput.y,
        sy,
        sx,
        tx,
        tolerance,
      )
    );
  }
  return false;
}

/**
 * blocks / edges から、block (= 対象) がスプライスすべき edge を探す。
 *
 * 返り値:
 *   - 該当 edge が **正確に 1 件** ならその edge を返す
 *   - 0 件 or 2 件以上 (= 曖昧) なら ``null``
 *   - block が SISO でない、registry meta が無い等の前提不成立も ``null``
 *
 * 自己 loop 防止: source/target が block 自身の edge は対象外。
 */
export function findSpliceCandidate(
  block: BlockGeom,
  blocks: readonly BlockGeom[],
  edges: readonly EdgeGeom[],
  registry: ReadonlyMap<string, BlockMetadata>,
  tolerance: number = SPLICE_TOLERANCE_PX,
): SpliceCandidate | null {
  const meta = registry.get(block.type);
  const ports = resolvePortCounts(block.type, block.params, meta);
  const bp = blockSISOPorts(block, ports.nInputs, ports.nOutputs);
  if (!bp) return null;

  const blocksById = new Map<string, BlockGeom>(blocks.map((b) => [b.id, b]));
  const matches: EdgeGeom[] = [];

  for (const edge of edges) {
    // 自己 loop 防止
    if (edge.src === block.id || edge.dst === block.id) continue;
    const src = blocksById.get(edge.src);
    const dst = blocksById.get(edge.dst);
    if (!src || !dst) continue;
    const srcMeta = registry.get(src.type);
    const dstMeta = registry.get(dst.type);
    const srcPorts = resolvePortCounts(src.type, src.params, srcMeta);
    const dstPorts = resolvePortCounts(dst.type, dst.params, dstMeta);
    const { source, target } = edgeHandlePositions(
      src,
      edge.src_idx,
      srcPorts.nInputs,
      srcPorts.nOutputs,
      dst,
      edge.dst_idx,
      dstPorts.nInputs,
      dstPorts.nOutputs,
    );
    if (blockOnEdge(bp.input, bp.output, source, target, tolerance)) {
      matches.push(edge);
    }
  }

  // 0 件 / 2+ 件は曖昧なので何もしない
  if (matches.length !== 1) return null;
  return { edge: matches[0]! };
}
