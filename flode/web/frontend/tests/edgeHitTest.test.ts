// ADR-0087: 配線のダブルクリックの幾何判定 (lib/edgeHitTest.ts)。
// DOM の当たり判定は、再描画で配線の要素が 1 フレーム消えると pane に当たるため使わない。

import type { Edge } from "@xyflow/react";
import { describe, expect, it } from "vitest";

import { modelToDiagram, type BlockNode } from "../src/lib/diagramConverter";
import {
  buildEdgeHitGeometry,
  distanceToPolyline,
  findSignalAtPoint,
} from "../src/lib/edgeHitTest";
import { resolveBlocksAtPath } from "../src/lib/pathResolver";
import type { FlwModel } from "../src/types/api";

/** 100x40 のブロック (出力 nOut、入力 nIn)。 */
function node(
  id: string,
  x: number,
  y: number,
  opts: { nIn?: number; nOut?: number; flipped?: boolean } = {},
): BlockNode {
  return {
    id,
    type: "blockNode",
    position: { x, y },
    width: 100,
    height: 40,
    data: {
      nInputs: opts.nIn ?? 1,
      nOutputs: opts.nOut ?? 1,
      flipped: opts.flipped ?? false,
    },
  } as unknown as BlockNode;
}

function edge(source: string, target: string, sh = 0, th = 0, via?: { x: number; y: number }): Edge {
  return {
    id: `${source}-${sh}-${target}-${th}`,
    source,
    target,
    sourceHandle: String(sh),
    targetHandle: String(th),
    ...(via ? { data: { via } } : {}),
  };
}

const TOL = 10;

describe("distanceToPolyline", () => {
  it("measures the distance to the nearest segment", () => {
    const poly = [
      { x: 0, y: 0 },
      { x: 10, y: 0 },
      { x: 10, y: 10 },
    ];
    expect(distanceToPolyline({ x: 5, y: 3 }, poly)).toBeCloseTo(3);
    expect(distanceToPolyline({ x: 14, y: 5 }, poly)).toBeCloseTo(4);
    expect(distanceToPolyline({ x: -3, y: -4 }, poly)).toBeCloseTo(5);
    expect(distanceToPolyline({ x: 1, y: 1 }, [])).toBe(Infinity);
  });
});

