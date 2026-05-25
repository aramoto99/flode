// ADR-0057: branch_waypoint の store アクション (set/reset) と孤児掃除
// (connection / block 削除) の動作テスト。
//
// 手動分岐点は applyEditingModel 経由で書き込むため undo/redo・dirty・auto-save に
// 自動的に乗る。トポロジ (connections) を一切変えないこと、枝が 2 本未満になった
// グループの waypoint が同一履歴で drop されること (Q6) を検証する。

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  removeBlockFromEditing,
  removeConnectionFromEditing,
  resetBranchWaypoint,
  setBranchWaypoint,
  useAppStore,
} from "../src/store/appStore";
import type { BranchWaypointDict, FlwModel } from "../src/types/api";

function makeModel(waypoints?: BranchWaypointDict): FlwModel {
  const m: FlwModel = {
    schema_version: "0.8",
    metadata: { name: "test" },
    simulator: {
      t_end: 10,
      dt: 0.01,
      solver: "RK45",
      rtol: 1e-3,
      atol: 1e-6,
      dt_base: null,
    },
    blocks: [
      { id: "src", type: "pyflw.blocks.sources.Step", params: {} },
      { id: "g1", type: "pyflw.blocks.mathops.Gain", params: { k: 2 } },
      { id: "g2", type: "pyflw.blocks.mathops.Gain", params: { k: 3 } },
    ],
    connections: [
      { src: "src", src_idx: 0, dst: "g1", dst_idx: 0 },
      { src: "src", src_idx: 0, dst: "g2", dst_idx: 0 },
    ],
    layout: {},
  };
  if (waypoints) m.branch_waypoints = waypoints;
  return m;
}

beforeEach(() => {
  useAppStore.setState({
    editingModel: makeModel(),
    editingPath: [],
    history: { past: [], future: [] },
    lastMergeKey: null,
    dirty: false,
  });
});

afterEach(() => {
  useAppStore.setState({
    editingModel: null,
    editingPath: [],
    history: { past: [], future: [] },
    lastMergeKey: null,
  });
});

describe("setBranchWaypoint", () => {
  it("creates a top-level waypoint and sets dirty + history", () => {
    setBranchWaypoint("src:0", { axis: "x", pos: 200 });
    const s = useAppStore.getState();
    expect(s.editingModel!.branch_waypoints).toEqual({
      "src:0": { axis: "x", pos: 200 },
    });
    expect(s.dirty).toBe(true);
    expect(s.history.past.length).toBe(1);
  });

  it("ignores NaN / Infinity coordinates (finite guard)", () => {
    const before = useAppStore.getState().editingModel;
    setBranchWaypoint("src:0", { axis: "x", pos: NaN });
    setBranchWaypoint("src:0", { axis: "x", pos: Infinity });
    const after = useAppStore.getState().editingModel;
    expect(after).toBe(before); // 一切書き込まれない (identity 不変)
    expect(useAppStore.getState().dirty).toBe(false);
  });

  it("does NOT change connections (topology invariance)", () => {
    const before = useAppStore.getState().editingModel!.connections;
    setBranchWaypoint("src:0", { axis: "x", pos: 1 });
    expect(useAppStore.getState().editingModel!.connections).toEqual(before);
  });

  it("collapses a drag (merge) into a single history entry", () => {
    setBranchWaypoint("src:0", { axis: "x", pos: 1 }, { merge: true });
    setBranchWaypoint("src:0", { axis: "x", pos: 2 }, { merge: true });
    setBranchWaypoint("src:0", { axis: "x", pos: 3 }, { merge: true });
    const s = useAppStore.getState();
    expect(s.history.past.length).toBe(1);
    expect(s.editingModel!.branch_waypoints).toEqual({ "src:0": { axis: "x", pos: 3 } });
  });

  it("writes into the subsystem scope when editingPath is set", () => {
    // Subsystem を 1 つ持つモデルに差し替え、その内部 scope で waypoint を設定
    const m: FlwModel = {
      schema_version: "0.8",
      simulator: makeModel().simulator,
      blocks: [
        {
          id: "sub1",
          type: "pyflw.subsystems.Subsystem",
          params: {
            n_inputs: 1,
            n_outputs: 1,
            blocks: [
              { id: "ip0", type: "pyflw.subsystems.Inport", params: { port_idx: 0 } },
              { id: "ga", type: "pyflw.blocks.mathops.Gain", params: { k: 1 } },
              { id: "gb", type: "pyflw.blocks.mathops.Gain", params: { k: 1 } },
            ],
            connections: [
              { src: "ip0", src_idx: 0, dst: "ga", dst_idx: 0 },
              { src: "ip0", src_idx: 0, dst: "gb", dst_idx: 0 },
            ],
          },
        },
      ],
      connections: [],
      layout: {},
    };
    useAppStore.setState({
      editingModel: m,
      editingPath: ["sub1"],
      history: { past: [], future: [] },
      lastMergeKey: null,
      dirty: false,
    });
    setBranchWaypoint("ip0:0", { axis: "x", pos: 120 });
    const subParams = useAppStore.getState().editingModel!.blocks[0]!
      .params as Record<string, unknown>;
    expect(subParams.branch_waypoints).toEqual({ "ip0:0": { axis: "x", pos: 120 } });
    // root scope は無影響
    expect(useAppStore.getState().editingModel!.branch_waypoints).toBeUndefined();
  });
});

