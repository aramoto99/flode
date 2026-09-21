// ADR-0079 §(9) (Stage 2): ベクトル配線の太線表示と設定トグル、Inspector の nested scope。

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { resolveScope } from "../src/components/SignalDtypeSection";
import {
  DIAGRAM_EDGE_STYLE,
  DIAGRAM_EDGE_STYLE_VECTOR,
  edgeStyleForShape,
} from "../src/lib/diagramConverter";
import { useAppStore } from "../src/store/appStore";
import type { DtypesResponse } from "../src/types/api";

describe("edgeStyleForShape (ADR-0079 §(9))", () => {
  it("uses the bold style only for rank >= 1 shapes when enabled", () => {
    expect(edgeStyleForShape([3], true)).toBe(DIAGRAM_EDGE_STYLE_VECTOR);
    expect(edgeStyleForShape([2, 2], true)).toBe(DIAGRAM_EDGE_STYLE_VECTOR);
    expect(edgeStyleForShape([], true)).toBe(DIAGRAM_EDGE_STYLE);
    expect(edgeStyleForShape(null, true)).toBe(DIAGRAM_EDGE_STYLE);
  });

  it("falls back to the thin style when the setting is off", () => {
    expect(edgeStyleForShape([3], false)).toBe(DIAGRAM_EDGE_STYLE);
  });
});

describe("vectorEdgesBold setting", () => {
  beforeEach(() => {
    window.localStorage.removeItem("flode.vector_edges");
    useAppStore.setState({ vectorEdgesBold: true });
  });
  afterEach(() => {
    window.localStorage.removeItem("flode.vector_edges");
  });

  it("defaults to on and persists off as '0'", () => {
    expect(useAppStore.getState().vectorEdgesBold).toBe(true);
    useAppStore.getState().setVectorEdgesBold(false);
    expect(useAppStore.getState().vectorEdgesBold).toBe(false);
    expect(window.localStorage.getItem("flode.vector_edges")).toBe("0");
    useAppStore.getState().setVectorEdgesBold(true);
    expect(window.localStorage.getItem("flode.vector_edges")).toBeNull();
  });
});

describe("resolveScope (nested Inspector, ADR-0079 §(6))", () => {
  const leaf: DtypesResponse = {
    schema_version: "signals.v1",
    ports: [{ block_id: "g", direction: "out", port_index: 0, dtype: "float64", shape: [3] }],
    diagnostics: [],
    summary: { total_ports: 1, by_dtype: {}, unresolved: 0, non_float_ports: 0 },
  };
  const root: DtypesResponse = {
    ...leaf,
    ports: [],
    inner: { sub: { ...leaf, inner: { inner: leaf } } },
  };

  it("walks the editing path through inner", () => {
    expect(resolveScope(root, [])).toBe(root);
    expect(resolveScope(root, ["sub"])).toBe(root.inner!.sub);
    expect(resolveScope(root, ["sub", "inner"])).toBe(leaf);
  });

  it("returns null when the path cannot be resolved (Stage 1 responses)", () => {
    expect(resolveScope(leaf, ["sub"])).toBeNull();
    expect(resolveScope(null, [])).toBeNull();
  });
});
