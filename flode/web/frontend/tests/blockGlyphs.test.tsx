// ADR-0019 §(2) §Open Question 2: blockGlyphs.tsx の smoke test。
// 33 ブロック分の glyph 解決と fallback の挙動を確認する。
//
// 目的:
//   1. registry にある全 type_path で glyph component が解決される (= mapping 漏れ防止)
//   2. 未登録 type_path は fallback を返す
//   3. ブラウザに描画したとき SVG element が出る (= JSX が落ちない)

import { describe, expect, it } from "vitest";

import { BlockGlyph, getBlockGlyph } from "../src/lib/blockGlyphs";
import { renderToStaticMarkup } from "react-dom/server";

const KNOWN_TYPE_PATHS = [
  "flode.blocks.sources.Constant",
  "flode.blocks.sources.Step",
  "flode.blocks.sources.Sine",
  "flode.blocks.sources.Ramp",
  "flode.blocks.sources.Clock",
  "flode.blocks.sources.PulseGenerator",
  "flode.blocks.mathops.Gain",
  "flode.blocks.mathops.Sum",
  "flode.blocks.mathops.Product",
  "flode.blocks.mathops.Saturation",
  "flode.blocks.mathops.Abs",
  "flode.blocks.mathops.Sign",
  "flode.blocks.mathops.MinMax",
  "flode.blocks.mathops.Divide",
  "flode.blocks.continuous.Integrator",
  "flode.blocks.continuous.Derivative",
  "flode.blocks.continuous.TransferFunction",
  "flode.blocks.continuous.StateSpace",
  "flode.blocks.continuous.MimoTransferFunction",
  "flode.blocks.discrete.UnitDelay",
  "flode.blocks.discrete.DiscreteIntegrator",
  "flode.blocks.discrete.ZeroOrderHoldDirect",
  "flode.blocks.discrete.RateTransition",
  "flode.blocks.discrete.DiscreteStateSpace",
  "flode.blocks.discrete.DiscreteTransferFunction",
  "flode.blocks.logic.RelationalOperator",
  "flode.blocks.logic.LogicalOperator",
  "flode.blocks.routing.Switch",
  "flode.blocks.routing.Mux",
  "flode.blocks.routing.Demux",
  "flode.blocks.sinks.Scope",
  "flode.blocks.sinks.Display",
  "flode.blocks.sinks.XYGraph",
  "flode.blocks.sinks.Terminator",
  "flode.subsystems.subsystem.Subsystem",
  "flode.subsystems.ports.Inport",
  "flode.subsystems.ports.Outport",
];

describe("blockGlyphs", () => {
  it("resolves a glyph component for every known type_path", () => {
    for (const t of KNOWN_TYPE_PATHS) {
      const Glyph = getBlockGlyph(t);
      expect(Glyph).toBeDefined();
      expect(typeof Glyph).toBe("function");
    }
  });

  it("returns a fallback component for unknown type_path", () => {
    const Fallback = getBlockGlyph("no.such.Block");
    expect(Fallback).toBeDefined();
    const html = renderToStaticMarkup(<Fallback />);
    expect(html).toContain("<svg");
  });

  it("renders an <svg> element for every known glyph", () => {
    for (const t of KNOWN_TYPE_PATHS) {
      const html = renderToStaticMarkup(<BlockGlyph typePath={t} />);
      expect(html).toContain("<svg");
    }
  });
});
