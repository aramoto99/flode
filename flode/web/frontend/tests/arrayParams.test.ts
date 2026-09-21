// ADR-0079 Stage 3 (v0.64.0): Inspector の数値欄で配列リテラルを受理する表と parser。

import { describe, expect, it } from "vitest";

import {
  ARRAY_CAPABLE_PARAMS,
  isArrayCapableParam,
  parseArrayLiteral,
} from "../src/lib/arrayParams";
import { formatValue } from "../src/lib/blockFormatting";

describe("isArrayCapableParam", () => {
  it("Constant.value / Gain.k / vector-state x0 are array capable", () => {
    expect(isArrayCapableParam("flode.blocks.sources.Constant", "value")).toBe(true);
    expect(isArrayCapableParam("flode.blocks.mathops.Gain", "k")).toBe(true);
    expect(isArrayCapableParam("flode.blocks.continuous.Integrator", "x0")).toBe(true);
    expect(isArrayCapableParam("flode.blocks.discrete.UnitDelay", "x0")).toBe(true);
  });

  it("other params / blocks are not", () => {
    expect(isArrayCapableParam("flode.blocks.sources.Constant", "dtype")).toBe(false);
    expect(isArrayCapableParam("flode.blocks.sources.Step", "step_time")).toBe(false);
    expect(isArrayCapableParam("flode.blocks.mathops.Gain", "multiplication")).toBe(false);
  });

  it("table lists exactly the 7 vector-state classes plus Constant and Gain", () => {
    expect(Object.keys(ARRAY_CAPABLE_PARAMS)).toHaveLength(9);
  });
});

describe("parseArrayLiteral", () => {
  it("returns undefined for non-array text", () => {
    expect(parseArrayLiteral("2.5")).toBeUndefined();
    expect(parseArrayLiteral("")).toBeUndefined();
  });

  it("parses 1-D and 2-D numeric arrays", () => {
    expect(parseArrayLiteral("[1, 2, 3]")).toEqual([1, 2, 3]);
    expect(parseArrayLiteral(" [[1, 0], [0, 1]] ")).toEqual([
      [1, 0],
      [0, 1],
    ]);
  });

  it("returns null for invalid or ragged arrays", () => {
    expect(parseArrayLiteral("[1, 2")).toBeNull();
    expect(parseArrayLiteral("[1, \"a\"]")).toBeNull();
    expect(parseArrayLiteral("[[1, 2], [3]]")).toBeNull();
  });
});

describe("formatValue", () => {
  it("formats scalars via formatNumber", () => {
    expect(formatValue(2)).toBe("2");
    expect(formatValue(0.5)).toBe("0.5");
  });

  it("formats short vectors inline and long ones by length", () => {
    expect(formatValue([1, 2, 3])).toBe("[1, 2, 3]");
    expect(formatValue([1, 2, 3, 4, 5])).toBe("[…](5)");
    expect(formatValue([])).toBe("[]");
  });

  it("formats matrices by dimensions", () => {
    expect(formatValue([[1, 2], [3, 4]])).toBe("[2×2]");
    expect(formatValue([[[1]]])).toBe("[1×1×1]");
  });
});
