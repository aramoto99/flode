// SPEC-0022 §機能要件 1-3: F2 ショートカットの起動ゲート単体テスト。
//
// useShortcuts.ts の F2 ハンドラは「単一ノード選択中のみ」renameRequest を
// 発火する。BlockIdLabel 側の反応 (renameRequest を受けて編集モードに入る) は
// tests/blockRenameInline.test.tsx で既にカバー済みなので、本ファイルは
// useShortcuts の gating ロジック (選択数 / テキスト編集中の抑止) のみを扱う。

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useShortcuts } from "../src/lib/useShortcuts";
import { useAppStore } from "../src/store/appStore";

// listBlockMetadata だけ stub (useShortcuts が Enter ハンドラ用に参照する registry
// query。F2 ロジックは registry を使わないが、useQuery 自体は必ず走る)。
vi.mock("../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/client")>();
  return { ...actual, listBlockMetadata: vi.fn(async () => ({ blocks: [] })) };
});

function Harness(): React.JSX.Element {
  useShortcuts();
  return <input data-testid="text-input" />;
}

function renderHarness(): ReturnType<typeof render> {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Harness />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useAppStore.setState({ selectedNodeIds: [], renameRequest: null });
});

afterEach(() => {
  cleanup();
  useAppStore.setState({ selectedNodeIds: [], renameRequest: null });
});

describe("useShortcuts — F2 rename gating", () => {
  it("単一ノード選択中は F2 で renameRequest が発火する", () => {
    useAppStore.setState({ selectedNodeIds: ["Gain_0"] });
    renderHarness();
    fireEvent.keyDown(window, { key: "F2" });
    const req = useAppStore.getState().renameRequest;
    expect(req?.blockId).toBe("Gain_0");
    expect(req?.nonce).toBeGreaterThan(0);
  });

  it("複数選択中は F2 で発火しない", () => {
    useAppStore.setState({ selectedNodeIds: ["Gain_0", "Gain_1"] });
    renderHarness();
    fireEvent.keyDown(window, { key: "F2" });
    expect(useAppStore.getState().renameRequest).toBeNull();
  });

  it("未選択では F2 で発火しない", () => {
    useAppStore.setState({ selectedNodeIds: [] });
    renderHarness();
    fireEvent.keyDown(window, { key: "F2" });
    expect(useAppStore.getState().renameRequest).toBeNull();
  });

  it("テキスト編集中 (input にフォーカス) は F2 で発火しない", () => {
    useAppStore.setState({ selectedNodeIds: ["Gain_0"] });
    renderHarness();
    const input = screen.getByTestId("text-input");
    fireEvent.keyDown(input, { key: "F2" });
    expect(useAppStore.getState().renameRequest).toBeNull();
  });

  it("同一ブロックへの連続 F2 でも nonce が単調増加する (再発火できる)", () => {
    useAppStore.setState({ selectedNodeIds: ["Gain_0"] });
    renderHarness();
    fireEvent.keyDown(window, { key: "F2" });
    const first = useAppStore.getState().renameRequest!.nonce;
    fireEvent.keyDown(window, { key: "F2" });
    const second = useAppStore.getState().renameRequest!.nonce;
    expect(second).toBeGreaterThan(first);
  });
});
