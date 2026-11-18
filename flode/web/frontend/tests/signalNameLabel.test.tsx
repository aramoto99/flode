// ADR-0087 論点 5 / SPEC-0038 §2-3: 配線脇の信号名ラベルと入力欄、配線のダブルクリック。
//
// キャンバス全体での挙動 (クイック挿入・ブロックのダブルクリックを奪わない、分岐でもラベルは 1 つ、
// 画面が拡大しない) は E2E (tests/e2e/signal-names.spec.ts) で確かめる。

import "../src/i18n";

import { ReactFlowProvider, Position } from "@xyflow/react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BranchableEdge, EDGE_HIT_AREA_TESTID } from "../src/components/BranchableEdge";
import {
  setSignalNameEditHandler,
  SignalNameLabel,
  SIGNAL_NAME_MAX_WIDTH_PX,
} from "../src/components/SignalNameLabel";
import { useAppStore } from "../src/store/appStore";
import type { FlwModel } from "../src/types/api";

function model(): FlwModel {
  return {
    schema_version: "0.15",
    simulator: { t_end: 1, dt: 0.1, solver: "RK45", rtol: 1e-3, atol: 1e-6, dt_base: null },
    blocks: [
      { id: "g", type: "flode.blocks.mathops.Gain", params: {} },
      { id: "sc", type: "flode.blocks.sinks.Scope", params: { n_inputs: 1 } },
    ],
    connections: [{ src: "g", src_idx: 0, dst: "sc", dst_idx: 0 }],
    signal_names: { "g:0": "old" },
  };
}

const handler = { open: vi.fn(), close: vi.fn() };

beforeEach(() => {
  handler.open.mockReset();
  handler.close.mockReset();
  setSignalNameEditHandler(handler);
  useAppStore.setState({
    editingModel: model(),
    editingPath: [],
    history: { past: [], future: [] },
    lastMergeKey: null,
    dirty: false,
  });
});

afterEach(() => {
  cleanup();
  setSignalNameEditHandler(null);
  useAppStore.setState({ editingModel: null, history: { past: [], future: [] } });
});

const label = (props: Partial<Parameters<typeof SignalNameLabel>[0]> = {}) => (
  <SignalNameLabel src="g" srcIdx={0} x={100} y={50} flipped={false} name="old" editing={false} {...props} />
);

describe("SignalNameLabel (display)", () => {
  it("renders nothing without a name when not editing", () => {
    const { container } = render(label({ name: "" }));
    expect(container.firstChild).toBeNull();
  });

  it("truncates by CSS width and shows the full name in title", () => {
    const long = "x".repeat(60);
    render(label({ name: long }));
    const el = screen.getByTestId("signal-name-label");
    expect(el.textContent).toBe(long);
    expect(el.getAttribute("title")).toBe(long);
    expect(el.className).toContain("truncate");
    expect(el.style.maxWidth).toBe(`${SIGNAL_NAME_MAX_WIDTH_PX}px`);
  });

  it("renders the name as text (no HTML)", () => {
    render(label({ name: "<b>bold</b>" }));
    expect(screen.getByTestId("signal-name-label").textContent).toBe("<b>bold</b>");
    expect(screen.getByTestId("signal-name-label").querySelector("b")).toBeNull();
  });

  it("anchors after the output port, mirrored for flipped blocks", () => {
    const { rerender } = render(label());
    const anchor = screen.getByTestId("signal-name-anchor");
    expect(anchor.className).toContain("nodrag");
    expect(anchor.className).toContain("nopan");
    expect(anchor.style.transform).toBe("translate(104px, 48px) translate(0, -100%)");
    rerender(label({ flipped: true }));
    expect(screen.getByTestId("signal-name-anchor").style.transform).toBe(
      "translate(96px, 48px) translate(-100%, -100%)",
    );
  });

  it("double-click on the label starts editing and does not bubble (quick insert)", () => {
    const parent = vi.fn();
    render(<div onDoubleClick={parent}>{label()}</div>);
    fireEvent.doubleClick(screen.getByTestId("signal-name-label"));
    expect(handler.open).toHaveBeenCalledWith("g", 0);
    expect(parent).not.toHaveBeenCalled();
  });
});

