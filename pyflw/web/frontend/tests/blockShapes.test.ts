// ADR-0019 §(2): blockShapes.ts のテスト。Simulink 風の type→shape mapping。

import { describe, expect, it } from "vitest";

import {
  getBlockShape,
  isKnownShapeKind,
} from "../src/lib/blockShapes";

describe("blockShapes", () => {
  it("returns triangle-r for Gain", () => {
    expect(getBlockShape("pyflw.blocks.mathops.Gain").kind).toBe("triangle-r");
  });

  it("returns circle for Sum / Product (Divide became rect in v0.35.4)", () => {
    expect(getBlockShape("pyflw.blocks.mathops.Sum").kind).toBe("circle");
    expect(getBlockShape("pyflw.blocks.mathops.Product").kind).toBe("circle");
    // v0.35.4: Divide はユーザー要望で矩形に変更
    expect(getBlockShape("pyflw.blocks.mathops.Divide").kind).toBe("rect");
  });

  it("returns bar for Mux / Demux", () => {
    expect(getBlockShape("pyflw.blocks.routing.Mux").kind).toBe("bar");
    expect(getBlockShape("pyflw.blocks.routing.Demux").kind).toBe("bar");
  });

  it("returns trapezoid-r for Inport, trapezoid-l for Outport", () => {
    expect(getBlockShape("pyflw.subsystems.ports.Inport").kind).toBe("trapezoid-r");
    expect(getBlockShape("pyflw.subsystems.ports.Outport").kind).toBe("trapezoid-l");
  });

  it("returns rect-wide for TransferFunction / StateSpace family", () => {
    expect(getBlockShape("pyflw.blocks.continuous.TransferFunction").kind).toBe(
      "rect-wide",
    );
    expect(getBlockShape("pyflw.blocks.continuous.StateSpace").kind).toBe(
      "rect-wide",
    );
    expect(
      getBlockShape("pyflw.blocks.continuous.MimoTransferFunction").kind,
    ).toBe("rect-wide");
    expect(
      getBlockShape("pyflw.blocks.discrete.DiscreteTransferFunction").kind,
    ).toBe("rect-wide");
  });

  it("falls back to default rect for unknown type_path", () => {
    const s = getBlockShape("no.such.Block");
    expect(s.kind).toBe("rect");
    expect(s.width).toBeGreaterThan(0);
    expect(s.height).toBeGreaterThan(0);
  });

  it("returns sane positive dimensions for every shape", () => {
    const types = [
      "pyflw.blocks.sources.Constant",
      "pyflw.blocks.mathops.Gain",
      "pyflw.blocks.mathops.Sum",
      "pyflw.blocks.routing.Mux",
      "pyflw.subsystems.ports.Inport",
      "pyflw.subsystems.ports.Outport",
      "pyflw.blocks.continuous.TransferFunction",
    ];
    for (const t of types) {
      const s = getBlockShape(t);
      expect(s.width).toBeGreaterThan(0);
      expect(s.height).toBeGreaterThan(0);
      expect(isKnownShapeKind(s.kind)).toBe(true);
    }
  });
});
