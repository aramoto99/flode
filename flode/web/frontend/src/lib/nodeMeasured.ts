// キャンバスの再描画で、前回 React Flow が測ったブロックの寸法 (``measured``) を引き継ぐ。
//
// DiagramCanvas は描画のたびに ``modelToDiagram`` で node を作り直して React Flow に渡す。
// ``measured`` の無い node を受け取ると、React Flow (``adoptUserNodes`` → ``parseHandles``) は
// handle の位置 (handleBounds) を捨てて測り直すまで配線を描かない (= 全配線が 1 フレーム消え、
// DOM 要素も作り直される)。形が変わっていない node には前回の ``measured`` を付けて、handle の
// 位置を保たせる。形に効く値が変わった node には付けず、今までどおり測り直させる (古い寸法・
// handle 位置を残さない)。
//
// 注意: React Flow v12 の内部構造に依存している (``nodeLookup`` の ``internals.userNode`` と
// ``measured``、および ``parseHandles`` が ``measured`` のある node の handleBounds を保つこと)。
// React Flow の更新でこれが変わると、配線が毎回作り直される挙動に戻る (または古い handle 位置が
// 残る)。E2E ``tests/e2e/edges-stable-on-render.spec.ts`` で検知できる。

import type { BlockNode } from "./diagramConverter";
import { resolveControlSlots } from "./dynamicPorts";

/** 前回 React Flow に渡した node (``internals.userNode``) のうち、ここで比べる部分。 */
interface PreviousUserNode {
  type?: string;
  width?: number;
  height?: number;
  data: Record<string, unknown>;
}

/** React Flow の内部 node のうち、ここで使う部分。 */
export interface PreviousInternalNode {
  measured?: { width?: number; height?: number };
  internals: { userNode: PreviousUserNode };
}

/** BlockNodeView と同じ条件で制御スロットを読む (ユーザーブロックは制御スロットを持たない)。 */
function controlSlotsOf(data: Partial<BlockNode["data"]>): string {
  if (data.userBlock !== undefined) return "";
  const slots = resolveControlSlots(data.params as Record<string, unknown> | undefined);
  return `${slots.hasEnable ? "E" : ""}${slots.hasTrigger ? "T" : ""}`;
}

/**
 * handle の位置・ブロックの寸法に効く値が同じか。
 *
 * handle の配置と wrapper の寸法は、次の値だけで決まる (BlockNodeView の
 * ``inputHandlePosition`` / ``outputHandlePosition`` と形・寸法の計算):
 * node の type / width / height、data の blockType (形の種類) / nInputs / nOutputs / flipped /
 * shapeWidth / shapeHeight / isContainer / userBlock の種類 (面)、Subsystem の制御スロット
 * (Enable / Trigger の有無。``resolveControlSlots``。enable / trigger は上辺、data 入力は左辺で、
 * nInputs が同じでも配置が変わる)。
 *
 * BlockNodeView の handle の計算に新しい入力を足したら、ここの比較にも足すこと。
 */
function sameShape(next: BlockNode, prev: PreviousUserNode): boolean {
  const a = next.data;
  const b = prev.data as Partial<BlockNode["data"]>;
  return (
    next.type === prev.type &&
    next.width === prev.width &&
    next.height === prev.height &&
    a.blockType === b.blockType &&
    a.nInputs === b.nInputs &&
    a.nOutputs === b.nOutputs &&
    (a.flipped ?? false) === (b.flipped ?? false) &&
    a.shapeWidth === b.shapeWidth &&
    a.shapeHeight === b.shapeHeight &&
    a.isContainer === b.isContainer &&
    a.userBlock?.kind === b.userBlock?.kind &&
    controlSlotsOf(a) === controlSlotsOf(b)
  );
}

/**
 * 形が前回と同じ node に、前回 React Flow が測った ``measured`` を付けて返す。
 * 前回が無い・まだ測っていない・形が変わった node はそのまま返す (React Flow が測り直す)。
 *
 * @param nodes - 今回 React Flow に渡す node。
 * @param previous - id → 前回の内部 node (React Flow の ``nodeLookup``)。呼ぶ側は、表示中の
 *   スコープやファイルが前回の描画から変わったときは何も返さない関数を渡す (別スコープの同じ id
 *   と混同しないため)。
 * @returns ``measured`` を引き継いだ node の配列 (変えない node は同じ参照)。
 */
export function carryOverMeasured(
  nodes: readonly BlockNode[],
  previous: (id: string) => PreviousInternalNode | undefined,
): BlockNode[] {
  return nodes.map((n) => {
    const prev = previous(n.id);
    const measured = prev?.measured;
    if (
      prev === undefined ||
      measured === undefined ||
      measured.width === undefined ||
      measured.height === undefined ||
      !sameShape(n, prev.internals.userNode)
    ) {
      return n;
    }
    return { ...n, measured: { width: measured.width, height: measured.height } };
  });
}
