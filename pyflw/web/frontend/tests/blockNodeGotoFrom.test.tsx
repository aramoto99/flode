// SPEC-0003 / ADR-0055: Goto / From のラベル render テスト。
//
// Canvas (BlockNodeView) で Goto は ``[tag]``、From は ``>tag>`` のラベルを
// 表示することを検証する。enum select / tag 編集は ParameterPanel 側の
// 既存パスで自動的に動くため別 test 不要。
// GotoTagVisibility (Scoped 用) は Amendment (2026-05-19) で Phase 2 送り。

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BlockNodeView } from "../src/components/BlockNodeView";

vi.mock("../src/store/appStore", () => ({
  useAppStore: () => undefined,
  updateBlockSize: vi.fn(),
}));

vi.mock("@xyflow/react", () => ({
  Handle: () => null,
  NodeResizer: () => null,
  Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
  useUpdateNodeInternals: () => vi.fn(),
}));

afterEach(() => {
  cleanup();
});

/** ヘルパ: BlockNodeView に渡す最小 NodeProps を構築。 */
function renderBlockNode(
  blockType: string,
  params: Record<string, unknown>,
  nInputs: number,
  nOutputs: number,
): void {
  // BlockNodeView は NodeProps を継承する Props を取る。テストでは最小限のフィールド
  // (data / id / selected) だけ与えれば label render branch に到達する。
  const data = {
    blockType,
    params,
    nInputs,
    nOutputs,
    connectedInputs: [],
    connectedOutputs: [],
  };
  // NodeProps の残りフィールドは any 経由でバイパス (テスト目的なので strict 型不要)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  render(<BlockNodeView data={data as any} id="test_block" selected={false} {...({} as any)} />);
}

describe("BlockNodeView: Goto / From labels (SPEC-0003)", () => {
  it("renders Goto as [tag]", () => {
    renderBlockNode(
      "pyflw.blocks.routing.Goto",
      { tag: "velocity", tag_visibility: "local" },
      1,
      0,
    );
    // Testing Library 推奨: ユーザーが見るテキストで検証
    expect(screen.getByText("[velocity]")).toBeTruthy();
  });

  it("renders From as >tag>", () => {
    renderBlockNode(
      "pyflw.blocks.routing.From",
      { tag: "velocity" },
      0,
      1,
    );
    expect(screen.getByText(">velocity>")).toBeTruthy();
  });

  it("renders '?' as fallback when tag is missing or non-string", () => {
    // Goto without tag → fallback to "?"
    renderBlockNode("pyflw.blocks.routing.Goto", {}, 1, 0);
    expect(screen.getByText("[?]")).toBeTruthy();
  });
});
