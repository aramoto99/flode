// bug-report 2026-11-19-edges-recreated-every-render: 再描画で前回の ``measured`` を引き継ぐ。
// 形が同じ node だけに付け、形に効く値が変わった node には付けない (React Flow に測り直させる)。

import { describe, expect, it } from "vitest";

import type { BlockNode } from "../src/lib/diagramConverter";
import { carryOverMeasured, type PreviousInternalNode } from "../src/lib/nodeMeasured";

function node(overrides: Partial<BlockNode["data"]> = {}, size = { width: 80, height: 40 }): BlockNode {
  return {
    id: "g",
    type: "blockNode",
    position: { x: 0, y: 0 },
    width: size.width,
    height: size.height,
    data: {
      blockType: "flode.blocks.mathops.Gain",
      params: { k: 1 },
      nInputs: 1,
      nOutputs: 1,
      isContainer: false,
      shapeWidth: size.width,
      shapeHeight: size.height,
      flipped: false,
      ...overrides,
    },
  };
}

function lookup(prev: BlockNode, measured: PreviousInternalNode["measured"] = { width: 80, height: 40 }) {
  const internal: PreviousInternalNode = { measured, internals: { userNode: prev } };
  return (id: string): PreviousInternalNode | undefined => (id === prev.id ? internal : undefined);
}

describe("carryOverMeasured", () => {
  it("carries measured when the shape is unchanged (params / selection may differ)", () => {
    const next = node({ params: { k: 2 } });
    const [out] = carryOverMeasured([next], lookup(node()));
    expect(out!.measured).toEqual({ width: 80, height: 40 });
    expect(out!.data).toBe(next.data);
  });

  it.each([
    ["input count", { nInputs: 2 }],
    ["output count", { nOutputs: 3 }],
    ["flip", { flipped: true }],
    ["shape width", { shapeWidth: 120 }],
    ["shape height", { shapeHeight: 60 }],
    ["block type", { blockType: "flode.blocks.mathops.Sum" }],
    ["container", { isContainer: true }],
    [
      "user block face",
      { userBlock: { kind: "placeholder", declaredInputs: null, declaredOutputs: null, removedParams: [] } },
    ],
  ] as const)("does not carry measured when the %s changes (re-measured)", (_label, change) => {
    const next = node(change as Partial<BlockNode["data"]>);
    const [out] = carryOverMeasured([next], lookup(node()));
    expect(out).toBe(next);
    expect(out!.measured).toBeUndefined();
  });

  describe("Subsystem control slots (same nInputs, different handle layout)", () => {
    const SUB = "flode.subsystems.subsystem.Subsystem";
    const inport = { id: "i", type: "flode.subsystems.ports.Inport", params: {} };
    const enable = { id: "e", type: "flode.subsystems.control_blocks.Enable", params: {} };
    const trigger = { id: "t", type: "flode.subsystems.control_blocks.Trigger", params: {} };
    const sub = (blocks: unknown[], nInputs: number): BlockNode =>
      node({ blockType: SUB, isContainer: true, nInputs, params: { blocks, connections: [] } });

    it("Inport x2 + Enable -> Inport x3 is re-measured", () => {
      const next = sub([inport, inport, inport], 3);
      expect(carryOverMeasured([next], lookup(sub([inport, inport, enable], 3)))[0]).toBe(next);
    });

    it("Enable only -> Trigger only is re-measured", () => {
      const next = sub([trigger], 1);
      expect(carryOverMeasured([next], lookup(sub([enable], 1)))[0]).toBe(next);
    });

    it("same slots (other inner edits) keep measured", () => {
      const next = sub([inport, enable, { id: "g", type: "flode.blocks.mathops.Gain", params: {} }], 2);
      const [out] = carryOverMeasured([next], lookup(sub([inport, enable], 2)));
      expect(out!.measured).toEqual({ width: 80, height: 40 });
    });

    it("user blocks have no control slots even with a 'blocks' argument", () => {
      const user = (blocks: unknown[]): BlockNode =>
        node({
          userBlock: { kind: "user", declaredInputs: 1, declaredOutputs: 1, removedParams: [] },
          params: { blocks },
        });
      const [out] = carryOverMeasured([user([trigger])], lookup(user([enable])));
      expect(out!.measured).toEqual({ width: 80, height: 40 });
    });
  });

  it("does not carry measured when the node size (resize) changes", () => {
    const next = node({}, { width: 100, height: 40 });
    expect(carryOverMeasured([next], lookup(node()))[0]).toBe(next);
  });

  it("leaves new nodes and not-yet-measured nodes as they are", () => {
    const next = node();
    expect(carryOverMeasured([next], () => undefined)[0]).toBe(next);
    const unmeasured: PreviousInternalNode = { internals: { userNode: node() } };
    expect(carryOverMeasured([next], () => unmeasured)[0]).toBe(next);
    expect(carryOverMeasured([next], lookup(node(), { width: 80 }))[0]).toBe(next);
  });
});
