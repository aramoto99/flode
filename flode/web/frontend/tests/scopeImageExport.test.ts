// scopeImageExport の純粋部 (deriveLegend) をテスト。
// canvas 合成 / clipboard は jsdom の canvas 2d 非対応のため手動確認に委ねる。

import { describe, expect, it, vi } from "vitest";

// uPlot は module 評価時に matchMedia を使う (jsdom 未実装)。import より前に stub を入れる
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

import { buildOptions } from "../src/components/ScopeView";
import { deriveLegend } from "../src/lib/scopeImageExport";
import { FALLBACK_COLORS } from "../src/lib/scopeSettings";
import { defaultScopeColumnLabels } from "../src/lib/signalDisplayNames";

describe("deriveLegend", () => {
  it("uses scopeId as label for a single signal", () => {
    const legend = deriveLegend(defaultScopeColumnLabels("Scope_0", 1), undefined);
    expect(legend).toHaveLength(1);
    expect(legend[0]!.label).toBe("Scope_0");
    expect(legend[0]!.color).toBe(FALLBACK_COLORS[0]);
  });

  it("uses scopeId[i] labels for multiple signals", () => {
    const legend = deriveLegend(defaultScopeColumnLabels("Scope_1", 3), undefined);
    expect(legend.map((e) => e.label)).toEqual([
      "Scope_1[0]",
      "Scope_1[1]",
      "Scope_1[2]",
    ]);
    expect(legend.map((e) => e.color)).toEqual([
      FALLBACK_COLORS[0],
      FALLBACK_COLORS[1],
      FALLBACK_COLORS[2],
    ]);
  });

  it("honors per-signal explicit colors", () => {
    const legend = deriveLegend(["a", "b"], { "1": { color: "#abcdef" } });
    expect(legend[0]!.color).toBe(FALLBACK_COLORS[0]); // 未指定は fallback
    expect(legend[1]!.color).toBe("#abcdef"); // 明示色
  });

  it("returns empty array for zero signals", () => {
    expect(deriveLegend([], undefined)).toEqual([]);
  });

  it("uses the same labels as the uPlot series (ADR-0087)", () => {
    const labels = ["speed", "force[0]", "force[1]"];
    const series = buildOptions("S", 3, {}, undefined, labels).series.slice(1);
    expect(series.map((s) => s.label)).toEqual(deriveLegend(labels, undefined).map((e) => e.label));
  });

  it("falls back to default labels when the label count does not match", () => {
    const series = buildOptions("S", 2, {}, undefined, ["only-one"]).series.slice(1);
    expect(series.map((s) => s.label)).toEqual(["S[0]", "S[1]"]);
  });
});
