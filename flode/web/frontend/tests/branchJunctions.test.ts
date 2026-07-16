// ADR-0057 (改訂): 分岐点 ● の解決 (resolveJunctions) と幹線上再構成
// (reconstructVia / normalizeWaypointEntry) の単体テスト。
//
// R1 拘束: 手動 ● は幹線 (source 出力高さ) 上の 1 軸位置に再構成され、自動 ● と
// 意味が揃う。R3 後方互換: v1 旧形 {x,y} は {axis:"x", pos:x} として読む。
// R4 クランプ: pos は [source 端, 最も近い target 端] に収める。

import { describe, expect, it } from "vitest";
import type { Edge } from "@xyflow/react";

import {
  normalizeWaypointEntry,
  reconstructVia,
  resolveJunctions,
} from "../src/lib/branchJunctions";
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
      blockType: "flode.blocks.mathops.Gain",
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

// src(0,0) → g1(200,0) / g2(200,120)。出力点 sx=80, sy=20。midX=140。
// clamp 範囲 lo=sx=80, hi=min(tx)=200。
const nodes: BlockNode[] = [
  node("src", 0, 0, 0, 1),
  node("g1", 200, 0, 1, 1),
  node("g2", 200, 120, 1, 1),
];
const edges: Edge[] = [edge("e0", "src", "g1"), edge("e1", "src", "g2")];

describe("resolveJunctions", () => {
  it("returns an auto dot (manual=false) when no waypoint exists", () => {
    const { dots, vias } = resolveJunctions(nodes, edges, {});
    expect(dots).toHaveLength(1);
    expect(dots[0]).toMatchObject({
      x: 140,
      y: 20,
      groupKey: "src:0",
      manual: false,
      axis: "x",
    });
    expect(vias.size).toBe(0);
  });

  it("overrides auto with a single manual dot reconstructed on the trunk", () => {
    // pos=170 を幹線 (sy=20) 上に再構成 → ● は (170,20)。auto の (140,20) は出ない。
    const { dots, vias } = resolveJunctions(nodes, edges, {
      "src:0": { axis: "x", pos: 170 },
    });
    expect(dots).toHaveLength(1);
    expect(dots[0]).toMatchObject({
      x: 170,
      y: 20, // ← 幹線高さに拘束 (= R1)
      groupKey: "src:0",
      manual: true,
      axis: "x",
      lo: 80,
      hi: 200,
    });
    expect(vias.get("src:0")).toEqual({ x: 170, y: 20 });
  });

  it("clamps the manual pos to [source edge, nearest target edge] (R4)", () => {
    const over = resolveJunctions(nodes, edges, { "src:0": { axis: "x", pos: 999 } });
    expect(over.dots[0]).toMatchObject({ x: 200, y: 20 }); // hi=200
    const under = resolveJunctions(nodes, edges, { "src:0": { axis: "x", pos: -50 } });
    expect(under.dots[0]).toMatchObject({ x: 80, y: 20 }); // lo=80
  });

  it("migrates a v1 {x,y} waypoint to a trunk-constrained dot (R3/R6)", () => {
    // 旧形 {x,y} を opaque に持つモデル → axis"x", pos=x、y は楽観無視。
    const legacy = { "src:0": { x: 170, y: 300 } } as never;
    const { dots, vias } = resolveJunctions(nodes, edges, legacy);
    expect(dots).toHaveLength(1);
    expect(dots[0]).toMatchObject({ x: 170, y: 20, manual: true }); // y=300 は捨てる
    expect(vias.get("src:0")).toEqual({ x: 170, y: 20 });
  });

  it("ignores a waypoint whose group has < 2 branches (orphan)", () => {
    const single: Edge[] = [edge("e0", "src", "g1")];
    const { dots, vias } = resolveJunctions(nodes, single, {
      "src:0": { axis: "x", pos: 140 },
    });
    expect(dots).toEqual([]);
    expect(vias.size).toBe(0);
  });

  it("ignores a waypoint with non-finite pos", () => {
    const { dots, vias } = resolveJunctions(nodes, edges, {
      "src:0": { axis: "x", pos: NaN },
    });
    // 不正 pos → 手動 ● を打たない (グループはスキップ、auto にも戻さない)
    expect(dots).toEqual([]);
    expect(vias.size).toBe(0);
  });

  it("suppresses dots when target nodes are missing (dangling edges)", () => {
    // edge は 2 本あるが target node が graph に無い → targetEps < 2 で分岐不成立。
    // 手動 waypoint があっても ● も via も出さない (= モデル corrupt 回避)。
    const dangling: Edge[] = [
      edge("e0", "src", "missing1"),
      edge("e1", "src", "missing2"),
    ];
    const { dots, vias } = resolveJunctions(nodes, dangling, {
      "src:0": { axis: "x", pos: 140 },
    });
    expect(dots).toEqual([]);
    expect(vias.size).toBe(0);
  });

  it("uses the persistence key form '<src>:<idx>'", () => {
    const { dots } = resolveJunctions(nodes, edges, {});
    expect(dots[0]!.groupKey).toBe("src:0");
  });
});

describe("reconstructVia", () => {
  it("places the via on the horizontal trunk (axis x): {pos, sy}", () => {
    expect(reconstructVia("x", 170, 80, 20, 80, 200)).toEqual({ x: 170, y: 20 });
  });

  it("clamps pos to [lo, hi] (axis x)", () => {
    expect(reconstructVia("x", 999, 80, 20, 80, 200)).toEqual({ x: 200, y: 20 });
    expect(reconstructVia("x", -5, 80, 20, 80, 200)).toEqual({ x: 80, y: 20 });
  });

  it("places the via on the vertical trunk (axis y): {sx, pos} (future-ready)", () => {
    expect(reconstructVia("y", 150, 80, 20, 50, 300)).toEqual({ x: 80, y: 150 });
    expect(reconstructVia("y", 999, 80, 20, 50, 300)).toEqual({ x: 80, y: 300 });
  });
});

describe("normalizeWaypointEntry", () => {
  it("passes through a new {axis,pos} entry", () => {
    expect(normalizeWaypointEntry({ axis: "x", pos: 5 })).toEqual({ axis: "x", pos: 5 });
    expect(normalizeWaypointEntry({ axis: "y", pos: 7 })).toEqual({ axis: "y", pos: 7 });
  });

  it("migrates a v1 {x,y} entry to {axis:'x', pos:x} (y ignored)", () => {
    expect(normalizeWaypointEntry({ x: 42, y: 99 })).toEqual({ axis: "x", pos: 42 });
  });

  it("returns null for invalid / empty entries", () => {
    expect(normalizeWaypointEntry(undefined)).toBeNull();
    expect(normalizeWaypointEntry(null)).toBeNull();
    expect(normalizeWaypointEntry({})).toBeNull();
    expect(normalizeWaypointEntry({ axis: "x", pos: NaN })).toBeNull();
    expect(normalizeWaypointEntry({ x: Infinity, y: 1 })).toBeNull();
  });
});
