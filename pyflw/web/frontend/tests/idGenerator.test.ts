// ADR-0019 §(4.4) §(9): block ID 自動採番のテスト。

import { describe, expect, it } from "vitest";

import {
  buildDefaultParams,
  generateUniqueId,
  typeNameFromPath,
} from "../src/lib/idGenerator";

describe("typeNameFromPath", () => {
  it("returns last dot segment", () => {
    expect(typeNameFromPath("pyflw.blocks.mathops.Gain")).toBe("Gain");
  });
  it("returns whole string for single segment", () => {
    expect(typeNameFromPath("Gain")).toBe("Gain");
  });
});

describe("generateUniqueId", () => {
  it("produces Gain_0 when no existing", () => {
    expect(generateUniqueId("pyflw.blocks.mathops.Gain", new Set())).toBe("Gain_0");
  });
  it("skips taken counters", () => {
    expect(
      generateUniqueId(
        "pyflw.blocks.mathops.Gain",
        new Set(["Gain_0", "Gain_1"]),
      ),
    ).toBe("Gain_2");
  });
  it("preserves type name from full path", () => {
    expect(generateUniqueId("pyflw.subsystems.ports.Inport", new Set())).toBe(
      "Inport_0",
    );
  });
  it("throws on 10000-deep collision (defensive)", () => {
    const taken = new Set<string>();
    for (let i = 0; i < 10000; i++) taken.add(`X_${i}`);
    expect(() => generateUniqueId("X", taken)).toThrow();
  });
});

describe("buildDefaultParams", () => {
  it("uses default when has_default=true", () => {
    expect(
      buildDefaultParams([
        { name: "k", type: "float", has_default: true, default: 1.0 },
      ]),
    ).toEqual({ k: 1.0 });
  });
  it("falls back to type-appropriate value when no default", () => {
    expect(
      buildDefaultParams([
        { name: "k", type: "float", has_default: false, default: null },
        { name: "name", type: "str", has_default: false, default: null },
        { name: "flag", type: "bool", has_default: false, default: null },
        { name: "items", type: "list[int]", has_default: false, default: null },
        { name: "opts", type: "dict", has_default: false, default: null },
      ]),
    ).toEqual({ k: 0, name: "", flag: false, items: [], opts: {} });
  });
});
