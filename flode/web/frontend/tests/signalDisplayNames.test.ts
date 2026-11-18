// ADR-0087 論点 3 / SPEC-0038 §4: Scope の列ごとの表示名 (deriveScopeColumnLabels) と
// 接続元ポート名 (portNameOf)、hook (useScopeColumnLabels) が再実行なしで名前の変更に追従すること。

import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { _setDtypeResolutionForTest } from "../src/lib/dtypeResolution";
import { portNameOf } from "../src/lib/portNames";
import { _resetPythonSpecCacheForTest, putPythonSpec } from "../src/lib/pythonFunctionSpec";
import {
  deriveScopeColumnLabels,
  expandLabel,
  MUX_TYPE,
  useScopeColumnLabels,
  type LabelScope,
} from "../src/lib/signalDisplayNames";
import { setSignalName, useAppStore } from "../src/store/appStore";
import type {
  BlockEntry,
  BlockMetadata,
  ConnectionEntry,
  FlwModel,
  PythonFunctionIntrospectResult,
} from "../src/types/api";

const C = (src: string, src_idx: number, dst: string, dst_idx = 0): ConnectionEntry => ({
  src,
  src_idx,
  dst,
  dst_idx,
});
const B = (id: string, type: string, params: Record<string, unknown> = {}): BlockEntry => ({
  id,
  type,
  params,
});
const SCOPE = "flode.blocks.sinks.Scope";
const GAIN = "flode.blocks.mathops.Gain";

type Shapes = Record<string, number[]>;
/** "<id>:<in|out>:<idx>" → shape の表で shapeOf を作る (無ければ null = 未解決)。 */
const shapeTable =
  (t: Shapes) =>
  (id: string, dir: "in" | "out", idx: number): number[] | null =>
    t[`${id}:${dir}:${idx}`] ?? null;

function labels(
  scope: LabelScope,
  nColumns: number,
  shapes: Shapes = {},
  portNames: Record<string, string> = {},
): string[] {
  return deriveScopeColumnLabels({
    scope,
    scopeId: "sc",
    nColumns,
    shapeOf: shapeTable(shapes),
    portNameOf: (b, i) => portNames[`${b.id}:${i}`] ?? null,
  });
}

describe("expandLabel", () => {
  it("expands scalar / vector / matrix in C order", () => {
    expect(expandLabel("x", [])).toEqual(["x"]);
    expect(expandLabel("x", null)).toEqual(["x"]);
    expect(expandLabel("v", [3])).toEqual(["v[0]", "v[1]", "v[2]"]);
    expect(expandLabel("m", [2, 2])).toEqual(["m[0,0]", "m[0,1]", "m[1,0]", "m[1,1]"]);
  });
});

