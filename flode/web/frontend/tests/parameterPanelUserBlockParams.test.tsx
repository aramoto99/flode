// ユーザーブロックの Inspector: 型ラベルに応じた編集と、ポートが引数で変わるブロックの確定。
// - list[str] 等の引数は既定値が空リストでも文字列の配列として編集する
// - int の引数は名前に関係なく整数として検証する (組み込みは従来の名前ベースのまま)
// - dynamic_ports のブロックは編集後の引数のポートを解決してから確定し、減ったポートの配線を剪定する

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BlockMetadata, FlwModel, ResolvedPortShapes } from "../src/types/api";

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

const USER_TYPE = "flode_ws.io.Labels";
const DYN_TYPE = "flode_ws.io.Split";

const USER_META: BlockMetadata = {
  type_path: USER_TYPE,
  display_name: "Labels",
  category: "",
  icon: "default",
  docstring_summary: "",
  params_spec: [
    { name: "names", type: "list[str]", has_default: true, default: [], description: "" },
    { name: "count", type: "int", has_default: true, default: 2, description: "" },
    { name: "gain", type: "float", has_default: true, default: 1.5, description: "" },
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

const DYN_META: BlockMetadata = {
  ...USER_META,
  type_path: DYN_TYPE,
  display_name: "Split",
  params_spec: [{ name: "n", type: "int", has_default: true, default: 2, description: "" }],
  default_n_outputs: 2,
  port_shapes_out_default: [[], []],
  dynamic_ports: true,
};

function ports(n: number): ResolvedPortShapes {
  return {
    n_inputs: 1,
    n_outputs: n,
    port_shapes_in: [[]],
    port_shapes_out: Array.from({ length: n }, () => []),
    input_names: [],
    output_names: [],
  };
}

const resolveMock =
  vi.fn<(typePath: string, params: Record<string, unknown>) => Promise<ResolvedPortShapes>>();
vi.mock("../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/client")>();
  return {
    ...actual,
    listBlockMetadata: vi.fn(async () => ({
      schema_version: "blocks.v3",
      blocks: [USER_META, DYN_META],
    })),
    resolvePortShapes: (typePath: string, params: Record<string, unknown>) =>
      resolveMock(typePath, params),
  };
});

import { ParameterPanel } from "../src/components/ParameterPanel";
import {
  _resetUserBlockPortsForTest,
  ensureUserBlockPorts,
} from "../src/lib/userBlockPorts";
import { useAppStore } from "../src/store/appStore";

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

/** 描画して registry の到着 (= ユーザーブロックの見出し) まで待つ。 */
async function renderPanel(m: FlwModel): Promise<void> {
  useAppStore.setState({ editingModel: m, editingPath: [], selectedNodeId: "B1" });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ParameterPanel modelId="test" />
    </QueryClientProvider>,
  );
  await screen.findByTestId("block-header-user-summary");
}

function params(): Record<string, unknown> {
  return useAppStore.getState().editingModel!.blocks[0]!.params;
}

beforeEach(() => {
  _resetUserBlockPortsForTest();
  resolveMock.mockReset();
});
afterEach(() => cleanup());

describe("ParameterPanel: user block parameter types", () => {
  it("edits a list[str] parameter with an empty default as strings", async () => {
    await renderPanel(model(USER_TYPE, { names: [], count: 2, gain: 1.5 }));
    const editor = (await screen.findByTestId("param-input-names")) as HTMLTextAreaElement;
    expect(editor.getAttribute("placeholder")).toBe('["A", "B"]');

    fireEvent.change(editor, { target: { value: '["A", "B"]' } });
    fireEvent.blur(editor);

    expect(params().names).toEqual(["A", "B"]);
    expect(screen.queryByTestId("param-input-names-error")).toBeNull();
  });

  it("rejects numbers in a list[str] parameter", async () => {
    await renderPanel(model(USER_TYPE, { names: [], count: 2, gain: 1.5 }));
    const editor = await screen.findByTestId("param-input-names");

    fireEvent.change(editor, { target: { value: "[1, 2]" } });
    fireEvent.blur(editor);

    expect(screen.getByTestId("param-input-names-error").textContent).toContain(
      '"expected":"string"',
    );
    expect(params().names).toEqual([]);
  });

  it("validates an int parameter as an integer whatever its name", async () => {
    await renderPanel(model(USER_TYPE, { names: [], count: 2, gain: 1.5 }));
    const count = await screen.findByTestId("param-input-count");

    fireEvent.change(count, { target: { value: "2.5" } });
    expect(screen.getByRole("alert").textContent).toContain("inspector.invalid_integer");
    expect(params().count).toBe(2);

    fireEvent.change(count, { target: { value: "7" } });
    expect(params().count).toBe(7);
    expect(screen.queryByRole("alert")).toBeNull();

    // float の引数は小数をそのまま受ける
    fireEvent.change(screen.getByTestId("param-input-gain"), { target: { value: "0.25" } });
    expect(params().gain).toBe(0.25);
  });
});

describe("ParameterPanel: dynamic_ports user block", () => {
  it("commits after resolving the new ports and prunes wires beyond them", async () => {
    resolveMock.mockImplementation(async (_t, p) => ports(Number(p.n)));
    await ensureUserBlockPorts([{ type_path: DYN_TYPE, params: { n: 2 } }]);
    await renderPanel(
      model(DYN_TYPE, { n: 2 }, [
        { src: "B1", src_idx: 0, dst: "X", dst_idx: 0 },
        { src: "B1", src_idx: 1, dst: "Y", dst_idx: 0 },
      ]),
    );
    const input = await screen.findByTestId("param-input-n");

    await act(async () => {
      fireEvent.change(input, { target: { value: "1" } });
    });

    await waitFor(() => expect(params().n).toBe(1));
    expect(resolveMock).toHaveBeenCalledWith(DYN_TYPE, { n: 1 });
    expect(useAppStore.getState().editingModel!.connections).toEqual([
      { src: "B1", src_idx: 0, dst: "X", dst_idx: 0 },
    ]);
  });

  it("keeps only the last of several edits made while waiting", async () => {
    const pending: Array<() => void> = [];
    resolveMock.mockImplementation(
      (_t, p) =>
        new Promise((resolve) => {
          pending.push(() => resolve(ports(Number(p.n))));
        }),
    );
    await renderPanel(model(DYN_TYPE, { n: 2 }));
    const input = await screen.findByTestId("param-input-n");

    fireEvent.change(input, { target: { value: "3" } });
    fireEvent.change(input, { target: { value: "4" } });
    expect(params().n).toBe(2); // 応答待ち

    await act(async () => {
      for (const done of pending) done();
    });

    await waitFor(() => expect(params().n).toBe(4));
  });

  it("warns about wires beyond the resolved ports", async () => {
    resolveMock.mockResolvedValue(ports(1));
    await ensureUserBlockPorts([{ type_path: DYN_TYPE, params: { n: 1 } }]);
    await renderPanel(model(DYN_TYPE, { n: 1 }, [{ src: "B1", src_idx: 1, dst: "Y", dst_idx: 0 }]));

    const hint = await screen.findByTestId("param-excess-ports");
    expect(hint.textContent).toContain("out[1]");
  });
});
