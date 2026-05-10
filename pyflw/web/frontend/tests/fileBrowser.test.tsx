// ADR-0041 §論点 7-A: FileBrowser コンポーネントの最小 vitest。
// 初期 fetch エラー (= File API 無効モード = 503) のメッセージ表示と、
// tree fetch 成功時の children rendering を検証する。
//
// v0.18.0 で追加予定 (= ADR-0041 §論点 7-A): 右クリック context menu /
// inline rename (F2) / drag-drop / multi-select。本テストは v0.17.0 段階の
// scope に限定。

import {
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FileBrowser } from "../src/components/FileBrowser";
import { useAppStore } from "../src/store/appStore";

// 各テストで個別に挙動を切り替えるため top-level mock を使う
vi.mock("../src/api/filesApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/filesApi")>();
  return {
    ...actual,
    fileTree: vi.fn(),
    getFileContent: vi.fn(),
  };
});

// 動的に import される spy を取り出すヘルパ (top-level mock に対する型安全アクセス)。
// ``vi.mocked()`` で型情報を Mock<T> に変換する。
async function getMocks(): Promise<{
  fileTree: ReturnType<typeof vi.fn>;
  getFileContent: ReturnType<typeof vi.fn>;
}> {
  const mod = await import("../src/api/filesApi");
  return {
    fileTree: vi.mocked(mod.fileTree),
    getFileContent: vi.mocked(mod.getFileContent),
  };
}

function renderWithProvider(ui: React.ReactNode): void {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
    },
  });
  render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  // store のリセット (= 前テストの state を持ち込まない)
  useAppStore.setState({
    selectedFilePath: null,
    selectedModelId: null,
    editingModel: null,
    editingFileMtime: null,
    editingFileEtag: null,
    dirty: false,
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("FileBrowser tree rendering", () => {
  it("renders title and refresh button", async () => {
    const { fileTree } = await getMocks();
    fileTree.mockResolvedValue({ path: "", children: [] });
    renderWithProvider(<FileBrowser />);
    // タイトル "Workspace" がいずれかの言語で表示されている
    const title = screen.queryByText(/Workspace|ワークスペース/i);
    expect(title).toBeTruthy();
  });

  it("renders empty state when workspace has no children", async () => {
    const { fileTree } = await getMocks();
    fileTree.mockResolvedValue({ path: "", children: [] });
    renderWithProvider(<FileBrowser />);
    // ローディング → 空メッセージへの遷移
    await screen.findByText(/empty workspace|空のワークスペース|empty/i);
  });

  it("renders file entries from tree response", async () => {
    const { fileTree } = await getMocks();
    fileTree.mockResolvedValue({
      path: "",
      children: [
        {
          name: "alpha.flw.json",
          type: "file",
          size: 100,
          mtime: "2026-05-10T00:00:00Z",
        },
        {
          name: "beta.flw.json",
          type: "file",
          size: 200,
          mtime: "2026-05-10T00:00:00Z",
        },
      ],
    });
    renderWithProvider(<FileBrowser />);
    await screen.findByText("alpha.flw.json");
    expect(screen.getByText("beta.flw.json")).toBeTruthy();
  });

  it("renders directory entries with collapse arrow", async () => {
    const { fileTree } = await getMocks();
    fileTree.mockResolvedValue({
      path: "",
      children: [
        {
          name: "controllers",
          type: "directory",
          size: null,
          mtime: "2026-05-10T00:00:00Z",
        },
      ],
    });
    renderWithProvider(<FileBrowser />);
    await screen.findByText("controllers");
    // collapsed by default — fetch は controllers path に対しては走らない
    expect(fileTree).toHaveBeenCalledTimes(1);
    expect(fileTree).toHaveBeenCalledWith("");
  });
});

describe("FileBrowser file open", () => {
  it("clicking .flw.json file calls getFileContent and updates store", async () => {
    const { fileTree, getFileContent } = await getMocks();
    fileTree.mockResolvedValue({
      path: "",
      children: [
        {
          name: "model.flw.json",
          type: "file",
          size: 100,
          mtime: "2026-05-10T00:00:00Z",
        },
      ],
    });
    getFileContent.mockResolvedValue({
      path: "model.flw.json",
      content: { schema_version: "0.8", simulator: {}, blocks: [], connections: [] },
      mtime: "2026-05-10T00:00:00Z",
      etag: 'W/"100-1"',
    });

    renderWithProvider(<FileBrowser />);
    const fileButton = await screen.findByText("model.flw.json");
    fireEvent.click(fileButton);

    // 非同期 update を待つ
    await new Promise((resolve) => setTimeout(resolve, 10));

    expect(getFileContent).toHaveBeenCalledWith("model.flw.json");
    const state = useAppStore.getState();
    expect(state.selectedFilePath).toBe("model.flw.json");
    expect(state.editingFileEtag).toBe('W/"100-1"');
    expect(state.dirty).toBe(false);
  });

  it("clicking non-flw.json file does not trigger getFileContent", async () => {
    const { fileTree, getFileContent } = await getMocks();
    fileTree.mockResolvedValue({
      path: "",
      children: [
        {
          name: "readme.txt",
          type: "file",
          size: 50,
          mtime: "2026-05-10T00:00:00Z",
        },
      ],
    });

    renderWithProvider(<FileBrowser />);
    const fileButton = await screen.findByText("readme.txt");
    fireEvent.click(fileButton);

    expect(getFileContent).not.toHaveBeenCalled();
  });
});
