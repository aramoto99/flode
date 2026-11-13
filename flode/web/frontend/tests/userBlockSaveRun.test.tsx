// ADR-0081 §論点 3 / §4-B (U5): 保存・実行要求の組み立てと実行前チェック。
// - 消えた引数は保存時と実行時に同じ関数で除去 (画面上のモデルも、undo には積まない)
// - プレースホルダ・超過ポートの配線があれば実行要求を送らずログタブに理由を出す
// - backend の 400 unknown_block_type も同じ表示になる
// - ユーザーブロックはパラメータ編集で配線を剪定しない (組み込みは従来どおり)

import i18n from "../src/i18n";

import { QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import * as client from "../src/api/client";
import * as filesApi from "../src/api/filesApi";
import { ErrorView } from "../src/components/ErrorView";
import { prepareModelForBackend } from "../src/lib/modelForBackend";
import { indexRegistry } from "../src/lib/portShapeValidate";
import { queryClient } from "../src/lib/queryClient";
import { BLOCKS_REGISTRY_QUERY_KEY } from "../src/lib/queryKeys";
import { useAutoSave } from "../src/lib/useAutoSave";
import { useSimulation } from "../src/lib/useSimulation";
import { runPrecheckFailure } from "../src/lib/userBlockModel";
import { updateBlockParams, useAppStore } from "../src/store/appStore";
import type { BlockMetadata, FailurePayload, FlwModel } from "../src/types/api";

vi.mock("../src/api/filesApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/filesApi")>();
  return {
    ...actual,
    putFileContent: vi.fn(async () => ({ path: "m.flw.json", mtime: 1, etag: "e1" })),
  };
});
vi.mock("../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/client")>();
  return {
    ...actual,
    startSimulationByPath: vi.fn(async () => ({ simulation_id: "sim-1" })),
  };
});
vi.mock("../src/api/stream", () => ({
  streamSimulation: vi.fn(() => ({ close: vi.fn() })),
}));

const putFileContent = vi.mocked(filesApi.putFileContent);
const startSimulationByPath = vi.mocked(client.startSimulationByPath);

const USER_TYPE = "flode_ws.filters.Trim";
const SUM_TYPE = "flode.blocks.mathops.Sum";
const GAIN_TYPE = "flode.blocks.mathops.Gain";
const GONE_TYPE = "flode_ws.filters.Gone";

function meta(over: Partial<BlockMetadata>): BlockMetadata {
  return {
    type_path: GAIN_TYPE,
    display_name: "Gain",
    category: "math",
    icon: "default",
    docstring_summary: "",
    params_spec: [{ name: "k", type: "float", has_default: true, default: 1, description: "" }],
    default_n_inputs: 1,
    default_n_outputs: 1,
    port_shapes_in_default: [[]],
    port_shapes_out_default: [[]],
    tags: [],
    is_container: false,
    mask_capable: false,
    source: "builtin",
    ...over,
  };
}

const USER_META = meta({ type_path: USER_TYPE, display_name: "Trim", source: "workspace" });
const SUM_META = meta({
  type_path: SUM_TYPE,
  display_name: "Sum",
  default_n_inputs: 2,
  params_spec: [{ name: "signs", type: "str", has_default: true, default: "++", description: "" }],
});
const BLOCKS = [USER_META, SUM_META, meta({})];

function model(
  blocks: FlwModel["blocks"],
  connections: FlwModel["connections"] = [],
): FlwModel {
  return {
    schema_version: "0.15",
    simulator: { t_end: 1, dt: 0.01, solver: "RK45", rtol: 1e-3, atol: 1e-6, dt_base: null },
    blocks,
    connections,
    layout: {},
  };
}

function openModel(m: FlwModel): void {
  useAppStore.setState({
    editingModel: m,
    editingPath: [],
    selectedFilePath: "m.flw.json",
    editingFileEtag: "e0",
    dirty: false,
    history: { past: [], future: [] },
    lastFailure: null,
    lastFailureSource: null,
    activeErrorTab: false,
    status: "idle",
  });
}

const withRemovedParam = (): FlwModel =>
  model(
    [
      { id: "g", type: GAIN_TYPE, params: { k: 2 } },
      { id: "t", type: USER_TYPE, params: { k: 3, bias: 1 } },
    ],
    [{ src: "g", src_idx: 0, dst: "t", dst_idx: 0 }],
  );

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

beforeEach(() => {
  queryClient.setQueryData(BLOCKS_REGISTRY_QUERY_KEY, {
    schema_version: "blocks.v3",
    blocks: BLOCKS,
  });
  putFileContent.mockClear();
  startSimulationByPath.mockClear();
});

afterEach(() => {
  cleanup();
  queryClient.removeQueries({ queryKey: BLOCKS_REGISTRY_QUERY_KEY });
});

