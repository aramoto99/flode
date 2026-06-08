// SPEC-0016 v0.39.1 amendment: ParameterPanel が registry.params_spec と
// block.params を merge して、モデルにない param も default 値で Inspector
// に表示することの統合テスト。
//
// 旧モデルで保存された FileWriter (= n_inputs / labels のみ) に対し、
// backend が path / format を追加した場合、Inspector で path / format も
// 編集可能で表示されることを検証する。

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ParameterPanel } from "../src/components/ParameterPanel";
import { useAppStore } from "../src/store/appStore";
import type { BlockMetadata, FlwModel } from "../src/types/api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, fallback?: string) =>
      typeof fallback === "string" ? fallback : k,
  }),
}));

// listBlockMetadata を mock し、FileWriter の params_spec に path / format を
// 含めた payload を返す (= 新 backend を simulate)。
const FILEWRITER_META: BlockMetadata = {
  type_path: "pyflw.blocks.file_writer.FileWriter",
  display_name: "File Writer",
  category: "sinks",
  icon: "sinks.file_writer",
  docstring_summary: "Write simulation results to a file.",
  params_spec: [
    {
      name: "n_inputs",
      type: "int",
      has_default: true,
      default: 1,
      description: "",
    },
    {
      name: "labels",
      type: "list[str] | None",
      has_default: true,
      default: null,
      description: "",
    },
    {
      name: "path",
      type: "str",
      has_default: true,
      default: "",
      description: "",
    },
    {
      name: "format",
      type: "str",
      has_default: true,
      default: "auto",
      description: "",
      enum_values: ["auto", "csv", "npz"],
    },
  ],
  default_n_inputs: 1,
  default_n_outputs: 0,
  port_shapes_in_default: [[1]],
  port_shapes_out_default: [],
  tags: [],
  is_container: false,
  mask_capable: false,
};

vi.mock("../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/client")>();
  return {
    ...actual,
    listBlockMetadata: vi.fn(async () => ({ blocks: [FILEWRITER_META] })),
  };
});

function makeLegacyFileWriterModel(): FlwModel {
  // 旧 backend (v0.39.0) で保存された FileWriter。
  // path / format は params に含まれていない。
  return {
    schema_version: "0.9",
    simulator: {
      t_end: 1,
      dt: 0.01,
      solver: "RK45",
      rtol: 1e-3,
      atol: 1e-6,
      dt_base: null,
    },
    blocks: [
      {
        id: "FW_legacy",
        type: "pyflw.blocks.file_writer.FileWriter",
        params: {
          n_inputs: 1,
          labels: null,
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

afterEach(() => cleanup());

describe("ParameterPanel: SPEC-0016 v0.39.1 params merge with registry", () => {
  it("renders new params (path / format) for legacy FileWriter model", async () => {
    useAppStore.setState({
      editingModel: makeLegacyFileWriterModel(),
      editingPath: [],
      selectedNodeId: "FW_legacy",
    });
    renderPanel();

    // registry payload を await (react-query で fetch される想定)
    await waitFor(() => {
      expect(screen.queryByTestId("param-input-path")).toBeTruthy();
    });

    // path は string param なので input、空文字列 default
    const pathInput = screen.getByTestId("param-input-path") as HTMLInputElement;
    expect(pathInput.value).toBe("");

    // format は enum なので select、"auto" default
    const formatSelect = screen.getByTestId(
      "param-input-format",
    ) as HTMLSelectElement;
    expect(formatSelect.value).toBe("auto");
  });

  it("preserves existing n_inputs value (= block.params が registry default に上書きされない)", async () => {
    const model = makeLegacyFileWriterModel();
    model.blocks[0]!.params.n_inputs = 5;  // ユーザーが編集済の値
    useAppStore.setState({
      editingModel: model,
      editingPath: [],
      selectedNodeId: "FW_legacy",
    });
    renderPanel();

    await waitFor(() => {
      expect(screen.queryByTestId("param-input-n_inputs")).toBeTruthy();
    });

    const nInputs = screen.getByTestId(
      "param-input-n_inputs",
    ) as HTMLInputElement;
    expect(nInputs.value).toBe("5");  // registry default 1 ではなく block.params の 5
  });

  it("commit on new param adds the key to block.params", async () => {
    useAppStore.setState({
      editingModel: makeLegacyFileWriterModel(),
      editingPath: [],
      selectedNodeId: "FW_legacy",
    });
    renderPanel();

    await waitFor(() => {
      expect(screen.queryByTestId("param-input-path")).toBeTruthy();
    });

    const pathInput = screen.getByTestId("param-input-path") as HTMLInputElement;
    fireEvent.change(pathInput, { target: { value: "out.csv" } });
    fireEvent.blur(pathInput);

    const m = useAppStore.getState().editingModel!;
    const blk = m.blocks.find((b) => b.id === "FW_legacy")!;
    expect(blk.params.path).toBe("out.csv");
    // 既存の key は失われない
    expect(blk.params.n_inputs).toBe(1);
  });
});
