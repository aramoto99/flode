// ADR-0054: TriggeredSubsystem の trigger 入力 (= 末尾 slot、ADR-0036 §(2)
// `input_sources[-1]` 固定) を上辺中央に配置し、データ入力 (左辺) と視覚的に
// 区別する render 仕様を verify する。
//
// 検査軸:
//   1. trigger slot Handle の `data-handlepos` が "top" (= Position.Top)
//   2. データ入力 (= i < nIn - 1) は "left" 維持
//   3. flip 時、trigger は上辺維持 (= Top は不変)、データ port のみ "left"→"right"
//   4. 中央に TriggeredSubsystemGlyph (= polyline 雷) が描画される
//   5. trigger glyph (▽) は接続済みでも描画される (= アイデンティティ常時提示)
//   6. 通常データ chevron (>) は接続済み時に従来通り抑制される

import { ReactFlowProvider } from "@xyflow/react";
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BlockNodeView } from "../src/components/BlockNodeView";
import { TRIGGERED_SUBSYSTEM_TYPE } from "../src/lib/blockTypes";

vi.mock("../src/store/appStore", () => ({
  useAppStore: (
    selector: (s: { scopes: Record<string, never> }) => unknown,
  ) => selector({ scopes: {} }),
  updateBlockSize: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

afterEach(() => {
  cleanup();
});

function baseProps(opts: {
  nInputs: number;
  flipped?: boolean;
  connectedInputs?: number[];
}) {
  return {
    id: "ts1",
    data: {
      blockType: TRIGGERED_SUBSYSTEM_TYPE,
      params: { blocks: [], connections: [] },
      color: "#475569",
      nInputs: opts.nInputs,
      nOutputs: 0,
      isContainer: true,
      shapeWidth: 96,
      shapeHeight: 56,
      connectedInputs: opts.connectedInputs ?? [],
      connectedOutputs: [],
      flipped: opts.flipped ?? false,
    },
    selected: false,
    type: "blockNode",
    zIndex: 0,
    isConnectable: true,
    positionAbsoluteX: 0,
    positionAbsoluteY: 0,
    dragging: false,
    draggable: true,
    selectable: true,
    deletable: true,
  };
}

function renderNode(props: ReturnType<typeof baseProps>) {
  return render(
    <ReactFlowProvider>
      <BlockNodeView {...props} />
    </ReactFlowProvider>,
  );
}

describe("BlockNodeView TriggeredSubsystem (ADR-0054)", () => {
  it("trigger slot is placed on the top edge (= last input handle has data-handlepos='top')", () => {
    // nInputs=1 (= 内部 Inport ゼロ、trigger のみ)
    const { container } = renderNode(baseProps({ nInputs: 1 }));
    const targets = container.querySelectorAll(".react-flow__handle.target");
    expect(targets.length).toBe(1);
    expect(targets[0]?.getAttribute("data-handlepos")).toBe("top");
  });

  it("data inputs stay on left and trigger goes to top (nInputs=3 = 2 data + 1 trigger)", () => {
    const { container } = renderNode(baseProps({ nInputs: 3 }));
    const targets = Array.from(
      container.querySelectorAll(".react-flow__handle.target"),
    );
    expect(targets.length).toBe(3);
    // id="0","1" がデータ (左)、id="2" が trigger (上)
    const byId = new Map(targets.map((t) => [t.getAttribute("data-id"), t]));
    // React Flow の `data-id` は完全な handleId ではない (内部 escape) ので、
    // 配列順 (= Array.from の DOM 順 = render 順) に依存する。
    expect(targets[0]?.getAttribute("data-handlepos")).toBe("left");
    expect(targets[1]?.getAttribute("data-handlepos")).toBe("left");
    expect(targets[2]?.getAttribute("data-handlepos")).toBe("top");
    void byId; // type guard for unused warning
  });

  it("flipped=true → trigger stays on top, data ports flip left→right", () => {
    const { container } = renderNode(
      baseProps({ nInputs: 3, flipped: true }),
    );
    const targets = Array.from(
      container.querySelectorAll(".react-flow__handle.target"),
    );
    expect(targets.length).toBe(3);
    // データ入力は flip で right に
    expect(targets[0]?.getAttribute("data-handlepos")).toBe("right");
    expect(targets[1]?.getAttribute("data-handlepos")).toBe("right");
    // trigger は上辺維持 (flipPosition で Top/Bottom 不変、ADR-0054 §Decision)
    expect(targets[2]?.getAttribute("data-handlepos")).toBe("top");
  });

  it("renders the lightning glyph (= polyline) in the block center", () => {
    const { container } = renderNode(baseProps({ nInputs: 1 }));
    // TriggeredSubsystemGlyph は SVG > polyline で雷を描く (ADR-0054)。
    // ShapeOutline の rect とは別物 (rect は ShapeOutline に任せた)。
    // data-testid="trigger-center-glyph" の子孫に限定して、他 SVG の polyline
    // (= 将来追加されうる) との偽陽性を避ける (code-reviewer SHOULD-2)。
    const centerContainer = container.querySelector(
      "[data-testid='trigger-center-glyph']",
    );
    expect(centerContainer).not.toBeNull();
    const polyline = centerContainer!.querySelector("svg polyline");
    expect(polyline).not.toBeNull();
  });

  it("trigger glyph is rendered even when the trigger slot is connected", () => {
    // 通常 chevron は接続済時に消えるが、trigger glyph は識別目的で常時表示。
    // 末尾 index (= nInputs - 1) が connected でも Handle 内に <span> が残る。
    const { container } = renderNode(
      baseProps({ nInputs: 2, connectedInputs: [1] }),
    );
    const targets = Array.from(
      container.querySelectorAll(".react-flow__handle.target"),
    );
    // trigger slot (= index 1) は上辺、内部に glyph span がある
    const triggerHandle = targets[1]!;
    expect(triggerHandle.getAttribute("data-handlepos")).toBe("top");
    expect(triggerHandle.querySelector("span")).not.toBeNull();
  });

  it("data input chevron IS suppressed when connected (= 既存挙動継承、回帰防止)", () => {
    const { container } = renderNode(
      baseProps({ nInputs: 2, connectedInputs: [0] }),
    );
    const targets = Array.from(
      container.querySelectorAll(".react-flow__handle.target"),
    );
    const dataHandle = targets[0]!;
    expect(dataHandle.getAttribute("data-handlepos")).toBe("left");
    expect(dataHandle.querySelector("span")).toBeNull();
  });
});
