// SPEC-0022 §機能要件 2/6: renameBlockInEditing のエッジケース補強テスト。
//
// 既存 tests/renameBlock.test.ts (R1〜R6 の基本ケース) を補完し、以下を検証する:
// - branch_waypoints で同一 prefix の複数キー ("<id>:0" と "<id>:1") が両方付け替わる
// - id の prefix が部分一致するだけのキー (e.g. "Gain_00:0") は誤って書き換えない
// - 無関係のキー (別 id) は不変
// - Subsystem 自身を root scope (editingPath=[]) で rename したとき、
//   layout / branch_waypoints は追従し、内部 params (nested blocks/layout) は
//   完全に不変 (同一参照) であること
// - workspaceLayout の `scope:<id>` 葉が splitTree 経由で付け替わる (R6)
// - editingScopeSettingsId が新 id に追従する (R6)

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { INPORT_TYPE, SUBSYSTEM_TYPE } from "../src/lib/blockTypes";
import { makeWorkspaceLayoutKey } from "../src/lib/storageKeys";
import type { SplitTree } from "../src/lib/splitTree";
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
      { id: "Gain_00", type: GAIN, params: { k: 9 } },
      { id: "Scope_0", type: SCOPE, params: {} },
      {
        id: "Sub_0",
        type: SUBSYSTEM,
        params: {
          blocks: [
            { id: "Inport_0", type: INPORT, params: { port_idx: 0 } },
            { id: "Inner_Gain", type: GAIN, params: { k: 5 } },
          ],
          connections: [
            { src: "Inport_0", src_idx: 0, dst: "Inner_Gain", dst_idx: 0 },
          ],
          layout: { Inport_0: { x: 0, y: 0 }, Inner_Gain: { x: 100, y: 0 } },
          branch_waypoints: { "Inport_0:0": { axis: "x", pos: 50 } },
        },
      },
    ],
    connections: [
      { src: "Gain_0", src_idx: 0, dst: "Scope_0", dst_idx: 0 },
      { src: "Gain_0", src_idx: 0, dst: "Sub_0", dst_idx: 0 },
    ],
    layout: {
      Gain_0: { x: 0, y: 0 },
      Gain_00: { x: 0, y: 200 },
      Scope_0: { x: 200, y: 0 },
      Sub_0: { x: 200, y: 100 },
    },
    branch_waypoints: {
      "Gain_0:0": { axis: "x", pos: 150 },
      "Gain_0:1": { axis: "y", pos: 250 },
      "Gain_00:0": { axis: "x", pos: 5 },
    },
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
    editingScopeSettingsId: null,
    workspaceHash: null,
    activeTabFilePath: null,
  });
  window.localStorage.clear();
});

afterEach(() => {
  useAppStore.setState({
    editingModel: null,
    editingPath: [],
    history: { past: [], future: [] },
    scopePanels: [],
    scopes: {},
    editingScopeSettingsId: null,
    workspaceHash: null,
    activeTabFilePath: null,
  });
  window.localStorage.clear();
});

function model(): FlwModel {
  return useAppStore.getState().editingModel!;
}

describe("renameBlockInEditing — branch_waypoints の複数キー / prefix 部分一致", () => {
  it("同一 prefix の複数キー (id:0, id:1) が両方付け替わる", () => {
    const err = renameBlockInEditing("Gain_0", "トルクゲイン");
    expect(err).toBeNull();
    expect(model().branch_waypoints).toEqual({
      "トルクゲイン:0": { axis: "x", pos: 150 },
      "トルクゲイン:1": { axis: "y", pos: 250 },
      "Gain_00:0": { axis: "x", pos: 5 },
    });
  });

  it("id の prefix が部分一致するだけのキー (Gain_00:0) は書き換えない", () => {
    renameBlockInEditing("Gain_0", "x");
    const wp = model().branch_waypoints!;
    // 完全一致した Gain_0:* のみ x:* に付け替わる
    expect(wp).toHaveProperty("x:0");
    expect(wp).toHaveProperty("x:1");
    // "Gain_0" で始まるだけの "Gain_00:0" は誤って "x0:0" 等に書き換わらず元のまま残る
    expect(wp).toHaveProperty("Gain_00:0");
    expect(wp["Gain_00:0"]).toEqual({ axis: "x", pos: 5 });
  });

  it("Gain_00 自身を rename しても Gain_0 の waypoints は不変", () => {
    renameBlockInEditing("Gain_00", "別ゲイン");
    const wp = model().branch_waypoints!;
    expect(wp).toEqual({
      "Gain_0:0": { axis: "x", pos: 150 },
      "Gain_0:1": { axis: "y", pos: 250 },
      "別ゲイン:0": { axis: "x", pos: 5 },
    });
  });
});

