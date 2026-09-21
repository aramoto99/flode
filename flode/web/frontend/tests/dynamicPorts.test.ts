// dynamicPorts.ts の port count 算出ルールが Python 側 (flode/blocks/*) の
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
      "flode.blocks.mathops.Sum",
      { signs: "+++--" },
      META(2, 1),
    );
    expect(r).toEqual({ nInputs: 5, nOutputs: 1 });
  });

  it("Sum without signs falls back to default", () => {
    const r = resolvePortCounts(
      "flode.blocks.mathops.Sum",
      {},
      META(2, 1),
    );
    expect(r.nInputs).toBe(2);
  });

  it("Product: n_inputs param (NOT signs)", () => {
    const r = resolvePortCounts(
      "flode.blocks.mathops.Product",
      { n_inputs: 4 },
      META(2, 1),
    );
    expect(r.nInputs).toBe(4);
  });

  it("Divide: signs length controls n_inputs", () => {
    const r = resolvePortCounts(
      "flode.blocks.mathops.Divide",
      { signs: "*//*/" },
      META(2, 1),
    );
    expect(r.nInputs).toBe(5);
  });

  it("LogicalOperator: n_inputs param", () => {
    const r = resolvePortCounts(
      "flode.blocks.logic.LogicalOperator",
      { operator: "AND", n_inputs: 4 },
      META(2, 1),
    );
    expect(r.nInputs).toBe(4);
  });

  it("ADR-0079 D-9: StateSpace family is 1 vector port in / 1 out regardless of B / C", () => {
    // v0.64.0: m = 3 / p = 1 でもポートは 1 本ずつ (shape (3,) は backend が宣言)
    const ss = resolvePortCounts(
      "flode.blocks.continuous.StateSpace",
      {
        A: [[0, 1], [-1, 0]],
        B: [[1, 0, 0], [0, 1, 0]],
        C: [[1, 0]],
        D: [[0, 0, 0]],
      },
      META(1, 1),
    );
    expect(ss).toEqual({ nInputs: 1, nOutputs: 1 });
    const mimo = resolvePortCounts(
      "flode.blocks.continuous.MimoTransferFunction",
      { numerators: [[[1.0], [0.5]], [[0.3], [1.0]]], denominator: [1.0, 1.0] },
      META(1, 1),
    );
    expect(mimo).toEqual({ nInputs: 1, nOutputs: 1 });
    const dss = resolvePortCounts(
      "flode.blocks.discrete.DiscreteStateSpace",
      { A: [[0]], B: [[1, 1]], C: [[1], [1]], D: [[0, 0], [0, 0]], sample_time: 0.1 },
      META(1, 1),
    );
    expect(dss).toEqual({ nInputs: 1, nOutputs: 1 });
  });

  it("Mux: n controls n_inputs and (n,) output shape implicitly", () => {
    const r = resolvePortCounts(
      "flode.blocks.routing.Mux",
      { n: 4 },
      META(2, 1),
    );
    expect(r).toEqual({ nInputs: 4, nOutputs: 1 });
  });

  it("Demux: n controls n_outputs", () => {
    const r = resolvePortCounts(
      "flode.blocks.routing.Demux",
      { n: 5 },
      META(1, 2),
    );
    expect(r).toEqual({ nInputs: 1, nOutputs: 5 });
  });

  it("Scope / Display / Terminator: n_inputs", () => {
    expect(
      resolvePortCounts(
        "flode.blocks.sinks.Scope",
        { n_inputs: 3 },
        META(1, 0),
      ),
    ).toEqual({ nInputs: 3, nOutputs: 0 });
    expect(
      resolvePortCounts(
        "flode.blocks.sinks.Display",
        { n_inputs: 2 },
        META(1, 0),
      ),
    ).toEqual({ nInputs: 2, nOutputs: 0 });
    expect(
      resolvePortCounts(
        "flode.blocks.sinks.Terminator",
        { n_inputs: 4 },
        META(1, 0),
      ),
    ).toEqual({ nInputs: 4, nOutputs: 0 });
  });

  it("Subsystem: n_inputs/n_outputs derived from inner Inport/Outport (ADR-0039)", () => {
    const r = resolvePortCounts(
      "flode.subsystems.subsystem.Subsystem",
      {
        blocks: [
          { id: "in0", type: "flode.subsystems.ports.Inport", params: { port_idx: 0 } },
          { id: "in1", type: "flode.subsystems.ports.Inport", params: { port_idx: 1 } },
          { id: "in2", type: "flode.subsystems.ports.Inport", params: { port_idx: 2 } },
          { id: "out0", type: "flode.subsystems.ports.Outport", params: { port_idx: 0 } },
          { id: "out1", type: "flode.subsystems.ports.Outport", params: { port_idx: 1 } },
        ],
      },
      META(1, 1),
    );
    expect(r).toEqual({ nInputs: 3, nOutputs: 2 });
  });

  it("Subsystem + internal Trigger: n_inputs += 1 (ADR-0058)", () => {
    const r = resolvePortCounts(
      "flode.subsystems.subsystem.Subsystem",
      {
        blocks: [
          { id: "in0", type: "flode.subsystems.ports.Inport", params: { port_idx: 0 } },
          { id: "out0", type: "flode.subsystems.ports.Outport", params: { port_idx: 0 } },
          {
            id: "trig",
            type: "flode.subsystems.control_blocks.Trigger",
            params: { trigger_type: "rising" },
          },
        ],
      },
      META(1, 1),
    );
    expect(r).toEqual({ nInputs: 2, nOutputs: 1 });
  });

  it("Subsystem + internal Enable: n_inputs += 1 (ADR-0058)", () => {
    const r = resolvePortCounts(
      "flode.subsystems.subsystem.Subsystem",
      {
        blocks: [
          { id: "in0", type: "flode.subsystems.ports.Inport", params: { port_idx: 0 } },
          { id: "out0", type: "flode.subsystems.ports.Outport", params: { port_idx: 0 } },
          {
            id: "en",
            type: "flode.subsystems.control_blocks.Enable",
            params: {
              states_when_enabling: "held",
              outputs_when_disabled: "held",
            },
          },
        ],
      },
      META(1, 1),
    );
    expect(r).toEqual({ nInputs: 2, nOutputs: 1 });
  });

  it("Subsystem + Trigger + Enable: n_inputs += 2 (ADR-0058)", () => {
    const r = resolvePortCounts(
      "flode.subsystems.subsystem.Subsystem",
      {
        blocks: [
          { id: "in0", type: "flode.subsystems.ports.Inport", params: { port_idx: 0 } },
          { id: "in1", type: "flode.subsystems.ports.Inport", params: { port_idx: 1 } },
          { id: "out0", type: "flode.subsystems.ports.Outport", params: { port_idx: 0 } },
          {
            id: "en",
            type: "flode.subsystems.control_blocks.Enable",
            params: {
              states_when_enabling: "held",
              outputs_when_disabled: "held",
            },
          },
          {
            id: "trig",
            type: "flode.subsystems.control_blocks.Trigger",
            params: { trigger_type: "rising" },
          },
        ],
      },
      META(1, 1),
    );
    expect(r).toEqual({ nInputs: 4, nOutputs: 1 });
  });

  it("MinMax: n_inputs", () => {
    const r = resolvePortCounts(
      "flode.blocks.mathops.MinMax",
      { n_inputs: 5 },
      META(2, 1),
    );
    expect(r.nInputs).toBe(5);
  });

  it("Static blocks fall back to registry default (Gain)", () => {
    const r = resolvePortCounts(
      "flode.blocks.mathops.Gain",
      { k: 2.0 },
      META(1, 1),
    );
    expect(r).toEqual({ nInputs: 1, nOutputs: 1 });
  });

  it("invalid n (0 or negative) falls back to default", () => {
    expect(
      resolvePortCounts(
        "flode.blocks.routing.Mux",
        { n: 0 },
        META(2, 1),
      ).nInputs,
    ).toBe(2);
    expect(
      resolvePortCounts(
        "flode.blocks.routing.Mux",
        { n: -1 },
        META(2, 1),
      ).nInputs,
    ).toBe(2);
  });

  it("non-int n is truncated", () => {
    expect(
      resolvePortCounts(
        "flode.blocks.routing.Mux",
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
      "flode.blocks.mathops.Sum",
      "flode.blocks.mathops.Product",
      "flode.blocks.mathops.Divide",
      "flode.blocks.mathops.MinMax",
      "flode.blocks.logic.LogicalOperator",
      "flode.blocks.routing.Mux",
      "flode.blocks.routing.Demux",
      "flode.blocks.sinks.Scope",
      "flode.blocks.sinks.Display",
      "flode.blocks.sinks.Terminator",
      "flode.subsystems.subsystem.Subsystem",
    ];
    for (const t of dynTypes) {
      expect(hasDynamicPorts(t)).toBe(true);
    }
  });

  it("returns false for static blocks", () => {
    expect(hasDynamicPorts("flode.blocks.mathops.Gain")).toBe(false);
    expect(hasDynamicPorts("flode.blocks.sources.Constant")).toBe(false);
    expect(hasDynamicPorts("flode.blocks.continuous.Integrator")).toBe(false);
    // ADR-0079 D-9 (v0.64.0): StateSpace 系は 1 in / 1 out 固定になった
    expect(hasDynamicPorts("flode.blocks.continuous.StateSpace")).toBe(false);
    expect(hasDynamicPorts("flode.blocks.discrete.DiscreteStateSpace")).toBe(false);
    expect(hasDynamicPorts("flode.blocks.continuous.MimoTransferFunction")).toBe(false);
  });
});
