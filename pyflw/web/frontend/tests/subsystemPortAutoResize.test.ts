// 再現テスト: Subsystem ドリルダウン中に Inport / Outport を追加・削除した時、
// 親 Subsystem の n_inputs / n_outputs が自動同期し、port_idx は連番、親階層の
// connections は dst_idx / src_idx が追従シフトされること (Simulink semantics)。
//
// バグ修正前は addBlockToEditing が親 Subsystem の params.n_inputs を更新せず、
// save 時に backend Subsystem._build (= 内部 Inport 数 == n_inputs を要求) で
// BlockSpecError を受ける構造になっていた。

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
    schema_version: "0.7",
    simulator: {
      t_end: 1,
      dt: 0.01,
      solver: "RK45",
      rtol: 1e-6,
      atol: 1e-9,
      dt_base: null,
    },
    blocks: [
      {
        id: "src",
        type: "pyflw.blocks.sources.Constant",
        params: { value: 1.0 },
      },
      {
        id: "sub",
        type: SUBSYSTEM_TYPE,
        params: {
          n_inputs: 1,
          n_outputs: 1,
          blocks: [
            {
              id: "in0",
              type: INPORT_TYPE,
              params: { port_idx: 0 },
            },
            {
              id: "out0",
              type: OUTPORT_TYPE,
              params: { port_idx: 0 },
            },
          ],
          connections: [],
          layout: { in0: { x: 0, y: 0 }, out0: { x: 200, y: 0 } },
        },
      },
      {
        id: "snk",
        type: "pyflw.blocks.sinks.Terminator",
        params: {},
      },
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
  // Triggered: n_inputs = 内部 Inport 数 + 1 (trigger)、trigger は親 dst_idx = n_inputs - 1
  return {
    schema_version: "0.7",
    simulator: {
      t_end: 1,
      dt: 0.01,
      solver: "RK45",
      rtol: 1e-6,
      atol: 1e-9,
      dt_base: null,
    },
    blocks: [
      {
        id: "data_src",
        type: "pyflw.blocks.sources.Constant",
        params: { value: 1.0 },
      },
      {
        id: "trig_src",
        type: "pyflw.blocks.sources.PulseGenerator",
        params: {},
      },
      {
        id: "tsub",
        type: TRIGGERED_TYPE,
        params: {
          n_inputs: 2, // 内部 Inport 1 + trigger 1
          n_outputs: 1,
          trigger_mode: "rising",
          blocks: [
            {
              id: "in0",
              type: INPORT_TYPE,
              params: { port_idx: 0 },
            },
            {
              id: "out0",
              type: OUTPORT_TYPE,
              params: { port_idx: 0 },
            },
          ],
          connections: [],
          layout: {},
        },
      },
    ],
    connections: [
      // データ入力 (dst_idx=0) と trigger 入力 (dst_idx=1 = n_inputs - 1)
      { src: "data_src", src_idx: 0, dst: "tsub", dst_idx: 0 },
      { src: "trig_src", src_idx: 0, dst: "tsub", dst_idx: 1 },
    ],
    layout: {},
  };
}

beforeEach(() => {
  // store を真っさらに reset
  useAppStore.setState({
    editingModel: null,
    editingPath: [],
    dirty: false,
  });
});

