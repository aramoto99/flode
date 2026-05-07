// ADR-0023 §Decision §(3): ScopeBuffer SoA + 倍々リングバッファの単体テスト。
//
// 旧実装 (number[] / number[][] の spread append) は append 1 件ごとに O(N) で、
// 連続 N batch の合計が O(N²) になっていた。新実装は Float64Array の倍々増加で
// amortized O(1)、列指向 (1 信号 = 1 typed array) で uPlot に直接渡せる。

import { describe, expect, it } from "vitest";

import {
  appendBatch,
  createBuffer,
  type ScopeBuffer,
} from "../src/lib/scopeBuffer";

const INITIAL_CAPACITY = 1024;

describe("createBuffer", () => {
  it("starts with length=0 and capacity=INITIAL_CAPACITY=1024", () => {
    const b = createBuffer();
    expect(b.length).toBe(0);
    expect(b.capacity).toBe(INITIAL_CAPACITY);
    expect(b.times).toBeInstanceOf(Float64Array);
    expect(b.times.length).toBe(INITIAL_CAPACITY);
    expect(b.values).toEqual([]);
    expect(b.n_signals).toBe(0);
  });
});

describe("appendBatch (first batch)", () => {
  it("fixes n_signals on first non-empty batch", () => {
    const b = appendBatch(createBuffer(), [0.0, 0.1], [
      [1, 2, 3],
      [4, 5, 6],
    ]);
    expect(b.n_signals).toBe(3);
    expect(b.length).toBe(2);
    expect(b.values.length).toBe(3);
    expect(b.values[0]).toBeInstanceOf(Float64Array);
  });

  it("transposes wire row-major into column SoA", () => {
    // wire: values[i][p]、内部: values[p][i]
    const b = appendBatch(createBuffer(), [0.0, 0.1, 0.2], [
      [10, 20],
      [11, 21],
      [12, 22],
    ]);
    // 信号 0: [10, 11, 12]、信号 1: [20, 21, 22]
    expect(Array.from(b.values[0]!.subarray(0, 3))).toEqual([10, 11, 12]);
    expect(Array.from(b.values[1]!.subarray(0, 3))).toEqual([20, 21, 22]);
    expect(Array.from(b.times.subarray(0, 3))).toEqual([0.0, 0.1, 0.2]);
  });

  it("ignores empty batch (no n_signals fixation)", () => {
    const b = appendBatch(createBuffer(), [], []);
    expect(b.length).toBe(0);
    expect(b.n_signals).toBe(0);
  });

  it("ignores batch where times length != values length (defensive)", () => {
    // wire の規約違反 (= サーバ側 bug)。drop して以前の状態を返す。
    const b0 = createBuffer();
    const b1 = appendBatch(b0, [0.0, 0.1], [[1, 2]]); // values length=1 != times length=2
    expect(b1.length).toBe(0);
  });
});

describe("appendBatch (subsequent batches)", () => {
  it("appends without reallocation when within capacity", () => {
    let b = createBuffer();
    b = appendBatch(b, [0.0], [[1]]);
    const timesRef = b.times;
    b = appendBatch(b, [0.1], [[2]]);
    expect(b.times).toBe(timesRef); // 参照同一性 = 再確保していない
    expect(b.length).toBe(2);
  });

  it("doubles capacity when exceeded", () => {
    let b = createBuffer(); // capacity=1024
    // 1025 点入れる → 1024 → 2048 に倍々
    const times = Array.from({ length: 1025 }, (_, i) => i * 0.01);
    const values = times.map((_, i) => [i, i * 2]);
    b = appendBatch(b, times, values);
    expect(b.length).toBe(1025);
    expect(b.capacity).toBeGreaterThanOrEqual(1025);
    expect(b.capacity).toBe(2048); // 1024 → 2048 (倍々)
    expect(b.values.length).toBe(2);
    // データ整合性: 末尾 5 点が正しいか
    expect(b.times[1024]).toBeCloseTo(10.24);
    expect(b.values[0]![1024]).toBe(1024);
    expect(b.values[1]![1024]).toBe(2048);
  });

  it("doubles capacity multiple times when batch is large", () => {
    let b = createBuffer();
    // 5000 点を一気に → 1024 → 2048 → 4096 → 8192
    const n = 5000;
    const times = new Array<number>(n);
    const values = new Array<number[]>(n);
    for (let i = 0; i < n; i++) {
      times[i] = i;
      values[i] = [i];
    }
    b = appendBatch(b, times, values);
    expect(b.length).toBe(n);
    expect(b.capacity).toBe(8192);
    expect(b.values[0]![4999]).toBe(4999);
  });

  it("rejects batch with different n_signals after first fix", () => {
    let b = createBuffer();
    b = appendBatch(b, [0.0], [[1, 2]]); // n_signals=2
    const before = b;
    // n_signals=3 の batch は drop (= サーバ側 bug の可能性、UI を破壊しない)
    const after = appendBatch(b, [0.1], [[1, 2, 3]]);
    expect(after).toBe(before); // 参照変わらず = 何もしていない
  });
});

