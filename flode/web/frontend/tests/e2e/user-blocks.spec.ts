import { copyFileSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";

import { readPortEnv } from "./ports";

// ADR-0081 U4: ワークスペースの blocks/ に置いた Python のブロックがパレットの
// ワークスペースセクションに出て、Inspector にパラメータの説明と選択肢が出る。
//
// backend は globalSetup より先に起動する (playwright.config.ts) ため、起動時点の
// .workspace/ には今回の fixtures/blocks/ がまだ無いことがある。テストはパレットの
// ⋯ メニューから「再読み込み」して読み込ませる (再読み込みの経路の確認も兼ねる)。
// キャンバスへの描画・実行は U5 / U6 の範囲。
//
// FLODE_E2E_SHOT_DIR を指定するとスクリーンショットをそこに保存する (CI では不要)。

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WORKSPACE = path.join(__dirname, ".workspace");
// 他の spec が使う minimal_model.flw.json を汚さないよう、複製したモデルで操作する
const MODEL_FILENAME = "user_blocks_model.flw.json";
const SCALER_TYPE = "flode_ws.e2e_blocks.E2eScaler";
const OFFSET_TYPE = "flode_ws.e2e_blocks.E2eOffset";
const SHOT_DIR = process.env.FLODE_E2E_SHOT_DIR ?? "";
const BROKEN_FILE = path.join(WORKSPACE, "blocks", "e2e_broken.py");
const BACKEND_URL = `http://127.0.0.1:${readPortEnv("E2E_BACKEND_PORT", 8770)}`;

/** FLODE_E2E_SHOT_DIR が指定されていればスクリーンショットを保存する。 */
async function shot(page: Page, name: string, locator?: ReturnType<Page["locator"]>): Promise<void> {
  if (SHOT_DIR === "") return;
  mkdirSync(SHOT_DIR, { recursive: true });
  const file = path.join(SHOT_DIR, name);
  if (locator !== undefined) await locator.screenshot({ path: file });
  else await page.screenshot({ path: file });
}

test.describe("User blocks in the palette (ADR-0081 U4)", () => {
  test.beforeAll(() => {
    copyFileSync(
      path.join(WORKSPACE, "minimal_model.flw.json"),
      path.join(WORKSPACE, MODEL_FILENAME),
    );
  });

  test.afterAll(async ({ playwright }) => {
    rmSync(path.join(WORKSPACE, MODEL_FILENAME), { force: true });
    rmSync(BROKEN_FILE, { force: true });
    // 後続の spec に読み込みエラーを残さない (壊れたファイルを消して読み込み直す)
    const api = await playwright.request.newContext({ baseURL: BACKEND_URL });
    await api.post("/api/v1/blocks/reload", { data: {} });
    await api.dispose();
  });

  test("workspace section lists the blocks and the Inspector shows descriptions and choices", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 860 });
    await page.goto("/");
    await page.getByText(MODEL_FILENAME).click({ timeout: 15_000 });

    // 左ペインをパレットに切り替える
    const libraryTab = page.getByTestId("activity-bar-library");
    if ((await libraryTab.getAttribute("aria-selected")) !== "true") {
      await libraryTab.click();
    }

    // ⋯ メニュー → 再読み込み (成功トーストが出る)
    await page.getByTestId("palette-menu-button").click();
    await page.getByTestId("palette-menu-reload").click();
    await expect(page.getByText(/Blocks reloaded|ブロックを再読み込みしました/)).toBeVisible({
      timeout: 15_000,
    });

    // ワークスペースセクション: 組み込みより上、カテゴリはサブ見出し、未宣言は直下
    const section = page.locator(
      "[data-testid='palette-user-section'][data-source-id='workspace']",
    );
    await expect(section).toBeVisible();
    await expect(section.locator(`[data-type-path='${SCALER_TYPE}']`)).toBeVisible();
    await expect(section.locator(`[data-type-path='${OFFSET_TYPE}']`)).toBeVisible();
    const subgroup = section.getByTestId("palette-user-subgroup");
    await expect(subgroup).toContainText(/E2E filters/i);
    await expect(subgroup.locator(`[data-type-path='${SCALER_TYPE}']`)).toBeVisible();
    await expect(subgroup.locator(`[data-type-path='${OFFSET_TYPE}']`)).toHaveCount(0);
    const firstSectionId = await page
      .getByTestId("palette-user-section")
      .first()
      .getAttribute("data-source-id");
    expect(firstSectionId).toBe("workspace");
    // 見出しのツールチップに読んだファイル
    await expect(section.getByTestId("palette-user-section-header")).toHaveAttribute(
      "title",
      /e2e_blocks\.py/,
    );
    const palette = page.getByTestId("block-palette");
    await shot(page, "palette_workspace_section.png", palette);

    // 読み込みエラー欄を開く (fixture にエラーは無い = 「なし」と読んだファイル一覧)
    const loadErrors = page.getByTestId("palette-load-errors");
    await loadErrors.locator("summary").click();
    await expect(page.getByTestId("palette-load-files")).toContainText("e2e_blocks.py");
    await shot(page, "palette_load_errors_open.png", palette);

    // パレットからキャンバスへドロップして選択する (ユーザーブロック専用の描画は U5)
    await section
      .locator(`[data-type-path='${SCALER_TYPE}']`)
      .dragTo(page.locator(".react-flow__pane"), { targetPosition: { x: 420, y: 320 } });
    const added = page.locator(
      ".react-flow__node:not([data-id='src']):not([data-id='g']):not([data-id='sc'])",
    );
    await expect(added).toHaveCount(1);
    await added.click();

    // Inspector: パラメータの説明と選択肢
    await expect(page.getByTestId("parameter-panel")).toBeVisible();
    await expect(page.getByTestId("block-header-user-summary")).toContainText("E2E Scaler");
    await expect(page.getByTestId("param-desc-k")).toHaveText("Gain applied to the input.");
    await expect(page.getByTestId("param-desc-mode")).toHaveText(
      "How quickly the output follows the input.",
    );
    const mode = page.getByTestId("param-input-mode");
    await expect(mode).toHaveJSProperty("tagName", "SELECT");
    await expect(mode).toHaveValue("fast");
    await expect(mode.locator("option")).toHaveText(["fast", "slow"]);
    await shot(page, "inspector_description_choices.png");

    // 構文エラーのファイルを足して再読み込み → 読み込みエラー欄に件数と行が出る
    writeFileSync(BROKEN_FILE, "def broken(:\n    pass\n", "utf-8");
    await page.getByTestId("palette-reload-button").click();
    const summary = loadErrors.locator("summary");
    await expect(summary).toHaveText(/\(1\)/, { timeout: 15_000 });
    const row = page.getByTestId("palette-load-error-row").first();
    await expect(row).toHaveAttribute("data-severity", "error");
    await expect(row).toContainText("blocks/e2e_broken.py:1");
    await shot(page, "palette_load_errors_with_error.png", palette);
  });
});
