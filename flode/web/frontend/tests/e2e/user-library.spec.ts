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

test.describe("Block context menu", () => {
  // 回帰: 階層を移動した後に、ブロックの右クリックメニュー (と右ドラッグ複製) が
  // 効かなくなる不具合があった。
  test("still opens after drilling into a Subsystem and coming back", async ({ page }) => {
    await page.goto("/");
    await page.getByText(FIXTURE_FILENAME).click({ timeout: 15_000 });
    const subsystemNode = page.locator('.react-flow__node[data-id="MyGain"]');
    await expect(subsystemNode).toBeVisible();

    // 移動前: メニューが出る
    await subsystemNode.click({ button: "right" });
    await expect(page.getByTestId("block-menu-add-to-library")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("block-context-menu")).toHaveCount(0);

    // drill-down → 戻る
    await subsystemNode.dblclick();
    await expect(page.locator('.react-flow__node[data-id="k"]')).toBeVisible();
    await page.getByRole("button", { name: "Top", exact: true }).click();
    await expect(subsystemNode).toBeVisible();

    // 移動後: 同じようにメニューが出る
    await subsystemNode.click({ button: "right" });
    await expect(page.getByTestId("block-menu-add-to-library")).toBeVisible();
    await page.keyboard.press("Escape");
  });

  // 回帰: 範囲選択でブロックを複数選ぶと、React Flow が選択範囲の上に透明な四角
  // (.react-flow__nodesselection-rect) を重ねる。その上の右クリックはブロックに届かず、
  // ブラウザのメニューが出て flode のメニューも開かなかった。配線とズームボタンの
  // 右クリックでもブラウザのメニューが出ていた。
  test("opens on a box-selected block and never shows the browser menu in the canvas", async ({
    page,
  }) => {
    await page.goto("/");
    await page.getByText(FIXTURE_FILENAME).click({ timeout: 15_000 });
    const subsystemNode = page.locator('.react-flow__node[data-id="MyGain"]');
    await expect(subsystemNode).toBeVisible();

    // 全ハンドラの後に contextmenu の defaultPrevented を記録する (false = ブラウザの
    // メニューが出る)
    await page.evaluate(() => {
      const w = window as unknown as { __contextMenuPrevented: boolean[] };
      w.__contextMenuPrevented = [];
      window.addEventListener("contextmenu", (e) => w.__contextMenuPrevented.push(e.defaultPrevented));
    });
    const takePrevented = (): Promise<boolean[]> =>
      page.evaluate(() => {
        const w = window as unknown as { __contextMenuPrevented: boolean[] };
        const out = w.__contextMenuPrevented;
        w.__contextMenuPrevented = [];
        return out;
      });

    // 3 ブロックをドラッグで囲んで範囲選択する
    const src = await page.locator('.react-flow__node[data-id="src"]').boundingBox();
    const sc = await page.locator('.react-flow__node[data-id="sc"]').boundingBox();
    if (src === null || sc === null) throw new Error("fixture nodes have no bounding box");
    await page.mouse.move(src.x - 20, src.y - 60);
    await page.mouse.down();
    await page.mouse.move(sc.x + sc.width + 20, sc.y + sc.height + 40, { steps: 10 });
    await page.mouse.up();
    await expect(page.locator(".react-flow__node.selected")).toHaveCount(3);
    await expect(page.locator(".react-flow__nodesselection-rect")).toHaveCount(1);

    // 選択範囲の上から Subsystem を右クリック → flode のメニュー、ブラウザのメニューは出ない
    const gain = await subsystemNode.boundingBox();
    if (gain === null) throw new Error("subsystem node has no bounding box");
    await page.mouse.click(gain.x + gain.width / 2, gain.y + gain.height / 2, { button: "right" });
    await expect(page.getByTestId("block-menu-add-to-library")).toBeVisible();
    expect(await takePrevented()).toEqual([true]);
    // 複数選択は保たれる
    await expect(page.locator(".react-flow__node.selected")).toHaveCount(3);
    await page.keyboard.press("Escape");

    // 配線の右クリック
    await page.locator(".react-flow__pane").click({ position: { x: 20, y: 20 } });
    // React Flow が配線の当たり判定に使う要素を直接右クリックする (bounding box の中心は
    // 折れ線の上に乗らないことがあり、pane に当たると回帰を検出できない)
    const edgeHit = page.locator(".react-flow__edge-interaction").first();
    const edgeTarget = await edgeHit.evaluate((el) => {
      const w = window as unknown as { __edgeTargetIsEdge: boolean };
      w.__edgeTargetIsEdge = false;
      const onCtx = (e: Event): void => {
        w.__edgeTargetIsEdge =
          e.target instanceof Element && e.target.closest(".react-flow__edge") !== null;
      };
      window.addEventListener("contextmenu", onCtx, { capture: true, once: true });
      return el.tagName.toLowerCase();
    });
    expect(edgeTarget).toBe("path");
    await edgeHit.click({ button: "right", force: true });
    expect(
      await page.evaluate(
        () => (window as unknown as { __edgeTargetIsEdge: boolean }).__edgeTargetIsEdge,
      ),
    ).toBe(true);
    await expect(page.getByTestId("block-context-menu")).toHaveCount(0);
    // キャンバス左下のボタン (全体表示) の右クリック
    await page.locator(".react-flow__controls-fitview").click({ button: "right" });
    expect(await takePrevented()).toEqual([true, true]);
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

  // SPEC-0032 §1.9: 上書き登録 → 配置済みブロックに更新マーカー → 確認つきの差し替え →
  // 中身が新版になる → Ctrl+Z 1 回で元に戻る。
  test("overwrite an entry, see the update marker, replace from the Inspector, undo", async ({
    page,
  }) => {
    const name = "E2E Rev";
    const placedId = "E2E_Rev";
    await page.goto("/");
    await page.getByText(FIXTURE_FILENAME).click({ timeout: 15_000 });
    const sourceNode = page.locator('.react-flow__node[data-id="MyGain"]');
    await expect(sourceNode).toBeVisible();
    const topButton = page.getByRole("button", { name: "Top", exact: true });

    /** MyGain を ``name`` でマイブロックに登録する (ダイアログを開いて送信まで)。 */
    const submitRegistration = async (): Promise<void> => {
      await sourceNode.click({ button: "right" });
      await page.getByTestId("block-menu-add-to-library").click();
      await page.getByTestId("library-entry-name").fill(name);
      await page.getByTestId("library-entry-submit").click();
    };

    // --- rev 1 を登録して配置 ---
    await submitRegistration();
    await expect(page.getByTestId("library-entry-dialog")).toHaveCount(0);
    await page.getByLabel("Library", { exact: true }).click();
    const entry = page.getByTestId("palette-section-my-blocks").getByText(name, { exact: true });
    await entry.dragTo(page.getByTestId("rf__wrapper"), { targetPosition: { x: 80, y: 40 } });
    const placedNode = page.locator(`.react-flow__node[data-id="${placedId}"]`);
    await expect(placedNode).toBeVisible();
    const marker = page.getByTestId(`library-update-marker-${placedId}`);
    await expect(marker).toHaveCount(0);

    // 配置直後の Inspector: 由来行と「最新」
    await expect(page.getByTestId("library-provenance-source")).toHaveText(
      `My Blocks / ${name} (rev 1)`,
    );
    await expect(page.getByTestId("library-provenance-status")).toHaveText("Up to date");
    await expect(page.getByTestId("library-provenance-replace")).toHaveCount(0);

    // --- 登録元の中身を変えて (内部 Gain k: 3 → 5)、同名で上書き登録 → rev 2 ---
    await sourceNode.dblclick();
    await page.locator('.react-flow__node[data-id="k"]').click();
    await page.getByTestId("param-input-k").fill("5");
    await page.getByTestId("param-input-k").blur();
    await topButton.click();
    await expect(sourceNode).toBeVisible();
    await submitRegistration();
    // 同名 → 確認ダイアログ (既定は別名)。ここでは上書きを選ぶ
    await expect(page.getByTestId("library-name-conflict-dialog")).toBeVisible();
    await expect(page.getByTestId("library-conflict-overwrite")).toHaveText(
      "Overwrite (rev 1 → 2)",
    );
    await page.getByTestId("library-conflict-overwrite").click();
    await expect(page.getByTestId("library-name-conflict-dialog")).toHaveCount(0);
    // 上書きの通知は新規登録と別の文言 (版が分かる)
    await expect(page.getByText(`Updated "${name}" in My Blocks to rev 2.`)).toBeVisible();

    // --- 配置済みブロックに更新マーカー (登録元は rev 2 になったので付かない) ---
    await expect(marker).toBeVisible();
    await expect(marker).toHaveAttribute("title", /rev 1 → 2/);
    await expect(page.getByTestId("library-update-marker-MyGain")).toHaveCount(0);
    await snapshot(page, "update-marker.png");

    // --- Inspector: 更新あり + [差し替え] ---
    await placedNode.click();
    await expect(page.getByTestId("library-provenance-status")).toHaveText(
      "Update available (rev 1 → 2)",
    );
    await snapshot(page, "inspector-provenance-update.png");
    await page.getByTestId("library-provenance-replace").click();
    const confirmDialog = page.getByTestId("library-replace-dialog");
    await expect(confirmDialog).toContainText("edits you made inside this block will be lost");
    // 差し替え元 (ライブラリの表示名・内部名・種別・エントリ) と版が明記される
    await expect(page.getByTestId("library-replace-source")).toHaveText("My Blocks(user)");
    await expect(page.getByTestId("library-replace-kind")).toContainText("your own library");
    await expect(confirmDialog).toContainText(name);
    await expect(confirmDialog).toContainText("rev 1 → rev 2");
    // 既定はキャンセル (破壊的な操作を Enter で確定させない)
    await expect(page.getByTestId("library-replace-cancel")).toBeFocused();
    await snapshot(page, "replace-confirm-dialog.png");
    await page.getByTestId("library-replace-confirm").click();

    await expect(page.getByTestId("library-provenance-status")).toHaveText("Up to date");
    await expect(page.getByTestId("library-provenance-source")).toHaveText(
      `My Blocks / ${name} (rev 2)`,
    );
    await expect(marker).toHaveCount(0);
    // id と位置はそのまま (ノードは同じ id で存在し続ける)
    await expect(placedNode).toBeVisible();

    // --- 中身が新版 (k = 5) になっている ---
    await placedNode.dblclick();
    await page.locator('.react-flow__node[data-id="k"]').click();
    await expect(page.getByTestId("param-input-k")).toHaveValue("5");
    await topButton.click();
    await expect(placedNode).toBeVisible();

    // --- Ctrl+Z 1 回で差し替え前 (rev 1、更新あり) に戻る ---
    await page.locator(".react-flow__pane").click({ position: { x: 20, y: 20 } });
    await page.keyboard.press("Control+z");
    await expect(marker).toBeVisible();
    await placedNode.click();
    await expect(page.getByTestId("library-provenance-status")).toHaveText(
      "Update available (rev 1 → 2)",
    );
    await placedNode.dblclick();
    await page.locator('.react-flow__node[data-id="k"]').click();
    await expect(page.getByTestId("param-input-k")).toHaveValue("3");
  });

  // ADR-0080 Amendments 2: 自分の書き出し物は同じ環境に取り込めない (uid が重複する)。
  // 書き出しファイルを取得し、取り込みの確認ダイアログが衝突を表示して確定できない
  // ことを確かめる (別環境への取り込み → 警告表示は unit で確認している)。
  test("an exported My Blocks file cannot be imported back into the same environment", async ({
    page,
  }) => {
    const exported = await page.request.get("/api/v1/libraries/user/export");
    expect(exported.ok()).toBe(true);
    expect(exported.headers()["content-disposition"]).toMatch(/attachment; filename="user-/);
    const text = await exported.text();
    const library = JSON.parse(text) as { name: string; uid: string };
    // 予約名 user のままでは受け取った側が取り込めないので改名されている
    expect(library.name).toMatch(/^user-[0-9a-f]{8}$/);
    expect(library.uid.startsWith(library.name.slice("user-".length))).toBe(true);

    await page.goto("/");
    await page.getByLabel("Library", { exact: true }).click();
    await expect(page.getByTestId("palette-section-my-blocks")).toBeVisible();
    await page.getByTestId("palette-import-file").setInputFiles({
      name: "exported.flwlib.json",
      mimeType: "application/json",
      buffer: Buffer.from(text, "utf-8"),
    });
    await expect(page.getByTestId("library-import-dialog")).toBeVisible();
    await expect(page.getByTestId("library-import-conflict")).toContainText("same library ID");
    await expect(page.getByTestId("library-import-confirm")).toBeDisabled();
    await page.getByTestId("library-import-cancel").click();
    await expect(page.getByTestId("library-import-dialog")).toHaveCount(0);
    // 取り込まれていない (取り込みライブラリのセクションが増えていない)
    await expect(page.getByTestId(`palette-library-header-${library.name}`)).toHaveCount(0);
  });
});
