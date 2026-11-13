// ADR-0081 §論点 3 / §4-B (U5): 定義が変わったユーザーブロックとプレースホルダの Inspector。
// - 消えた引数に警告、増えた引数は registry の既定値で表示 (entry には書かない)
// - 型が変わった引数に警告、超過ポートの配線に警告
// - プレースホルダは params を読み取り専用で表示し、理由を出す (entry は変えない)

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ParameterPanel } from "../src/components/ParameterPanel";
import { useAppStore } from "../src/store/appStore";
import type { BlockMetadata, FlwModel } from "../src/types/api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, opts?: string | Record<string, unknown>) =>
      typeof opts === "string"
        ? opts
        : opts !== undefined
          ? `${k}:${JSON.stringify(opts)}`
          : k,
  }),
}));

const USER_TYPE = "flode_ws.filters.Trim";
const GONE_TYPE = "flode_ws.filters.Gone";

const USER_META: BlockMetadata = {
  type_path: USER_TYPE,
  display_name: "Trim",
  category: "",
  icon: "default",
  docstring_summary: "",
  params_spec: [
    { name: "k", type: "float", has_default: true, default: 1.0, description: "" },
    { name: "added", type: "float", has_default: true, default: 0.5, description: "" },
    { name: "label", type: "str", has_default: true, default: "x", description: "" },
  ],
  default_n_inputs: 1,
  default_n_outputs: 1,
  port_shapes_in_default: [[]],
  port_shapes_out_default: [[]],
  tags: [],
  is_container: false,
  mask_capable: false,
  source: "workspace",
  input_names: [],
  output_names: [],
};

vi.mock("../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/client")>();
  return {
    ...actual,
    listBlockMetadata: vi.fn(async () => ({
      schema_version: "blocks.v3",
      blocks: [USER_META],
    })),
  };
});

function model(
  type: string,
  params: Record<string, unknown>,
  connections: FlwModel["connections"] = [],
): FlwModel {
  return {
    schema_version: "0.15",
    simulator: { t_end: 1, dt: 0.01, solver: "RK45", rtol: 1e-3, atol: 1e-6, dt_base: null },
    blocks: [{ id: "B1", type, params }],
    connections,
    layout: {},
  };
}

function renderPanel(m: FlwModel): void {
  useAppStore.setState({ editingModel: m, editingPath: [], selectedNodeId: "B1" });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ParameterPanel modelId="test" />
    </QueryClientProvider>,
  );
}

afterEach(() => cleanup());

describe("ParameterPanel: changed user block definitions", () => {
  it("warns about parameters removed from the block", async () => {
    renderPanel(model(USER_TYPE, { k: 2, bias: 1, opts: { a: 1 } }));
    const row = await screen.findByTestId("param-removed-bias");
    expect(row.getAttribute("data-tone")).toBe("warning");
    expect(row.textContent).toBe("inspector.param.removed");
    expect(screen.queryByTestId("param-removed-k")).toBeNull();
    // 読み取り専用の値 (オブジェクト) も名前を出す
    expect(screen.getByTestId("param-removed-read-only").textContent).toContain('"names":"opts"');
  });

  it("shows added parameters with the registry default without writing them", async () => {
    const m = model(USER_TYPE, { k: 2 });
    renderPanel(m);
    const input = (await screen.findByTestId("param-input-added")) as HTMLInputElement;
    expect(input.value).toBe("0.5");
    expect(useAppStore.getState().editingModel!.blocks[0]!.params).toEqual({ k: 2 });
  });

  it("warns when a kept parameter changed its type", async () => {
    renderPanel(model(USER_TYPE, { k: 2, label: 3 }));
    const hint = await screen.findByTestId("param-type-mismatch-label");
    expect(hint.textContent).toContain('"expected":"string"');
    expect(screen.queryByTestId("param-type-mismatch-k")).toBeNull();
  });

  it("warns about wires beyond the block's ports", async () => {
    renderPanel(
      model(USER_TYPE, { k: 2 }, [
        { src: "X", src_idx: 0, dst: "B1", dst_idx: 1 },
        { src: "B1", src_idx: 3, dst: "Y", dst_idx: 0 },
      ]),
    );
    const hint = await screen.findByTestId("param-excess-ports");
    expect(hint.getAttribute("data-tone")).toBe("error");
    expect(hint.textContent).toContain("in[1], out[3]");
  });
});

describe("ParameterPanel: placeholder", () => {
  it("shows the parameters read-only with the reason and keeps the entry", async () => {
    const params = { k: 2, nested: { a: [1, 2] } };
    renderPanel(model(GONE_TYPE, params));
    const panel = await screen.findByTestId("parameter-panel-placeholder");
    expect(panel).toBeTruthy();
    expect(screen.getByTestId("placeholder-reason").textContent).toContain(GONE_TYPE);
    expect(JSON.parse(screen.getByTestId("placeholder-params").textContent ?? "")).toEqual(params);
    // 編集用の入力は出さない
    expect(screen.queryByTestId("param-input-k")).toBeNull();
    expect(useAppStore.getState().editingModel!.blocks[0]!.params).toBe(params);
  });

  it("is not shown before the registry arrives", async () => {
    // registry 取得前は通常の Inspector (判定しない)
    renderPanel(model(GONE_TYPE, { k: 2 }));
    expect(screen.queryByTestId("parameter-panel-placeholder")).toBeNull();
    await waitFor(() =>
      expect(screen.getByTestId("parameter-panel-placeholder")).toBeTruthy(),
    );
  });
});
