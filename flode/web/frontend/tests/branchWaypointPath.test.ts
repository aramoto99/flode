// ADR-0057: branch_waypoint の scope-aware 永続化 (root / Subsystem) と孤児掃除の
// 単体テスト。
//
// backend は opaque round-trip (Python 無改修) のため、frontend の
// resolve/applyBranchWaypointsAtPath が root の top-level / Subsystem の
// params.branch_waypoints を正しく読み書きし、未知キーを失わないことが要。
// ADR-0057 Open Question #1 (Subsystem round-trip 喪失) をここで検証する。

import { describe, expect, it } from "vitest";

import {
  applyBranchWaypointsAtPath,
  pruneBranchWaypoints,
  resolveBranchWaypointsAtPath,
} from "../src/lib/pathResolver";
import type { BlockEntry, BranchWaypointDict, FlwModel } from "../src/types/api";

function baseModel(): FlwModel {
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
}

/** params.branch_waypoints を持つ Subsystem を 1 つ含むモデル。 */
function subsystemModel(): FlwModel {
  const sub: BlockEntry = {
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
      layout: { ip0: { x: 40, y: 80 } },
      // 既存の opaque カスタムキー (= round-trip で失われないことを確認する番兵)
      mask: { foo: 1 },
    },
  };
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
    blocks: [{ id: "in", type: "pyflw.blocks.sources.Step", params: {} }, sub],
    connections: [{ src: "in", src_idx: 0, dst: "sub1", dst_idx: 0 }],
    layout: {},
  };
}

describe("resolveBranchWaypointsAtPath", () => {
  it("returns empty dict when absent (backward compat)", () => {
    expect(resolveBranchWaypointsAtPath(baseModel(), [])).toEqual({});
  });

  it("reads top-level branch_waypoints at root scope", () => {
    const m = baseModel();
    m.branch_waypoints = { "src:0": { axis: "x", pos: 200 } };
    expect(resolveBranchWaypointsAtPath(m, [])).toEqual({
      "src:0": { axis: "x", pos: 200 },
    });
  });

  it("reads params.branch_waypoints inside a subsystem scope", () => {
    const m = subsystemModel();
    (m.blocks[1]!.params as Record<string, unknown>).branch_waypoints = {
      "ip0:0": { axis: "x", pos: 120 },
    };
    expect(resolveBranchWaypointsAtPath(m, ["sub1"])).toEqual({
      "ip0:0": { axis: "x", pos: 120 },
    });
  });
});

describe("applyBranchWaypointsAtPath (root scope)", () => {
  it("writes a top-level waypoint and round-trips", () => {
    const m = baseModel();
    const next = applyBranchWaypointsAtPath(m, [], (wp) => ({
      ...wp,
      "src:0": { axis: "x", pos: 200 },
    }));
    expect(next.branch_waypoints).toEqual({ "src:0": { axis: "x", pos: 200 } });
    // round-trip
    expect(resolveBranchWaypointsAtPath(next, [])).toEqual({
      "src:0": { axis: "x", pos: 200 },
    });
    // 原本不変 (immutable)
    expect(m.branch_waypoints).toBeUndefined();
  });

  it("drops the key entirely when the dict becomes empty", () => {
    const m = baseModel();
    m.branch_waypoints = { "src:0": { axis: "x", pos: 1 } };
    const next = applyBranchWaypointsAtPath(m, [], () => ({}));
    expect("branch_waypoints" in next).toBe(false);
  });

  it("does not touch connections (topology invariance)", () => {
    const m = baseModel();
    const next = applyBranchWaypointsAtPath(m, [], (wp) => ({
      ...wp,
      "src:0": { axis: "x", pos: 9 },
    }));
    expect(next.connections).toEqual(m.connections);
  });
});

describe("applyBranchWaypointsAtPath (subsystem scope, Open Question #1)", () => {
  it("writes params.branch_waypoints without losing other params keys", () => {
    const m = subsystemModel();
    const next = applyBranchWaypointsAtPath(m, ["sub1"], (wp) => ({
      ...wp,
      "ip0:0": { axis: "x", pos: 120 },
    }));
    const subParams = next.blocks[1]!.params as Record<string, unknown>;
    expect(subParams.branch_waypoints).toEqual({ "ip0:0": { axis: "x", pos: 120 } });
    // 既存の blocks / connections / layout / mask (opaque) が保持される
    expect(subParams.mask).toEqual({ foo: 1 });
    expect((subParams.layout as Record<string, unknown>).ip0).toEqual({
      x: 40,
      y: 80,
    });
    expect(Array.isArray(subParams.connections)).toBe(true);
    // round-trip
    expect(resolveBranchWaypointsAtPath(next, ["sub1"])).toEqual({
      "ip0:0": { axis: "x", pos: 120 },
    });
  });

  it("drops params.branch_waypoints key when emptied", () => {
    const m = subsystemModel();
    (m.blocks[1]!.params as Record<string, unknown>).branch_waypoints = {
      "ip0:0": { axis: "x", pos: 1 },
    };
    const next = applyBranchWaypointsAtPath(m, ["sub1"], () => ({}));
    const subParams = next.blocks[1]!.params as Record<string, unknown>;
    expect("branch_waypoints" in subParams).toBe(false);
    // root scope は無影響
    expect(next.branch_waypoints).toBeUndefined();
  });
});

describe("pruneBranchWaypoints", () => {
  it("keeps keys whose group has >= 2 branches", () => {
    const conns = [
      { src: "src", src_idx: 0, dst: "g1", dst_idx: 0 },
      { src: "src", src_idx: 0, dst: "g2", dst_idx: 0 },
    ];
    const wp: BranchWaypointDict = { "src:0": { axis: "x", pos: 1 } };
    expect(pruneBranchWaypoints(conns, wp)).toEqual(wp);
  });

  it("drops keys whose group dropped below 2 branches (orphan)", () => {
    const conns = [{ src: "src", src_idx: 0, dst: "g1", dst_idx: 0 }];
    const wp: BranchWaypointDict = { "src:0": { axis: "x", pos: 1 } };
    expect(pruneBranchWaypoints(conns, wp)).toEqual({});
  });

  it("keeps a 2->3 branch group (key unchanged)", () => {
    const conns = [
      { src: "src", src_idx: 0, dst: "g1", dst_idx: 0 },
      { src: "src", src_idx: 0, dst: "g2", dst_idx: 0 },
      { src: "src", src_idx: 0, dst: "g3", dst_idx: 0 },
    ];
    const wp: BranchWaypointDict = { "src:0": { axis: "x", pos: 5 } };
    expect(pruneBranchWaypoints(conns, wp)).toEqual(wp);
  });

  it("distinguishes source handle index in the key", () => {
    const conns = [
      { src: "src", src_idx: 0, dst: "g1", dst_idx: 0 },
      { src: "src", src_idx: 0, dst: "g2", dst_idx: 0 },
      { src: "src", src_idx: 1, dst: "g3", dst_idx: 0 },
    ];
    // src:1 は 1 本のみ → drop。src:0 は残す。
    const wp: BranchWaypointDict = { "src:0": { axis: "x", pos: 1 }, "src:1": { axis: "x", pos: 2 } };
    expect(pruneBranchWaypoints(conns, wp)).toEqual({ "src:0": { axis: "x", pos: 1 } });
  });
});
