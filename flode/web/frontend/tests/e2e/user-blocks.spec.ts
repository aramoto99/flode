import { copyFileSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
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

// ADR-0081 U5: キャンバス上のユーザーブロック。置いて結線したモデルを実行 → .py の引数を
// 消して再読み込み (Inspector に警告、実行時に除去) → .py を消して再読み込み (プレースホルダ、
// 実行前チェックで止まる) → .py を戻して再読み込み (元に戻る)。
// 後始末は U4 と同じ流儀: 足したファイルを消して API で再読み込みする。

const CANVAS_BLOCK_FILE = path.join(WORKSPACE, "blocks", "e2e_canvas.py");
const CANVAS_MODEL_FILENAME = "user_blocks_canvas.flw.json";
const TRIM_TYPE = "flode_ws.e2e_canvas.E2eTrim";

/** ``bias`` 引数を持つ版 (最初の定義)。 */
const TRIM_SOURCE_WITH_BIAS = `from flode import block


@block(display_name="E2E Trim")  # type: ignore[untyped-decorator]
def e2e_trim(t: float, u: float, *, k: float = 2.0, bias: float = 0.0) -> float:
    """Scale and shift the input (E2E fixture)."""
    return k * u + bias
`;

/** ``bias`` 引数を消した版。 */
const TRIM_SOURCE_WITHOUT_BIAS = `from flode import block


@block(display_name="E2E Trim")  # type: ignore[untyped-decorator]
def e2e_trim(t: float, u: float, *, k: float = 2.0) -> float:
    """Scale the input (E2E fixture)."""
    return k * u
`;

/** Constant → E2eTrim → Scope (bias=0.5 を entry に持つ) のモデル。 */
function canvasModel(): Record<string, unknown> {
  return {
    schema_version: "0.15",
    metadata: { tool: "flode e2e (ADR-0081 U5)" },
    simulator: { t_end: 0.1, dt: 0.01, solver: "RK45", rtol: 1e-6, atol: 1e-9, dt_base: null },
    blocks: [
      { id: "src", type: "flode.blocks.sources.Constant", params: { value: 1.0 } },
      { id: "trim", type: TRIM_TYPE, params: { k: 3.0, bias: 0.5 } },
      {
        id: "sc",
        type: "flode.blocks.sinks.Scope",
        params: { n_inputs: 1, labels: ["in0"], buffer_mode: "ring", buffer_capacity: 100000 },
      },
    ],
    connections: [
      { src: "src", src_idx: 0, dst: "trim", dst_idx: 0 },
      { src: "trim", src_idx: 0, dst: "sc", dst_idx: 0 },
    ],
    layout: {
      src: { x: 100, y: 120 },
      trim: { x: 240, y: 112 },
      sc: { x: 420, y: 116 },
    },
  };
}

/**
 * パレットの ⋯ メニューから再読み込みし、frontend の registry の取り直し
 * (GET /api/v1/blocks) が終わるまで待つ (消えた引数の除去は最新の取得結果でだけ行うため)。
 */
async function reloadFromPalette(page: Page): Promise<void> {
  const refetched = page.waitForResponse(
    (r) => r.request().method() === "GET" && /\/api\/v1\/blocks(\?|$)/.test(r.url()),
  );
  await page.getByTestId("palette-menu-button").click();
  await page.getByTestId("palette-menu-reload").click();
  await refetched;
}

/** ツールバーの実行ボタンを押す。 */
async function runSimulation(page: Page): Promise<void> {
  await page
    .locator("button[title^='Run Simulation'], button[title^='シミュレーション実行']")
    .click();
}

test.describe("User blocks on the canvas (ADR-0081 U5)", () => {
  test.beforeAll(() => {
    mkdirSync(path.dirname(CANVAS_BLOCK_FILE), { recursive: true });
    writeFileSync(CANVAS_BLOCK_FILE, TRIM_SOURCE_WITH_BIAS, "utf-8");
    writeFileSync(
      path.join(WORKSPACE, CANVAS_MODEL_FILENAME),
      JSON.stringify(canvasModel(), null, 2),
      "utf-8",
    );
  });

  test.afterAll(async ({ playwright }) => {
    rmSync(CANVAS_BLOCK_FILE, { force: true });
    rmSync(path.join(WORKSPACE, CANVAS_MODEL_FILENAME), { force: true });
    const api = await playwright.request.newContext({ baseURL: BACKEND_URL });
    await api.post("/api/v1/blocks/reload", { data: {} });
    await api.dispose();
  });

  test("run, removed argument, placeholder and recovery", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 860 });
    await page.goto("/");
    await page.getByText(CANVAS_MODEL_FILENAME).click({ timeout: 15_000 });
    const libraryTab = page.getByTestId("activity-bar-library");
    if ((await libraryTab.getAttribute("aria-selected")) !== "true") {
      await libraryTab.click();
    }
    await reloadFromPalette(page);

    // 1. ユーザーブロックが汎用矩形 + 表示名で描かれ、実行できる
    const node = page.locator(".react-flow__node[data-id='trim']");
    const face = node.locator("[data-user-block]");
    await expect(face).toHaveAttribute("data-user-block", "user", { timeout: 15_000 });
    await expect(node.getByTestId("user-block-title")).toHaveText("E2E Trim");
    const status = page.getByTestId("simulation-status");
    await runSimulation(page);
    await expect(status).toHaveAttribute("data-status", "completed", { timeout: 30_000 });
    await shot(page, "u5_user_block_wired.png");

    // 2. .py から bias を消して再読み込み → Inspector に警告、実行できる (除去される)
    writeFileSync(CANVAS_BLOCK_FILE, TRIM_SOURCE_WITHOUT_BIAS, "utf-8");
    await reloadFromPalette(page);
    // 再読み込みの直後、開いているモデルの値が次の保存で消えることを warning トーストで知らせる
    await expect(page.getByText(/Parameters were removed from 1 block/)).toBeVisible({
      timeout: 15_000,
    });
    await expect(node.getByTestId("user-block-removed-params")).toBeVisible();
    await shot(page, "u5_removed_params_toast.png");
    await node.click();
    await expect(page.getByTestId("param-removed-bias")).toBeVisible({ timeout: 15_000 });
    await shot(page, "u5_inspector_removed_argument.png");
    await runSimulation(page);
    await expect(status).toHaveAttribute("data-status", "completed", { timeout: 30_000 });
    // 保存したモデルからも除去されている (k は保持)
    await expect
      .poll(() => {
        const saved = JSON.parse(
          readFileSync(path.join(WORKSPACE, CANVAS_MODEL_FILENAME), "utf-8"),
        ) as { blocks: Array<{ id: string; params: Record<string, unknown> }> };
        return saved.blocks.find((b) => b.id === "trim")?.params;
      })
      .toEqual({ k: 3.0 });
    await expect(page.getByTestId("param-removed-bias")).toHaveCount(0);

    // 3. .py を消して再読み込み → プレースホルダ (配線は保持)、実行前チェックで止まる
    rmSync(CANVAS_BLOCK_FILE, { force: true });
    await reloadFromPalette(page);
    await expect(face).toHaveAttribute("data-user-block", "placeholder", { timeout: 15_000 });
    await expect(node.getByTestId("placeholder-label")).toBeVisible();
    await expect(page.locator(".react-flow__edge")).toHaveCount(2);
    await node.click();
    await expect(page.getByTestId("parameter-panel-placeholder")).toBeVisible();
    await shot(page, "u5_placeholder.png");
    await runSimulation(page);
    await expect(status).toHaveAttribute("data-status", "failed", { timeout: 15_000 });
    await expect(
      page.getByRole("alert").filter({ hasText: "not loaded" }),
    ).toContainText(TRIM_TYPE);
    await shot(page, "u5_placeholder_run_blocked.png");

    // 4. .py を戻して再読み込み → 元に戻り、実行できる
    writeFileSync(CANVAS_BLOCK_FILE, TRIM_SOURCE_WITHOUT_BIAS, "utf-8");
    await reloadFromPalette(page);
    await expect(face).toHaveAttribute("data-user-block", "user", { timeout: 15_000 });
    await runSimulation(page);
    await expect(status).toHaveAttribute("data-status", "completed", { timeout: 30_000 });
  });
});
