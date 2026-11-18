// ADR-0087 / SPEC-0038: 信号名の store 操作と追従。
//
// - setSignalName: 正規化・検証・空で削除・同名 no-op・1 編集 = 1 履歴・Undo/Redo
// - 消える側 (applyEditingModel の reconcile): ブロック削除・最後の配線の削除・ポート数減少・
//   addConnectionToEditing の置き換え・spliceEdgeWithBlock
// - 移す側: rename (最上位・Subsystem 内) / 行の付け替え / Outport 削除で親スコープが詰まる /
//   コピー・貼り付け
// - 保存直前 (prepareModelForBackend) の全スコープ reconcile

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { prepareModelForBackend } from "../src/lib/modelForBackend";
import {
  addConnectionToEditing,
  copySelectionToClipboard,
  pasteClipboard,
  removeBlockFromEditing,
  removeConnectionFromEditing,
  renameBlockInEditing,
  setSignalName,
  signalNameInEditing,
  spliceEdgeWithBlock,
  updateBlockParams,
  updateBlockParamsAndRemap,
  useAppStore,
} from "../src/store/appStore";
import type { BlockEntry, ConnectionEntry, FlwModel } from "../src/types/api";

const SUB = "flode.subsystems.subsystem.Subsystem";
const INPORT = "flode.subsystems.ports.Inport";
const OUTPORT = "flode.subsystems.ports.Outport";

const C = (src: string, src_idx: number, dst: string, dst_idx = 0): ConnectionEntry => ({
  src,
  src_idx,
  dst,
  dst_idx,
});

function baseModel(): FlwModel {
  return {
    schema_version: "0.15",
    simulator: { t_end: 1, dt: 0.1, solver: "RK45", rtol: 1e-3, atol: 1e-6, dt_base: null },
    blocks: [
      { id: "src", type: "flode.blocks.sources.Step", params: {} },
      { id: "g1", type: "flode.blocks.mathops.Gain", params: { k: 2 } },
      { id: "g2", type: "flode.blocks.mathops.Gain", params: { k: 3 } },
      { id: "dm", type: "flode.blocks.routing.Demux", params: { n: 3 } },
      { id: "sc", type: "flode.blocks.sinks.Scope", params: { n_inputs: 3 } },
    ],
    connections: [
      C("src", 0, "g1"),
      C("src", 0, "g2"),
      C("g1", 0, "dm"),
      C("dm", 0, "sc", 0),
      C("dm", 1, "sc", 1),
      C("dm", 2, "sc", 2),
    ],
    layout: {},
  };
}

/** 最上位に Subsystem "sub" (内部: Inport i → Gain g → Outport o0, Gain g → Outport o1)。 */
function subsystemModel(): FlwModel {
  const sub: BlockEntry = {
    id: "sub",
    type: SUB,
    params: {
      blocks: [
        { id: "i", type: INPORT, params: { port_idx: 0 } },
        { id: "g", type: "flode.blocks.mathops.Gain", params: { k: 1 } },
        { id: "o0", type: OUTPORT, params: { port_idx: 0 } },
        { id: "o1", type: OUTPORT, params: { port_idx: 1 } },
      ],
      connections: [C("i", 0, "g"), C("g", 0, "o0"), C("g", 0, "o1")],
      signal_names: { "g:0": "inner gain" },
    },
  };
  return {
    schema_version: "0.15",
    simulator: { t_end: 1, dt: 0.1, solver: "RK45", rtol: 1e-3, atol: 1e-6, dt_base: null },
    blocks: [
      { id: "src", type: "flode.blocks.sources.Step", params: {} },
      sub,
      { id: "sc", type: "flode.blocks.sinks.Scope", params: { n_inputs: 2 } },
    ],
    connections: [C("src", 0, "sub"), C("sub", 0, "sc", 0), C("sub", 1, "sc", 1)],
    signal_names: { "sub:0": "first", "sub:1": "second" },
    layout: {},
  };
}

function reset(m: FlwModel, path: string[] = []): void {
  useAppStore.setState({
    editingModel: m,
    editingPath: path,
    history: { past: [], future: [] },
    lastMergeKey: null,
    dirty: false,
    selectedNodeIds: [],
    selectedNodeId: null,
    clipboard: null,
  });
}

