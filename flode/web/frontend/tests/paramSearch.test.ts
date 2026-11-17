// ADR-0085 §4-D: 引数値検索のコントローラ (デバウンス・IME・直列化・古い応答の破棄・409 の再試行・
// 閉じた後の破棄) と、追加する値の組み立て (appendUniqueValues)。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../src/api/client";
import {
  appendUniqueValues,
  ParamSearchController,
  PARAM_SEARCH_DEBOUNCE_MS,
  PARAM_SEARCH_RETRY_MS,
  type ParamSearchViewState,
} from "../src/lib/paramSearch";
import type { ParamSearchResponse } from "../src/types/api";

/** 1 回の要求 (手で解決・失敗させる)。 */
interface Call {
  query: string;
  current: string[];
  signal: AbortSignal;
  resolve: (r: ParamSearchResponse) => void;
  reject: (e: unknown) => void;
}

function response(query: string): ParamSearchResponse {
  return { columns: ["name"], rows: [{ cells: [query], value: `${query}: x` }], truncated: false };
}

function setup(current: () => string[] = () => []): {
  controller: ParamSearchController;
  calls: Call[];
  states: ParamSearchViewState[];
  last: () => ParamSearchViewState;
} {
  const calls: Call[] = [];
  const states: ParamSearchViewState[] = [];
  const controller = new ParamSearchController({
    search: (query, cur, signal) =>
      new Promise<ParamSearchResponse>((resolve, reject) => {
        calls.push({ query, current: cur, signal, resolve, reject });
      }),
    getCurrent: current,
    onState: (s) => states.push(s),
  });
  return { controller, calls, states, last: () => states[states.length - 1]! };
}

