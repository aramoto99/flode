// SPEC-0026 §確定事項 7: Constant の canvas 表示は**実効値** (output_type 適用後)。
// 偶数丸め (backend np.round と一致、JS Math.round とは違う) も含めて固定する。

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

const CONSTANT = "flode.blocks.sources.Constant";

function renderConstant(params: Record<string, unknown>) {
  const shape = getBlockShape(CONSTANT);
  return render(
    <ReactFlowProvider>
      <BlockNodeView
        id="b1"
        data={{
          blockType: CONSTANT,
          params,
          nInputs: 0,
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

describe("Constant の実効値表示 (SPEC-0026)", () => {
  it("output_type なし (旧モデル) は生値をそのまま表示", () => {
    const { container } = renderConstant({ value: 1.5 });
    expect(container.textContent).toContain("1.5");
  });

  it("int は偶数丸めの実効値 (2.5 → 2、Math.round の 3 ではない)", () => {
    const { container } = renderConstant({ value: 2.5, output_type: "int" });
    expect(container.textContent).toContain("2");
    expect(container.textContent).not.toContain("2.5");
    expect(container.textContent).not.toContain("3");
  });

  it("bool は 0/1 の実効値 (0.4 → 1)", () => {
    const { container } = renderConstant({ value: 0.4, output_type: "bool" });
    expect(container.textContent).toContain("1");
    expect(container.textContent).not.toContain("0.4");
  });

  it("float は恒等 (生値のまま)", () => {
    const { container } = renderConstant({ value: -3.25, output_type: "float" });
    expect(container.textContent).toContain("-3.25");
  });
});