const model = (): FlwModel => useAppStore.getState().editingModel!;
const subParams = (m: FlwModel = model()): Record<string, unknown> =>
  m.blocks.find((b) => b.id === "sub")!.params as Record<string, unknown>;

beforeEach(() => reset(baseModel()));
afterEach(() => reset(null as unknown as FlwModel));

describe("setSignalName", () => {
  it("normalizes and stores the name; 1 edit = 1 history entry", () => {
    expect(setSignalName("src", 0, "  é  ")).toBeNull();
    expect(model().signal_names).toEqual({ "src:0": "é" });
    expect(useAppStore.getState().history.past.length).toBe(1);
    expect(useAppStore.getState().dirty).toBe(true);
    expect(signalNameInEditing("src", 0)).toBe("é");
  });

  it("returns an error and does not write invalid names", () => {
    const before = model();
    expect(setSignalName("src", 0, "a\nb")).toBe("control_char");
    expect(setSignalName("src", 0, "x".repeat(65))).toBe("too_long");
    expect(model()).toBe(before);
    expect(useAppStore.getState().history.past.length).toBe(0);
  });

  it("same name is a no-op; empty clears and removes the key", () => {
    setSignalName("src", 0, "n");
    setSignalName("src", 0, " n ");
    expect(useAppStore.getState().history.past.length).toBe(1);
    setSignalName("src", 0, "   ");
    expect("signal_names" in model()).toBe(false);
    expect(useAppStore.getState().history.past.length).toBe(2);
    // 名前が無い状態で空を確定しても履歴を積まない
    setSignalName("src", 0, "");
    expect(useAppStore.getState().history.past.length).toBe(2);
  });

  it("undo / redo restores the name", () => {
    setSignalName("src", 0, "a");
    setSignalName("src", 0, "b");
    useAppStore.getState().undo();
    expect(model().signal_names).toEqual({ "src:0": "a" });
    useAppStore.getState().undo();
    expect(model().signal_names).toBeUndefined();
    useAppStore.getState().redo();
    expect(model().signal_names).toEqual({ "src:0": "a" });
  });

  it("writes into the Subsystem scope when drilled in", () => {
    reset(subsystemModel(), ["sub"]);
    setSignalName("i", 0, "inner in");
    expect(subParams().signal_names).toEqual({ "g:0": "inner gain", "i:0": "inner in" });
    expect(model().signal_names).toEqual({ "sub:0": "first", "sub:1": "second" });
  });

  it("keeps the key order when replacing", () => {
    setSignalName("src", 0, "a");
    setSignalName("g1", 0, "b");
    setSignalName("src", 0, "c");
    expect(Object.keys(model().signal_names!)).toEqual(["src:0", "g1:0"]);
  });
});

describe("names disappear with their last wire (reconcile)", () => {
  beforeEach(() => {
    setSignalName("src", 0, "step");
    setSignalName("dm", 2, "third");
  });

  it("removing one of two branches keeps the name; removing both drops it", () => {
    removeConnectionFromEditing("src", 0, "g1", 0);
    expect(model().signal_names).toEqual({ "src:0": "step", "dm:2": "third" });
    removeConnectionFromEditing("src", 0, "g2", 0);
    expect(model().signal_names).toEqual({ "dm:2": "third" });
    // 同じ履歴: Undo 1 回で配線と名前が戻る
    useAppStore.getState().undo();
    expect(model().signal_names).toEqual({ "src:0": "step", "dm:2": "third" });
  });

  it("deleting the source block drops its names", () => {
    removeBlockFromEditing("src");
    expect(model().signal_names).toEqual({ "dm:2": "third" });
  });

  it("reducing output ports (updateBlockParams) drops the removed port's name", () => {
    updateBlockParams("dm", { n: 2 });
    expect(model().signal_names).toEqual({ "src:0": "step" });
  });

  it("addConnectionToEditing replacing the only wire drops the name", () => {
    addConnectionToEditing(C("g2", 0, "sc", 2));
    expect(model().signal_names).toEqual({ "src:0": "step" });
  });

  it("spliceEdgeWithBlock keeps the upstream name (wire re-created)", () => {
    spliceEdgeWithBlock(C("dm", 2, "sc", 2), "g2");
    // dm:2 → g2 の新しい配線があるので名前は残る
    expect(model().signal_names).toEqual({ "src:0": "step", "dm:2": "third" });
  });
});

