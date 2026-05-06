import { describe, expect, it } from "vitest";

import { modelToDiagram, nodesToLayout } from "../src/lib/diagramConverter";
import type { BlockNode } from "../src/lib/diagramConverter";
import type { FlwModel } from "../src/types/api";

describe("modelToDiagram", () => {
  const baseModel: FlwModel = {
    schema_version: "0.5",
    simulator: {
      t_end: 1.0,
      dt: 0.01,
      solver: "RK45",
      rtol: 1e-6,
      atol: 1e-9,
      dt_base: null,
    },
    blocks: [
      { id: "src", type: "pyflw.blocks.Constant", params: { value: 1.0 } },
      { id: "g", type: "pyflw.blocks.Gain", params: { k: 2.0 } },
    ],
    connections: [{ src: "src", src_idx: 0, dst: "g", dst_idx: 0 }],
  };

  it("converts blocks to nodes with positions", () => {
    const { nodes } = modelToDiagram(baseModel);
    expect(nodes).toHaveLength(2);
    expect(nodes[0]?.id).toBe("src");
    expect(nodes[1]?.id).toBe("g");
    expect(nodes[0]?.position.x).toBe(0);
  });

  it("converts connections to edges", () => {
    const { edges } = modelToDiagram(baseModel);
    expect(edges).toHaveLength(1);
    expect(edges[0]?.source).toBe("src");
    expect(edges[0]?.target).toBe("g");
    expect(edges[0]?.sourceHandle).toBe("0");
    expect(edges[0]?.targetHandle).toBe("0");
  });

  it("preserves block params in node data", () => {
    const { nodes } = modelToDiagram(baseModel);
    expect(nodes[0]?.data.params).toEqual({ value: 1.0 });
    expect(nodes[1]?.data.blockType).toBe("pyflw.blocks.Gain");
  });

  // ADR-0020: layout が JSON にある場合はそれを使う。
  it("uses model.layout positions when present", () => {
    const model: FlwModel = {
      ...baseModel,
      layout: {
        src: { x: 100, y: 60 },
        g: { x: 300, y: 60 },
      },
    };
    const { nodes } = modelToDiagram(model);
    expect(nodes[0]?.position).toEqual({ x: 100, y: 60 });
    expect(nodes[1]?.position).toEqual({ x: 300, y: 60 });
  });

  // ADR-0020: layout が無い block だけ grid fallback を使う。
  it("falls back to grid layout for blocks missing in layout", () => {
    const model: FlwModel = {
      ...baseModel,
      layout: {
        src: { x: 100, y: 60 },
        // g は欠落
      },
    };
    const { nodes } = modelToDiagram(model);
    expect(nodes[0]?.position).toEqual({ x: 100, y: 60 });
    // g は idx=1 → grid (1*200, 0)
    expect(nodes[1]?.position).toEqual({ x: 200, y: 0 });
  });

  it("returns auto-layout when layout key is absent (backward compatible)", () => {
    const { nodes } = modelToDiagram(baseModel);
    expect(nodes[0]?.position).toEqual({ x: 0, y: 0 });
    expect(nodes[1]?.position).toEqual({ x: 200, y: 0 });
  });
});

describe("nodesToLayout", () => {
  it("builds a layout dict keyed by node id", () => {
    const nodes: BlockNode[] = [
      {
        id: "a",
        position: { x: 10, y: 20 },
        data: { blockType: "X", params: {} },
        type: "default",
      } as BlockNode,
      {
        id: "b",
        position: { x: 30, y: 40 },
        data: { blockType: "Y", params: {} },
        type: "default",
      } as BlockNode,
    ];
    expect(nodesToLayout(nodes)).toEqual({
      a: { x: 10, y: 20 },
      b: { x: 30, y: 40 },
    });
  });

  it("returns empty dict for empty nodes", () => {
    expect(nodesToLayout([])).toEqual({});
  });
});
