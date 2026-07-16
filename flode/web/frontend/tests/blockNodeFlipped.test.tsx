// v0.15.0 Flip Block: BlockNodeView が `data.flipped` を受けたとき、
//   - SVG ShapeOutline サブツリーに `transform: scaleX(-1)` (= 三角形 ▶→◀)
//   - Handle の data-handlepos が "left"↔"right" 反転 (= edge anchor 追従)
//   - ShapeContent (テキスト) は反転せず、triangle-r で justify-start → justify-end

import { ReactFlowProvider } from "@xyflow/react";
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BlockNodeView } from "../src/components/BlockNodeView";

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

const baseProps = (flipped: boolean) => ({
  id: "g1",
  data: {
    blockType: "flode.blocks.mathops.Gain",
    params: { k: 2.0 },
    color: "#475569",
    nInputs: 1,
    nOutputs: 1,
    isContainer: false,
    shapeWidth: 80,
    shapeHeight: 40,
    connectedInputs: [],
    connectedOutputs: [],
    flipped,
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
});

function renderNode(flipped: boolean) {
  return render(
    <ReactFlowProvider>
      <BlockNodeView {...baseProps(flipped)} />
    </ReactFlowProvider>,
  );
}

/** SVG (= ShapeOutline) を抱える wrapper div。flip 時は scaleX(-1)。 */
function getSvgWrapper(container: Element): HTMLElement | null {
  const svg = container.querySelector("svg");
  return (svg?.parentElement ?? null) as HTMLElement | null;
}

/** Gain (triangle-r) のテキスト wrapper (justify-start / end)。 */
function getTriangleTextDiv(container: Element): HTMLElement | null {
  const candidates = container.querySelectorAll(
    ".items-center.text-\\[10px\\]",
  );
  return (candidates[0] ?? null) as HTMLElement | null;
}

describe("BlockNodeView Flip Block (v0.15.0)", () => {
  it("flipped=false → no SVG transform, triangle text uses justify-start, target on left", () => {
    const { container } = renderNode(false);

    const svg = getSvgWrapper(container);
    expect(svg!.style.transform === "" || svg!.style.transform === "none").toBe(
      true,
    );

    const text = getTriangleTextDiv(container);
    expect(text!.className).toMatch(/justify-start/);

    const target = container.querySelector(".react-flow__handle.target");
    const source = container.querySelector(".react-flow__handle.source");
    expect(target?.getAttribute("data-handlepos")).toBe("left");
    expect(source?.getAttribute("data-handlepos")).toBe("right");
  });

  it("flipped=true → SVG scaleX(-1), text justify-end, handles flip via data-handlepos", () => {
    const { container } = renderNode(true);

    const svg = getSvgWrapper(container);
    expect(svg!.style.transform).toBe("scaleX(-1)");

    const text = getTriangleTextDiv(container);
    expect(text!.className).toMatch(/justify-end/);

    const target = container.querySelector(".react-flow__handle.target");
    const source = container.querySelector(".react-flow__handle.source");
    expect(target?.getAttribute("data-handlepos")).toBe("right");
    expect(source?.getAttribute("data-handlepos")).toBe("left");
  });

  it("Handles are siblings of (not nested inside) the SVG wrapper — z-order over ShapeContent", () => {
    // 重要: ShapeContent が Handle を覆って drag を吸収しないこと。
    // Handle は外側 wrapper の直接の子 (= ShapeContent と兄弟) であり、
    // code 順で ShapeContent の **後** に来る = z-order 上、ShapeContent より上。
    const { container } = renderNode(false);
    const innerWrapper = container.querySelector(".relative.h-full.w-full");
    expect(innerWrapper).not.toBeNull();
    const handles = innerWrapper!.querySelectorAll(":scope > .react-flow__handle");
    expect(handles.length).toBe(2);
  });

  it("dynamic toggle: rerender flips SVG and handle positions together", () => {
    const { container, rerender } = render(
      <ReactFlowProvider>
        <BlockNodeView {...baseProps(false)} />
      </ReactFlowProvider>,
    );
    expect(getSvgWrapper(container)!.style.transform).not.toBe("scaleX(-1)");
    expect(
      container
        .querySelector(".react-flow__handle.target")
        ?.getAttribute("data-handlepos"),
    ).toBe("left");

    rerender(
      <ReactFlowProvider>
        <BlockNodeView {...baseProps(true)} />
      </ReactFlowProvider>,
    );
    expect(getSvgWrapper(container)!.style.transform).toBe("scaleX(-1)");
    expect(
      container
        .querySelector(".react-flow__handle.target")
        ?.getAttribute("data-handlepos"),
    ).toBe("right");
  });
});