describe("subarray slicing", () => {
  it("can produce a length-bounded view for plotting", () => {
    let b = createBuffer();
    b = appendBatch(b, [0.0, 0.1, 0.2], [
      [1],
      [2],
      [3],
    ]);
    const tView = b.times.subarray(0, b.length);
    const v0View = b.values[0]!.subarray(0, b.length);
    expect(tView.length).toBe(3);
    expect(v0View.length).toBe(3);
    expect(Array.from(v0View)).toEqual([1, 2, 3]);
  });
});

describe("amortized O(1) append", () => {
  it("handles 100k point append in linear time", () => {
    // 1 点ずつ 100k 回 append しても、倍々増加で O(N) で済む。
    // CI 環境は遅いので「絶対閾値」は厳密でなくスモークレベル: 5 秒以内。
    let b = createBuffer();
    const N = 100_000;
    const t0 = performance.now();
    for (let i = 0; i < N; i++) {
      b = appendBatch(b, [i * 0.001], [[i, i * 2]]);
    }
    const elapsed = performance.now() - t0;
    expect(b.length).toBe(N);
    expect(elapsed).toBeLessThan(5000);
  });
});

describe("ScopeBuffer type", () => {
  it("matches expected shape", () => {
    const b: ScopeBuffer = createBuffer();
    expect(b).toHaveProperty("times");
    expect(b).toHaveProperty("values");
    expect(b).toHaveProperty("length");
    expect(b).toHaveProperty("capacity");
    expect(b).toHaveProperty("n_signals");
  });
});

// ─── 補強テスト (ADR-0023 境界値・エッジケース) ──────────────────────────────

describe("appendBatch: n_signals=1 single signal trace", () => {
  it("stores a single signal correctly across multiple batches", () => {
    // n_signals=1 の最小構成が正しく動くことを保証する
    let b = createBuffer();
    b = appendBatch(b, [0.0, 0.1, 0.2], [[10], [20], [30]]);
    expect(b.n_signals).toBe(1);
    expect(b.length).toBe(3);
    expect(b.values.length).toBe(1);
    expect(Array.from(b.values[0]!.subarray(0, 3))).toEqual([10, 20, 30]);
  });

  it("appends a second batch to a single-signal buffer without reallocation", () => {
    let b = createBuffer();
    b = appendBatch(b, [0.0], [[100]]);
    const timesRef = b.times;
    const valuesRef = b.values[0];
    b = appendBatch(b, [0.1], [[200]]);
    // 容量内なので typed array 参照が変わらない
    expect(b.times).toBe(timesRef);
    expect(b.values[0]).toBe(valuesRef);
    expect(b.length).toBe(2);
    expect(b.values[0]![1]).toBe(200);
  });
});

