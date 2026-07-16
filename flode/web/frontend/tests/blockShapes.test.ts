// ADR-0019 §(2): blockShapes.ts のテスト。リファレンスツール風の type→shape mapping。

import { describe, expect, it } from "vitest";

import {
  getBlockShape,
  isKnownShapeKind,
} from "../src/lib/blockShapes";

describe("blockShapes", () => {
  it("returns triangle-r for Gain", () => {
    expect(getBlockShape("flode.blocks.mathops.Gain").kind).toBe("triangle-r");
  });

  it("returns circle for Sum / Product (Divide became rect in v0.35.4)", () => {
    expect(getBlockShape("flode.blocks.mathops.Sum").kind).toBe("circle");
    expect(getBlockShape("flode.blocks.mathops.Product").kind).toBe("circle");
    // v0.35.4: Divide はユーザー要望で矩形に変更
    expect(getBlockShape("flode.blocks.mathops.Divide").kind).toBe("rect");
  });

  it("returns bar for Mux / Demux", () => {
    expect(getBlockShape("flode.blocks.routing.Mux").kind).toBe("bar");
    expect(getBlockShape("flode.blocks.routing.Demux").kind).toBe("bar");
  });

  it("returns rect for Goto / From (SPEC-0003 / ADR-0055)", () => {
    // tag ラベル中心の表示なので rect、横長 80x32
    // GotoTagVisibility は Amendment (2026-05-19) で Phase 2 送り
    const goto = getBlockShape("flode.blocks.routing.Goto");
    const from = getBlockShape("flode.blocks.routing.From");
    expect(goto.kind).toBe("rect");
    expect(from.kind).toBe("rect");
    // 同じサイズ (= UI の統一感)
    expect(goto.width).toBe(80);
    expect(goto.height).toBe(32);
    expect(from.width).toBe(80);
    expect(from.height).toBe(32);
  });

  it("returns trapezoid-r for Inport, trapezoid-l for Outport", () => {
    expect(getBlockShape("flode.subsystems.ports.Inport").kind).toBe("trapezoid-r");
    expect(getBlockShape("flode.subsystems.ports.Outport").kind).toBe("trapezoid-l");
  });

  it("returns rect-wide for TransferFunction / StateSpace family", () => {
    expect(getBlockShape("flode.blocks.continuous.TransferFunction").kind).toBe(
      "rect-wide",
    );
    expect(getBlockShape("flode.blocks.continuous.StateSpace").kind).toBe(
      "rect-wide",
    );
    expect(
      getBlockShape("flode.blocks.continuous.MimoTransferFunction").kind,
    ).toBe("rect-wide");
    expect(
      getBlockShape("flode.blocks.discrete.DiscreteTransferFunction").kind,
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
      "flode.blocks.sources.Constant",
      "flode.blocks.mathops.Gain",
      "flode.blocks.mathops.Sum",
      "flode.blocks.routing.Mux",
      "flode.subsystems.ports.Inport",
      "flode.subsystems.ports.Outport",
      "flode.blocks.continuous.TransferFunction",
    ];
    for (const t of types) {
      const s = getBlockShape(t);
      expect(s.width).toBeGreaterThan(0);
      expect(s.height).toBeGreaterThan(0);
      expect(isKnownShapeKind(s.kind)).toBe(true);
    }
  });
});
