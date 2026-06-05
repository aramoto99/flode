// SPEC-0018 / ADR-0068 §A-1: 動的 n_inputs resolver の safe evaluator テスト。

import { describe, expect, it, vi } from "vitest";

import { resolveNInputs } from "../src/lib/registryResolver";

describe("resolveNInputs", () => {
  it("returns fallback when resolver is undefined", () => {
    expect(resolveNInputs(undefined, {}, 5)).toBe(5);
    expect(resolveNInputs(undefined, {})).toBe(0); // default fallback
  });

  it("evaluates len(params.<attr>) for valid array params", () => {
    const params = { breakpoints_axes: [[0, 1], [0, 1], [0, 1]] };
    expect(resolveNInputs("len(params.breakpoints_axes)", params)).toBe(3);
  });

  it("returns 0 when the attr is not an array", () => {
    const params = { breakpoints_axes: "not-array" };
    expect(resolveNInputs("len(params.breakpoints_axes)", params)).toBe(0);
  });

  it("returns 0 when the attr is missing", () => {
    expect(resolveNInputs("len(params.missing)", {})).toBe(0);
  });

  it("handles whitespace in the DSL", () => {
    const params = { breakpoints_axes: [[0, 1], [0, 1]] };
    expect(
      resolveNInputs("  len( params.breakpoints_axes ) ", params),
    ).toBe(2);
  });

  it("rejects non-DSL syntax and falls back (security)", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    // 任意 JS / eval パターンは reject
    expect(resolveNInputs("alert(1)", {}, 42)).toBe(42);
    expect(resolveNInputs("params.foo.bar", {}, 42)).toBe(42);
    expect(resolveNInputs("len(params.a) + 1", {}, 42)).toBe(42);
    expect(resolveNInputs("function() { return 10; }()", {}, 42)).toBe(42);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it("rejects attr names with non-identifier characters", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    // ドット / ブラケットは attr 名に許可しない
    expect(resolveNInputs("len(params.a.b)", {})).toBe(0); // a.b の閉じ括弧前で全パターン不一致
    expect(resolveNInputs("len(params.a[0])", {})).toBe(0);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});
