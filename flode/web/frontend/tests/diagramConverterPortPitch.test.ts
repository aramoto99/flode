// v0.47.0: Subsystem (container) はポート脇ラベルのため 16px ピッチ、その他は 12px。
// registry 未取得 (meta undefined) 時は 12px にフォールバックし、後続の再レンダーで
// 自己修復する (= クラッシュしない) ことも固定する。

import { describe, expect, it } from "vitest";

import { modelToDiagram } from "../src/lib/diagramConverter";
import { INPORT_TYPE, SUBSYSTEM_TYPE } from "../src/lib/blockTypes";
import { getBlockShape } from "../src/lib/blockShapes";
import type { BlockMetadata, FlwModel } from "../src/types/api";

const N_PORTS = 6; // 6*16+8=104 > 64 (既定高) / 6*12+8=80 > 64 で分岐が観測できる

function subsystemModel(): FlwModel {
  return {
    schema_version: "0.10",
    simulator: { t_end: 1, dt: 0.01, solver: "RK45", rtol: 1e-3, atol: 1e-6, dt_base: null },
    blocks: [
      {
        id: "Sub_0",
        type: SUBSYSTEM_TYPE,
        params: {
          blocks: Array.from({ length: N_PORTS }, (_, i) => ({
            id: `Inport_${i}`,
            type: INPORT_TYPE,
            params: { port_idx: i },
          })),
          connections: [],
        },
      },
    ],
    connections: [],
    layout: {},
  };
}

function registryWith(isContainer: boolean): ReadonlyMap<string, BlockMetadata> {
  const meta = {
    type_path: SUBSYSTEM_TYPE,
    is_container: isContainer,
    n_inputs: 1,
    n_outputs: 1,
  } as unknown as BlockMetadata;
  return new Map([[SUBSYSTEM_TYPE, meta]]);
}

describe("modelToDiagram — ポートピッチ (v0.47.0)", () => {
  it("container (is_container=true) は 16px ピッチで高さを伸ばす", () => {
    const { nodes } = modelToDiagram(subsystemModel(), registryWith(true));
    expect(nodes[0]!.height).toBe(N_PORTS * 16 + 8);
  });

  it("非 container は従来の 12px ピッチ", () => {
    const { nodes } = modelToDiagram(subsystemModel(), registryWith(false));
    expect(nodes[0]!.height).toBe(N_PORTS * 12 + 8);
  });

  it("registry 未取得 (meta undefined) は 12px にフォールバックしクラッシュしない", () => {
    const { nodes } = modelToDiagram(subsystemModel(), undefined);
    expect(nodes[0]!.height).toBe(N_PORTS * 12 + 8);
  });

  it("ポートが少なければ既定高 (120×64) を維持する", () => {
    const model = subsystemModel();
    (model.blocks[0]!.params as { blocks: unknown[] }).blocks = [
      { id: "Inport_0", type: INPORT_TYPE, params: { port_idx: 0 } },
    ];
    const { nodes } = modelToDiagram(model, registryWith(true));
    const base = getBlockShape(SUBSYSTEM_TYPE);
    expect(nodes[0]!.width).toBe(base.width);
    expect(nodes[0]!.height).toBe(base.height);
  });

  it("layout.h が保存済みならピッチ計算より優先される (手動リサイズ尊重)", () => {
    const model = subsystemModel();
    model.layout = { Sub_0: { x: 0, y: 0, h: 70 } };
    const { nodes } = modelToDiagram(model, registryWith(true));
    expect(nodes[0]!.height).toBe(70);
  });
});
