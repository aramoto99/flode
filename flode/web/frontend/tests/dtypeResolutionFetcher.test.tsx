// SPEC-0028 §5.5: useDtypeResolutionFetcher (モデルレベル store) の
// debounce / abort / store 反映。

import { cleanup, render } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "../src/api/client";
import {
  _resetDtypeFetchStateForTest,
  _setDtypeResolutionForTest,
  getDtypeResolution,
  useDtypeResolutionFetcher,
} from "../src/lib/dtypeResolution";
import { useAppStore } from "../src/store/appStore";
import type { DtypesResponse, FlwModel } from "../src/types/api";

vi.mock("../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/client")>();
  return { ...actual, resolveModelDtypes: vi.fn() };
});

const resolveModelDtypes = vi.mocked(client.resolveModelDtypes);

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const MODEL = { blocks: [], connections: [] } as unknown as FlwModel;

const RESPONSE: DtypesResponse = {
  schema_version: "dtypes.v1",
  ports: [{ block_id: "c", direction: "out", port_index: 0, dtype: "int32" }],
  diagnostics: [],
  summary: { total_ports: 1, by_dtype: { int32: 1 }, unresolved: 0, non_float_ports: 1 },
};

function Harness(): null {
  useDtypeResolutionFetcher();
  return null;
}

const DEBOUNCE_MS = 300;

beforeEach(() => {
  vi.useFakeTimers();
  useAppStore.setState({ editingModel: MODEL });
  _setDtypeResolutionForTest(null);
  _resetDtypeFetchStateForTest();
});

afterEach(() => {
  cleanup();
  _setDtypeResolutionForTest(null);
  _resetDtypeFetchStateForTest();
  vi.useRealTimers();
  vi.clearAllMocks();
});

async function flush(ms: number = DEBOUNCE_MS): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("useDtypeResolutionFetcher (SPEC-0028 §5.5)", () => {
  it("fetches after the debounce and publishes to the store", async () => {
    resolveModelDtypes.mockResolvedValue(RESPONSE);
    render(<Harness />);
    await flush();
    expect(resolveModelDtypes).toHaveBeenCalledTimes(1);
    expect(getDtypeResolution()).toEqual(RESPONSE);
  });

  it("debounces rapid edits into a single fetch", async () => {
    resolveModelDtypes.mockResolvedValue(RESPONSE);
    render(<Harness />);
    await flush(100);
    act(() => {
      useAppStore.setState({
        editingModel: { ...(MODEL as object) } as unknown as FlwModel,
      });
    });
    await flush(100);
    expect(resolveModelDtypes).not.toHaveBeenCalled();
    await flush();
    expect(resolveModelDtypes).toHaveBeenCalledTimes(1);
  });

  it("serialises fetches: in-flight blocks new requests, latest is queued", async () => {
    // security SHOULD-4: サーバ側の resolve はキャンセル不能なので、
    // in-flight 中は新規 fetch を発行せず「最新 1 件」だけ queue する
    let resolveFirst: ((r: DtypesResponse) => void) | undefined;
    resolveModelDtypes
      .mockImplementationOnce(
        () =>
          new Promise<DtypesResponse>((res) => {
            resolveFirst = res;
          }),
      )
      .mockResolvedValueOnce(RESPONSE);
    render(<Harness />);
    await flush();
    expect(resolveModelDtypes).toHaveBeenCalledTimes(1);

    // in-flight 中に 2 回編集 → 新しい fetch は始まらない (queue に最新のみ)
    act(() => {
      useAppStore.setState({
        editingModel: { ...(MODEL as object) } as unknown as FlwModel,
      });
    });
    await flush();
    act(() => {
      useAppStore.setState({
        editingModel: { ...(MODEL as object) } as unknown as FlwModel,
      });
    });
    await flush();
    expect(resolveModelDtypes).toHaveBeenCalledTimes(1);

    // 完了後に queue 分がちょうど 1 回だけ処理される
    await act(async () => {
      resolveFirst!(RESPONSE);
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(resolveModelDtypes).toHaveBeenCalledTimes(2);
    expect(getDtypeResolution()).toEqual(RESPONSE);
  });

  it("stores null on failure (readers fall back silently)", async () => {
    resolveModelDtypes.mockRejectedValue(new Error("boom"));
    _setDtypeResolutionForTest(RESPONSE);
    render(<Harness />);
    await flush();
    expect(getDtypeResolution()).toBeNull();
  });
});
