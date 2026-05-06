import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

// ADR-0012 §(3) ParameterPanel の E2E。
// 数値パラメータを inline 編集して PUT /api/v1/models/{id} で永続化されることを
// 確認する。Phase 2 改善 #4 の機能検証。

const FIXTURE_MODEL_ID = "minimal_model";
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE_PATH = path.join(__dirname, "fixtures", "minimal_model.flw.json");

// テスト実行前に fixture のスナップショットを取り、afterEach で必ず復元する。
// PUT API は JSON フォーマット (`2.0` → `2`、trailing newline) を変えるため、
// バイナリ一致での復元には fs ベースの戻しが必要 (code-reviewer MUST 修正)。
let fixtureSnapshot: string;

test.describe("ParameterPanel", () => {
  test.beforeAll(() => {
    fixtureSnapshot = readFileSync(FIXTURE_PATH, "utf-8");
  });

  test.afterEach(() => {
    // 各テストの成否にかかわらず fixture を元に戻す。fs ベースなので Playwright
    // ブラウザを開く必要はなく確実に冪等。
    writeFileSync(FIXTURE_PATH, fixtureSnapshot, "utf-8");
  });

  test("edits a numeric param and persists via PUT", async ({ page }) => {
    await page.goto("/");
    await page
      .getByRole("button", { name: FIXTURE_MODEL_ID })
      .click({ timeout: 15_000 });

    // 何も選択していない初期状態 (右パネルは "Click a block" メッセージ)
    await expect(page.getByTestId("parameter-panel-empty")).toBeVisible();

    // ノード "g" (Gain ブロック、param: k=2.0) を React Flow 上でクリック。
    // React Flow は data-id 属性でノードを識別する。
    await page.locator('.react-flow__node[data-id="g"]').click();

    // 右パネルが Gain ブロックの編集モードになる
    await expect(page.getByTestId("parameter-panel")).toBeVisible();
    const kInput = page.getByTestId("param-input-k");
    await expect(kInput).toHaveValue("2");

    // 値を 2 → 7.5 に変更し Save
    await kInput.fill("7.5");
    await page.getByTestId("parameter-panel-save").click();

    // 保存成功 (Saved badge と PUT 成功)
    await expect(page.getByText("Saved")).toBeVisible({ timeout: 10_000 });

    // モデル再読込で input が新しい値を保持していること
    await page.reload();
    await page
      .getByRole("button", { name: FIXTURE_MODEL_ID })
      .click({ timeout: 15_000 });
    await page.locator('.react-flow__node[data-id="g"]').click();
    await expect(page.getByTestId("param-input-k")).toHaveValue("7.5");
  });

  test("rejects invalid numeric input with an error message", async ({ page }) => {
    await page.goto("/");
    await page
      .getByRole("button", { name: FIXTURE_MODEL_ID })
      .click({ timeout: 15_000 });
    await page.locator('.react-flow__node[data-id="g"]').click();

    const kInput = page.getByTestId("param-input-k");
    await expect(kInput).toHaveValue("2");
    // ``<input type="number">`` は Playwright の ``fill("")`` / ``clear()`` で
    // 確実に空にならないことがあるため、ネイティブセッターで value="" を流し込み
    // React の onChange を明示的に発火する。
    await kInput.evaluate((el) => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        "value",
      )?.set;
      setter?.call(el, "");
      el.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await expect(kInput).toHaveValue("");
    await page.getByTestId("parameter-panel-save").click();
    await expect(page.getByText(/Invalid number/)).toBeVisible();
  });
});
