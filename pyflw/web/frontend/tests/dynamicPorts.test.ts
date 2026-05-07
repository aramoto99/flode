// dynamicPorts.ts の port count 算出ルールが Python 側 (pyflw/blocks/*) の
// __init__ ロジックと一致することを単体テストで担保する。

import { describe, expect, it } from "vitest";

import {
  hasDynamicPorts,
  resolvePortCounts,
} from "../src/lib/dynamicPorts";
import type { BlockMetadata } from "../src/types/api";

const META = (defaultIn: number, defaultOut: number): BlockMetadata => ({
  type_path: "x",
  display_name: "x",
  category: "x",
  icon: "x",
  color: "#000",
  docstring_summary: "",
  params_spec: [],
  default_n_inputs: defaultIn,
  default_n_outputs: defaultOut,
  port_shapes_in_default: [],
  port_shapes_out_default: [],
  tags: [],
  is_container: false,
  mask_capable: false,
});

describe("resolvePortCounts", () => {
  it("Sum: signs length = n_inputs", () => {
    const r = resolvePortCounts(
      "pyflw.blocks.mathops.Sum",
      { signs: "+++--" },
      META(2, 1),
    );
    expect(r).toEqual({ nInputs: 5, nOutputs: 1 });
  });

  it("Sum without signs falls back to default", () => {
    const r = resolvePortCounts(
      "pyflw.blocks.mathops.Sum",
      {},
      META(2, 1),
    );
    expect(r.nInputs).toBe(2);
  });

  it("Product: n_inputs param (NOT signs)", () => {
    const r = resolvePortCounts(
      "pyflw.blocks.mathops.Product",
      { n_inputs: 4 },
      META(2, 1),
    );
    expect(r.nInputs).toBe(4);
  });

  it("Divide: signs length controls n_inputs", () => {
    const r = resolvePortCounts(
      "pyflw.blocks.mathops.Divide",
      { signs: "*//*/" },
      META(2, 1),
    );
    expect(r.nInputs).toBe(5);
  });

  it("LogicalOperator: n_inputs param", () => {
    const r = resolvePortCounts(
      "pyflw.blocks.logic.LogicalOperator",
      { operator: "AND", n_inputs: 4 },
      META(2, 1),
    );
    expect(r.nInputs).toBe(4);
  });

  it("StateSpace: n_inputs from B.shape[1], n_outputs from C.shape[0]", () => {
    // 2-state, 3-input, 1-output
    const r = resolvePortCounts(
      "pyflw.blocks.continuous.StateSpace",
      {
        A: [[0, 1], [-1, 0]],
        B: [[1, 0, 0], [0, 1, 0]], // 2x3 → 3 inputs
        C: [[1, 0]], // 1x2 → 1 output
        D: [[0, 0, 0]],
      },
      META(1, 1),
    );
    expect(r).toEqual({ nInputs: 3, nOutputs: 1 });
  });

  it("MimoTransferFunction: 2x2 numerators → 2 in / 2 out", () => {
    const r = resolvePortCounts(
      "pyflw.blocks.continuous.MimoTransferFunction",
      {
        numerators: [
          [[1.0], [0.5]],
          [[0.3], [1.0]],
        ],
        denominator: [1.0, 1.0],
      },
      META(1, 1),
    );
    expect(r).toEqual({ nInputs: 2, nOutputs: 2 });
  });

  it("DiscreteStateSpace: same as StateSpace", () => {
    const r = resolvePortCounts(
      "pyflw.blocks.discrete.DiscreteStateSpace",
      {
        A: [[0]],
        B: [[1, 1]], // 1x2 → 2 inputs
        C: [[1], [1]], // 2x1 → 2 outputs
        D: [[0, 0], [0, 0]],
        sample_time: 0.1,
      },
      META(1, 1),
    );
    expect(r).toEqual({ nInputs: 2, nOutputs: 2 });
  });

  it("Mux: n controls n_inputs and (n,) output shape implicitly", () => {
    const r = resolvePortCounts(
      "pyflw.blocks.routing.Mux",
      { n: 4 },
      META(2, 1),
    );
    expect(r).toEqual({ nInputs: 4, nOutputs: 1 });
  });

  it("Demux: n controls n_outputs", () => {
    const r = resolvePortCounts(
      "pyflw.blocks.routing.Demux",
      { n: 5 },
      META(1, 2),
    );
    expect(r).toEqual({ nInputs: 1, nOutputs: 5 });
  });

  it("Scope / Display / Terminator: n_inputs", () => {
    expect(
      resolvePortCounts(
        "pyflw.blocks.sinks.Scope",
        { n_inputs: 3 },
        META(1, 0),
      ),
    ).toEqual({ nInputs: 3, nOutputs: 0 });
    expect(
      resolvePortCounts(
        "pyflw.blocks.sinks.Display",
        { n_inputs: 2 },
        META(1, 0),
      ),
    ).toEqual({ nInputs: 2, nOutputs: 0 });
    expect(
      resolvePortCounts(
        "pyflw.blocks.sinks.Terminator",
        { n_inputs: 4 },
        META(1, 0),
      ),
    ).toEqual({ nInputs: 4, nOutputs: 0 });
  });

  it("Subsystem: n_inputs and n_outputs", () => {
    const r = resolvePortCounts(
      "pyflw.subsystems.subsystem.Subsystem",
      { n_inputs: 3, n_outputs: 2 },
      META(1, 1),
    );
    expect(r).toEqual({ nInputs: 3, nOutputs: 2 });
  });

  it("MinMax: n_inputs", () => {
    const r = resolvePortCounts(
      "pyflw.blocks.mathops.MinMax",
      { n_inputs: 5 },
      META(2, 1),
    );
    expect(r.nInputs).toBe(5);
  });

  it("Static blocks fall back to registry default (Gain)", () => {
    const r = resolvePortCounts(
      "pyflw.blocks.mathops.Gain",
      { k: 2.0 },
      META(1, 1),
    );
    expect(r).toEqual({ nInputs: 1, nOutputs: 1 });
  });

  it("invalid n (0 or negative) falls back to default", () => {
    expect(
      resolvePortCounts(
        "pyflw.blocks.routing.Mux",
        { n: 0 },
        META(2, 1),
      ).nInputs,
    ).toBe(2);
    expect(
      resolvePortCounts(
        "pyflw.blocks.routing.Mux",
        { n: -1 },
        META(2, 1),
      ).nInputs,
    ).toBe(2);
  });

  it("non-int n is truncated", () => {
    expect(
      resolvePortCounts(
        "pyflw.blocks.routing.Mux",
        { n: 3.7 },
        META(2, 1),
      ).nInputs,
    ).toBe(3);
  });

  it("missing meta still works (fallback 1/1)", () => {
    const r = resolvePortCounts("unknown.Block", {}, undefined);
    expect(r).toEqual({ nInputs: 1, nOutputs: 1 });
  });
});

