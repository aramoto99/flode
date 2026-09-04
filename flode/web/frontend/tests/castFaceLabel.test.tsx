// SPEC-0026 変更履歴 (3): Cast の canvas 面表示は変換後の型名 (ユーザー要望で
// 固定テキスト `cast` から変更。パレット glyph は `cast` のまま)。

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

describe("Cast の面表示は変換後の型名 (SPEC-0026 変更履歴 (3))", () => {
  it.each(["float", "int", "bool"] as const)("output_type=%s を表示", (ot) => {
    const { container } = renderCast({ output_type: ot });
    expect(container.textContent).toContain(ot);
    expect(container.textContent).not.toContain("cast");
  });

  it("params 欠落 (防御) は既定の float を表示", () => {
    const { container } = renderCast({});
    expect(container.textContent).toContain("float");
  });
});
