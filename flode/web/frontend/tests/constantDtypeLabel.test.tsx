// SPEC-0028 Q9: Constant / Cast の canvas 面表示 (dtype 宣言時)。
// Constant: 生値 + dtype 名 (変換値を frontend で計算しない)。Cast: dtype 名。

import { ReactFlowProvider } from "@xyflow/react";
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BlockNodeView } from "../src/components/BlockNodeView";

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

describe("Constant / Cast canvas face with dtype (SPEC-0028 Q9)", () => {
  it("Constant with dtype shows the raw value and the dtype name", () => {
    const { getByText, getByTestId } = renderBlock(
      "flode.blocks.sources.Constant",
      { value: 1.5, dtype: "int32" },
    );
    // 生値 1.5 を表示 (1 に変換して見せない — 変換の再実装をしない)
    expect(getByText("1.5")).toBeTruthy();
    expect(getByTestId("constant-dtype-label").textContent).toBe("int32");
  });

  it("Constant without dtype (auto) shows the raw value only", () => {
    const { getByText, queryByTestId } = renderBlock(
      "flode.blocks.sources.Constant",
      { value: 2.7 },
    );
    expect(getByText("2.7")).toBeTruthy(); // 生値のまま (変換の再実装をしない)
    expect(queryByTestId("constant-dtype-label")).toBeNull();
  });

  it("Cast with dtype shows the dtype name", () => {
    const { getByText } = renderBlock("flode.blocks.cast.Cast", {
      dtype: "uint8",
    });
    expect(getByText("uint8")).toBeTruthy();
  });
});