describe("findSignalAtPoint", () => {
  // a (0,0)-(100,40) の出力 (100,20) → b (300,0) の入力 (300,20): 水平な直線
  const nodes = [node("a", 0, 0), node("b", 300, 0)];
  const geo = buildEdgeHitGeometry(nodes, [edge("a", "b")]);

  it("picks the wire within the hit width, not outside", () => {
    expect(findSignalAtPoint({ x: 200, y: 26 }, geo.edges, geo.nodes, TOL)).toEqual({ src: "a", srcIdx: 0 });
    expect(findSignalAtPoint({ x: 200, y: 31 }, geo.edges, geo.nodes, TOL)).toBeNull();
  });

  it("the hit width is in screen px (scaled by zoom)", () => {
    // zoom 2 なら flow 座標で 5 まで
    expect(findSignalAtPoint({ x: 200, y: 27 }, geo.edges, geo.nodes, TOL / 2)).toBeNull();
    expect(findSignalAtPoint({ x: 200, y: 24 }, geo.edges, geo.nodes, TOL / 2)).not.toBeNull();
  });

  it("does nothing over a block body (block double-click is not taken)", () => {
    expect(findSignalAtPoint({ x: 95, y: 20 }, geo.edges, geo.nodes, TOL)).toBeNull();
  });

  it("branches share the signal; the nearest wire wins between different signals", () => {
    const ns = [node("a", 0, 0, { nOut: 2 }), node("b", 300, 0), node("c", 300, 200)];
    // a:0 (y=13.3) → b、a:0 → c (分岐)、a:1 (y=26.7) → b の入力 1 ではなく c
    const g = buildEdgeHitGeometry(ns, [edge("a", "b"), edge("a", "c"), edge("a", "c", 1, 0)]);
    // 分岐 (a→c) の縦の区間の上
    const onBranch = findSignalAtPoint({ x: 200, y: 120 }, g.edges, g.nodes, TOL);
    expect(onBranch?.src).toBe("a");
    // 出力 0 と 1 の水平区間は y が 13.3 / 26.7: 近い方
    expect(findSignalAtPoint({ x: 140, y: 15 }, g.edges, g.nodes, TOL)).toEqual({ src: "a", srcIdx: 0 });
    expect(findSignalAtPoint({ x: 140, y: 25 }, g.edges, g.nodes, TOL)).toEqual({ src: "a", srcIdx: 1 });
  });

  it("follows a manual branch point (via)", () => {
    const ns = [node("a", 0, 0), node("b", 300, 100)];
    const g = buildEdgeHitGeometry(ns, [edge("a", "b", 0, 0, { x: 150, y: 20 })]);
    // via x=150 で縦に折れる
    expect(findSignalAtPoint({ x: 152, y: 70 }, g.edges, g.nodes, TOL)).toEqual({ src: "a", srcIdx: 0 });
    expect(findSignalAtPoint({ x: 200, y: 70 }, g.edges, g.nodes, TOL)).toBeNull();
  });

  it("flipped source block: the output is on the left edge", () => {
    // a は反転 (出力が左辺 x=300)、b は左側 (入力は左辺 x=0 のまま非反転)
    const ns = [node("a", 300, 0, { flipped: true }), node("b", 0, 100)];
    const g = buildEdgeHitGeometry(ns, [edge("a", "b")]);
    const start = g.edges[0]!.polyline[0]!;
    expect(start).toEqual({ x: 300, y: 20 });
    expect(findSignalAtPoint({ x: 295, y: 22 }, g.edges, g.nodes, TOL)).toEqual({ src: "a", srcIdx: 0 });
    // 反転しないと出力側になる右辺 (x=400) の外は配線ではない
    expect(findSignalAtPoint({ x: 410, y: 20 }, g.edges, g.nodes, TOL)).toBeNull();
  });

  it("skips wires whose blocks have no size yet", () => {
    const unsized = { ...node("a", 0, 0), width: undefined, data: { nInputs: 1, nOutputs: 1 } };
    const g = buildEdgeHitGeometry([unsized as unknown as BlockNode, node("b", 300, 0)], [edge("a", "b")]);
    expect(g.edges).toHaveLength(0);
  });

  it("a block whose port counts are unknown still excludes its body", () => {
    // c は寸法はあるがポート数が未確定 (配線の端点は取れない)。a→b の配線が c の上を通る
    const portless = { ...node("c", 150, 0), data: {} } as unknown as BlockNode;
    const g = buildEdgeHitGeometry([node("a", 0, 0), node("b", 400, 0), portless], [edge("a", "b")]);
    expect(findSignalAtPoint({ x: 200, y: 20 }, g.edges, g.nodes, TOL)).toBeNull();
    expect(findSignalAtPoint({ x: 120, y: 20 }, g.edges, g.nodes, TOL)).toEqual({ src: "a", srcIdx: 0 });
  });
});

describe("buildEdgeHitGeometry inside a Subsystem scope", () => {
  it("uses the inner scope's blocks and wires (real converter output)", () => {
    const model: FlwModel = {
      schema_version: "0.15",
      simulator: { t_end: 1, dt: 0.1, solver: "RK45", rtol: 1e-3, atol: 1e-6, dt_base: null },
      blocks: [
        {
          id: "sub",
          type: "flode.subsystems.subsystem.Subsystem",
          params: {
            blocks: [
              { id: "i", type: "flode.subsystems.ports.Inport", params: { port_idx: 0 } },
              { id: "k", type: "flode.blocks.mathops.Gain", params: { k: 2 } },
            ],
            connections: [{ src: "i", src_idx: 0, dst: "k", dst_idx: 0 }],
            layout: { i: { x: 0, y: 0 }, k: { x: 300, y: 0 } },
          },
        },
      ],
      connections: [],
      layout: { sub: { x: 0, y: 0 } },
    };
    const view = resolveBlocksAtPath(model, ["sub"]);
    const { nodes, edges } = modelToDiagram({ ...model, ...view });
    const g = buildEdgeHitGeometry(nodes, edges);
    expect(g.edges).toHaveLength(1);
    // 最初の区間 (出力ポートから出た水平区間) の中点
    const [p0, p1] = g.edges[0]!.polyline;
    const onWire = { x: (p0!.x + p1!.x) / 2, y: p0!.y };
    expect(findSignalAtPoint(onWire, g.edges, g.nodes, TOL)).toEqual({ src: "i", srcIdx: 0 });
    // 配線から離れた点は当たらない
    expect(findSignalAtPoint({ x: onWire.x, y: onWire.y + 50 }, g.edges, g.nodes, TOL)).toBeNull();
  });
});
