// ADR-0019 §(6.1): port shape pre-validate ヘルパのテスト。

import { describe, expect, it } from "vitest";

import {
  formatShape,
  indexRegistry,
  shapeEquals,
  validatePortShapeConnection,
} from "../src/lib/portShapeValidate";
import type { BlockEntry, BlockMetadata } from "../src/types/api";

const META_GAIN: BlockMetadata = {
  type_path: "pyflw.blocks.mathops.Gain",
  display_name: "Gain",
  category: "mathops",
  icon: "math.gain",
  color: "#3b82f6",
  docstring_summary: "",
  params_spec: [],
  default_n_inputs: 1,
  default_n_outputs: 1,
  port_shapes_in_default: [[]],
  port_shapes_out_default: [[]],
  tags: ["sm_a"],
  is_container: false,
  mask_capable: false,
};

const META_MUX: BlockMetadata = {
  type_path: "pyflw.blocks.routing.Mux",
  display_name: "Mux",
  category: "routing",
  icon: "routing.mux",
  color: "#06b6d4",
  docstring_summary: "",
  params_spec: [],
  default_n_inputs: 2,
  default_n_outputs: 1,
  port_shapes_in_default: [[], []],
  port_shapes_out_default: [[2]],
  tags: ["sm_b"],
  is_container: false,
  mask_capable: false,
};

const META_DEMUX: BlockMetadata = {
  type_path: "pyflw.blocks.routing.Demux",
  display_name: "Demux",
  category: "routing",
  icon: "routing.demux",
  color: "#06b6d4",
  docstring_summary: "",
  params_spec: [],
  default_n_inputs: 1,
  default_n_outputs: 2,
  port_shapes_in_default: [[2]],
  port_shapes_out_default: [[], []],
  tags: ["sm_b"],
  is_container: false,
  mask_capable: false,
};

describe("shapeEquals", () => {
  it("identical scalars are equal", () => {
    expect(shapeEquals([], [])).toBe(true);
  });
  it("identical vectors are equal", () => {
    expect(shapeEquals([3], [3])).toBe(true);
  });
  it("different ranks differ", () => {
    expect(shapeEquals([], [3])).toBe(false);
  });
  it("different sizes differ", () => {
    expect(shapeEquals([2], [3])).toBe(false);
  });
});

describe("formatShape", () => {
  it("scalar prints as 'scalar ()'", () => {
    expect(formatShape([])).toBe("scalar ()");
  });
  it("rank-1 vector uses numpy-like trailing comma", () => {
    expect(formatShape([3])).toBe("(3,)");
  });
  it("rank-2 tuple has no trailing comma", () => {
    expect(formatShape([3, 4])).toBe("(3,4)");
  });
});

