// ADR-0080 §A3-3 / §A7 (SPEC-0032 §1.4): 由来の解決、差し替えの互換判定・値の
// 引き継ぎ・モデルへの適用、適用直前の再確認、rename での由来の保持。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  BlockEntry,
  ConnectionEntry,
  FlwModel,
  LibraryEntryDetail,
  LibraryMetadata,
  PythonFunctionIntrospectResult,
  PythonFunctionSpec,
} from "../src/types/api";

vi.mock("../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/client")>();
  return {
    ...actual,
    getLibraryEntry: vi.fn(),
    introspectPythonFunctions: vi.fn(),
  };
});

import * as client from "../src/api/client";
import {
  buildLibraryIndex,
  readProvenance,
  resolveProvenance,
} from "../src/lib/libraryProvenance";
import {
  carryOverValues,
  checkReplacementCompatibility,
  replaceBlockInModel,
  type SpecLookup,
} from "../src/lib/libraryReplacement";
import {
  replaceBlockFromLibrary,
  type ReplacementTarget,
} from "../src/lib/libraryReplacementFlow";
import { _resetPythonSpecCacheForTest } from "../src/lib/pythonFunctionSpec";
import { renameBlockInEditing, useAppStore } from "../src/store/appStore";

const api = vi.mocked(client);

const SUBSYSTEM = "flode.subsystems.subsystem.Subsystem";
const PYTHON = "flode.blocks.pythonfunc.PythonFunction";
const INPORT = "flode.subsystems.ports.Inport";
const OUTPORT = "flode.subsystems.ports.Outport";
const ENABLE = "flode.subsystems.control_blocks.Enable";
const TRIGGER = "flode.subsystems.control_blocks.Trigger";
const GAIN = "flode.blocks.mathops.Gain";
const SCOPE = "flode.blocks.sinks.Scope";

/** Subsystem 本体を作る: Inport ``nIn`` 個、Outport ``nOut`` 個、任意で制御ブロック。 */
function subsystem(
  nIn: number,
  nOut: number,
  extra: { enable?: boolean; trigger?: boolean; inner?: BlockEntry[]; params?: Record<string, unknown> } = {},
): { type: string; params: Record<string, unknown> } {
  const blocks: BlockEntry[] = [];
  for (let i = 0; i < nIn; i++) blocks.push({ id: `in${i + 1}`, type: INPORT, params: { port_idx: i } });
  for (let i = 0; i < nOut; i++) blocks.push({ id: `out${i + 1}`, type: OUTPORT, params: { port_idx: i } });
  if (extra.enable) blocks.push({ id: "en", type: ENABLE, params: {} });
  if (extra.trigger) blocks.push({ id: "trg", type: TRIGGER, params: {} });
  blocks.push(...(extra.inner ?? []));
  return { type: SUBSYSTEM, params: { blocks, connections: [], ...extra.params } };
}

function pySpec(overrides: Partial<PythonFunctionSpec> = {}): PythonFunctionSpec {
  return {
    resolved: true,
    func_name: "f",
    n_inputs: 1,
    n_outputs: 1,
    n_states: 0,
    direct_feedthrough: true,
    sample_time: null,
    params_spec: [],
    input_names: ["u"],
    output_names: ["y"],
    editable: { inputs: true, outputs: true, min_inputs: 1, max_inputs: 32, min_outputs: 1, max_outputs: 32 },
    ...overrides,
  };
}

/** コード → 解析結果の lookup を作る。 */
function specs(table: Record<string, PythonFunctionIntrospectResult>): SpecLookup {
  return (code) => (typeof code === "string" ? table[code] : undefined);
}

const NO_SPECS: SpecLookup = () => undefined;

function conn(src: string, srcIdx: number, dst: string, dstIdx: number): ConnectionEntry {
  return { src, src_idx: srcIdx, dst, dst_idx: dstIdx };
}

// ---------------------------------------------------------------------------
// 由来の解決
// ---------------------------------------------------------------------------

function lib(name: string, uid: string | null, revision: number, entryId = "pid"): LibraryMetadata {
  return {
    name,
    uid,
    display_name: name,
    display_name_i18n: {},
    description: "",
    description_i18n: {},
    version: "1",
    origin: name === "user" ? "user" : "path",
    writable: false,
    write_disabled_reason: "",
    entries: [
      {
        id: entryId,
        display_name: "PID",
        display_name_i18n: {},
        description: "",
        description_i18n: {},
        category_suffix: "",
        kind: "subsystem",
        revision,
        updated_at: null,
        contains_python: false,
        python_block_paths: [],
      },
    ],
  };
}

