// ADR-0087 / SPEC-0038: 信号名の純関数 (規則・検証付き読み出し・reconcile・id の付け替え)。

import { describe, expect, it } from "vitest";

import {
  MAX_SIGNAL_NAME_CHARS,
  normalizeSignalName,
  parsePortKey,
  readSignalNames,
  reconcileSignalNames,
  remapPortKeyedDictIds,
  renamePortKeyedDictId,
  validateSignalName,
} from "../src/lib/signalNames";
import { remapPortKeyedDict } from "../src/lib/paramRows";
import type { BlockEntry, ConnectionEntry, FlwModel } from "../src/types/api";

function model(
  connections: ConnectionEntry[],
  signal_names?: Record<string, unknown>,
  blocks: BlockEntry[] = [],
): FlwModel {
  const m: FlwModel = {
    schema_version: "0.15",
    simulator: { t_end: 1, dt: 0.1, solver: "RK45", rtol: 1e-3, atol: 1e-6, dt_base: null },
    blocks,
    connections,
  };
  if (signal_names !== undefined) (m as unknown as Record<string, unknown>).signal_names = signal_names;
  return m;
}

const C = (src: string, src_idx: number, dst: string, dst_idx = 0): ConnectionEntry => ({
  src,
  src_idx,
  dst,
  dst_idx,
});

describe("normalizeSignalName / validateSignalName", () => {
  it("trims and NFC-normalizes", () => {
    expect(normalizeSignalName("  é  ")).toBe("é");
  });

  it("accepts an empty name (= clear)", () => {
    expect(validateSignalName(normalizeSignalName("   "))).toBeNull();
  });

  it.each([
    ["ascii", "speed"],
    ["japanese", "左脚の力"],
    ["emoji", "😀 signal"],
    ["combining (counted after NFC)", "é".repeat(MAX_SIGNAL_NAME_CHARS)],
    ["exactly 64 code points of emoji", "😀".repeat(MAX_SIGNAL_NAME_CHARS)],
  ])("accepts %s", (_label, raw) => {
    expect(validateSignalName(normalizeSignalName(raw))).toBeNull();
  });

  it("rejects 65 code points", () => {
    expect(validateSignalName("x".repeat(MAX_SIGNAL_NAME_CHARS + 1))).toBe("too_long");
    expect(validateSignalName("😀".repeat(MAX_SIGNAL_NAME_CHARS + 1))).toBe("too_long");
  });

  it.each([
    ["newline", "a\nb"],
    ["carriage return", "a\rb"],
    ["tab", "a\tb"],
    ["NUL", "a\u0000b"],
    ["line separator", "a b"],
    ["paragraph separator", "a b"],
    ["lone surrogate", "a\ud800b"],
  ])("rejects %s", (_label, raw) => {
    expect(validateSignalName(normalizeSignalName(raw))).toBe("control_char");
  });

  it("uses the same limit as the backend (64)", () => {
    expect(MAX_SIGNAL_NAME_CHARS).toBe(64);
  });
});

describe("parsePortKey / readSignalNames", () => {
  it("splits at the last colon", () => {
    expect(parsePortKey("a:b:3")).toEqual({ src: "a:b", srcIdx: 3 });
    expect(parsePortKey("g:01")).toBeNull();
    expect(parsePortKey("nocolon")).toBeNull();
    expect(parsePortKey(":0")).toBeNull();
  });

  it("ignores malformed keys, non-string and invalid values", () => {
    const raw = JSON.parse(
      '{"g:0":"ok","__proto__":"x","bad":"y","h:1":5,"i:2":"a\\nb","j:3":"   ","k:4":"  pad  "}',
    ) as unknown;
    const names = readSignalNames(raw);
    expect([...names.entries()]).toEqual([
      ["g:0", "ok"],
      ["k:4", "pad"],
    ]);
    expect(({} as Record<string, unknown>).x).toBeUndefined(); // prototype は汚れない
  });

  it("returns empty for non-objects", () => {
    expect(readSignalNames(undefined).size).toBe(0);
    expect(readSignalNames(["a"]).size).toBe(0);
    expect(readSignalNames("x").size).toBe(0);
  });
});

