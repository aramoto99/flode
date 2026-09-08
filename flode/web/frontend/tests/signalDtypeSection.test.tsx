// SPEC-0028 (SM-D Stage 1): SignalDtypeSection の vitest。
// store ベース表示 / auto_note / island・state hint / unknown 温存 / 非表示条件。
// (Stage 0 の fetch/debounce は lib/dtypeResolution.ts へ移動 — 同 fetcher の
//  debounce/abort は dtypeResolutionFetcher.test.tsx が担当)

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SignalDtypeSection } from "../src/components/SignalDtypeSection";
import { _setDtypeResolutionForTest } from "../src/lib/dtypeResolution";
import { useAppStore } from "../src/store/appStore";
import type { DtypesResponse, FlwModel } from "../src/types/api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) => {
      if (typeof fallback === "string") return fallback;
      if (
        fallback !== null &&
        typeof fallback === "object" &&
        "defaultValue" in (fallback as Record<string, unknown>)
      ) {
        return String((fallback as Record<string, unknown>).defaultValue);
      }
      return key;
    },
  }),
}));

const UNDECLARED_MODEL = {
  blocks: [{ id: "integ", type: "flode.blocks.continuous.Integrator", params: {} }],
  connections: [],
} as unknown as FlwModel;

const DECLARED_MODEL = {
  blocks: [
    { id: "c", type: "flode.blocks.sources.Constant", params: { dtype: "int32" } },
    { id: "integ", type: "flode.blocks.continuous.Integrator", params: {} },
  ],
  connections: [],
} as unknown as FlwModel;

function responseFor(
  entries: DtypesResponse["ports"],
  diagnostics: DtypesResponse["diagnostics"] = [],
): DtypesResponse {
  return {
    schema_version: "dtypes.v1",
    ports: entries,
    diagnostics,
    summary: {
      total_ports: entries.length,
      by_dtype: {},
      unresolved: 0,
      non_float_ports: 0,
    },
  };
}

beforeEach(() => {
  useAppStore.setState({ editingModel: DECLARED_MODEL, editingPath: [] });
  _setDtypeResolutionForTest(null);
});

afterEach(() => {
  cleanup();
  _setDtypeResolutionForTest(null);
  vi.clearAllMocks();
});

describe("SignalDtypeSection (SPEC-0028 Stage 1)", () => {
  it("renders rows, widened hint, and no shadow note (AC-9)", () => {
    _setDtypeResolutionForTest(
      responseFor(
        [
          { block_id: "integ", direction: "in", port_index: 0, dtype: "float64" },
          { block_id: "integ", direction: "out", port_index: 0, dtype: "float64" },
        ],
        [
          {
            severity: "info",
            code: "dtype.implicit_widening",
            message: "widened",
            block_id: "integ",
            direction: "in",
            port_index: 0,
            from_dtype: "int32",
            to_dtype: "float64",
          },
        ],
      ),
    );
    render(<SignalDtypeSection blockId="integ" />);
    expect(screen.getByTestId("dtype-in-0").textContent).toBe("float64");
    expect(screen.getByTestId("dtype-widened-0").textContent).toBe(
      "Widened from int32 to float64",
    );
    // AC-9: shadow_note は存在しない
    expect(screen.queryByTestId("dtype-shadow-note")).toBeNull();
    // dtype 宣言モデルなので auto_note も出ない
    expect(screen.queryByTestId("dtype-auto-note")).toBeNull();
  });

  it("shows the auto note for models without any declared dtype", () => {
    useAppStore.setState({ editingModel: UNDECLARED_MODEL });
    _setDtypeResolutionForTest(
      responseFor([
        { block_id: "integ", direction: "out", port_index: 0, dtype: "float64" },
      ]),
    );
    render(<SignalDtypeSection blockId="integ" />);
    expect(screen.getByTestId("dtype-auto-note").textContent).toBe(
      "No dtype declared — all signals run as float64.",
    );
  });

  it("shows island and state hints from diagnostics", () => {
    _setDtypeResolutionForTest(
      responseFor(
        [{ block_id: "sub", direction: "out", port_index: 0, dtype: "float64" }],
        [
          {
            severity: "info",
            code: "dtype.opaque_float64_island",
            message: "island",
            block_id: "sub",
            direction: null,
            port_index: null,
            from_dtype: null,
            to_dtype: null,
          },
        ],
      ),
    );
    render(<SignalDtypeSection blockId="sub" />);
    expect(screen.getByTestId("dtype-island-note")).toBeTruthy();
    expect(screen.queryByTestId("dtype-state-note")).toBeNull();
  });

  it("keeps the unknown dash for static-mode results", () => {
    _setDtypeResolutionForTest(
      responseFor([
        { block_id: "pf", direction: "out", port_index: 0, dtype: "unknown" },
      ]),
    );
    render(<SignalDtypeSection blockId="pf" />);
    expect(screen.getByTestId("dtype-out-0").textContent).toBe("—");
    expect(screen.getByTestId("dtype-unresolved-out-0")).toBeTruthy();
  });

  it("hides when no resolution is available", () => {
    render(<SignalDtypeSection blockId="integ" />);
    expect(screen.queryByTestId("dtype-in-0")).toBeNull();
  });

  it("hides while editing inside a subsystem (root scope only)", () => {
    useAppStore.setState({ editingPath: ["sub1"] });
    _setDtypeResolutionForTest(
      responseFor([
        { block_id: "integ", direction: "out", port_index: 0, dtype: "float64" },
      ]),
    );
    render(<SignalDtypeSection blockId="integ" />);
    expect(screen.queryByTestId("dtype-out-0")).toBeNull();
  });
});
