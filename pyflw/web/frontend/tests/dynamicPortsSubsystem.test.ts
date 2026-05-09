// ADR-0039: Subsystem の port count を内部 Inport / Outport から派生計算する
// `resolvePortCounts` の挙動を検証する。

import { describe, expect, it } from "vitest";

import {
  INPORT_TYPE,
  OUTPORT_TYPE,
  SUBSYSTEM_TYPE,
  TRIGGERED_SUBSYSTEM_TYPE,
} from "../src/lib/blockTypes";
import { resolvePortCounts } from "../src/lib/dynamicPorts";

describe("resolvePortCounts: Subsystem port derivation (ADR-0039)", () => {
  it("derives n_inputs/n_outputs from inner Inport/Outport blocks", () => {
    const params = {
      blocks: [
        { id: "in0", type: INPORT_TYPE, params: { port_idx: 0 } },
        { id: "in1", type: INPORT_TYPE, params: { port_idx: 1 } },
        { id: "out0", type: OUTPORT_TYPE, params: { port_idx: 0 } },
        { id: "g", type: "pyflw.blocks.mathops.Gain", params: { k: 2.0 } },
      ],
    };
    const counts = resolvePortCounts(SUBSYSTEM_TYPE, params, undefined);
    expect(counts.nInputs).toBe(2);
    expect(counts.nOutputs).toBe(1);
  });

  it("returns 0/0 for an empty Subsystem", () => {
    const counts = resolvePortCounts(SUBSYSTEM_TYPE, { blocks: [] }, undefined);
    expect(counts.nInputs).toBe(0);
    expect(counts.nOutputs).toBe(0);
  });

  it("falls back to registry default when params.blocks is missing", () => {
    // params に blocks フィールドがない (= drag prefetch 直後 等のレース) 場合
    const counts = resolvePortCounts(SUBSYSTEM_TYPE, {}, undefined);
    expect(counts.nInputs).toBe(1); // default_n_inputs default
    expect(counts.nOutputs).toBe(1);
  });
});

describe("resolvePortCounts: TriggeredSubsystem (= internal Inport count + 1 trigger)", () => {
  it("adds 1 to nInputs for trigger slot", () => {
    const params = {
      trigger_mode: "rising",
      blocks: [
        { id: "in0", type: INPORT_TYPE, params: { port_idx: 0 } },
        { id: "out0", type: OUTPORT_TYPE, params: { port_idx: 0 } },
      ],
    };
    const counts = resolvePortCounts(TRIGGERED_SUBSYSTEM_TYPE, params, undefined);
    expect(counts.nInputs).toBe(2); // internal 1 + trigger 1
    expect(counts.nOutputs).toBe(1);
  });

  it("returns 1/0 for an empty TriggeredSubsystem (= trigger only)", () => {
    const counts = resolvePortCounts(
      TRIGGERED_SUBSYSTEM_TYPE,
      { blocks: [] },
      undefined,
    );
    expect(counts.nInputs).toBe(1);
    expect(counts.nOutputs).toBe(0);
  });
});
