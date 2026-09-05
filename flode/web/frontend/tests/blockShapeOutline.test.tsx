// v0.46.2 (ADR-0070 ④): Inport / Outport = 角丸カプセル、五角形タグの輪郭 SVG が
// canvas に描かれることを検証する。
// v0.53.4 (ユーザー指摘): Goto/From の形状割当が逆だったため入替 —
// Goto = 右辺尖りの矢印頭 / From = 左辺凹みのリボン尾。
// あわせて Inport のポート番号表示が shape 変更後も残ることを確認する。

import { ReactFlowProvider } from "@xyflow/react";
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BlockNodeView } from "../src/components/BlockNodeView";
import { getBlockShape } from "../src/lib/blockShapes";
import { INPORT_TYPE, OUTPORT_TYPE } from "../src/lib/blockTypes";

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

function renderBlock(typePath: string, params: Record<string, unknown>) {
  const shape = getBlockShape(typePath);
  return render(
    <ReactFlowProvider>
      <BlockNodeView
        id="b1"
        data={{
          blockType: typePath,
          params,
          nInputs: 1,
          nOutputs: 1,
          isContainer: false,
          shapeWidth: shape.width,
          shapeHeight: shape.height,
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

/** points 属性を数値ペア配列に分解する。 */
function polygonPoints(el: Element): Array<[number, number]> {
  return (el.getAttribute("points") ?? "")
    .trim()
    .split(/\s+/)
    .map((p) => p.split(",").map(Number) as [number, number]);
}

describe("ブロック輪郭 (v0.46.2 de facto 形状)", () => {
  it("Inport はカプセル (rx = 高さ/2 の rect) + ポート番号", () => {
    const { container, getByText } = renderBlock(INPORT_TYPE, { port_idx: 2 });
    const rect = container.querySelector("svg rect");
    expect(rect).not.toBeNull();
    const { height } = getBlockShape(INPORT_TYPE);
    expect(Number(rect!.getAttribute("rx"))).toBe((height - 2) / 2);
    expect(container.querySelector("svg polygon")).toBeNull();
    expect(getByText("3")).toBeTruthy(); // port_idx + 1
  });

  it("Outport もカプセルでポート番号を表示", () => {
    const { container, getByText } = renderBlock(OUTPORT_TYPE, { port_idx: 0 });
    expect(container.querySelector("svg rect[rx]")).not.toBeNull();
    expect(getByText("1")).toBeTruthy();
  });

  it("Goto は右辺が尖る五角形 (頂点が右辺中央 = 矢印頭)", () => {
    const { container, getByTestId } = renderBlock("flode.blocks.routing.Goto", {
      tag: "A",
    });
    const poly = container.querySelector("svg polygon");
    expect(poly).not.toBeNull();
    const pts = polygonPoints(poly!);
    expect(pts).toHaveLength(5);
    const { width, height } = getBlockShape("flode.blocks.routing.Goto");
    const tip = pts[2]!;
    expect(tip[0]).toBe(width - 1);
    expect(tip[1]).toBe(height / 2);
    // 左辺 (入力配線側) は垂直 (凹まない)
    expect(pts[0]![0]).toBe(1);
    expect(pts[4]![0]).toBe(1);
    expect(getByTestId("goto-label").textContent).toBe("[A]");
  });

  it("From は左辺が凹む五角形 (凹み頂点が左辺中央より内側 = リボン尾)", () => {
    const { container, getByTestId } = renderBlock("flode.blocks.routing.From", {
      tag: "A",
    });
    const poly = container.querySelector("svg polygon");
    expect(poly).not.toBeNull();
    const pts = polygonPoints(poly!);
    expect(pts).toHaveLength(5);
    const { width, height } = getBlockShape("flode.blocks.routing.From");
    const notch = pts[4]!;
    expect(notch[0]).toBeGreaterThan(1); // 左辺 (x=1) より内側
    expect(notch[0]).toBeLessThan(width / 2);
    expect(notch[1]).toBe(height / 2);
    // 右辺 (出力配線側) は垂直 (尖らない)
    expect(pts[1]![0]).toBe(width - 1);
    expect(pts[2]![0]).toBe(width - 1);
    expect(getByTestId("from-label").textContent).toBe(">A>");
  });
});
