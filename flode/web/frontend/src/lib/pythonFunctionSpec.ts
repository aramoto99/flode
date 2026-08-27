// SPEC-0023 / ADR-0073 §論点 1: PythonFunction の静的解析結果 (introspect) の
// クライアント側キャッシュ。
//
// - key は **code 文字列そのもの**。同じコードは同じ構造なので block id に依存しない
// - ``resolvePortCounts`` (同期・純関数) から読めるよう module-level Map で持つ。
//   introspect の完了は ``subscribe`` で通知し、React 側は ``usePythonSpecVersion``
//   で再描画をトリガーする (= ロード直後の 1 往復ぶんだけ registry default で描かれる、
//   ADR-0073 §Consequences)
// - モデル JSON にはキャッシュしない (導出データの二重書き手を作らない)

import { introspectPythonFunctions } from "../api/client";
import type {
  BlockEntry,
  FlwModel,
  PythonFunctionIntrospectResult,
} from "../types/api";
import { PYTHON_FUNCTION_TYPE } from "./blockTypes";

const cache = new Map<string, PythonFunctionIntrospectResult>();
const inflight = new Map<string, Promise<void>>();
const listeners = new Set<() => void>();
let version = 0;

function notify(): void {
  version += 1;
  for (const l of listeners) l();
}

/** 同期取得。未解決 (= introspect 未完了 / 未要求) なら ``undefined``。 */
export function getCachedPythonSpec(
  code: unknown,
): PythonFunctionIntrospectResult | undefined {
  if (typeof code !== "string") return undefined;
  return cache.get(code);
}

/** 解析結果を直接投入する (= PythonCodeDialog が Apply 前に introspect した結果を
 *  ``updateBlockParams`` より先にキャッシュへ入れ、剪定判定を正しくするため)。 */
export function putPythonSpec(
  code: string,
  result: PythonFunctionIntrospectResult,
): void {
  cache.set(code, result);
  notify();
}

/** 通知購読 (``useSyncExternalStore`` 用)。 */
export function subscribePythonSpecs(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** 現在の cache 世代 (``useSyncExternalStore`` の snapshot)。 */
export function getPythonSpecVersion(): number {
  return version;
}

/**
 * ``codes`` のうち未キャッシュのものを 1 回の introspect でまとめて解決する。
 * 通信失敗時は cache に何も入れない (= 次回再試行される)。
 */
export async function ensurePythonSpecs(codes: Iterable<string>): Promise<void> {
  const wanted = Array.from(new Set(codes));
  // 契約: resolve 時点で ``codes`` は全て cache 済み (失敗した要求は除く)。
  // 他呼び出しで in-flight のものはその Promise を待ち、未要求分だけ新規に問い合わせる。
  const pending = wanted
    .map((c) => inflight.get(c))
    .filter((p): p is Promise<void> => p !== undefined);
  const missing = wanted.filter((c) => !cache.has(c) && !inflight.has(c));
  if (missing.length === 0) {
    await Promise.all(pending);
    return;
  }
  const items = missing.map((code, i) => ({ key: `c${i}`, code }));
  const p = (async () => {
    try {
      const resp = await introspectPythonFunctions(items);
      for (const { key, code } of items) {
        const r = resp.results[key];
        if (r !== undefined) cache.set(code, r);
      }
      notify();
    } finally {
      for (const { code } of items) inflight.delete(code);
    }
  })();
  for (const { code } of items) inflight.set(code, p);
  await Promise.all([...pending, p]);
}

/**
 * 1 件だけ introspect し、結果を cache に投入して返す (PythonCodeDialog /
 * PythonFunctionEditor 共通の commit 経路)。通信失敗は throw (cache 不変)。
 */
export async function introspectSingle(
  code: string,
): Promise<PythonFunctionIntrospectResult> {
  const cached = cache.get(code);
  if (cached !== undefined) return cached;
  const resp = await introspectPythonFunctions([{ key: "k", code }]);
  const result = resp.results.k;
  if (result === undefined) {
    throw new Error("introspect returned no result for the requested key");
  }
  putPythonSpec(code, result);
  return result;
}

/** モデル (Subsystem 内部を再帰) から PythonFunction の code を集める。 */
export function collectPythonCodes(model: FlwModel | null | undefined): string[] {
  const out: string[] = [];
  const walk = (blocks: unknown): void => {
    if (!Array.isArray(blocks)) return;
    for (const b of blocks as BlockEntry[]) {
      if (!b || typeof b !== "object") continue;
      if (b.type === PYTHON_FUNCTION_TYPE && typeof b.params?.code === "string") {
        out.push(b.params.code);
      }
      const inner = (b.params as Record<string, unknown> | undefined)?.blocks;
      if (Array.isArray(inner)) walk(inner);
    }
  };
  walk(model?.blocks);
  return out;
}

/** test 用: キャッシュを空にする。 */
export function _resetPythonSpecCacheForTest(): void {
  cache.clear();
  inflight.clear();
  notify();
}
