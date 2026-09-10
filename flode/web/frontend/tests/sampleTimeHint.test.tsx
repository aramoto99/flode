// v0.57.0 (ADR-0002 §(2) 改訂): Inspector の sample_time 実効周期ヒント。
// -1 (継承) → 「上流の離散レート、なければ dt に追従」 / 明示値 → 「固定周期」。
// 解決値のグラフ再計算は frontend でしない (規則の説明のみ) — 二重実装回避。

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ParameterPanel } from "../src/components/ParameterPanel";
import { useAppStore } from "../src/store/appStore";
import type { FlwModel } from "../src/types/api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, params?: Record<string, string> | string) =>
      typeof params === "string" ? params : k,
  }),
}));

vi.mock("../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/client")>();
  return { ...actual, listBlockMetadata: vi.fn(async () => ({ blocks: [] })) };
});

function makeModel(sampleTime: number): FlwModel {
  return {
    schema_version: "0.12",
    simulator: {
      t_end: 10,
      dt: 0.01,
      solver: "RK45",
      rtol: 1e-3,
      atol: 1e-6,
      dt_base: null,
    },
    blocks: [
      {
        id: "UnitDelay_1",
        type: "flode.blocks.discrete.UnitDelay",
        params: { sample_time: sampleTime, x0: 0 },
      },
      {
        id: "Gain_1",
        type: "flode.blocks.mathops.Gain",
        params: { k: 2 },
      },
    ],
    connections: [],
    layout: {},
  };
}

function renderPanel(sampleTime: number, selectedNodeId: string): void {
  useAppStore.setState({
    editingModel: makeModel(sampleTime),
    editingPath: [],
    selectedNodeId,
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ParameterPanel modelId="test" />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
});

describe("ParameterPanel: sample_time effective-period hint", () => {
  it("shows the inherited hint for sample_time=-1", () => {
    renderPanel(-1, "UnitDelay_1");
    const hint = screen.getByTestId("param-hint-sample-time");
    expect(hint.textContent).toContain("inspector.sample_time.inherited_hint");
  });

  it("shows the fixed hint for an explicit sample_time", () => {
    renderPanel(0.2, "UnitDelay_1");
    const hint = screen.getByTestId("param-hint-sample-time");
    expect(hint.textContent).toContain("inspector.sample_time.fixed_hint");
  });

  it("renders no hint for blocks without sample_time", () => {
    renderPanel(0.2, "Gain_1");
    expect(screen.queryByTestId("param-hint-sample-time")).toBeNull();
  });
});