describe("hasDynamicPorts", () => {
  it("identifies known dynamic-port blocks", () => {
    const dynTypes = [
      "pyflw.blocks.mathops.Sum",
      "pyflw.blocks.mathops.Product",
      "pyflw.blocks.mathops.Divide",
      "pyflw.blocks.mathops.MinMax",
      "pyflw.blocks.logic.LogicalOperator",
      "pyflw.blocks.routing.Mux",
      "pyflw.blocks.routing.Demux",
      "pyflw.blocks.sinks.Scope",
      "pyflw.blocks.sinks.Display",
      "pyflw.blocks.sinks.Terminator",
      "pyflw.blocks.continuous.StateSpace",
      "pyflw.blocks.discrete.DiscreteStateSpace",
      "pyflw.blocks.continuous.MimoTransferFunction",
      "pyflw.subsystems.subsystem.Subsystem",
    ];
    for (const t of dynTypes) {
      expect(hasDynamicPorts(t)).toBe(true);
    }
  });

  it("returns false for static blocks", () => {
    expect(hasDynamicPorts("pyflw.blocks.mathops.Gain")).toBe(false);
    expect(hasDynamicPorts("pyflw.blocks.sources.Constant")).toBe(false);
    expect(hasDynamicPorts("pyflw.blocks.continuous.Integrator")).toBe(false);
  });
});
