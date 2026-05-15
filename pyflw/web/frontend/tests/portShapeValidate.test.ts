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

  // ---------- v3.14.13 回帰テスト: dynamic-port count 反映 ----------
  // バグ: getDefaultPortShapes が registry 固定 default のみ返し、Scope の
  // n_inputs を 2 に上げても in[1] への接続が "does not exist (n_inputs=1)"
  // で拒否されていた。Scope / Sum / Product / Mux 等で同じ問題。
  describe("param-aware port count resolution (regression: dynamic-port blocks)", () => {
    const META_SCOPE: BlockMetadata = {
      type_path: "pyflw.blocks.sinks.Scope",
      display_name: "Scope",
      category: "sinks",
      icon: "sinks.scope",
      docstring_summary: "",
      params_spec: [],
      default_n_inputs: 1,
      default_n_outputs: 0,
      port_shapes_in_default: [[]],
      port_shapes_out_default: [],
      tags: ["sm_a"],
      is_container: false,
      mask_capable: false,
    };
    const META_SUM: BlockMetadata = {
      type_path: "pyflw.blocks.mathops.Sum",
      display_name: "Sum",
      category: "mathops",
      icon: "math.sum",
      docstring_summary: "",
      params_spec: [],
      default_n_inputs: 2,
      default_n_outputs: 1,
      port_shapes_in_default: [[], []],
      port_shapes_out_default: [[]],
      tags: ["sm_a"],
      is_container: false,
      mask_capable: false,
    };

    it("Scope with n_inputs=2 accepts connection to in[1] (= the reported bug)", () => {
      const scope: BlockEntry = {
        id: "Scope_0",
        type: "pyflw.blocks.sinks.Scope",
        params: { n_inputs: 2, buffer_mode: "ring", buffer_capacity: 100000 },
      };
      const reg = indexRegistry([META_GAIN, META_SCOPE]);
      const r = validatePortShapeConnection(gain1, 0, scope, 1, reg);
      expect(r.ok).toBe(true);
    });

    it("Scope with n_inputs=2 still rejects connection to non-existent in[2]", () => {
      const scope: BlockEntry = {
        id: "Scope_0",
        type: "pyflw.blocks.sinks.Scope",
        params: { n_inputs: 2 },
      };
      const reg = indexRegistry([META_GAIN, META_SCOPE]);
      const r = validatePortShapeConnection(gain1, 0, scope, 2, reg);
      expect(r.ok).toBe(false);
      expect(r.reason).toContain("does not exist");
      expect(r.reason).toContain("n_inputs=2");
    });

    it("Sum with signs='+++' accepts connection to in[2]", () => {
      const sum: BlockEntry = {
        id: "Sum_0",
        type: "pyflw.blocks.mathops.Sum",
        params: { signs: "+++" },
      };
      const reg = indexRegistry([META_GAIN, META_SUM]);
      const r = validatePortShapeConnection(gain1, 0, sum, 2, reg);
      expect(r.ok).toBe(true);
    });

    it("Mux with n=3 accepts connection to in[2] — output shape fix is out of scope (known bug)", () => {
      // 注: 本テストは入力 port count の修正のみ確認。Mux 出力 shape は
      // [[2]] (= META_MUX.port_shapes_out_default の固定値) のままで、n=3 のとき
      // 期待される [[3]] には更新されない (= 別バグとして scope 外)。
      const mux3: BlockEntry = {
        id: "Mux_0",
        type: "pyflw.blocks.routing.Mux",
        params: { n: 3 },
      };
      const reg = indexRegistry([META_GAIN, META_MUX]);
      const r = validatePortShapeConnection(gain1, 0, mux3, 2, reg);
      expect(r.ok).toBe(true);
    });

    it("Sum with signs='+' shrinks to 1 input, rejects in[1] (= count < defaults.length path)", () => {
      // resizeShapes の count < defaults.length 経路を担保: registry default は
      // n_inputs=2 だが signs="+" で 1 に縮む → in[1] は does not exist
      const sum: BlockEntry = {
        id: "Sum_0",
        type: "pyflw.blocks.mathops.Sum",
        params: { signs: "+" },
      };
      const reg = indexRegistry([META_GAIN, META_SUM]);
      const r = validatePortShapeConnection(gain1, 0, sum, 1, reg);
      expect(r.ok).toBe(false);
      expect(r.reason).toContain("does not exist");
      expect(r.reason).toContain("n_inputs=1");
    });

    it("default-param Scope (n_inputs=1) still rejects in[1] (= existing behavior preserved)", () => {
      const scope: BlockEntry = {
        id: "Scope_0",
        type: "pyflw.blocks.sinks.Scope",
        params: {},
      };
      const reg = indexRegistry([META_GAIN, META_SCOPE]);
      const r = validatePortShapeConnection(gain1, 0, scope, 1, reg);
      expect(r.ok).toBe(false);
      expect(r.reason).toContain("does not exist");
    });
  });
});
