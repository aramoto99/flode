// Toolbar の終了時刻欄 (StopTimeInput): 空欄 = 終了時刻なし ("inf")。
// unbounded のときは空欄 + placeholder "∞" で表示し、空欄で確定すると
// t_end="inf" が store に書かれる (2026-11-14)。

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StopTimeInput } from "../src/components/Toolbar";
import { UNBOUNDED_SYMBOL } from "../src/lib/timeUtil";
import { useAppStore } from "../src/store/appStore";
import type { FlwModel, TEnd } from "../src/types/api";

// react-i18next: key をそのまま返す (他の component test と同方針)。
// Toolbar が import する i18n 初期化 (initReactI18next) は actual を残す。
vi.mock("react-i18next", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-i18next")>();
  return { ...actual, useTranslation: () => ({ t: (k: string) => k }) };
});

function makeModel(tEnd: TEnd): FlwModel {
  return {
    schema_version: "0.8",
    simulator: { t_end: tEnd, dt: 0.01, solver: "RK45", rtol: 1e-3, atol: 1e-6, dt_base: null },
    blocks: [],
    connections: [],
    layout: {},
  };
}

function input(): HTMLInputElement {
  return screen.getByTestId("toolbar-stop-time") as HTMLInputElement;
}

function tEndInStore(): TEnd | undefined {
  return useAppStore.getState().editingModel?.simulator.t_end;
}

beforeEach(() => {
  useAppStore.setState({ editingModel: null, editingPath: [], dirty: false });
});

afterEach(() => {
  cleanup();
});

describe("StopTimeInput", () => {
  it("shows finite t_end as number", () => {
    useAppStore.setState({ editingModel: makeModel(10) });
    render(<StopTimeInput disabled={false} />);
    expect(input().value).toBe("10");
    expect(input().placeholder).toBe(UNBOUNDED_SYMBOL);
  });

  it("shows unbounded t_end as empty field with ∞ placeholder", () => {
    useAppStore.setState({ editingModel: makeModel("inf") });
    render(<StopTimeInput disabled={false} />);
    expect(input().value).toBe("");
    expect(input().placeholder).toBe(UNBOUNDED_SYMBOL);
  });

  it("commits empty field as 'inf'", () => {
    useAppStore.setState({ editingModel: makeModel(10) });
    render(<StopTimeInput disabled={false} />);
    fireEvent.change(input(), { target: { value: "" } });
    fireEvent.blur(input());
    expect(tEndInStore()).toBe("inf");
    expect(input().value).toBe("");
  });

  it("commits typed 'INF' as 'inf' and shows it as empty", () => {
    useAppStore.setState({ editingModel: makeModel(10) });
    render(<StopTimeInput disabled={false} />);
    fireEvent.change(input(), { target: { value: "INF" } });
    fireEvent.blur(input());
    expect(tEndInStore()).toBe("inf");
    expect(input().value).toBe("");
  });

  it("normalizes 'inf' typed while already unbounded to empty", () => {
    useAppStore.setState({ editingModel: makeModel("inf") });
    render(<StopTimeInput disabled={false} />);
    fireEvent.change(input(), { target: { value: "inf" } });
    fireEvent.blur(input());
    expect(tEndInStore()).toBe("inf");
    expect(input().value).toBe("");
  });

  it("replaces unbounded with a number", () => {
    useAppStore.setState({ editingModel: makeModel("inf") });
    render(<StopTimeInput disabled={false} />);
    fireEvent.change(input(), { target: { value: "5" } });
    fireEvent.blur(input());
    expect(tEndInStore()).toBe(5);
    expect(input().value).toBe("5");
  });

  it("reverts invalid input to the previous value", () => {
    useAppStore.setState({ editingModel: makeModel(10) });
    render(<StopTimeInput disabled={false} />);
    fireEvent.change(input(), { target: { value: "-1" } });
    fireEvent.blur(input());
    expect(tEndInStore()).toBe(10);
    expect(input().value).toBe("10");
  });

  it("commits on Enter", () => {
    useAppStore.setState({ editingModel: makeModel(10) });
    render(<StopTimeInput disabled={false} />);
    input().focus();
    fireEvent.change(input(), { target: { value: "" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    fireEvent.blur(input()); // jsdom: .blur() の focusout を明示発火
    expect(tEndInStore()).toBe("inf");
  });

  it("commits whitespace-only as 'inf'", () => {
    useAppStore.setState({ editingModel: makeModel(10) });
    render(<StopTimeInput disabled={false} />);
    fireEvent.change(input(), { target: { value: "   " } });
    fireEvent.blur(input());
    expect(tEndInStore()).toBe("inf");
    expect(input().value).toBe("");
  });

  it("Escape discards the edit (cleared field does not become 'inf')", () => {
    useAppStore.setState({ editingModel: makeModel(10) });
    render(<StopTimeInput disabled={false} />);
    input().focus();
    fireEvent.change(input(), { target: { value: "" } });
    fireEvent.keyDown(input(), { key: "Escape" });
    expect(input().value).toBe("10");
    fireEvent.blur(input());
    expect(tEndInStore()).toBe(10);
  });

  it("follows external store changes", () => {
    useAppStore.setState({ editingModel: makeModel("inf") });
    render(<StopTimeInput disabled={false} />);
    expect(input().value).toBe("");
    act(() => {
      useAppStore.setState({ editingModel: makeModel(10) });
    });
    expect(input().value).toBe("10");
  });

  it("normalizes an equal finite value ('1e1' → '10')", () => {
    useAppStore.setState({ editingModel: makeModel(10) });
    render(<StopTimeInput disabled={false} />);
    fireEvent.change(input(), { target: { value: "1e1" } });
    fireEvent.blur(input());
    expect(tEndInStore()).toBe(10);
    expect(input().value).toBe("10");
  });

  it("does not rewrite store when Infinity (number) is blurred untouched", () => {
    useAppStore.setState({ editingModel: makeModel(Number.POSITIVE_INFINITY) });
    render(<StopTimeInput disabled={false} />);
    fireEvent.blur(input());
    expect(tEndInStore()).toBe(Number.POSITIVE_INFINITY);
    expect(useAppStore.getState().dirty).toBe(false);
  });

  it("does nothing on blur when no model is open (enabled field)", () => {
    render(<StopTimeInput disabled={false} />);
    fireEvent.blur(input());
    expect(useAppStore.getState().editingModel).toBeNull();
    expect(useAppStore.getState().dirty).toBe(false);
  });

  it("hides ∞ placeholder when no model is open", () => {
    render(<StopTimeInput disabled={true} />);
    expect(input().value).toBe("");
    expect(input().placeholder).toBe("");
  });
});
