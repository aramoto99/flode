// SPEC-0022 §機能要件 7: Subsystem 外面ポートラベルのテスト。
// 内部 Inport / Outport の id が既定 ({TypeName}_{n}) なら非表示、rename 済なら
// ポート脇に表示 (部分表示可)。Trigger / Enable slot は対象外。flip で左右反転。

import { ReactFlowProvider } from "@xyflow/react";
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BlockNodeView } from "../src/components/BlockNodeView";
import {
  INPORT_TYPE,
  OUTPORT_TYPE,
  SUBSYSTEM_TYPE,
  TRIGGER_TYPE,
} from "../src/lib/blockTypes";
import type { BlockEntry } from "../src/types/api";

vi.mock("../src/store/appStore", () => ({
  useAppStore: (
    selector: (s: {
      scopes: Record<string, never>;
      renameRequest: null;
    }) => unknown,
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

const SUBSYSTEM = SUBSYSTEM_TYPE;
const INPORT = INPORT_TYPE;
const OUTPORT = OUTPORT_TYPE;
const TRIGGER = TRIGGER_TYPE;

function subsystemProps(innerBlocks: BlockEntry[], flipped = false) {
  return {
    id: "Sub_0",
    data: {
      blockType: SUBSYSTEM,
      params: { blocks: innerBlocks, connections: [] },
      nInputs: innerBlocks.filter((b) => b.type === INPORT).length,
      nOutputs: innerBlocks.filter((b) => b.type === OUTPORT).length,
      isContainer: true,
      shapeWidth: 120,
      shapeHeight: 80,
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
}

function renderSubsystem(innerBlocks: BlockEntry[], flipped = false) {
  return render(
    <ReactFlowProvider>
      <BlockNodeView {...subsystemProps(innerBlocks, flipped)} />
    </ReactFlowProvider>,
  );
}

describe("Subsystem 外面ポートラベル (SPEC-0022 Q5、2026-08-25 Q6 撤回)", () => {
  it("既定 id (Inport_0 等) でも常時表示する (Q6 撤回、リファレンスツール同等)", () => {
    const { getByTestId } = renderSubsystem([
      { id: "Inport_0", type: INPORT, params: { port_idx: 0 } },
      { id: "Outport_0", type: OUTPORT, params: { port_idx: 0 } },
    ]);
    expect(getByTestId("subsystem-port-label-in-0").textContent).toBe("Inport_0");
    expect(getByTestId("subsystem-port-label-out-0").textContent).toBe(
      "Outport_0",
    );
  });

  it("既定・rename 済ポートが混在しても全ポート表示、y は handle 等分配式に一致", () => {
    const { getByTestId } = renderSubsystem([
      { id: "Inport_0", type: INPORT, params: { port_idx: 0 } }, // 既定 → 表示
      { id: "速度", type: INPORT, params: { port_idx: 1 } },
      { id: "トルク", type: OUTPORT, params: { port_idx: 0 } },
    ]);
    expect(getByTestId("subsystem-port-label-in-0").textContent).toBe("Inport_0");
    const inLabel = getByTestId("subsystem-port-label-in-1");
    expect(inLabel.textContent).toBe("速度");
    expect(inLabel.title).toBe("速度");
    // nDataIn=2 → top = ((1+1)*100)/(2+1)%
    expect(inLabel.style.top).toBe(`${(2 * 100) / 3}%`);
    expect(inLabel.style.left).toBe("4px");
    const outLabel = getByTestId("subsystem-port-label-out-0");
    expect(outLabel.textContent).toBe("トルク");
    // nOut=1 → top = ((0+1)*100)/(1+1)% = 50%
    expect(outLabel.style.top).toBe("50%");
    expect(outLabel.style.right).toBe("4px");
  });

  it("Trigger / Enable slot はラベル対象外で、data ポートの等分配にも影響しない", () => {
    const { getByTestId, container } = renderSubsystem([
      { id: "速度", type: INPORT, params: { port_idx: 0 } },
      { id: "MyTrigger", type: TRIGGER, params: {} },
    ]);
    // nDataIn=1 (Trigger は数えない) → top = 50%
    expect(getByTestId("subsystem-port-label-in-0").style.top).toBe("50%");
    expect(
      container.querySelectorAll('[data-testid^="subsystem-port-label"]'),
    ).toHaveLength(1);
  });

  it("flipped で入力ラベルが右寄せ・出力ラベルが左寄せに入れ替わる", () => {
    const { getByTestId } = renderSubsystem(
      [
        { id: "速度", type: INPORT, params: { port_idx: 0 } },
        { id: "トルク", type: OUTPORT, params: { port_idx: 0 } },
      ],
      true,
    );
    expect(getByTestId("subsystem-port-label-in-0").style.right).toBe("4px");
    expect(getByTestId("subsystem-port-label-out-0").style.left).toBe("4px");
  });

  it("ラベルは truncate + max-width で幅を自動拡張しない (Q5)", () => {
    const longName = "とても長いポート名でブロック幅を超える";
    const { getByTestId } = renderSubsystem([
      { id: longName, type: INPORT, params: { port_idx: 0 } },
    ]);
    const label = getByTestId("subsystem-port-label-in-0");
    expect(label.className).toMatch(/truncate/);
    expect(label.style.maxWidth).toBe("45%");
    expect(label.title).toBe(longName);
  });
});
