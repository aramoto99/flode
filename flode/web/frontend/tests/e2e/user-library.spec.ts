import { existsSync, mkdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { e2eMarkerLibraryName } from "./libraryState";

// SPEC-0032 §1.9 / ADR-0080: 実 backend で「Subsystem を右クリックで登録 →
// 再起動なしでパレット最上部のマイブロックに出る → drop で配置」を通す。
//
// backend のユーザーライブラリの置き場は playwright.config.ts が OS の一時
// ディレクトリに向けている (実ホーム ~/.flode には書かない)。書き込みの前に、
// backend が本当にその一時ディレクトリを読んでいることを目印ライブラリで確かめる。

const FIXTURE_FILENAME = "subsystem_model.flw.json";
const ENTRY_NAME = "E2E Gain";
// 表示名由来の block id (空白は _ に置換、SPEC-0032 §1.4-2)
const PLACED_BLOCK_ID = "E2E_Gain";
const STATE_DIR = process.env.FLODE_E2E_STATE_DIR ?? "";
// 目視確認用スクリーンショットの保存先 (未指定なら保存しない)
const SCREENSHOT_DIR = process.env.FLODE_E2E_SCREENSHOT_DIR ?? "";

/** 目視確認用のスクリーンショットを保存する (保存先が未指定なら何もしない)。 */
async function snapshot(
  target: { screenshot: (options: { path: string }) => Promise<unknown> },
  name: string,
): Promise<void> {
  if (!SCREENSHOT_DIR) return;
  mkdirSync(SCREENSHOT_DIR, { recursive: true });
  await target.screenshot({ path: path.join(SCREENSHOT_DIR, name) });
}

test.describe("Right-button drag on a block", () => {
  test("copies the block, and a single undo removes the copy", async ({ page }) => {
    await page.goto("/");
    await page.getByText(FIXTURE_FILENAME).click({ timeout: 15_000 });
    const nodes = page.locator(".react-flow__node");
    await expect(nodes).toHaveCount(3);
    const box = await page.locator('.react-flow__node[data-id="src"]').boundingBox();
    if (box === null) throw new Error("source node has no bounding box");
    const startX = box.x + box.width / 2;
    const startY = box.y + box.height / 2;

    // 右ボタンを押したまま動かす → 複製がカーソルに追従する
    await page.mouse.move(startX, startY);
    await page.mouse.down({ button: "right" });
    await page.mouse.move(startX + 30, startY + 60, { steps: 5 });
    await page.mouse.move(startX + 60, startY + 120, { steps: 5 });
    await page.mouse.up({ button: "right" });

    await expect(nodes).toHaveCount(4);
    // ドラッグなのでメニューは開かない。元のブロックは残っている
    await expect(page.getByTestId("block-context-menu")).toHaveCount(0);
    await expect(page.locator('.react-flow__node[data-id="src"]')).toBeVisible();

    // 追加 + 追従は undo 履歴 1 件 → Ctrl+Z 1 回で複製が消える
    await page.locator(".react-flow__pane").click({ position: { x: 20, y: 20 } });
    await page.keyboard.press("Control+z");
    await expect(nodes).toHaveCount(3);
    await expect(page.locator('.react-flow__node[data-id="src"]')).toBeVisible();
  });
});

test.describe("User library (My Blocks)", () => {
  test("register a Subsystem, see it in My Blocks, and place it by drop", async ({
    page,
  }) => {
    // --- 安全確認: backend のユーザーライブラリは実ホームではなく一時ディレクトリ ---
    expect(STATE_DIR, "FLODE_E2E_STATE_DIR must be set by playwright.config.ts").not.toBe("");
    const registryResponse = await page.request.get("/api/v1/libraries");
    expect(registryResponse.ok()).toBe(true);
    const registry = (await registryResponse.json()) as {
      libraries: { name: string }[];
      user_library: { enabled: boolean; writable: boolean };
    };
    expect(
      registry.libraries.map((lib) => lib.name),
      "backend must load the marker library from the temporary user library dir. " +
        "If it is missing, Playwright probably reused a backend that was started with " +
        "a different configuration (so writes could land in the real home directory). " +
        "Re-run with different E2E_BACKEND_PORT / E2E_FRONTEND_PORT values.",
    ).toContain(e2eMarkerLibraryName(STATE_DIR));
    expect(registry.user_library.writable).toBe(true);

    await page.goto("/");
    await page.getByText(FIXTURE_FILENAME).click({ timeout: 15_000 });
    const sourceNode = page.locator('.react-flow__node[data-id="MyGain"]');
    await expect(sourceNode).toBeVisible();

    // 登録できない種別 (Constant) の右クリックではメニューが出ない
    await page.locator('.react-flow__node[data-id="src"]').click({ button: "right" });
    await expect(page.getByTestId("block-context-menu")).toHaveCount(0);

    // --- 登録: 右クリック →「ライブラリに追加…」→ ダイアログ ---
    await sourceNode.click({ button: "right" });
    await page.getByTestId("block-menu-add-to-library").click();
    const dialog = page.getByTestId("library-entry-dialog");
    await expect(dialog).toBeVisible();
    // 名前の既定値はブロックの id
    await expect(page.getByTestId("library-entry-name")).toHaveValue("MyGain");
    await page.getByTestId("library-entry-name").fill(ENTRY_NAME);
    await page.getByTestId("library-entry-description").fill("Gain of 3 (E2E)");
    await page.getByTestId("library-entry-category").fill("e2e");
    await snapshot(page, "register-dialog.png");
    await page.getByTestId("library-entry-submit").click();
    await expect(dialog).toHaveCount(0);

    // 右クリックだけでは複製が作られない (右ドラッグ複製との両立)
    await expect(page.locator(".react-flow__node")).toHaveCount(3);

    // --- パレット: 再起動なしで最上部のマイブロックに出る ---
    await page.getByLabel("Library", { exact: true }).click();
    const myBlocks = page.getByTestId("palette-section-my-blocks");
    await expect(myBlocks).toBeVisible();
    const entry = myBlocks.getByText(ENTRY_NAME, { exact: true });
    await expect(entry).toBeVisible();
    await expect(page.getByTestId("palette-my-blocks-group-e2e")).toBeVisible();
    await snapshot(page, "palette-my-blocks.png");

    // --- drop で配置: id はエントリ名由来 ---
    // キャンバス左上の空き (fitView で既存ブロックは中央に寄っている) に落とす
    await entry.dragTo(page.getByTestId("rf__wrapper"), {
      targetPosition: { x: 80, y: 40 },
    });
    await expect(
      page.locator(`.react-flow__node[data-id="${PLACED_BLOCK_ID}"]`),
    ).toBeVisible();
    await expect(page.locator(".react-flow__node")).toHaveCount(4);
    await snapshot(page, "placed-from-my-blocks.png");

    // --- ファイルは一時ディレクトリに書かれている ---
    const userLibraryPath = path.join(STATE_DIR, "libraries", "user.flwlib.json");
    expect(existsSync(userLibraryPath)).toBe(true);
    const saved = JSON.parse(readFileSync(userLibraryPath, "utf-8")) as {
      schema_version: string;
      name: string;
      entries: { display_name: string; category_suffix: string; revision: number }[];
    };
    expect(saved.schema_version).toBe("libraries.v4");
    expect(saved.name).toBe("user");
    expect(saved.entries).toHaveLength(1);
    expect(saved.entries[0]).toMatchObject({
      display_name: ENTRY_NAME,
      category_suffix: "e2e",
      revision: 1,
    });
  });
});
