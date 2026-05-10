// ADR-0041 §論点 11-A: useExternalChangesPoll hook のテスト。
//
// 5 秒 polling で `getFileContent` を叩き、etag 不一致を検出する挙動を検証する。
// 主要シナリオ:
//   - selectedFilePath が null → polling しない
//   - dirty=false で etag 変化 → silent reload (= editingModel を上書き)
//   - dirty=true で etag 変化 → window.confirm が呼ばれる
//   - simulation 実行中 → polling しない

import { renderHook } from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { useExternalChangesPoll } from "../src/lib/useExternalChangesPoll";
import { useAppStore } from "../src/store/appStore";

vi.mock("../src/api/filesApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/filesApi")>();
  return {
    ...actual,
    getFileContent: vi.fn(),
  };
});

async function getMocks(): Promise<{
  getFileContent: ReturnType<typeof vi.fn>;
}> {
  const mod = await import("../src/api/filesApi");
  return { getFileContent: vi.mocked(mod.getFileContent) };
}

beforeEach(() => {
  vi.useFakeTimers();
  useAppStore.setState({
    selectedFilePath: null,
    selectedModelId: null,
    editingModel: null,
    editingFileMtime: null,
    editingFileEtag: null,
    dirty: false,
    status: "idle",
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("useExternalChangesPoll: when no file selected", () => {
  it("does not poll when selectedFilePath is null", async () => {
    const { getFileContent } = await getMocks();
    renderHook(() => useExternalChangesPoll());
    await vi.advanceTimersByTimeAsync(20_000); // 4 ticks 分
    expect(getFileContent).not.toHaveBeenCalled();
  });
});

describe("useExternalChangesPoll: silent reload (dirty=false)", () => {
  it("reloads editingModel silently when etag changed and not dirty", async () => {
    const { getFileContent } = await getMocks();
    useAppStore.setState({
      selectedFilePath: "demo.flw.json",
      editingModel: { schema_version: "0.8" } as never,
      editingFileEtag: 'W/"100-1"',
      editingFileMtime: "2026-05-10T00:00:00Z",
      dirty: false,
    });
    getFileContent.mockResolvedValue({
      path: "demo.flw.json",
      content: { schema_version: "0.8", marker: "external" },
      mtime: "2026-05-10T00:01:00Z",
      etag: 'W/"200-2"', // 違う etag
    });

    renderHook(() => useExternalChangesPoll());
    // 5 秒 advance → 1 tick
    await vi.advanceTimersByTimeAsync(5100);

    expect(getFileContent).toHaveBeenCalledWith("demo.flw.json");
    const state = useAppStore.getState();
    // silent reload で editingModel + etag が更新されている
    expect((state.editingModel as { marker?: string } | null)?.marker).toBe(
      "external",
    );
    expect(state.editingFileEtag).toBe('W/"200-2"');
    expect(state.dirty).toBe(false);
  });

  it("does NOT reload when etag matches (= no change)", async () => {
    const { getFileContent } = await getMocks();
    useAppStore.setState({
      selectedFilePath: "demo.flw.json",
      editingModel: { schema_version: "0.8", original: true } as never,
      editingFileEtag: 'W/"100-1"',
      dirty: false,
    });
    getFileContent.mockResolvedValue({
      path: "demo.flw.json",
      content: { schema_version: "0.8", original: false },
      mtime: "2026-05-10T00:00:00Z",
      etag: 'W/"100-1"', // 同じ etag
    });

    renderHook(() => useExternalChangesPoll());
    await vi.advanceTimersByTimeAsync(5100);

    const state = useAppStore.getState();
    // etag 一致 → editingModel は変更されていない
    expect((state.editingModel as { original?: boolean }).original).toBe(true);
  });
});

describe("useExternalChangesPoll: dirty + external change → confirm", () => {
  it("prompts user via window.confirm when dirty and etag differs", async () => {
    const { getFileContent } = await getMocks();
    useAppStore.setState({
      selectedFilePath: "demo.flw.json",
      editingModel: { schema_version: "0.8", local: true } as never,
      editingFileEtag: 'W/"100-1"',
      dirty: true,
    });
    getFileContent.mockResolvedValue({
      path: "demo.flw.json",
      content: { schema_version: "0.8", external: true },
      mtime: "2026-05-10T00:01:00Z",
      etag: 'W/"200-2"',
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    renderHook(() => useExternalChangesPoll());
    await vi.advanceTimersByTimeAsync(5100);

    expect(confirmSpy).toHaveBeenCalled();
    // OK 選択 → 外部変更を取り込み
    const state = useAppStore.getState();
    expect((state.editingModel as { external?: boolean }).external).toBe(true);
    expect(state.dirty).toBe(false);

    confirmSpy.mockRestore();
  });

  it("preserves local changes when user cancels confirm", async () => {
    const { getFileContent } = await getMocks();
    useAppStore.setState({
      selectedFilePath: "demo.flw.json",
      editingModel: { schema_version: "0.8", local: true } as never,
      editingFileEtag: 'W/"100-1"',
      dirty: true,
    });
    getFileContent.mockResolvedValue({
      path: "demo.flw.json",
      content: { schema_version: "0.8", external: true },
      mtime: "2026-05-10T00:01:00Z",
      etag: 'W/"200-2"',
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    renderHook(() => useExternalChangesPoll());
    await vi.advanceTimersByTimeAsync(5100);

    expect(confirmSpy).toHaveBeenCalled();
    // Cancel → editingModel は保持、dirty も維持
    const state = useAppStore.getState();
    expect((state.editingModel as { local?: boolean }).local).toBe(true);
    expect(state.dirty).toBe(true);

    confirmSpy.mockRestore();
  });
});

describe("useExternalChangesPoll: simulation running", () => {
  it("does not poll while simulation is running", async () => {
    const { getFileContent } = await getMocks();
    useAppStore.setState({
      selectedFilePath: "demo.flw.json",
      editingFileEtag: 'W/"100-1"',
      status: "running",
    });

    renderHook(() => useExternalChangesPoll());
    await vi.advanceTimersByTimeAsync(20_000);

    expect(getFileContent).not.toHaveBeenCalled();
  });
});