describe("resetBranchWaypoint", () => {
  it("removes the manual waypoint (back to auto)", () => {
    useAppStore.setState({
      editingModel: makeModel({ "src:0": { axis: "x", pos: 9 } }),
      editingPath: [],
      history: { past: [], future: [] },
      lastMergeKey: null,
      dirty: false,
    });
    resetBranchWaypoint("src:0");
    expect(useAppStore.getState().editingModel!.branch_waypoints).toBeUndefined();
    expect(useAppStore.getState().dirty).toBe(true);
    expect(useAppStore.getState().history.past.length).toBe(1);
  });

  it("is a no-op when the key is absent (identity preserved)", () => {
    const before = useAppStore.getState().editingModel;
    resetBranchWaypoint("src:0");
    expect(useAppStore.getState().editingModel).toBe(before);
    expect(useAppStore.getState().dirty).toBe(false);
  });
});

describe("orphan cleanup on connection / block removal (ADR-0057 §(5))", () => {
  it("drops the waypoint when a 2-branch group falls to 1 (removeConnection)", () => {
    useAppStore.setState({
      editingModel: makeModel({ "src:0": { axis: "x", pos: 5 } }),
      editingPath: [],
      history: { past: [], future: [] },
      lastMergeKey: null,
      dirty: false,
    });
    removeConnectionFromEditing("src", 0, "g2", 0);
    const m = useAppStore.getState().editingModel!;
    expect(m.branch_waypoints).toBeUndefined();
    // connection 削除は 1 履歴 (孤児掃除も同一エントリ)
    expect(useAppStore.getState().history.past.length).toBe(1);
  });

  it("keeps the waypoint for a 3->2 branch group (still >= 2)", () => {
    const m = makeModel({ "src:0": { axis: "x", pos: 5 } });
    m.blocks.push({ id: "g3", type: "pyflw.blocks.mathops.Gain", params: { k: 4 } });
    m.connections.push({ src: "src", src_idx: 0, dst: "g3", dst_idx: 0 });
    useAppStore.setState({
      editingModel: m,
      editingPath: [],
      history: { past: [], future: [] },
      lastMergeKey: null,
      dirty: false,
    });
    removeConnectionFromEditing("src", 0, "g3", 0);
    expect(useAppStore.getState().editingModel!.branch_waypoints).toEqual({
      "src:0": { axis: "x", pos: 5 },
    });
  });

  it("drops the waypoint when removing a branch target block (removeBlock)", () => {
    useAppStore.setState({
      editingModel: makeModel({ "src:0": { axis: "x", pos: 5 } }),
      editingPath: [],
      history: { past: [], future: [] },
      lastMergeKey: null,
      dirty: false,
    });
    removeBlockFromEditing("g2"); // 残り src->g1 のみ → group < 2
    expect(useAppStore.getState().editingModel!.branch_waypoints).toBeUndefined();
  });
});