describe("appendBatch: capacity boundary at exactly INITIAL_CAPACITY (1024)", () => {
  it("fills buffer to exactly capacity=1024 without reallocation", () => {
    // ちょうど 1024 点: 拡張トリガー直前の境界 — 再確保が起きてはいけない
    const N = INITIAL_CAPACITY; // 1024
    const times = Array.from({ length: N }, (_, i) => i * 0.001);
    const values = times.map((_, i) => [i]);
    let b = createBuffer();
    const initialTimesRef = b.times; // createBuffer() の時点での参照 (まだ n_signals 未確定)

    b = appendBatch(b, times, values);

    expect(b.length).toBe(N);
    expect(b.capacity).toBe(INITIAL_CAPACITY); // 拡張していない
    // 初回 batch は必ず realloc (n_signals 確定) なので新しい times になる
    // 容量は維持されているべき
    expect(b.times.length).toBe(INITIAL_CAPACITY);
    // データ末尾 (index 1023) が正しい
    expect(b.times[N - 1]).toBeCloseTo((N - 1) * 0.001);
    expect(b.values[0]![N - 1]).toBe(N - 1);
    // 参照が安定しているか: capacity 内で 2 回目以降 append は参照変わらない
    const timesRef2 = b.times;
    b = appendBatch(b, [N * 0.001], [[N]]); // 1025 点目 → realloc
    expect(b.times).not.toBe(timesRef2); // 拡張で新参照になる
    expect(b.capacity).toBe(2048);
    // 元の参照は今は使わない; 初回リファレンスは確保前なので比較しない
    void initialTimesRef;
  });

  it("triggers reallocation on the 1025th point (capacity+1)", () => {
    // 拡張トリガー直後 (1025 点目) で capacity が正確に 2048 になる
    const N = INITIAL_CAPACITY + 1; // 1025
    const times = Array.from({ length: N }, (_, i) => i);
    const values = times.map((_, i) => [i * 10, i * 20]);
    let b = createBuffer();
    b = appendBatch(b, times, values);

    expect(b.length).toBe(N);
    expect(b.capacity).toBe(2048);
    // 既存データが正しくコピーされているか (index 0 と index 1024 の両端)
    expect(b.times[0]).toBe(0);
    expect(b.times[1024]).toBe(1024);
    expect(b.values[0]![1024]).toBe(10240);
    expect(b.values[1]![1024]).toBe(20480);
  });
});

describe("appendBatch: reference stability for shallow comparison (zustand)", () => {
  it("keeps times and values[p] reference stable when within capacity", () => {
    // 容量内なら times / values[p] の参照が安定 = zustand の浅比較が効く
    let b = createBuffer();
    b = appendBatch(b, [0.0, 0.1], [[1, 2], [3, 4]]);
    const t0 = b.times;
    const v0 = b.values[0];
    const v1 = b.values[1];

    b = appendBatch(b, [0.2, 0.3], [[5, 6], [7, 8]]);
    expect(b.times).toBe(t0);
    expect(b.values[0]).toBe(v0);
    expect(b.values[1]).toBe(v1);
  });

  it("changes times and values[p] reference when capacity is exceeded", () => {
    // 拡張時は必ず新しい typed array に置き換わる
    const N = INITIAL_CAPACITY + 1;
    const times = Array.from({ length: N }, (_, i) => i);
    const values = times.map((_, i) => [i]);
    let b = createBuffer();
    // 初回 batch (realloc あり): 参照が確定
    b = appendBatch(b, times.slice(0, INITIAL_CAPACITY), values.slice(0, INITIAL_CAPACITY));
    const t0 = b.times;
    const v0 = b.values[0];

    // capacity 超え → realloc
    b = appendBatch(b, [times[INITIAL_CAPACITY]!], [[values[INITIAL_CAPACITY]![0]!]]);
    expect(b.times).not.toBe(t0);
    expect(b.values[0]).not.toBe(v0);
  });
});

describe("appendBatch: large n_signals (n_signals=16)", () => {
  it("allocates all 16 signal columns on first batch", () => {
    // 16 信号: メモリ確保が線形にスケールするか
    const n = 16;
    const row = Array.from({ length: n }, (_, p) => p * 10);
    let b = createBuffer();
    b = appendBatch(b, [0.0], [row]);

    expect(b.n_signals).toBe(n);
    expect(b.values.length).toBe(n);
    for (let p = 0; p < n; p++) {
      expect(b.values[p]).toBeInstanceOf(Float64Array);
      expect(b.values[p]![0]).toBe(p * 10);
    }
  });
});

