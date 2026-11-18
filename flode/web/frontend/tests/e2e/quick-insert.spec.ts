import { rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";

// 回帰テスト (bug-report 2026-11-19-quick-insert-dblclick-zooms):
// 空き領域のダブルクリックでクイック挿入が開かず、画面が拡大するだけだった。React Flow の
// d3-zoom (dblclick.zoom) が先にイベントを受けて拡大し、伝播を止めるため、wrapper の
// onDoubleClick (クイック挿入) まで届かなかった。
// あわせて、他のダブルクリックの入口 (ブロック・手動分岐点 ●) が今までどおりであることを見る。
// 配線 (信号名)・信号名ラベル・Subsystem へのドリルインは signal-names.spec.ts、
// Scope のパネルは workspace-multipane.spec.ts が確かめる。

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WORKSPACE = path.join(__dirname, ".workspace");
const MODEL_FILENAME = "quick_insert_work.flw.json";

/** src が g1 / g2 に分岐し、分岐点を手動で固定したモデル。 */
function model(): Record<string, unknown> {
  return {
    schema_version: "0.15",
    metadata: { tool: "flode e2e (quick insert)" },
    simulator: { t_end: 0.1, dt: 0.01, solver: "RK45", rtol: 1e-6, atol: 1e-9, dt_base: null },
    blocks: [
      { id: "src", type: "flode.blocks.sources.Constant", params: { value: 1.0 } },
      { id: "g1", type: "flode.blocks.mathops.Gain", params: { k: 2.0 } },
      { id: "g2", type: "flode.blocks.mathops.Gain", params: { k: 3.0 } },
    ],
    connections: [
      { src: "src", src_idx: 0, dst: "g1", dst_idx: 0 },
      { src: "src", src_idx: 0, dst: "g2", dst_idx: 0 },
    ],
    layout: {
      src: { x: 60, y: 100 },
      g1: { x: 300, y: 60 },
      g2: { x: 300, y: 200 },
    },
    branch_waypoints: { "src:0": { axis: "x", pos: 200 } },
  };
}

/** キャンバスの拡大率 (``.react-flow__viewport`` の transform の scale)。 */
async function viewportScale(page: Page): Promise<number> {
  const style = (await page.locator(".react-flow__viewport").getAttribute("style")) ?? "";
  const m = /scale\(([-\d.e]+)\)/.exec(style);
  if (m === null) throw new Error(`no scale in ${style}`);
  return Number(m[1]);
}

/**
 * ダブルクリックの拡大はアニメーションするので、しばらく scale が変わらないことを見る
 * (「起きないこと」の確認なので、一定時間見続けるしかない。拡大のアニメーションより長く見る)。
 */
async function expectScaleStays(page: Page, before: number): Promise<void> {
  for (let i = 0; i < 7; i++) {
    expect(Math.abs((await viewportScale(page)) / before - 1), "the canvas zoomed").toBeLessThan(0.01);
    await page.waitForTimeout(100);
  }
}

const quickAdd = (page: Page) =>
  page.locator("[role='dialog'][aria-label='Quick add block'], [role='dialog'][aria-label='クイック追加']");

test.describe("Quick insert by double-clicking the empty canvas", () => {
  test.beforeAll(() => {
    writeFileSync(path.join(WORKSPACE, MODEL_FILENAME), JSON.stringify(model(), null, 2));
  });

  test.afterAll(() => {
    rmSync(path.join(WORKSPACE, MODEL_FILENAME), { force: true });
  });

  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 860 });
    await page.goto("/");
    await page.getByRole("button", { name: MODEL_FILENAME, exact: true }).click({ timeout: 15_000 });
    await expect(page.locator(".react-flow__edge")).toHaveCount(2, { timeout: 15_000 });
    await expect(page.locator("[data-junction-dot]")).toHaveCount(1);
  });

  test("opens quick insert without zooming and inserts the block where clicked", async ({ page }) => {
    const pane = page.locator(".react-flow__pane");
    const box = await pane.boundingBox();
    if (box === null) throw new Error("no pane");
    // ブロックも配線も無い場所 (右下寄り)
    const click = { x: box.x + box.width - 160, y: box.y + box.height - 120 };
    const before = await viewportScale(page);
    await page.mouse.dblclick(click.x, click.y);

    await expect(quickAdd(page)).toBeVisible();
    await expectScaleStays(page, before);

    // 検索して Enter で挿入 → クリックした位置 (左上) に置かれる
    await quickAdd(page).locator("input").fill("Gain");
    await quickAdd(page).locator("input").press("Enter");
    await expect(quickAdd(page)).toHaveCount(0);
    const added = page.locator(
      ".react-flow__node:not([data-id='src']):not([data-id='g1']):not([data-id='g2'])",
    );
    await expect(added).toHaveCount(1);
    const nodeBox = await added.boundingBox();
    if (nodeBox === null) throw new Error("no added node");
    expect(Math.abs(nodeBox.x - click.x)).toBeLessThan(3);
    expect(Math.abs(nodeBox.y - click.y)).toBeLessThan(3);
  });

  test("double-clicking a manual branch point resets it and does not open quick insert", async ({
    page,
  }) => {
    const dot = page.locator("[data-junction-dot]");
    await expect(dot).toHaveAttribute("data-junction-dot", "manual");
    await dot.dblclick();
    await expect(dot).toHaveAttribute("data-junction-dot", "auto");
    await expect(quickAdd(page)).toHaveCount(0);
  });

  test("double-clicking a block does not open quick insert", async ({ page }) => {
    await page.locator(".react-flow__node[data-id='g1']").dblclick();
    await expect(quickAdd(page)).toHaveCount(0);
  });
});
