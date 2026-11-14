// ポート chevron (`>` / `<`) がブロック枠に接して描かれること。
//
// 回帰: 以前は chevron 中心を Handle 中心 (= ブロック境界) から 6px 外へ押し出して
// いたため、入力側で約 2px、出力側で約 5px の隙間が枠との間に空いていた。
//
// jsdom はレイアウト計測できないので、chevron span の inline transform から
// 「枠に最も近い端」の x 座標を幾何計算して検証する。
//   - chevron 要素は Handle (24px) の left:50% = ブロック境界に左端を置いた 6×6 の箱
//   - translate(Xpx, -50%) 後に rotate するので、箱の中心 = 境界 + X + 3
//   - 先端 (rotate 後の角) は中心から 6/√2 ≈ 4.24px、付け根側 (線幅ぶん) は約 1.24px

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

const CHEVRON_SIZE = 6;
const TIP_REACH = CHEVRON_SIZE / Math.SQRT2; // 中心 → 先端
const ARM_REACH = 1.75 / Math.SQRT2; // 中心 → 付け根側の線の外縁
/** ブロック境界と chevron の枠側の端の間に許す最大の隙間 (px)。 */
const MAX_GAP_PX = 1;

function renderNode(flipped: boolean) {
  return render(
    <ReactFlowProvider>
      <BlockNodeView
        id="g1"
        data={{
          blockType: "flode.blocks.mathops.Sum",
          params: {},
          color: "#475569",
          nInputs: 1,
          nOutputs: 1,
          isContainer: false,
          shapeWidth: 80,
          shapeHeight: 40,
          connectedInputs: [],
          connectedOutputs: [],
          flipped,
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

/** Handle 内の chevron span の箱中心を「ブロック境界から外向きの距離 (px)」で返す。 */
function outwardCenter(handle: Element): number {
  const span = handle.querySelector("span") as HTMLElement | null;
  expect(span).not.toBeNull();
  const m = /translate\((-?[\d.]+)(px|%),/.exec(span!.style.transform);
  expect(m).not.toBeNull();
  // translate の % は自要素 (6px) 基準
  const tx = m![2] === "%" ? (Number(m![1]) / 100) * CHEVRON_SIZE : Number(m![1]);
  const center = tx + CHEVRON_SIZE / 2; // 境界基準 (右向き正)
  const side = handle.getAttribute("data-handlepos");
  return side === "left" ? -center : center;
}

describe("BlockNodeView port chevron touches the block border", () => {
  it.each([false, true])("flipped=%s", (flipped) => {
    const { container } = renderNode(flipped);
    const target = container.querySelector(".react-flow__handle.target")!;
    const source = container.querySelector(".react-flow__handle.source")!;

    // 入力: 先端が枠を向く → 枠に最も近い端 = 中心 - 先端距離
    const inGap = outwardCenter(target) - TIP_REACH;
    // 出力: 付け根が枠を向く → 枠に最も近い端 = 中心 - 付け根距離
    const outGap = outwardCenter(source) - ARM_REACH;

    for (const gap of [inGap, outGap]) {
      expect(gap).toBeGreaterThanOrEqual(0); // ブロック境界より内側に食い込まない
      expect(gap).toBeLessThanOrEqual(MAX_GAP_PX);
    }
  });
});
