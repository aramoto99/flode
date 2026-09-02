// SPEC-0023 / ADR-0073 §論点 1: PythonFunction spec cache と dynamicPorts / 剪定ガード。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  BlockMetadata,
  FlwModel,
  PythonFunctionIntrospectResponse,
} from "../src/types/api";

const introspectMock = vi.fn<
  (items: ReadonlyArray<{ key: string; code: string }>) => Promise<PythonFunctionIntrospectResponse>
>();
vi.mock("../src/api/client", () => ({
  introspectPythonFunctions: (items: ReadonlyArray<{ key: string; code: string }>) =>
    introspectMock(items),
}));

import { PYTHON_FUNCTION_TYPE } from "../src/lib/blockTypes";
import { canPruneOnParamChange, resolvePortCounts } from "../src/lib/dynamicPorts";
import {
  _resetPythonSpecCacheForTest,
  collectPythonCodes,
  ensurePythonSpecs,
  getCachedPythonSpec,
  getPythonSpecVersion,
  putPythonSpec,
  subscribePythonSpecs,
} from "../src/lib/pythonFunctionSpec";

const META: BlockMetadata = {
  type_path: PYTHON_FUNCTION_TYPE,
  display_name: "Python Function",
  category: "userfunc",
  icon: "userfunc.pythonfunction",
  docstring_summary: "",
  params_spec: [],
  default_n_inputs: 1,
  default_n_outputs: 1,
  port_shapes_in_default: [[]],
  port_shapes_out_default: [[]],
  tags: [],
  is_container: false,
  mask_capable: false,
};

const CODE_2IN = "@block\ndef f(t: float, u: tuple[float, float]) -> float:\n    return u[0]\n";
const SPEC_2IN = {
  resolved: true as const,
  func_name: "f",
  n_inputs: 2,
  n_outputs: 1,
  n_states: 0,
  direct_feedthrough: true,
  sample_time: null,
  params_spec: [],
  input_names: [],
  output_names: [],
  editable: {
    inputs: true,
    outputs: true,
    min_inputs: 1,
    max_inputs: 32,
    min_outputs: 1,
    max_outputs: 32,
  },
};

beforeEach(() => {
  _resetPythonSpecCacheForTest();
  introspectMock.mockReset();
});
afterEach(() => vi.clearAllMocks());

describe("resolvePortCounts (PythonFunction)", () => {
  it("falls back to registry default while the spec is unknown", () => {
    expect(resolvePortCounts(PYTHON_FUNCTION_TYPE, { code: CODE_2IN }, META)).toEqual({
      nInputs: 1,
      nOutputs: 1,
    });
  });

  it("uses the cached spec once available", () => {
    putPythonSpec(CODE_2IN, SPEC_2IN);
    expect(resolvePortCounts(PYTHON_FUNCTION_TYPE, { code: CODE_2IN }, META)).toEqual({
      nInputs: 2,
      nOutputs: 1,
    });
  });

  it("keeps default for an unresolved (erroneous) code", () => {
    putPythonSpec("bad", {
      resolved: false,
      error: { message: "x", lineno: 1, col: 1, kind: "syntax" },
    });
    expect(resolvePortCounts(PYTHON_FUNCTION_TYPE, { code: "bad" }, META)).toEqual({
      nInputs: 1,
      nOutputs: 1,
    });
  });
});

describe("canPruneOnParamChange", () => {
  it("is always true for non-PythonFunction blocks", () => {
    expect(canPruneOnParamChange("flode.blocks.mathops.Sum", { signs: "+" })).toBe(true);
  });

  it("is false while the new code is not analysed (V10 guard)", () => {
    expect(canPruneOnParamChange(PYTHON_FUNCTION_TYPE, { code: CODE_2IN })).toBe(false);
    putPythonSpec(CODE_2IN, SPEC_2IN);
    expect(canPruneOnParamChange(PYTHON_FUNCTION_TYPE, { code: CODE_2IN })).toBe(true);
  });
});

describe("ensurePythonSpecs", () => {
  it("batches only missing codes and notifies subscribers", async () => {
    putPythonSpec("known", SPEC_2IN);
    introspectMock.mockResolvedValue({
      results: { c0: SPEC_2IN, c1: { resolved: false, error: { message: "e", lineno: 2, col: null, kind: "spec" } } },
    });
    const listener = vi.fn();
    subscribePythonSpecs(listener);
    const before = getPythonSpecVersion();
    await ensurePythonSpecs(["known", "a", "b", "a"]);
    expect(introspectMock).toHaveBeenCalledTimes(1);
    expect(introspectMock.mock.calls[0][0].map((i) => i.code)).toEqual(["a", "b"]);
    expect(getCachedPythonSpec("a")).toEqual(SPEC_2IN);
    expect(getCachedPythonSpec("b")?.resolved).toBe(false);
    expect(getPythonSpecVersion()).toBeGreaterThan(before);
    expect(listener).toHaveBeenCalled();
  });

  it("does not cache anything when the request fails (retry later)", async () => {
    introspectMock.mockRejectedValue(new Error("network"));
    await expect(ensurePythonSpecs(["x"])).rejects.toThrow("network");
    expect(getCachedPythonSpec("x")).toBeUndefined();
    introspectMock.mockResolvedValue({ results: { c0: SPEC_2IN } });
    await ensurePythonSpecs(["x"]);
    expect(getCachedPythonSpec("x")).toEqual(SPEC_2IN);
  });
});

describe("collectPythonCodes", () => {
  it("walks nested subsystems", () => {
    const model = {
      schema_version: "0.10",
      simulator: {},
      blocks: [
        { id: "pf1", type: PYTHON_FUNCTION_TYPE, params: { code: "A" } },
        {
          id: "sub",
          type: "flode.subsystems.subsystem.Subsystem",
          params: {
            blocks: [{ id: "pf2", type: PYTHON_FUNCTION_TYPE, params: { code: "B" } }],
          },
        },
        { id: "g", type: "flode.blocks.mathops.Gain", params: { k: 1 } },
      ],
      connections: [],
    } as unknown as FlwModel;
    expect(collectPythonCodes(model)).toEqual(["A", "B"]);
    expect(collectPythonCodes(null)).toEqual([]);
  });
});
