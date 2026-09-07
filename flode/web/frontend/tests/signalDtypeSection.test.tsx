// SPEC-0027 (SM-D Stage 0): SignalDtypeSection の vitest。
// 行描画 / 失敗時非表示 / unknown 表示 / shadow_note / 300ms debounce + abort。

import { cleanup, render, screen } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "../src/api/client";
import { SignalDtypeSection } from "../src/components/SignalDtypeSection";
import { useAppStore } from "../src/store/appStore";
import type { DtypesResponse, FlwModel } from "../src/types/api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) => {
      if (typeof fallback === "string") return fallback;
      if (
        fallback !== null &&
        typeof fallback === "object" &&
        "defaultValue" in (fallback as Record<string, unknown>)
      ) {
        return String((fallback as Record<string, unknown>).defaultValue);
      }
      return key;
    },
  }),
}));

vi.mock("../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/client")>();
  return { ...actual, resolveModelDtypes: vi.fn() };
});

const resolveModelDtypes = vi.mocked(client.resolveModelDtypes);

// react の act() を testing 環境として明示 (fake timers + act 併用時の警告抑止)
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const MODEL = { blocks: [], connections: [] } as unknown as FlwModel;

function responseFor(entries: DtypesResponse["ports"], diagnostics: DtypesResponse["diagnostics"] = []): DtypesResponse {
  return {
    schema_version: "dtypes.v1",
    ports: entries,
    diagnostics,
    summary: { total_ports: entries.length, by_dtype: {}, unresolved: 0, non_float_ports: 0 },
  };
}

const DEBOUNCE_MS = 300;

beforeEach(() => {
  vi.useFakeTimers();
  useAppStore.setState({ editingModel: MODEL, editingPath: [] });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
});

async function flushDebounce(ms: number = DEBOUNCE_MS): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("SignalDtypeSection (SPEC-0027 Stage 0)", () => {
  it("renders per-port dtype rows, widened hint and the shadow note", async () => {
    resolveModelDtypes.mockResolvedValue(
      responseFor(
        [
          { block_id: "integ", direction: "in", port_index: 0, dtype: "float64" },
          { block_id: "integ", direction: "out", port_index: 0, dtype: "float64" },
          { block_id: "other", direction: "out", port_index: 0, dtype: "int64" },
        ],
        [
          {
            severity: "info",
            code: "dtype.implicit_widening",
            message: "widened",
            block_id: "integ",
            direction: "in",
            port_index: 0,
            from_dtype: "int64",
            to_dtype: "float64",
          },
        ],
      ),
    );
    render(<SignalDtypeSection blockId="integ" />);
    await flushDebounce();

    expect(screen.getByTestId("dtype-in-0").textContent).toBe("float64");
    expect(screen.getByTestId("dtype-out-0").textContent).toBe("float64");
    // 他ブロックの行は描画しない (選択中ブロックのみ)
    expect(screen.queryByText("int64")).toBeNull();
    // D-4 昇格の hint
    expect(screen.getByTestId("dtype-widened-0").textContent).toBe(
      "Widened from int64 to float64",
    );
    // shadow_note は必須 (SPEC-0027 §5.3)
    expect(screen.getByTestId("dtype-shadow-note").textContent).toBe(
      "Display only — does not affect simulation results.",
    );
  });

  it("hides the section silently when the request fails", async () => {
    resolveModelDtypes.mockRejectedValue(new Error("boom"));
    render(<SignalDtypeSection blockId="integ" />);
    await flushDebounce();
    expect(screen.queryByTestId("dtype-shadow-note")).toBeNull();
  });

  it("renders unknown as a dash with an unresolved hint", async () => {
    resolveModelDtypes.mockResolvedValue(
      responseFor([
        { block_id: "sub", direction: "out", port_index: 0, dtype: "unknown" },
      ]),
    );
    render(<SignalDtypeSection blockId="sub" />);
    await flushDebounce();
    expect(screen.getByTestId("dtype-out-0").textContent).toBe("—");
    expect(screen.getByTestId("dtype-unresolved-out-0").textContent).toBe(
      "Not resolved in this release",
    );
  });

  it("does not render while editing inside a subsystem (root scope only)", async () => {
    useAppStore.setState({ editingPath: ["sub1"] });
    resolveModelDtypes.mockResolvedValue(responseFor([]));
    render(<SignalDtypeSection blockId="integ" />);
    await flushDebounce();
    expect(resolveModelDtypes).not.toHaveBeenCalled();
    expect(screen.queryByTestId("dtype-shadow-note")).toBeNull();
  });

  it("debounces edits and aborts the in-flight request on model change", async () => {
    resolveModelDtypes.mockImplementation(
      () => new Promise<DtypesResponse>(() => undefined), // 永遠に pending
    );
    render(<SignalDtypeSection blockId="integ" />);

    // debounce 中 (300ms 未満) の編集は前の timer を潰す → fetch は 1 回も飛ばない
    await flushDebounce(100);
    act(() => {
      useAppStore.setState({
        editingModel: { ...(MODEL as object) } as unknown as FlwModel,
      });
    });
    await flushDebounce(100);
    expect(resolveModelDtypes).not.toHaveBeenCalled();

    // debounce 経過で 1 回だけ飛ぶ
    await flushDebounce();
    expect(resolveModelDtypes).toHaveBeenCalledTimes(1);
    const firstSignal = resolveModelDtypes.mock.calls[0]![1];
    expect(firstSignal?.aborted).toBe(false);

    // in-flight 中にさらに編集 → 旧リクエストは abort される
    act(() => {
      useAppStore.setState({
        editingModel: { ...(MODEL as object) } as unknown as FlwModel,
      });
    });
    expect(firstSignal?.aborted).toBe(true);
    await flushDebounce();
    expect(resolveModelDtypes).toHaveBeenCalledTimes(2);
  });
});
