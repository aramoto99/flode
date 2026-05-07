// ADR-0023 §Decision §(2): uPlot 薄ラッパの単体テスト。
//
// uPlot 本体を vi.mock でモックして、ラッパの API 設計 (mount / unmount /
// setData 差分更新 / setSize on resize) のみを検証する。
// 描画自体の正しさは uPlot 本体が担保するので、ここでは検査しない。

import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// --- uPlot mock (default export) ---
const setData = vi.fn();
const setSize = vi.fn();
const destroy = vi.fn();
const ctorCalls: Array<{ opts: unknown; data: unknown; root: unknown }> = [];

vi.mock("uplot", () => {
  const ctor = vi.fn(function (
    this: { setData: typeof setData; setSize: typeof setSize; destroy: typeof destroy },
    opts: unknown,
    data: unknown,
    root: unknown,
  ) {
    ctorCalls.push({ opts, data, root });
    this.setData = setData;
    this.setSize = setSize;
    this.destroy = destroy;
  });
  return { default: ctor };
});

import { UPlotChart } from "../src/components/UPlotChart";

beforeEach(() => {
  setData.mockClear();
  setSize.mockClear();
  destroy.mockClear();
  ctorCalls.length = 0;
});

afterEach(() => {
  cleanup();
});

describe("UPlotChart mount / unmount", () => {
  it("instantiates uPlot once on mount", () => {
    const data: [Float64Array, Float64Array] = [
      new Float64Array([0, 1, 2]),
      new Float64Array([10, 20, 30]),
    ];
    const opts = { width: 400, height: 200, series: [{}, { label: "A" }] };
    render(<UPlotChart options={opts} data={data} />);
    expect(ctorCalls.length).toBe(1);
    expect(destroy).not.toHaveBeenCalled();
  });

  it("calls destroy on unmount", () => {
    const data: [Float64Array, Float64Array] = [
      new Float64Array([0]),
      new Float64Array([1]),
    ];
    const opts = { width: 100, height: 100, series: [{}, { label: "A" }] };
    const { unmount } = render(<UPlotChart options={opts} data={data} />);
    unmount();
    expect(destroy).toHaveBeenCalledTimes(1);
  });
});

describe("UPlotChart setData diffing", () => {
  it("calls setData when data prop changes", () => {
    const opts = { width: 100, height: 100, series: [{}, { label: "A" }] };
    const d1: [Float64Array, Float64Array] = [
      new Float64Array([0, 1]),
      new Float64Array([10, 20]),
    ];
    const d2: [Float64Array, Float64Array] = [
      new Float64Array([0, 1, 2]),
      new Float64Array([10, 20, 30]),
    ];
    const { rerender } = render(<UPlotChart options={opts} data={d1} />);
    expect(setData).not.toHaveBeenCalled(); // 初回は constructor が data を持つ
    rerender(<UPlotChart options={opts} data={d2} />);
    expect(setData).toHaveBeenCalledTimes(1);
    expect(setData).toHaveBeenCalledWith(d2);
  });

  it("does not call setData when data reference is unchanged", () => {
    const opts = { width: 100, height: 100, series: [{}, { label: "A" }] };
    const d: [Float64Array, Float64Array] = [
      new Float64Array([0, 1]),
      new Float64Array([10, 20]),
    ];
    const { rerender } = render(<UPlotChart options={opts} data={d} />);
    rerender(<UPlotChart options={opts} data={d} />); // 同一参照
    expect(setData).not.toHaveBeenCalled();
  });
});

// ─── 補強テスト (ADR-0023 境界値・エッジケース) ──────────────────────────────

describe("UPlotChart: options 参照変更で destroy → 再生成", () => {
  it("destroys the old uPlot instance and creates a new one when options reference changes", () => {
    // options 参照変更は uPlot の仕様で全再構築が必要 (setData では対応不可)
    const d: [Float64Array, Float64Array] = [
      new Float64Array([0, 1]),
      new Float64Array([10, 20]),
    ];
    const opts1 = { width: 100, height: 100, series: [{}, { label: "A" }] };
    const opts2 = { width: 200, height: 150, series: [{}, { label: "B" }] }; // 別参照
    const { rerender } = render(<UPlotChart options={opts1} data={d} />);
    expect(ctorCalls.length).toBe(1);
    expect(destroy).not.toHaveBeenCalled();

    rerender(<UPlotChart options={opts2} data={d} />);
    // 既存 instance が破棄されて新しい instance が作られる
    expect(destroy).toHaveBeenCalledTimes(1);
    expect(ctorCalls.length).toBe(2);
  });

  it("does not call setData when options change triggers full rebuild", () => {
    // options 変更で新 instance が作られるとき、data effect は skip すべき
    // (新 instance のコンストラクタが data を受け取るので setData は不要)
    const d: [Float64Array, Float64Array] = [
      new Float64Array([0, 1]),
      new Float64Array([10, 20]),
    ];
    const opts1 = { width: 100, height: 100, series: [{}, { label: "A" }] };
    const opts2 = { width: 200, height: 150, series: [{}, { label: "B" }] };
    const { rerender } = render(<UPlotChart options={opts1} data={d} />);
    rerender(<UPlotChart options={opts2} data={d} />);
    // data 参照が同一なので setData は呼ばれないはず
    expect(setData).not.toHaveBeenCalled();
  });
});

describe("UPlotChart: className prop", () => {
  it("applies the className prop to the container div", () => {
    const d: [Float64Array, Float64Array] = [
      new Float64Array([0]),
      new Float64Array([1]),
    ];
    const opts = { width: 100, height: 100, series: [{}, { label: "A" }] };
    const { container } = render(
      <UPlotChart options={opts} data={d} className="absolute inset-0" />,
    );
    const div = container.firstChild as HTMLElement;
    expect(div.className).toContain("absolute");
    expect(div.className).toContain("inset-0");
  });
});

describe("UPlotChart: double unmount protection", () => {
  it("does not call destroy a second time on double unmount", () => {
    // React 18 StrictMode double-invoke や手動二重 unmount で destroy が二重呼びされない
    // (実際の二重 unmount は RTL で再現困難だが、cleanup chain の健全性を確認)
    const d: [Float64Array, Float64Array] = [
      new Float64Array([0, 1]),
      new Float64Array([10, 20]),
    ];
    const opts = { width: 100, height: 100, series: [{}, { label: "A" }] };
    const { unmount } = render(<UPlotChart options={opts} data={d} />);
    unmount();
    expect(destroy).toHaveBeenCalledTimes(1);
    // 2 回目の unmount を試みる (= Reactの unmount は 1 回しか呼べないが
    // cleanup は 1 回だけ走ることを確認)
    // 既に unmount 済みなので再度呼んでも何も起きない (エラーにならない)
    expect(() => unmount()).not.toThrow();
    // destroy は追加で呼ばれない
    expect(destroy).toHaveBeenCalledTimes(1);
  });
});
