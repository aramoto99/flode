// v0.32.0: dialogService unit tests。
// queue / resolve / subscribe の振る舞いを確認する (= UI 側 DialogHost は別途
// e2e で検証、ここでは pure service logic のみ)。

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  _resetDialogServiceForTest,
  dialog,
  getCurrentDialog,
  resolveCurrentDialog,
  subscribeDialog,
} from "../src/lib/dialogService";

afterEach(() => {
  _resetDialogServiceForTest();
});

describe("dialogService.alert", () => {
  it("queues an alert and resolves on close", async () => {
    const p = dialog.alert("hello");
    const current = getCurrentDialog();
    expect(current).not.toBeNull();
    expect(current?.kind).toBe("alert");
    expect(current?.message).toBe("hello");

    resolveCurrentDialog(undefined);
    await expect(p).resolves.toBeUndefined();
    expect(getCurrentDialog()).toBeNull();
  });

  it("passes through options.title and options.okLabel", () => {
    void dialog.alert("body", { title: "Heads up", okLabel: "Got it" });
    const current = getCurrentDialog();
    expect(current?.options).toMatchObject({ title: "Heads up", okLabel: "Got it" });
  });
});

describe("dialogService.confirm", () => {
  it("resolves true when OK is selected", async () => {
    const p = dialog.confirm("Delete?");
    resolveCurrentDialog(true);
    await expect(p).resolves.toBe(true);
  });

  it("resolves false when Cancel is selected", async () => {
    const p = dialog.confirm("Delete?");
    resolveCurrentDialog(false);
    await expect(p).resolves.toBe(false);
  });

  it("coerces non-boolean resolution to boolean", async () => {
    const p = dialog.confirm("ok?");
    // Escape 時に undefined を渡す経路を想定: false に丸める
    resolveCurrentDialog(undefined);
    await expect(p).resolves.toBe(false);
  });

  it("passes variant: 'danger' through", () => {
    void dialog.confirm("Delete?", { variant: "danger" });
    expect(getCurrentDialog()?.options).toMatchObject({ variant: "danger" });
  });
});

describe("dialogService.prompt", () => {
  it("resolves the entered string on OK", async () => {
    const p = dialog.prompt("name?");
    resolveCurrentDialog("foo.flw.json");
    await expect(p).resolves.toBe("foo.flw.json");
  });

  it("resolves null on Cancel", async () => {
    const p = dialog.prompt("name?");
    resolveCurrentDialog(null);
    await expect(p).resolves.toBeNull();
  });

  it("exposes defaultValue / placeholder via options", () => {
    void dialog.prompt("name?", {
      defaultValue: "untitled.flw.json",
      placeholder: "type here",
    });
    expect(getCurrentDialog()?.options).toMatchObject({
      defaultValue: "untitled.flw.json",
      placeholder: "type here",
    });
  });
});

describe("dialogService queue", () => {
  it("shows dialogs sequentially when called in parallel", async () => {
    const p1 = dialog.alert("first");
    const p2 = dialog.alert("second");
    const p3 = dialog.confirm("third");

    // 最初は first のみ active
    expect(getCurrentDialog()?.message).toBe("first");

    resolveCurrentDialog(undefined);
    await p1;
    expect(getCurrentDialog()?.message).toBe("second");

    resolveCurrentDialog(undefined);
    await p2;
    expect(getCurrentDialog()?.message).toBe("third");
    expect(getCurrentDialog()?.kind).toBe("confirm");

    resolveCurrentDialog(true);
    await expect(p3).resolves.toBe(true);
    expect(getCurrentDialog()).toBeNull();
  });
});

describe("dialogService subscribe", () => {
  it("notifies listener when active dialog changes", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeDialog(listener);
    void dialog.alert("x");
    expect(listener).toHaveBeenCalledTimes(1);
    resolveCurrentDialog(undefined);
    // close → queue 空なら active=null へ遷移、これも 1 回 notify
    expect(listener).toHaveBeenCalledTimes(2);
    unsubscribe();
    void dialog.alert("y");
    // 解除後は呼ばれない
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("resolveCurrentDialog is a no-op when no active dialog", () => {
    // No active dialog → 呼んでも throw しない
    expect(() => resolveCurrentDialog(undefined)).not.toThrow();
  });
});
