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
  "pyflw.blocks.sources.Constant",
  "pyflw.blocks.sources.Step",
  "pyflw.blocks.sources.Sine",
  "pyflw.blocks.sources.Ramp",
  "pyflw.blocks.sources.Clock",
  "pyflw.blocks.sources.PulseGenerator",
  "pyflw.blocks.mathops.Gain",
  "pyflw.blocks.mathops.Sum",
  "pyflw.blocks.mathops.Product",
  "pyflw.blocks.mathops.Saturation",
  "pyflw.blocks.mathops.Abs",
  "pyflw.blocks.mathops.Sign",
  "pyflw.blocks.mathops.MinMax",
  "pyflw.blocks.mathops.Divide",
  "pyflw.blocks.continuous.Integrator",
  "pyflw.blocks.continuous.Derivative",
  "pyflw.blocks.continuous.TransferFunction",
  "pyflw.blocks.continuous.StateSpace",
  "pyflw.blocks.continuous.MimoTransferFunction",
  "pyflw.blocks.discrete.UnitDelay",
  "pyflw.blocks.discrete.DiscreteIntegrator",
  "pyflw.blocks.discrete.ZeroOrderHoldDirect",
  "pyflw.blocks.discrete.RateTransition",
  "pyflw.blocks.discrete.DiscreteStateSpace",
  "pyflw.blocks.discrete.DiscreteTransferFunction",
  "pyflw.blocks.logic.RelationalOperator",
  "pyflw.blocks.logic.LogicalOperator",
  "pyflw.blocks.routing.Switch",
  "pyflw.blocks.routing.Mux",
  "pyflw.blocks.routing.Demux",
  "pyflw.blocks.sinks.Scope",
  "pyflw.blocks.sinks.Display",
  "pyflw.blocks.sinks.XYGraph",
  "pyflw.blocks.sinks.Terminator",
  "pyflw.subsystems.subsystem.Subsystem",
  "pyflw.subsystems.ports.Inport",
  "pyflw.subsystems.ports.Outport",
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
