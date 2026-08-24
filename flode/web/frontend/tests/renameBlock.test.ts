// SPEC-0022: renameBlockInEditing の参照原子更新テスト (R1〜R6)。
//
// rename が 1 回の store 更新で blocks / connections / layout /
// branch_waypoints / scope_settings と非永続 GUI 状態を書き換え、
// undo 1 発で完全復帰することを検証する。

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { INPORT_TYPE, SUBSYSTEM_TYPE } from "../src/lib/blockTypes";
import { renameBlockInEditing, useAppStore } from "../src/store/appStore";
import type { FlwModel } from "../src/types/api";

const GAIN = "flode.blocks.mathops.Gain";
const SCOPE = "flode.blocks.sinks.Scope";
const SUBSYSTEM = SUBSYSTEM_TYPE;
const INPORT = INPORT_TYPE;

function baseModel(): FlwModel {
  return {
    schema_version: "0.10",
    metadata: { name: "test" },
    simulator: {
      t_end: 10,
      dt: 0.01,
      solver: "RK45",
      rtol: 1e-3,
      atol: 1e-6,
      dt_base: null,
    },
    blocks: [
      { id: "Gain_0", type: GAIN, params: { k: 2 } },
      { id: "Scope_0", type: SCOPE, params: {} },
      {
        id: "Sub_0",
        type: SUBSYSTEM,
        params: {
          blocks: [
            { id: "Inport_0", type: INPORT, params: { port_idx: 0 } },
            { id: "Gain_0", type: GAIN, params: { k: 5 } },
          ],
          connections: [
            { src: "Inport_0", src_idx: 0, dst: "Gain_0", dst_idx: 0 },
          ],
          layout: { Inport_0: { x: 0, y: 0 }, Gain_0: { x: 100, y: 0 } },
        },
      },
    ],
    connections: [
      { src: "Gain_0", src_idx: 0, dst: "Scope_0", dst_idx: 0 },
      { src: "Gain_0", src_idx: 0, dst: "Sub_0", dst_idx: 0 },
    ],
    layout: {
      Gain_0: { x: 0, y: 0 },
      Scope_0: { x: 200, y: 0 },
      Sub_0: { x: 200, y: 100 },
    },
    branch_waypoints: { "Gain_0:0": { axis: "x", pos: 150 } },
    scope_settings: { Scope_0: { y_min: -1 } },
  } as unknown as FlwModel;
}

beforeEach(() => {
  useAppStore.setState({
    editingModel: baseModel(),
    editingPath: [],
    history: { past: [], future: [] },
    lastMergeKey: null,
    dirty: false,
    selectedNodeIds: [],
    selectedNodeId: null,
    scopePanels: [],
    scopes: {},
    renameRequest: null,
  });
});

afterEach(() => {
  useAppStore.setState({
    editingModel: null,
    editingPath: [],
    history: { past: [], future: [] },
    scopePanels: [],
    scopes: {},
  });
});

function model(): FlwModel {
  return useAppStore.getState().editingModel!;
}

describe("renameBlockInEditing — R1〜R5 (モデル内参照の原子的更新)", () => {
  it("blocks / connections (src・dst) / layout / branch_waypoints が一括更新される", () => {
    const err = renameBlockInEditing("Gain_0", "トルクゲイン");
    expect(err).toBeNull();
    const m = model();
    expect(m.blocks.map((b) => b.id)).toEqual(["トルクゲイン", "Scope_0", "Sub_0"]);
    expect(m.connections).toEqual([
      { src: "トルクゲイン", src_idx: 0, dst: "Scope_0", dst_idx: 0 },
      { src: "トルクゲイン", src_idx: 0, dst: "Sub_0", dst_idx: 0 },
    ]);
    expect(m.layout).toHaveProperty("トルクゲイン");
    expect(m.layout).not.toHaveProperty("Gain_0");
    expect(m.layout!["トルクゲイン"]).toEqual({ x: 0, y: 0 });
    expect(m.branch_waypoints).toEqual({
      "トルクゲイン:0": { axis: "x", pos: 150 },
    });
  });

  it("params は一切変化しない (deep equal)", () => {
    const before = JSON.parse(JSON.stringify(model().blocks[0]!.params));
    renameBlockInEditing("Gain_0", "g2");
    expect(model().blocks[0]!.params).toEqual(before);
  });

  it("Scope の rename で scope_settings のキーが付け替わる", () => {
    renameBlockInEditing("Scope_0", "速度計");
    const m = model();
    expect(m.scope_settings).toEqual({ 速度計: { y_min: -1 } });
  });

  it("Subsystem 内での rename が親スコープを壊さない", () => {
    useAppStore.setState({ editingPath: ["Sub_0"] });
    const err = renameBlockInEditing("Gain_0", "内部ゲイン");
    expect(err).toBeNull();
    const m = model();
    // 親スコープの Gain_0 は不変
    expect(m.blocks[0]!.id).toBe("Gain_0");
    expect(m.connections[0]!.src).toBe("Gain_0");
    // 内部のみ rename
    const params = m.blocks[2]!.params as {
      blocks: Array<{ id: string }>;
      connections: Array<{ src: string; dst: string }>;
      layout: Record<string, unknown>;
    };
    expect(params.blocks.map((b) => b.id)).toEqual(["Inport_0", "内部ゲイン"]);
    expect(params.connections[0]!.dst).toBe("内部ゲイン");
    expect(params.layout).toHaveProperty("内部ゲイン");
    expect(params.layout).not.toHaveProperty("Gain_0");
  });

  it("Inport の rename で port_idx と親 dst_idx が不変", () => {
    useAppStore.setState({ editingPath: ["Sub_0"] });
    renameBlockInEditing("Inport_0", "速度");
    const m = model();
    const params = m.blocks[2]!.params as {
      blocks: Array<{ id: string; params: Record<string, unknown> }>;
    };
    expect(params.blocks[0]!.id).toBe("速度");
    expect(params.blocks[0]!.params.port_idx).toBe(0);
    // 親の Subsystem への結線は port_idx ベースで不変
    expect(m.connections[1]).toEqual({
      src: "Gain_0",
      src_idx: 0,
      dst: "Sub_0",
      dst_idx: 0,
    });
  });
});