describe("names move with ids / port numbers", () => {
  it("rename moves the key at top level", () => {
    setSignalName("dm", 1, "mid");
    expect(renameBlockInEditing("dm", "demux")).toBeNull();
    expect(model().signal_names).toEqual({ "demux:1": "mid" });
    useAppStore.getState().undo();
    expect(model().signal_names).toEqual({ "dm:1": "mid" });
  });

  it("rename moves the key inside a Subsystem only", () => {
    reset(subsystemModel(), ["sub"]);
    renameBlockInEditing("g", "gain");
    expect(subParams().signal_names).toEqual({ "gain:0": "inner gain" });
    expect(model().signal_names).toEqual({ "sub:0": "first", "sub:1": "second" });
  });

  it("row remap moves output names and drops deleted rows", () => {
    setSignalName("dm", 0, "zero");
    setSignalName("dm", 1, "one");
    setSignalName("dm", 2, "two");
    updateBlockParamsAndRemap("dm", { n: 2 }, [{ side: "output", map: [null, 0, 1] }]);
    expect(model().signal_names).toEqual({ "dm:0": "one", "dm:1": "two" });
  });

  it("deleting an Outport shifts the parent-scope keys (no name lands on a neighbour)", () => {
    reset(subsystemModel(), ["sub"]);
    removeBlockFromEditing("o0");
    // 親の sub:1 の配線は sub:0 に詰まり、名前も一緒に移る。消えた sub:0 の名前は消える
    expect(model().connections).toContainEqual(C("sub", 0, "sc", 1));
    expect(model().signal_names).toEqual({ "sub:0": "second" });
  });

  it("copy / paste carries names only when the source and a wire are both copied", () => {
    setSignalName("src", 0, "step");
    setSignalName("g1", 0, "gain out");
    useAppStore.setState({ selectedNodeIds: ["src", "g1"] });
    copySelectionToClipboard();
    // g1 → dm の配線は dm が選ばれていないのでコピーされない → g1:0 の名前は運ばない
    expect(useAppStore.getState().clipboard!.signal_names).toEqual({ "src:0": "step" });
    pasteClipboard();
    const names = model().signal_names!;
    const pastedSrc = useAppStore.getState().selectedNodeIds.find((id) => id.startsWith("src"))!;
    expect(names[`${pastedSrc}:0`]).toBe("step");
    expect(names["src:0"]).toBe("step");
    expect(Object.keys(names)).toHaveLength(3);
  });

  it("copying a Subsystem block carries its inner names", () => {
    reset(subsystemModel());
    useAppStore.setState({ selectedNodeIds: ["sub"] });
    copySelectionToClipboard();
    pasteClipboard();
    const pasted = model().blocks.at(-1)!;
    expect((pasted.params as Record<string, unknown>).signal_names).toEqual({ "g:0": "inner gain" });
  });
});

describe("prepareModelForBackend", () => {
  it("drops orphan / invalid names in every scope without pushing history", () => {
    const m = subsystemModel();
    (subParams(m) as Record<string, unknown>).signal_names = { "g:0": "ok", "ghost:0": "x" };
    m.signal_names = { "sub:0": "first", bad: "y", "src:0": 12 } as unknown as Record<string, string>;
    reset(m);
    const out = prepareModelForBackend(m);
    expect(out.signal_names).toEqual({ "sub:0": "first" });
    expect(subParams(out).signal_names).toEqual({ "g:0": "ok" });
    expect(model()).toBe(out);
    expect(useAppStore.getState().history.past.length).toBe(0);
  });

  it("leaves a model without names untouched (same reference)", () => {
    const m = baseModel();
    reset(m);
    expect(prepareModelForBackend(m)).toBe(m);
  });
});
