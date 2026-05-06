// パラメータ編集の純粋ロジック (ADR-0012 §(3) ParameterPanel 用)。
// React に依存しないため Vitest unit test で検証可能。

import type { BlockEntry, FlwModel } from "../types/api";

/**
 * パラメータ値が inline 編集可能 (number) かを判定する。
 * Phase 2 改善ではスカラー数値のみ inline 編集対応、それ以外は read-only 表示。
 */
export function isEditableParam(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/**
 * 与えられた string 入力を number にパースする。
 * - 空文字は ``null`` (検証エラーとして扱う)
 * - ``Number()`` で NaN/Infinity になるものは ``null``
 * - 上記以外は有限数を返す
 */
export function parseNumericInput(input: string): number | null {
  if (input.trim() === "") return null;
  const n = Number(input);
  if (!Number.isFinite(n)) return null;
  return n;
}

/**
 * モデル中の特定ブロックのパラメータを 1 件更新した新しいモデルを返す
 * (immutable update)。
 *
 * 既存ブロックや connections は浅い参照として保持し、対象ブロックのみ
 * 新しい参照に置き換える。React Query の cache update 用。
 */
export function updateBlockParam(
  model: FlwModel,
  blockId: string,
  paramKey: string,
  newValue: unknown,
): FlwModel {
  const blocks: BlockEntry[] = model.blocks.map((b) => {
    if (b.id !== blockId) return b;
    return {
      ...b,
      params: { ...b.params, [paramKey]: newValue },
    };
  });
  return { ...model, blocks };
}

/**
 * モデル中で対象ブロックを find する。見つからなければ ``undefined``。
 */
export function findBlock(model: FlwModel, blockId: string): BlockEntry | undefined {
  return model.blocks.find((b) => b.id === blockId);
}
