// ADR-0041 §論点 11-A: useExternalChangesPoll hook のテスト。
//
// 5 秒 polling で **条件付き GET** (`getFileContentIfChanged`) を叩き、
// 304 (= null) / 200 (= 外部変更) を検出する挙動を検証する。
// 主要シナリオ:
//   - selectedFilePath が null → polling しない
//   - 304 (変更なし) → 何もしない
//   - dirty=false で変更あり → silent reload (= editingModel を上書き)
//   - dirty=true で変更あり → dialog.confirm が呼ばれる
//   - simulation 実行中 → polling しない
//   - タブ非表示中 → polling しない、再表示で即時 tick
//   - etag 未確定 (null) → polling しない

import { cleanup, renderHook } from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { dialog } from "../src/lib/dialogService";
import { useExternalChangesPoll } from "../src/lib/useExternalChangesPoll";
import { useAppStore } from "../src/store/appStore";

vi.mock("../src/api/filesApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/filesApi")>();
  return {
    ...actual,
    getFileContentIfChanged: vi.fn(),
  };
});

async function getMocks(): Promise<{
  getFileContentIfChanged: ReturnType<typeof vi.fn>;
}> {
  const mod = await import("../src/api/filesApi");
  return { getFileContentIfChanged: vi.mocked(mod.getFileContentIfChanged) };
}

