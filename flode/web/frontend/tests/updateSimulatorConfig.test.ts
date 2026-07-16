// v0.16.0: updateSimulatorConfig は editingModel.simulator を patch する
// 単純なアクション。t_end は Toolbar の Stop Time フィールド、それ以外は
// Model Settings ダイアログから呼ばれる。

import { beforeEach, describe, expect, it } from "vitest";

import { updateSimulatorConfig, useAppStore } from "../src/store/appStore";
import type { FlwModel } from "../src/types/api";

function makeModel(): FlwModel {
  return {
    schema_version: "0.8",
    simulator: {
      t_end: 10,
      dt: 0.01,
      solver: "RK45",
      rtol: 1e-3,
      atol: 1e-6,
      dt_base: null,
    },
    blocks: [],
    connections: [],
    layout: {},
  };
}

beforeEach(() => {
  useAppStore.setState({
    editingModel: null,
    editingPath: [],
    dirty: false,
  });
});

describe("updateSimulatorConfig", () => {
  it("patches t_end (only) without touching other fields", () => {
    useAppStore.setState({ editingModel: makeModel(), editingPath: [] });
    updateSimulatorConfig({ t_end: 25 });
    const sim = useAppStore.getState().editingModel!.simulator;
    expect(sim.t_end).toBe(25);
    expect(sim.dt).toBe(0.01);
    expect(sim.solver).toBe("RK45");
    expect(sim.rtol).toBe(1e-3);
    expect(sim.atol).toBe(1e-6);
    expect(sim.dt_base).toBeNull();
  });

  it("patches multiple fields at once (= Model Settings save)", () => {
    useAppStore.setState({ editingModel: makeModel(), editingPath: [] });
    updateSimulatorConfig({
      solver: "LSODA",
      dt: 0.005,
      rtol: 1e-6,
      atol: 1e-9,
      dt_base: 0.005,
    });
    const sim = useAppStore.getState().editingModel!.simulator;
    expect(sim.solver).toBe("LSODA");
    expect(sim.dt).toBe(0.005);
    expect(sim.rtol).toBe(1e-6);
    expect(sim.atol).toBe(1e-9);
    expect(sim.dt_base).toBe(0.005);
    expect(sim.t_end).toBe(10); // 触れていないフィールドは保持
  });

  it("dt_base can be reset to null (= Auto)", () => {
    const m = makeModel();
    m.simulator.dt_base = 0.005;
    useAppStore.setState({ editingModel: m, editingPath: [] });
    updateSimulatorConfig({ dt_base: null });
    expect(useAppStore.getState().editingModel!.simulator.dt_base).toBeNull();
  });

  it("sets dirty flag (= autosave triggers)", () => {
    useAppStore.setState({
      editingModel: makeModel(),
      editingPath: [],
      dirty: false,
    });
    updateSimulatorConfig({ t_end: 5 });
    expect(useAppStore.getState().dirty).toBe(true);
  });

  it("no-op when editingModel is null", () => {
    useAppStore.setState({ editingModel: null });
    updateSimulatorConfig({ t_end: 5 });
    expect(useAppStore.getState().editingModel).toBeNull();
  });

  it("does not touch blocks / connections / layout", () => {
    const model = makeModel();
    model.blocks = [
      { id: "g", type: "flode.blocks.mathops.Gain", params: { k: 2 } },
    ];
    model.connections = [];
    model.layout = { g: { x: 1, y: 2 } };
    useAppStore.setState({ editingModel: model, editingPath: [] });
    updateSimulatorConfig({ t_end: 100 });
    const m = useAppStore.getState().editingModel!;
    expect(m.blocks).toEqual(model.blocks);
    expect(m.layout).toEqual({ g: { x: 1, y: 2 } });
  });
});
