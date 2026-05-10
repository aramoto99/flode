// v0.20.0: appStore の undo / redo 履歴管理テスト。
//
// editingModel に対する applyEditingModel 呼び出しが past を蓄積し、undo/redo
// で正しく状態を遷移させることを検証する。

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  HISTORY_MAX,
  useAppStore,
} from "../src/store/appStore";
import type { FlwModel } from "../src/types/api";

function emptyModel(): FlwModel {
  return {
    schema_version: "0.8",
    metadata: { name: "test" },
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

/** `simulator.dt` を新しい値で書き換えた model を返す applyEditingModel 用ヘルパ。 */
function setDt(dt: number): (m: FlwModel) => FlwModel {
  return (m) => ({ ...m, simulator: { ...m.simulator, dt } });
}

beforeEach(() => {
  // store を初期状態に
  useAppStore.setState({
    editingModel: emptyModel(),
    history: { past: [], future: [] },
    dirty: false,
    selectedModelId: null,
    selectedFilePath: null,
  });
});

afterEach(() => {
  useAppStore.setState({
    editingModel: null,
    history: { past: [], future: [] },
  });
});

describe("history initial state", () => {
  it("empty history → canUndo / canRedo false", () => {
    const state = useAppStore.getState();
    expect(state.canUndo()).toBe(false);
    expect(state.canRedo()).toBe(false);
  });
});

describe("applyEditingModel pushes to past", () => {
  it("applyEditingModel pushes previous state to past", () => {
    const before = useAppStore.getState().editingModel!;
    useAppStore.getState().applyEditingModel(setDt(0.001));
    const after = useAppStore.getState();
    expect(after.history.past).toHaveLength(1);
    expect(after.history.past[0]?.simulator.dt).toBe(before.simulator.dt);
    expect(after.editingModel?.simulator.dt).toBe(0.001);
    expect(after.dirty).toBe(true);
  });

  it("clears future on new edit (= redo 候補は破棄)", () => {
    const state = useAppStore.getState();
    state.applyEditingModel(setDt(0.001));
    state.undo();
    expect(useAppStore.getState().history.future).toHaveLength(1);
    // 別の編集をすると future がクリア
    state.applyEditingModel(setDt(0.5));
    expect(useAppStore.getState().history.future).toHaveLength(0);
  });

  it("no-op fn (= return same reference) does not push history", () => {
    const state = useAppStore.getState();
    state.applyEditingModel((m) => m);
    expect(useAppStore.getState().history.past).toHaveLength(0);
  });

  it("history is capped at HISTORY_MAX", () => {
    const state = useAppStore.getState();
    for (let i = 0; i < HISTORY_MAX + 10; i++) {
      state.applyEditingModel(setDt(i + 1));
    }
    expect(useAppStore.getState().history.past).toHaveLength(HISTORY_MAX);
  });
});

describe("undo / redo round trip", () => {
  it("undo restores previous state, redo re-applies", () => {
    const state = useAppStore.getState();
    state.applyEditingModel(setDt(0.001));
    state.applyEditingModel(setDt(0.5));

    expect(useAppStore.getState().editingModel?.simulator.dt).toBe(0.5);

    state.undo();
    expect(useAppStore.getState().editingModel?.simulator.dt).toBe(0.001);

    state.undo();
    expect(useAppStore.getState().editingModel?.simulator.dt).toBe(0.01); // 初期

    state.redo();
    expect(useAppStore.getState().editingModel?.simulator.dt).toBe(0.001);

    state.redo();
    expect(useAppStore.getState().editingModel?.simulator.dt).toBe(0.5);
  });

  it("undo at empty past is a no-op", () => {
    const state = useAppStore.getState();
    state.undo();
    expect(useAppStore.getState().history.past).toHaveLength(0);
    expect(useAppStore.getState().history.future).toHaveLength(0);
  });

  it("redo at empty future is a no-op", () => {
    const state = useAppStore.getState();
    state.redo();
    expect(useAppStore.getState().history.future).toHaveLength(0);
  });

  it("undo sets dirty=true (= 次回保存対象)", () => {
    const state = useAppStore.getState();
    state.applyEditingModel(setDt(0.001));
    useAppStore.setState({ dirty: false }); // 保存後の状態を仮定
    state.undo();
    expect(useAppStore.getState().dirty).toBe(true);
  });
});

describe("setEditingModel clears history", () => {
  it("setEditingModel(null) clears past and future", () => {
    const state = useAppStore.getState();
    state.applyEditingModel(setDt(0.001));
    state.applyEditingModel(setDt(0.5));
    state.undo();
    // ここで past=1, future=1 の状態
    expect(useAppStore.getState().history.past.length).toBeGreaterThan(0);

    state.setEditingModel(emptyModel());
    expect(useAppStore.getState().history.past).toHaveLength(0);
    expect(useAppStore.getState().history.future).toHaveLength(0);
  });
});

describe("selectFilePath / selectModel clears history", () => {
  it("selectFilePath clears history (= 別ファイルと混ぜない)", () => {
    const state = useAppStore.getState();
    state.applyEditingModel(setDt(0.001));
    expect(useAppStore.getState().history.past.length).toBeGreaterThan(0);
    state.selectFilePath("foo.flw.json");
    expect(useAppStore.getState().history.past).toHaveLength(0);
  });

  it("selectModel clears history", () => {
    const state = useAppStore.getState();
    state.applyEditingModel(setDt(0.001));
    state.selectModel("test");
    expect(useAppStore.getState().history.past).toHaveLength(0);
  });
});
