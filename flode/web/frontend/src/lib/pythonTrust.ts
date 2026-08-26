// SPEC-0023 / ADR-0073 §論点 4 (S): PythonFunction 実行の「承認 digest」記録。
//
// これは **UX 機構であってセキュリティ機構ではない** (REST を直接叩けば ack を
// 自分で付けられる)。目的は「このモデルは Python を実行する」の告知と同意を
// 初回だけ求め、同じコードの再実行では邪魔をしないこと。
//
// - 保存先: localStorage (``storageKeys.ts`` の慣例、server に永続 state を作らない)
// - digest はサーバだけが計算する (``crypto.subtle`` は非 secure context で使えない
//   ため client では計算しない)。client は 409 の detail に載った digest を保存し、
//   次回 start で echo する
// - 失効: コードが 1 文字でも変われば digest が変わる = 自動失効

import type { ApiError } from "../api/client";
import type { FailurePayload } from "../types/api";
import { makePythonTrustKey } from "./storageKeys";

const memoryFallback = new Map<string, string>();

function _storage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** 保存済み digest (無ければ ``null``)。 */
export function readPythonTrust(
  workspaceHash: string | null,
  modelPath: string,
): string | null {
  const key = makePythonTrustKey(workspaceHash ?? "-", modelPath);
  const s = _storage();
  if (s !== null) {
    try {
      // localStorage が使える環境ではそれだけを信頼する (= サイトデータ削除で
      // 承認も消える)。memory fallback は storage が使えない時だけ参照する。
      return s.getItem(key);
    } catch {
      // private mode 等で getItem が throw するケースは memory fallback へ
    }
  }
  return memoryFallback.get(key) ?? null;
}

/** digest を保存する。localStorage が使えない環境ではセッション内メモリに保持。 */
export function writePythonTrust(
  workspaceHash: string | null,
  modelPath: string,
  digest: string,
): void {
  const key = makePythonTrustKey(workspaceHash ?? "-", modelPath);
  const s = _storage();
  if (s !== null) {
    try {
      s.setItem(key, digest);
      return;
    } catch {
      // quota / private mode: memory fallback へ (= 次回セッションで再確認になるだけ)
    }
  }
  memoryFallback.set(key, digest);
}

export interface PythonUnconfirmed {
  digest: string;
  blockLabels: string[];
}

/** 409 ``python_function_unconfirmed`` の detail から digest / block 一覧を取り出す。
 *  該当しない例外なら ``null``。 */
export function parsePythonUnconfirmed(e: unknown): PythonUnconfirmed | null {
  const err = e as Partial<ApiError> | null;
  if (!err || err.status !== 409) return null;
  const s = err.structured as FailurePayload | null | undefined;
  if (!s || s.category !== "python_function_unconfirmed") return null;
  const digest = s.template_args.digest;
  if (typeof digest !== "string" || digest.length === 0) return null;
  const labelsRaw = s.template_args.block_labels;
  const blockLabels = Array.isArray(labelsRaw)
    ? labelsRaw.filter((x): x is string => typeof x === "string")
    : [];
  return { digest, blockLabels };
}

/**
 * start API を soft gate 込みで呼ぶ純関数 (React 非依存、テスト容易)。
 *
 * 1. 保存済み digest があれば ack 付きで start
 * 2. 409 ``python_function_unconfirmed`` なら ``confirm`` を呼び、承認なら digest を
 *    保存して **同じ start を ack 付きで 1 回だけ再送**
 * 3. 拒否なら ``null`` (= 失敗ではなくキャンセル)
 *
 * それ以外の例外はそのまま投げる (= 呼び出し側の既存エラー処理へ)。
 */
export async function startWithPythonGate<T>(
  start: (ack: string | undefined) => Promise<T>,
  opts: {
    workspaceHash: string | null;
    modelPath: string;
    confirm: (info: PythonUnconfirmed) => Promise<boolean>;
  },
): Promise<T | null> {
  const saved = readPythonTrust(opts.workspaceHash, opts.modelPath);
  try {
    return await start(saved ?? undefined);
  } catch (e) {
    const info = parsePythonUnconfirmed(e);
    if (info === null) throw e;
    const ok = await opts.confirm(info);
    if (!ok) return null;
    writePythonTrust(opts.workspaceHash, opts.modelPath, info.digest);
    return await start(info.digest);
  }
}
