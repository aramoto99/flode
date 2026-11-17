// ADR-0086 §5-C, SPEC-0037 P-1〜P-8 / 受け入れ条件 7: updateBlockParamsAndRemap。
// - 追加・削除・並べ替え・置き換え・テキスト編集がそれぞれ 1 回の Undo で引数・配線・分岐点ごと戻る
// - 直前の通常の引数編集 (params:<id> の合体キー) とは合体しない
// - 出力側は branch_waypoints のキーも移し、枝が 2 本未満になった分岐点は掃除する
// - remaps が空 (テキスト編集) なら番号で対応し、ポート数を超えた配線だけ落とす

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  BlockMetadata,
  BranchWaypointDict,
  ConnectionEntry,
  FlwModel,
  ResolvedPortShapes,
} from "../src/types/api";

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

import { remapDelete, remapSwap, remapAppend } from "../src/lib/paramRows";
import { indexRegistry } from "../src/lib/portShapeValidate";
import { _resetUserBlockPortsForTest, ensureUserBlockPorts } from "../src/lib/userBlockPorts";
import {
  updateBlockParams,
  updateBlockParamsAndRemap,
  useAppStore,
} from "../src/store/appStore";

const TYPE = "flode_ws.parts.Bin";

const META: BlockMetadata = {
  type_path: TYPE,
  display_name: "Bin",
  category: "",
  icon: "default",
  docstring_summary: "",
  params_spec: [
    { name: "parts", type: "list[str]", has_default: true, default: [], description: "", row_editor: true },
    { name: "outs", type: "list[str]", has_default: true, default: [], description: "", row_editor: true },
  ],
  default_n_inputs: 0,
  default_n_outputs: 0,
  port_shapes_in_default: [],
  port_shapes_out_default: [],
  tags: [],
  is_container: false,
  mask_capable: false,
  source: "workspace",
  input_names: [],
  output_names: [],
  dynamic_ports: true,
};
const REGISTRY = indexRegistry([META]);

/** parts の行数 = 入力ポート数、outs の行数 = 出力ポート数。 */
function ports(params: Record<string, unknown>): ResolvedPortShapes {
  const n = (k: string): number => (Array.isArray(params[k]) ? (params[k] as unknown[]).length : 0);
  return {
    n_inputs: n("parts"),
    n_outputs: n("outs"),
    port_shapes_in: Array.from({ length: n("parts") }, () => []),
    port_shapes_out: Array.from({ length: n("outs") }, () => []),
    input_names: [],
    output_names: [],
  } as unknown as ResolvedPortShapes;
}

const PARTS = ["a", "b", "c"];
const OUTS = ["x", "y", "z"];

function makeModel(waypoints?: BranchWaypointDict): FlwModel {
  const connections: ConnectionEntry[] = [
    { src: "s0", src_idx: 0, dst: "B", dst_idx: 0 },
    { src: "s1", src_idx: 0, dst: "B", dst_idx: 1 },
    { src: "s2", src_idx: 0, dst: "B", dst_idx: 2 },
    { src: "B", src_idx: 1, dst: "k1", dst_idx: 0 },
    { src: "B", src_idx: 1, dst: "k2", dst_idx: 0 },
    { src: "B", src_idx: 2, dst: "k3", dst_idx: 0 },
    { src: "B", src_idx: 2, dst: "k4", dst_idx: 0 },
  ];
  const m: FlwModel = {
    schema_version: "0.15",
    simulator: { t_end: 1, dt: 0.01, solver: "RK45", rtol: 1e-3, atol: 1e-6, dt_base: null },
    blocks: [
      { id: "B", type: TYPE, params: { parts: PARTS, outs: OUTS } },
      ...["s0", "s1", "s2", "k1", "k2", "k3", "k4"].map((id) => ({
        id,
        type: "flode.blocks.mathops.Gain",
        params: { k: 1 },
      })),
    ],
    connections,
    layout: {},
  };
  if (waypoints) m.branch_waypoints = waypoints;
  return m;
}

/** ParameterPanel と同じく、確定前に新しい引数のポートを解決しておく。 */
async function apply(
  params: Record<string, unknown>,
  remaps: Parameters<typeof updateBlockParamsAndRemap>[2],
): Promise<void> {
  await ensureUserBlockPorts([{ type_path: TYPE, params }]);
  updateBlockParamsAndRemap("B", params, remaps, REGISTRY);
}

function state(): { params: Record<string, unknown>; conns: string[]; wp: BranchWaypointDict } {
  const m = useAppStore.getState().editingModel!;
  return {
    params: m.blocks.find((b) => b.id === "B")!.params,
    conns: m.connections.map((c) => `${c.src}:${c.src_idx}->${c.dst}:${c.dst_idx}`).sort(),
    wp: m.branch_waypoints ?? {},
  };
}

beforeEach(async () => {
  _resetUserBlockPortsForTest();
  resolveMock.mockReset();
  resolveMock.mockImplementation(async (_t, params) => ports(params));
  // 描画済みのブロックと同じく、今の引数のポートも解決済みにしておく (剪定の「前」の数)
  await ensureUserBlockPorts([{ type_path: TYPE, params: { parts: PARTS, outs: OUTS } }]);
  useAppStore.setState({
    editingModel: makeModel({
      "B:1": { axis: "x", pos: 1 },
      "B:2": { axis: "x", pos: 2 },
    }),
    editingPath: [],
    history: { past: [], future: [] },
    lastMergeKey: null,
    dirty: false,
  });
});

