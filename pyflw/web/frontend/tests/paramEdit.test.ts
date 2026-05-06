import { describe, expect, it } from "vitest";

import {
  findBlock,
  isEditableParam,
  parseNumericInput,
  updateBlockParam,
} from "../src/lib/paramEdit";
import type { FlwModel } from "../src/types/api";

const baseModel: FlwModel = {
  schema_version: "0.2",
  simulator: {
    t_end: 1.0,
    dt: 0.01,
    solver: "RK45",
    rtol: 1e-6,
    atol: 1e-9,
    dt_base: null,
  },
  blocks: [
    { id: "src", type: "pyflw.blocks.sources.Constant", params: { value: 1.0 } },
    { id: "g", type: "pyflw.blocks.mathops.Gain", params: { k: 2.0 } },
    {
      id: "sc",
      type: "pyflw.blocks.sinks.Scope",
      params: { n_inputs: 1, labels: ["in0"] },
    },
  ],
  connections: [],
};

describe("isEditableParam", () => {
  it("accepts finite numbers", () => {
    expect(isEditableParam(0)).toBe(true);
    expect(isEditableParam(-3.14)).toBe(true);
    expect(isEditableParam(1e10)).toBe(true);
  });

  it("rejects NaN, Infinity, and non-number types", () => {
    expect(isEditableParam(Number.NaN)).toBe(false);
    expect(isEditableParam(Number.POSITIVE_INFINITY)).toBe(false);
    expect(isEditableParam("1.0")).toBe(false);
    expect(isEditableParam(null)).toBe(false);
    expect(isEditableParam([1, 2, 3])).toBe(false);
    expect(isEditableParam({ value: 1 })).toBe(false);
    // boolean は typeof === "boolean" で除外。明示的にカバーする。
    expect(isEditableParam(true)).toBe(false);
    // BigInt は typeof === "bigint" で number でないため除外される。
    // pyflw の JSON モデルで BigInt が来る経路はないが、`unknown` 入力の
    // 安全性のため型ガードを保証する。
    expect(isEditableParam(BigInt(1))).toBe(false);
    expect(isEditableParam(undefined)).toBe(false);
  });
});

describe("parseNumericInput", () => {
  it("parses standard numeric strings", () => {
    expect(parseNumericInput("0")).toBe(0);
    expect(parseNumericInput("3.14")).toBe(3.14);
    expect(parseNumericInput("-2.5e3")).toBe(-2500);
    expect(parseNumericInput("  7  ")).toBe(7);
  });

  it("returns null for empty / non-numeric / NaN / Infinity input", () => {
    expect(parseNumericInput("")).toBeNull();
    expect(parseNumericInput("   ")).toBeNull();
    expect(parseNumericInput("abc")).toBeNull();
    expect(parseNumericInput("1.2.3")).toBeNull();
    expect(parseNumericInput("Infinity")).toBeNull();
    expect(parseNumericInput("-Infinity")).toBeNull();
    expect(parseNumericInput("NaN")).toBeNull();
  });
});

describe("findBlock", () => {
  it("returns the matching block", () => {
    const b = findBlock(baseModel, "g");
    expect(b?.id).toBe("g");
    expect(b?.params).toEqual({ k: 2.0 });
  });

  it("returns undefined for unknown id", () => {
    expect(findBlock(baseModel, "missing")).toBeUndefined();
  });
});

describe("updateBlockParam", () => {
  it("returns a new model with the target param replaced", () => {
    const next = updateBlockParam(baseModel, "g", "k", 5.0);
    expect(findBlock(next, "g")?.params).toEqual({ k: 5.0 });
  });

  it("does not mutate the input model or other blocks", () => {
    const before = JSON.stringify(baseModel);
    const next = updateBlockParam(baseModel, "g", "k", 99);
    expect(JSON.stringify(baseModel)).toBe(before);
    expect(findBlock(next, "src")?.params).toEqual({ value: 1.0 });
    expect(findBlock(next, "src")).toBe(findBlock(baseModel, "src"));
  });

  it("preserves untouched params on the target block", () => {
    const next = updateBlockParam(baseModel, "sc", "n_inputs", 2);
    expect(findBlock(next, "sc")?.params).toEqual({
      n_inputs: 2,
      labels: ["in0"],
    });
  });

  it("is a no-op (structurally) when the block id is not found", () => {
    const next = updateBlockParam(baseModel, "missing", "k", 0);
    expect(next.blocks).toEqual(baseModel.blocks);
  });
});