describe("removed parameters on save and run", () => {
  it("run removes them from the request and from the model on screen (no undo entry)", async () => {
    openModel(withRemovedParam());
    const { result } = renderHook(() => useSimulation());
    await act(async () => {
      await result.current.run();
    });
    expect(putFileContent).toHaveBeenCalledTimes(1);
    const sent = putFileContent.mock.calls[0]![1];
    expect(sent.blocks[1]!.params).toEqual({ k: 3 });
    expect(sent.blocks[0]!.params).toEqual({ k: 2 }); // 組み込みは不変
    expect(startSimulationByPath).toHaveBeenCalledTimes(1);
    const state = useAppStore.getState();
    expect(state.editingModel!.blocks[1]!.params).toEqual({ k: 3 });
    expect(state.history.past).toHaveLength(0);
  });

  it("save (Ctrl+S auto-save flush) uses the same removal", async () => {
    openModel(withRemovedParam());
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    renderHook(() => useAutoSave(), { wrapper });
    await act(async () => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "s", ctrlKey: true }));
      await Promise.resolve();
    });
    expect(putFileContent).toHaveBeenCalledTimes(1);
    expect(putFileContent.mock.calls[0]![1].blocks[1]!.params).toEqual({ k: 3 });
    expect(useAppStore.getState().editingModel!.blocks[1]!.params).toEqual({ k: 3 });
  });

  it("returns the same model and leaves the screen alone when nothing is removed", () => {
    const m = model([{ id: "t", type: USER_TYPE, params: { k: 3 } }]);
    openModel(m);
    expect(prepareModelForBackend(m)).toBe(m);
    expect(useAppStore.getState().editingModel).toBe(m);
  });

  it("keeps placeholders untouched on save", () => {
    const m = model([{ id: "p", type: GONE_TYPE, params: { anything: 1 } }]);
    openModel(m);
    expect(prepareModelForBackend(m)).toBe(m);
  });
});

describe("pre-run check", () => {
  it("stops a model with placeholders and shows them in the log tab", async () => {
    openModel(
      model(
        [
          { id: "g", type: GAIN_TYPE, params: {} },
          { id: "p", type: GONE_TYPE, params: {} },
        ],
        [{ src: "g", src_idx: 0, dst: "p", dst_idx: 0 }],
      ),
    );
    const { result } = renderHook(() => useSimulation());
    await act(async () => {
      await result.current.run();
    });
    expect(putFileContent).not.toHaveBeenCalled();
    expect(startSimulationByPath).not.toHaveBeenCalled();
    const state = useAppStore.getState();
    expect(state.lastFailure?.template_key).toBe("error.unknown_block_type");
    expect(state.lastFailure?.template_args.types).toEqual([GONE_TYPE]);
    expect(state.activeErrorTab).toBe(true);
    render(<ErrorView />);
    expect(screen.getByRole("alert").textContent).toContain(
      `The model uses block types that are not loaded: ${GONE_TYPE}`,
    );
  });

  it("stops a model with wires beyond the user block ports", async () => {
    openModel(
      model(
        [
          { id: "g", type: GAIN_TYPE, params: {} },
          { id: "t", type: USER_TYPE, params: {} },
        ],
        [{ src: "g", src_idx: 0, dst: "t", dst_idx: 1 }],
      ),
    );
    const { result } = renderHook(() => useSimulation());
    await act(async () => {
      await result.current.run();
    });
    expect(putFileContent).not.toHaveBeenCalled();
    expect(useAppStore.getState().lastFailure?.template_key).toBe(
      "error.excess_port_connections",
    );
    render(<ErrorView />);
    expect(screen.getByRole("alert").textContent).toContain("t.in[1]");
  });

  it("shows the backend 400 unknown_block_type the same way", async () => {
    const m = model([{ id: "p", type: GONE_TYPE, params: {} }]);
    const precheck = runPrecheckFailure(m, indexRegistry(BLOCKS))!;
    // backend (権威) は registry が古いと判定が食い違うことがあるので、frontend の
    // チェックを通った後の 400 を想定する (registry 未取得)
    queryClient.removeQueries({ queryKey: BLOCKS_REGISTRY_QUERY_KEY });
    openModel(m);
    const backendPayload: FailurePayload = {
      ...precheck,
      template_args: { ...precheck.template_args, message: "server" },
      raw_message: "server",
    };
    startSimulationByPath.mockRejectedValueOnce(
      new client.ApiError(400, "Bad Request", backendPayload, backendPayload),
    );
    const { result } = renderHook(() => useSimulation());
    await act(async () => {
      await result.current.run();
    });
    expect(useAppStore.getState().lastFailure).toEqual(backendPayload);
    const fromBackend = render(<ErrorView />).getByRole("alert").textContent;
    cleanup();
    useAppStore.getState().setLastFailure(precheck, "start");
    const fromPrecheck = render(<ErrorView />).getByRole("alert").textContent;
    expect(fromBackend).toBe(fromPrecheck);
  });
});

describe("pruning wires on parameter edits", () => {
  it("does not prune wires of a user block", () => {
    openModel(
      model(
        [
          { id: "g", type: GAIN_TYPE, params: {} },
          { id: "t", type: USER_TYPE, params: { k: 1 } },
        ],
        [
          { src: "g", src_idx: 0, dst: "t", dst_idx: 0 },
          { src: "g", src_idx: 0, dst: "t", dst_idx: 1 },
        ],
      ),
    );
    updateBlockParams("t", { k: 5 }, indexRegistry(BLOCKS));
    const m = useAppStore.getState().editingModel!;
    expect(m.connections).toHaveLength(2);
    expect(m.blocks[1]!.params).toEqual({ k: 5 });
  });

  it("still prunes builtin blocks whose ports shrink", () => {
    openModel(
      model(
        [
          { id: "g", type: GAIN_TYPE, params: {} },
          { id: "s", type: SUM_TYPE, params: { signs: "+++" } },
        ],
        [
          { src: "g", src_idx: 0, dst: "s", dst_idx: 0 },
          { src: "g", src_idx: 0, dst: "s", dst_idx: 2 },
        ],
      ),
    );
    updateBlockParams("s", { signs: "++" }, indexRegistry(BLOCKS));
    expect(useAppStore.getState().editingModel!.connections).toHaveLength(1);
  });
});
