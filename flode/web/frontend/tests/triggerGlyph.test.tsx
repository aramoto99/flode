// v0.47.0: Trigger glyph をエッジ記号に変更 (ADR-0070 ④ de facto)。
// canvas では trigger_type に応じて rising / falling / either / function-call を
// 描き分け、palette glyph と Subsystem 上辺 indicator は rising のエッジ記号。

import { ReactFlowProvider } from "@xyflow/react";
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BlockNodeView } from "../src/components/BlockNodeView";
import { BlockGlyph, TriggerIndicatorGlyph } from "../src/lib/blockGlyphs";
import { TRIGGER_TYPE } from "../src/lib/blockTypes";

vi.mock("../src/store/appStore", () => ({
  useAppStore: (
    selector: (s: { scopes: Record<string, never>; renameRequest: null }) => unknown,
  ) => selector({ scopes: {}, renameRequest: null }),
  updateBlockSize: vi.fn(),
  renameBlockInEditing: vi.fn(() => null),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

afterEach(() => {
  cleanup();
});

function renderTrigger(params: Record<string, unknown>) {
  return render(
    <ReactFlowProvider>
      <BlockNodeView
        id="t1"
        data={{
          blockType: TRIGGER_TYPE,
          params,
          nInputs: 1,
          nOutputs: 0,
          isContainer: false,
          shapeWidth: 72,
          shapeHeight: 40,
          connectedInputs: [],
          connectedOutputs: [],
          flipped: false,
        }}
        selected={false}
        type="blockNode"
        zIndex={0}
        isConnectable
        positionAbsoluteX={0}
        positionAbsoluteY={0}
        dragging={false}
        draggable
        selectable
        deletable
      />
    </ReactFlowProvider>,
  );
}

/** glyph 内の polyline points 一覧。 */
function polylines(el: Element): string[] {
  return Array.from(el.querySelectorAll("polyline")).map(
    (p) => p.getAttribute("points") ?? "",
  );
}

describe("Trigger エッジ記号 (v0.47.0)", () => {
  it("rising (既定): 低→高ステップ + 上向き矢印頭", () => {
    const { getByTestId } = renderTrigger({ trigger_type: "rising" });
    const pts = polylines(getByTestId("trigger-glyph-rising"));
    expect(pts).toContain("3,17 10,17 10,7 21,7");
    expect(pts).toContain("7,10 10,7 13,10");
    expect(pts).not.toContain("7,14 10,17 13,14");
  });

  it("falling: 高→低ステップ + 下向き矢印頭", () => {
    const { getByTestId } = renderTrigger({ trigger_type: "falling" });
    const pts = polylines(getByTestId("trigger-glyph-falling"));
    expect(pts).toContain("3,7 10,7 10,17 21,17");
    expect(pts).toContain("7,14 10,17 13,14");
  });

  it("either: 上下両方の矢印頭", () => {
    const { getByTestId } = renderTrigger({ trigger_type: "either" });
    const pts = polylines(getByTestId("trigger-glyph-either"));
    expect(pts).toContain("7,10 10,7 13,10");
    expect(pts).toContain("7,14 10,17 13,14");
  });

  it("function-call: f() テキスト", () => {
    const { getByTestId } = renderTrigger({ trigger_type: "function-call" });
    expect(getByTestId("trigger-glyph-function-call").textContent).toBe("f()");
  });

  it("trigger_type 不明 / 欠落は rising にフォールバック", () => {
    const { getByTestId } = renderTrigger({});
    expect(getByTestId("trigger-glyph-rising")).toBeTruthy();
  });

  it("palette glyph は rising のエッジ記号 (稲妻ではない)", () => {
    const { container } = render(<BlockGlyph typePath={TRIGGER_TYPE} />);
    const pts = polylines(container);
    expect(pts).toContain("3,17 10,17 10,7 21,7");
    expect(pts).not.toContain("14,3 9,12 13,12 10,21"); // 旧稲妻
  });

  it("Subsystem 上辺 indicator も同じエッジ記号", () => {
    const { container } = render(<TriggerIndicatorGlyph />);
    const pts = polylines(container);
    expect(pts).toContain("1,9 5,9 5,3 11,3");
  });
});