describe("renameBlockInEditing — 検証 NG 時はモデル不変", () => {
  it.each([
    ["", "empty"],
    ["  ", "empty"],
    ["速度 指令", "charset"],
    ["a:b", "charset"],
    ["あ".repeat(65), "too_long"],
    ["Scope_0", "duplicate"],
    ["Ｓｃｏｐｅ＿０", "confusable_duplicate"],
  ])("%j → %s", (candidate, expected) => {
    const before = JSON.parse(JSON.stringify(model()));
    const err = renameBlockInEditing("Gain_0", candidate);
    expect(err?.code).toBe(expected);
    expect(model()).toEqual(before);
    expect(useAppStore.getState().history.past).toHaveLength(0);
  });

  it("duplicate / confusable_duplicate は衝突相手の id を conflictId で返す (SPEC §9)", () => {
    expect(renameBlockInEditing("Gain_0", "Scope_0")).toEqual({
      code: "duplicate",
      conflictId: "Scope_0",
    });
    expect(renameBlockInEditing("Gain_0", "Ｓｃｏｐｅ＿０")).toEqual({
      code: "confusable_duplicate",
      conflictId: "Scope_0",
    });
  });

  it("旧 id と同一 (trim / NFC 正規化後) は no-op で履歴に積まない", () => {
    expect(renameBlockInEditing("Gain_0", " Gain_0 ")).toBeNull();
    expect(useAppStore.getState().history.past).toHaveLength(0);
  });

  it("存在しない block は no-op", () => {
    expect(renameBlockInEditing("missing", "x")).toBeNull();
    expect(useAppStore.getState().history.past).toHaveLength(0);
  });
});

describe("renameBlockInEditing — undo / 履歴", () => {
  it("rename は 1 履歴 entry で、undo 1 発で完全復帰する", () => {
    const before = JSON.parse(JSON.stringify(model()));
    renameBlockInEditing("Gain_0", "トルクゲイン");
    const state = useAppStore.getState();
    expect(state.history.past).toHaveLength(1);
    state.undo();
    expect(model()).toEqual(before);
  });

  it("連続 rename は履歴をマージしない (mergeKey なし)", () => {
    renameBlockInEditing("Gain_0", "a");
    renameBlockInEditing("a", "b");
    expect(useAppStore.getState().history.past).toHaveLength(2);
  });
});

describe("renameBlockInEditing — R6 (非永続 GUI 状態)", () => {
  it("選択中ノードの選択が維持される", () => {
    useAppStore.setState({ selectedNodeIds: ["Gain_0"], selectedNodeId: "Gain_0" });
    renameBlockInEditing("Gain_0", "g");
    const s = useAppStore.getState();
    expect(s.selectedNodeIds).toEqual(["g"]);
    expect(s.selectedNodeId).toBe("g");
  });

  it("開いている Scope パネルと実行バッファが新 id に付け替わる", () => {
    const buffer = { times: [0, 1], values: [[0], [1]], nSignals: 1 };
    useAppStore.setState({
      scopePanels: ["Scope_0"],
      scopes: { Scope_0: buffer as never },
    });
    renameBlockInEditing("Scope_0", "速度計");
    const s = useAppStore.getState();
    expect(s.scopePanels).toEqual(["速度計"]);
    expect(Object.keys(s.scopes)).toEqual(["速度計"]);
    expect(s.scopes["速度計"]).toBe(buffer);
  });

  it('"__proto__" への rename で layout エントリが消えない (prototype-key 対策)', () => {
    // "__proto__" は XID 的に合法な id。素の代入だと Object.prototype の setter が
    // 呼ばれて own property が作られず、layout / scope_settings のエントリが
    // silent に消失する (security-reviewer MEDIUM-1 の回帰テスト)
    const err = renameBlockInEditing("Gain_0", "__proto__");
    expect(err).toBeNull();
    const m = model();
    expect(m.blocks[0]!.id).toBe("__proto__");
    expect(Object.keys(m.layout!)).toContain("__proto__");
    expect(m.layout!["__proto__"]).toEqual({ x: 0, y: 0 });
    expect(Object.keys(m.layout!)).toHaveLength(3);
    // prototype は汚染されていない
    expect(Object.getPrototypeOf(m.layout)).toBe(Object.prototype);
  });

  it("NFD 入力は NFC で格納される", () => {
    renameBlockInEditing("Gain_0", "がいん"); // NFD (か + U+3099)
    expect(model().blocks[0]!.id).toBe("がいん"); // NFC 合成済
  });
});
