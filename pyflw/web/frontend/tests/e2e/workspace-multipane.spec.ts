import { expect, type Page, test } from "@playwright/test";

// ADR-0045 Stage 1 (= v0.27.0): Workspace convergence Stage 1 = multi-pane split。
// `<main>` 内 Diagram + Scope の縦/横任意配置、localStorage 永続化、floating panel
// 並存を検証する E2E spec。
//
// 検証範囲 (= ADR-0045 §(8) 主要シナリオ E2E):
//   1. レイアウト初期化: Scope ブロックを持つモデルなら diagram + scopes-stack
//      の縦 split が表示される (= DEFAULT_TREE_WITH_SCOPES)
//   2. 常設化 (v0.42.x ユーザー要望): scopes-stack は × (分割解除) で閉じられず、
//      旧「出力エリアを表示」復帰ボタンも存在しない
//   3. 自動復元: 旧仕様で「閉じた状態」が永続化された layout (= diagram 単独) を
//      復元しても、Scope ブロックを持つモデルなら scopes-stack が自動再追加される
//   4. floating panel 並存: Scope ブロックの dblclick で react-rnd panel が出る
//
// **scope buffer 依存テスト (= scope:<id> 葉の split out)** はシミュレーション実行が
// 必要なため Stage 1 E2E では割愛 (= sim を始動して buffer を populate する別 spec が要)。

const FIXTURE_FILENAME = "minimal_model.flw.json";

async function openFixture(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByText(FIXTURE_FILENAME).click({ timeout: 15_000 });
  await expect(page.locator(".react-flow__viewport")).toBeVisible({
    timeout: 15_000,
  });
}

test.describe("ADR-0045 Workspace multi-pane Stage 1", () => {
  test.beforeEach(async ({ page }) => {
    // 既存 localStorage を一度クリア (= テスト間の干渉を防ぐ、ADR-0045 §(3) キーは
    // pyflw.workspace_layout.* / pyflw.last_active.* など)
    await page.goto("/");
    await page.evaluate(() => window.localStorage.clear());
  });

  test("initial layout shows diagram + scopes-stack for fixture with Scope", async ({
    page,
  }) => {
    await openFixture(page);
    // Diagram slot は data-testid で識別 (= WorkspaceSplit 内の DiagramSlot)
    await expect(
      page.locator("[data-testid='workspace-pane-diagram-slot']"),
    ).toBeVisible({ timeout: 10_000 });
    // diagram pane の title bar (= "Diagram" en / "ダイアグラム" ja のいずれか)
    await expect(
      page.getByText(/^(Diagram|ダイアグラム)$/).first(),
    ).toBeVisible();
    // scopes-stack pane (= pane 葉の data-testid で判定。タイトル文言
    // "Output/出力" は v0.30.3 の復帰ボタンと衝突するため text では見ない)
    await expect(
      page.locator("[data-testid='workspace-pane-leaf-scopes-stack']"),
    ).toBeVisible();
  });

  test("scopes-stack pane is permanent (no close button, no restore button)", async ({
    page,
  }) => {
    await openFixture(page);
    await expect(
      page.locator("[data-testid='workspace-pane-leaf-scopes-stack']"),
    ).toBeVisible();
    // v0.42.x: scopes-stack に unsplit (= 分割解除) ボタンは付かない。
    // 初期レイアウトでは他に閉じられる pane も無いため、画面全体で 0 個。
    await expect(
      page.getByRole("button", { name: /^(Close pane|分割解除)$/ }),
    ).toHaveCount(0);
    // 旧「出力エリアを表示」復帰ボタン (v0.30.3) も廃止済み
    await expect(
      page.getByRole("button", { name: /^(Show output area|出力エリアを表示)/ }),
    ).toHaveCount(0);
  });

  test("legacy 'closed output area' layout is auto-restored on reload", async ({
    page,
  }) => {
    await openFixture(page);
    await expect(
      page.locator("[data-testid='workspace-pane-leaf-scopes-stack']"),
    ).toBeVisible();
    // 旧仕様 (× で閉じられた) の永続 layout を再現: 保存済みキーを
    // diagram 単独 tree で上書きしてからリロードする
    await page.evaluate(() => {
      for (const key of Object.keys(window.localStorage)) {
        if (key.startsWith("pyflw.workspace_layout.")) {
          window.localStorage.setItem(
            key,
            JSON.stringify({ kind: "leaf", paneId: "diagram" }),
          );
        }
      }
    });
    await page.reload();
    await expect(page.locator(".react-flow__viewport")).toBeVisible({
      timeout: 15_000,
    });
    // Scope ブロックを持つモデルなので scopes-stack が自動再追加される
    await expect(
      page.locator("[data-testid='workspace-pane-leaf-scopes-stack']"),
    ).toBeVisible();
    await expect(
      page.locator("[data-testid='workspace-pane-diagram-slot']"),
    ).toBeVisible();
  });

  test("split layout persists across page reload (Ctrl+\\ tab split)", async ({
    page,
  }) => {
    // scopes-stack 常設化と無関係な汎用 split 操作で、splitPane → localStorage
    // 永続化 → reload 復元 のパイプラインを検証する (旧 unsplit ベースのテスト
    // の置き換え)。Ctrl+\ = active tab を diagram の右に split (ADR-0052 §(6))。
    await openFixture(page);
    const tabLeaf = page.locator(
      `[data-testid='workspace-pane-leaf-tab:${FIXTURE_FILENAME}']`,
    );
    await expect(tabLeaf).toHaveCount(0);
    await page.keyboard.press("Control+\\");
    await expect(tabLeaf).toBeVisible();

    await page.reload();
    await expect(page.locator(".react-flow__viewport")).toBeVisible({
      timeout: 15_000,
    });
    // 永続化された tab 葉入り SplitTree が復元される
    await expect(tabLeaf).toBeVisible();
  });

  test("floating Scope panel coexists with docked multi-pane (ADR-0044)", async ({
    page,
  }) => {
    await openFixture(page);
    // Scope ブロック (= 3 番目のノード "sc") をダブルクリック → react-rnd panel が出る
    const nodes = page.locator(".react-flow__node");
    await expect(nodes).toHaveCount(3, { timeout: 10_000 });
    await nodes.nth(2).dblclick();
    // ScopePanelContainer の Rnd wrapper は ``data-testid="scope-floating-panel-<id>"``
    // (= ADR-0045 NITS #7 で追加、CSS クラス依存セレクタを避ける)
    await expect(
      page.locator("[data-testid^='scope-floating-panel-']").first(),
    ).toBeVisible({ timeout: 10_000 });
    // 同時に docked 領域の Diagram + scopes-stack pane も残る
    await expect(
      page.locator("[data-testid='workspace-pane-diagram-slot']"),
    ).toBeVisible();
    await expect(
      page.locator("[data-testid='workspace-pane-leaf-scopes-stack']"),
    ).toBeVisible();
  });
});
