// scopeImageExport の純粋部 (deriveLegend) をテスト。
// canvas 合成 / clipboard は jsdom の canvas 2d 非対応のため手動確認に委ねる。

import { describe, expect, it } from "vitest";

import { deriveLegend } from "../src/lib/scopeImageExport";
import { FALLBACK_COLORS } from "../src/lib/scopeSettings";

describe("deriveLegend", () => {
  it("uses scopeId as label for a single signal", () => {
    const legend = deriveLegend("Scope_0", 1, undefined);
    expect(legend).toHaveLength(1);
    expect(legend[0]!.label).toBe("Scope_0");
    expect(legend[0]!.color).toBe(FALLBACK_COLORS[0]);
  });

  it("uses scopeId[i] labels for multiple signals", () => {
    const legend = deriveLegend("Scope_1", 3, undefined);
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
    const legend = deriveLegend("S", 2, { "1": { color: "#abcdef" } });
    expect(legend[0]!.color).toBe(FALLBACK_COLORS[0]); // 未指定は fallback
    expect(legend[1]!.color).toBe("#abcdef"); // 明示色
  });

  it("returns empty array for zero signals", () => {
    expect(deriveLegend("S", 0, undefined)).toEqual([]);
  });
});