describe("renameBlockInEditing — Subsystem 自身の rename (editingPath=[])", () => {
  it("layout / 参照は追従し、内部 params は完全に不変 (同一参照)", () => {
    const beforeParams = model().blocks[3]!.params;
    const err = renameBlockInEditing("Sub_0", "モータ制御");
    expect(err).toBeNull();
    const m = model();
    expect(m.blocks.map((b) => b.id)).toEqual([
      "Gain_0",
      "Gain_00",
      "Scope_0",
      "モータ制御",
    ]);
    expect(m.connections[1]).toEqual({
      src: "Gain_0",
      src_idx: 0,
      dst: "モータ制御",
      dst_idx: 0,
    });
    expect(m.layout).toHaveProperty("モータ制御");
    expect(m.layout).not.toHaveProperty("Sub_0");
    // 内部 params (nested blocks/connections/layout/branch_waypoints) はビット単位で不変
    expect(m.blocks[3]!.params).toBe(beforeParams);
  });

  it("Subsystem 自身に紐づく branch_waypoints も付け替わる", () => {
    useAppStore.setState((s) => {
      const m = s.editingModel!;
      return {
        editingModel: {
          ...m,
          branch_waypoints: { ...m.branch_waypoints, "Sub_0:0": { axis: "y", pos: 30 } },
        },
      };
    });
    renameBlockInEditing("Sub_0", "モータ制御");
    const wp = model().branch_waypoints!;
    expect(wp).toHaveProperty("モータ制御:0");
    expect(wp).not.toHaveProperty("Sub_0:0");
  });
});

describe("renameBlockInEditing — workspaceLayout の scope:<id> 葉付け替え (R6)", () => {
  function treeWithScopeLeaf(): SplitTree {
    return {
      kind: "split",
      orientation: "horizontal",
      ratio: 0.6,
      a: { kind: "leaf", paneId: "diagram" },
      b: { kind: "leaf", paneId: "scope:Scope_0" },
    };
  }

  it("scope:<oldId> 葉が scope:<newId> に付け替わる", () => {
    useAppStore.setState({ workspaceLayout: treeWithScopeLeaf() });
    renameBlockInEditing("Scope_0", "速度計");
    const tree = useAppStore.getState().workspaceLayout;
    expect(tree).toEqual({
      kind: "split",
      orientation: "horizontal",
      ratio: 0.6,
      a: { kind: "leaf", paneId: "diagram" },
      b: { kind: "leaf", paneId: "scope:速度計" },
    });
  });

  it("scope:<id> 葉が存在しない場合は workspaceLayout に触れない", () => {
    const originalTree: SplitTree = { kind: "leaf", paneId: "diagram" };
    useAppStore.setState({ workspaceLayout: originalTree });
    renameBlockInEditing("Scope_0", "速度計");
    expect(useAppStore.getState().workspaceLayout).toBe(originalTree);
  });

  it("workspaceHash / activeTabFilePath が確定していれば localStorage に永続化される", () => {
    useAppStore.setState({
      workspaceLayout: treeWithScopeLeaf(),
      workspaceHash: "hash123",
      activeTabFilePath: "demo.flw.json",
    });
    renameBlockInEditing("Scope_0", "速度計");
    const key = makeWorkspaceLayoutKey("hash123", "demo.flw.json");
    const stored = window.localStorage.getItem(key);
    expect(stored).not.toBeNull();
    expect(stored).toContain("scope:速度計");
  });

  it("workspaceHash が未確定 (null) でも例外にならない (no-op)", () => {
    useAppStore.setState({
      workspaceLayout: treeWithScopeLeaf(),
      workspaceHash: null,
      activeTabFilePath: null,
    });
    expect(() => renameBlockInEditing("Scope_0", "速度計")).not.toThrow();
  });
});

describe("renameBlockInEditing — editingScopeSettingsId の追従 (R6)", () => {
  it("編集中の scope_settings ダイアログの対象 id が新 id に追従する", () => {
    useAppStore.setState({ editingScopeSettingsId: "Scope_0" });
    renameBlockInEditing("Scope_0", "速度計");
    expect(useAppStore.getState().editingScopeSettingsId).toBe("速度計");
  });

  it("rename 対象と無関係なら editingScopeSettingsId は不変", () => {
    useAppStore.setState({ editingScopeSettingsId: "Scope_0" });
    renameBlockInEditing("Gain_0", "x");
    expect(useAppStore.getState().editingScopeSettingsId).toBe("Scope_0");
  });
});
