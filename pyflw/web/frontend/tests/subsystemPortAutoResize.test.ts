// ADR-0039 (v2.0): Subsystem の `n_inputs` / `n_outputs` は派生 property 化された
// ため、frontend で auto-sync は不要 (= 内部 Inport/Outport を追加するだけで
// `dynamicPorts.resolvePortCounts` が自動で派生計算する)。
//
// 残るテストは:
//   1. port_idx の自動採番 (= 内部既存同種 count を新 Inport の port_idx に上書き)
//   2. port_idx 連番再割り当て (= 削除時に残った同種 ports の port_idx を -1)
//   3. 親階層 connections の dst_idx / src_idx シフト (= port_idx 連番再割り当て
//      に同期、TriggeredSubsystem trigger 接続も同じロジックで自動末尾保持)
//   4. TriggeredSubsystem trigger 接続 +1 シフト (= Inport 追加時、ADR-0036 §(2))

import { beforeEach, describe, expect, it } from "vitest";

import {
  INPORT_TYPE,
  OUTPORT_TYPE,
  SUBSYSTEM_TYPE,
  TRIGGERED_SUBSYSTEM_TYPE as TRIGGERED_TYPE,
} from "../src/lib/blockTypes";
import { findBlockAtPath, resolveBlocksAtPath } from "../src/lib/pathResolver";
import {
  addBlockToEditing,
  removeBlockFromEditing,
  useAppStore,
} from "../src/store/appStore";
import type { BlockEntry, FlwModel } from "../src/types/api";

function makeBaseModel(): FlwModel {
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
      { id: "src", type: "pyflw.blocks.sources.Constant", params: { value: 1.0 } },
      {
        id: "sub",
        type: SUBSYSTEM_TYPE,
        params: {
          // ADR-0039: n_inputs / n_outputs フィールドは廃止
          blocks: [
            { id: "in0", type: INPORT_TYPE, params: { port_idx: 0 } },
            { id: "out0", type: OUTPORT_TYPE, params: { port_idx: 0 } },
          ],
          connections: [],
          layout: { in0: { x: 0, y: 0 }, out0: { x: 200, y: 0 } },
        },
      },
      { id: "snk", type: "pyflw.blocks.sinks.Terminator", params: {} },
    ],
    connections: [
      { src: "src", src_idx: 0, dst: "sub", dst_idx: 0 },
      { src: "sub", src_idx: 0, dst: "snk", dst_idx: 0 },
    ],
    layout: {
      src: { x: 0, y: 0 },
      sub: { x: 100, y: 0 },
      snk: { x: 300, y: 0 },
    },
  };
}

function makeTriggeredModel(): FlwModel {
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
      { id: "data_src", type: "pyflw.blocks.sources.Constant", params: { value: 1.0 } },
      { id: "trig_src", type: "pyflw.blocks.sources.PulseGenerator", params: {} },
      {
        id: "tsub",
        type: TRIGGERED_TYPE,
        params: {
          trigger_mode: "rising",
          // 内部 Inport 1 (= 派生 n_inputs = 1 + 1 trigger = 2)
          blocks: [
            { id: "in0", type: INPORT_TYPE, params: { port_idx: 0 } },
            { id: "out0", type: OUTPORT_TYPE, params: { port_idx: 0 } },
          ],
          connections: [],
          layout: {},
        },
      },
    ],
    connections: [
      // データ入力 dst_idx=0、trigger 入力 dst_idx=1 (= 派生 n_inputs - 1)
      { src: "data_src", src_idx: 0, dst: "tsub", dst_idx: 0 },
      { src: "trig_src", src_idx: 0, dst: "tsub", dst_idx: 1 },
    ],
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