/** document.hidden を制御する (jsdom 既定は false)。 */
function setHidden(hidden: boolean): void {
  Object.defineProperty(document, "hidden", {
    configurable: true,
    get: () => hidden,
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  setHidden(false);
  useAppStore.setState({
    selectedFilePath: null,
    editingModel: null,
    editingFileMtime: null,
    editingFileEtag: null,
    dirty: false,
    status: "idle",
  });
});

afterEach(() => {
  // hook を unmount して interval / visibilitychange リスナーを掃除する
  // (= 前テストのリスナーが残ると dispatchEvent が多重 tick する)
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
  setHidden(false);
});

describe("useExternalChangesPoll: when no file selected", () => {
  it("does not poll when selectedFilePath is null", async () => {
    const { getFileContentIfChanged } = await getMocks();
    renderHook(() => useExternalChangesPoll());
    await vi.advanceTimersByTimeAsync(20_000); // 4 ticks 分
    expect(getFileContentIfChanged).not.toHaveBeenCalled();
  });
});

describe("useExternalChangesPoll: 304 (変更なし)", () => {
  it("304 (= null) のとき state を変更しない", async () => {
    const { getFileContentIfChanged } = await getMocks();
    useAppStore.setState({
      selectedFilePath: "demo.flw.json",
      editingModel: { schema_version: "0.9", original: true } as never,
      editingFileEtag: 'W/"100-1"',
      dirty: false,
    });
    getFileContentIfChanged.mockResolvedValue(null); // = 304

    renderHook(() => useExternalChangesPoll());
    await vi.advanceTimersByTimeAsync(5100);

    // local etag 付きの条件付き GET が呼ばれる
    expect(getFileContentIfChanged).toHaveBeenCalledWith(
      "demo.flw.json",
      'W/"100-1"',
    );
    const state = useAppStore.getState();
    expect((state.editingModel as { original?: boolean }).original).toBe(true);
    expect(state.editingFileEtag).toBe('W/"100-1"');
  });

  it("etag 未確定 (null) の間は polling しない", async () => {
    const { getFileContentIfChanged } = await getMocks();
    useAppStore.setState({
      selectedFilePath: "demo.flw.json",
      editingFileEtag: null,
    });
    getFileContentIfChanged.mockResolvedValue(null);

    renderHook(() => useExternalChangesPoll());
    await vi.advanceTimersByTimeAsync(10_200);

    expect(getFileContentIfChanged).not.toHaveBeenCalled();
  });
});

describe("useExternalChangesPoll: silent reload (dirty=false)", () => {
  it("reloads editingModel silently when changed and not dirty", async () => {
    const { getFileContentIfChanged } = await getMocks();
    useAppStore.setState({
      selectedFilePath: "demo.flw.json",
      editingModel: { schema_version: "0.9" } as never,
      editingFileEtag: 'W/"100-1"',
      editingFileMtime: "2026-05-10T00:00:00Z",
      dirty: false,
    });
    getFileContentIfChanged.mockResolvedValue({
      path: "demo.flw.json",
      content: { schema_version: "0.9", marker: "external" },
      mtime: "2026-05-10T00:01:00Z",
      etag: 'W/"200-2"', // 違う etag
    });

    renderHook(() => useExternalChangesPoll());
    // 5 秒 advance → 1 tick
    await vi.advanceTimersByTimeAsync(5100);

    expect(getFileContentIfChanged).toHaveBeenCalledWith(
      "demo.flw.json",
      'W/"100-1"',
    );
    const state = useAppStore.getState();
    // silent reload で editingModel + etag が更新されている
    expect((state.editingModel as { marker?: string } | null)?.marker).toBe(
      "external",
    );
    expect(state.editingFileEtag).toBe('W/"200-2"');
    expect(state.dirty).toBe(false);
  });
});

describe("useExternalChangesPoll: dirty + external change → confirm", () => {
  // v0.32.0: window.confirm を dialog.confirm に置換したのに合わせて test も spy 化
  it("prompts user via dialog.confirm when dirty and changed", async () => {
    const { getFileContentIfChanged } = await getMocks();
    useAppStore.setState({
      selectedFilePath: "demo.flw.json",
      editingModel: { schema_version: "0.9", local: true } as never,
      editingFileEtag: 'W/"100-1"',
      dirty: true,
    });
    getFileContentIfChanged.mockResolvedValue({
      path: "demo.flw.json",
      content: { schema_version: "0.9", external: true },
      mtime: "2026-05-10T00:01:00Z",
      etag: 'W/"200-2"',
    });
    const confirmSpy = vi.spyOn(dialog, "confirm").mockResolvedValue(true);

    renderHook(() => useExternalChangesPoll());
    await vi.advanceTimersByTimeAsync(5100);
    // dialog.confirm は async resolve なので microtask flush を待つ
    await vi.runAllTicks();
    await Promise.resolve();

    expect(confirmSpy).toHaveBeenCalled();
    // OK 選択 → 外部変更を取り込み
    const state = useAppStore.getState();
    expect((state.editingModel as { external?: boolean }).external).toBe(true);
    expect(state.dirty).toBe(false);

    confirmSpy.mockRestore();
  });

  it("preserves local changes when user cancels confirm", async () => {
    const { getFileContentIfChanged } = await getMocks();
    useAppStore.setState({
      selectedFilePath: "demo.flw.json",
      editingModel: { schema_version: "0.9", local: true } as never,
      editingFileEtag: 'W/"100-1"',
      dirty: true,
    });
    getFileContentIfChanged.mockResolvedValue({
      path: "demo.flw.json",
      content: { schema_version: "0.9", external: true },
      mtime: "2026-05-10T00:01:00Z",
      etag: 'W/"200-2"',
    });
    const confirmSpy = vi.spyOn(dialog, "confirm").mockResolvedValue(false);

    renderHook(() => useExternalChangesPoll());
    await vi.advanceTimersByTimeAsync(5100);
    await vi.runAllTicks();
    await Promise.resolve();

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
    const { getFileContentIfChanged } = await getMocks();
    useAppStore.setState({
      selectedFilePath: "demo.flw.json",
      editingFileEtag: 'W/"100-1"',
      status: "running",
    });

    renderHook(() => useExternalChangesPoll());
    await vi.advanceTimersByTimeAsync(20_000);

    expect(getFileContentIfChanged).not.toHaveBeenCalled();
  });
});

describe("useExternalChangesPoll: visibility gating", () => {
  it("タブ非表示中は polling しない", async () => {
    const { getFileContentIfChanged } = await getMocks();
    useAppStore.setState({
      selectedFilePath: "demo.flw.json",
      editingFileEtag: 'W/"100-1"',
    });
    getFileContentIfChanged.mockResolvedValue(null);
    setHidden(true);

    renderHook(() => useExternalChangesPoll());
    await vi.advanceTimersByTimeAsync(15_300); // 3 ticks 分

    expect(getFileContentIfChanged).not.toHaveBeenCalled();
  });

  it("再表示 (visibilitychange) で interval を待たず即時 tick する", async () => {
    const { getFileContentIfChanged } = await getMocks();
    useAppStore.setState({
      selectedFilePath: "demo.flw.json",
      editingFileEtag: 'W/"100-1"',
    });
    getFileContentIfChanged.mockResolvedValue(null);
    setHidden(true);

    renderHook(() => useExternalChangesPoll());
    await vi.advanceTimersByTimeAsync(5100);
    expect(getFileContentIfChanged).not.toHaveBeenCalled();

    setHidden(false);
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(0); // microtask のみ流す
    expect(getFileContentIfChanged).toHaveBeenCalledTimes(1);
  });
});
