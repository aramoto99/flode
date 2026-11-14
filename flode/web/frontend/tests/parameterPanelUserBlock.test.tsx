// ADR-0081 §7 (U4): Inspector でユーザーブロックのパラメータ説明 (params_spec[].description)
// と選択肢 (enum_values) を出す。組み込みブロックの表示は変えない。

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ParameterPanel } from "../src/components/ParameterPanel";
import { useAppStore } from "../src/store/appStore";
import type { BlockMetadata, FlwModel } from "../src/types/api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, fallback?: string) => (typeof fallback === "string" ? fallback : k),
  }),
}));

const RLO = String.fromCharCode(0x202e);
const USER_TYPE = "flode_ws.filters.MovingAverage";
const BUILTIN_TYPE = "flode.blocks.file_writer.FileWriter";

const USER_META: BlockMetadata = {
  type_path: USER_TYPE,
  display_name: "Moving average",
  category: "filters",
  icon: "default",
  docstring_summary: `Average of the last n samples.${RLO}`,
  params_spec: [
    {
      name: "n",
      type: "int",
      has_default: true,
      default: 4,
      description: "Number of samples\nin the window.",
    },
    {
      name: "gain",
      type: "float",
      has_default: true,
      default: 1,
      description: "Output gain.",
      description_i18n: { ja: "出力のゲイン", en: "Output gain (en)." },
    },
    {
      name: "method",
      type: "str",
      has_default: true,
      default: "mean",
      description: "How to combine the samples.",
      enum_values: ["mean", `median${RLO}`],
    },
  ],
  default_n_inputs: 1,
  default_n_outputs: 1,
  port_shapes_in_default: [[]],
  port_shapes_out_default: [[]],
  tags: [],
  is_container: false,
  mask_capable: false,
  source: "workspace",
  input_names: ["u"],
  output_names: ["y"],
};

const BUILTIN_META: BlockMetadata = {
  ...USER_META,
  type_path: BUILTIN_TYPE,
  display_name: "File Writer",
  source: "builtin",
  params_spec: [
    {
      name: "format",
      type: "str",
      has_default: true,
      default: "auto",
      description: "builtin description is not shown",
      enum_values: ["auto", "csv"],
    },
  ],
};

vi.mock("../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/client")>();
  return {
    ...actual,
    listBlockMetadata: vi.fn(async () => ({
      schema_version: "blocks.v3",
      blocks: [USER_META, BUILTIN_META],
    })),
  };
});

function model(type: string, params: Record<string, unknown>): FlwModel {
  return {
    schema_version: "0.15",
    simulator: { t_end: 1, dt: 0.01, solver: "RK45", rtol: 1e-3, atol: 1e-6, dt_base: null },
    blocks: [{ id: "B1", type, params }],
    connections: [],
    layout: {},
  };
}

function renderPanel(): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ParameterPanel modelId="test" />
    </QueryClientProvider>,
  );
}

afterEach(() => cleanup());

describe("ParameterPanel: user block descriptions and choices", () => {
  it("shows each parameter description under its row, cleaned", async () => {
    useAppStore.setState({
      editingModel: model(USER_TYPE, { n: 4, method: "mean" }),
      editingPath: [],
      selectedNodeId: "B1",
    });
    renderPanel();
    const desc = await screen.findByTestId("param-desc-n");
    expect(desc.textContent).toBe("Number of samples in the window.");
    expect(screen.getByTestId("param-desc-method").textContent).toBe(
      "How to combine the samples.",
    );
    // 見出し 2 行目に表示名と説明 (整形済み)
    const summary = screen.getByTestId("block-header-user-summary");
    expect(summary.textContent).toBe("Moving average — Average of the last n samples.");
  });

  it("picks the language-specific parameter description for the UI language", async () => {
    useAppStore.setState({
      editingModel: model(USER_TYPE, { n: 4, method: "mean", gain: 1 }),
      editingPath: [],
      selectedNodeId: "B1",
    });
    renderPanel();
    // テストの i18n は言語未設定 = "en"
    const desc = await screen.findByTestId("param-desc-gain");
    expect(desc.textContent).toBe("Output gain (en).");
  });

  it("renders choices with the select, keeping raw values and cleaning labels", async () => {
    useAppStore.setState({
      editingModel: model(USER_TYPE, { n: 4, method: "mean" }),
      editingPath: [],
      selectedNodeId: "B1",
    });
    renderPanel();
    // registry の取得後に select へ切り替わる (取得前は値の型どおりの文字列入力)
    await waitFor(() =>
      expect(screen.getByTestId("param-input-method").tagName).toBe("SELECT"),
    );
    const select = screen.getByTestId("param-input-method") as HTMLSelectElement;
    const options = Array.from(select.options);
    expect(options.map((o) => o.value)).toEqual(["mean", `median${RLO}`]);
    expect(options.map((o) => o.textContent)).toEqual(["mean", "median"]);
    fireEvent.change(select, { target: { value: `median${RLO}` } });
    const blk = useAppStore.getState().editingModel!.blocks[0]!;
    expect(blk.params.method).toBe(`median${RLO}`);
  });

  it("shows the registry default for a parameter missing from the model", async () => {
    useAppStore.setState({
      editingModel: model(USER_TYPE, { n: 4 }),
      editingPath: [],
      selectedNodeId: "B1",
    });
    renderPanel();
    const select = (await screen.findByTestId("param-input-method")) as HTMLSelectElement;
    expect(select.value).toBe("mean");
  });

  it("does not change builtin blocks (no description row, no summary line)", async () => {
    useAppStore.setState({
      editingModel: model(BUILTIN_TYPE, { format: "auto" }),
      editingPath: [],
      selectedNodeId: "B1",
    });
    renderPanel();
    await waitFor(() => expect(screen.queryByTestId("param-input-format")).toBeTruthy());
    expect(screen.queryByTestId("param-desc-format")).toBeNull();
    expect(screen.queryByTestId("block-header-user-summary")).toBeNull();
  });
});
