// ADR-0079 Stage 3 (v0.64.0): Inspector の数値欄で配列リテラルを受理するパラメータ。
//
// Inspector は「値の型」でエディタを選ぶため、スカラで保存された数値パラメータを
// 配列 (ベクトル定数 / 行列ゲイン / ベクトル初期状態) に変える手段が JSON / Python
// API しか無かった。本表に載せたパラメータだけ、数値欄に ``[1, 2, 3]`` と書くと
// 配列として commit し、逆に配列欄に ``2.5`` と書くとスカラに戻す。
//
// Python 側 (flode/blocks/*) で「スカラも配列も受ける」パラメータと一致させること
// (dynamicPorts.ts と同じ SSOT 方針)。

import type { PrimitiveParam } from "./paramEdit";

const VECTOR_STATE_TYPES: readonly string[] = [
  "flode.blocks.continuous.Integrator",
  "flode.blocks.continuous.Derivative",
  "flode.blocks.discrete.UnitDelay",
  "flode.blocks.discrete.DiscreteIntegrator",
  "flode.blocks.discrete.RateTransition",
  "flode.blocks.discrete.ZeroOrderHoldDirect",
  "flode.blocks.discontinuities.RateLimiter",
];

/** type_path → 配列化を許す param 名。 */
export const ARRAY_CAPABLE_PARAMS: Readonly<Record<string, readonly string[]>> = {
  "flode.blocks.sources.Constant": ["value"],
  "flode.blocks.mathops.Gain": ["k"],
  ...Object.fromEntries(VECTOR_STATE_TYPES.map((t) => [t, ["x0"]])),
};

/**
 * ``typePath`` のパラメータ ``key`` がスカラ ⇄ 配列の切替を許すか。
 */
export function isArrayCapableParam(typePath: string, key: string): boolean {
  const keys = ARRAY_CAPABLE_PARAMS[typePath];
  return keys !== undefined && keys.includes(key);
}

/** regular shape の n-D 数値配列 (空配列も可) か。 */
function isRegularNumericArray(value: unknown): boolean {
  if (typeof value === "number") return Number.isFinite(value);
  if (!Array.isArray(value)) return false;
  if (value.length === 0) return true;
  const first = value[0];
  if (typeof first === "number") {
    return value.every((v) => typeof v === "number" && Number.isFinite(v));
  }
  if (Array.isArray(first)) {
    const len = first.length;
    return value.every(
      (row) => Array.isArray(row) && row.length === len && isRegularNumericArray(row),
    );
  }
  return false;
}

/**
 * 数値欄に書かれたテキストが配列リテラル (先頭 ``[``) なら parse して返す。
 *
 * @returns 配列 (regular shape の数値 n-D 配列) / 配列リテラルでなければ ``undefined`` /
 *   配列リテラルだが不正なら ``null``。
 */
export function parseArrayLiteral(text: string): PrimitiveParam | null | undefined {
  const trimmed = text.trim();
  if (!trimmed.startsWith("[")) return undefined;
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    return null;
  }
  if (!Array.isArray(parsed) || !isRegularNumericArray(parsed)) return null;
  return parsed;
}
