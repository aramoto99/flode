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

/** ParameterPanel が直接編集可能な型 (number / string / bool / 1-D array)。
 *  v5.4.0 (SPEC-0011) で 1-D 配列を editable に追加。2-D 以上は readOnly 維持。 */
export type PrimitiveParam = number | string | boolean | unknown[];

/**
 * パラメータ値が直接編集可能か判定する。
 *
 * - number / string / bool: 既存通り editable
 * - 1-D 配列 (全要素が number / string): SPEC-0011 で editable に追加
 * - 2-D 以上の配列 / dict / null / ndarray: readOnly JSON 表示
 */
export function isPrimitiveParam(value: unknown): value is PrimitiveParam {
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value === "string") return true;
  if (typeof value === "boolean") return true;
  if (Array.isArray(value)) {
    // 1-D のみ: 全要素が number / string のみ受け入れる (= 2-D 配列 / object
    // 要素を含むものは readOnly に落とす、SPEC-0011 §スコープ外)
    return value.every((v) => typeof v === "number" || typeof v === "string");
  }
  return false;
}

/**
 * string が「長い式」(textarea で編集すべき) か判定する (SPEC-0011 Q3)。
 *
 * 閾値: 40 文字超 or 改行を含む。短い enum-like / 名前なら既存 single-line
 * input、長い数式 (Fcn.expression 等) なら多行 textarea (ExpressionEditor)。
 */
export function isLongStringParam(value: string): boolean {
  return value.length > 40 || value.includes("\n");
}

/**
 * 1-D 配列の要素型を先頭要素から推論する (SPEC-0011 §1.2)。
 *
 * - 空配列: ``"number"`` (LookupTable1D 等の数値配列 default を想定)
 * - 先頭が string: ``"string"``
 * - それ以外: ``"number"``
 */
export function inferArrayElementType(
  value: unknown[],
): "number" | "string" {
  if (value.length === 0) return "number";
  if (typeof value[0] === "string") return "string";
  return "number";
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
