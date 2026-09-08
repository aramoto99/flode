import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

// ADR-0012 §(3) ParameterPanel E2E。v3.x ADR-0019 §(5) で auto-save 化されたため
// 旧 "Save" ボタンは無く、入力即時 commit + 500ms debounce で File API PUT。
// 本テストは数値パラメータを inline 編集して **ファイルに永続化される**ことを
// fs ベースで確認する (= GUI 上の "Saved" badge は廃止済)。

const FIXTURE_FILENAME = "minimal_model.flw.json";
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE_PATH = path.join(__dirname, "fixtures", FIXTURE_FILENAME);
const AUTOSAVE_DEBOUNCE_MS = 500;

let fixtureSnapshot: string;

test.describe("ParameterPanel (v3.x auto-save)", () => {
  test.beforeAll(() => {
    fixtureSnapshot = readFileSync(FIXTURE_PATH, "utf-8");
  });

  test.afterEach(() => {
    // 各テストで fs ベースに fixture を復元 (= 次テスト・次 CI run の独立性)
    writeFileSync(FIXTURE_PATH, fixtureSnapshot, "utf-8");
  });

  test("edits a numeric param and persists via File API PUT", async ({
    page,
  }) => {
    await page.goto("/");
    await page.getByText(FIXTURE_FILENAME).click({ timeout: 15_000 });

    // 空 Inspector (ノード未選択)
    await expect(page.getByTestId("parameter-panel-empty")).toBeVisible();

    // Gain ブロック "g" を React Flow 上で選択 (data-id)
    await page.locator('.react-flow__node[data-id="g"]').click();

    // Inspector が編集モードに遷移
    await expect(page.getByTestId("parameter-panel")).toBeVisible();
    const kInput = page.getByTestId("param-input-k");
    await expect(kInput).toHaveValue("2");

    // 値を 2 → 7.5 に変更 (= onChange で即 commit、auto-save が 500ms 後に PUT)
    await kInput.fill("7.5");
    await kInput.blur();

    // debounce + PUT 反映待ち
    await page.waitForTimeout(AUTOSAVE_DEBOUNCE_MS + 1500);

    // ファイルが書き換わっていることを確認 (= 真の永続化検証、UI badge 非依存)
    const persisted = JSON.parse(readFileSync(FIXTURE_PATH, "utf-8"));
    const gain = (persisted.blocks as { id: string; params: { k: number } }[])
      .find((b) => b.id === "g");
    expect(gain?.params.k).toBe(7.5);
  });

  // SPEC-0028 (SM-D Stage 1): 信号型セクション。shadow 表記は撤去され、
  // dtype 未宣言モデルには auto_note が出る
  test("shows the signal dtype section with the auto note for undeclared models", async ({
    page,
  }) => {
    await page.goto("/");
    await page.getByText(FIXTURE_FILENAME).click({ timeout: 15_000 });
    await page.locator('.react-flow__node[data-id="g"]').click();
    await expect(page.getByTestId("parameter-panel")).toBeVisible();

    // 300ms debounce 後に backend の resolve-dtypes 結果が描画される
    await expect(page.getByTestId("dtype-out-0")).toHaveText("float64", {
      timeout: 10_000,
    });
    // AC-9: shadow_note は存在しない。未宣言モデルには auto_note
    await expect(page.getByTestId("dtype-shadow-note")).toHaveCount(0);
    await expect(page.getByTestId("dtype-auto-note")).toBeVisible();
  });

  // SPEC-0028: dtype 宣言モデル — Inspector の select と信号型表示
  test("dtype select and resolved dtypes for a declared model", async ({
    page,
  }) => {
    await page.goto("/");
    await page.getByText("dtype_model.flw.json").click({ timeout: 15_000 });
    await page.locator('.react-flow__node[data-id="c"]').click();
    await expect(page.getByTestId("parameter-panel")).toBeVisible();

    // dtype param が enum <select> として描かれ int32 が選択されている
    const dtypeSelect = page.getByTestId("param-input-dtype");
    await expect(dtypeSelect).toBeVisible();
    await expect(dtypeSelect).toHaveValue("int32");

    // 信号型セクション: out[0] = int32、auto_note なし
    await expect(page.getByTestId("dtype-out-0")).toHaveText("int32", {
      timeout: 10_000,
    });
    await expect(page.getByTestId("dtype-auto-note")).toHaveCount(0);
  });
});