describe("appendBatch: special float values (NaN, Infinity, -0)", () => {
  it("stores NaN without information loss", () => {
    // Float64Array は NaN を保持できる
    let b = createBuffer();
    b = appendBatch(b, [0.0], [[NaN]]);
    expect(Number.isNaN(b.values[0]![0])).toBe(true);
  });

  it("stores Infinity and -Infinity without information loss", () => {
    let b = createBuffer();
    b = appendBatch(b, [0.0, 0.1], [[Infinity], [-Infinity]]);
    expect(b.values[0]![0]).toBe(Infinity);
    expect(b.values[0]![1]).toBe(-Infinity);
  });

  it("stores -0 and preserves its sign", () => {
    // Float64Array は -0 を格納できる (IEEE 754 準拠)
    let b = createBuffer();
    b = appendBatch(b, [0.0], [[-0]]);
    // Object.is で -0 を区別する
    expect(Object.is(b.values[0]![0], -0)).toBe(true);
  });

  it("stores NaN in the times column without information loss", () => {
    // 非単調な時刻やセンサ欠損で NaN 時刻が来ても drop しない (= 順序検証は描画側責務)
    let b = createBuffer();
    b = appendBatch(b, [NaN], [[42]]);
    expect(Number.isNaN(b.times[0])).toBe(true);
    expect(b.values[0]![0]).toBe(42);
  });
});

describe("appendBatch: massive single batch (multi-level doubling)", () => {
  it("handles 50000 points in a single batch with correct multi-level capacity doubling", () => {
    // 50000 点を 1 回: 1024 → 2048 → 4096 → ... → 65536
    const N = 50_000;
    const times = Array.from({ length: N }, (_, i) => i * 0.01);
    const values = times.map((_, i) => [i, i + 1]);
    let b = createBuffer();
    b = appendBatch(b, times, values);

    expect(b.length).toBe(N);
    expect(b.capacity).toBe(65536); // 2^16
    expect(b.n_signals).toBe(2);
    // 先頭と末尾のデータ整合性
    expect(b.times[0]).toBeCloseTo(0);
    expect(b.times[N - 1]).toBeCloseTo((N - 1) * 0.01);
    expect(b.values[0]![0]).toBe(0);
    expect(b.values[0]![N - 1]).toBe(N - 1);
    expect(b.values[1]![N - 1]).toBe(N);
  });
});

describe("appendBatch: non-monotonic times", () => {
  it("stores non-monotonic time values without error (ordering is display-side concern)", () => {
    // times が単調増加でない batch はバッファ上は許容する (= 順序検査は描画側責務)
    let b = createBuffer();
    b = appendBatch(b, [0.3, 0.1, 0.2], [[3], [1], [2]]);
    expect(b.length).toBe(3);
    expect(Array.from(b.times.subarray(0, 3))).toEqual([0.3, 0.1, 0.2]);
  });
});

describe("appendBatch: empty batch is a no-op", () => {
  it("returns the same reference for times=[] values=[] after fixation", () => {
    // n_signals が確定した後の empty batch は prev 参照そのまま返る
    let b = createBuffer();
    b = appendBatch(b, [0.0], [[1]]);
    const prev = b;
    const next = appendBatch(b, [], []);
    expect(next).toBe(prev);
  });
});

describe("appendBatch: mismatched row lengths in values (defensive)", () => {
  it("drops batch where a values row has fewer elements than n_signals", () => {
    // values[i] の長さが n_signals より少ない不正入力 (= サーバ側 bug) は drop
    let b = createBuffer();
    b = appendBatch(b, [0.0], [[1, 2]]); // n_signals=2 確定
    const prev = b;
    // 2 回目: values[i] が長さ 1 (n_signals=2 と不一致)
    const next = appendBatch(b, [0.1], [[99]]); // [[99]] で n_signals=1 → mismatch
    expect(next).toBe(prev);
    expect(next.length).toBe(1);
  });
});
