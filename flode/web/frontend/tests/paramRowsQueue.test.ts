// ADR-0086 §3-D (X4): param-rows 要求のページ単位の直列キュー。
// - 同時に走る要求は 1 本
// - まだ送っていない同じスロットの要求は新しい方に置き換える
// - ダイアログ由来を表の describe より先に送る
// - 409 は 1 秒後に再送 (待つ間に同じスロットへ新しい要求が来たらそちらを送る)
// - 取り消し: 待ち行列から除き、走っている要求は受信をやめて次へ進む

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../src/api/client";
import {
  isParamRowsCancelled,
  ParamRowsCancelledError,
  ParamRowsQueue,
} from "../src/lib/paramRowsQueue";

const RETRY_MS = 1000;

/** 外から解決できる要求。 */
interface Deferred<T> {
  promise: Promise<T>;
  resolve: (v: T) => void;
  reject: (e: unknown) => void;
}
function deferred<T>(): Deferred<T> {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** マイクロタスクを流す。 */
async function flush(): Promise<void> {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
}

describe("ParamRowsQueue", () => {
  let queue: ParamRowsQueue;
  beforeEach(() => {
    vi.useFakeTimers();
    queue = new ParamRowsQueue({ retryMs: RETRY_MS });
  });
  afterEach(() => {
    queue.reset();
    vi.useRealTimers();
  });

  it("runs one request at a time, in order", async () => {
    const started: string[] = [];
    const d1 = deferred<string>();
    const d2 = deferred<string>();
    const p1 = queue.enqueue("describe:B:a", "table", () => {
      started.push("a");
      return d1.promise;
    });
    const p2 = queue.enqueue("describe:B:b", "table", () => {
      started.push("b");
      return d2.promise;
    });
    expect(started).toEqual(["a"]);
    expect(queue.pendingCount).toBe(1);
    d1.resolve("A");
    await expect(p1).resolves.toBe("A");
    await flush();
    expect(started).toEqual(["a", "b"]);
    d2.resolve("B");
    await expect(p2).resolves.toBe("B");
  });

  it("replaces a not-yet-sent request of the same slot with the newer one", async () => {
    const started: string[] = [];
    const blocker = deferred<string>();
    void queue.enqueue("describe:X:x", "table", () => blocker.promise);
    const old = queue.enqueue("describe:B:a", "table", async () => {
      started.push("old");
      return "old";
    });
    const newer = queue.enqueue("describe:B:a", "table", async () => {
      started.push("new");
      return "new";
    });
    await expect(old).rejects.toSatisfy(
      (e: unknown) => isParamRowsCancelled(e) && (e as ParamRowsCancelledError).superseded,
    );
    expect(queue.pendingCount).toBe(1);
    blocker.resolve("x");
    await expect(newer).resolves.toBe("new");
    expect(started).toEqual(["new"]);
  });

  it("sends dialog requests before table describes", async () => {
    const started: string[] = [];
    const blocker = deferred<string>();
    void queue.enqueue("describe:X:x", "table", () => blocker.promise);
    const run = (name: string) => async (): Promise<string> => {
      started.push(name);
      return name;
    };
    const t1 = queue.enqueue("describe:B:a", "table", run("table-a"));
    const dlg = queue.enqueue("dialog:1:form", "dialog", run("dialog"));
    const t2 = queue.enqueue("describe:B:b", "table", run("table-b"));
    blocker.resolve("x");
    await Promise.all([t1, dlg, t2]);
    expect(started).toEqual(["dialog", "table-a", "table-b"]);
  });

  it("retries a 409 after the wait, sending the newest request of that slot", async () => {
    const calls: string[] = [];
    let first = true;
    const p1 = queue.enqueue("dialog:1:preview", "dialog", async () => {
      calls.push("v1");
      if (first) {
        first = false;
        throw new ApiError(409, "409 busy", null, "busy");
      }
      return "v1";
    });
    await flush();
    expect(calls).toEqual(["v1"]);
    // 再送の待ちの間に同じスロットへ新しい要求
    const p2 = queue.enqueue("dialog:1:preview", "dialog", async () => {
      calls.push("v2");
      return "v2";
    });
    await expect(p1).rejects.toBeInstanceOf(ParamRowsCancelledError);
    await vi.advanceTimersByTimeAsync(RETRY_MS - 1);
    expect(calls).toEqual(["v1"]);
    await vi.advanceTimersByTimeAsync(1);
    await expect(p2).resolves.toBe("v2");
    expect(calls).toEqual(["v1", "v2"]);
  });

  it("retries the same request when nothing newer arrived", async () => {
    let n = 0;
    const p = queue.enqueue("describe:B:a", "table", async () => {
      n += 1;
      if (n === 1) throw new ApiError(409, "409 busy", null, "busy");
      return "ok";
    });
    await vi.advanceTimersByTimeAsync(RETRY_MS);
    await expect(p).resolves.toBe("ok");
    expect(n).toBe(2);
  });

  it("does not resend a cancelled slot after 409", async () => {
    let n = 0;
    const p = queue.enqueue("describe:B:a", "table", async () => {
      n += 1;
      throw new ApiError(409, "409 busy", null, "busy");
    });
    await flush();
    queue.cancel("describe:B:a");
    await expect(p).rejects.toBeInstanceOf(ParamRowsCancelledError);
    await vi.advanceTimersByTimeAsync(RETRY_MS * 3);
    expect(n).toBe(1);
  });

  it("passes other errors through", async () => {
    const p = queue.enqueue("dialog:1:form", "dialog", async () => {
      throw new ApiError(400, "400 bad", null, "bad");
    });
    await expect(p).rejects.toMatchObject({ status: 400 });
  });

  it("cancelling the running request aborts it and moves on", async () => {
    let signal: AbortSignal | null = null;
    const hang = deferred<string>();
    const p1 = queue.enqueue("dialog:7:form", "dialog", (s) => {
      signal = s;
      return hang.promise;
    });
    const p2 = queue.enqueue("describe:B:a", "table", async () => "next");
    queue.cancelPrefix("dialog:7:");
    expect(signal!.aborted).toBe(true);
    await expect(p1).rejects.toBeInstanceOf(ParamRowsCancelledError);
    await expect(p2).resolves.toBe("next");
    // 遅れて来た応答は無視される
    hang.resolve("late");
    await flush();
    expect(queue.runningSlot).toBeNull();
  });

  it("cancel removes queued requests of that slot only", async () => {
    const blocker = deferred<string>();
    void queue.enqueue("describe:X:x", "table", () => blocker.promise);
    const a = queue.enqueue("describe:B:a", "table", async () => "a");
    const b = queue.enqueue("describe:B:b", "table", async () => "b");
    queue.cancel("describe:B:a");
    await expect(a).rejects.toBeInstanceOf(ParamRowsCancelledError);
    blocker.resolve("x");
    await expect(b).resolves.toBe("b");
  });
});
