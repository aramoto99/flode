import { expect, type Page, test } from "@playwright/test";

// ADR-0045 Stage 1 (= v0.27.0): Workspace convergence Stage 1 = multi-pane split。
// `<main>` 内 Diagram + Scope の縦/横任意配置、localStorage 永続化、floating panel
// 並存を検証する E2E spec。
//
// 検証範囲 (= ADR-0045 §(8) 主要シナリオ E2E):
//   1. レイアウト初期化: Scope ブロックを持つモデルなら diagram + scopes-stack
//      の縦 split が表示される (= DEFAULT_TREE_WITH_SCOPES)
//   2. 分割解除: scopes-stack pane の unsplit ボタンで diagram のみに縮約
//   3. 再分割: 縮約後は diagram title bar の「出力エリアを表示」復帰ボタン
//      (v0.30.3、diagram からの split は v0.30.2 で禁止) で scopes-stack を再追加
//   4. 永続化: 操作後にリロードしても同じレイアウトが復元される
//   5. floating panel 並存: Scope ブロックの dblclick で react-rnd panel が出る
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

  test("unsplit button removes scopes-stack pane", async ({ page }) => {
    await openFixture(page);
    // scopes-stack pane に unsplit ボタンがある (= aria-label "Close pane" en /
    // "分割解除" ja)。pane title bar 内なので first() で十分。
    const unsplitBtn = page
      .getByRole("button", { name: /^(Close pane|分割解除)$/ })
      .first();
    await expect(unsplitBtn).toBeVisible();
    await unsplitBtn.click();
    // unsplit 後は scopes-stack pane が消える。v0.30.3 以降、diagram 側に
    // 「出力を表示」復帰ボタン (= text "Output/出力") が出るため、pane の
    // 有無は text ではなく pane 葉の data-testid で判定する。
    await expect(
      page.locator("[data-testid='workspace-pane-leaf-scopes-stack']"),
    ).toHaveCount(0);
    // diagram pane は残る
    await expect(
      page.locator("[data-testid='workspace-pane-diagram-slot']"),
    ).toBeVisible();
  });

  test("after unsplit, show-output-area button re-adds scopes-stack pane", async ({
    page,
  }) => {
    await openFixture(page);
    // まず scopes-stack を unsplit して diagram のみに
    await page
      .getByRole("button", { name: /^(Close pane|分割解除)$/ })
      .first()
      .click();
    await expect(
      page.locator("[data-testid='workspace-pane-leaf-scopes-stack']"),
    ).toHaveCount(0);
    // v0.30.2 で diagram pane からの split は禁止され、代わりに v0.30.3 の
    // 「出力を表示」復帰ボタン (aria-label = "Show output area...") が
    // scopes-stack pane を再追加する正規経路になった
    const showScopesBtn = page
      .getByRole("button", {
        name: /^(Show output area|出力エリアを表示)/,
      })
      .first();
    await expect(showScopesBtn).toBeVisible();
    await showScopesBtn.click();
    // scopes-stack pane が再出現
    await expect(
      page.locator("[data-testid='workspace-pane-leaf-scopes-stack']"),
    ).toBeVisible();
  });

  test("layout persists across page reload", async ({ page }) => {
    await openFixture(page);
    // scopes-stack を unsplit → diagram only に変更 (= localStorage に永続化される)
    await page
      .getByRole("button", { name: /^(Close pane|分割解除)$/ })
      .first()
      .click();
    await expect(
      page.locator("[data-testid='workspace-pane-leaf-scopes-stack']"),
    ).toHaveCount(0);

    // リロード後、last_active 経由で fixture が自動復元される (ADR-0043 §論点 8-A)
    await page.reload();
    await expect(page.locator(".react-flow__viewport")).toBeVisible({
      timeout: 15_000,
    });
    // 永続化された SplitTree (= diagram のみ) が復元 → scopes-stack pane 不在
    await expect(
      page.locator("[data-testid='workspace-pane-leaf-scopes-stack']"),
    ).toHaveCount(0);
    // diagram pane は復元される
    await expect(
      page.locator("[data-testid='workspace-pane-diagram-slot']"),
    ).toBeVisible();
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
