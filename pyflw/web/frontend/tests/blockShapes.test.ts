// ADR-0019 §(2): blockShapes.ts のテスト。リファレンスツール風の type→shape mapping。

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

  it("returns rect for Goto / From / GotoTagVisibility (SPEC-0003 / ADR-0055)", () => {
    // tag ラベル中心の表示なので rect、横長 80x32
    const goto = getBlockShape("pyflw.blocks.routing.Goto");
    const from = getBlockShape("pyflw.blocks.routing.From");
    const vis = getBlockShape("pyflw.blocks.routing.GotoTagVisibility");
    expect(goto.kind).toBe("rect");
    expect(from.kind).toBe("rect");
    expect(vis.kind).toBe("rect");
    // 同じサイズ (= UI の統一感)、width / height とも 3 ブロック揃える
    expect(goto.width).toBe(80);
    expect(goto.height).toBe(32);
    expect(from.width).toBe(80);
    expect(from.height).toBe(32);
    expect(vis.width).toBe(80);
    expect(vis.height).toBe(32);
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
