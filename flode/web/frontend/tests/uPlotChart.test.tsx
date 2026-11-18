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
const setScale = vi.fn();
const posToVal = vi.fn((pos: number, axis: string) => {
  // テスト用 stub: data 座標 ≒ pixel 座標 / 10 を返す (= 簡易な変換)
  void axis;
  return pos / 10;
});
const ctorCalls: Array<{ opts: unknown; data: unknown; root: unknown }> = [];

vi.mock("uplot", () => {
  const ctor = vi.fn(function (
    this: {
      setData: typeof setData;
      setSize: typeof setSize;
      destroy: typeof destroy;
      setScale: typeof setScale;
      posToVal: typeof posToVal;
      scales: Record<string, { min: number; max: number }>;
    },
    opts: unknown,
    data: unknown,
    root: unknown,
  ) {
    ctorCalls.push({ opts, data, root });
    this.setData = setData;
    this.setSize = setSize;
    this.destroy = destroy;
    this.setScale = setScale;
    this.posToVal = posToVal;
    // テスト用 default scales: x [0,10], y [0,100]
    this.scales = { x: { min: 0, max: 10 }, y: { min: 0, max: 100 } };
  });
  return { default: ctor };
});

import { UPlotChart } from "../src/components/UPlotChart";

/** 直近に作られた uPlot の root (= プロット領域。wheel / pan の受け口)。 */
function plotRootOf(container: HTMLElement): HTMLElement {
  const root = ctorCalls[ctorCalls.length - 1]!.root as HTMLElement;
  expect(container.contains(root)).toBe(true);
  return root;
}