describe("Subsystem port auto-resize on Inport/Outport drop", () => {
  it("adding an Inport into a Subsystem increments parent n_inputs and assigns next port_idx", () => {
    useAppStore.setState({
      editingModel: makeBaseModel(),
      editingPath: ["sub"],
    });
    const newInport: BlockEntry = {
      id: "in1",
      type: INPORT_TYPE,
      // ユーザーが drop した時点の params (= BlockPalette default は port_idx=0 の可能性)、
      // addBlockToEditing が内部既存 count から自動採番で上書きする想定
      params: { port_idx: 0 },
    };
    addBlockToEditing(newInport, { x: 0, y: 100 });

    const model = useAppStore.getState().editingModel!;
    const parent = findBlockAtPath(model, [], "sub")!;
    expect(parent.params.n_inputs).toBe(2);

    const inner = resolveBlocksAtPath(model, ["sub"]);
    const addedInport = inner.blocks.find((b) => b.id === "in1")!;
    expect(addedInport.params.port_idx).toBe(1);

    // 既存 inport の port_idx は不変
    const in0 = inner.blocks.find((b) => b.id === "in0")!;
    expect(in0.params.port_idx).toBe(0);

    // 親階層 connections は不変 (= 既存接続を破壊しない)
    expect(model.connections).toHaveLength(2);
  });

  it("adding an Outport into a Subsystem increments parent n_outputs and assigns next port_idx", () => {
    useAppStore.setState({
      editingModel: makeBaseModel(),
      editingPath: ["sub"],
    });
    addBlockToEditing(
      { id: "out1", type: OUTPORT_TYPE, params: { port_idx: 0 } },
      { x: 200, y: 100 },
    );

    const model = useAppStore.getState().editingModel!;
    const parent = findBlockAtPath(model, [], "sub")!;
    expect(parent.params.n_outputs).toBe(2);

    const inner = resolveBlocksAtPath(model, ["sub"]);
    const out1 = inner.blocks.find((b) => b.id === "out1")!;
    expect(out1.params.port_idx).toBe(1);
  });

  it("removing an Inport decrements parent n_inputs and severs the matching parent-level connection", () => {
    useAppStore.setState({
      editingModel: makeBaseModel(),
      editingPath: ["sub"],
    });
    removeBlockFromEditing("in0");

    const model = useAppStore.getState().editingModel!;
    const parent = findBlockAtPath(model, [], "sub")!;
    expect(parent.params.n_inputs).toBe(0);

    const inner = resolveBlocksAtPath(model, ["sub"]);
    expect(inner.blocks.find((b) => b.id === "in0")).toBeUndefined();

    // 親階層の src→sub.0 接続は削除される (= dst_idx==0 が消滅したため)
    expect(
      model.connections.some((c) => c.dst === "sub" && c.dst_idx === 0),
    ).toBe(false);
  });

  it("removing a middle Inport renumbers remaining port_idx and shifts parent dst_idx", () => {
    // base model に 2 個 Inport を追加して in0/in1/in2 (port_idx 0/1/2)、
    // それぞれに親階層から接続を貼り、in1 削除で port_idx と dst_idx が 1 連番ずれることを検証
    const m = makeBaseModel();
    const sub = m.blocks.find((b) => b.id === "sub")!;
    sub.params = {
      ...sub.params,
      n_inputs: 3,
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
      // src→sub.0 (= 既存)、src1→sub.1、src2→sub.2、sub.0→snk (= 既存) に揃える
      { src: "src", src_idx: 0, dst: "sub", dst_idx: 0 },
      { src: "src1", src_idx: 0, dst: "sub", dst_idx: 1 },
      { src: "src2", src_idx: 0, dst: "sub", dst_idx: 2 },
      { src: "sub", src_idx: 0, dst: "snk", dst_idx: 0 },
    ];
    useAppStore.setState({ editingModel: m, editingPath: ["sub"] });

    removeBlockFromEditing("in1");

    const model = useAppStore.getState().editingModel!;
    const parent = findBlockAtPath(model, [], "sub")!;
    expect(parent.params.n_inputs).toBe(2);

    const inner = resolveBlocksAtPath(model, ["sub"]);
    const in0 = inner.blocks.find((b) => b.id === "in0")!;
    const in2 = inner.blocks.find((b) => b.id === "in2")!;
    expect(in0.params.port_idx).toBe(0);
    expect(in2.params.port_idx).toBe(1); // 2 → 1 にシフト

    // 親 connections: src→sub.0 不変、src1→sub.1 削除、src2→sub.2 が sub.1 にシフト
    const subConnections = model.connections.filter((c) => c.dst === "sub");
    expect(subConnections).toHaveLength(2);
    expect(
      subConnections.find((c) => c.src === "src" && c.dst_idx === 0),
    ).toBeDefined();
    expect(
      subConnections.find((c) => c.src === "src1"),
    ).toBeUndefined(); // 削除
    expect(
      subConnections.find((c) => c.src === "src2" && c.dst_idx === 1),
    ).toBeDefined();
  });

  it("adding an Inport into a TriggeredSubsystem shifts the trigger connection (= n_inputs-1 slot)", () => {
    useAppStore.setState({
      editingModel: makeTriggeredModel(),
      editingPath: ["tsub"],
    });
    addBlockToEditing(
      { id: "in1", type: INPORT_TYPE, params: { port_idx: 0 } },
      { x: 0, y: 100 },
    );

    const model = useAppStore.getState().editingModel!;
    const parent = findBlockAtPath(model, [], "tsub")!;
    expect(parent.params.n_inputs).toBe(3); // 内部 Inport 2 + trigger 1

    const inner = resolveBlocksAtPath(model, ["tsub"]);
    const in1 = inner.blocks.find((b) => b.id === "in1")!;
    expect(in1.params.port_idx).toBe(1);

    // trigger 接続は旧 dst_idx = 1 (= 旧 n_inputs - 1) → 新 dst_idx = 2 (= 新 n_inputs - 1)
    const trigConn = model.connections.find(
      (c) => c.src === "trig_src" && c.dst === "tsub",
    )!;
    expect(trigConn.dst_idx).toBe(2);

    // データ接続 (dst_idx = 0) は不変
    const dataConn = model.connections.find(
      (c) => c.src === "data_src" && c.dst === "tsub",
    )!;
    expect(dataConn.dst_idx).toBe(0);
  });

  it("removing an Inport from a TriggeredSubsystem keeps trigger as the last slot", () => {
    // n_inputs=3, 内部 in0/in1, trigger dst_idx=2 から in0 を削除
    const m = makeTriggeredModel();
    const tsub = m.blocks.find((b) => b.id === "tsub")!;
    tsub.params = {
      ...tsub.params,
      n_inputs: 3,
      blocks: [
        { id: "in0", type: INPORT_TYPE, params: { port_idx: 0 } },
        { id: "in1", type: INPORT_TYPE, params: { port_idx: 1 } },
        { id: "out0", type: OUTPORT_TYPE, params: { port_idx: 0 } },
      ],
    };
    m.connections = [
      { src: "data_src", src_idx: 0, dst: "tsub", dst_idx: 0 },
      // 仮に dst_idx=1 にも何か繋いでおく (= in1 への接続)
      { src: "data_src", src_idx: 0, dst: "tsub", dst_idx: 1 },
      // trigger は末尾 dst_idx=2
      { src: "trig_src", src_idx: 0, dst: "tsub", dst_idx: 2 },
    ];
    useAppStore.setState({ editingModel: m, editingPath: ["tsub"] });

    removeBlockFromEditing("in0");

    const model = useAppStore.getState().editingModel!;
    const parent = findBlockAtPath(model, [], "tsub")!;
    expect(parent.params.n_inputs).toBe(2); // 内部 1 + trigger 1

    const inner = resolveBlocksAtPath(model, ["tsub"]);
    const in1 = inner.blocks.find((b) => b.id === "in1")!;
    expect(in1.params.port_idx).toBe(0); // 1 → 0

    // 親 connections:
    // - data_src→tsub.0 (= 旧 in0 への接続) は削除される
    // - data_src→tsub.1 (= 旧 in1 への接続) は dst_idx=0 にシフト
    // - trigger→tsub.2 は dst_idx=1 (= 新 n_inputs - 1) にシフト
    const tsubConnections = model.connections.filter((c) => c.dst === "tsub");
    expect(tsubConnections).toHaveLength(2);
    const inboundDataIdx = tsubConnections
      .filter((c) => c.src === "data_src")
      .map((c) => c.dst_idx);
    expect(inboundDataIdx).toEqual([0]);
    const trigConn = tsubConnections.find((c) => c.src === "trig_src")!;
    expect(trigConn.dst_idx).toBe(1);
  });

  it("removing an Outport decrements parent n_outputs and shifts parent src_idx (= MUST-3 carve-out for Outport branch)", () => {
    // base model に Outport を 1 つ増やして out0/out1 (port_idx 0/1) を持たせ、
    // それぞれに親階層 sink への接続 (sub.0→snk, sub.1→snk2) を貼る。
    // out0 を削除 → n_outputs=2→1、sub→snk 接続削除、sub.1→snk2 が sub.0 にシフト。
    const m = makeBaseModel();
    const sub = m.blocks.find((b) => b.id === "sub")!;
    sub.params = {
      ...sub.params,
      n_outputs: 2,
      blocks: [
        { id: "in0", type: INPORT_TYPE, params: { port_idx: 0 } },
        { id: "out0", type: OUTPORT_TYPE, params: { port_idx: 0 } },
        { id: "out1", type: OUTPORT_TYPE, params: { port_idx: 1 } },
      ],
    };
    m.blocks.push({
      id: "snk2",
      type: "pyflw.blocks.sinks.Terminator",
      params: {},
    });
    m.connections = [
      { src: "src", src_idx: 0, dst: "sub", dst_idx: 0 },
      { src: "sub", src_idx: 0, dst: "snk", dst_idx: 0 },
      { src: "sub", src_idx: 1, dst: "snk2", dst_idx: 0 },
    ];
    useAppStore.setState({ editingModel: m, editingPath: ["sub"] });

    removeBlockFromEditing("out0");

    const model = useAppStore.getState().editingModel!;
    const parent = findBlockAtPath(model, [], "sub")!;
    expect(parent.params.n_outputs).toBe(1);

    const inner = resolveBlocksAtPath(model, ["sub"]);
    const out1 = inner.blocks.find((b) => b.id === "out1")!;
    expect(out1.params.port_idx).toBe(0); // 1 → 0

    // 親 connections: sub.0→snk は削除、sub.1→snk2 が sub.0 にシフト
    const subOut = model.connections.filter((c) => c.src === "sub");
    expect(subOut).toHaveLength(1);
    expect(subOut[0]!.src_idx).toBe(0);
    expect(subOut[0]!.dst).toBe("snk2");
  });

  it("removing an Inport with missing port_idx still decrements parent n_inputs (= MUST-2 defensive)", () => {
    // 想定外データ: Inport に port_idx が無い (= legacy / corrupt model)。
    // 親 n_inputs は -1 されるが、親 connections のシフトは port_idx 不明
    // のためスキップされる。少なくとも内部 Inport 数 == n_inputs の不変条件は
    // 維持して、後続の Subsystem._build エラーを早期化する。
    const m = makeBaseModel();
    const sub = m.blocks.find((b) => b.id === "sub")!;
    sub.params = {
      ...sub.params,
      n_inputs: 1,
      blocks: [
        { id: "in_no_idx", type: INPORT_TYPE, params: {} },
        { id: "out0", type: OUTPORT_TYPE, params: { port_idx: 0 } },
      ],
    };
    useAppStore.setState({ editingModel: m, editingPath: ["sub"] });

    removeBlockFromEditing("in_no_idx");

    const model = useAppStore.getState().editingModel!;
    const parent = findBlockAtPath(model, [], "sub")!;
    expect(parent.params.n_inputs).toBe(0);
    const inner = resolveBlocksAtPath(model, ["sub"]);
    expect(inner.blocks.find((b) => b.id === "in_no_idx")).toBeUndefined();
  });

  it("adding an Inport at the top-level (no parent Subsystem) is a safe no-op for parent sync", () => {
    // editingPath = [] では「親」が存在しない (= top-level モデル)。
    // 同期スキップで model 自体に純粋追加されること、port_idx 自動採番は動くこと。
    useAppStore.setState({
      editingModel: makeBaseModel(),
      editingPath: [],
    });
    addBlockToEditing(
      { id: "stray_inport", type: INPORT_TYPE, params: { port_idx: 0 } },
      { x: 500, y: 500 },
    );

    const model = useAppStore.getState().editingModel!;
    expect(model.blocks.find((b) => b.id === "stray_inport")).toBeDefined();
    // top-level に元から Inport がなければ自動採番は 0、これは元 params と同じなので変化なし
    const stray = model.blocks.find((b) => b.id === "stray_inport")!;
    expect(stray.params.port_idx).toBe(0);
  });
});
