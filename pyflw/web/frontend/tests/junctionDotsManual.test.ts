// ADR-0057: computeJunctionDots の手動上書きロジックの単体テスト。
//
// 手動 waypoint を持つ (source, sourceHandle) グループは自動算出をスキップし、
// waypoint 座標に ● を 1 個だけ打つ (= 二重表示防止 + 描画 via と ● 座標が同一値)。
// waypoint が無いグループは従来どおり findJunctionPoints の自動 ● を出す。

import { describe, expect, it } from "vitest";
import type { Edge } from "@xyflow/react";

import { computeJunctionDots } from "../src/components/JunctionDots";
import type { BlockNode } from "../src/lib/diagramConverter";

function node(
  id: string,
  x: number,
  y: number,
  nInputs: number,
  nOutputs: number,
): BlockNode {
  return {
    id,
    position: { x, y },
    width: 80,
    height: 40,
    type: "blockNode",
    data: {
      blockType: "pyflw.blocks.mathops.Gain",
      params: {},
      nInputs,
      nOutputs,
      shapeWidth: 80,
      shapeHeight: 40,
    },
  };
}

function edge(id: string, source: string, target: string): Edge {
  return { id, source, target, sourceHandle: "0", targetHandle: "0" };
}

// src(0,0) → g1(200,0) / g2(200,120): sx=80, sy=20, midX=140。自動分岐点 (140,20)。
const nodes: BlockNode[] = [
  node("src", 0, 0, 0, 1),
  node("g1", 200, 0, 1, 1),
  node("g2", 200, 120, 1, 1),
];
const edges: Edge[] = [edge("e0", "src", "g1"), edge("e1", "src", "g2")];

describe("computeJunctionDots", () => {
  it("returns an auto dot (manual=false) when no waypoint exists", () => {
    const dots = computeJunctionDots(nodes, edges, {});
    expect(dots).toHaveLength(1);
    expect(dots[0]).toMatchObject({
      x: 140,
      y: 20,
      groupKey: "src:0",
      manual: false,
    });
  });

  it("overrides auto with a single manual dot at the waypoint", () => {
    const dots = computeJunctionDots(nodes, edges, {
      "src:0": { x: 140, y: 300 },
    });
    expect(dots).toHaveLength(1);
    expect(dots[0]).toEqual({
      x: 140,
      y: 300,
      groupKey: "src:0",
      manual: true,
    });
  });

  it("ignores a waypoint whose group has < 2 branches (orphan)", () => {
    const single: Edge[] = [edge("e0", "src", "g1")];
    const dots = computeJunctionDots(nodes, single, {
      "src:0": { x: 10, y: 10 },
    });
    expect(dots).toEqual([]);
  });

  it("ignores a waypoint with non-finite coordinates", () => {
    const dots = computeJunctionDots(nodes, edges, {
      "src:0": { x: NaN, y: 10 },
    });
    // 手動座標が不正 → ● を打たない (= auto にも戻らず、その group はスキップ)
    expect(dots).toEqual([]);
  });

  it("uses the persistence key form '<src>:<idx>' for the group", () => {
    const dots = computeJunctionDots(nodes, edges, {});
    expect(dots[0]!.groupKey).toBe("src:0");
  });
});