afterEach(() => {
  useAppStore.setState({ editingModel: null, history: { past: [], future: [] }, lastMergeKey: null });
});

describe("updateBlockParamsAndRemap", () => {
  it("deleting a wired middle input row keeps later wires on their rows; one undo restores all", async () => {
    const before = state();
    await apply({ parts: ["a", "c"], outs: OUTS }, [{ side: "input", map: remapDelete(3, 1) }]);
    const after = state();
    expect(after.params.parts).toEqual(["a", "c"]);
    expect(after.conns).toContain("s0:0->B:0");
    expect(after.conns).toContain("s2:0->B:1");
    expect(after.conns.some((c) => c.startsWith("s1:"))).toBe(false);
    expect(useAppStore.getState().history.past).toHaveLength(1);

    useAppStore.getState().undo();
    expect(state()).toEqual(before);
  });

  it("output swap moves wires and branch waypoint keys together", async () => {
    await apply({ parts: PARTS, outs: ["x", "z", "y"] }, [{ side: "output", map: remapSwap(3, 1, 2) }]);
    const s = state();
    expect(s.conns).toContain("B:2->k1:0");
    expect(s.conns).toContain("B:1->k3:0");
    expect(s.wp).toEqual({ "B:2": { axis: "x", pos: 1 }, "B:1": { axis: "x", pos: 2 } });
    useAppStore.getState().undo();
    expect(state().wp).toEqual({ "B:1": { axis: "x", pos: 1 }, "B:2": { axis: "x", pos: 2 } });
  });

  it("deleting an output row drops its wires and its waypoint", async () => {
    await apply({ parts: PARTS, outs: ["x", "z"] }, [{ side: "output", map: remapDelete(3, 1) }]);
    const s = state();
    expect(s.conns.filter((c) => c.startsWith("B:"))).toEqual(["B:1->k3:0", "B:1->k4:0"]);
    expect(s.wp).toEqual({ "B:1": { axis: "x", pos: 2 } });
  });

  it("append leaves wires as they are and adds one undo step", async () => {
    const before = state();
    await apply({ parts: [...PARTS, "d"], outs: OUTS }, [{ side: "input", map: remapAppend(3) }]);
    expect(state().conns).toEqual(before.conns);
    expect(useAppStore.getState().history.past).toHaveLength(1);
    useAppStore.getState().undo();
    expect(state()).toEqual(before);
  });

  it("text edit (no remaps) keeps numbering and prunes wires beyond the new port count", async () => {
    await apply({ parts: ["q"], outs: OUTS }, []);
    const s = state();
    expect(s.conns.filter((c) => c.includes("->B:"))).toEqual(["s0:0->B:0"]);
  });

  it("does not merge with a preceding regular param edit", async () => {
    updateBlockParams("B", { parts: PARTS, outs: OUTS, extra: 1 }, REGISTRY);
    expect(useAppStore.getState().lastMergeKey).toBe("params:B");
    await apply({ parts: ["a", "b"], outs: OUTS, extra: 1 }, [{ side: "input", map: remapDelete(3, 2) }]);
    expect(useAppStore.getState().history.past).toHaveLength(2);
    expect(useAppStore.getState().lastMergeKey).toBeNull();
    // 直後の通常編集も別履歴
    updateBlockParams("B", { parts: ["a", "b"], outs: OUTS, extra: 2 }, REGISTRY);
    expect(useAppStore.getState().history.past).toHaveLength(3);
  });

  it("is a no-op (no history) when the block is gone", () => {
    updateBlockParamsAndRemap("nope", { parts: [] }, [], REGISTRY);
    expect(useAppStore.getState().history.past).toHaveLength(0);
  });

  it("works inside a Subsystem scope", async () => {
    const inner = makeModel({ "B:1": { axis: "y", pos: 5 }, "B:2": { axis: "y", pos: 6 } });
    useAppStore.setState({
      editingModel: {
        ...makeModel(),
        blocks: [
          {
            id: "S",
            type: "flode.subsystems.Subsystem",
            params: {
              blocks: inner.blocks,
              connections: inner.connections,
              branch_waypoints: inner.branch_waypoints,
            },
          },
        ],
        connections: [],
      },
      editingPath: ["S"],
    });
    await ensureUserBlockPorts([{ type_path: TYPE, params: { parts: PARTS, outs: ["y", "z"] } }]);
    updateBlockParamsAndRemap("B", { parts: PARTS, outs: ["y", "z"] }, [
      { side: "output", map: remapDelete(3, 0) },
    ], REGISTRY);
    const sub = useAppStore.getState().editingModel!.blocks[0]!.params as Record<string, unknown>;
    const conns = (sub.connections as ConnectionEntry[]).filter((c) => c.src === "B");
    expect(conns.map((c) => c.src_idx).sort()).toEqual([0, 0, 1, 1]);
    expect(sub.branch_waypoints).toEqual({ "B:0": { axis: "y", pos: 5 }, "B:1": { axis: "y", pos: 6 } });
  });
});
