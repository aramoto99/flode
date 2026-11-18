// ADR-0087 / SPEC-0038 §4-6: Scope 設定ダイアログの信号行に表示名が出る (凡例と同じ関数)。
// XYGraph の行は今までどおり [i]。

import "../src/i18n";

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ScopeSettingsDialog } from "../src/components/ScopeSettingsDialog";
import { appendBatch, createBuffer } from "../src/lib/scopeBuffer";
import { useAppStore } from "../src/store/appStore";
import type { FlwModel } from "../src/types/api";

function setup(): void {
  const model: FlwModel = {
    schema_version: "0.15",
    simulator: { t_end: 1, dt: 0.1, solver: "RK45", rtol: 1e-3, atol: 1e-6, dt_base: null },
    blocks: [
      { id: "g", type: "flode.blocks.mathops.Gain", params: {} },
      { id: "s", type: "flode.blocks.sinks.Scope", params: { n_inputs: 2 } },
    ],
    connections: [{ src: "g", src_idx: 0, dst: "s", dst_idx: 0 }],
    signal_names: { "g:0": "a long signal name" },
  };
  const buffer = appendBatch(createBuffer(), [0], [[1, 2]]);
  useAppStore.setState({ editingModel: model, editingPath: [], scopes: { s: buffer, xy: buffer } });
}

beforeEach(setup);
afterEach(cleanup);

describe("ScopeSettingsDialog signal rows", () => {
  it("shows the display names with a title (Scope)", () => {
    render(<ScopeSettingsDialog scopeId="s" onClose={() => {}} />);
    fireEvent.click(screen.getAllByRole("tab")[1]!);
    const first = screen.getByTestId("scope-signal-label-0");
    expect(first.textContent).toBe("a long signal name");
    expect(first.getAttribute("title")).toBe("a long signal name");
    expect(screen.getByTestId("scope-signal-label-1").textContent).toBe("s[1]");
  });

  it("keeps [i] for XYGraph", () => {
    render(<ScopeSettingsDialog scopeId="xy" isXY onClose={() => {}} />);
    fireEvent.click(screen.getAllByRole("tab")[1]!);
    expect(screen.queryByTestId("scope-signal-label-0")).toBeNull();
  });
});
