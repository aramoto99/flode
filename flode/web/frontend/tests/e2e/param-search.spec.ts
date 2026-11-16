import { copyFileSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { readPortEnv } from "./ports";

// ADR-0085 / SPEC-0036: ユーザーブロックの引数に入れる値を検索して選ぶ。
// Inspector の「探す…」→ 検索 → 2 行選んで「追加」→ ポートが 2 つ増える →
// 同じ行をもう一度出すとブロックが別名を提案し、追加するとポートがさらに増える。
//
// 題材は fixtures/blocks/e2e_blocks.py の中立なダミーブロック (``block_dynamic_ports`` +
// ``block_param_search``)。型名・引数名・検索語は registry と検索 API から見つける
// (fixture の名前に依存させない)。後始末は user-blocks.spec.ts と同じ流儀。
//
// FLODE_E2E_SHOT_DIR を指定するとスクリーンショットをそこに保存する (CI では不要)。

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WORKSPACE = path.join(__dirname, ".workspace");
const MODEL_FILENAME = "param_search_model.flw.json";
const BACKEND_URL = `http://127.0.0.1:${readPortEnv("E2E_BACKEND_PORT", 8770)}`;
const SHOT_DIR = process.env.FLODE_E2E_SHOT_DIR ?? "";
/** 2 行以上返る検索語を探す候補 (1 文字の部分一致)。 */
const QUERY_CANDIDATES = ["a", "e", "o", "i", "u", "r", "s", "t", "n", "l"];

/** registry の ``params_spec`` の必要な部分。 */
interface ParamSpecLike {
  name: string;
  searchable?: boolean;
}
interface BlockLike {
  type_path: string;
  source?: string;
  dynamic_ports?: boolean;
  params_spec: ParamSpecLike[];
}

/** ワークスペースの、検索を宣言した引数でポートが増減するブロックを registry から探す。 */
async function findSearchableBlock(
  api: APIRequestContext,
): Promise<{ typePath: string; param: string } | undefined> {
  const res = await api.get("/api/v1/blocks");
  const body = (await res.json()) as { blocks: BlockLike[] };
  for (const b of body.blocks) {
    if (b.source !== "workspace" || b.dynamic_ports !== true) continue;
    const p = b.params_spec.find((s) => s.searchable === true);
    if (p !== undefined) return { typePath: b.type_path, param: p.name };
  }
  return undefined;
}

/** 空の ``current`` で 2 行以上返る検索語を見つける。 */
async function findQuery(
  api: APIRequestContext,
  typePath: string,
  param: string,
): Promise<string | undefined> {
  for (const query of QUERY_CANDIDATES) {
    const res = await api.post("/api/v1/blocks/search-param-values", {
      data: { type_path: typePath, param, query, current: [] },
    });
    if (!res.ok()) continue;
    const body = (await res.json()) as { rows: unknown[] };
    if (body.rows.length >= 2) return query;
  }
  return undefined;
}

async function shot(page: Page, name: string): Promise<void> {
  if (SHOT_DIR === "") return;
  await page.screenshot({ path: path.join(SHOT_DIR, name) });
}

test.describe("Parameter value search (ADR-0085)", () => {
  test.beforeAll(() => {
    copyFileSync(
      path.join(WORKSPACE, "minimal_model.flw.json"),
      path.join(WORKSPACE, MODEL_FILENAME),
    );
  });

  test.afterAll(async ({ playwright }) => {
    rmSync(path.join(WORKSPACE, MODEL_FILENAME), { force: true });
    const api = await playwright.request.newContext({ baseURL: BACKEND_URL });
    await api.post("/api/v1/blocks/reload", { data: {} });
    await api.dispose();
  });

  test("search, add two rows, ports grow, re-add gets a new name", async ({
    page,
    playwright,
  }) => {
    await page.setViewportSize({ width: 1280, height: 860 });
    await page.goto("/");
    await page.getByText(MODEL_FILENAME).click({ timeout: 15_000 });
    const libraryTab = page.getByTestId("activity-bar-library");
    if ((await libraryTab.getAttribute("aria-selected")) !== "true") {
      await libraryTab.click();
    }
    // 起動時点の .workspace/ に fixture が無いことがあるので読み込み直す
    const refetched = page.waitForResponse(
      (r) => r.request().method() === "GET" && /\/api\/v1\/blocks(\?|$)/.test(r.url()),
    );
    await page.getByTestId("palette-menu-button").click();
    await page.getByTestId("palette-menu-reload").click();
    await refetched;

    const api = await playwright.request.newContext({ baseURL: BACKEND_URL });
    const target = await findSearchableBlock(api);
    expect(target, "e2e_blocks.py must define a searchable dynamic-ports block").toBeDefined();
    const { typePath, param } = target!;
    const query = await findQuery(api, typePath, param);
    await api.dispose();
    expect(query, "the search function must return 2+ rows for some 1-letter query").toBeDefined();

    // パレットからキャンバスへ置いて選択する
    const section = page.locator(
      "[data-testid='palette-user-section'][data-source-id='workspace']",
    );
    await section
      .locator(`[data-type-path='${typePath}']`)
      .dragTo(page.locator(".react-flow__pane"), { targetPosition: { x: 420, y: 320 } });
    const node = page.locator(
      ".react-flow__node:not([data-id='src']):not([data-id='g']):not([data-id='sc'])",
    );
    await expect(node).toHaveCount(1);
    await node.click();
    await expect(page.getByTestId("parameter-panel")).toBeVisible();
    const handles = node.locator(".react-flow__handle");
    const before = await handles.count();

    // 探す… → 検索
    await page.getByTestId(`param-search-${param}`).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await page.getByTestId("param-search-query").fill(query!);
    const rows = page.getByTestId("param-search-table-row");
    await expect(rows.nth(1)).toBeVisible({ timeout: 30_000 });

    // 2 行選んで追加 → 引数の末尾に 2 行、ポートが 2 つ増える
    const first = rows.nth(0);
    const firstValue = (await first.getAttribute("data-key"))!;
    const firstLabel = (await first.locator("td").nth(1).textContent()) ?? "";
    const secondValue = (await rows.nth(1).getAttribute("data-key"))!;
    await first.click();
    await rows.nth(1).click();
    await expect(page.getByTestId("param-search-add")).toBeEnabled();
    await shot(page, "param_search_selected.png");
    await page.getByTestId("param-search-add").click();
    await expect(handles).toHaveCount(before + 2, { timeout: 15_000 });
    const editor = page.getByTestId(`param-input-${param}`);
    await expect(editor).toHaveValue(new RegExp(escapeRegExp(JSON.stringify(secondValue))));
    await expect(editor).toHaveValue(new RegExp(escapeRegExp(JSON.stringify(firstValue))));

    // 追加後は同じ検索語で再検索され、同じ行にはブロックが衝突しない名前を提案する
    const again = rows.filter({ hasText: firstLabel }).first();
    await expect(again).not.toHaveAttribute("data-key", firstValue, { timeout: 30_000 });
    await expect(again).not.toHaveAttribute("data-disabled", "true");
    await again.click();
    await page.getByTestId("param-search-add").click();
    await expect(handles).toHaveCount(before + 3, { timeout: 15_000 });
    await shot(page, "param_search_added.png");

    await page.getByTestId("param-search-close").click();
    await expect(dialog).toHaveCount(0);
  });
});

/** 正規表現の特殊文字をエスケープする。 */
function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
