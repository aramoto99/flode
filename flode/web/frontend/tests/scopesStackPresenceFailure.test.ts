// Bug: Scope ブロックが無いモデルで失敗した時、ログタブを載せる出力エリア
// (= scopes-stack pane) が存在せず失敗詳細を開けない (2026-09-11)。
// 出力エリアの presence 条件を「Scope あり **or** 失敗あり」に拡張した
// `normalizeScopesStackPresence` の回帰テスト。

import { beforeEach, describe, expect, it } from "vitest";

import { DEFAULT_TREE, DEFAULT_TREE_WITH_SCOPES, findLeaf } from "../src/lib/splitTree";
import { useAppStore } from "../src/store/appStore";
import type { FailurePayload } from "../src/types/api";

const _PAYLOAD: FailurePayload = {
  category: "divide_by_zero",
  template_key: "error.divide_by_zero",
  template_args: { block_label: "Divide1", t: 1.234 },
  block_id: "div_1",
  block_ids: ["div_1"],
  block_type: "flode.blocks.mathops.Divide",
  block_label: "Divide1",
  t: 1.234,
  raw_message: "ZeroDivisionError: float division by zero",
  raw_traceback: "tb",
};

function hasStack(): boolean {
  return findLeaf(useAppStore.getState().workspaceLayout, "scopes-stack");
}

beforeEach(() => {
  useAppStore.setState({
    workspaceLayout: DEFAULT_TREE,
    lastFailure: null,
    lastFailureSource: null,
    activeErrorTab: false,
    status: "idle",
  });
});

describe("normalizeScopesStackPresence — 失敗あり時の出力エリア常設", () => {
  it("Scope 無し + 失敗あり → scopes-stack pane が挿入される (再現テスト)", () => {
    useAppStore.getState().setLastFailure(_PAYLOAD, "runtime");
    useAppStore.getState().normalizeScopesStackPresence(false);
    expect(hasStack()).toBe(true);
  });

  it("Scope 無し + 失敗あり → 既存の pane は撤去されない", () => {
    useAppStore.setState({ workspaceLayout: DEFAULT_TREE_WITH_SCOPES });
    useAppStore.getState().setLastFailure(_PAYLOAD, "runtime");
    useAppStore.getState().normalizeScopesStackPresence(false);
    expect(hasStack()).toBe(true);
  });

  it("Scope 無し + 失敗クリア後 → pane は撤去される (v0.42.x の追従仕様を維持)", () => {
    useAppStore.getState().setLastFailure(_PAYLOAD, "runtime");
    useAppStore.getState().normalizeScopesStackPresence(false);
    useAppStore.getState().setLastFailure(null, "runtime");
    useAppStore.getState().normalizeScopesStackPresence(false);
    expect(hasStack()).toBe(false);
  });

  it("Scope 無し + 失敗無し → pane は挿入されない (既存挙動)", () => {
    useAppStore.getState().normalizeScopesStackPresence(false);
    expect(hasStack()).toBe(false);
  });

  it("Scope あり → 失敗の有無に関わらず pane が存在する (既存挙動)", () => {
    useAppStore.getState().normalizeScopesStackPresence(true);
    expect(hasStack()).toBe(true);
    useAppStore.getState().setLastFailure(_PAYLOAD, "runtime");
    useAppStore.getState().normalizeScopesStackPresence(true);
    expect(hasStack()).toBe(true);
  });
});