describe("reconcileSignalNames", () => {
  it("keeps a name while at least one wire remains", () => {
    const prev = model([C("g", 0, "a"), C("g", 0, "b")], { "g:0": "n" });
    const next = { ...prev, connections: [C("g", 0, "b")] };
    expect(reconcileSignalNames(prev, next).signal_names).toEqual({ "g:0": "n" });
  });

  it("drops the name when the last wire is removed, and drops the key when empty", () => {
    const prev = model([C("g", 0, "a")], { "g:0": "n" });
    const next = { ...prev, connections: [] };
    const out = reconcileSignalNames(prev, next);
    expect("signal_names" in out).toBe(false);
  });

  it("returns the same reference when nothing changed", () => {
    const prev = model([C("g", 0, "a")], { "g:0": "n" });
    const next = { ...prev, layout: { g: { x: 1, y: 2 } } };
    expect(reconcileSignalNames(prev, next)).toBe(next);
    // 全スコープ検査でも変化なしなら同一参照
    expect(reconcileSignalNames(null, next)).toBe(next);
  });

  it("drops malformed / invalid entries when the scope is re-checked", () => {
    const m = model([C("g", 0, "a")], { "g:0": "n", "zz:9": "orphan", bad: "x", "g:1": 3 });
    expect(reconcileSignalNames(null, m).signal_names).toEqual({ "g:0": "n" });
  });

  it("drops a non-object signal_names", () => {
    const m = model([C("g", 0, "a")], ["x"] as unknown as Record<string, unknown>);
    expect("signal_names" in reconcileSignalNames(null, m)).toBe(false);
  });

  it("reconciles inside a changed Subsystem and skips unchanged ones", () => {
    const sub = (id: string, conns: ConnectionEntry[], names: Record<string, string>): BlockEntry => ({
      id,
      type: "flode.subsystems.subsystem.Subsystem",
      params: { blocks: [], connections: conns, signal_names: names },
    });
    const s1 = sub("s1", [C("g", 0, "o")], { "g:0": "inner" });
    // s2 は孤児キーを持つが、prev と同じ参照なので見ない (= 開いただけのモデルを書き換えない)
    const s2 = sub("s2", [], { "x:0": "orphan" });
    const prev = model([], undefined, [s1, s2]);
    const s1Next: BlockEntry = { ...s1, params: { ...s1.params, connections: [] } };
    const next = { ...prev, blocks: [s1Next, s2] };
    const out = reconcileSignalNames(prev, next);
    expect("signal_names" in (out.blocks[0]!.params as Record<string, unknown>)).toBe(false);
    expect(out.blocks[1]).toBe(s2);
    // 全スコープ検査なら s2 の孤児も消える
    const all = reconcileSignalNames(null, next);
    expect("signal_names" in (all.blocks[1]!.params as Record<string, unknown>)).toBe(false);
  });

  it("does not pollute the prototype with a __proto__ key", () => {
    const raw = JSON.parse('{"__proto__:0":"p","g:0":"n"}') as Record<string, unknown>;
    const m = model([C("__proto__", 0, "a"), C("g", 0, "a")], raw);
    const out = reconcileSignalNames(null, { ...m, connections: [C("g", 0, "a"), C("__proto__", 0, "b")] });
    expect(Object.keys(out.signal_names ?? {})).toEqual(["__proto__:0", "g:0"]);
  });
});

describe("renamePortKeyedDictId / remapPortKeyedDict / remapPortKeyedDictIds", () => {
  it("renames only keys whose id part matches exactly", () => {
    const d = { "g:0": "a", "g:1": "b", "gg:0": "c", "x:g:0": "d" };
    expect(renamePortKeyedDictId(d, "g", "h")).toEqual({
      "h:0": "a",
      "h:1": "b",
      "gg:0": "c",
      "x:g:0": "d",
    });
    expect(renamePortKeyedDictId(d, "none", "h")).toBe(d);
  });

  it("moves keys with an output remap and drops deleted rows", () => {
    const d = { "b:0": "zero", "b:1": "one", "b:2": "two", "c:0": "other" };
    const out = remapPortKeyedDict(d, "b", { side: "output", map: [null, 0, 1] });
    expect(out).toEqual({ "c:0": "other", "b:0": "one", "b:1": "two" });
    expect(remapPortKeyedDict(d, "b", { side: "input", map: [null] })).toBe(d);
  });

  it("re-keys a clipboard dict with the paste id map", () => {
    const d = { "g:0": "a", "h:1": "b" };
    expect(remapPortKeyedDictIds(d, new Map([["g", "g_5"]]))).toEqual({ "g_5:0": "a" });
  });
});