describe("ADR-0039: Subsystem port handling (derived property + port_idx renumber)", () => {
  it("adding an Inport into a Subsystem assigns next port_idx (parent n_inputs is derived)", () => {
    useAppStore.setState({
      editingModel: makeBaseModel(),
      editingPath: ["sub"],
    });
    const newInport: BlockEntry = {
      id: "in1",
      type: INPORT_TYPE,
      params: { port_idx: 0 }, // BlockPalette default、addBlockToEditing が上書き
    };
    addBlockToEditing(newInport, { x: 0, y: 100 });

    const model = useAppStore.getState().editingModel!;
    const inner = resolveBlocksAtPath(model, ["sub"]);
    const addedInport = inner.blocks.find((b) => b.id === "in1")!;
    expect(addedInport.params.port_idx).toBe(1);

    // 親 Subsystem の params には n_inputs フィールドは存在しない (= 派生)
    const parent = findBlockAtPath(model, [], "sub")!;
    expect(parent.params.n_inputs).toBeUndefined();

    // 内部 Inport は 2 個 (in0 + in1) になっており dynamicPorts が派生計算する
    const inports = inner.blocks.filter((b) => b.type === INPORT_TYPE);
    expect(inports).toHaveLength(2);

    // 親階層 connections は不変
    expect(model.connections).toHaveLength(2);
  });

  it("adding an Outport assigns next port_idx (parent n_outputs is derived)", () => {
    useAppStore.setState({
      editingModel: makeBaseModel(),
      editingPath: ["sub"],
    });
    addBlockToEditing(
      { id: "out1", type: OUTPORT_TYPE, params: { port_idx: 0 } },
      { x: 200, y: 100 },
    );

    const model = useAppStore.getState().editingModel!;
    const inner = resolveBlocksAtPath(model, ["sub"]);
    const out1 = inner.blocks.find((b) => b.id === "out1")!;
    expect(out1.params.port_idx).toBe(1);

    // 派生のため params.n_outputs は存在しない
    const parent = findBlockAtPath(model, [], "sub")!;
    expect(parent.params.n_outputs).toBeUndefined();
  });

  it("removing an Inport severs the matching parent-level connection", () => {
    useAppStore.setState({
      editingModel: makeBaseModel(),
      editingPath: ["sub"],
    });
    removeBlockFromEditing("in0");

    const model = useAppStore.getState().editingModel!;
    const inner = resolveBlocksAtPath(model, ["sub"]);
    expect(inner.blocks.find((b) => b.id === "in0")).toBeUndefined();
    // 親階層の src→sub.0 接続は削除される
    expect(
      model.connections.some((c) => c.dst === "sub" && c.dst_idx === 0),
    ).toBe(false);
  });

  it("removing a middle Inport renumbers remaining port_idx and shifts parent dst_idx", () => {
    const m = makeBaseModel();
    const sub = m.blocks.find((b) => b.id === "sub")!;
    sub.params = {
      ...sub.params,
      blocks: [
        { id: "in0", type: INPORT_TYPE, params: { port_idx: 0 } },
        { id: "in1", type: INPORT_TYPE, params: { port_idx: 1 } },
        { id: "in2", type: INPORT_TYPE, params: { port_idx: 2 } },
        { id: "out0", type: OUTPORT_TYPE, params: { port_idx: 0 } },
      ],
    };
    m.blocks.push(
      { id: "src1", type: "pyflw.blocks.sources.Constant", params: {} },
      { id: "src2", type: "pyflw.blocks.sources.Constant", params: {} },
    );
    m.connections = [
      { src: "src", src_idx: 0, dst: "sub", dst_idx: 0 },
      { src: "src1", src_idx: 0, dst: "sub", dst_idx: 1 },
      { src: "src2", src_idx: 0, dst: "sub", dst_idx: 2 },
      { src: "sub", src_idx: 0, dst: "snk", dst_idx: 0 },
    ];
    useAppStore.setState({ editingModel: m, editingPath: ["sub"] });

    removeBlockFromEditing("in1");

    const model = useAppStore.getState().editingModel!;
    const inner = resolveBlocksAtPath(model, ["sub"]);
    const in0 = inner.blocks.find((b) => b.id === "in0")!;
    const in2 = inner.blocks.find((b) => b.id === "in2")!;
    expect(in0.params.port_idx).toBe(0);
    expect(in2.params.port_idx).toBe(1); // 2 → 1

    const subConnections = model.connections.filter((c) => c.dst === "sub");
    expect(subConnections).toHaveLength(2);
    expect(subConnections.find((c) => c.src === "src" && c.dst_idx === 0)).toBeDefined();
    expect(subConnections.find((c) => c.src === "src1")).toBeUndefined();
    expect(subConnections.find((c) => c.src === "src2" && c.dst_idx === 1)).toBeDefined();
  });

  it("removing an Outport renumbers remaining port_idx and shifts parent src_idx", () => {
    const m = makeBaseModel();
    const sub = m.blocks.find((b) => b.id === "sub")!;
    sub.params = {
      ...sub.params,
      blocks: [
        { id: "in0", type: INPORT_TYPE, params: { port_idx: 0 } },
        { id: "out0", type: OUTPORT_TYPE, params: { port_idx: 0 } },
        { id: "out1", type: OUTPORT_TYPE, params: { port_idx: 1 } },
      ],
    };
    m.blocks.push({ id: "snk2", type: "pyflw.blocks.sinks.Terminator", params: {} });
    m.connections = [
      { src: "src", src_idx: 0, dst: "sub", dst_idx: 0 },
      { src: "sub", src_idx: 0, dst: "snk", dst_idx: 0 },
      { src: "sub", src_idx: 1, dst: "snk2", dst_idx: 0 },
    ];
    useAppStore.setState({ editingModel: m, editingPath: ["sub"] });

    removeBlockFromEditing("out0");

    const model = useAppStore.getState().editingModel!;
    const inner = resolveBlocksAtPath(model, ["sub"]);
    const out1 = inner.blocks.find((b) => b.id === "out1")!;
    expect(out1.params.port_idx).toBe(0);

    const subOut = model.connections.filter((c) => c.src === "sub");
    expect(subOut).toHaveLength(1);
    expect(subOut[0]!.src_idx).toBe(0);
    expect(subOut[0]!.dst).toBe("snk2");
  });

  it("adding an Inport into a TriggeredSubsystem shifts the trigger connection by +1", () => {
    useAppStore.setState({
      editingModel: makeTriggeredModel(),
      editingPath: ["tsub"],
    });
    addBlockToEditing(
      { id: "in1", type: INPORT_TYPE, params: { port_idx: 0 } },
      { x: 0, y: 100 },
    );

    const model = useAppStore.getState().editingModel!;
    const inner = resolveBlocksAtPath(model, ["tsub"]);
    const in1 = inner.blocks.find((b) => b.id === "in1")!;
    expect(in1.params.port_idx).toBe(1);

    // 派生 n_inputs = 内部 Inport 2 + trigger = 3
    // trigger 接続は旧 dst_idx=1 → 新 dst_idx=2
    const trigConn = model.connections.find(
      (c) => c.src === "trig_src" && c.dst === "tsub",
    )!;
    expect(trigConn.dst_idx).toBe(2);

    // データ接続 (dst_idx=0) は不変
    const dataConn = model.connections.find(
      (c) => c.src === "data_src" && c.dst === "tsub",
    )!;
    expect(dataConn.dst_idx).toBe(0);
  });

  it("removing an Inport from a TriggeredSubsystem keeps trigger as the last slot", () => {
    const m = makeTriggeredModel();
    const tsub = m.blocks.find((b) => b.id === "tsub")!;
    tsub.params = {
      ...tsub.params,
      blocks: [
        { id: "in0", type: INPORT_TYPE, params: { port_idx: 0 } },
        { id: "in1", type: INPORT_TYPE, params: { port_idx: 1 } },
        { id: "out0", type: OUTPORT_TYPE, params: { port_idx: 0 } },
      ],
    };
    m.connections = [
      { src: "data_src", src_idx: 0, dst: "tsub", dst_idx: 0 },
      { src: "data_src", src_idx: 0, dst: "tsub", dst_idx: 1 },
      { src: "trig_src", src_idx: 0, dst: "tsub", dst_idx: 2 },
    ];
    useAppStore.setState({ editingModel: m, editingPath: ["tsub"] });

    removeBlockFromEditing("in0");

    const model = useAppStore.getState().editingModel!;
    const inner = resolveBlocksAtPath(model, ["tsub"]);
    const in1 = inner.blocks.find((b) => b.id === "in1")!;
    expect(in1.params.port_idx).toBe(0);

    // trigger は dst_idx=2 → 1 にシフト (= port_idx 連番再割り当てに連動)
    const tsubConnections = model.connections.filter((c) => c.dst === "tsub");
    expect(tsubConnections).toHaveLength(2);
    const inboundDataIdx = tsubConnections
      .filter((c) => c.src === "data_src")
      .map((c) => c.dst_idx);
    expect(inboundDataIdx).toEqual([0]);
    const trigConn = tsubConnections.find((c) => c.src === "trig_src")!;
    expect(trigConn.dst_idx).toBe(1);
  });

  it("adding an Inport at top-level (no parent Subsystem) is a safe no-op for parent sync", () => {
    useAppStore.setState({
      editingModel: makeBaseModel(),
      editingPath: [],
    });
    addBlockToEditing(
      { id: "stray_inport", type: INPORT_TYPE, params: { port_idx: 0 } },
      { x: 500, y: 500 },
    );

    const model = useAppStore.getState().editingModel!;
    const stray = model.blocks.find((b) => b.id === "stray_inport")!;
    expect(stray.params.port_idx).toBe(0);
  });
});
