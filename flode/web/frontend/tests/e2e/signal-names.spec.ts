import { copyFileSync, readFileSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";

import { readPortEnv } from "./ports";

// ADR-0087 / SPEC-0038: 信号名。
//
// 1. 配線のダブルクリックで名前の入力欄が出る (画面は拡大しない)。Enter で確定し、配線の脇に出る
// 2. 分岐した配線のどの枝で編集しても同じ名前 (ラベルは 1 つ)
// 3. 空き領域のダブルクリック (クイック挿入) は今までどおり、ラベルのダブルクリックでは出ない
// 4. Subsystem の中で名前を付けても実行できる (backend が構築前に取り除く)
// 5. 自動保存 → 開き直しても名前が残る → 実行すると Scope の凡例に
//    信号名 > 接続元ポート名 (ユーザーブロックの output_names) > 既定名 が出る
// 6. 名前を変えると実行し直さなくても凡例が変わる
//
// ユーザーブロック E2ePair (出力ポート名 alpha / beta) は fixtures/blocks/e2e_blocks.py。
// backend は globalSetup より先に起動するので、パレットの ⋯ メニューから再読み込みして読ませる。

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WORKSPACE = path.join(__dirname, ".workspace");
const FIXTURE = "signal_names_model.flw.json";
const MODEL_FILENAME = "signal_names_work.flw.json";
const MODEL_PATH = path.join(WORKSPACE, MODEL_FILENAME);
const BACKEND_URL = `http://127.0.0.1:${readPortEnv("E2E_BACKEND_PORT", 8770)}`;

/** connections の順に振られる edge id (modelToDiagram の "e{idx}-{src}-{dst}")。 */
const EDGE_G_SC = "e1-g-sc";
const EDGE_SRC_G = "e0-src-g";
const EDGE_SRC_DISP = "e2-src-disp";
const EDGE_SRC_SUB = "e5-src-sub";
const INNER_EDGE_I_K = "e0-i-k";

/**
 * 配線の当たり判定 path 上の点をダブルクリックする。分岐点 ● (当たり判定が配線より上) と
 * 始点のラベルを避けて、終端 (矢印) の少し手前を押す。
 */
async function dblclickEdge(page: Page, edgeId: string): Promise<void> {
  const hit = page.locator(`.react-flow__edge[data-id='${edgeId}'] [data-testid='edge-hit-area']`);
  await expect(hit).toHaveCount(1, { timeout: 15_000 });
  const pt = await hit.evaluate((el) => {
    const p = el as SVGPathElement;
    const len = p.getTotalLength();
    // 接続先のハンドル (境界から 12px はみ出す) と矢印も避ける
    const q = p.getPointAtLength(Math.max(len / 2, len - 30));
    const m = p.getScreenCTM();
    if (m === null) throw new Error("no CTM");
    return { x: q.x * m.a + q.y * m.c + m.e, y: q.x * m.b + q.y * m.d + m.f };
  });
  await page.mouse.dblclick(pt.x, pt.y);
}

/** 入力欄に名前を入れて Enter で確定する。 */
async function typeName(page: Page, name: string): Promise<void> {
  const input = page.getByTestId("signal-name-input");
  await expect(input).toBeVisible();
  await input.fill(name);
  await input.press("Enter");
  await expect(input).toHaveCount(0);
}

function labelOf(page: Page, src: string, srcIdx = 0) {
  return page.locator(
    `[data-testid='signal-name-anchor'][data-src='${src}'][data-src-idx='${srcIdx}']`,
  );
}

/** キャンバスの拡大率 (``.react-flow__viewport`` の transform の scale)。 */
async function viewportScale(page: Page): Promise<number> {
  const style = (await page.locator(".react-flow__viewport").getAttribute("style")) ?? "";
  const m = /scale\(([-\d.e]+)\)/.exec(style);
  if (m === null) throw new Error(`no scale in ${style}`);
  return Number(m[1]);
}

/** 保存されたファイルの信号名 (最上位 / Subsystem sub の中)。 */
function savedNames(): { top: unknown; inner: unknown } {
  const saved = JSON.parse(readFileSync(MODEL_PATH, "utf-8")) as {
    signal_names?: unknown;
    blocks: Array<{ id: string; params: Record<string, unknown> }>;
  };
  return {
    top: saved.signal_names,
    inner: saved.blocks.find((b) => b.id === "sub")?.params.signal_names,
  };
}

async function openModel(page: Page): Promise<void> {
  const fileTab = page.getByTestId("activity-bar-file");
  await expect(fileTab).toBeVisible({ timeout: 15_000 });
  if ((await fileTab.getAttribute("aria-selected")) !== "true") {
    await fileTab.click();
  }
  // ファイル一覧の項目 (再読み込み後はタブ・ステータスバーにも同じ名前が出る)
  await page.getByRole("button", { name: MODEL_FILENAME, exact: true }).click({ timeout: 15_000 });
  await expect(page.locator(".react-flow__node[data-id='sc']")).toBeVisible({ timeout: 15_000 });
}

async function reloadBlocks(page: Page): Promise<void> {
  const libraryTab = page.getByTestId("activity-bar-library");
  if ((await libraryTab.getAttribute("aria-selected")) !== "true") {
    await libraryTab.click();
  }
  const refetched = page.waitForResponse(
    (r) => r.request().method() === "GET" && /\/api\/v1\/blocks(\?|$)/.test(r.url()),
  );
  await page.getByTestId("palette-menu-button").click();
  await page.getByTestId("palette-menu-reload").click();
  await refetched;
}

async function runSimulation(page: Page): Promise<void> {
  await page
    .locator("button[title^='Run Simulation'], button[title^='シミュレーション実行']")
    .click();
  await expect(page.getByTestId("simulation-status")).toHaveAttribute("data-status", "completed", {
    timeout: 30_000,
  });
}

function legendLabels(page: Page) {
  return page.locator("[data-testid='workspace-pane-leaf-scopes-stack'] .u-legend .u-label");
}

test.describe("Signal names (ADR-0087)", () => {
  test.beforeAll(() => {
    copyFileSync(path.join(WORKSPACE, FIXTURE), MODEL_PATH);
  });

  test.afterAll(async ({ playwright }) => {
    rmSync(MODEL_PATH, { force: true });
    const api = await playwright.request.newContext({ baseURL: BACKEND_URL });
    await api.post("/api/v1/blocks/reload", { data: {} });
    await api.dispose();
  });

  test("name wires, keep them across reopen, run with a Subsystem name, legend", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1400, height: 900 });
    await page.goto("/");
    await openModel(page);
    await reloadBlocks(page);
    await expect(
      page.locator(".react-flow__node[data-id='pair'] [data-user-block]"),
    ).toHaveAttribute("data-user-block", "user", { timeout: 15_000 });
    // fitView のアニメーションが落ち着くのを待ってから viewport を記録する
    await page.waitForTimeout(500);

    // 1. 配線のダブルクリック → 入力欄 (画面は拡大しない)。Enter で確定、脇に出る
    const before = await viewportScale(page);
    await dblclickEdge(page, EDGE_G_SC);
    await expect(page.getByTestId("signal-name-input")).toBeVisible();
    // ダブルクリックのズーム (d3-zoom はアニメーションする) が起きていない
    await page.waitForTimeout(600);
    expect(Math.abs((await viewportScale(page)) / before - 1)).toBeLessThan(0.01);
    await typeName(page, "amplified");
    await expect(labelOf(page, "g").getByTestId("signal-name-label")).toHaveText("amplified");
    await expect(labelOf(page, "g").getByTestId("signal-name-label")).toHaveAttribute(
      "title",
      "amplified",
    );

    // 規則違反 (65 文字) は確定せずエラー、Esc で取り消し
    await dblclickEdge(page, EDGE_SRC_G);
    await page.getByTestId("signal-name-input").fill("x".repeat(65));
    await page.getByTestId("signal-name-input").press("Enter");
    await expect(page.getByTestId("signal-name-error")).toBeVisible();
    await page.getByTestId("signal-name-input").press("Escape");
    await expect(page.getByTestId("signal-name-input")).toHaveCount(0);
    await expect(labelOf(page, "src")).toHaveCount(0);

    // 2. 分岐した配線: 別の枝で付けた名前が、どの枝から開いても同じ。ラベルは 1 つ
    await dblclickEdge(page, EDGE_SRC_DISP);
    await typeName(page, "source");
    await expect(labelOf(page, "src")).toHaveCount(1);
    await dblclickEdge(page, EDGE_SRC_SUB);
    await expect(page.getByTestId("signal-name-input")).toHaveValue("source");
    await page.getByTestId("signal-name-input").press("Escape");
    await expect(labelOf(page, "src")).toHaveCount(1);

    // 3. ラベルのダブルクリックでも編集でき、クイック挿入は開かない
    await labelOf(page, "src").getByTestId("signal-name-label").dblclick();
    await expect(page.getByTestId("signal-name-input")).toBeVisible();
    const quickAdd = page.locator("[aria-label='Quick add block'], [aria-label='クイック追加']");
    await expect(quickAdd).toHaveCount(0);
    await page.getByTestId("signal-name-input").press("Escape");
    await expect(page.getByTestId("signal-name-input")).toHaveCount(0);

    // 4. Subsystem の中で名前を付ける (中のスコープの params.signal_names)
    await page.locator(".react-flow__node[data-id='sub']").dblclick();
    await expect(page.locator(".react-flow__node[data-id='k']")).toBeVisible({ timeout: 10_000 });
    await dblclickEdge(page, INNER_EDGE_I_K);
    await typeName(page, "$Kp inner");
    await expect(labelOf(page, "i").getByTestId("signal-name-label")).toHaveText("$Kp inner");
    await page.getByRole("button", { name: /^(Top|トップ)$/ }).click();
    await expect(page.locator(".react-flow__node[data-id='sc']")).toBeVisible();

    // 5. 自動保存される (最上位と Subsystem の中)
    await expect
      .poll(() => savedNames(), { timeout: 15_000 })
      .toEqual({ top: { "g:0": "amplified", "src:0": "source" }, inner: { "i:0": "$Kp inner" } });

    // 開き直しても残る
    await page.reload();
    await openModel(page);
    await expect(labelOf(page, "g").getByTestId("signal-name-label")).toHaveText("amplified");
    await expect(labelOf(page, "src")).toHaveCount(1);

    // 実行できる (Subsystem 内の名前があっても) → 凡例: 信号名 / ポート名
    await runSimulation(page);
    await expect(legendLabels(page)).toHaveText(["amplified", "alpha", "beta"], {
      timeout: 15_000,
    });

    // 6. 名前を変えると実行し直さなくても凡例が変わる
    await dblclickEdge(page, EDGE_G_SC);
    await typeName(page, "doubled");
    await expect(legendLabels(page)).toHaveText(["doubled", "alpha", "beta"]);

    // 名前を消すと既定名に戻る
    await dblclickEdge(page, EDGE_G_SC);
    await typeName(page, "");
    await expect(legendLabels(page)).toHaveText(["sc[0]", "alpha", "beta"]);
    await expect(labelOf(page, "g")).toHaveCount(0);
  });
});
