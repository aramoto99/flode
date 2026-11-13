// ADR-0081 §論点 3 (U5 レビュー対応): 消えた引数の除去をユーザーに分かる形にする。
// - 再読み込みの直後、開いているモデルに消えた引数があれば warning トースト
// - 保存・実行で実際に除去したら warning トースト (同じ組はセッション中 1 回)
// - 除去は「最新の取得に成功した registry」でだけ行う (invalidate 済み・取得中は除去しない)
// - モデルを開くと registry を invalidate する
// - Save As (MenuBar) と「保存して開く」(FileBrowser) も除去を通る

import i18n from "../src/i18n";

import { QueryClientProvider } from "@tanstack/react-query";
import { ReactFlowProvider } from "@xyflow/react";
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "../src/api/client";
import * as filesApi from "../src/api/filesApi";
import { FileBrowser } from "../src/components/FileBrowser";
import { MenuBar } from "../src/components/MenuBar";
import {
  _resetRemovalNoticesForTest,
  freshRegistryIndex,
  prepareModelForBackend,
} from "../src/lib/modelForBackend";
import { queryClient } from "../src/lib/queryClient";
import { BLOCKS_REGISTRY_QUERY_KEY } from "../src/lib/queryKeys";
import { useBlockReload } from "../src/lib/useBlockReload";
import { useAppStore } from "../src/store/appStore";
import { clearAllToasts, useToastStore } from "../src/store/toastStore";
import type { BlockMetadata, BlockReloadResponse, FlwModel } from "../src/types/api";

vi.mock("../src/api/filesApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/filesApi")>();
  return {
    ...actual,
    putFileContent: vi.fn(async () => ({ path: "x", mtime: 1, etag: "e1" })),
    getFileContent: vi.fn(),
    fileTree: vi.fn(),
  };
});
vi.mock("../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/client")>();
  return { ...actual, reloadBlocks: vi.fn() };
});

const putFileContent = vi.mocked(filesApi.putFileContent);
const getFileContent = vi.mocked(filesApi.getFileContent);
const fileTree = vi.mocked(filesApi.fileTree);
const reloadBlocks = vi.mocked(client.reloadBlocks);

const USER_TYPE = "flode_ws.filters.Trim";

const USER_META: BlockMetadata = {
  type_path: USER_TYPE,
  display_name: "Trim",
  category: "",
  icon: "default",
  docstring_summary: "",
  params_spec: [{ name: "k", type: "float", has_default: true, default: 1, description: "" }],
  default_n_inputs: 1,
  default_n_outputs: 1,
  port_shapes_in_default: [[]],
  port_shapes_out_default: [[]],
  tags: [],
  is_container: false,
  mask_capable: false,
  source: "workspace",
};

function model(params: Record<string, unknown>): FlwModel {
  return {
    schema_version: "0.15",
    simulator: { t_end: 1, dt: 0.01, solver: "RK45", rtol: 1e-3, atol: 1e-6, dt_base: null },
    blocks: [{ id: "t", type: USER_TYPE, params }],
    connections: [],
    layout: {},
  };
}

function setRegistry(): void {
  queryClient.setQueryData(BLOCKS_REGISTRY_QUERY_KEY, {
    schema_version: "blocks.v3",
    blocks: [USER_META],
  });
}

function warnings(): string[] {
  return useToastStore
    .getState()
    .toasts.filter((t) => t.severity === "warning")
    .map((t) => t.message);
}

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

beforeEach(() => {
  setRegistry();
  _resetRemovalNoticesForTest();
  clearAllToasts();
  putFileContent.mockClear();
  useAppStore.setState({
    editingModel: model({ k: 2, bias: 1 }),
    editingPath: [],
    selectedFilePath: "m.flw.json",
    editingFileEtag: "e0",
    dirty: true,
    tabs: [],
    activeTabFilePath: "m.flw.json",
  });
});

afterEach(() => {
  cleanup();
  queryClient.removeQueries({ queryKey: BLOCKS_REGISTRY_QUERY_KEY });
  queryClient.removeQueries({ queryKey: ["files-tree"] });
});

