// ADR-0030: ``<ToastContainer>`` の render + a11y attribute をテスト。
// store の挙動は toastStore.test.ts でカバー。ここでは render 出力に集中する。

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ToastContainer } from "../src/components/Toast";
import {
  clearAllToasts,
  pushToast,
  useToastStore,
} from "../src/store/toastStore";

beforeEach(() => {
  clearAllToasts();
  useToastStore.setState({ _nextId: 1 });
});

afterEach(() => {
  cleanup();
  clearAllToasts();
});

describe("ToastContainer render", () => {
  it("renders region even when no toasts (= AT must observe region from initial paint)", () => {
    render(<ToastContainer />);
    const region = screen.getByRole("region");
    expect(region.children).toHaveLength(0);
    // region 自体に aria-live=polite が常時付く (= 後から追加された toast が
    // AT に通知されるよう、初回 paint から live region として登録される)。
    expect(region.getAttribute("aria-live")).toBe("polite");
  });

  it("renders region wrapper with i18n aria-label when toasts exist", () => {
    pushToast({ message: "hello", durationMs: 0 });
    render(<ToastContainer />);
    const region = screen.getByRole("region");
    expect(region.getAttribute("aria-label")).toBeTruthy();
  });
});

describe("ToastContainer a11y by severity", () => {
  it("info → role=status, aria-live=polite", () => {
    pushToast({ severity: "info", message: "info msg", durationMs: 0 });
    render(<ToastContainer />);
    const item = screen.getByRole("status");
    expect(item.getAttribute("aria-live")).toBe("polite");
    expect(within(item).getByText("info msg")).toBeTruthy();
  });

  it("success → role=status, aria-live=polite", () => {
    pushToast({ severity: "success", message: "ok", durationMs: 0 });
    render(<ToastContainer />);
    const item = screen.getByRole("status");
    expect(item.getAttribute("aria-live")).toBe("polite");
  });

  it("warning → role=alert, aria-live=assertive", () => {
    pushToast({ severity: "warning", message: "warn", durationMs: 0 });
    render(<ToastContainer />);
    const item = screen.getByRole("alert");
    expect(item.getAttribute("aria-live")).toBe("assertive");
  });

  it("error → role=alert, aria-live=assertive", () => {
    pushToast({ severity: "error", message: "boom", durationMs: 0 });
    render(<ToastContainer />);
    const item = screen.getByRole("alert");
    expect(item.getAttribute("aria-live")).toBe("assertive");
  });
});

describe("ToastContainer rendering multiple toasts", () => {
  it("renders all stacked toasts in DOM order", () => {
    pushToast({ severity: "info", message: "A", durationMs: 0 });
    pushToast({ severity: "warning", message: "B", durationMs: 0 });
    pushToast({ severity: "error", message: "C", durationMs: 0 });
    render(<ToastContainer />);
    expect(screen.getAllByRole("status")).toHaveLength(1); // info
    expect(screen.getAllByRole("alert")).toHaveLength(2); // warning + error
    expect(screen.getByText("A")).toBeTruthy();
    expect(screen.getByText("B")).toBeTruthy();
    expect(screen.getByText("C")).toBeTruthy();
  });
});

describe("ToastContainer dismiss button", () => {
  it("each toast has a labeled close button", () => {
    pushToast({ severity: "info", message: "x", durationMs: 0 });
    render(<ToastContainer />);
    // i18n key resolution によって 'Dismiss notification' 等の文言になる
    const button = screen.getByRole("button");
    expect(button.getAttribute("aria-label")).toBeTruthy();
  });

  it("clicking close dismisses that specific toast", () => {
    pushToast({ severity: "info", message: "x", durationMs: 0 });
    pushToast({ severity: "info", message: "y", durationMs: 0 });
    render(<ToastContainer />);
    expect(useToastStore.getState().toasts).toHaveLength(2);
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(2);
    buttons[0]?.click();
    expect(useToastStore.getState().toasts).toHaveLength(1);
  });
});
