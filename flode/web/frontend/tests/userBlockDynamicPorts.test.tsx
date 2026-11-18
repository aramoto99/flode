// ポートが引数で変わるユーザーブロック (registry の dynamic_ports、block_dynamic_ports = True)。
// - 引数ごとのポートをサーバ (resolve-port-shapes) に問い合わせ、type_path + 安定 JSON で覚える
// - 未解決の間は registry の既定値、解決後はポート数・shape・ポート名・超過ポート・剪定に使う
// - dynamic_ports でないユーザーブロックは従来どおり (問い合わせない・剪定しない)

import { ReactFlowProvider } from "@xyflow/react";
import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BlockMetadata, FlwModel, ResolvedPortShapes } from "../src/types/api";

const resolveMock =
  vi.fn<(typePath: string, params: Record<string, unknown>) => Promise<ResolvedPortShapes>>();
vi.mock("../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/client")>();
  return {
    ...actual,
    resolvePortShapes: (typePath: string, params: Record<string, unknown>) =>
      resolveMock(typePath, params),
  };
});
vi.mock("../src/store/appStore", () => ({
  useAppStore: (
    selector: (s: { scopes: Record<string, never>; renameRequest: null }) => unknown,
  ) => selector({ scopes: {}, renameRequest: null }),
  updateBlockSize: vi.fn(),
  renameBlockInEditing: vi.fn(() => null),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

import { ApiError } from "../src/api/client";
import { BlockNodeView } from "../src/components/BlockNodeView";
import { modelToDiagram, type BlockNodeData } from "../src/lib/diagramConverter";
import { canPruneOnParamChange, resolvePortCounts } from "../src/lib/dynamicPorts";
import { getDefaultPortShapes, indexRegistry } from "../src/lib/portShapeValidate";
import { collectExcessPortConnections, runPrecheckFailure } from "../src/lib/userBlockModel";
import {
  _resetUserBlockPortsForTest,
  collectDynamicUserBlocks,
  ensureUserBlockPorts,
  getCachedUserBlockPorts,
  getUserBlockPortsVersion,
  subscribeUserBlockPorts,
  userBlockPortsKey,
} from "../src/lib/userBlockPorts";

const DYN_TYPE = "flode_ws.io.Split";
const FIXED_TYPE = "flode_ws.io.Fixed";
const SUBSYSTEM_TYPE = "flode.subsystems.Subsystem";

function meta(over: Partial<BlockMetadata>): BlockMetadata {
  return {
    type_path: FIXED_TYPE,
    display_name: "Fixed",
    category: "",
    icon: "default",
    docstring_summary: "",
    params_spec: [],
    default_n_inputs: 1,
    default_n_outputs: 2,
    port_shapes_in_default: [[]],
    port_shapes_out_default: [[], []],
    tags: [],
    is_container: false,
    mask_capable: false,
    source: "workspace",
    input_names: ["in"],
    output_names: ["a", "b"],
    ...over,
  };
}

const DYN_META = meta({ type_path: DYN_TYPE, display_name: "Split", dynamic_ports: true });
const FIXED_META = meta({});
const SUBSYSTEM_META = meta({
  type_path: SUBSYSTEM_TYPE,
  display_name: "Subsystem",
  source: "builtin",
  is_container: true,
  input_names: [],
  output_names: [],
});
const REGISTRY = indexRegistry([DYN_META, FIXED_META, SUBSYSTEM_META]);

const THREE: ResolvedPortShapes = {
  n_inputs: 1,
  n_outputs: 3,
  port_shapes_in: [[]],
  port_shapes_out: [[], [2], []],
  input_names: [],
  output_names: ["x", "y", "z"],
};
const ONE: ResolvedPortShapes = {
  n_inputs: 1,
  n_outputs: 1,
  port_shapes_in: [[]],
  port_shapes_out: [[]],
  input_names: [],
  output_names: ["only"],
};

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

function renderNode(id: string, data: BlockNodeData) {
  return render(
    <ReactFlowProvider>
      <BlockNodeView
        id={id}
        data={data}
        selected={false}
        type="blockNode"
        zIndex={0}
        isConnectable
        positionAbsoluteX={0}
        positionAbsoluteY={0}
        dragging={false}
        draggable
        selectable
        deletable
      />
    </ReactFlowProvider>,
  );
}

beforeEach(() => {
  _resetUserBlockPortsForTest();
  resolveMock.mockReset();
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("userBlockPorts cache", () => {
  it("keys by type and stable JSON of the params", () => {
    expect(userBlockPortsKey(DYN_TYPE, { a: 1, b: [1, { d: 2, c: 3 }] })).toBe(
      userBlockPortsKey(DYN_TYPE, { b: [1, { c: 3, d: 2 }], a: 1 }),
    );
    expect(userBlockPortsKey(DYN_TYPE, { a: 1 })).not.toBe(userBlockPortsKey(FIXED_TYPE, { a: 1 }));
  });

  it("dedupes concurrent requests and does not refetch cached params", async () => {
    resolveMock.mockResolvedValue(THREE);
    const listener = vi.fn();
    const unsubscribe = subscribeUserBlockPorts(listener);
    const before = getUserBlockPortsVersion();

    await Promise.all([
      ensureUserBlockPorts([{ type_path: DYN_TYPE, params: { n: 3 } }]),
      ensureUserBlockPorts([
        { type_path: DYN_TYPE, params: { n: 3 } },
        { type_path: DYN_TYPE, params: { n: 3 } },
      ]),
    ]);
    await ensureUserBlockPorts([{ type_path: DYN_TYPE, params: { n: 3 } }]);
    unsubscribe();

    expect(resolveMock).toHaveBeenCalledTimes(1);
    expect(resolveMock).toHaveBeenCalledWith(DYN_TYPE, { n: 3 });
    expect(getCachedUserBlockPorts(DYN_TYPE, { n: 3 })?.outputNames).toEqual(["x", "y", "z"]);
    expect(listener).toHaveBeenCalled();
    expect(getUserBlockPortsVersion()).toBeGreaterThan(before);
  });

  it("remembers rejected params (400) but retries after network failures", async () => {
    resolveMock.mockRejectedValueOnce(new ApiError(400, "400 bad", null, "bad"));
    await ensureUserBlockPorts([{ type_path: DYN_TYPE, params: { n: -1 } }]);
    await ensureUserBlockPorts([{ type_path: DYN_TYPE, params: { n: -1 } }]);
    expect(resolveMock).toHaveBeenCalledTimes(1);
    expect(getCachedUserBlockPorts(DYN_TYPE, { n: -1 })).toBeUndefined();
    // 拒否された引数は registry の既定値で描く
    expect(resolvePortCounts(DYN_TYPE, { n: -1 }, DYN_META)).toEqual({ nInputs: 1, nOutputs: 2 });

    resolveMock.mockRejectedValueOnce(new TypeError("network"));
    await ensureUserBlockPorts([{ type_path: DYN_TYPE, params: { n: 5 } }]);
    resolveMock.mockResolvedValueOnce(THREE);
    await ensureUserBlockPorts([{ type_path: DYN_TYPE, params: { n: 5 } }]);
    expect(resolveMock).toHaveBeenCalledTimes(3);
    expect(getCachedUserBlockPorts(DYN_TYPE, { n: 5 })?.nOutputs).toBe(3);
  });

  it("collects dynamic user blocks only, including inside subsystems", () => {
    const m = model([
      { id: "d", type: DYN_TYPE, params: { n: 3 } },
      { id: "f", type: FIXED_TYPE, params: {} },
      {
        id: "sub",
        type: SUBSYSTEM_TYPE,
        params: { blocks: [{ id: "inner", type: DYN_TYPE, params: { n: 1 } }], connections: [] },
      },
    ]);
    expect(collectDynamicUserBlocks(m, REGISTRY)).toEqual([
      { type_path: DYN_TYPE, params: { n: 3 } },
      { type_path: DYN_TYPE, params: { n: 1 } },
    ]);
    expect(collectDynamicUserBlocks(m, undefined)).toEqual([]);
  });
});

describe("ports of dynamic user blocks", () => {
  it("uses registry defaults until resolved, then the resolved counts and shapes", async () => {
    const block = { id: "d", type: DYN_TYPE, params: { n: 3 } };
    expect(resolvePortCounts(DYN_TYPE, block.params, DYN_META)).toEqual({ nInputs: 1, nOutputs: 2 });
    expect(getDefaultPortShapes(block, REGISTRY).out).toEqual([[], []]);

    resolveMock.mockResolvedValue(THREE);
    await ensureUserBlockPorts([{ type_path: DYN_TYPE, params: block.params }]);

    expect(resolvePortCounts(DYN_TYPE, block.params, DYN_META)).toEqual({ nInputs: 1, nOutputs: 3 });
    expect(getDefaultPortShapes(block, REGISTRY).out).toEqual([[], [2], []]);
  });

  it("draws the resolved port count and names on the canvas", async () => {
    const m = model([{ id: "d", type: DYN_TYPE, params: { n: 3 } }]);
    const before = modelToDiagram(m, REGISTRY).nodes[0]!;
    expect(before.data.nOutputs).toBe(2);
    expect(before.data.userBlock?.outputNames).toEqual(["a", "b"]);

    resolveMock.mockResolvedValue(THREE);
    await ensureUserBlockPorts([{ type_path: DYN_TYPE, params: { n: 3 } }]);
    const after = modelToDiagram(m, REGISTRY).nodes[0]!;

    expect(after.data.nOutputs).toBe(3);
    expect(after.data.userBlock?.declaredOutputs).toBe(3);
    const view = renderNode("d", after.data);
    expect(view.getByTestId("userblock-port-label-out-0").textContent).toBe("x");
    expect(view.getByTestId("userblock-port-label-out-2").textContent).toBe("z");
    expect(view.queryByTestId("userblock-port-label-in-0")).toBeNull(); // 解決後は無名
  });

  it("checks excess ports against the resolved counts", async () => {
    const m = model(
      [{ id: "d", type: DYN_TYPE, params: { n: 1 } }],
      [{ src: "d", src_idx: 1, dst: "X", dst_idx: 0 }],
    );
    expect(collectExcessPortConnections(m, REGISTRY)).toEqual([]);

    resolveMock.mockResolvedValue(ONE);
    await ensureUserBlockPorts([{ type_path: DYN_TYPE, params: { n: 1 } }]);

    expect(collectExcessPortConnections(m, REGISTRY)).toEqual([
      { blockId: "d", qualifiedId: "d", type: DYN_TYPE, direction: "out", portIndex: 1 },
    ]);
  });

  it("allows pruning on param change only when the next params are resolved", async () => {
    expect(canPruneOnParamChange(DYN_TYPE, { n: 1 }, REGISTRY)).toBe(false);
    resolveMock.mockResolvedValue(ONE);
    await ensureUserBlockPorts([{ type_path: DYN_TYPE, params: { n: 1 } }]);
    expect(canPruneOnParamChange(DYN_TYPE, { n: 1 }, REGISTRY)).toBe(true);
    expect(canPruneOnParamChange(DYN_TYPE, { n: 2 }, REGISTRY)).toBe(false);
  });
});

// bug-report 2026-11-19-run-precheck-unresolved-dynamic-ports: ファイルを開いた直後
// (resolve-port-shapes の応答前) に実行すると、registry の既定のポート数と比べて
// 「ブロックに無いポートへの配線」と誤って止めていた。未解決のポートは超過と断定しない。
describe("unresolved dynamic ports are not reported as excess", () => {
  // 既定は in 1 / out 2。in[1] と out[2] は既定では超過だが、引数で増えるかもしれない
  const wired = (params: Record<string, unknown>) =>
    model(
      [
        { id: "d", type: DYN_TYPE, params },
        { id: "f", type: FIXED_TYPE, params: {} },
      ],
      [
        { src: "f", src_idx: 0, dst: "d", dst_idx: 1 },
        { src: "d", src_idx: 2, dst: "f", dst_idx: 0 },
      ],
    );

  it("does not stop the run before the ports are resolved (request not answered yet)", () => {
    const m = wired({ n: 3 });
    expect(collectExcessPortConnections(m, REGISTRY)).toEqual([]);
    expect(runPrecheckFailure(m, REGISTRY)).toBeNull();
  });

  it("does not stop the run after a network failure (not cached, retried later)", async () => {
    resolveMock.mockRejectedValueOnce(new TypeError("network"));
    await ensureUserBlockPorts([{ type_path: DYN_TYPE, params: { n: 3 } }]);
    expect(runPrecheckFailure(wired({ n: 3 }), REGISTRY)).toBeNull();
  });

  it("still stops the run when the resolved ports really are fewer", async () => {
    resolveMock.mockResolvedValue(ONE);
    await ensureUserBlockPorts([{ type_path: DYN_TYPE, params: { n: 1 } }]);
    const failure = runPrecheckFailure(wired({ n: 1 }), REGISTRY);
    expect(failure?.category).toBe("excess_port_connections");
    expect(failure?.template_args.ports).toEqual(["d.in[1]", "d.out[2]"]);
  });

  it("rejected params (400) keep the registry defaults as before", async () => {
    resolveMock.mockRejectedValueOnce(new ApiError(400, "400 bad", null, "bad"));
    await ensureUserBlockPorts([{ type_path: DYN_TYPE, params: { n: -1 } }]);
    expect(collectExcessPortConnections(wired({ n: -1 }), REGISTRY)).toHaveLength(2);
  });

  it("static user blocks are checked against the registry as before", () => {
    const m = model(
      [{ id: "f", type: FIXED_TYPE, params: {} }],
      [{ src: "f", src_idx: 2, dst: "f", dst_idx: 1 }],
    );
    expect(collectExcessPortConnections(m, REGISTRY)).toEqual([
      { blockId: "f", qualifiedId: "f", type: FIXED_TYPE, direction: "in", portIndex: 1 },
      { blockId: "f", qualifiedId: "f", type: FIXED_TYPE, direction: "out", portIndex: 2 },
    ]);
  });

  it("does not draw the wires as excess (red) until resolved, then does", async () => {
    const m = wired({ n: 1 });
    const before = modelToDiagram(m, REGISTRY);
    expect(before.edges.filter((e) => e.data?.excessPort === true)).toEqual([]);
    expect(before.nodes.find((n) => n.id === "d")!.data.userBlock?.declaredOutputs).toBeNull();

    resolveMock.mockResolvedValue(ONE);
    await ensureUserBlockPorts([{ type_path: DYN_TYPE, params: { n: 1 } }]);
    const after = modelToDiagram(m, REGISTRY);
    expect(after.edges.filter((e) => e.data?.excessPort === true)).toHaveLength(2);
    expect(after.nodes.find((n) => n.id === "d")!.data.userBlock?.declaredOutputs).toBe(1);
  });
});

describe("user blocks without dynamic_ports", () => {
  it("keep registry ports and are never pruned", async () => {
    resolveMock.mockResolvedValue(ONE);
    await ensureUserBlockPorts([{ type_path: FIXED_TYPE, params: {} }]);
    // 問い合わせ結果があっても使わない (宣言していないブロックのポートは固定)
    expect(resolvePortCounts(FIXED_TYPE, {}, FIXED_META)).toEqual({ nInputs: 1, nOutputs: 2 });
    expect(canPruneOnParamChange(FIXED_TYPE, {}, REGISTRY)).toBe(false);
    const n = modelToDiagram(model([{ id: "f", type: FIXED_TYPE, params: {} }]), REGISTRY).nodes[0]!;
    expect(n.data.userBlock?.outputNames).toEqual(["a", "b"]);
  });
});