describe("notice when values are removed on save / run", () => {
  it("shows one warning toast per (block, parameter) set in the session", () => {
    const m = useAppStore.getState().editingModel!;
    const pruned = prepareModelForBackend(m);
    expect(pruned.blocks[0]!.params).toEqual({ k: 2 });
    expect(warnings()).toHaveLength(1);
    expect(warnings()[0]).toContain("t (bias)");
    // 同じ組の 2 回目 (undo で戻った等) は知らせない
    prepareModelForBackend(model({ k: 2, bias: 1 }));
    expect(warnings()).toHaveLength(1);
    // 新しい組は知らせる
    prepareModelForBackend(model({ k: 2, gain: 1 }));
    expect(warnings()).toHaveLength(2);
  });
});

describe("removal only with the latest successfully fetched registry", () => {
  it("does not remove anything while the registry is invalidated / not fetched", async () => {
    await queryClient.invalidateQueries({ queryKey: BLOCKS_REGISTRY_QUERY_KEY });
    expect(freshRegistryIndex()).toBeUndefined();
    const m = useAppStore.getState().editingModel!;
    expect(prepareModelForBackend(m)).toBe(m);
    expect(warnings()).toHaveLength(0);
    queryClient.removeQueries({ queryKey: BLOCKS_REGISTRY_QUERY_KEY });
    expect(prepareModelForBackend(m)).toBe(m);
    // 取得し直せば除去する
    setRegistry();
    expect(freshRegistryIndex()?.has(USER_TYPE)).toBe(true);
    expect(prepareModelForBackend(m)).not.toBe(m);
  });

  it("invalidates the registry when a model is opened", () => {
    useAppStore.getState().openFileInTab("other.flw.json", model({ k: 1 }), "1", "e");
    expect(queryClient.getQueryState(BLOCKS_REGISTRY_QUERY_KEY)?.isInvalidated).toBe(true);
    expect(freshRegistryIndex()).toBeUndefined();
  });
});

describe("notice right after a reload", () => {
  it("warns about blocks in the open model that lost parameters", async () => {
    reloadBlocks.mockResolvedValue({
      schema_version: "blocks.v3",
      blocks: [USER_META],
      added: [],
      removed: [],
      changed: [USER_TYPE],
      restart_required_sources: [],
      errors: [],
    } as BlockReloadResponse);
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useBlockReload(), { wrapper });
    await act(async () => {
      await result.current.reload();
    });
    expect(warnings()).toHaveLength(1);
    expect(warnings()[0]).toContain("1 block(s)");
    expect(warnings()[0]).toContain("t (bias)");
    // 再読み込み自体はモデルを書き換えない
    expect(useAppStore.getState().editingModel!.blocks[0]!.params).toEqual({ k: 2, bias: 1 });
  });
});

describe("other save paths use the same removal", () => {
  it("Save As (MenuBar)", async () => {
    getFileContent.mockResolvedValue({
      path: "copy.flw.json",
      content: model({ k: 2 }),
      mtime: "1",
      etag: "e2",
    } as never);
    render(
      <QueryClientProvider client={queryClient}>
        <ReactFlowProvider>
          <MenuBar />
        </ReactFlowProvider>
      </QueryClientProvider>,
    );
    fireEvent.keyDown(window, { key: "S", ctrlKey: true, shiftKey: true });
    const input = await screen.findByDisplayValue("m_copy.flw.json");
    fireEvent.change(input, { target: { value: "copy.flw.json" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(putFileContent).toHaveBeenCalled());
    expect(putFileContent.mock.calls[0]![0]).toBe("copy.flw.json");
    expect(putFileContent.mock.calls[0]![1].blocks[0]!.params).toEqual({ k: 2 });
  });

  it("Save & Open (FileBrowser)", async () => {
    fileTree.mockResolvedValue({
      path: "",
      children: [
        { name: "m.flw.json", type: "file", size: 1, mtime: "1" },
        { name: "next.flw.json", type: "file", size: 1, mtime: "1" },
      ],
    } as never);
    getFileContent.mockResolvedValue({
      path: "next.flw.json",
      content: model({ k: 1 }),
      mtime: "1",
      etag: "e3",
    } as never);
    render(
      <QueryClientProvider client={queryClient}>
        <FileBrowser />
      </QueryClientProvider>,
    );
    fireEvent.click(await screen.findByText("next.flw.json"));
    fireEvent.click(await screen.findByText("Save & Open"));
    await waitFor(() => expect(putFileContent).toHaveBeenCalled());
    expect(putFileContent.mock.calls[0]![0]).toBe("m.flw.json");
    expect(putFileContent.mock.calls[0]![1].blocks[0]!.params).toEqual({ k: 2 });
  });
});