beforeEach(() => {
  setData.mockClear();
  setSize.mockClear();
  destroy.mockClear();
  setScale.mockClear();
  posToVal.mockClear();
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

describe("UPlotChart: 凡例はプロット領域の外 (同じ枠内) に置く", () => {
  // uPlot は凡例 table を root (= setSize で枠いっぱいにした領域) の下に足すので、
  // そのままだと凡例が枠の外にはみ出して見えなかった。凡例は legend.mount で
  // プロット領域の兄弟要素に移し、プロット領域は残りの寸法だけを使う。
  const d: [Float64Array, Float64Array] = [
    new Float64Array([0, 1]),
    new Float64Array([10, 20]),
  ];
  const opts = { width: 100, height: 100, series: [{}, { label: "A" }] };

  function mountLegend(): { legendTable: HTMLElement; plotRoot: HTMLElement } {
    const { opts: passed, root } = ctorCalls[ctorCalls.length - 1]! as {
      opts: { legend?: { mount?: (u: unknown, el: HTMLElement) => void } };
      root: HTMLElement;
    };
    const legendTable = document.createElement("table");
    passed.legend?.mount?.({}, legendTable);
    return { legendTable, plotRoot: root };
  }

  it.each([
    ["top", "flex-col"],
    ["bottom", "flex-col-reverse"],
    ["right", "flex-row-reverse"],
  ] as const)("legend=%s: 凡例はプロット領域の兄弟 (%s)", (placement, dirClass) => {
    const { container } = render(
      <UPlotChart options={opts} data={d} legend={placement} />,
    );
    const { legendTable, plotRoot } = mountLegend();
    expect(plotRoot.contains(legendTable)).toBe(false);
    const legendHost = legendTable.parentElement!;
    expect(legendHost.parentElement).toBe(plotRoot.parentElement);
    // 先頭の子が凡例、次がプロット領域 (並びの向きはクラスで決める)
    expect(legendHost.nextElementSibling).toBe(plotRoot);
    expect(plotRoot.parentElement!.className).toContain(dirClass);
    expect(container.firstChild!.contains(legendTable)).toBe(true);
  });

  it("options を作り直しても凡例は 1 つだけ (古い凡例は destroy で消える)", () => {
    // 実 uPlot の destroy() は mount 先へ移した凡例も remove する (1.6.32)。
    // モックでもそれを再現し、置き場が使い回されて凡例が重ならないことを見る。
    const mounted: HTMLElement[] = [];
    destroy.mockImplementation(() => mounted.shift()?.remove());
    const { rerender } = render(<UPlotChart options={opts} data={d} legend="top" />);
    mounted.push(mountLegend().legendTable);
    rerender(<UPlotChart options={{ ...opts }} data={d} legend="top" />);
    const { legendTable } = mountLegend();
    mounted.push(legendTable);
    expect(legendTable.parentElement!.children).toHaveLength(1);
    destroy.mockReset();
  });

  it("凡例の上のホイールではズームしない (凡例のスクロールに使う)", () => {
    render(<UPlotChart options={opts} data={d} legend="top" />);
    const { legendTable } = mountLegend();
    const ev = new WheelEvent("wheel", { bubbles: true, cancelable: true, deltaY: -100 });
    legendTable.dispatchEvent(ev);
    expect(setScale).not.toHaveBeenCalled();
    expect(ev.defaultPrevented).toBe(false);
  });

  it("呼び出し側の legend 設定 (show / live) はそのまま渡す", () => {
    const withLegend = { ...opts, legend: { show: true, live: false } };
    render(<UPlotChart options={withLegend} data={d} legend="top" />);
    const passed = ctorCalls[0]!.opts as { legend: { show: boolean; live: boolean } };
    expect(passed.legend.show).toBe(true);
    expect(passed.legend.live).toBe(false);
  });
});

describe("UPlotChart: wheel zoom (ADR-0044 §論点 7)", () => {
  function dispatchWheel(
    el: HTMLElement,
    init: Partial<WheelEventInit & { ctrlKey: boolean; shiftKey: boolean }>,
  ): WheelEvent {
    // jsdom の WheelEvent は preventDefault を自前で持つ。cancelable: true で
    // デフォルト挙動キャンセル可能にする。
    const ev = new WheelEvent("wheel", {
      bubbles: true,
      cancelable: true,
      deltaY: init.deltaY ?? 100,
      clientX: init.clientX ?? 50,
      clientY: init.clientY ?? 50,
      ctrlKey: init.ctrlKey ?? false,
      shiftKey: init.shiftKey ?? false,
    });
    el.dispatchEvent(ev);
    return ev;
  }

  it("zooms in X axis on wheel up (negative deltaY)", () => {
    const opts = { width: 400, height: 200, series: [{}, { label: "A" }] };
    const data: [Float64Array, Float64Array] = [
      new Float64Array([0, 1, 2]),
      new Float64Array([10, 20, 30]),
    ];
    const { container } = render(<UPlotChart options={opts} data={data} />);
    const div = plotRootOf(container);
    dispatchWheel(div, { deltaY: -100, clientX: 50 });
    // setScale("x", {...}) が呼ばれる
    expect(setScale).toHaveBeenCalledTimes(1);
    const [axis, range] = setScale.mock.calls[0]!;
    expect(axis).toBe("x");
    // zoom in なので新 range は元 [0,10] より狭い
    expect((range as { max: number }).max - (range as { min: number }).min).toBeLessThan(10);
  });

  it("zooms out X axis on wheel down (positive deltaY)", () => {
    const opts = { width: 400, height: 200, series: [{}, { label: "A" }] };
    const data: [Float64Array, Float64Array] = [
      new Float64Array([0, 1]),
      new Float64Array([10, 20]),
    ];
    const { container } = render(<UPlotChart options={opts} data={data} />);
    const div = plotRootOf(container);
    dispatchWheel(div, { deltaY: 100, clientX: 50 });
    expect(setScale).toHaveBeenCalledTimes(1);
    const [, range] = setScale.mock.calls[0]!;
    // zoom out なので新 range は元 [0,10] より広い
    expect((range as { max: number }).max - (range as { min: number }).min).toBeGreaterThan(10);
  });

  it("targets Y axis when Shift held", () => {
    const opts = { width: 400, height: 200, series: [{}, { label: "A" }] };
    const data: [Float64Array, Float64Array] = [
      new Float64Array([0, 1]),
      new Float64Array([10, 20]),
    ];
    const { container } = render(<UPlotChart options={opts} data={data} />);
    const div = plotRootOf(container);
    dispatchWheel(div, { deltaY: -100, shiftKey: true });
    expect(setScale).toHaveBeenCalledTimes(1);
    expect(setScale.mock.calls[0]![0]).toBe("y");
  });

  it("passes through Ctrl+wheel (browser page zoom)", () => {
    const opts = { width: 400, height: 200, series: [{}, { label: "A" }] };
    const data: [Float64Array, Float64Array] = [
      new Float64Array([0, 1]),
      new Float64Array([10, 20]),
    ];
    const { container } = render(<UPlotChart options={opts} data={data} />);
    const div = plotRootOf(container);
    const ev = dispatchWheel(div, { deltaY: -100, ctrlKey: true });
    // setScale は呼ばれず、event の preventDefault も呼ばれない (= browser に譲る)
    expect(setScale).not.toHaveBeenCalled();
    expect(ev.defaultPrevented).toBe(false);
  });

  it("prevents page scroll while zooming (preventDefault)", () => {
    const opts = { width: 400, height: 200, series: [{}, { label: "A" }] };
    const data: [Float64Array, Float64Array] = [
      new Float64Array([0, 1]),
      new Float64Array([10, 20]),
    ];
    const { container } = render(<UPlotChart options={opts} data={data} />);
    const div = plotRootOf(container);
    const ev = dispatchWheel(div, { deltaY: 50 });
    expect(ev.defaultPrevented).toBe(true);
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
