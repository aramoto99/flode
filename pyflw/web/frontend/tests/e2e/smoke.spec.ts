import { expect, test } from "@playwright/test";

// pyflw Web GUI の最小回帰テスト (v3.x、ADR-0041 File API ベース)。
//
// v2.x までは ModelList / model_id ベースだったが、v0.21.0 で workspace +
// FileBrowser に置換されたため smoke spec を全面書き換え。
// 検証内容:
//   1. ルート (/) にアクセスし、title bar "pyflw" が描画される
//   2. workspace 内の minimal_model.flw.json が FileBrowser に表示される
//   3. ファイルを開くと TabStrip にタブが現れる + DiagramCanvas が描画される

const FIXTURE_FILENAME = "minimal_model.flw.json";

test.describe("pyflw web GUI smoke (v3.x)", () => {
  test("renders root page with pyflw branding", async ({ page }) => {
    await page.goto("/");
    // title bar の "pyflw" + version
    await expect(page.locator("text=pyflw").first()).toBeVisible({
      timeout: 15_000,
    });
  });

  test("shows fixture file in workspace tree", async ({ page }) => {
    await page.goto("/");
    // FileBrowser の tree に minimal_model.flw.json が出る
    // (= GET /api/v1/files/tree が返す children)
    await expect(page.getByText(FIXTURE_FILENAME)).toBeVisible({
      timeout: 15_000,
    });
  });

  test("opens fixture file, showing diagram canvas and tab strip", async ({
    page,
  }) => {
    await page.goto("/");
    // tree 上で fixture をクリック → 開く
    await page
      .getByText(FIXTURE_FILENAME)
      .click({ timeout: 15_000 });

    // TabStrip に該当 file の basename が表示される
    await expect(
      page.locator(`text=${FIXTURE_FILENAME}`).first(),
    ).toBeVisible({ timeout: 10_000 });

    // DiagramCanvas (React Flow) の viewport が描画される
    await expect(page.locator(".react-flow__viewport")).toBeVisible({
      timeout: 10_000,
    });
  });
});
