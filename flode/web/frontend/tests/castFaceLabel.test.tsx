// Cast の canvas 面表示は変換後の型名 (パレット glyph は `cast` のまま)。
// v0.56.0 (output_type 撤去): dtype 名を常時表示 (既定 float64)。

import { ReactFlowProvider } from "@xyflow/react";
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BlockNodeView } from "../src/components/BlockNodeView";
import { getBlockShape } from "../src/lib/blockShapes";

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

const CAST = "flode.blocks.cast.Cast";

function renderCast(params: Record<string, unknown>) {
  const shape = getBlockShape(CAST);
  return render(
    <ReactFlowProvider>
      <BlockNodeView
        id="c1"
        data={{
          blockType: CAST,
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

describe("Cast の面表示は dtype 名 (v0.56.0 output_type 撤去後)", () => {
  it.each(["float64", "int32", "int64", "uint8", "bool"] as const)(
    "dtype=%s を表示",
    (dt) => {
      const { container } = renderCast({ dtype: dt });
      expect(container.textContent).toContain(dt);
      expect(container.textContent).not.toContain("cast");
    },
  );

  it("params 欠落 (防御) は既定の float64 を表示", () => {
    const { container } = renderCast({});
    expect(container.textContent).toContain("float64");
  });
});
