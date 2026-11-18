import { copyFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";

// 回帰テスト (bug-report 2026-11-19-edges-recreated-every-render):
// キャンバスが再描画されるたびに、配線 (edge) の DOM 要素が消えて作り直されていた。
// DiagramCanvas が ``measured`` を持たない新しい node を毎回 React Flow に渡し、React Flow が
// handle の位置 (handleBounds) を捨てて測り直すまで edge を描かなかったため。
// 再描画を起こす操作 (ノードの選択・ブロックの移動・信号名の付与) のあとも、配線の要素が
// 削除されず同じ要素のまま残ることを確かめる。

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WORKSPACE = path.join(__dirname, ".workspace");
const MODEL_FILENAME = "edges_stable_work.flw.json";
const SLOT_MODEL_FILENAME = "edges_stable_slots.flw.json";
const OTHER_MODEL_FILENAME = "edges_stable_other.flw.json";

/** 配線 (``.react-flow__edge`` を含む要素) の削除を数える MutationObserver を仕掛ける。 */
async function watchEdgeRemovals(page: Page): Promise<void> {
  await page.evaluate(() => {
    const w = window as unknown as { __edgeRemovals: number; __edgeObserver?: MutationObserver };
    w.__edgeRemovals = 0;
    w.__edgeObserver?.disconnect();
    const root = document.querySelector(".react-flow__edges");
    if (root === null) throw new Error("no edges layer");
    const obs = new MutationObserver((records) => {
      for (const r of records) {
        r.removedNodes.forEach((n) => {
          if (
            n instanceof Element &&
            (n.matches(".react-flow__edge") || n.querySelector(".react-flow__edge") !== null)
          ) {
            w.__edgeRemovals += 1;
          }
        });
      }
    });
    obs.observe(root, { childList: true, subtree: true });
    w.__edgeObserver = obs;
  });
}

async function edgeRemovals(page: Page): Promise<number> {
  return page.evaluate(() => (window as unknown as { __edgeRemovals: number }).__edgeRemovals);
}

/** 配線 ``id`` の要素に印を付ける (後で同じ要素が残っているかを見る)。 */
async function markEdge(page: Page, id: string): Promise<void> {
  await page.locator(`.react-flow__edge[data-id='${id}']`).evaluate((el) => {
    el.setAttribute("data-e2e-mark", "kept");
  });
}

type Pt = { x: number; y: number };

/** 配線の当たり判定 path の始点・終点 (画面座標)。 */
async function edgeEnds(page: Page, id: string): Promise<{ start: Pt; end: Pt }> {
  return page
    .locator(`.react-flow__edge[data-id='${id}'] [data-testid='edge-hit-area']`)
    .evaluate((el) => {
      const p = el as SVGPathElement;
      const m = p.getScreenCTM();
      if (m === null) throw new Error("no CTM");
      const at = (len: number): { x: number; y: number } => {
        const q = p.getPointAtLength(len);
        return { x: q.x * m.a + q.y * m.c + m.e, y: q.x * m.b + q.y * m.d + m.f };
      };
      return { start: at(0), end: at(p.getTotalLength()) };
    });
}

/** ノードの handle の中心 (画面座標)。 */
async function handleCenter(
  page: Page,
  nodeId: string,
  kind: "source" | "target",
  handleId: string,
): Promise<Pt> {
  const box = await page
    .locator(`.react-flow__node[data-id='${nodeId}'] .react-flow__handle.${kind}[data-handleid='${handleId}']`)
    .boundingBox();
  if (box === null) throw new Error(`no handle ${nodeId}/${kind}/${handleId}`);
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}


/**
 * 配線 ``edgeId`` の端 (``side``) と handle の中心とのずれ (画面 px)。BranchableEdge は端点を
 * handle 中心から 12 flow px ブロック側へずらすので、x は 20 px まで許し、y は一致を見る。
 * 古い handle 位置が残ると大きくずれる。付いていれば 0、付いていなければずれの大きさ。
 */
async function detachment(
  page: Page,
  edgeId: string,
  side: "start" | "end",
  nodeId: string,
  kind: "source" | "target",
  handleId: string,
): Promise<number> {
  const end = (await edgeEnds(page, edgeId))[side];
  const h = await handleCenter(page, nodeId, kind, handleId);
  const dy = Math.abs(end.y - h.y);
  const dx = Math.abs(end.x - h.x);
  return dy < 2 && dx < 20 ? 0 : dx + dy;
}

/** 配線の端が handle に付くまで待つ (測定・fitView が落ち着いたことの確認も兼ねる)。 */
async function expectAttached(
  page: Page,
  edgeId: string,
  side: "start" | "end",
  nodeId: string,
  kind: "source" | "target",
  handleId: string,
): Promise<void> {
  await expect
    .poll(() => detachment(page, edgeId, side, nodeId, kind, handleId), { timeout: 5_000 })
    .toBe(0);
}

/**
 * ファイル一覧からモデルを開く。``replacing`` なら今のファイルを置き換えるので、未保存の
 * 確認ダイアログ (開いたモデルは migration 済みで未保存扱い) で「保存して開く」を押す。
 */
async function openModel(page: Page, filename: string, replacing = false): Promise<void> {
  const fileTab = page.getByTestId("activity-bar-file");
  await expect(fileTab).toBeVisible({ timeout: 15_000 });
  if ((await fileTab.getAttribute("aria-selected")) !== "true") await fileTab.click();
  await page.getByRole("button", { name: filename, exact: true }).click({ timeout: 15_000 });
  if (replacing) {
    await page.getByRole("button", { name: /^(Save & Open|保存して開く)$/ }).click();
  }
}

/** Subsystem ``sub`` (Inport i0, i1 + Enable en) に 3 本入る (データ 2 本 + enable 1 本) モデル。 */
function slotModel(): Record<string, unknown> {
  return {
    schema_version: "0.15",
    metadata: { tool: "flode e2e (edges re-measured on control slot change)" },
    simulator: { t_end: 0.1, dt: 0.01, solver: "RK45", rtol: 1e-6, atol: 1e-9, dt_base: null },
    blocks: [
      { id: "c", type: "flode.blocks.sources.Constant", params: { value: 1.0 } },
      { id: "d", type: "flode.blocks.sources.Constant", params: { value: 2.0 } },
      { id: "p", type: "flode.blocks.sources.Constant", params: { value: 1.0 } },
      {
        id: "sub",
        type: "flode.subsystems.subsystem.Subsystem",
        params: {
          blocks: [
            { id: "i0", type: "flode.subsystems.ports.Inport", params: { port_idx: 0 } },
            { id: "i1", type: "flode.subsystems.ports.Inport", params: { port_idx: 1 } },
            { id: "en", type: "flode.subsystems.control_blocks.Enable", params: {} },
            { id: "o", type: "flode.subsystems.ports.Outport", params: { port_idx: 0 } },
          ],
          connections: [{ src: "i0", src_idx: 0, dst: "o", dst_idx: 0 }],
          layout: {
            i0: { x: 60, y: 60 },
            i1: { x: 60, y: 160 },
            en: { x: 260, y: 20 },
            o: { x: 400, y: 60 },
          },
        },
      },
      { id: "term", type: "flode.blocks.sinks.Terminator", params: { n_inputs: 1 } },
    ],
    connections: [
      { src: "c", src_idx: 0, dst: "sub", dst_idx: 0 },
      { src: "d", src_idx: 0, dst: "sub", dst_idx: 1 },
      { src: "p", src_idx: 0, dst: "sub", dst_idx: 2 },
      { src: "sub", src_idx: 0, dst: "term", dst_idx: 0 },
    ],
    layout: {
      c: { x: 60, y: 60 },
      d: { x: 60, y: 160 },
      p: { x: 220, y: -60 },
      sub: { x: 260, y: 80 },
      term: { x: 480, y: 100 },
    },
  };
}

/** minimal_model と同じ id ``g`` を、形の違うブロック (Mux、入力 3) にしたモデル。 */
function otherShapeModel(): Record<string, unknown> {
  return {
    schema_version: "0.15",
    metadata: { tool: "flode e2e (same id, other shape)" },
    simulator: { t_end: 0.1, dt: 0.01, solver: "RK45", rtol: 1e-6, atol: 1e-9, dt_base: null },
    blocks: [
      { id: "src", type: "flode.blocks.sources.Constant", params: { value: 1.0 } },
      { id: "g", type: "flode.blocks.routing.Mux", params: { n: 3 } },
      { id: "sc", type: "flode.blocks.sinks.Scope", params: { n_inputs: 1 } },
    ],
    connections: [
      { src: "src", src_idx: 0, dst: "g", dst_idx: 2 },
      { src: "g", src_idx: 0, dst: "sc", dst_idx: 0 },
    ],
    layout: { src: { x: 100, y: 160 }, g: { x: 240, y: 100 }, sc: { x: 380, y: 100 } },
  };
}

test.describe("Edges are not recreated on every canvas render", () => {
  test.beforeAll(() => {
    copyFileSync(path.join(WORKSPACE, "minimal_model.flw.json"), path.join(WORKSPACE, MODEL_FILENAME));
    writeFileSync(path.join(WORKSPACE, SLOT_MODEL_FILENAME), JSON.stringify(slotModel(), null, 2));
    writeFileSync(path.join(WORKSPACE, OTHER_MODEL_FILENAME), JSON.stringify(otherShapeModel(), null, 2));
  });

  test.afterAll(() => {
    for (const f of [MODEL_FILENAME, SLOT_MODEL_FILENAME, OTHER_MODEL_FILENAME]) {
      rmSync(path.join(WORKSPACE, f), { force: true });
    }
  });

  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 860 });
    await page.goto("/");
  });

  test("selecting, moving a block and naming a wire keep the edge elements", async ({ page }) => {
    await openModel(page, MODEL_FILENAME);
    await expect(page.locator(".react-flow__edge")).toHaveCount(2, { timeout: 15_000 });
    // 開いた直後の測定が終わってから (配線が handle に付いてから) の変化だけを数える
    await expectAttached(page, "e1-g-sc", "end", "sc", "target", "0");
    await markEdge(page, "e0-src-g");
    await markEdge(page, "e1-g-sc");
    await watchEdgeRemovals(page);

    // 1. ノードの選択 (DiagramCanvas が再描画される)
    const sc = page.locator(".react-flow__node[data-id='sc']");
    await sc.click();
    await expect(sc).toHaveClass(/selected/);
    expect(await edgeRemovals(page)).toBe(0);

    // 2. 無関係なブロック (sc) を少し動かす: src → g の配線はそのまま
    // (1 px ではドラッグの閾値を越えず位置が変わらないことがあるので 10 px)
    const box = await sc.boundingBox();
    if (box === null) throw new Error("no sc box");
    const beforeTransform = await sc.evaluate((el) => (el as HTMLElement).style.transform);
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 10, box.y + box.height / 2, { steps: 5 });
    await page.mouse.up();
    await expect
      .poll(() => sc.evaluate((el) => (el as HTMLElement).style.transform))
      .not.toBe(beforeTransform);
    await expect(page.locator(".react-flow__edge[data-id='e0-src-g']")).toHaveAttribute(
      "data-e2e-mark",
      "kept",
    );

    // 3. 信号名を付ける (src → g の配線をダブルクリック → 入力 → Enter)
    const hit = page.locator(".react-flow__edge[data-id='e0-src-g'] [data-testid='edge-hit-area']");
    const pt = await hit.evaluate((el) => {
      const p = el as SVGPathElement;
      const q = p.getPointAtLength(p.getTotalLength() / 2);
      const m = p.getScreenCTM();
      if (m === null) throw new Error("no CTM");
      return { x: q.x * m.a + q.y * m.c + m.e, y: q.x * m.b + q.y * m.d + m.f };
    });
    await page.mouse.dblclick(pt.x, pt.y);
    const input = page.getByTestId("signal-name-input");
    await expect(input).toBeVisible();
    await input.fill("stable");
    await input.press("Enter");
    await expect(page.getByTestId("signal-name-label")).toHaveText("stable");

    // どの操作でも配線の要素は削除されず、印を付けた要素が残っている
    expect(await edgeRemovals(page)).toBe(0);
    await expect(page.locator(".react-flow__edge[data-e2e-mark='kept']")).toHaveCount(2);
  });

  test("handle positions are re-measured when a block flips or its port count changes", async ({
    page,
  }) => {
    await openModel(page, MODEL_FILENAME);
    await expectAttached(page, "e1-g-sc", "start", "g", "source", "0");

    // 反転: g の出力 (e1 の始点) は左辺へ、入力 (e0 の終点) は右辺へ移る
    const before = await edgeEnds(page, "e1-g-sc");
    await page.locator(".react-flow__node[data-id='g']").click();
    await page.getByTestId("flip-block-button").click();
    await expect
      .poll(async () => (await edgeEnds(page, "e1-g-sc")).start.x, { timeout: 5_000 })
      .toBeLessThan(before.start.x - 20);
    await expectAttached(page, "e1-g-sc", "start", "g", "source", "0");
    await expectAttached(page, "e0-src-g", "end", "g", "target", "0");

    // ポート数の変化: Scope の入力を 3 にすると、入力 0 の handle は上へ移る
    await page.locator(".react-flow__node[data-id='sc']").click();
    const nInputs = page.getByTestId("param-input-n_inputs");
    await nInputs.fill("3");
    await nInputs.press("Enter");
    await expect(page.locator(".react-flow__node[data-id='sc'] .react-flow__handle.target")).toHaveCount(3);
    await expectAttached(page, "e1-g-sc", "end", "sc", "target", "0");
  });

  test("Subsystem control slot change (Enable removed, Inport added) re-measures handles", async ({
    page,
  }) => {
    await openModel(page, SLOT_MODEL_FILENAME);
    const sub = page.locator(".react-flow__node[data-id='sub']");
    await expect(sub.locator(".react-flow__handle.target")).toHaveCount(3, { timeout: 15_000 });
    // 最初は enable が上辺 (dst_idx 2)、データ 2 本が左辺
    await expectAttached(page, "e2-p-sub", "end", "sub", "target", "2");

    // 中に入って Enable を消し、Inport を 1 つ足す (入力は Inport 3 本、上辺のスロットは無くなる)
    await sub.dblclick();
    await expect(page.locator(".react-flow__node[data-id='en']")).toBeVisible({ timeout: 10_000 });
    await page.locator(".react-flow__node[data-id='en']").click();
    await page.keyboard.press("Delete");
    await expect(page.locator(".react-flow__node[data-id='en']")).toHaveCount(0);
    const libraryTab = page.getByTestId("activity-bar-library");
    if ((await libraryTab.getAttribute("aria-selected")) !== "true") await libraryTab.click();
    await page
      .locator("[data-type-path='flode.subsystems.ports.Inport']")
      .first()
      .dragTo(page.locator(".react-flow__pane"), { targetPosition: { x: 200, y: 360 } });
    await expect(page.locator(".react-flow__node")).toHaveCount(4);
    await page.getByRole("button", { name: /^(Top|トップ)$/ }).click();

    // 戻ると 3 本とも左辺 (データ入力) の handle に付いている
    await expect(sub.locator(".react-flow__handle.target")).toHaveCount(3);
    await expectAttached(page, "e0-c-sub", "end", "sub", "target", "0");
    await expectAttached(page, "e1-d-sub", "end", "sub", "target", "1");
    await expectAttached(page, "e2-p-sub", "end", "sub", "target", "2");
    const h2 = await handleCenter(page, "sub", "target", "2");
    const subBox = await sub.boundingBox();
    if (subBox === null) throw new Error("no sub box");
    // 入力 2 はもう上辺ではない (左辺 = ブロックの左端付近)
    expect(Math.abs(h2.x - subBox.x)).toBeLessThan(20);
  });

  test("switching files with the same block id but a different shape keeps edges attached", async ({
    page,
  }) => {
    await openModel(page, MODEL_FILENAME);
    await expectAttached(page, "e0-src-g", "end", "g", "target", "0");
    await openModel(page, OTHER_MODEL_FILENAME, true);
    await expect(page.locator(".react-flow__node[data-id='g'] .react-flow__handle.target")).toHaveCount(3, {
      timeout: 15_000,
    });
    await expectAttached(page, "e0-src-g", "end", "g", "target", "2");
    await expectAttached(page, "e1-g-sc", "start", "g", "source", "0");

    // 元のモデルへ戻る (今のモデルは schema 0.15 で未保存の変更が無いので、確認は出ない)
    await openModel(page, MODEL_FILENAME);
    await expect(page.locator(".react-flow__node[data-id='g'] .react-flow__handle.target")).toHaveCount(1);
    await expectAttached(page, "e0-src-g", "end", "g", "target", "0");
    await expectAttached(page, "e1-g-sc", "start", "g", "source", "0");
  });
});
