// ADR-0030: グローバル toast 通知機構。
// Zustand store + auto-dismiss timer + severity 別 a11y 属性。
//
// 設計方針:
// - i18n キー解決は呼び出し側 component の ``t()`` で済ませる (= store は resolved
//   な string を受ける、ADR-0030 §技術的負債)。
// - timer ID は **モジュールスコープの Map** で管理 (= Zustand state の immutable
//   原則を保つ、code-reviewer MUST 修正)。dismiss 時に clearTimeout で leak 防止。
// - 最大 3 件 stacking、超過時は最古を即時 dismiss (= UX が screen を覆い尽くさない)。

import { create } from "zustand";

export type ToastSeverity = "info" | "success" | "warning" | "error";

export interface ToastItem {
  /** 一意 ID (= 単調増加 counter)。React の key + dismissToast の引数に使う。 */
  id: number;
  severity: ToastSeverity;
  message: string;
}

interface ToastStore {
  toasts: ToastItem[];
  /** 内部用: 単調増加 ID counter。push で +1 する。 */
  _nextId: number;
}

/** stacking の上限。超過時は最古を即時 dismiss する (ADR-0030 §スタッキング)。 */
const MAX_TOASTS = 3;

/** severity 別のデフォルト dismiss 時間 (ms)。warning/error は長めに残す。 */
const DEFAULT_DURATION_MS: Record<ToastSeverity, number> = {
  info: 3000,
  success: 3000,
  warning: 5000,
  error: 5000,
};

/** 各 toast の dismiss timer (id → handle)。
 *
 * Zustand state とは分離してモジュールスコープに置く (= 副作用 / 非 React state)。
 * これにより ``setState`` を経由しない in-place ミューテーション (= immutable 違反)
 * を避けつつ、devtools / immer ミドルウェア追加時の互換性を保つ
 * (code-reviewer MUST 修正)。
 */
const _timers = new Map<number, ReturnType<typeof setTimeout>>();

export const useToastStore = create<ToastStore>(() => ({
  toasts: [],
  _nextId: 1,
}));

/**
 * toast を queue に追加して auto-dismiss timer を設定する (副作用関数)。
 *
 * @param severity ``"info" | "success" | "warning" | "error"``。デフォルト ``"info"``。
 * @param message 表示する文言 (resolved な string、i18n キー解決は呼び出し側で済ませる)。
 * @param durationMs auto-dismiss までの ms。省略時は severity 別デフォルト
 *   (info/success=3000、warning/error=5000)。``0`` 以下を渡すと auto-dismiss しない
 *   (= 手動 dismiss 必須、永続表示用途)。
 * @returns 採番された toast id (manual dismiss に使える)。
 */
export function pushToast(args: {
  severity?: ToastSeverity;
  message: string;
  durationMs?: number;
}): number {
  const severity = args.severity ?? "info";
  const duration =
    args.durationMs !== undefined
      ? args.durationMs
      : DEFAULT_DURATION_MS[severity];
  // setter 関数形式で常に最新 state を読む (= Zustand 公式推奨、同一同期スタックでの
  // 連続 push でも _nextId の更新が直列化される、code-reviewer MUST 修正)。
  let assignedId = 0;
  let droppedIds: number[] = [];
  useToastStore.setState((prev) => {
    assignedId = prev._nextId;
    const newItem: ToastItem = {
      id: assignedId,
      severity,
      message: args.message,
    };
    let nextToasts = [...prev.toasts, newItem];
    if (nextToasts.length > MAX_TOASTS) {
      const dropped = nextToasts.slice(0, nextToasts.length - MAX_TOASTS);
      droppedIds = dropped.map((t) => t.id);
      nextToasts = nextToasts.slice(-MAX_TOASTS);
    }
    return { toasts: nextToasts, _nextId: prev._nextId + 1 };
  });
  // drop された旧 toast の timer を確実に clear (leak 防止)。
  for (const droppedId of droppedIds) {
    const handle = _timers.get(droppedId);
    if (handle !== undefined) {
      clearTimeout(handle);
      _timers.delete(droppedId);
    }
  }
  if (duration > 0) {
    const handle = setTimeout(() => dismissToast(assignedId), duration);
    _timers.set(assignedId, handle);
  }
  return assignedId;
}

/** 指定 id の toast を即時 dismiss する。timer も clear して leak を防ぐ。 */
export function dismissToast(id: number): void {
  const handle = _timers.get(id);
  if (handle !== undefined) {
    clearTimeout(handle);
    _timers.delete(id);
  }
  useToastStore.setState((prev) => ({
    toasts: prev.toasts.filter((t) => t.id !== id),
  }));
}

/** 全 toast を即時 dismiss する (= ナビゲーション時の cleanup 等)。 */
export function clearAllToasts(): void {
  for (const handle of _timers.values()) {
    clearTimeout(handle);
  }
  _timers.clear();
  useToastStore.setState({ toasts: [] });
}
