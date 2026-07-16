// ADR-0042 §論点 3-A / §論点 5-A: ``parseTEnd`` / ``parseToolbarTEnd`` のテスト。

import { describe, expect, it } from "vitest";

import { parseTEnd, parseToolbarTEnd } from "../src/lib/timeUtil";

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

  it("rejects empty / NaN / negative / zero", () => {
    expect(parseToolbarTEnd("")).toBeNull();
    expect(parseToolbarTEnd("   ")).toBeNull();
    expect(parseToolbarTEnd("abc")).toBeNull();
    expect(parseToolbarTEnd("-1")).toBeNull();
    expect(parseToolbarTEnd("0")).toBeNull();
    expect(parseToolbarTEnd("NaN")).toBeNull();
  });
});
