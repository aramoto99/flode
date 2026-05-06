// ADR-0021 §(2): pathResolver のテスト。

import { describe, expect, it } from "vitest";

import {
  applyAtPath,
  findBlockAtPath,
  resolveBlocksAtPath,
} from "../src/lib/pathResolver";
import type { FlwModel } from "../src/types/api";

const NESTED_MODEL: FlwModel = {
  schema_version: "0.6",
  simulator: {
    t_end: 1,
    dt: 0.01,
    solver: "RK45",
    rtol: 1e-6,
    atol: 1e-9,
    dt_base: null,
  },
  blocks: [
    {
      id: "outer",
      type: "pyflw.subsystems.subsystem.Subsystem",
      params: {
        n_inputs: 0,
        n_outputs: 0,
        blocks: [
          {
            id: "g",
            type: "pyflw.blocks.mathops.Gain",
            params: { k: 2.0 },
          },
          {
            id: "inner",
            type: "pyflw.subsystems.subsystem.Subsystem",
            params: {
              n_inputs: 0,
              n_outputs: 0,
              blocks: [
                {
                  id: "h",
                  type: "pyflw.blocks.mathops.Gain",
                  params: { k: 3.0 },
                },
              ],
              connections: [],
              layout: { h: { x: 100, y: 200 } },
            },
          },
        ],
        connections: [],
      },
    },
  ],
  connections: [],
  layout: { outer: { x: 0, y: 0 } },
};

describe("resolveBlocksAtPath", () => {
  it("returns top-level for empty path", () => {
    const v = resolveBlocksAtPath(NESTED_MODEL, []);
    expect(v.blocks).toHaveLength(1);
    expect(v.blocks[0]?.id).toBe("outer");
    expect(v.layout.outer).toEqual({ x: 0, y: 0 });
  });

  it("descends into a single subsystem", () => {
    const v = resolveBlocksAtPath(NESTED_MODEL, ["outer"]);
    expect(v.blocks).toHaveLength(2);
    expect(v.blocks.map((b) => b.id)).toEqual(["g", "inner"]);
  });

  it("descends two levels", () => {
    const v = resolveBlocksAtPath(NESTED_MODEL, ["outer", "inner"]);
    expect(v.blocks).toHaveLength(1);
    expect(v.blocks[0]?.id).toBe("h");
    expect(v.layout.h).toEqual({ x: 100, y: 200 });
  });

  it("throws on missing segment", () => {
    expect(() => resolveBlocksAtPath(NESTED_MODEL, ["nope"])).toThrow();
  });

  it("throws when descending into a non-subsystem", () => {
    expect(() => resolveBlocksAtPath(NESTED_MODEL, ["outer", "g"])).toThrow();
  });
});

describe("applyAtPath", () => {
  it("modifies top-level immutably", () => {
    const next = applyAtPath(NESTED_MODEL, [], (view) => ({
      ...view,
      blocks: [
        ...view.blocks,
        {
          id: "new",
          type: "pyflw.blocks.sources.Constant",
          params: { value: 1.0 },
        },
      ],
    }));
    expect(next.blocks).toHaveLength(2);
    // 元 model は不変
    expect(NESTED_MODEL.blocks).toHaveLength(1);
  });

  it("modifies nested layout without affecting other branches", () => {
    const next = applyAtPath(NESTED_MODEL, ["outer", "inner"], (view) => ({
      ...view,
      layout: { h: { x: 999, y: 888 } },
    }));
    const updated = resolveBlocksAtPath(next, ["outer", "inner"]);
    expect(updated.layout.h).toEqual({ x: 999, y: 888 });
    // top-level / outer のレイアウトは触らない
    expect(next.layout?.outer).toEqual({ x: 0, y: 0 });
  });

  it("preserves outer subsystem identity outside path", () => {
    const next = applyAtPath(NESTED_MODEL, ["outer"], (view) => ({
      ...view,
      blocks: view.blocks.map((b) =>
        b.id === "g" ? { ...b, params: { k: 99.0 } } : b,
      ),
    }));
    const view = resolveBlocksAtPath(next, ["outer"]);
    const g = view.blocks.find((b) => b.id === "g");
    expect((g?.params as { k: number }).k).toBe(99.0);
    // inner subsystem は同じ参照内容
    const inner = resolveBlocksAtPath(next, ["outer", "inner"]);
    expect(inner.blocks[0]?.id).toBe("h");
  });
});

describe("findBlockAtPath", () => {
  it("finds at root", () => {
    expect(findBlockAtPath(NESTED_MODEL, [], "outer")?.id).toBe("outer");
  });
  it("finds nested", () => {
    expect(findBlockAtPath(NESTED_MODEL, ["outer", "inner"], "h")?.id).toBe("h");
  });
  it("returns undefined when not present", () => {
    expect(findBlockAtPath(NESTED_MODEL, ["outer"], "ghost")).toBeUndefined();
  });
});
