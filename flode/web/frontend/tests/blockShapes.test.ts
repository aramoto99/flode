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

  it("returns mirrored pentagon tags for Goto (trapezoid-l) / From (trapezoid-r)", () => {
    // v0.53.7: ユーザー指摘「切り込みの方向が左右逆」で確定 — Goto = 左辺が
    // 左向きに尖る (From の左右鏡像)、From = 右辺尖り
    const goto = getBlockShape("flode.blocks.routing.Goto");
    const from = getBlockShape("flode.blocks.routing.From");
    expect(goto.kind).toBe("trapezoid-l");
    expect(from.kind).toBe("trapezoid-r");
    // 同じサイズ (= UI の統一感)、v0.47.0: タグ系は通常ブロックより一段小さい 72×28
    expect(goto.width).toBe(72);
    expect(goto.height).toBe(28);
    expect(from.width).toBe(72);
    expect(from.height).toBe(28);
  });

  it("returns stadium (capsule) for Inport / Outport (v0.46.2, de facto shape)", () => {
    const inport = getBlockShape("flode.subsystems.ports.Inport");
    const outport = getBlockShape("flode.subsystems.ports.Outport");
    expect(inport.kind).toBe("stadium");
    expect(outport.kind).toBe("stadium");
    // カプセルは rx = h/2 前提なので幅 >= 高さ
    expect(inport.width).toBeGreaterThanOrEqual(inport.height);
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
