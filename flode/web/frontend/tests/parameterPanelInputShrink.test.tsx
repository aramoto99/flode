// Bug regression: ParameterPanel (Inspector) の値入力欄が narrow sidebar
// (200-280px) で横にはみ出し、横スクロール + ラベル見切れになる問題。
//
// 根本原因は flex item の ``min-width: auto`` (= <input> 固有最小幅 ~150px) で、
// ``min-w-0`` が無いと flex-1 でも縮まずパネル幅を超える。jsdom はレイアウトを
// 計算しないため、はみ出しそのものではなく「値入力が min-w-0 を持ち縮める余地が
// ある」という不変条件を className で検証する (= 回帰ガード)。

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ParameterPanel } from "../src/components/ParameterPanel";
import { useAppStore } from "../src/store/appStore";
import type { FlwModel } from "../src/types/api";

// react-i18next: key をそのまま返す (modelSettingsModal.test と同方針)。
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, params?: Record<string, string> | string) =>
      typeof params === "string" ? params : k,
  }),
}));

// listBlockMetadata だけ stub (appStore 等が使う他 export は actual を維持)。
vi.mock("../src/api/client", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../src/api/client")>();
  return { ...actual, listBlockMetadata: vi.fn(async () => ({ blocks: [] })) };
});

function makeModel(): FlwModel {
  return {
    schema_version: "0.8",
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
        id: "XYGraph_1",
        type: "flode.blocks.sinks.XYGraph",
        // x_label / y_label は文字列、decimals は数値 (string / number 両 branch を網羅)。
        params: { x_label: "x", y_label: "y", decimals: 3 },
      },
    ],
    connections: [],
    layout: {},
  };
}

// Mask Subsystem 編集 (MaskValuesEditor) は別コードパス。mask_params が非空配列の
// ブロックを選択すると bool→select / それ以外→input を描画する。
function makeMaskModel(): FlwModel {
  return {
    schema_version: "0.8",
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
        id: "Sub_1",
        type: "flode.subsystems.Subsystem",
        params: {
          blocks: [],
          mask_params: [
            { name: "gain", type: "float", default: 1, description: "" },
            { name: "enabled", type: "bool", default: false, description: "" },
          ],
          mask_values: { gain: 2, enabled: true },
        },
      },
    ],
    connections: [],
    layout: {},
  };
}

function renderPanel(): ReturnType<typeof render> {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ParameterPanel modelId="test" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useAppStore.setState({
    editingModel: makeModel(),
    editingPath: [],
    selectedNodeId: "XYGraph_1",
  });
});

afterEach(() => {
  cleanup();
});

describe("ParameterPanel: value inputs shrink in a narrow inspector", () => {
  it("string param inputs carry min-w-0 so they can shrink below intrinsic width", () => {
    renderPanel();
    for (const key of ["x_label", "y_label"]) {
      const input = screen.getByTestId(`param-input-${key}`);
      expect(input.className).toContain("min-w-0");
    }
  });

  it("number param input carries min-w-0", () => {
    renderPanel();
    const input = screen.getByTestId("param-input-decimals");
    expect(input.className).toContain("min-w-0");
  });

  it("mask number input and bool select carry min-w-0 (MaskValuesEditor branch)", () => {
    useAppStore.setState({
      editingModel: makeMaskModel(),
      editingPath: [],
      selectedNodeId: "Sub_1",
    });
    renderPanel();
    expect(
      screen.getByTestId("mask-input-gain").className,
    ).toContain("min-w-0");
    expect(
      screen.getByTestId("mask-input-enabled").className,
    ).toContain("min-w-0");
  });
});
