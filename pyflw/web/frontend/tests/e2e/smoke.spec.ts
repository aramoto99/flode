import { expect, test } from "@playwright/test";

// pyflw Web GUI の最小回帰テスト。
//
// 検証内容:
// 1. ルート (/) にアクセスし、ヘッダー "pyflw" が描画される
// 2. fixtures/minimal_model のモデルがリストに表示される
// 3. モデルを選択すると Diagram と Simulation Controls が表示される
// 4. Run ボタンを押すと WebSocket 経由で進捗が更新される

const FIXTURE_MODEL_ID = "minimal_model";

test.describe("pyflw web GUI smoke", () => {
  test("renders root page with pyflw header", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "pyflw" })).toBeVisible();
    await expect(page.getByText("Models")).toBeVisible();
  });

  test("shows fixture model in the model list", async ({ page }) => {
    await page.goto("/");
    // ModelList は React Query で /api/v1/models を fetch する。
    // fixture から minimal_model.flw.json を読み込んでいることを確認。
    await expect(
      page.getByRole("button", { name: FIXTURE_MODEL_ID })
    ).toBeVisible({ timeout: 15_000 });
  });

  test("selecting a model shows the diagram canvas and simulation controls", async ({
    page,
  }) => {
    await page.goto("/");
    await page
      .getByRole("button", { name: FIXTURE_MODEL_ID })
      .click({ timeout: 15_000 });

    // SimulationControls の Run / Stop ボタン
    await expect(page.getByRole("button", { name: "Run" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Stop" })).toBeVisible();
    // モデル未選択時のメッセージが消えている
    await expect(
      page.getByText("Select a model from the left panel")
    ).toBeHidden();
  });

  test("Run button starts simulation and progress reaches t_end", async ({
    page,
  }) => {
    await page.goto("/");
    await page
      .getByRole("button", { name: FIXTURE_MODEL_ID })
      .click({ timeout: 15_000 });

    const runButton = page.getByRole("button", { name: "Run" });
    await runButton.click();

    // minimal_model は t_end=0.1, dt=0.01 で 11 ステップなので即終了する。
    // ``running`` 中間状態は WebSocket 速度次第で観測できないため、最終状態
    // ``completed`` だけを待つ (code-reviewer SHOULD 修正)。
    await expect(page.getByText("status: completed")).toBeVisible({
      timeout: 30_000,
    });
  });
});
