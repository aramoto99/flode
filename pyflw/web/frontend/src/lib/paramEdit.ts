// パラメータ編集の純粋ロジック (ADR-0012 §(3) ParameterPanel 用)。
// React に依存しないため Vitest unit test で検証可能。

import type { BlockEntry, FlwModel } from "../types/api";

/**
 * パラメータ値が inline 編集可能 (number) かを判定する (legacy, 数値のみ)。
 * 文字列 / bool 含むより広い判定は ``isPrimitiveParam`` を使う。
 */
export function isEditableParam(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** ParameterPanel が直接編集可能な primitive 型 (number / string / bool)。 */
export type PrimitiveParam = number | string | boolean;

/**
 * パラメータ値が primitive (number / string / bool) かを判定する。
 * これら以外 (ndarray / list / dict / null) は read-only JSON 表示。
 */
export function isPrimitiveParam(value: unknown): value is PrimitiveParam {
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value === "string") return true;
  if (typeof value === "boolean") return true;
  return false;
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