describe("resolveProvenance", () => {
  it("matches by uid regardless of the library name (renamed on export)", () => {
    const index = buildLibraryIndex([lib("user-8c1e2f0a", "uid-A", 2)]);
    const status = resolveProvenance(
      { library: "user", library_uid: "uid-A", entry: "pid", revision: 2 },
      index,
    );
    expect(status.kind).toBe("current");
    if (status.kind === "current") expect(status.library.name).toBe("user-8c1e2f0a");
  });

  it("treats the same name with a different uid as a different library", () => {
    // 別人の user/pid を自分の user/pid と誤認しない
    const index = buildLibraryIndex([lib("user", "uid-MINE", 9)]);
    expect(
      resolveProvenance({ library: "user", library_uid: "uid-THEIRS", entry: "pid", revision: 1 }, index).kind,
    ).toBe("missing");
  });

  it("matches by name when the provenance has no uid", () => {
    const index = buildLibraryIndex([lib("std", null, 1), lib("other", "uid-X", 5)]);
    expect(resolveProvenance({ library: "std", entry: "pid", revision: 1 }, index).kind).toBe("current");
    // uid 無しの由来は、uid を持つライブラリにも名前で一致する
    expect(resolveProvenance({ library: "other", entry: "pid", revision: 5 }, index).kind).toBe("current");
  });

  it("reports update / ahead / current by comparing revisions", () => {
    const index = buildLibraryIndex([lib("user", "uid-A", 3)]);
    const at = (revision: number): string =>
      resolveProvenance({ library: "user", library_uid: "uid-A", entry: "pid", revision }, index).kind;
    expect(at(2)).toBe("update");
    expect(at(3)).toBe("current");
    expect(at(4)).toBe("ahead");
  });

  it("reports missing when the library or the entry is gone", () => {
    const index = buildLibraryIndex([lib("user", "uid-A", 3)]);
    expect(resolveProvenance({ library: "user", library_uid: "uid-A", entry: "deleted", revision: 1 }, index).kind).toBe("missing");
    expect(resolveProvenance({ library: "nope", entry: "pid", revision: 1 }, index).kind).toBe("missing");
  });

  it("treats absent or malformed provenance as none (never throws)", () => {
    const index = buildLibraryIndex([lib("user", "uid-A", 3)]);
    for (const raw of [
      undefined,
      null,
      "user/pid",
      42,
      [],
      {},
      { library: "user", entry: "pid" },
      { library: "user", entry: "pid", revision: "3" },
      { library: "user", entry: "pid", revision: 0 },
      { library: "user", entry: "pid", revision: 1.5 },
      { library: "", entry: "pid", revision: 1 },
      { library: "user", entry: "pid", revision: 1, library_uid: 7 },
    ]) {
      expect(resolveProvenance(raw, index).kind).toBe("none");
    }
  });

  it("readProvenance reads own properties only and rejects unsafe revisions", () => {
    // __proto__ 経由で継承した値は由来として扱わない
    const inherited = Object.create({ library: "user", entry: "pid", revision: 1 }) as object;
    expect(readProvenance(inherited)).toBeNull();
    const viaLiteral = { __proto__: { library: "user", entry: "pid", revision: 1 } };
    expect(readProvenance(viaLiteral)).toBeNull();
    // JSON 由来の "__proto__" / "constructor" キーは無視され、プロトタイプも汚さない
    const parsed: unknown = JSON.parse(
      '{"library":"user","entry":"pid","revision":2,"__proto__":{"polluted":true},"constructor":{"x":1}}',
    );
    expect(readProvenance(parsed)).toEqual({ library: "user", entry: "pid", revision: 2 });
    expect(({} as Record<string, unknown>).polluted).toBeUndefined();
    expect(JSON.stringify(readProvenance(parsed))).not.toContain("constructor");
    // 安全な整数の範囲外
    for (const revision of [1e308, Number.MAX_SAFE_INTEGER + 2, Infinity, NaN, -1]) {
      expect(readProvenance({ library: "user", entry: "pid", revision })).toBeNull();
    }
  });

  it("readProvenance normalizes key order and drops unknown keys", () => {
    expect(
      JSON.stringify(readProvenance({ revision: 2, extra: "x", entry: "pid", library_uid: "u", library: "user" })),
    ).toBe('{"library":"user","library_uid":"u","entry":"pid","revision":2}');
  });
});

// ---------------------------------------------------------------------------
// 互換判定
// ---------------------------------------------------------------------------