/** 保留中の Promise のコールバックを流す。 */
async function flush(): Promise<void> {
  await vi.advanceTimersByTimeAsync(0);
}

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("ParamSearchController", () => {
  it("sends after the input pauses for the debounce time", async () => {
    const { controller, calls } = setup();
    controller.setQuery("a");
    await vi.advanceTimersByTimeAsync(PARAM_SEARCH_DEBOUNCE_MS - 1);
    controller.setQuery("ab");
    await vi.advanceTimersByTimeAsync(PARAM_SEARCH_DEBOUNCE_MS - 1);
    expect(calls).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1);
    expect(calls.map((c) => c.query)).toEqual(["ab"]);
  });

  it("trims the query and sends immediately on Enter", async () => {
    const { controller, calls } = setup();
    controller.setQuery("  ab ");
    controller.submit("  ab ");
    expect(calls.map((c) => c.query)).toEqual(["ab"]);
    // 予約していたデバウンスは取り消されている
    await vi.advanceTimersByTimeAsync(PARAM_SEARCH_DEBOUNCE_MS * 2);
    expect(calls).toHaveLength(1);
  });

  it("does not send an empty query and clears the table", async () => {
    const { controller, calls, last } = setup();
    controller.setQuery("ab");
    await vi.advanceTimersByTimeAsync(PARAM_SEARCH_DEBOUNCE_MS);
    calls[0]!.resolve(response("ab"));
    await flush();
    expect(last().result).not.toBeNull();

    controller.setQuery("   ");
    controller.submit("   ");
    await vi.advanceTimersByTimeAsync(PARAM_SEARCH_DEBOUNCE_MS);
    expect(calls).toHaveLength(1);
    expect(last()).toEqual({ pending: false, result: null, error: null, stale: false });
  });

  it("does not schedule while an IME composition is in progress", async () => {
    const { controller, calls } = setup();
    controller.setQuery("か", true);
    await vi.advanceTimersByTimeAsync(PARAM_SEARCH_DEBOUNCE_MS * 2);
    expect(calls).toHaveLength(0);
    controller.setQuery("漢");
    await vi.advanceTimersByTimeAsync(PARAM_SEARCH_DEBOUNCE_MS);
    expect(calls.map((c) => c.query)).toEqual(["漢"]);
  });

  it("keeps one request in flight and sends only the latest queued query", async () => {
    const { controller, calls, last } = setup();
    controller.submit("a");
    controller.submit("ab");
    controller.submit("abc");
    expect(calls.map((c) => c.query)).toEqual(["a"]);
    expect(last().pending).toBe(true);

    calls[0]!.resolve(response("a"));
    await flush();
    // 古い世代の応答は表に出さず、最新の検索語だけを送る
    expect(last().result).toBeNull();
    expect(calls.map((c) => c.query)).toEqual(["a", "abc"]);

    calls[1]!.resolve(response("abc"));
    await flush();
    expect(last()).toEqual({ pending: false, result: response("abc"), error: null, stale: false });
  });

  it("discards a response whose query changed while waiting for the debounce", async () => {
    const { controller, calls, last } = setup();
    controller.submit("a");
    controller.setQuery("ab"); // まだ送らない (デバウンス中)
    calls[0]!.resolve(response("a"));
    await flush();
    expect(last().result).toBeNull();
    await vi.advanceTimersByTimeAsync(PARAM_SEARCH_DEBOUNCE_MS);
    expect(calls.map((c) => c.query)).toEqual(["a", "ab"]);
  });

  it("reads current when each request is sent (a copy)", async () => {
    let current = ["A: x"];
    const { controller, calls } = setup(() => current);
    controller.submit("a");
    current = ["A: x", "B: x"];
    calls[0]!.resolve(response("a"));
    await flush();
    controller.refresh();
    expect(calls[0]!.current).toEqual(["A: x"]);
    expect(calls[1]!.current).toEqual(["A: x", "B: x"]);
    expect(calls[1]!.current).not.toBe(current);
  });

  it("refresh re-runs the same query and drops the response in flight", async () => {
    const { controller, calls, last } = setup();
    controller.submit("a");
    controller.refresh();
    calls[0]!.resolve(response("old"));
    await flush();
    expect(last().result).toBeNull();
    expect(calls.map((c) => c.query)).toEqual(["a", "a"]);
    calls[1]!.resolve(response("new"));
    await flush();
    expect(last().result).toEqual(response("new"));
  });

  it("marks the shown result stale on refresh until the new response arrives", async () => {
    const { controller, calls, last } = setup();
    controller.submit("a");
    calls[0]!.resolve(response("a"));
    await flush();
    expect(last().stale).toBe(false);

    controller.refresh();
    expect(last()).toMatchObject({ pending: true, stale: true, result: response("a") });
    // 再検索が失敗しても古い提案は古いまま
    calls[1]!.reject(new ApiError(400, "400 boom", null, "boom"));
    await flush();
    expect(last()).toMatchObject({ stale: true, error: "boom" });

    controller.submit("a");
    calls[2]!.resolve(response("a2"));
    await flush();
    expect(last()).toMatchObject({ stale: false, result: response("a2") });
  });

  it("does not search again when the trimmed query is unchanged", async () => {
    const { controller, calls } = setup();
    controller.setQuery("ab");
    await vi.advanceTimersByTimeAsync(PARAM_SEARCH_DEBOUNCE_MS);
    expect(calls).toHaveLength(1);
    // 要求中・結果あり・失敗後のどれでも、同じ検索語の入力では送り直さない
    controller.setQuery("ab ");
    await vi.advanceTimersByTimeAsync(PARAM_SEARCH_DEBOUNCE_MS);
    expect(calls).toHaveLength(1);
    calls[0]!.resolve(response("ab"));
    await flush();
    controller.setQuery(" ab");
    await vi.advanceTimersByTimeAsync(PARAM_SEARCH_DEBOUNCE_MS);
    expect(calls).toHaveLength(1);
    // Enter は明示的な再検索
    controller.submit("ab");
    expect(calls).toHaveLength(2);
  });

  it("still sends when only trailing spaces are typed before the debounce fires", async () => {
    const { controller, calls } = setup();
    controller.setQuery("ab");
    await vi.advanceTimersByTimeAsync(PARAM_SEARCH_DEBOUNCE_MS - 1);
    controller.setQuery("ab ");
    await vi.advanceTimersByTimeAsync(PARAM_SEARCH_DEBOUNCE_MS);
    expect(calls.map((c) => c.query)).toEqual(["ab"]);
  });

  it("retries a 409 after the retry delay with the latest query", async () => {
    const { controller, calls, last } = setup();
    controller.submit("a");
    calls[0]!.reject(new ApiError(409, "409 busy", null, "busy"));
    await flush();
    expect(last()).toMatchObject({ pending: true, error: null });
    await vi.advanceTimersByTimeAsync(PARAM_SEARCH_RETRY_MS - 1);
    expect(calls).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(calls.map((c) => c.query)).toEqual(["a", "a"]);
  });

  it("does not retry a 409 once the query has changed", async () => {
    const { controller, calls } = setup();
    controller.submit("a");
    calls[0]!.reject(new ApiError(409, "409 busy", null, "busy"));
    await flush();
    controller.setQuery("ab");
    await vi.advanceTimersByTimeAsync(PARAM_SEARCH_DEBOUNCE_MS);
    expect(calls.map((c) => c.query)).toEqual(["a", "ab"]);
    await vi.advanceTimersByTimeAsync(PARAM_SEARCH_RETRY_MS * 2);
    expect(calls).toHaveLength(2);
  });

  it("shows the server detail of other errors", async () => {
    const { controller, calls, last } = setup();
    controller.submit("a");
    calls[0]!.reject(new ApiError(400, "400 ValueError: bad", null, "ValueError: bad"));
    await flush();
    expect(last()).toMatchObject({ pending: false, error: "ValueError: bad" });
  });

  it("aborts and ignores everything after dispose", async () => {
    const { controller, calls, states } = setup();
    controller.submit("a");
    const before = states.length;
    controller.dispose();
    expect(calls[0]!.signal.aborted).toBe(true);
    calls[0]!.resolve(response("a"));
    await flush();
    controller.setQuery("b");
    await vi.advanceTimersByTimeAsync(PARAM_SEARCH_DEBOUNCE_MS);
    expect(calls).toHaveLength(1);
    expect(states).toHaveLength(before);
  });
});

describe("appendUniqueValues", () => {
  const rows = ["a", "b", "c", "d"].map((v) => ({ cells: [v], value: v }));

  it("appends in table order, not selection order", () => {
    expect(appendUniqueValues(["x"], rows, new Set(["d", "b"]))).toEqual(["x", "b", "d"]);
  });

  it("skips values that are already present", () => {
    expect(appendUniqueValues(["b"], rows, new Set(["a", "b"]))).toEqual(["b", "a"]);
  });

  it("ignores selected keys that are not in the table", () => {
    expect(appendUniqueValues([], rows, new Set(["zzz"]))).toEqual([]);
  });
});

describe("ParamSearchController without getCurrent (ADR-0086 §3-D)", () => {
  it("sends an empty current when getCurrent is omitted", async () => {
    const seen: string[][] = [];
    const controller = new ParamSearchController({
      search: async (query, current) => {
        seen.push(current);
        return response(query);
      },
      onState: () => undefined,
    });
    controller.submit("bolt");
    await flush();
    expect(seen).toEqual([[]]);
    controller.dispose();
  });
});
