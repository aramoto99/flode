// v0.15.0: Inspector の「左右反転」チェックボックスから呼ばれる toggleBlockFlipped
// が editingModel.layout に flipped フィールドを書き込み、modelToDiagram 経由で
// data.flipped が BlockNodeView に流れるところまでを end-to-end で検証する。

import { beforeEach, describe, expect, it } from "vitest";

import { modelToDiagram } from "../src/lib/diagramConverter";
import { SUBSYSTEM_TYPE } from "../src/lib/blockTypes";
import { resolveBlocksAtPath } from "../src/lib/pathResolver";
import { toggleBlockFlipped, useAppStore } from "../src/store/appStore";
import type { FlwModel } from "../src/types/api";

function makeModel(): FlwModel {
  return {
    schema_version: "0.8",
    simulator: {
      t_end: 1,
      dt: 0.01,
      solver: "RK45",
      rtol: 1e-6,
      atol: 1e-9,
      dt_base: null,
    },
    blocks: [
      { id: "g", type: "pyflw.blocks.mathops.Gain", params: { k: 2.0 } },
    ],
    connections: [],
    layout: { g: { x: 0, y: 0 } },
  };
}

beforeEach(() => {
  useAppStore.setState({
    editingModel: null,
    editingPath: [],
    dirty: false,
  });
});

describe("toggleBlockFlipped (v0.15.0 Flip Block)", () => {
  it("writes flipped: true to layout entry on first toggle", () => {
    useAppStore.setState({ editingModel: makeModel(), editingPath: [] });
    toggleBlockFlipped("g");
    const m = useAppStore.getState().editingModel!;
    expect(m.layout!["g"]!.flipped).toBe(true);
  });

  it("removes flipped key when toggling back to false", () => {
    useAppStore.setState({ editingModel: makeModel(), editingPath: [] });
    toggleBlockFlipped("g");
    toggleBlockFlipped("g");
    const m = useAppStore.getState().editingModel!;
    expect(m.layout!["g"]!.flipped).toBeUndefined();
  });

  it("preserves x/y/w/h on toggle", () => {
    const model = makeModel();
    model.layout = { g: { x: 100, y: 60, w: 80, h: 40 } };
    useAppStore.setState({ editingModel: model, editingPath: [] });
    toggleBlockFlipped("g");
    const m = useAppStore.getState().editingModel!;
    expect(m.layout!["g"]).toEqual({ x: 100, y: 60, w: 80, h: 40, flipped: true });
  });

  it("propagates flipped through modelToDiagram to node data", () => {
    useAppStore.setState({ editingModel: makeModel(), editingPath: [] });
    toggleBlockFlipped("g");
    const m = useAppStore.getState().editingModel!;
    const { nodes } = modelToDiagram(m);
    expect(nodes[0]?.data.flipped).toBe(true);
  });

  it("toggles flipped inside a Subsystem (path != [])", () => {
    const model: FlwModel = {
      schema_version: "0.8",
      simulator: makeModel().simulator,
      blocks: [
        {
          id: "sub",
          type: SUBSYSTEM_TYPE,
          params: {
            blocks: [
              {
                id: "inner_g",
                type: "pyflw.blocks.mathops.Gain",
                params: { k: 1 },
              },
            ],
            connections: [],
            layout: { inner_g: { x: 50, y: 50 } },
          },
        },
      ],
      connections: [],
      layout: { sub: { x: 0, y: 0 } },
    };
    useAppStore.setState({ editingModel: model, editingPath: ["sub"] });
    toggleBlockFlipped("inner_g");
    const m = useAppStore.getState().editingModel!;
    const inner = resolveBlocksAtPath(m, ["sub"]);
    expect(inner.layout["inner_g"]!.flipped).toBe(true);
    // 親階層の sub には flipped を書かない
    expect(m.layout!["sub"]!.flipped).toBeUndefined();
  });

  it("creates a layout entry from {x:0, y:0} when none existed", () => {
    const model = makeModel();
    model.layout = {}; // entry 無しから始める
    useAppStore.setState({ editingModel: model, editingPath: [] });
    toggleBlockFlipped("g");
    const m = useAppStore.getState().editingModel!;
    expect(m.layout!["g"]).toEqual({ x: 0, y: 0, flipped: true });
  });
});