describe("checkReplacementCompatibility (Subsystem)", () => {
  const old: BlockEntry = { id: "S", ...subsystem(2, 1) };

  it("allows a version that adds an input at the end", () => {
    const result = checkReplacementCompatibility(
      old,
      subsystem(3, 1),
      [conn("a", 0, "S", 0), conn("b", 0, "S", 1), conn("S", 0, "c", 0)],
      NO_SPECS,
    );
    expect(result).toMatchObject({ ok: true, nOutputs: 1 });
  });

  it("rejects when a connected input disappears, naming the port", () => {
    const result = checkReplacementCompatibility(
      old,
      subsystem(1, 1),
      [conn("a", 0, "S", 0), conn("b", 0, "S", 1)],
      NO_SPECS,
    );
    expect(result).toEqual({ ok: false, issues: [{ kind: "input_missing", index: 1 }] });
  });

  it("allows removing a port that is not connected", () => {
    const result = checkReplacementCompatibility(old, subsystem(1, 1), [conn("a", 0, "S", 0)], NO_SPECS);
    expect(result.ok).toBe(true);
  });

  it("rejects when a connected output disappears", () => {
    const twoOut: BlockEntry = { id: "S", ...subsystem(1, 2) };
    expect(
      checkReplacementCompatibility(twoOut, subsystem(1, 1), [conn("S", 1, "c", 0)], NO_SPECS),
    ).toEqual({ ok: false, issues: [{ kind: "output_missing", index: 1 }] });
    expect(
      checkReplacementCompatibility(twoOut, subsystem(1, 1), [conn("S", 0, "c", 0)], NO_SPECS).ok,
    ).toBe(true);
  });

  it("rejects when the slot kind of a connected input changes (data → enable)", () => {
    // 旧: [data, data]。新: Inport 1 個 + Enable = [data, enable]。index 1 の役割が変わる
    const result = checkReplacementCompatibility(
      old,
      subsystem(1, 1, { enable: true }),
      [conn("a", 0, "S", 0), conn("b", 0, "S", 1)],
      NO_SPECS,
    );
    expect(result).toEqual({
      ok: false,
      issues: [{ kind: "input_kind_changed", index: 1, from: "data", to: "enable" }],
    });
  });

  it("Enabled / Triggered: the control slots follow the data inputs", () => {
    const gated: BlockEntry = { id: "S", ...subsystem(1, 1, { enable: true, trigger: true }) };
    const wires = [conn("a", 0, "S", 0), conn("e", 0, "S", 1), conn("t", 0, "S", 2)];
    // 同じ構成なら可
    expect(
      checkReplacementCompatibility(gated, subsystem(1, 1, { enable: true, trigger: true }), wires, NO_SPECS).ok,
    ).toBe(true);
    // Inport を足すと enable / trigger の index がずれる → 接続中なら不可
    expect(
      checkReplacementCompatibility(gated, subsystem(2, 1, { enable: true, trigger: true }), wires, NO_SPECS),
    ).toEqual({
      ok: false,
      issues: [
        { kind: "input_kind_changed", index: 1, from: "enable", to: "data" },
        { kind: "input_kind_changed", index: 2, from: "trigger", to: "enable" },
      ],
    });
    // Enable を外すと index 1 が trigger になる
    expect(
      checkReplacementCompatibility(gated, subsystem(1, 1, { trigger: true }), wires, NO_SPECS),
    ).toEqual({
      ok: false,
      issues: [
        { kind: "input_kind_changed", index: 1, from: "enable", to: "trigger" },
        { kind: "input_missing", index: 2 },
      ],
    });
  });

  it("ignores connections of other blocks and does not compare shapes", () => {
    const result = checkReplacementCompatibility(
      old,
      subsystem(0, 0),
      [conn("x", 0, "y", 5), conn("y", 3, "x", 9)],
      NO_SPECS,
    );
    expect(result.ok).toBe(true);
  });

  it("reports renamed boundary ports as a notice, not as a rejection", () => {
    const renamed = subsystem(2, 1);
    (renamed.params.blocks as BlockEntry[])[1]!.id = "setpoint";
    const result = checkReplacementCompatibility(old, renamed, [conn("a", 0, "S", 1)], NO_SPECS);
    expect(result).toMatchObject({ ok: true, portNameChanges: ["in[1] in2 → setpoint"] });
  });
});

describe("checkReplacementCompatibility (PythonFunction)", () => {
  const old: BlockEntry = { id: "F", type: PYTHON, params: { code: "old" } };
  const body = { type: PYTHON, params: { code: "new" } };
  const wires = [conn("a", 0, "F", 0), conn("b", 0, "F", 1), conn("F", 0, "c", 0)];

  it("refuses to judge without the analysis of both codes (no 1-in / 1-out guess)", () => {
    expect(checkReplacementCompatibility(old, body, [], NO_SPECS)).toEqual({
      ok: false,
      issues: [
        { kind: "spec_unavailable", side: "old" },
        { kind: "spec_unavailable", side: "new" },
      ],
    });
    // 片方だけ取得済みでも拒否
    expect(
      checkReplacementCompatibility(old, body, [], specs({ old: pySpec() })),
    ).toEqual({ ok: false, issues: [{ kind: "spec_unavailable", side: "new" }] });
  });

  it("refuses when the new code failed analysis", () => {
    const failed: PythonFunctionIntrospectResult = {
      resolved: false,
      error: { message: "syntax", lineno: 1, col: 1, kind: "syntax" },
    };
    expect(
      checkReplacementCompatibility(old, body, [], specs({ old: pySpec(), new: failed })),
    ).toEqual({ ok: false, issues: [{ kind: "spec_unavailable", side: "new" }] });
  });

  it("uses the analyzed port counts", () => {
    const table = specs({
      old: pySpec({ n_inputs: 2, input_names: ["u", "v"] }),
      new: pySpec({ n_inputs: 3, input_names: ["u", "w", "x"] }),
    });
    expect(checkReplacementCompatibility(old, body, wires, table)).toMatchObject({
      ok: true,
      portNameChanges: ["in[1] v → w"],
    });
    const shrunk = specs({ old: pySpec({ n_inputs: 2 }), new: pySpec({ n_inputs: 1 }) });
    expect(checkReplacementCompatibility(old, body, wires, shrunk)).toEqual({
      ok: false,
      issues: [{ kind: "input_missing", index: 1 }],
    });
  });

  it("rejects block types that cannot be library entries", () => {
    const gain: BlockEntry = { id: "G", type: GAIN, params: { k: 1 } };
    expect(checkReplacementCompatibility(gain, subsystem(1, 1), [], NO_SPECS)).toEqual({
      ok: false,
      issues: [{ kind: "unsupported_type", side: "old", type: GAIN }],
    });
  });
});

