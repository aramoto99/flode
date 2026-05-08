// ADR-0030: グローバル toast store のテスト。
// push / auto-dismiss / 最大件数 / severity デフォルト / clearAll を検証する。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearAllToasts,
  dismissToast,
  pushToast,
  useToastStore,
} from "../src/store/toastStore";

beforeEach(() => {
  // 各 test 開始時に store をクリア
  clearAllToasts();
  // 内部 counter も reset する (= test 間で id を予測可能にする)
  useToastStore.setState({ _nextId: 1 });
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("pushToast", () => {
  it("adds a toast with default severity 'info'", () => {
    const id = pushToast({ message: "hello" });
    expect(id).toBe(1);
    const toasts = useToastStore.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0]).toMatchObject({
      id: 1,
      severity: "info",
      message: "hello",
    });
  });

  it("respects explicit severity", () => {
    pushToast({ severity: "error", message: "boom" });
    pushToast({ severity: "warning", message: "watch out" });
    const toasts = useToastStore.getState().toasts;
    expect(toasts.map((t) => t.severity)).toEqual(["error", "warning"]);
  });

  it("auto-dismisses after default duration (3s for info)", () => {
    pushToast({ severity: "info", message: "hi" });
    expect(useToastStore.getState().toasts).toHaveLength(1);
    vi.advanceTimersByTime(2999);
    expect(useToastStore.getState().toasts).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("auto-dismisses after default duration (5s for warning/error)", () => {
    pushToast({ severity: "warning", message: "w" });
    pushToast({ severity: "error", message: "e" });
    vi.advanceTimersByTime(4999);
    expect(useToastStore.getState().toasts).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("does not auto-dismiss when durationMs <= 0 (persistent)", () => {
    pushToast({ message: "sticky", durationMs: 0 });
    vi.advanceTimersByTime(60000);
    expect(useToastStore.getState().toasts).toHaveLength(1);
  });

  it("respects explicit durationMs", () => {
    pushToast({ message: "fast", durationMs: 100 });
    vi.advanceTimersByTime(99);
    expect(useToastStore.getState().toasts).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("returns increasing ids (= unique handle for manual dismiss)", () => {
    const id1 = pushToast({ message: "a" });
    const id2 = pushToast({ message: "b" });
    const id3 = pushToast({ message: "c" });
    expect(id2).toBeGreaterThan(id1);
    expect(id3).toBeGreaterThan(id2);
  });
});

describe("stacking limit (MAX_TOASTS=3)", () => {
  it("drops oldest when 4th is pushed", () => {
    pushToast({ message: "1" });
    pushToast({ message: "2" });
    pushToast({ message: "3" });
    pushToast({ message: "4" });
    const toasts = useToastStore.getState().toasts;
    expect(toasts.map((t) => t.message)).toEqual(["2", "3", "4"]);
  });

  it("clears the dropped toast's timer (no leak)", () => {
    pushToast({ message: "1", durationMs: 10000 });
    pushToast({ message: "2", durationMs: 10000 });
    pushToast({ message: "3", durationMs: 10000 });
    pushToast({ message: "4", durationMs: 10000 });
    // 最古 "1" は drop 済 + timer も clear 済 → advance しても残り 3 件は変わらず
    vi.advanceTimersByTime(9999);
    expect(useToastStore.getState().toasts).toHaveLength(3);
    vi.advanceTimersByTime(2);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });
});

describe("dismissToast", () => {
  it("removes the specified toast", () => {
    const id1 = pushToast({ message: "a" });
    const id2 = pushToast({ message: "b" });
    dismissToast(id1);
    const toasts = useToastStore.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0]?.id).toBe(id2);
  });

  it("is a no-op for unknown id", () => {
    pushToast({ message: "a" });
    dismissToast(9999);
    expect(useToastStore.getState().toasts).toHaveLength(1);
  });

  it("clears the auto-dismiss timer (= no late firing)", () => {
    const id = pushToast({ message: "a", durationMs: 1000 });
    dismissToast(id);
    // timer が clear されている → advance しても再 dismiss は走らない (state 不変)
    vi.advanceTimersByTime(2000);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });
});

describe("clearAllToasts", () => {
  it("removes all toasts and clears all timers", () => {
    pushToast({ message: "a" });
    pushToast({ message: "b" });
    pushToast({ message: "c" });
    clearAllToasts();
    expect(useToastStore.getState().toasts).toHaveLength(0);
    vi.advanceTimersByTime(60000);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });
});
