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
      { id: "src", type: "flode.blocks.Constant", params: { value: 1.0 } },
      { id: "g", type: "flode.blocks.Gain", params: { k: 2.0 } },
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
    expect(nodes[1]?.data.blockType).toBe("flode.blocks.Gain");
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
    // g は idx=1 → horizontal grid (1*120, 0)
    expect(nodes[1]?.position).toEqual({ x: 120, y: 0 });
  });

  it("returns horizontal grid auto-layout when layout key is absent", () => {
    // Reference-tool-like horizontal flow: idx 0 = (0,0), idx 1 = (120,0), ... wrap at 8
    const { nodes } = modelToDiagram(baseModel);
    expect(nodes[0]?.position).toEqual({ x: 0, y: 0 });
    expect(nodes[1]?.position).toEqual({ x: 120, y: 0 });
  });

  // v0.15.0: layout[id].flipped を data.flipped に転写し、BlockNodeView が
  // Position.Left ↔ Right を反転できるようにする。
  it("populates data.flipped from layout entry", () => {
    const model: FlwModel = {
      ...baseModel,
      layout: {
        src: { x: 0, y: 0, flipped: true },
        g: { x: 100, y: 0 },
      },
    };
    const { nodes } = modelToDiagram(model);
    expect(nodes[0]?.data.flipped).toBe(true);
    expect(nodes[1]?.data.flipped).toBe(false);
  });

  it("defaults data.flipped to false when layout entry has no flipped key", () => {
    const { nodes } = modelToDiagram(baseModel);
    expect(nodes[0]?.data.flipped).toBe(false);
    expect(nodes[1]?.data.flipped).toBe(false);
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
