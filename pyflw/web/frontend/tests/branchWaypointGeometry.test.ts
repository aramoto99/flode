// ADR-0057: 手動 branch waypoint (via) 経由の step polyline 幾何の単体テスト。
//
// 描画 (BranchableEdge) と ● 算出 (JunctionDots) が同一の getStepEdgePolyline を
// 共有することで「描画と ● 座標が定義上一致」する (= 幾何 SSOT)。本テストは via
// 経由 polyline が必ず via を通ること / 後方互換 (via 無し = 従来 midX 近似) /
// polylineToSvgPath / computeStepEdgePolyline の via 透過を検証する。

import { describe, expect, it } from "vitest";

import {
  computeStepEdgePolyline,
  getStepEdgePolyline,
  polylineToSvgPath,
  type EdgeEndpointNode,
  type Point,
} from "../src/lib/edgeRectIntersect";

/** polyline が点 ``p`` を頂点として含むか (= via が確実にワイヤ上の頂点)。 */
function hasVertex(poly: readonly Point[], p: Point): boolean {
  return poly.some((q) => q.x === p.x && q.y === p.y);
}

describe("getStepEdgePolyline (via 無し = 後方互換)", () => {
  it("returns the legacy 4-point midX approximation", () => {
    expect(getStepEdgePolyline(0, 0, 100, 40)).toEqual([
      { x: 0, y: 0 },
      { x: 50, y: 0 },
      { x: 50, y: 40 },
      { x: 100, y: 40 },
    ]);
  });
});

describe("getStepEdgePolyline (via あり)", () => {
  it("always routes through the via point as a vertex", () => {
    const via = { x: 70, y: 200 };
    const poly = getStepEdgePolyline(0, 0, 300, 40, via);
    expect(hasVertex(poly, via)).toBe(true);
    // 始点 / 終点は端点のまま
    expect(poly[0]).toEqual({ x: 0, y: 0 });
    expect(poly[poly.length - 1]).toEqual({ x: 300, y: 40 });
  });

  it("two branches sharing source+via share the trunk and diverge at via", () => {
    // 同一 (source, handle) の 2 枝は sy / via が共通なので (sx,sy)→(via.x,sy)→via
    // を共有し、via から各 target へ分かれる。
    const via = { x: 120, y: 100 };
    const a = getStepEdgePolyline(0, 0, 300, 40, via);
    const b = getStepEdgePolyline(0, 0, 300, 250, via);
    // trunk 部分 (先頭 3 頂点 = source → (via.x,sy) → via) が一致する
    expect(a.slice(0, 3)).toEqual(b.slice(0, 3));
    expect(a.slice(0, 3)).toEqual([
      { x: 0, y: 0 },
      { x: 120, y: 0 },
      { x: 120, y: 100 },
    ]);
  });

  it("dedupes degenerate vertices when via lies on the trunk", () => {
    // via.y == sy のとき (via.x, sy) と via が重なる → 連続重複頂点を除去する。
    const via = { x: 60, y: 0 };
    const poly = getStepEdgePolyline(0, 0, 200, 40, via);
    // 連続する重複頂点が無いこと
    for (let i = 1; i < poly.length; i++) {
      expect(poly[i]).not.toEqual(poly[i - 1]);
    }
    expect(hasVertex(poly, via)).toBe(true);
  });
});

describe("polylineToSvgPath", () => {
  it("emits M/L commands with right-angle segments", () => {
    expect(
      polylineToSvgPath([
        { x: 0, y: 0 },
        { x: 50, y: 0 },
        { x: 50, y: 40 },
      ]),
    ).toBe("M0,0L50,0L50,40");
  });

  it("returns empty string for < 2 points", () => {
    expect(polylineToSvgPath([])).toBe("");
    expect(polylineToSvgPath([{ x: 1, y: 2 }])).toBe("");
  });
});

describe("computeStepEdgePolyline (via 透過)", () => {
  const src: EdgeEndpointNode = {
    position: { x: 0, y: 0 },
    width: 80,
    height: 40,
    nInputs: 0,
    nOutputs: 1,
  }; // sx=80, sy=20
  const dst: EdgeEndpointNode = {
    position: { x: 300, y: 0 },
    width: 80,
    height: 40,
    nInputs: 1,
    nOutputs: 1,
  }; // tx=300, ty=20

  it("passes via through to the polyline", () => {
    const via = { x: 150, y: 120 };
    const poly = computeStepEdgePolyline(src, 0, dst, 0, via);
    expect(hasVertex(poly, via)).toBe(true);
    expect(poly[0]).toEqual({ x: 80, y: 20 });
    expect(poly[poly.length - 1]).toEqual({ x: 300, y: 20 });
  });

  it("without via stays identical to legacy behavior", () => {
    const poly = computeStepEdgePolyline(src, 0, dst, 0);
    // midX = (80+300)/2 = 190。via なし時は dedupeConsecutive を**意図的に通さない**
    // ため (= 後方互換: 既存 findJunctionPoints は退化セグメントを許容する)、sy==ty で
    // (190,20) が 2 個連続する 4 頂点になる。via なしに dedupe を入れるリファクタを
    // するときはこの期待値も更新すること。
    expect(poly).toEqual([
      { x: 80, y: 20 },
      { x: 190, y: 20 },
      { x: 190, y: 20 },
      { x: 300, y: 20 },
    ]);
  });
});
