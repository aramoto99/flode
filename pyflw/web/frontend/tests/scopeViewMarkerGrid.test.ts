// Scope 設定「Marker」「Minor grid」が時系列描画 (buildOptions) に実際に効く
// ことをテストする。
//
// 背景: 旧実装は marker を XYGraphView でしか読まず、時系列 Scope は
// ``points: {show: false}`` ハードコード、grid_minor はどこからも読まれない
// 「飾り設定」だった。ダイアログに出す以上、両方とも描画へ反映する。

import type uPlot from "uplot";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// uPlot は module 評価時に matchMedia で devicePixelRatio 変化を監視する
// (jsdom 未実装 API)。import より前に stub を注入する。
vi.hoisted(() => {
  (globalThis as { matchMedia?: unknown }).matchMedia ??= () => ({
    matches: false,
    media: "",
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
  });
});

import {
  buildMarkerPaths,
  buildMinorGridAxis,
  buildOptions,
} from "../src/components/ScopeView";
import { DEFAULT_SCOPE_SETTINGS } from "../src/lib/scopeSettings";

/** jsdom に Path2D が無いため、描画命令を記録する stub に差し替える。 */
class Path2DStub {
  ops: Array<{ op: string; args: number[] }> = [];
  moveTo(...args: number[]): void {
    this.ops.push({ op: "moveTo", args });
  }
  lineTo(...args: number[]): void {
    this.ops.push({ op: "lineTo", args });
  }
  arc(...args: number[]): void {
    this.ops.push({ op: "arc", args });
  }
  rect(...args: number[]): void {
    this.ops.push({ op: "rect", args });
  }
}

beforeEach(() => {
  vi.stubGlobal("Path2D", Path2DStub);
  vi.stubGlobal("devicePixelRatio", 1);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("buildOptions: marker 設定が時系列 series に反映される", () => {
  it("marker 未指定 (none) は点を描かない", () => {
    const opts = buildOptions("s1", 1, DEFAULT_SCOPE_SETTINGS);
    expect(opts.series[1]!.points).toEqual({ show: false });
  });

  it("marker=circle で points.show=true + カスタム paths が付く", () => {
    const opts = buildOptions("s1", 2, {
      signals: { "1": { marker: "circle" } },
    });
    // signal 0 は none のまま
    expect(opts.series[1]!.points).toEqual({ show: false });
    const p = opts.series[2]!.points!;
    expect(p.show).toBe(true);
    expect(typeof p.paths).toBe("function");
  });
});

describe("buildMarkerPaths: 形状ごとの Path2D 生成", () => {
  /** valToPos = 恒等写像の最小 uPlot mock (3 サンプル、bbox 400px)。 */
  function fakeUplot(): uPlot {
    return {
      data: [
        [0, 1, 2],
        [10, 20, 30],
      ],
      series: [{}, { scale: "y" }],
      bbox: { width: 400, height: 200, left: 0, top: 0 },
      valToPos: (v: number) => v,
    } as unknown as uPlot;
  }

  it("circle は各サンプル位置に arc を描く", () => {
    const paths = buildMarkerPaths("circle")(fakeUplot(), 1, 0, 2);
    const stroke = paths!.stroke as unknown as Path2DStub;
    expect(stroke.ops.filter((o) => o.op === "arc")).toHaveLength(3);
    // 白抜き用の fill も付く
    expect(paths!.fill).toBe(paths!.stroke);
  });

  it("square は rect、cross は線 2 本 (fill なし)", () => {
    const sq = buildMarkerPaths("square")(fakeUplot(), 1, 0, 2);
    expect(
      (sq!.stroke as unknown as Path2DStub).ops.filter((o) => o.op === "rect"),
    ).toHaveLength(3);

    const cr = buildMarkerPaths("cross")(fakeUplot(), 1, 0, 2);
    const ops = (cr!.stroke as unknown as Path2DStub).ops;
    expect(ops.filter((o) => o.op === "lineTo")).toHaveLength(6);
    expect(cr!.fill).toBeNull();
  });

  it("高密度データでは stride 間引きで marker 数を抑える (波形自体は間引かない)", () => {
    const n = 10_000;
    const u = {
      data: [
        Array.from({ length: n }, (_, i) => i),
        Array.from({ length: n }, (_, i) => i * 2),
      ],
      series: [{}, { scale: "y" }],
      bbox: { width: 400, height: 200, left: 0, top: 0 },
      valToPos: (v: number) => v,
    } as unknown as uPlot;
    const paths = buildMarkerPaths("circle")(u, 1, 0, n - 1);
    const arcs = (paths!.stroke as unknown as Path2DStub).ops.filter(
      (o) => o.op === "arc",
    );
    // 400px / (直径 5px × 2) = 40 個程度まで間引かれる
    expect(arcs.length).toBeLessThanOrEqual(41);
    expect(arcs.length).toBeGreaterThan(0);
  });
});

describe("buildOptions / buildMinorGridAxis: Minor grid", () => {
  it("grid_minor=false (default) では minor axis を追加しない (axes は major 2 本)", () => {
    const opts = buildOptions("s1", 1, DEFAULT_SCOPE_SETTINGS);
    expect(opts.axes).toHaveLength(2);
  });

  it("grid_minor=true で x/y の minor axis が major より先に並ぶ", () => {
    const opts = buildOptions("s1", 1, { grid_minor: true });
    expect(opts.axes).toHaveLength(4);
    expect(opts.axes![0]!.scale).toBe("x");
    expect(opts.axes![1]!.scale).toBe("y");
    // minor は grid 線のみ (ラベル無し・サイズ 0)
    expect(opts.axes![0]!.size).toBe(0);
    expect(opts.axes![0]!.grid!.show).toBe(true);
  });

  it("y_mode=log では y の minor は出さない (線形細分が誤解を招くため)", () => {
    const opts = buildOptions("s1", 1, { grid_minor: true, y_mode: "log" });
    // x minor + major 2 本 = 3
    expect(opts.axes).toHaveLength(3);
    expect(opts.axes![0]!.scale).toBe("x");
  });

  it("splits は foundIncr の 1/5 刻み、grid.filter は major 位置を null にする", () => {
    const axis = buildMinorGridAxis("y");
    const splitsFn = axis.splits as Extract<uPlot.Axis.Splits, Function>;
    const u = {} as uPlot;
    // min=0, max=1, major incr=0.5 -> minor 0.1 刻みで 0..1 の 11 点
    const splits = splitsFn(u, 0, 0, 1, 0.5, 0);
    expect(splits).toHaveLength(11);
    expect(splits[1]).toBeCloseTo(0.1, 12);

    // grid 線の描画対象は axis.filter ではなく grid.filter で決まる
    // (axis.filter はラベル用で grid 線には効かない)。
    expect(axis.filter).toBeUndefined();
    const gridFilterFn = axis.grid!.filter!;
    const filtered = gridFilterFn(u, splits, 0, 0, 0.5);
    // 0 / 0.5 / 1.0 (major と一致) が null、それ以外は残る
    expect(filtered.filter((v) => v === null)).toHaveLength(3);
    expect(filtered[1]).toBeCloseTo(0.1, 12);
  });

  it("foundIncr が 0 / 非有限のときは空 splits (ゼロ除算防御)", () => {
    const axis = buildMinorGridAxis("x");
    const splitsFn = axis.splits as Extract<uPlot.Axis.Splits, Function>;
    expect(splitsFn({} as uPlot, 0, 0, 1, 0, 0)).toEqual([]);
    expect(splitsFn({} as uPlot, 0, 0, 1, Number.NaN, 0)).toEqual([]);
  });
});
