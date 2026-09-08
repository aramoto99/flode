// SPEC-0028 §5.5: モデルレベルの dtype 解決結果 store (SM-D Stage 1)。
//
// pythonFunctionSpec.ts と同じ「module cache + useSyncExternalStore」流儀。
// SignalDtypeSection (Inspector) と DisplayLiveValue (canvas) が同じ結果を読む。
// frontend は dtype を**再計算しない** — backend の resolve-dtypes 結果の
// 表示のみ (ADR-0077 §データ整合性 1 の SSOT 制約)。

import { useEffect, useSyncExternalStore } from "react";

import { resolveModelDtypes } from "../api/client";
import { useAppStore } from "../store/appStore";
import type { DtypesResponse, FlwModel } from "../types/api";

/** 編集 → 再取得の debounce (SPEC-0028、Stage 0 の Q3 を踏襲)。 */
const RESOLVE_DEBOUNCE_MS = 300;

let current: DtypesResponse | null = null;
let version = 0;
const listeners = new Set<() => void>();

function notify(): void {
  version += 1;
  listeners.forEach((l) => l());
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

function getVersion(): number {
  return version;
}

/** 現在の解決結果 (未取得 / 失敗時は null)。 */
export function getDtypeResolution(): DtypesResponse | null {
  return current;
}

/** @internal テスト用: store を直接設定する。 */
export function _setDtypeResolutionForTest(res: DtypesResponse | null): void {
  current = res;
  notify();
}

/** @internal テスト用: fetch 直列化の module 状態をリセットする。 */
export function _resetDtypeFetchStateForTest(): void {
  _seq += 1; // 進行中の結果を無効化
  _running = false;
  _queued = null;
}

/** 指定ポートの解決済み dtype (無ければ null)。 */
export function dtypeForPort(
  blockId: string,
  direction: "in" | "out",
  portIndex: number,
): string | null {
  if (!current) return null;
  const entry = current.ports.find(
    (p) =>
      p.block_id === blockId &&
      p.direction === direction &&
      p.port_index === portIndex,
  );
  return entry ? entry.dtype : null;
}

/**
 * モデルが dtype を宣言しているか (backend `has_declared_dtype` と同じ root 走査)。
 *
 * param の**存在確認のみ**で dtype の計算はしない (SSOT 非侵害)。
 */
export function hasDeclaredDtype(model: FlwModel | null): boolean {
  const blocks = (
    model as unknown as {
      blocks?: Array<{ params?: Record<string, unknown> }>;
    } | null
  )?.blocks;
  if (!blocks) return false;
  return blocks.some((b) => {
    const d = b.params?.dtype;
    return typeof d === "string" && d !== "auto";
  });
}

/** 現在の解決結果を購読する hook (store 更新で再レンダリング)。 */
export function useDtypeResolution(): DtypesResponse | null {
  useSyncExternalStore(subscribe, getVersion, getVersion);
  return current;
}

// security SHOULD-4 (2026-09-08): サーバ側の resolve はキャンセルできない
// (run_in_threadpool の同期処理) ため、**in-flight は常に 1 本に直列化**する。
// 実行中に来た編集は「最新 1 件だけ」を queue し、完了後にまとめて解決する
// (連続編集で worker thread を食い潰さない)。stale な結果は seq で破棄。
let _seq = 0;
let _running = false;
let _queued: FlwModel | null = null;

async function _fetchAndPublish(model: FlwModel): Promise<void> {
  if (_running) {
    _queued = model; // 最新だけ残す (中間状態は解決しない)
    return;
  }
  _running = true;
  const mySeq = ++_seq;
  try {
    const res = await resolveModelDtypes(model);
    if (mySeq === _seq) {
      current = res;
      notify();
    }
  } catch {
    if (mySeq === _seq) {
      current = null;
      notify();
    }
  } finally {
    _running = false;
    if (_queued !== null) {
      const next = _queued;
      _queued = null;
      void _fetchAndPublish(next);
    }
  }
}

/**
 * editingModel の変化を 300ms debounce で fetch し store を更新する。
 * アプリで 1 箇所 (DiagramCanvas) だけ mount する。失敗時は null
 * (読み手はセクション非表示 / 既定整形へフォールバック)。
 */
export function useDtypeResolutionFetcher(): void {
  const editingModel = useAppStore((s) => s.editingModel);
  useEffect(() => {
    if (!editingModel) {
      current = null;
      notify();
      return;
    }
    const timer = window.setTimeout(() => {
      void _fetchAndPublish(editingModel);
    }, RESOLVE_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [editingModel]);
}
