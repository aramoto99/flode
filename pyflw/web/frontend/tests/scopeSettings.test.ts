// ADR-0044 §論点 4 / §論点 9: ``updateScopeSettings`` / ``resetScopeSettings`` の
// 動作テスト。
//
// v0.24.5 まで ``resetScopeSettings`` は object spread の挙動誤解で「単一 scope
// の設定」が削除されないバグ (= scope_settings dict が空になっても top-level
// に元の object 参照が残る) があった。本テストでその回帰を防ぐ。

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useAppStore } from "../src/store/appStore";
import type { FlwModel, ScopeSettings } from "../src/types/api";

function makeModel(scopeSettings?: Record<string, ScopeSettings>): FlwModel {
  const m: FlwModel = {
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
  if (scopeSettings) m.scope_settings = scopeSettings;
  return m;
}

beforeEach(() => {
  useAppStore.setState({
    editingModel: makeModel(),
    history: { past: [], future: [] },
    dirty: false,
  });
});

afterEach(() => {
  useAppStore.setState({
    editingModel: null,
    history: { past: [], future: [] },
  });
});

describe("updateScopeSettings", () => {
  it("creates scope_settings entry on first patch", () => {
    useAppStore
      .getState()
      .updateScopeSettings("Scope_0", { y_mode: "manual", y_min: -1, y_max: 1 });
    const m = useAppStore.getState().editingModel!;
    expect(m.scope_settings).toBeDefined();
    expect(m.scope_settings!["Scope_0"]).toEqual({
      y_mode: "manual",
      y_min: -1,
      y_max: 1,
    });
  });

  it("merges partial patches without dropping existing keys", () => {
    const st = useAppStore.getState();
    st.updateScopeSettings("Scope_0", { y_mode: "manual" });
    st.updateScopeSettings("Scope_0", { y_min: -5 });
    const m = useAppStore.getState().editingModel!;
    expect(m.scope_settings!["Scope_0"]).toEqual({
      y_mode: "manual",
      y_min: -5,
    });
  });

  it("sets dirty and pushes history", () => {
    useAppStore.getState().updateScopeSettings("Scope_0", { y_mode: "log" });
    const s = useAppStore.getState();
    expect(s.dirty).toBe(true);
    expect(s.history.past.length).toBe(1);
  });
});

describe("resetScopeSettings", () => {
  it("removes the entry for the given scope (multiple scopes case)", () => {
    useAppStore.setState({
      editingModel: makeModel({
        Scope_0: { y_mode: "manual", y_min: 0, y_max: 1 },
        Scope_1: { legend: "right" },
      }),
      history: { past: [], future: [] },
      dirty: false,
    });
    useAppStore.getState().resetScopeSettings("Scope_0");
    const m = useAppStore.getState().editingModel!;
    expect(m.scope_settings).toBeDefined();
    expect(m.scope_settings!["Scope_0"]).toBeUndefined();
    expect(m.scope_settings!["Scope_1"]).toEqual({ legend: "right" });
  });

  it("drops scope_settings key entirely when last entry is removed", () => {
    // v0.24.6 回帰防止: 旧実装は spread の挙動誤解で scope_settings が残っていた
    useAppStore.setState({
      editingModel: makeModel({
        Scope_0: { y_mode: "log", legend: "off" },
      }),
      history: { past: [], future: [] },
      dirty: false,
    });
    useAppStore.getState().resetScopeSettings("Scope_0");
    const m = useAppStore.getState().editingModel!;
    expect(m.scope_settings).toBeUndefined();
    expect("scope_settings" in m).toBe(false);
  });

  it("is a no-op when the scope has no entry", () => {
    useAppStore.setState({
      editingModel: makeModel({ Scope_1: { legend: "off" } }),
      history: { past: [], future: [] },
      dirty: false,
    });
    const before = useAppStore.getState().editingModel;
    useAppStore.getState().resetScopeSettings("Scope_0");
    const after = useAppStore.getState().editingModel;
    expect(after).toBe(before); // identity 不変 (= no set 呼び出し)
    expect(useAppStore.getState().dirty).toBe(false);
    expect(useAppStore.getState().history.past.length).toBe(0);
  });

  it("is a no-op when scope_settings is undefined", () => {
    // editingModel に scope_settings が無い初期状態
    const before = useAppStore.getState().editingModel;
    useAppStore.getState().resetScopeSettings("Scope_0");
    const after = useAppStore.getState().editingModel;
    expect(after).toBe(before);
    expect(useAppStore.getState().dirty).toBe(false);
  });

  it("is a no-op when editingModel is null", () => {
    useAppStore.setState({ editingModel: null });
    useAppStore.getState().resetScopeSettings("Scope_0");
    expect(useAppStore.getState().editingModel).toBeNull();
  });

  it("pushes to history (so undo can revive the cleared settings)", () => {
    useAppStore.setState({
      editingModel: makeModel({ Scope_0: { y_mode: "log" } }),
      history: { past: [], future: [] },
      dirty: false,
    });
    useAppStore.getState().resetScopeSettings("Scope_0");
    const s = useAppStore.getState();
    expect(s.dirty).toBe(true);
    expect(s.history.past.length).toBe(1);
  });
});
