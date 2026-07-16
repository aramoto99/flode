// Drag 範囲選択でエッジが選択されないバグの回帰テスト。
//
// React Flow v12 の rubber-band 選択は「選択ノードに接続している edge」しか
// 拾わず、edge geometry と選択矩形の交差判定をしない。flode 側で
// onSelectionEnd 経由で交差判定して補完するため、ここではその geometry
// 判定ロジックの単体テストを書く。

import { describe, expect, it } from "vitest";

import {
  computeStepEdgePolyline,
  polylineIntersectsRect,
  segmentIntersectsRect,
  type EdgeEndpointNode,
  type Point,
  type Rect,
} from "../src/lib/edgeRectIntersect";

// ---------- segmentIntersectsRect ----------

describe("segmentIntersectsRect", () => {
  const rect: Rect = { x: 40, y: 20, w: 30, h: 60 }; // x ∈ [40,70], y ∈ [20,80]

  it("returns true when a horizontal segment passes through the rect", () => {
    const p1: Point = { x: 0, y: 50 };
    const p2: Point = { x: 100, y: 50 };
    expect(segmentIntersectsRect(p1, p2, rect)).toBe(true);
  });

  it("returns true when a vertical segment passes through the rect", () => {
    const p1: Point = { x: 50, y: 0 };
    const p2: Point = { x: 50, y: 200 };
    expect(segmentIntersectsRect(p1, p2, rect)).toBe(true);
  });

  it("returns true when one endpoint is inside the rect", () => {
    const p1: Point = { x: 50, y: 50 }; // inside
    const p2: Point = { x: 200, y: 50 };
    expect(segmentIntersectsRect(p1, p2, rect)).toBe(true);
  });

  it("returns true when both endpoints are inside the rect", () => {
    const p1: Point = { x: 45, y: 30 };
    const p2: Point = { x: 65, y: 70 };
    expect(segmentIntersectsRect(p1, p2, rect)).toBe(true);
  });

  it("returns false when the segment is entirely to the left of the rect", () => {
    const p1: Point = { x: 0, y: 30 };
    const p2: Point = { x: 30, y: 70 };
    expect(segmentIntersectsRect(p1, p2, rect)).toBe(false);
  });

  it("returns false when the segment is entirely above the rect", () => {
    const p1: Point = { x: 0, y: 5 };
    const p2: Point = { x: 100, y: 10 };
    expect(segmentIntersectsRect(p1, p2, rect)).toBe(false);
  });

  it("returns false when the segment is parallel and outside (same y but x-range disjoint)", () => {
    const p1: Point = { x: 0, y: 50 };
    const p2: Point = { x: 30, y: 50 };
    expect(segmentIntersectsRect(p1, p2, rect)).toBe(false);
  });

  it("returns true for a diagonal segment crossing the rect", () => {
    const p1: Point = { x: 0, y: 0 };
    const p2: Point = { x: 200, y: 200 };
    // Crosses x=40..70 around y=40..70, well inside y range
    expect(segmentIntersectsRect(p1, p2, rect)).toBe(true);
  });
});

// ---------- polylineIntersectsRect ----------

