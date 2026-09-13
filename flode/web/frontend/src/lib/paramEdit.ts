// パラメータ編集の純粋ロジック (ADR-0012 §(3) ParameterPanel 用)。
// React に依存しないため Vitest unit test で検証可能。

import type { BlockEntry, FlwModel } from "../types/api";
import { isLogicalOperatorUnary } from "./dynamicPorts";

/**
 * パラメータ値が inline 編集可能 (number) かを判定する (legacy, 数値のみ)。
 * 文字列 / bool 含むより広い判定は ``isPrimitiveParam`` を使う。
 */
export function isEditableParam(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** ParameterPanel が直接編集可能な型 (number / string / bool / n-D array)。
 *  v5.4.0 (SPEC-0011) で 1-D 配列を editable に追加。
 *  v5.6.0 (SPEC-0017) で 2-D 数値配列 (= LookupTable2D.table) を GridEditor 経由で追加。
 *  v5.8.0 (SPEC-0018) で 3-D 以上の n-D 数値配列 (= LookupTableND.table) を JSON 編集で追加。 */
export type PrimitiveParam = number | string | boolean | unknown[];

/**
 * 値が n-D 数値配列 (regular shape、全要素 number) かを再帰判定する。
 * 空配列は規則的とみなす (= true)。
 */
function isRegularNumericArray(value: unknown): boolean {
  if (typeof value === "number") return true;
  if (!Array.isArray(value)) return false;
  if (value.length === 0) return true;
  // 全要素が同じ shape (= 同じ深さ + 同じ長さ) でなければならない
  const first = value[0];
  if (typeof first === "number") {
    return value.every((v) => typeof v === "number");
  }
  if (Array.isArray(first)) {
    const firstLen = first.length;
    return value.every(
      (row) =>
        Array.isArray(row) &&
        row.length === firstLen &&
        isRegularNumericArray(row),
    );
  }
  return false;
}

/**
 * パラメータ値が直接編集可能か判定する。
 *
 * - number / string / bool: 既存通り editable
 * - 1-D 配列 (全要素が number / string): SPEC-0011 で editable に追加
 * - 2-D 数値配列 (= 行が全て number 配列で regular shape): SPEC-0017 GridEditor 対応
 * - 3-D 以上の n-D 数値配列 (regular shape): SPEC-0018 LookupTableND 対応 (JSON 編集)
 * - dict / null / ndarray: readOnly JSON 表示
 */
export function isPrimitiveParam(value: unknown): value is PrimitiveParam {
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value === "string") return true;
  if (typeof value === "boolean") return true;
  if (Array.isArray(value)) {
    if (value.length === 0) return true; // 空配列は 1-D 扱い (元の挙動維持)
    // 1-D: 全要素が number / string
    if (typeof value[0] === "number" || typeof value[0] === "string") {
      return value.every((v) => typeof v === "number" || typeof v === "string");
    }
    // 2-D 以上: 全要素 number の regular shape
    if (Array.isArray(value[0])) {
      return isRegularNumericArray(value);
    }
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

/**
 * 1 つのパラメータ変更に伴って backend の validation 上 **必ず一緒に変わる** 従属
 * パラメータを揃えた params を返す (bug-fix 2026-09-13)。
 *
 * 現状の対象は LogicalOperator のみ (``logic.py``: 単項演算子 NOT は ``n_inputs=1``
 * 固定、それ以外は ``n_inputs >= 2``):
 *
 * - ``operator`` を変更 → 単項なら ``n_inputs=1``、単項から 2 項へ戻したら
 *   ``max(2, 現在値)``
 * - ``n_inputs`` を直接変更 → 単項なら常に 1、2 項なら ``max(2, 入力値)`` に clamp
 *
 * 既定 n_inputs=2 のまま NOT を選ぶと run / 保存時に BlockSpecError になり、Inspector
 * からは原因が見えなかった。単項判定は ``dynamicPorts.ts`` の
 * ``isLogicalOperatorUnary`` と共有する (ポート数の描画と一致させるため)。
 *
 * @param block - 編集中のブロック
 * @param key - 変更したパラメータ名
 * @param value - 変更後の値
 * @returns 従属パラメータを揃えた新しい params
 */
export function withDependentParams(
  block: BlockEntry,
  key: string,
  value: unknown,
): Record<string, unknown> {
  const next: Record<string, unknown> = { ...block.params, [key]: value };
  if (!block.type.endsWith(".LogicalOperator")) return next;
  const currentN =
    typeof block.params.n_inputs === "number" ? block.params.n_inputs : 2;
  if (key === "operator") {
    if (isLogicalOperatorUnary(value)) {
      next.n_inputs = 1;
    } else if (isLogicalOperatorUnary(block.params.operator) || currentN < 2) {
      next.n_inputs = Math.max(2, currentN);
    }
  } else if (key === "n_inputs" && typeof value === "number") {
    next.n_inputs = isLogicalOperatorUnary(block.params.operator)
      ? 1
      : Math.max(2, Math.trunc(value));
  }
  return next;
}
