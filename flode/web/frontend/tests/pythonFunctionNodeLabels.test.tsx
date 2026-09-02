// SPEC-0024 / ADR-0074 §論点 6: PythonFunction ノードのポート名ラベル描画。
// - introspect 結果 (cache) から描く、無名 (空文字) は非表示
// - y は handle 等分配式、flip で左右反転
// - ラベルがあるときだけ glyph を w-[36%] に縮める (30+36+30 ≤ 100 の幾何不変式)
// - Subsystem の既存 testid (subsystem-port-label-*) は不変 (回帰は subsystemPortLabels.test.tsx)

import { ReactFlowProvider } from "@xyflow/react";
import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BlockNodeView } from "../src/components/BlockNodeView";
import { PYTHON_FUNCTION_TYPE } from "../src/lib/blockTypes";
import {
  _resetPythonSpecCacheForTest,
  putPythonSpec,
} from "../src/lib/pythonFunctionSpec";
import type { PythonFunctionSpec } from "../src/types/api";

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

const CODE = "@block\ndef f(t: float, u: tuple[float, float]) -> float:\n    return u[0]\n";

function spec(over: Partial<PythonFunctionSpec> = {}): PythonFunctionSpec {
  return {
    resolved: true,
    func_name: "f",
    n_inputs: 2,
    n_outputs: 1,
    n_states: 0,
    direct_feedthrough: true,
    sample_time: null,
    params_spec: [],
    input_names: [],
    output_names: [],
    editable: {
      inputs: true,
      outputs: true,
      min_inputs: 1,
      max_inputs: 32,
      min_outputs: 1,
      max_outputs: 32,
    },
    ...over,
  };
}

function renderNode(flipped = false) {
  const props = {
    id: "pf",
    data: {
      blockType: PYTHON_FUNCTION_TYPE,
      params: { code: CODE, user_params: {} },
      nInputs: 2,
      nOutputs: 1,
      isContainer: false,
      shapeWidth: 72,
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
  };
  return render(
    <ReactFlowProvider>
      <BlockNodeView {...props} />
    </ReactFlowProvider>,
  );
}

beforeEach(() => _resetPythonSpecCacheForTest());
afterEach(() => cleanup());

describe("PythonFunction ポート名ラベル (SPEC-0024)", () => {
  it("名前付きポートだけラベル表示、無名 (空文字) は非表示", () => {
    putPythonSpec(CODE, spec({ input_names: ["速度指令", ""], output_names: ["トルク"] }));
    const { getByTestId, queryByTestId } = renderNode();
    expect(getByTestId("pythonfunction-port-label-in-0").textContent).toBe("速度指令");
    expect(queryByTestId("pythonfunction-port-label-in-1")).toBeNull();
    expect(getByTestId("pythonfunction-port-label-out-0").textContent).toBe("トルク");
  });

  it("y は handle 等分配式 (((i+1)*100)/(n+1))、maxWidth 30%", () => {
    putPythonSpec(CODE, spec({ input_names: ["a", "b"] }));
    const { getByTestId } = renderNode();
    const in0 = getByTestId("pythonfunction-port-label-in-0");
    const in1 = getByTestId("pythonfunction-port-label-in-1");
    expect(in0.style.top).toBe(`${(1 * 100) / 3}%`);
    expect(in1.style.top).toBe(`${(2 * 100) / 3}%`);
    expect(in0.style.maxWidth).toBe("30%");
    expect(in0.style.left).toBe("4px");
  });

  it("flip で入力ラベルが右側に移る", () => {
    putPythonSpec(CODE, spec({ input_names: ["a", ""] }));
    const { getByTestId } = renderNode(true);
    const in0 = getByTestId("pythonfunction-port-label-in-0");
    expect(in0.style.right).toBe("4px");
    expect(in0.style.left).toBe("");
  });

  it("ラベルがあるとき glyph は w-[36%]、無いとき従来の w-[80%] (幾何不変式)", () => {
    putPythonSpec(CODE, spec({ input_names: ["a", ""] }));
    const withLabels = renderNode();
    expect(withLabels.container.querySelector(".w-\\[36\\%\\]")).not.toBeNull();
    cleanup();

    _resetPythonSpecCacheForTest();
    putPythonSpec(CODE, spec()); // 名前なし
    const withoutLabels = renderNode();
    expect(withoutLabels.container.querySelector(".w-\\[36\\%\\]")).toBeNull();
    expect(withoutLabels.container.querySelector(".w-\\[80\\%\\]")).not.toBeNull();
    // 30% (ラベル) + 36% (glyph) + 30% (ラベル) = 96% ≤ 100%
    expect(30 + 36 + 30).toBeLessThanOrEqual(100);
  });

  it("spec 未解決 (cache miss) ではラベルなし + 従来描画", () => {
    const { container } = renderNode();
    expect(container.querySelector('[data-testid^="pythonfunction-port-label"]')).toBeNull();
    expect(container.querySelector(".w-\\[80\\%\\]")).not.toBeNull();
  });
});
