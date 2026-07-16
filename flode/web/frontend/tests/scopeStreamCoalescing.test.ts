// Scope ストリームの rAF coalescing をテストする。
//
// 検証する不変条件:
//   1. 1 フレーム内の複数 scope_batch は flush (= rAF callback) まで反映されず、
//      flush 後に 1 回でまとめて反映される (= 描画頻度の間引き)。
//   2. progress は最新値のみ flush 後に反映される。
//   3. 終端メッセージ (completed/stopped/failed) は pending を同期 drain してから
//      ステータスを確定する (= 最終バッチの取りこぼし防止)。
//   4. startedSimulation / resetScopes は前 run の pending を破棄する。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAppStore } from "../src/store/appStore";
import type { StreamMessage } from "../src/types/api";

// requestAnimationFrame を手動制御する: 登録 callback を貯め、``runFrame()`` で実行。
let rafCallbacks: FrameRequestCallback[] = [];
let rafId = 0;

function runFrame(): void {
  const cbs = rafCallbacks;
  rafCallbacks = [];
  for (const cb of cbs) cb(0);
}

/** 1 信号・2 サンプルの scope_batch を作る (times=[t0,t0+1], 値=times と同値)。 */
function batch(scopeId: string, t0: number): StreamMessage {
  return {
    type: "scope_batch",
    scope_id: scopeId,
    times: [t0, t0 + 1],
    values: [[t0], [t0 + 1]],
  };
}

beforeEach(() => {
  rafCallbacks = [];
  rafId = 0;
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback): number => {
    rafCallbacks.push(cb);
    return ++rafId;
  });
  vi.stubGlobal("cancelAnimationFrame", (_id: number): void => {
    // 本テストでは個別 cancel の id 照合まではせず、pending 破棄の結果で検証する。
  });
  // store を初期化 (resetScopes が pending もクリアする)。
  useAppStore.getState().resetScopes();
  useAppStore.setState({ status: "idle", progress: null });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("scope stream rAF coalescing", () => {
  it("1 フレーム内の複数 scope_batch は flush までは未反映で、flush で 1 回にまとまる", () => {
    const h = useAppStore.getState().handleStreamMessage;
    h(batch("s1", 0));
    h(batch("s1", 2));
    h(batch("s1", 4));

    // flush 前: まだ buffer は生成されていない (= 同期 set していない証拠)。
    expect(useAppStore.getState().scopes["s1"]).toBeUndefined();
    // rAF は重複予約されず 1 本だけ。
    expect(rafCallbacks.length).toBe(1);

    runFrame();

    const buf = useAppStore.getState().scopes["s1"];
    expect(buf).toBeDefined();
    expect(buf!.length).toBe(6);
    expect(Array.from(buf!.times.subarray(0, 6))).toEqual([0, 1, 2, 3, 4, 5]);
    expect(Array.from(buf!.values[0]!.subarray(0, 6))).toEqual([0, 1, 2, 3, 4, 5]);
  });

  it("複数 scope を 1 フレームで個別バッファに振り分ける", () => {
    const h = useAppStore.getState().handleStreamMessage;
    h(batch("s1", 0));
    h(batch("s2", 10));
    runFrame();

    expect(useAppStore.getState().scopes["s1"]!.length).toBe(2);
    expect(useAppStore.getState().scopes["s2"]!.length).toBe(2);
    expect(Array.from(useAppStore.getState().scopes["s2"]!.times.subarray(0, 2))).toEqual([10, 11]);
  });

  it("progress は最新値のみ flush 後に反映される", () => {
    const h = useAppStore.getState().handleStreamMessage;
    h({ type: "progress", current_t: 0.1, t_end: 1 });
    h({ type: "progress", current_t: 0.5, t_end: 1 });

    expect(useAppStore.getState().progress).toBeNull();
    runFrame();
    expect(useAppStore.getState().progress).toEqual({ current_t: 0.5, t_end: 1 });
  });

  it.each(["completed", "stopped"] as const)(
    "%s は pending を同期 drain してからステータス確定する",
    (term) => {
      const h = useAppStore.getState().handleStreamMessage;
      h(batch("s1", 0));
      // flush 前 (= rAF 未発火) でも終端が来たら同期反映されること。
      expect(useAppStore.getState().scopes["s1"]).toBeUndefined();

      h({ type: term, duration_sec: 1.0 });

      const s = useAppStore.getState();
      expect(s.status).toBe(term);
      expect(s.scopes["s1"]).toBeDefined();
      expect(s.scopes["s1"]!.length).toBe(2);
    },
  );

  it("failed も pending を同期 drain してから失敗確定する", () => {
    const h = useAppStore.getState().handleStreamMessage;
    h(batch("s1", 0));
    h({ type: "failed", duration_sec: 1.0 });

    const s = useAppStore.getState();
    expect(s.status).toBe("failed");
    expect(s.scopes["s1"]!.length).toBe(2);
  });

  it("startedSimulation は前 run の rAF を cancel し pending を破棄する", () => {
    // cancel が実際に呼ばれることを id 照合で検証する (= pending 配列クリアの
    // 副作用だけでなく、予約済み frame の cancel まで保証する)。
    const cancelSpy = vi.fn();
    vi.stubGlobal("cancelAnimationFrame", cancelSpy);

    const h = useAppStore.getState().handleStreamMessage;
    h(batch("s1", 0)); // pending のまま rAF 予約。stub は handle=1 を返す。
    const registeredHandle = rafId;

    useAppStore.getState().startedSimulation("sim_next");
    expect(cancelSpy).toHaveBeenCalledWith(registeredHandle);

    runFrame(); // 予約済み callback が走っても pending は破棄済みなので no-op
    expect(useAppStore.getState().scopes).toEqual({});
    expect(useAppStore.getState().status).toBe("running");
  });

  it("resetScopes は未 flush pending を破棄する", () => {
    const h = useAppStore.getState().handleStreamMessage;
    h(batch("s1", 0));

    useAppStore.getState().resetScopes();
    runFrame();

    expect(useAppStore.getState().scopes).toEqual({});
  });
});