// ---------------------------------------------------------------------------
// 値の引き継ぎ
// ---------------------------------------------------------------------------

describe("carryOverValues", () => {
  it("Subsystem: keeps same-name mask values whose type fits, lists the rest", () => {
    const old = subsystem(1, 1, {
      params: { mask_values: { Kp: 2.5, Ki: 3, N: 7.5, flag: true, mode: 1, gone: 9 } },
    });
    const next = subsystem(1, 1, {
      params: {
        mask_params: [
          { name: "Kp", type: "float", default: 1.0, description: "" },
          { name: "Ki", type: "float", default: 0.1, description: "" },
          { name: "N", type: "int", default: 10, description: "" },
          { name: "flag", type: "bool", default: false, description: "" },
          { name: "mode", type: "bool", default: false, description: "" },
          { name: "Kd", type: "float", default: 0.5, description: "" },
        ],
        mask_values: { Kp: 1.0, Ki: 0.1, N: 10, flag: false, mode: false, Kd: 0.5 },
      },
    });
    const { params, notCarried } = carryOverValues(old, next, NO_SPECS);
    expect(params.mask_values).toEqual({
      Kp: 2.5, // float ← float
      Ki: 3, // float ← int
      N: 10, // int ← 7.5 は不可 → 新版の既定値
      flag: true, // bool ← bool
      mode: false, // bool ← 数値 は不可 → 新版の既定値
      Kd: 0.5, // 新規の名前 → 新版の既定値
    });
    expect(notCarried.sort()).toEqual(["N", "gone", "mode"]);
    // 本体 (内部ブロック・宣言) は新版のもの
    expect(params.blocks).toBe(next.params.blocks);
    expect(params.mask_params).toBe(next.params.mask_params);
    // 入力は変更しない
    expect(next.params.mask_values).toMatchObject({ Kp: 1.0 });
  });

  it("Subsystem: nothing to carry when the old block has no mask values", () => {
    const next = subsystem(1, 1, { params: { mask_values: { Kp: 1 } } });
    const { params, notCarried } = carryOverValues(subsystem(1, 1), next, NO_SPECS);
    expect(params).toEqual(next.params);
    expect(notCarried).toEqual([]);
  });

  it("Subsystem: does not invent mask_values when the new version has no mask", () => {
    const old = subsystem(1, 1, { params: { mask_values: { Kp: 2 } } });
    const { params, notCarried } = carryOverValues(old, subsystem(1, 1), NO_SPECS);
    expect(params).not.toHaveProperty("mask_values");
    expect(notCarried).toEqual(["Kp"]);
  });

  it("PythonFunction: keeps user_params declared by the new code with a fitting type", () => {
    const old = { type: PYTHON, params: { code: "old", user_params: { gain: 4, label: "a", removed: 1, n: 2.5 } } };
    const next = { type: PYTHON, params: { code: "new", user_params: { gain: 1.0, label: "x", n: 3, fresh: true } } };
    const table = specs({
      new: pySpec({
        params_spec: [
          { name: "gain", type: "float", has_default: true, default: 1.0, description: "" },
          { name: "label", type: "str", has_default: true, default: "x", description: "" },
          { name: "n", type: "int", has_default: true, default: 3, description: "" },
          { name: "fresh", type: "bool", has_default: true, default: true, description: "" },
        ],
      }),
    });
    const { params, notCarried } = carryOverValues(old, next, table);
    expect(params.user_params).toEqual({ gain: 4, label: "a", n: 3, fresh: true });
    expect(params.code).toBe("new");
    expect(notCarried.sort()).toEqual(["n", "removed"]);
  });

  it("carries nothing across different block kinds", () => {
    const old = subsystem(1, 1, { params: { mask_values: { Kp: 2 } } });
    const next = { type: PYTHON, params: { code: "new" } };
    expect(carryOverValues(old, next, NO_SPECS)).toEqual({ params: next.params, notCarried: [] });
  });
});

// ---------------------------------------------------------------------------
// モデルへの適用 / 実行手順
// ---------------------------------------------------------------------------

const PROVENANCE = { library: "user", library_uid: "uid-A", entry: "pid", revision: 1 };

