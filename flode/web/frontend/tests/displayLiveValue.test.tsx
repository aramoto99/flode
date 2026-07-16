// ADR-0023 §Decision §(3): DisplayLiveValue + formatDisplayValue の単体テスト。
//
// DisplayLiveValue は useAppStore(s => s.scopes[blockId]) で SoA ScopeBuffer を
// 読み取り、各信号の最新サンプル (length-1 番目) を表示する。
// useAppStore を vi.mock してバッファの中身を差し替えることで、
// store への依存を切り離して純粋に表示ロジックを検証する。

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ScopeBuffer } from "../src/lib/scopeBuffer";
import {
  DisplayLiveValue,
  formatDisplayValue,
} from "../src/components/BlockNodeView";

// --- useAppStore mock ---
// useAppStore((s) => s.scopes[blockId]) の戻り値をテストごとに差し替える。
// BlockNodeView の import より前に宣言しなければならない (vi.mock が hoist されるため)。
let mockBuffer: ScopeBuffer | undefined = undefined;

vi.mock("../src/store/appStore", () => ({
  useAppStore: (selector: (s: { scopes: Record<string, ScopeBuffer> }) => unknown) =>
    selector({ scopes: { test_block: mockBuffer as ScopeBuffer } }),
  updateBlockSize: vi.fn(),
}));

// @xyflow/react のモック (BlockNodeView が import しているが DisplayLiveValue 単体では不要)
vi.mock("@xyflow/react", () => ({
  Handle: () => null,
  NodeResizer: () => null,
  Position: { Left: "left", Right: "right" },
  useUpdateNodeInternals: () => vi.fn(),
}));

/** ヘルパー: 最小限の ScopeBuffer を作る (Float64Array 列指向 SoA)。 */
function makeBuffer(
  n_signals: number,
  length: number,
  valueFn: (p: number, i: number) => number = (p, i) => p * 100 + i,
): ScopeBuffer {
  const capacity = Math.max(length, 16);
  const times = new Float64Array(capacity);
  for (let i = 0; i < length; i++) times[i] = i * 0.01;

  const values: Float64Array[] = [];
  for (let p = 0; p < n_signals; p++) {
    const col = new Float64Array(capacity);
    for (let i = 0; i < length; i++) col[i] = valueFn(p, i);
    values.push(col);
  }
  return { times, values, length, capacity, n_signals };
}

beforeEach(() => {
  mockBuffer = undefined;
});

afterEach(() => {
  cleanup();
});

describe("DisplayLiveValue: no buffer (undefined)", () => {
  it("shows placeholder when buffer is undefined", () => {
    // scopes[blockId] が存在しない (= シミュレーション未実行 or リセット直後)
    mockBuffer = undefined;
    render(<DisplayLiveValue blockId="test_block" />);
    expect(screen.getByText("— — —")).toBeDefined();
  });
});

describe("DisplayLiveValue: empty buffer (length=0)", () => {
  it("shows placeholder when buffer.length is 0", () => {
    // バッファは確保されているがサンプルがまだ来ていない
    mockBuffer = makeBuffer(1, 0);
    render(<DisplayLiveValue blockId="test_block" />);
    expect(screen.getByText("— — —")).toBeDefined();
  });
});

describe("DisplayLiveValue: n_signals=1, length=1", () => {
  it("shows the single latest value formatted with 3 decimal places", () => {
    // n_signals=1, length=1: 値 = valueFn(0, 0) = 0
    mockBuffer = makeBuffer(1, 1, () => 3.14159);
    render(<DisplayLiveValue blockId="test_block" />);
    // formatDisplayValue(3.14159) = "3.142" (toFixed(3))
    expect(screen.getByText("3.142")).toBeDefined();
  });

  it("shows the last value (length-1) when buffer has multiple samples", () => {
    // length=100 のとき、最新 = index 99 の値
    // valueFn(p=0, i=99) = 99
    mockBuffer = makeBuffer(1, 100, (_p, i) => i * 1.5);
    render(<DisplayLiveValue blockId="test_block" />);
    // valueFn(0, 99) = 99 * 1.5 = 148.5 → "148.500"
    expect(screen.getByText("148.500")).toBeDefined();
  });
});

describe("DisplayLiveValue: n_signals=3, length=100", () => {
  it("shows the latest value of each signal", () => {
    // 3 信号それぞれの index=99 の値を表示する
    // valueFn(p, 99): p=0→99, p=1→199, p=2→299
    mockBuffer = makeBuffer(3, 100, (p, i) => p * 100 + i);
    render(<DisplayLiveValue blockId="test_block" />);
    // formatDisplayValue(99)  = "99.000"
    // formatDisplayValue(199) = "199.000"
    // formatDisplayValue(299) = "299.000"
    expect(screen.getByText("99.000")).toBeDefined();
    expect(screen.getByText("199.000")).toBeDefined();
    expect(screen.getByText("299.000")).toBeDefined();
  });

  it("renders one span per signal", () => {
    mockBuffer = makeBuffer(3, 100);
    const { container } = render(<DisplayLiveValue blockId="test_block" />);
    // 最外 div の直下には 3 つの span が並ぶ
    const spans = container.querySelectorAll("span");
    expect(spans.length).toBe(3);
  });
});

// ─── formatDisplayValue 単体テスト ──────────────────────────────────────────

describe("formatDisplayValue: numeric formatting", () => {
  it.each([
    [0, "0.000"],
    [1.23456, "1.235"],
    [-0.5, "-0.500"],
    [999.9999, "1000.000"], // toFixed(3) で四捨五入
    [10000, "1.00e+4"],     // >= 10000 → exponential(2)
    [-10000, "-1.00e+4"],
    [0.0001, "1.00e-4"],    // < 0.001 && v !== 0 → exponential(2)
    [-0.0001, "-1.00e-4"],
    [0, "0.000"],           // 0 は exponential ではなく toFixed(3)
  ])("formatDisplayValue(%s) === %s", (input, expected) => {
    expect(formatDisplayValue(input)).toBe(expected);
  });

  it("formats Infinity as 'Infinity'", () => {
    expect(formatDisplayValue(Infinity)).toBe("Infinity");
  });

  it("formats -Infinity as '-Infinity'", () => {
    expect(formatDisplayValue(-Infinity)).toBe("-Infinity");
  });

  it("formats NaN as 'NaN'", () => {
    expect(formatDisplayValue(NaN)).toBe("NaN");
  });
});