describe("deriveScopeColumnLabels", () => {
  const scalarScope = (signal_names?: Record<string, string>): LabelScope => ({
    blocks: [B("g", GAIN), B("h", GAIN), B("sc", SCOPE, { n_inputs: 3 })],
    connections: [C("g", 0, "sc", 0), C("h", 0, "sc", 1)],
    signal_names,
  });

  it("signal name > port name > default; unconnected port is default", () => {
    expect(labels(scalarScope({ "g:0": "speed" }), 3, {}, { "g:0": "pg", "h:0": "ph" })).toEqual([
      "speed",
      "ph",
      "sc[2]",
    ]);
  });

  it("no names → today's default labels (single column = scope id)", () => {
    expect(labels(scalarScope(), 3)).toEqual(["sc[0]", "sc[1]", "sc[2]"]);
    const one: LabelScope = {
      blocks: [B("g", GAIN), B("sc", SCOPE, { n_inputs: 1 })],
      connections: [C("g", 0, "sc")],
    };
    expect(labels(one, 1)).toEqual(["sc"]);
  });

  it("empty port names count as no name", () => {
    expect(labels(scalarScope(), 3, {}, { "g:0": "" })).toEqual(["sc[0]", "sc[1]", "sc[2]"]);
  });

  it("vectors and matrices expand like the backend column labels", () => {
    const scope: LabelScope = {
      blocks: [B("v", GAIN), B("m", GAIN), B("sc", SCOPE, { n_inputs: 2 })],
      connections: [C("v", 0, "sc", 0), C("m", 0, "sc", 1)],
      signal_names: { "v:0": "vel", "m:0": "mat" },
    };
    expect(labels(scope, 6, { "sc:in:0": [2], "sc:in:1": [2, 2] })).toEqual([
      "vel[0]",
      "vel[1]",
      "mat[0,0]",
      "mat[0,1]",
      "mat[1,0]",
      "mat[1,1]",
    ]);
  });

  it("column count mismatch → every column default", () => {
    // 形が分からない (スカラ仮定 = 2 列) のに実際は 4 列 → 全部既定名
    expect(labels(scalarScope({ "g:0": "speed" }), 4)).toEqual(["sc[0]", "sc[1]", "sc[2]", "sc[3]"]);
  });

  it("unknown shapes are treated as scalars", () => {
    expect(labels(scalarScope({ "g:0": "a", "h:0": "b" }), 3)).toEqual(["a", "b", "sc[2]"]);
  });

  it("traces through a Mux; unnamed / unconnected inputs keep the default column name", () => {
    const scope: LabelScope = {
      blocks: [
        B("a", GAIN),
        B("b", GAIN),
        B("mux", MUX_TYPE, { n: 3 }),
        B("sc", SCOPE, { n_inputs: 1 }),
      ],
      connections: [C("a", 0, "mux", 0), C("b", 0, "mux", 1), C("mux", 0, "sc", 0)],
      signal_names: { "a:0": "left" },
    };
    expect(labels(scope, 3, { "sc:in:0": [3] })).toEqual(["left", "sc[1]", "sc[2]"]);
  });

  it("a name on the Mux output wins over its inputs", () => {
    const scope: LabelScope = {
      blocks: [B("a", GAIN), B("mux", MUX_TYPE, { n: 2 }), B("sc", SCOPE, { n_inputs: 1 })],
      connections: [C("a", 0, "mux", 0), C("mux", 0, "sc", 0)],
      signal_names: { "a:0": "left", "mux:0": "both" },
    };
    expect(labels(scope, 2, { "sc:in:0": [2] })).toEqual(["both[0]", "both[1]"]);
  });

  it("follows nested Mux (inner n=1)", () => {
    const scope: LabelScope = {
      blocks: [
        B("a", GAIN),
        B("b", GAIN),
        B("inner", MUX_TYPE, { n: 1 }),
        B("outer", MUX_TYPE, { n: 2 }),
        B("sc", SCOPE, { n_inputs: 1 }),
      ],
      connections: [
        C("a", 0, "inner", 0),
        C("inner", 0, "outer", 0),
        C("b", 0, "outer", 1),
        C("outer", 0, "sc", 0),
      ],
      signal_names: { "a:0": "deep" },
    };
    expect(
      labels(scope, 2, { "sc:in:0": [2], "outer:in:0": [], "outer:in:1": [], "inner:in:0": [] }, { "b:0": "pb" }),
    ).toEqual(["deep", "pb"]);
  });

  it("stops on a Mux cycle", () => {
    const scope: LabelScope = {
      blocks: [B("m1", MUX_TYPE, { n: 1 }), B("m2", MUX_TYPE, { n: 1 }), B("sc", SCOPE, { n_inputs: 1 })],
      connections: [C("m1", 0, "m2", 0), C("m2", 0, "m1", 0), C("m1", 0, "sc", 0)],
    };
    expect(labels(scope, 1)).toEqual(["sc"]);
  });

  it("does not trace through non-Mux blocks", () => {
    const scope: LabelScope = {
      blocks: [B("a", GAIN), B("g", GAIN), B("sc", SCOPE, { n_inputs: 1 })],
      connections: [C("a", 0, "g", 0), C("g", 0, "sc", 0)],
      signal_names: { "a:0": "upstream" },
    };
    expect(labels(scope, 1)).toEqual(["sc"]);
  });

  it("ignores invalid stored names", () => {
    expect(labels(scalarScope({ "g:0": "a\nb", bad: "x" } as Record<string, string>), 3)).toEqual([
      "sc[0]",
      "sc[1]",
      "sc[2]",
    ]);
  });

  it("duplicate names are shown as is", () => {
    expect(labels(scalarScope({ "g:0": "same", "h:0": "same" }), 3)).toEqual(["same", "same", "sc[2]"]);
  });

  it("unknown scope id → default", () => {
    expect(
      deriveScopeColumnLabels({
        scope: scalarScope(),
        scopeId: "missing",
        nColumns: 2,
        shapeOf: () => null,
        portNameOf: () => "x",
      }),
    ).toEqual(["missing[0]", "missing[1]"]);
  });
});