function model(): FlwModel {
  return {
    schema_version: "0.15",
    simulator: { t_end: 1, dt: 0.1, solver: "RK45", rtol: 1e-6, atol: 1e-8, dt_base: null },
    blocks: [
      { id: "src", type: "flode.blocks.sources.Constant", params: { value: 1 } },
      {
        id: "PID",
        ...subsystem(1, 2, {
          inner: [
            { id: "old_scope", type: SCOPE, params: {} },
            { id: "shared_scope", type: SCOPE, params: {} },
          ],
          params: { mask_values: { Kp: 2.5 } },
        }),
        provenance: PROVENANCE,
      },
      { id: "sink", type: SCOPE, params: {} },
    ],
    connections: [conn("src", 0, "PID", 0), conn("PID", 0, "sink", 0)],
    layout: { src: { x: 0, y: 0 }, PID: { x: 100, y: 20, w: 120, h: 60, flipped: true }, sink: { x: 300, y: 0 } },
    branch_waypoints: {
      "PID:0": { axis: "x", pos: 200 },
      "PID:1": { axis: "x", pos: 210 },
      "src:0": { axis: "x", pos: 50 },
    },
    scope_settings: {
      old_scope: { legend: "off" },
      shared_scope: { legend: "top" },
      sink: { legend: "bottom" },
    },
  };
}

/** ライブラリの新版 (rev 2): 出力 1 本、内部 Scope は shared_scope と new_scope。 */
function newDetail(overrides: Partial<LibraryEntryDetail> = {}): LibraryEntryDetail {
  return {
    id: "pid",
    display_name: "PID",
    display_name_i18n: {},
    description: "",
    description_i18n: {},
    category_suffix: "",
    kind: "subsystem",
    revision: 2,
    updated_at: null,
    contains_python: false,
    python_block_paths: [],
    library_uid: "uid-A",
    block: {
      id: "PID",
      ...subsystem(2, 1, {
        inner: [
          { id: "shared_scope", type: SCOPE, params: {} },
          { id: "new_scope", type: SCOPE, params: {} },
        ],
        params: {
          mask_params: [{ name: "Kp", type: "float", default: 1.0, description: "" }],
          mask_values: { Kp: 1.0 },
        },
      }),
    },
    ...overrides,
  };
}

const TARGET: ReplacementTarget = {
  filePath: "m.flw.json",
  path: [],
  blockId: "PID",
  provenance: PROVENANCE,
  libraryName: "user",
};