describe("polylineIntersectsRect", () => {
  // 典型的な step edge: (0,0) → (50,0) → (50,100) → (100,100)
  // = 3 セグメント (水平 / 垂直 / 水平)
  const stepPolyline: Point[] = [
    { x: 0, y: 0 },
    { x: 50, y: 0 },
    { x: 50, y: 100 },
    { x: 100, y: 100 },
  ];

  it("returns true when rect covers the vertical leg of a step path (the reported bug case)", () => {
    // 報告されたスクリーンショットの状況: 選択矩形が垂直 leg だけを覆い、
    // 端点ノードはどちらも矩形外。React Flow v12 default では選択されないが
    // flode の補完ロジックでは選択されるべき。
    const rect: Rect = { x: 40, y: 30, w: 20, h: 40 }; // 矩形は x=40..60, y=30..70
    expect(polylineIntersectsRect(stepPolyline, rect)).toBe(true);
  });

  it("returns true when rect covers the first horizontal leg", () => {
    const rect: Rect = { x: 10, y: -10, w: 20, h: 20 }; // 矩形は y=-10..10 で y=0 の水平 leg を覆う
    expect(polylineIntersectsRect(stepPolyline, rect)).toBe(true);
  });

  it("returns true when rect covers the second horizontal leg", () => {
    const rect: Rect = { x: 70, y: 90, w: 20, h: 20 };
    expect(polylineIntersectsRect(stepPolyline, rect)).toBe(true);
  });

  it("returns false when rect is far from all segments", () => {
    const rect: Rect = { x: 200, y: 200, w: 10, h: 10 };
    expect(polylineIntersectsRect(stepPolyline, rect)).toBe(false);
  });

  it("returns false for a rect in the corner between segments (path is L-shaped, rect in the open angle)", () => {
    // step path (0,0) → (50,0) → (50,100) → (100,100) は左下に「凹」の領域を持つ。
    // 凹の中央付近 (x=20, y=50 周辺) は path から離れている。
    const rect: Rect = { x: 10, y: 40, w: 20, h: 20 }; // x=10..30, y=40..60
    expect(polylineIntersectsRect(stepPolyline, rect)).toBe(false);
  });

  it("handles empty / single-point polyline gracefully", () => {
    expect(polylineIntersectsRect([], { x: 0, y: 0, w: 10, h: 10 })).toBe(false);
    expect(
      polylineIntersectsRect([{ x: 5, y: 5 }], { x: 0, y: 0, w: 10, h: 10 }),
    ).toBe(false);
  });
});

// ---------- computeStepEdgePolyline ----------

describe("computeStepEdgePolyline", () => {
  // 左 ノード (出力 1 つ) → 右 ノード (入力 1 つ) の典型結線
  const srcNode: EdgeEndpointNode = {
    position: { x: 0, y: 0 },
    width: 60,
    height: 40,
    nInputs: 0,
    nOutputs: 1,
  };
  const dstNode: EdgeEndpointNode = {
    position: { x: 200, y: 100 },
    width: 60,
    height: 40,
    nInputs: 1,
    nOutputs: 0,
  };

  it("places source endpoint at the right border of the source node and target at the left border of the destination", () => {
    const polyline = computeStepEdgePolyline(srcNode, 0, dstNode, 0);
    expect(polyline[0]).toEqual({ x: 60, y: 20 }); // (0+60, 0+(0+1)*40/(1+1))
    expect(polyline[3]).toEqual({ x: 200, y: 120 }); // (200+0, 100+(0+1)*40/(1+1))
  });

  it("returns a 3-segment step polyline with midX between source and target", () => {
    const polyline = computeStepEdgePolyline(srcNode, 0, dstNode, 0);
    expect(polyline).toHaveLength(4);
    expect(polyline[1].x).toBe(polyline[2].x); // vertical leg
    expect(polyline[1].y).toBe(polyline[0].y); // source-side horizontal
    expect(polyline[2].y).toBe(polyline[3].y); // target-side horizontal
    expect(polyline[1].x).toBe((60 + 200) / 2);
  });

  it("uses uniform handle Y distribution for multi-port nodes", () => {
    const multiOut: EdgeEndpointNode = {
      ...srcNode,
      nOutputs: 3,
      height: 80,
    };
    // 出力 idx=1 (中央) → 80 * 2 / 4 = 40
    const polyline = computeStepEdgePolyline(multiOut, 1, dstNode, 0);
    expect(polyline[0].y).toBe(40);
  });

  it("flips source/target side when flipped=true", () => {
    const flippedSrc: EdgeEndpointNode = { ...srcNode, flipped: true };
    const flippedDst: EdgeEndpointNode = { ...dstNode, flipped: true };
    const polyline = computeStepEdgePolyline(flippedSrc, 0, flippedDst, 0);
    // 反転 source: 出力 = 左辺 = x=0、反転 dst: 入力 = 右辺 = 200+60=260
    expect(polyline[0].x).toBe(0);
    expect(polyline[3].x).toBe(260);
  });

  it("produces a polyline that intersects a rect crossing only the vertical leg (= reported bug shape)", () => {
    const polyline = computeStepEdgePolyline(srcNode, 0, dstNode, 0);
    // midX = (60+200)/2 = 130. 矩形は x=130 を含み、両端ノードからは離れている。
    const rect: Rect = { x: 120, y: 50, w: 20, h: 30 };
    expect(polylineIntersectsRect(polyline, rect)).toBe(true);
  });
});
