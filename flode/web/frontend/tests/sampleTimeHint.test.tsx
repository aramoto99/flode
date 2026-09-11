// SPEC-0030 (v0.58.0): Inspector の sample_time 3 モード UI。
// select (基準クロック "dt" / 継承 -1 / 明示値) + モード別ヒント。
// 解決値のグラフ再計算は frontend でしない (規則の説明のみ) — 二重実装回避。

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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

// 3 モード select は registry の requires_discrete_rate (backend ClassVar が
// SSOT) を見て出すため、UnitDelay の最小メタデータを返す
const UNIT_DELAY_META = {
  type_path: "flode.blocks.discrete.UnitDelay",
  params_spec: [],
  requires_discrete_rate: true,
} as unknown as import("../src/types/api").BlockMetadata;

vi.mock("../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/client")>();
  return {
    ...actual,
    listBlockMetadata: vi.fn(async () => ({ blocks: [UNIT_DELAY_META] })),
  };
});

function makeModel(sampleTime: number | string): FlwModel {
  return {
    schema_version: "0.13",
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

function renderPanel(
  sampleTime: number | string,
  selectedNodeId: string,
): void {
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

describe("ParameterPanel: sample_time three-mode UI (SPEC-0030)", () => {
  it('shows base-clock mode and hint for sample_time="dt"', async () => {
    renderPanel("dt", "UnitDelay_1");
    const mode = (await screen.findByTestId(
      "param-sample-time-mode",
    )) as HTMLSelectElement;
    expect(mode.value).toBe("base");
    expect(
      screen.getByTestId("param-hint-sample-time").textContent,
    ).toContain("inspector.sample_time.base_hint");
    // 明示値入力は隠れる
    expect(screen.queryByTestId("param-input-sample_time")).toBeNull();
  });

  it("shows upstream mode and hint for sample_time=-1", async () => {
    renderPanel(-1, "UnitDelay_1");
    const mode = (await screen.findByTestId(
      "param-sample-time-mode",
    )) as HTMLSelectElement;
    expect(mode.value).toBe("upstream");
    expect(
      screen.getByTestId("param-hint-sample-time").textContent,
    ).toContain("inspector.sample_time.upstream_hint");
  });

  it("shows explicit mode with number input for a positive sample_time", async () => {
    renderPanel(0.2, "UnitDelay_1");
    const mode = (await screen.findByTestId(
      "param-sample-time-mode",
    )) as HTMLSelectElement;
    expect(mode.value).toBe("explicit");
    const input = screen.getByTestId(
      "param-input-sample_time",
    ) as HTMLInputElement;
    expect(input.value).toBe("0.2");
    expect(
      screen.getByTestId("param-hint-sample-time").textContent,
    ).toContain("inspector.sample_time.fixed_hint");
  });

  it('switching to base commits the string "dt"', async () => {
    renderPanel(0.2, "UnitDelay_1");
    fireEvent.change(await screen.findByTestId("param-sample-time-mode"), {
      target: { value: "base" },
    });
    const model = useAppStore.getState().editingModel;
    const delay = model?.blocks.find((b) => b.id === "UnitDelay_1");
    expect(delay?.params.sample_time).toBe("dt");
  });

  it("switching to explicit seeds the value with the model dt", async () => {
    renderPanel("dt", "UnitDelay_1");
    fireEvent.change(await screen.findByTestId("param-sample-time-mode"), {
      target: { value: "explicit" },
    });
    const model = useAppStore.getState().editingModel;
    const delay = model?.blocks.find((b) => b.id === "UnitDelay_1");
    expect(delay?.params.sample_time).toBe(0.01); // dt の値のコピー
  });

  it("renders no sample-time UI for blocks without the param", () => {
    renderPanel(0.2, "Gain_1");
    expect(screen.queryByTestId("param-sample-time-mode")).toBeNull();
    expect(screen.queryByTestId("param-hint-sample-time")).toBeNull();
  });
});
