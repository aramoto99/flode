// v0.16.0: updateBlockPositions は複数 block の position を 1 回の
// applyEditingModel で一括更新する。複数選択ドラッグ時のエッジ追従ズレ対策。

import { beforeEach, describe, expect, it } from "vitest";

import {
  updateBlockPositions,
  useAppStore,
} from "../src/store/appStore";
import type { FlwModel } from "../src/types/api";

function makeModel(): FlwModel {
  return {
    schema_version: "0.8",
    simulator: {
      t_end: 1,
      dt: 0.01,
      solver: "RK45",
      rtol: 1e-3,
      atol: 1e-6,
      dt_base: null,
    },
    blocks: [
      { id: "a", type: "flode.blocks.sources.Constant", params: { value: 1 } },
      { id: "b", type: "flode.blocks.mathops.Gain", params: { k: 2 } },
      { id: "c", type: "flode.blocks.sinks.Display", params: {} },
    ],
    connections: [],
    layout: {
      a: { x: 0, y: 0 },
      b: { x: 100, y: 0, w: 80, h: 40 },
      c: { x: 200, y: 0 },
    },
  };
}

beforeEach(() => {
  useAppStore.setState({
    editingModel: null,
    editingPath: [],
    dirty: false,
  });
});

describe("updateBlockPositions (batched)", () => {
  it("updates multiple positions in a single applyEditingModel call", () => {
    useAppStore.setState({ editingModel: makeModel(), editingPath: [] });
    updateBlockPositions([
      { id: "a", x: 10, y: 20 },
      { id: "b", x: 110, y: 20 },
      { id: "c", x: 210, y: 20 },
    ]);
    const layout = useAppStore.getState().editingModel!.layout!;
    expect(layout["a"]).toEqual({ x: 10, y: 20 });
    expect(layout["b"]).toEqual({ x: 110, y: 20, w: 80, h: 40 });
    expect(layout["c"]).toEqual({ x: 210, y: 20 });
  });

  it("preserves w/h on entries that already have them", () => {
    useAppStore.setState({ editingModel: makeModel(), editingPath: [] });
    updateBlockPositions([{ id: "b", x: 999, y: 888 }]);
    const layout = useAppStore.getState().editingModel!.layout!;
    expect(layout["b"]).toEqual({ x: 999, y: 888, w: 80, h: 40 });
  });

  it("creates layout entry from scratch if missing", () => {
    const m = makeModel();
    delete m.layout!["a"];
    useAppStore.setState({ editingModel: m, editingPath: [] });
    updateBlockPositions([{ id: "a", x: 5, y: 5 }]);
    const layout = useAppStore.getState().editingModel!.layout!;
    expect(layout["a"]).toEqual({ x: 5, y: 5 });
  });

  it("no-op for empty updates array (= does not touch model)", () => {
    const before = makeModel();
    useAppStore.setState({ editingModel: before, editingPath: [], dirty: false });
    updateBlockPositions([]);
    expect(useAppStore.getState().editingModel).toBe(before); // 同一参照
    expect(useAppStore.getState().dirty).toBe(false);
  });

  it("sets dirty flag (= autosave triggers) on non-empty update", () => {
    useAppStore.setState({
      editingModel: makeModel(),
      editingPath: [],
      dirty: false,
    });
    updateBlockPositions([{ id: "a", x: 1, y: 1 }]);
    expect(useAppStore.getState().dirty).toBe(true);
  });

  it("does not touch other entries", () => {
    useAppStore.setState({ editingModel: makeModel(), editingPath: [] });
    updateBlockPositions([{ id: "b", x: 999, y: 999 }]);
    const layout = useAppStore.getState().editingModel!.layout!;
    expect(layout["a"]).toEqual({ x: 0, y: 0 });
    expect(layout["c"]).toEqual({ x: 200, y: 0 });
  });
});