beforeEach(() => {
  _resetPythonSpecCacheForTest();
  useAppStore.getState().setEditingModel(model());
  useAppStore.setState({ editingPath: [], selectedFilePath: "m.flw.json", dirty: false });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("replaceBlockInModel", () => {
  const replacement: BlockEntry = { ...newDetail().block, id: "PID", provenance: { ...PROVENANCE, revision: 2 } };

  it("keeps id, layout and connections; replaces the body and provenance", () => {
    const before = model();
    const after = replaceBlockInModel(before, [], "PID", replacement, 1);
    expect(after.blocks[1]).toBe(replacement);
    expect(after.blocks[0]).toBe(before.blocks[0]);
    expect(after.layout).toEqual(before.layout);
    expect(after.connections).toEqual(before.connections);
  });

  it("drops branch waypoints of outputs that no longer exist", () => {
    const after = replaceBlockInModel(model(), [], "PID", replacement, 1);
    expect(after.branch_waypoints).toEqual({
      "PID:0": { axis: "x", pos: 200 },
      "src:0": { axis: "x", pos: 50 },
    });
  });

  it("drops scope_settings that the new inner structure cannot resolve", () => {
    const after = replaceBlockInModel(model(), [], "PID", replacement, 1);
    // old_scope は新版に無い → 削除。shared_scope は新版にもある、sink は外側 → 保持
    expect(after.scope_settings).toEqual({
      shared_scope: { legend: "top" },
      sink: { legend: "bottom" },
    });
  });

  it("keeps a scope_settings key when a block with the same id still exists elsewhere", () => {
    const m = model();
    m.blocks.push({ id: "old_scope", type: SCOPE, params: {} });
    const after = replaceBlockInModel(m, [], "PID", replacement, 1);
    expect(after.scope_settings).toHaveProperty("old_scope");
  });

  it("returns the same model when the target does not exist", () => {
    const m = model();
    expect(replaceBlockInModel(m, [], "nope", replacement, 1)).toBe(m);
    expect(replaceBlockInModel(m, ["nope"], "PID", replacement, 1)).toBe(m);
  });

  it("replaces a block inside a Subsystem (drill-down scope)", () => {
    const m = model();
    m.blocks.push({
      id: "outer",
      type: SUBSYSTEM,
      params: { blocks: [{ id: "PID", ...subsystem(1, 1), provenance: PROVENANCE }], connections: [] },
    });
    const after = replaceBlockInModel(m, ["outer"], "PID", replacement, 1);
    expect((after.blocks[3]!.params.blocks as BlockEntry[])[0]).toBe(replacement);
    // top-level の同名ブロックは触らない
    expect(after.blocks[1]).toBe(m.blocks[1]);
  });
});

describe("replaceBlockFromLibrary (flow)", () => {
  it("applies in one undo step: body, carried values, provenance, cleanup", async () => {
    api.getLibraryEntry.mockResolvedValue(newDetail());
    const before = useAppStore.getState().editingModel;
    const outcome = await replaceBlockFromLibrary(TARGET);
    expect(outcome).toMatchObject({ status: "applied", revision: 2, notCarried: [] });
    expect(api.getLibraryEntry).toHaveBeenCalledWith("user", "pid");

    const state = useAppStore.getState();
    const block = state.editingModel!.blocks[1]!;
    expect(block.id).toBe("PID");
    expect(block.provenance).toEqual({ library: "user", library_uid: "uid-A", entry: "pid", revision: 2 });
    // 同名かつ型が合うマスク値は引き継ぐ
    expect(block.params.mask_values).toEqual({ Kp: 2.5 });
    // 中身は新版 (Inport 2 個)
    expect((block.params.blocks as BlockEntry[]).filter((b) => b.type === INPORT)).toHaveLength(2);
    expect(state.editingModel!.layout?.PID).toEqual({ x: 100, y: 20, w: 120, h: 60, flipped: true });
    expect(state.editingModel!.connections).toEqual(before!.connections);
    expect(state.editingModel!.scope_settings).not.toHaveProperty("old_scope");
    expect(state.editingModel!.branch_waypoints).not.toHaveProperty("PID:1");
    expect(state.dirty).toBe(true);
    expect(state.history.past).toHaveLength(1);

    // undo 1 回で完全に戻る
    state.undo();
    expect(useAppStore.getState().editingModel).toEqual(before);
  });

  it("builds provenance from the detail response, not from the list", async () => {
    // 一覧は rev 2 だったが、取得した本体は rev 5 (その間に上書きされた)
    api.getLibraryEntry.mockResolvedValue(newDetail({ revision: 5 }));
    const outcome = await replaceBlockFromLibrary(TARGET);
    expect(outcome).toMatchObject({ status: "applied", revision: 5 });
    const provenance = useAppStore.getState().editingModel!.blocks[1]!.provenance;
    expect(provenance).toEqual({ library: "user", library_uid: "uid-A", entry: "pid", revision: 5 });
  });

  it("uses the current name of the uid-matched library", async () => {
    api.getLibraryEntry.mockResolvedValue(newDetail());
    await replaceBlockFromLibrary({ ...TARGET, libraryName: "user-8c1e2f0a" });
    expect(api.getLibraryEntry).toHaveBeenCalledWith("user-8c1e2f0a", "pid");
    expect(useAppStore.getState().editingModel!.blocks[1]!.provenance?.library).toBe("user-8c1e2f0a");
  });

  it("rejects without touching the model when a connected port would be lost", async () => {
    useAppStore.getState().applyEditingModel((m) => ({
      ...m,
      connections: [...m.connections, conn("PID", 1, "sink", 0)],
    }));
    useAppStore.setState({ dirty: false });
    const before = useAppStore.getState().editingModel;
    api.getLibraryEntry.mockResolvedValue(newDetail());
    const outcome = await replaceBlockFromLibrary(TARGET);
    expect(outcome).toEqual({ status: "incompatible", issues: [{ kind: "output_missing", index: 1 }] });
    expect(useAppStore.getState().editingModel).toBe(before);
    expect(useAppStore.getState().dirty).toBe(false);
  });

  it("lists values that could not be carried over", async () => {
    api.getLibraryEntry.mockResolvedValue(
      newDetail({
        block: {
          id: "PID",
          ...subsystem(1, 2, {
            params: { mask_params: [{ name: "Kp", type: "bool", default: false, description: "" }], mask_values: { Kp: false } },
          }),
        },
      }),
    );
    const outcome = await replaceBlockFromLibrary(TARGET);
    expect(outcome).toMatchObject({ status: "applied", notCarried: ["Kp"] });
    expect(useAppStore.getState().editingModel!.blocks[1]!.params.mask_values).toEqual({ Kp: false });
  });

  it("reports a failed fetch and leaves the model alone", async () => {
    const before = useAppStore.getState().editingModel;
    api.getLibraryEntry.mockRejectedValue(new Error("404 gone"));
    const outcome = await replaceBlockFromLibrary(TARGET);
    expect(outcome.status).toBe("failed");
    expect(useAppStore.getState().editingModel).toBe(before);
  });

  describe("re-check right before applying", () => {
    /** 本体の取得中に ``mutate`` が起きた状況を作る。 */
    async function runWithChangeDuringFetch(mutate: () => void): Promise<string> {
      api.getLibraryEntry.mockImplementation(async () => {
        mutate();
        return newDetail();
      });
      const outcome = await replaceBlockFromLibrary(TARGET);
      return outcome.status;
    }

    /** 対象ブロックが差し替えられていない (rev 1 の由来のまま、または無い) こと。 */
    function expectNotReplaced(): void {
      const model = useAppStore.getState().editingModel;
      const block = model?.blocks.find((b) => b.id === "PID");
      if (block?.provenance !== undefined) expect(block.provenance.revision).not.toBe(2);
    }

    it("aborts when another file was opened", async () => {
      expect(
        await runWithChangeDuringFetch(() => useAppStore.setState({ selectedFilePath: "other.flw.json" })),
      ).toBe("stale");
      expectNotReplaced();
    });

    it("aborts when the user drilled into another scope", async () => {
      expect(await runWithChangeDuringFetch(() => useAppStore.setState({ editingPath: ["PID"] }))).toBe("stale");
      expectNotReplaced();
    });

    it("aborts when the block was deleted", async () => {
      expect(
        await runWithChangeDuringFetch(() =>
          useAppStore.getState().applyEditingModel((m) => ({
            ...m,
            blocks: m.blocks.filter((b) => b.id !== "PID"),
            connections: [],
          })),
        ),
      ).toBe("stale");
    });

    it("aborts when a block with the same id now has a different provenance", async () => {
      expect(
        await runWithChangeDuringFetch(() =>
          useAppStore.getState().applyEditingModel((m) => ({
            ...m,
            blocks: m.blocks.map((b) =>
              b.id === "PID" ? { ...b, provenance: { ...PROVENANCE, entry: "other" } } : b,
            ),
          })),
        ),
      ).toBe("stale");
      expect(useAppStore.getState().editingModel!.blocks[1]!.provenance?.entry).toBe("other");
    });

    it("aborts when the provenance was removed", async () => {
      expect(
        await runWithChangeDuringFetch(() =>
          useAppStore.getState().applyEditingModel((m) => ({
            ...m,
            blocks: m.blocks.map((b) => (b.id === "PID" ? { id: b.id, type: b.type, params: b.params } : b)),
          })),
        ),
      ).toBe("stale");
    });

    it("is stale from the start when the target does not match the model", async () => {
      const outcome = await replaceBlockFromLibrary({ ...TARGET, blockId: "nope" });
      expect(outcome.status).toBe("stale");
      expect(api.getLibraryEntry).not.toHaveBeenCalled();
    });
  });

  describe("PythonFunction", () => {
    const PY_PROVENANCE = { library: "user", library_uid: "uid-A", entry: "fn", revision: 1 };
    const PY_TARGET: ReplacementTarget = { ...TARGET, blockId: "F", provenance: PY_PROVENANCE };

    beforeEach(() => {
      useAppStore.getState().setEditingModel({
        ...model(),
        blocks: [
          { id: "src", type: "flode.blocks.sources.Constant", params: { value: 1 } },
          { id: "F", type: PYTHON, params: { code: "old", user_params: { gain: 4 } }, provenance: PY_PROVENANCE },
        ],
        connections: [conn("src", 0, "F", 0)],
      });
      api.getLibraryEntry.mockResolvedValue(
        newDetail({
          id: "fn",
          kind: "python_function",
          block: { id: "F", type: PYTHON, params: { code: "new", user_params: { gain: 1.0 } } },
        }),
      );
    });

    it("fetches the analysis of both codes before judging, then applies", async () => {
      api.introspectPythonFunctions.mockImplementation(async (items) => ({
        results: Object.fromEntries(
          items.map((item) => [
            item.key,
            pySpec({
              params_spec: [{ name: "gain", type: "float", has_default: true, default: 1.0, description: "" }],
            }),
          ]),
        ),
      }));
      const outcome = await replaceBlockFromLibrary(PY_TARGET);
      expect(outcome).toMatchObject({ status: "applied", notCarried: [] });
      const requested = api.introspectPythonFunctions.mock.calls.flatMap((call) => call[0].map((i) => i.code));
      expect(requested.sort()).toEqual(["new", "old"]);
      const block = useAppStore.getState().editingModel!.blocks[1]!;
      expect(block.params).toEqual({ code: "new", user_params: { gain: 4 } });
      expect(block.provenance?.revision).toBe(2);
    });

    it("refuses when the analysis cannot be fetched", async () => {
      const before = useAppStore.getState().editingModel;
      api.introspectPythonFunctions.mockRejectedValue(new Error("network down"));
      const outcome = await replaceBlockFromLibrary(PY_TARGET);
      // 新旧どちらも取得できていない → 両方を報告する
      expect(outcome).toEqual({
        status: "incompatible",
        issues: [
          { kind: "spec_unavailable", side: "old" },
          { kind: "spec_unavailable", side: "new" },
        ],
      });
      expect(useAppStore.getState().editingModel).toBe(before);
    });

    it("refuses when the new code does not analyze", async () => {
      api.introspectPythonFunctions.mockImplementation(async (items) => ({
        results: Object.fromEntries(
          items.map((item) => [
            item.key,
            item.code === "new"
              ? { resolved: false as const, error: { message: "bad", lineno: 1, col: 1, kind: "syntax" as const } }
              : pySpec(),
          ]),
        ),
      }));
      const outcome = await replaceBlockFromLibrary(PY_TARGET);
      expect(outcome).toEqual({
        status: "incompatible",
        issues: [{ kind: "spec_unavailable", side: "new" }],
      });
    });
  });
});

describe("replaceBlockFromLibrary: reviewed cases", () => {
  it("does nothing when the fetched entry belongs to a library with a different uid", async () => {
    const before = useAppStore.getState().editingModel;
    api.getLibraryEntry.mockResolvedValue(newDetail({ library_uid: "uid-OTHER" }));
    expect((await replaceBlockFromLibrary(TARGET)).status).toBe("stale");
    api.getLibraryEntry.mockResolvedValue(newDetail({ library_uid: null }));
    expect((await replaceBlockFromLibrary(TARGET)).status).toBe("stale");
    expect(useAppStore.getState().editingModel).toBe(before);
  });

  it("name-matched provenance (no uid) accepts whatever uid the library has", async () => {
    const noUid = { library: "user", entry: "pid", revision: 1 };
    useAppStore.getState().applyEditingModel((m) => ({
      ...m,
      blocks: m.blocks.map((b) => (b.id === "PID" ? { ...b, provenance: noUid } : b)),
    }));
    api.getLibraryEntry.mockResolvedValue(newDetail({ library_uid: "uid-A" }));
    const outcome = await replaceBlockFromLibrary({ ...TARGET, provenance: noUid });
    expect(outcome.status).toBe("applied");
  });

  it("replaces from an 'ahead' state (library has an older revision)", async () => {
    const ahead = { ...PROVENANCE, revision: 7 };
    useAppStore.getState().applyEditingModel((m) => ({
      ...m,
      blocks: m.blocks.map((b) => (b.id === "PID" ? { ...b, provenance: ahead } : b)),
    }));
    const beforeReplace = useAppStore.getState().editingModel;
    api.getLibraryEntry.mockResolvedValue(newDetail({ revision: 2 }));
    const outcome = await replaceBlockFromLibrary({ ...TARGET, provenance: ahead });
    expect(outcome).toMatchObject({ status: "applied", revision: 2 });
    expect(useAppStore.getState().editingModel!.blocks[1]!.provenance?.revision).toBe(2);
    useAppStore.getState().undo();
    expect(useAppStore.getState().editingModel).toEqual(beforeReplace);
  });

  it("Subsystem → PythonFunction: allowed when the ports fit; values are not carried", async () => {
    api.getLibraryEntry.mockResolvedValue(
      newDetail({
        kind: "python_function",
        block: { id: "PID", type: PYTHON, params: { code: "new", user_params: { Kp: 9 } } },
      }),
    );
    api.introspectPythonFunctions.mockImplementation(async (items) => ({
      results: Object.fromEntries(items.map((item) => [item.key, pySpec({ n_inputs: 1, n_outputs: 1 })])),
    }));
    const before = useAppStore.getState().editingModel;
    const outcome = await replaceBlockFromLibrary(TARGET);
    expect(outcome).toMatchObject({ status: "applied", notCarried: [] });
    // 取得するのは新版のコードだけ (旧版は Subsystem)
    expect(api.introspectPythonFunctions.mock.calls.flatMap((c) => c[0].map((i) => i.code))).toEqual(["new"]);
    const block = useAppStore.getState().editingModel!.blocks[1]!;
    expect(block.type).toBe(PYTHON);
    expect(block.id).toBe("PID");
    // 種別が違うので旧マスク値 (Kp: 2.5) は引き継がず、新版の既定値のまま
    expect(block.params).toEqual({ code: "new", user_params: { Kp: 9 } });
    expect(useAppStore.getState().editingModel!.connections).toEqual(before!.connections);
    // 旧 Subsystem の内部 Scope の設定は掃除される
    expect(useAppStore.getState().editingModel!.scope_settings).toEqual({ sink: { legend: "bottom" } });
    useAppStore.getState().undo();
    expect(useAppStore.getState().editingModel).toEqual(before);
  });

  it("Subsystem → PythonFunction: rejected when a connected output would be lost", async () => {
    useAppStore.getState().applyEditingModel((m) => ({
      ...m,
      connections: [...m.connections, conn("PID", 1, "sink", 0)],
    }));
    api.getLibraryEntry.mockResolvedValue(
      newDetail({ block: { id: "PID", type: PYTHON, params: { code: "new" } } }),
    );
    api.introspectPythonFunctions.mockImplementation(async (items) => ({
      results: Object.fromEntries(items.map((item) => [item.key, pySpec()])),
    }));
    expect(await replaceBlockFromLibrary(TARGET)).toEqual({
      status: "incompatible",
      issues: [{ kind: "output_missing", index: 1 }],
    });
  });

  it("does not need the analysis of PythonFunctions nested inside a Subsystem", async () => {
    // 内部に PythonFunction を含む新版。外面のポートは Inport / Outport で決まる
    api.getLibraryEntry.mockResolvedValue(
      newDetail({
        block: {
          id: "PID",
          ...subsystem(1, 2, { inner: [{ id: "f", type: PYTHON, params: { code: "nested" } }] }),
        },
      }),
    );
    api.introspectPythonFunctions.mockRejectedValue(new Error("network down"));
    const outcome = await replaceBlockFromLibrary(TARGET);
    expect(outcome.status).toBe("applied");
    expect(api.introspectPythonFunctions).not.toHaveBeenCalled();
  });
});

describe("rename keeps provenance", () => {
  it("a renamed block still carries its provenance", () => {
    useAppStore.getState().selectNode("PID");
    expect(renameBlockInEditing("PID", "Controller")).toBeNull();
    const block = useAppStore.getState().editingModel!.blocks.find((b) => b.id === "Controller");
    expect(block?.provenance).toEqual(PROVENANCE);
    expect(useAppStore.getState().editingModel!.blocks.some((b) => b.id === "PID")).toBe(false);
  });
});
