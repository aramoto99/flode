// ADR-0056 follow-up: findBlockPath の DFS パス逆引きをテスト。

import { describe, expect, it } from "vitest";

import { findBlockPath, findBlockTypeById } from "../src/lib/findBlockPath";
import type { FlwModel } from "../src/types/api";

function _model(blocks: FlwModel["blocks"]): FlwModel {
  return {
    schema_version: "1.0",
    blocks,
    connections: [],
    config: { t_end: 1.0, dt: 0.01, solver: "RK45" },
  } as unknown as FlwModel;
}

describe("findBlockPath", () => {
  it("returns [] for a top-level block", () => {
    const m = _model([
      { id: "a", type: "flode.blocks.mathops.Gain", params: {} },
      { id: "b", type: "flode.blocks.sinks.Scope", params: {} },
    ]);
    expect(findBlockPath(m, "a")).toEqual([]);
    expect(findBlockPath(m, "b")).toEqual([]);
  });

  it("returns null for a missing block", () => {
    const m = _model([
      { id: "a", type: "flode.blocks.mathops.Gain", params: {} },
    ]);
    expect(findBlockPath(m, "zzz")).toBeNull();
  });

  it("returns [sub1] for a block one level deep", () => {
    const m = _model([
      {
        id: "sub1",
        type: "flode.subsystems.Subsystem",
        params: {
          blocks: [
            { id: "inner", type: "flode.blocks.mathops.Gain", params: {} },
          ],
        },
      },
    ]);
    expect(findBlockPath(m, "inner")).toEqual(["sub1"]);
    expect(findBlockPath(m, "sub1")).toEqual([]); // subsystem 自体は top-level
  });

  it("returns [sub1, sub2] for a block two levels deep", () => {
    const m = _model([
      {
        id: "sub1",
        type: "flode.subsystems.Subsystem",
        params: {
          blocks: [
            {
              id: "sub2",
              type: "flode.subsystems.Subsystem",
              params: {
                blocks: [
                  { id: "deep", type: "flode.blocks.sinks.Scope", params: {} },
                ],
              },
            },
          ],
        },
      },
    ]);
    expect(findBlockPath(m, "deep")).toEqual(["sub1", "sub2"]);
    expect(findBlockPath(m, "sub2")).toEqual(["sub1"]);
  });

  it("handles blocks with no params.blocks (= non-subsystem) gracefully", () => {
    const m = _model([
      { id: "a", type: "flode.blocks.mathops.Gain", params: { k: 2.0 } },
    ]);
    expect(findBlockPath(m, "a")).toEqual([]);
    expect(findBlockPath(m, "missing")).toBeNull();
  });
});

describe("findBlockTypeById", () => {
  it("returns the type of a top-level block", () => {
    const m = _model([
      { id: "xy", type: "flode.blocks.sinks.XYGraph", params: {} },
      { id: "s", type: "flode.blocks.sinks.Scope", params: {} },
    ]);
    expect(findBlockTypeById(m, "xy")).toBe("flode.blocks.sinks.XYGraph");
    expect(findBlockTypeById(m, "s")).toBe("flode.blocks.sinks.Scope");
  });

  it("returns the type of a nested block", () => {
    const m = _model([
      {
        id: "sub",
        type: "flode.subsystems.Subsystem",
        params: {
          blocks: [
            { id: "xy", type: "flode.blocks.sinks.XYGraph", params: {} },
          ],
        },
      },
    ]);
    expect(findBlockTypeById(m, "xy")).toBe("flode.blocks.sinks.XYGraph");
  });

  it("returns null for a missing block", () => {
    const m = _model([
      { id: "s", type: "flode.blocks.sinks.Scope", params: {} },
    ]);
    expect(findBlockTypeById(m, "zzz")).toBeNull();
  });
});
