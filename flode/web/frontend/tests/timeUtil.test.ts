// ADR-0042 §論点 3-A / §論点 5-A: ``parseTEnd`` / ``parseToolbarTEnd`` のテスト。

import { describe, expect, it } from "vitest";

import {
  formatTEndLabel,
  formatToolbarTEnd,
  parseTEnd,
  parseToolbarTEnd,
  UNBOUNDED_SYMBOL,
} from "../src/lib/timeUtil";

describe("parseTEnd (wire/store value)", () => {
  it("returns finite value for positive number", () => {
    expect(parseTEnd(10)).toEqual({ value: 10, isUnbounded: false });
    expect(parseTEnd(0.5)).toEqual({ value: 0.5, isUnbounded: false });
  });

  it("treats Number.POSITIVE_INFINITY as unbounded (defensive)", () => {
    const r = parseTEnd(Number.POSITIVE_INFINITY);
    expect(r.isUnbounded).toBe(true);
    expect(r.value).toBe(Number.POSITIVE_INFINITY);
  });

  it("treats 'inf' string as unbounded", () => {
    const r = parseTEnd("inf");
    expect(r.isUnbounded).toBe(true);
    expect(r.value).toBe(Number.POSITIVE_INFINITY);
  });
});

describe("parseToolbarTEnd (user input)", () => {
  it("accepts positive number string", () => {
    expect(parseToolbarTEnd("10")).toBe(10);
    expect(parseToolbarTEnd("0.5")).toBe(0.5);
    expect(parseToolbarTEnd("  100 ")).toBe(100);
  });

  it("accepts 'inf' (case-insensitive, with whitespace)", () => {
    expect(parseToolbarTEnd("inf")).toBe("inf");
    expect(parseToolbarTEnd("INF")).toBe("inf");
    expect(parseToolbarTEnd("  Inf  ")).toBe("inf");
  });

  it("rejects '+inf' / 'infinity' / unicode (= ADR-0042 §論点 5-A)", () => {
    expect(parseToolbarTEnd("+inf")).toBeNull();
    expect(parseToolbarTEnd("-inf")).toBeNull();
    expect(parseToolbarTEnd("infinity")).toBeNull();
    expect(parseToolbarTEnd("∞")).toBeNull();
  });

  it("treats empty / whitespace-only as 'inf' (= 空欄は終了時刻なし)", () => {
    expect(parseToolbarTEnd("")).toBe("inf");
    expect(parseToolbarTEnd("   ")).toBe("inf");
  });

  it("rejects NaN / negative / zero / garbage", () => {
    expect(parseToolbarTEnd("abc")).toBeNull();
    expect(parseToolbarTEnd("-1")).toBeNull();
    expect(parseToolbarTEnd("0")).toBeNull();
    expect(parseToolbarTEnd("NaN")).toBeNull();
  });
});

describe("formatToolbarTEnd (display in input)", () => {
  it("shows finite value as-is", () => {
    expect(formatToolbarTEnd(10)).toBe("10");
    expect(formatToolbarTEnd(0.5)).toBe("0.5");
  });

  it("shows unbounded as empty string (placeholder ∞ が見える)", () => {
    expect(formatToolbarTEnd("inf")).toBe("");
    expect(formatToolbarTEnd(Number.POSITIVE_INFINITY)).toBe("");
  });

  it("shows undefined (no model) as empty string", () => {
    expect(formatToolbarTEnd(undefined)).toBe("");
  });

  it("formatTEndLabel shows ∞ for unbounded (StatusBar)", () => {
    expect(formatTEndLabel("inf")).toBe(UNBOUNDED_SYMBOL);
    expect(formatTEndLabel(Number.POSITIVE_INFINITY)).toBe(UNBOUNDED_SYMBOL);
    expect(formatTEndLabel(10)).toBe("10");
  });

  it("round-trips with parseToolbarTEnd", () => {
    expect(parseToolbarTEnd(formatToolbarTEnd("inf"))).toBe("inf");
    expect(parseToolbarTEnd(formatToolbarTEnd(10))).toBe(10);
  });
});
