// 終端後の Scope 波形 backfill (`GET /results` → replaceScopes) をテストする。
//
// 背景: WS ストリームは内部 queue (max 1024) 満杯時に古い scope_batch を
// silently drop するため、ライブ描画だけに依存すると波形が欠損したまま
// 「完全なグラフ」として表示されてしまう。終端後に一括結果で置き換えることで
// 表示を正にする。
//
// 検証する不変条件:
//   1. replaceScopes は WS 由来の欠損バッファを一括結果で完全に置き換える。
//   2. replaceScopes は未 flush の pending batch を破棄する (= 置換後に古い
//      batch が追記されて欠損状態へ戻らない)。
//   3. useSimulation は終端ステータスで /results を 1 回だけ fetch する
//      (複数マウントでも重複しない)。
//   4. fetch 完了前に次の run が始まっていたら結果を破棄する。

import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// useSimulation の import より前に hoist される (repo 規約: partial mock)。
vi.mock("../src/api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../src/api/client")>();
  return { ...mod, getSimulationResults: vi.fn() };
});

import { getSimulationResults } from "../src/api/client";
import { useSimulation } from "../src/lib/useSimulation";
import { useAppStore } from "../src/store/appStore";
import type { SimulationResults } from "../src/types/api";

const mockGetResults = vi.mocked(getSimulationResults);

function results(
  simId: string,
  scopes: SimulationResults["scopes"],
): SimulationResults {
  return { simulation_id: simId, status: "completed", scopes };
}

beforeEach(() => {
  mockGetResults.mockReset();
  useAppStore.getState().resetScopes();
  useAppStore.setState({ status: "idle", simulationId: null, progress: null });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("replaceScopes (store action)", () => {
  it("WS 由来の欠損バッファを一括結果で完全に置き換える", () => {
    const h = useAppStore.getState().handleStreamMessage;
    // WS では先頭 2 サンプルが drop され t=[2,3] しか届かなかったと想定
    h({ type: "scope_batch", scope_id: "s1", times: [2, 3], values: [[20], [30]] });
    h({ type: "completed", duration_sec: 1.0 });
    expect(useAppStore.getState().scopes["s1"]!.length).toBe(2);

    useAppStore.getState().replaceScopes({
      s1: { times: [0, 1, 2, 3], values: [[0], [10], [20], [30]] },
    });

    const buf = useAppStore.getState().scopes["s1"]!;
    expect(buf.length).toBe(4);
    expect(Array.from(buf.times.subarray(0, 4))).toEqual([0, 1, 2, 3]);
    expect(Array.from(buf.values[0]!.subarray(0, 4))).toEqual([0, 10, 20, 30]);
  });

  it("複数 scope をそれぞれ再構築する", () => {
    useAppStore.getState().replaceScopes({
      s1: { times: [0], values: [[1, 2]] },
      s2: { times: [0, 1], values: [[5], [6]] },
    });
    const s = useAppStore.getState();
    expect(s.scopes["s1"]!.n_signals).toBe(2);
    expect(s.scopes["s1"]!.length).toBe(1);
    expect(s.scopes["s2"]!.length).toBe(2);
  });

  it("未 flush の pending batch を破棄する (置換後に追記されない)", () => {
    const rafCallbacks: FrameRequestCallback[] = [];
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback): number => {
      rafCallbacks.push(cb);
      return rafCallbacks.length;
    });
    vi.stubGlobal("cancelAnimationFrame", (): void => {});
    try {
      const h = useAppStore.getState().handleStreamMessage;
      h({ type: "scope_batch", scope_id: "s1", times: [9], values: [[99]] });

      useAppStore.getState().replaceScopes({
        s1: { times: [0, 1], values: [[0], [1]] },
      });
      // 予約済み rAF が後から発火しても pending は破棄済みで no-op
      for (const cb of rafCallbacks) cb(0);

      const buf = useAppStore.getState().scopes["s1"]!;
      expect(buf.length).toBe(2);
      expect(Array.from(buf.times.subarray(0, 2))).toEqual([0, 1]);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("useSimulation の終端時 backfill", () => {
  it("completed で /results を 1 回だけ fetch し scopes を置き換える (複数マウントでも重複しない)", async () => {
    const simId = `sim_backfill_${Math.random()}`;
    mockGetResults.mockResolvedValue(
      results(simId, { s1: { labels: ["u0"], times: [0, 1], values: [[1], [2]] } }),
    );

    useAppStore.setState({ status: "running", simulationId: simId });
    // Toolbar と SimulationControls の 2 箇所マウントを模擬
    const hook1 = renderHook(() => useSimulation());
    const hook2 = renderHook(() => useSimulation());

    useAppStore.setState({ status: "completed" });
    hook1.rerender();
    hook2.rerender();

    await waitFor(() => {
      expect(useAppStore.getState().scopes["s1"]).toBeDefined();
    });
    expect(mockGetResults).toHaveBeenCalledTimes(1);
    expect(mockGetResults).toHaveBeenCalledWith(simId);
    expect(useAppStore.getState().scopes["s1"]!.length).toBe(2);

    hook1.unmount();
    hook2.unmount();
  });

  it("fetch 完了前に次の run が始まっていたら結果を破棄する", async () => {
    const simId = `sim_stale_${Math.random()}`;
    let resolve!: (r: SimulationResults) => void;
    mockGetResults.mockReturnValue(
      new Promise<SimulationResults>((res) => {
        resolve = res;
      }),
    );

    useAppStore.setState({ status: "running", simulationId: simId });
    const hook = renderHook(() => useSimulation());
    useAppStore.setState({ status: "completed" });
    hook.rerender();

    // fetch 解決前に次の run が開始 (simulationId が変わる)
    useAppStore.getState().startedSimulation("sim_next");
    resolve(
      results(simId, { s1: { labels: ["u0"], times: [0], values: [[1]] } }),
    );
    // microtask を流す
    await new Promise((r) => setTimeout(r, 0));

    expect(useAppStore.getState().scopes["s1"]).toBeUndefined();
    hook.unmount();
  });

  it("fetch 失敗時はライブ描画分を保持したまま何もしない", async () => {
    const simId = `sim_fail_${Math.random()}`;
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    mockGetResults.mockRejectedValue(new Error("network down"));

    useAppStore.setState({ status: "running", simulationId: simId });
    const h = useAppStore.getState().handleStreamMessage;
    h({ type: "scope_batch", scope_id: "s1", times: [0], values: [[1]] });
    h({ type: "completed", duration_sec: 1.0 });

    const hook = renderHook(() => useSimulation());
    await waitFor(() => {
      expect(warnSpy).toHaveBeenCalled();
    });
    // ライブ分は残る
    expect(useAppStore.getState().scopes["s1"]!.length).toBe(1);
    hook.unmount();
  });
});