describe("SignalNameLabel (editing)", () => {
  it("starts with the current name selected", () => {
    render(label({ editing: true }));
    const input = screen.getByTestId("signal-name-input") as HTMLInputElement;
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe("old");
    expect(input.selectionStart).toBe(0);
    expect(input.selectionEnd).toBe(3);
  });

  it("Enter commits (normalized) and closes", () => {
    render(label({ editing: true }));
    const input = screen.getByTestId("signal-name-input");
    fireEvent.change(input, { target: { value: "  new  " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(useAppStore.getState().editingModel!.signal_names).toEqual({ "g:0": "new" });
    expect(handler.close).toHaveBeenCalledTimes(1);
    expect(useAppStore.getState().history.past.length).toBe(1);
  });

  it("Escape cancels without writing; the following blur does not commit", () => {
    render(label({ editing: true }));
    const input = screen.getByTestId("signal-name-input");
    fireEvent.change(input, { target: { value: "changed" } });
    fireEvent.keyDown(input, { key: "Escape" });
    fireEvent.blur(input);
    expect(useAppStore.getState().editingModel!.signal_names).toEqual({ "g:0": "old" });
    expect(handler.close).toHaveBeenCalledTimes(1);
  });

  it("blur (click outside) commits", () => {
    render(label({ editing: true }));
    const input = screen.getByTestId("signal-name-input");
    fireEvent.change(input, { target: { value: "by blur" } });
    fireEvent.blur(input);
    expect(useAppStore.getState().editingModel!.signal_names).toEqual({ "g:0": "by blur" });
  });

  it("empty clears the name", () => {
    render(label({ editing: true }));
    const input = screen.getByTestId("signal-name-input");
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(useAppStore.getState().editingModel!.signal_names).toBeUndefined();
  });

  it("Enter during IME composition is ignored", () => {
    render(label({ editing: true }));
    const input = screen.getByTestId("signal-name-input");
    fireEvent.compositionStart(input);
    fireEvent.change(input, { target: { value: "へんかん" } });
    fireEvent.keyDown(input, { key: "Enter", isComposing: true });
    expect(handler.close).not.toHaveBeenCalled();
    fireEvent.compositionEnd(input);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(useAppStore.getState().editingModel!.signal_names).toEqual({ "g:0": "へんかん" });
  });

  it("shows an error and keeps editing for a too long name", () => {
    render(label({ editing: true }));
    const input = screen.getByTestId("signal-name-input");
    fireEvent.change(input, { target: { value: "y".repeat(65) } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByTestId("signal-name-error").textContent).toMatch(/64/);
    expect(handler.close).not.toHaveBeenCalled();
    expect(useAppStore.getState().editingModel!.signal_names).toEqual({ "g:0": "old" });
    // 直すとエラーが消える
    fireEvent.change(input, { target: { value: "ok" } });
    expect(screen.queryByTestId("signal-name-error")).toBeNull();
  });

  it("blur with an invalid name shows the error but does not take the focus back", () => {
    render(label({ editing: true }));
    const input = screen.getByTestId("signal-name-input");
    fireEvent.change(input, { target: { value: "z".repeat(65) } });
    const outside = document.createElement("button");
    document.body.appendChild(outside);
    outside.focus();
    fireEvent.blur(input);
    expect(screen.getByTestId("signal-name-error")).toBeTruthy();
    expect(document.activeElement).toBe(outside);
    expect(handler.close).not.toHaveBeenCalled();
    expect(useAppStore.getState().editingModel!.signal_names).toEqual({ "g:0": "old" });
    outside.remove();
  });

  it("shows an error for control characters", () => {
    render(label({ editing: true }));
    const input = screen.getByTestId("signal-name-input");
    fireEvent.change(input, { target: { value: "a\u0007b" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByTestId("signal-name-error")).toBeTruthy();
  });
});

describe("BranchableEdge", () => {
  it("renders the hit area that the canvas uses for double-click (no own listener)", () => {
    render(
      <ReactFlowProvider>
        <svg>
          <BranchableEdge
            id="e0-g-sc"
            source="g"
            target="sc"
            sourceHandleId="0"
            targetHandleId="0"
            sourceX={100}
            sourceY={50}
            targetX={300}
            targetY={50}
            sourcePosition={Position.Right}
            targetPosition={Position.Left}
            data={{ signalName: "old" }}
            // EdgeProps の残り (描画に使わない)
            {...({} as Record<string, never>)}
          />
        </svg>
      </ReactFlowProvider>,
    );
    const hit = screen.getByTestId(EDGE_HIT_AREA_TESTID);
    // 配線のダブルクリックは DiagramCanvas の capture listener が受ける (E2E で確認)
    fireEvent.doubleClick(hit);
    expect(handler.open).not.toHaveBeenCalled();
  });
});