describe("validatePortShapeConnection", () => {
  const registry = indexRegistry([META_GAIN, META_MUX, META_DEMUX]);

  const gain1: BlockEntry = {
    id: "g1",
    type: "pyflw.blocks.mathops.Gain",
    params: { k: 2.0 },
  };
  const gain2: BlockEntry = {
    id: "g2",
    type: "pyflw.blocks.mathops.Gain",
    params: { k: 3.0 },
  };
  const mux: BlockEntry = {
    id: "m1",
    type: "pyflw.blocks.routing.Mux",
    params: { n: 2 },
  };
  const demux: BlockEntry = {
    id: "d1",
    type: "pyflw.blocks.routing.Demux",
    params: { n: 2 },
  };

  it("scalar → scalar OK", () => {
    expect(
      validatePortShapeConnection(gain1, 0, gain2, 0, registry).ok,
    ).toBe(true);
  });

  it("Mux out (vector) → Gain in (scalar) is rejected", () => {
    const r = validatePortShapeConnection(mux, 0, gain1, 0, registry);
    expect(r.ok).toBe(false);
    expect(r.reason).toContain("Port shape mismatch");
  });

  it("Mux out (vector) → Demux in (vector) OK", () => {
    expect(validatePortShapeConnection(mux, 0, demux, 0, registry).ok).toBe(true);
  });

  it("invalid src port index returns descriptive error", () => {
    const r = validatePortShapeConnection(gain1, 5, gain2, 0, registry);
    expect(r.ok).toBe(false);
    expect(r.reason).toContain("does not exist");
  });

  it("ADR-0039: connecting into a Subsystem with internal Inport succeeds (n_inputs derived)", () => {
    // 空 Subsystem に internal Inport(port_idx=0) が 1 つある状態で外側から
    // connect → registry default では n_inputs=0 で弾かれていたが、派生計算
    // (= getDefaultPortShapes の Subsystem branch) で通るはず
    const sub: BlockEntry = {
      id: "sub",
      type: "pyflw.subsystems.subsystem.Subsystem",
      params: {
        blocks: [
          { id: "in0", type: "pyflw.subsystems.ports.Inport", params: { port_idx: 0 } },
        ],
        connections: [],
      },
    };
    const META_SUB: BlockMetadata = {
      type_path: "pyflw.subsystems.subsystem.Subsystem",
      display_name: "Subsystem",
      category: "subsystems",
      icon: "container.subsystem",
      color: "#6366f1",
      docstring_summary: "",
      params_spec: [],
      default_n_inputs: 0,
      default_n_outputs: 0,
      port_shapes_in_default: [],
      port_shapes_out_default: [],
      tags: ["sm_a", "container"],
      is_container: true,
      mask_capable: true,
    };
    const subRegistry = indexRegistry([META_GAIN, META_SUB]);
    const r = validatePortShapeConnection(gain1, 0, sub, 0, subRegistry);
    expect(r.ok).toBe(true);
  });

  it("ADR-0036/0039: TriggeredSubsystem accepts trigger slot at the end", () => {
    // 内部 Inport 1 つ → 外側 n_inputs = 2 (= internal 1 + trigger 1)。
    // dst_idx=1 (trigger) への接続は scalar trigger なので OK。
    const tsub: BlockEntry = {
      id: "tsub",
      type: "pyflw.subsystems.triggered.TriggeredSubsystem",
      params: {
        trigger_mode: "rising",
        blocks: [
          { id: "in0", type: "pyflw.subsystems.ports.Inport", params: { port_idx: 0 } },
        ],
        connections: [],
      },
    };
    const META_TSUB: BlockMetadata = {
      type_path: "pyflw.subsystems.triggered.TriggeredSubsystem",
      display_name: "Triggered Subsystem",
      category: "subsystems",
      icon: "container.triggered",
      color: "#6366f1",
      docstring_summary: "",
      params_spec: [],
      default_n_inputs: 1,
      default_n_outputs: 0,
      port_shapes_in_default: [[]],
      port_shapes_out_default: [],
      tags: ["sm_a", "container"],
      is_container: true,
      mask_capable: true,
    };
    const tsubRegistry = indexRegistry([META_GAIN, META_TSUB]);
    // dst_idx=0 (internal Inport)
    expect(validatePortShapeConnection(gain1, 0, tsub, 0, tsubRegistry).ok).toBe(true);
    // dst_idx=1 (trigger slot、末尾固定)
    expect(validatePortShapeConnection(gain1, 0, tsub, 1, tsubRegistry).ok).toBe(true);
    // dst_idx=2 (= n_inputs を超える) は does not exist
    const oob = validatePortShapeConnection(gain1, 0, tsub, 2, tsubRegistry);
    expect(oob.ok).toBe(false);
    expect(oob.reason).toContain("does not exist");
  });

  it("invalid dst port index returns descriptive error", () => {
    const r = validatePortShapeConnection(gain1, 0, gain2, 5, registry);
    expect(r.ok).toBe(false);
    expect(r.reason).toContain("does not exist");
  });

  it("override shapes are honored over registry", () => {
    // override で gain.out=(3,) と仮定 → demux.in=(2,) との mismatch を検出
    const r = validatePortShapeConnection(
      gain1,
      0,
      demux,
      0,
      registry,
      { src: { in: [[]], out: [[3]] } },
    );
    expect(r.ok).toBe(false);
  });
});
