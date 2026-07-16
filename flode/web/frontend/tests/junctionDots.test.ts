// 分岐点 ● (junction dot) の座標算出ロジックの単体テスト。
//
// ``findJunctionPoints`` は「同一 source ポートから出る複数 edge の polyline が
// 実際に分かれる座標」を返す。``computeStepEdgePolyline`` (= 描画と同一幾何) と
// 合成して end-to-end でも検証する。

import { describe, expect, it } from "vitest";

import {
  computeStepEdgePolyline,
  type EdgeEndpointNode,
  type Point,
} from "../src/lib/edgeRectIntersect";
import { findJunctionPoints } from "../src/lib/junctionDots";

/** 期待座標との一致を順不同で検証するヘルパ。 */
function expectPointsEqual(actual: Point[], expected: Point[]): void {
  const norm = (ps: Point[]): string[] =>
    ps.map((p) => `${p.x},${p.y}`).sort();
  expect(norm(actual)).toEqual(norm(expected));
}

describe("findJunctionPoints", () => {
  it("returns no dots for a single edge", () => {
    const a: Point[] = [
      { x: 0, y: 0 },
      { x: 50, y: 0 },
      { x: 50, y: 20 },
      { x: 100, y: 20 },
    ];
    expect(findJunctionPoints([a])).toEqual([]);
  });

  it("returns no dots for an empty group", () => {
    expect(findJunctionPoints([])).toEqual([]);
  });

  it("places one dot where two edges peel off the shared trunk", () => {
    // 共有 trunk を y=0 で右へ進み、A は x=50、B は x=100 で折れる。
    const a: Point[] = [
      { x: 0, y: 0 },
      { x: 50, y: 0 },
      { x: 50, y: 20 },
      { x: 100, y: 20 },
    ];
    const b: Point[] = [
      { x: 0, y: 0 },
      { x: 100, y: 0 },
      { x: 100, y: -40 },
      { x: 200, y: -40 },
    ];
    expectPointsEqual(findJunctionPoints([a, b]), [{ x: 50, y: 0 }]);
  });

  it("places two dots for a 3-way fan that peels at different x", () => {
    const a: Point[] = [
      { x: 0, y: 0 },
      { x: 50, y: 0 },
      { x: 50, y: 20 },
      { x: 100, y: 20 },
    ];
    const b: Point[] = [
      { x: 0, y: 0 },
      { x: 100, y: 0 },
      { x: 100, y: 40 },
      { x: 200, y: 40 },
    ];
    const c: Point[] = [
      { x: 0, y: 0 },
      { x: 150, y: 0 },
      { x: 150, y: -30 },
      { x: 300, y: -30 },
    ];
    expectPointsEqual(findJunctionPoints([a, b, c]), [
      { x: 50, y: 0 },
      { x: 100, y: 0 },
    ]);
  });

  it("dedupes the dot when multiple pairs diverge at the same point", () => {
    // A が最初に折れるので (A,B) と (A,C) はどちらも (50,0) で分岐 → dedupe で 1 点。
    const a: Point[] = [
      { x: 0, y: 0 },
      { x: 50, y: 0 },
      { x: 50, y: 20 },
      { x: 100, y: 20 },
    ];
    const b: Point[] = [
      { x: 0, y: 0 },
      { x: 50, y: 0 },
      { x: 50, y: 60 },
      { x: 100, y: 60 },
    ];
    const c: Point[] = [
      { x: 0, y: 0 },
      { x: 50, y: 0 },
      { x: 50, y: -30 },
      { x: 100, y: -30 },
    ];
    // (a,b): 縦 trunk を y=20 まで共有し A が横へ折れる → (50,20)
    // (a,c) / (b,c): (50,0) で上下に分かれる → dedupe で (50,0) 1 点
    const dots = findJunctionPoints([a, b, c]);
    expectPointsEqual(dots, [
      { x: 50, y: 20 },
      { x: 50, y: 0 },
    ]);
  });

  it("returns no dot for fully identical polylines (duplicate connection)", () => {
    // 重複接続が JSON 直編集等で混入してもターゲット座標に ● を打たない。
    const a: Point[] = [
      { x: 0, y: 0 },
      { x: 50, y: 0 },
      { x: 50, y: 20 },
      { x: 100, y: 20 },
    ];
    const b: Point[] = [
      { x: 0, y: 0 },
      { x: 50, y: 0 },
      { x: 50, y: 20 },
      { x: 100, y: 20 },
    ];
    expect(findJunctionPoints([a, b])).toEqual([]);
  });

  it("diverges along a shared vertical trunk (same midX, same side)", () => {
    // 同じ midX=50 で縦 trunk を共有し、A が y=20 で先に横へ折れる。
    const a: Point[] = [
      { x: 0, y: 0 },
      { x: 50, y: 0 },
      { x: 50, y: 20 },
      { x: 100, y: 20 },
    ];
    const b: Point[] = [
      { x: 0, y: 0 },
      { x: 50, y: 0 },
      { x: 50, y: 60 },
      { x: 100, y: 60 },
    ];
    expectPointsEqual(findJunctionPoints([a, b]), [{ x: 50, y: 20 }]);
  });

  it("diverges at the corner when targets are on opposite sides (same midX)", () => {
    const a: Point[] = [
      { x: 0, y: 0 },
      { x: 50, y: 0 },
      { x: 50, y: -20 },
      { x: 100, y: -20 },
    ];
    const b: Point[] = [
      { x: 0, y: 0 },
      { x: 50, y: 0 },
      { x: 50, y: 30 },
      { x: 100, y: 30 },
    ];
    expectPointsEqual(findJunctionPoints([a, b]), [{ x: 50, y: 0 }]);
  });
});

describe("findJunctionPoints + computeStepEdgePolyline (end-to-end)", () => {
  const src: EdgeEndpointNode = {
    position: { x: 0, y: 0 },
    width: 80,
    height: 40,
    nInputs: 0,
    nOutputs: 1,
  };
  // 出力ポート中心: sx = 80 (右辺), sy = 40/2 = 20

  it("computes a dot from real step polylines, tolerating degenerate segments", () => {
    // dst1 は src と同じ高さ (sy==ty=20) → midX で長さ 0 の退化セグメントが
    // 生じる。スキップして正しく分岐点を出せること。
    const dst1: EdgeEndpointNode = {
      position: { x: 200, y: 0 },
      width: 80,
      height: 40,
      nInputs: 1,
      nOutputs: 1,
    }; // ty = 20, midX = (80+200)/2 = 140
    const dst2: EdgeEndpointNode = {
      position: { x: 200, y: 120 },
      width: 80,
      height: 40,
      nInputs: 1,
      nOutputs: 1,
    }; // ty = 140, midX = 140

    const p1 = computeStepEdgePolyline(src, 0, dst1, 0);
    const p2 = computeStepEdgePolyline(src, 0, dst2, 0);
    expectPointsEqual(findJunctionPoints([p1, p2]), [{ x: 140, y: 20 }]);
  });
});