describe("portNameOf", () => {
  afterEach(() => _resetPythonSpecCacheForTest());

  it("uses the Subsystem inner Outport ids by port_idx", () => {
    const sub = B("sub", "flode.subsystems.subsystem.Subsystem", {
      blocks: [
        B("Out_b", "flode.subsystems.ports.Outport", { port_idx: 1 }),
        B("Out_a", "flode.subsystems.ports.Outport", { port_idx: 0 }),
      ],
      connections: [],
    });
    expect(portNameOf(sub, 0, undefined)).toBe("Out_a");
    expect(portNameOf(sub, 1, undefined)).toBe("Out_b");
    expect(portNameOf(sub, 2, undefined)).toBeNull();
  });

  it("uses the PythonFunction introspect output names (resolved only)", () => {
    const code = "def f(u):\n    return u\n";
    const spec = {
      resolved: true,
      n_inputs: 1,
      n_outputs: 2,
      input_names: ["u"],
      output_names: ["y", ""],
    } as unknown as PythonFunctionIntrospectResult;
    putPythonSpec(code, spec);
    const pf = B("pf", "flode.blocks.pythonfunc.PythonFunction", { code });
    expect(portNameOf(pf, 0, undefined)).toBe("y");
    expect(portNameOf(pf, 1, undefined)).toBeNull();
  });

  it("uses user block output_names from the registry", () => {
    const meta = {
      type_path: "user.blocks.Parts",
      category: "user",
      default_n_inputs: 0,
      default_n_outputs: 2,
      params_spec: [],
      output_names: ["alpha", "beta"],
      input_names: [],
      source: "user",
    } as unknown as BlockMetadata;
    const registry = new Map([[meta.type_path, meta]]);
    const ub = B("ub", meta.type_path);
    expect(portNameOf(ub, 1, registry)).toBe("beta");
    expect(portNameOf(ub, 1, undefined)).toBeNull();
  });

  it("built-in blocks have no port name", () => {
    expect(portNameOf(B("g", GAIN), 0, undefined)).toBeNull();
  });
});

describe("useScopeColumnLabels", () => {
  function model(): FlwModel {
    return {
      schema_version: "0.15",
      simulator: { t_end: 1, dt: 0.1, solver: "RK45", rtol: 1e-3, atol: 1e-6, dt_base: null },
      blocks: [B("g", GAIN), B("sc", SCOPE, { n_inputs: 1 })],
      connections: [C("g", 0, "sc")],
      layout: {},
    };
  }

  afterEach(() => {
    _setDtypeResolutionForTest(null);
    useAppStore.setState({ editingModel: null, editingPath: [], history: { past: [], future: [] } });
  });

  it("changes when a name is set (no re-run) and keeps the same array otherwise", () => {
    useAppStore.setState({ editingModel: model(), editingPath: [], history: { past: [], future: [] } });
    const { result } = renderHook(() => useScopeColumnLabels("sc", 1));
    expect(result.current).toEqual(["sc"]);
    act(() => {
      setSignalName("g", 0, "speed");
    });
    expect(result.current).toEqual(["speed"]);
    const before = result.current;
    // 名前に関係しない編集 (位置) では同じ配列を返す
    act(() => {
      useAppStore.getState().applyEditingModel((m) => ({ ...m, layout: { g: { x: 5, y: 5 } } }));
    });
    expect(result.current).toBe(before);
  });

  it("expands once the resolved shape arrives", () => {
    useAppStore.setState({ editingModel: model(), editingPath: [], history: { past: [], future: [] } });
    act(() => {
      setSignalName("g", 0, "v");
    });
    const { result } = renderHook(() => useScopeColumnLabels("sc", 2));
    expect(result.current).toEqual(["sc[0]", "sc[1]"]); // 形が分からない (1 列) と列数 2 が合わない
    act(() => {
      _setDtypeResolutionForTest({
        version: "signals.v1",
        ports: [{ block_id: "sc", direction: "in", port_index: 0, dtype: "float64", shape: [2] }],
      } as unknown as Parameters<typeof _setDtypeResolutionForTest>[0]);
    });
    expect(result.current).toEqual(["v[0]", "v[1]"]);
  });
});
