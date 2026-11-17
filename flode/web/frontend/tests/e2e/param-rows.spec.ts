import { readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type APIRequestContext, type Locator, type Page } from "@playwright/test";

import { readPortEnv } from "./ports";

// ADR-0086 / SPEC-0037 受け入れ条件 9: ユーザーブロックの行リスト引数の行エディタ。
// Inspector の表で行を追加すると入力ポートが 1 つ増える。配線のある途中の行を削除すると、
// 後ろの行の配線は同じ行 (詰まった番号のポート) に付いたまま残る。Undo で引数と配線が戻る。
//
// 題材は fixtures/blocks/e2e_blocks.py の中立なダミーブロック (``block_dynamic_ports`` +
// ``block_param_rows``)。型名・引数名は registry から見つけ、既存の行の値は検索 API
// (同じブロックの ``block_param_search``) から借りる (fixture の名前に依存させない)。
// 配線の確認は自動保存されたモデルファイルを読む (キャンバスのエッジは番号を持たないため)。
//
// FLODE_E2E_SHOT_DIR を指定するとスクリーンショットをそこに保存する (CI では不要)。

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WORKSPACE = path.join(__dirname, ".workspace");
const MODEL_FILENAME = "param_rows_model.flw.json";
const BACKEND_URL = `http://127.0.0.1:${readPortEnv("E2E_BACKEND_PORT", 8770)}`;
const SHOT_DIR = process.env.FLODE_E2E_SHOT_DIR ?? "";
/** 行の値・pick の候補を探す検索語 (1 文字の部分一致)。 */
const QUERY_CANDIDATES = ["a", "e", "o", "i", "u", "r", "s", "t", "n", "l"];
/** 行エディタのブロックの id。 */
const BIN_ID = "bin";
/** 配線元の Constant の id (行 i ← SOURCES[i])。 */
const SOURCES = ["s0", "s1", "s2"];

/** registry の ``params_spec`` の必要な部分。 */
interface ParamSpecLike {
  name: string;
  searchable?: boolean;
  row_editor?: boolean;
}
interface BlockLike {
  type_path: string;
  source?: string;
  dynamic_ports?: boolean;
  params_spec: ParamSpecLike[];
}
interface SavedModel {
  blocks: Array<{ id: string; params: Record<string, unknown> }>;
  connections: Array<{ src: string; src_idx: number; dst: string; dst_idx: number }>;
}

/** ワークスペースの、行エディタを宣言した引数でポートが増減するブロックを registry から探す。 */
async function findRowEditorBlock(
  api: APIRequestContext,
): Promise<{ typePath: string; param: string; searchable: boolean } | undefined> {
  const res = await api.get("/api/v1/blocks");
  const body = (await res.json()) as { blocks: BlockLike[] };
  for (const b of body.blocks) {
    if (b.source !== "workspace" || b.dynamic_ports !== true) continue;
    const p = b.params_spec.find((s) => s.row_editor === true);
    if (p !== undefined) {
      return { typePath: b.type_path, param: p.name, searchable: p.searchable === true };
    }
  }
  return undefined;
}

/** 初期の 3 行。ブロックの検索関数があればその値 (正しい行) を借りる。 */
async function initialRows(
  api: APIRequestContext,
  typePath: string,
  param: string,
  searchable: boolean,
): Promise<string[]> {
  if (searchable) {
    const rows: string[] = [];
    for (const query of QUERY_CANDIDATES) {
      const res = await api.post("/api/v1/blocks/search-param-values", {
        data: { type_path: typePath, param, query, current: rows },
      });
      if (!res.ok()) continue;
      const body = (await res.json()) as { rows: Array<{ value: string }> };
      for (const r of body.rows) {
        if (rows.length < SOURCES.length && !rows.includes(r.value)) rows.push(r.value);
      }
      if (rows.length >= SOURCES.length) return rows;
    }
  }
  // 検索が無い / 足りない: ポート数は行数で決まるので、説明に誤りが出ても配線の確認はできる
  return SOURCES.map((_, i) => `row${i}`);
}

/** Constant × 3 → 行エディタのブロックの入力 0..2 のモデル。 */
function rowsModel(typePath: string, param: string, rows: string[]): Record<string, unknown> {
  return {
    schema_version: "0.15",
    metadata: { tool: "flode e2e (ADR-0086)" },
    simulator: { t_end: 0.1, dt: 0.01, solver: "RK45", rtol: 1e-6, atol: 1e-9, dt_base: null },
    blocks: [
      ...SOURCES.map((id) => ({
        id,
        type: "flode.blocks.sources.Constant",
        params: { value: 1.0 },
      })),
      { id: BIN_ID, type: typePath, params: { [param]: rows } },
    ],
    connections: SOURCES.map((src, i) => ({ src, src_idx: 0, dst: BIN_ID, dst_idx: i })),
    layout: {
      s0: { x: 100, y: 80 },
      s1: { x: 100, y: 180 },
      s2: { x: 100, y: 280 },
      [BIN_ID]: { x: 320, y: 160 },
    },
  };
}

/** 自動保存されたモデル。 */
function savedModel(): SavedModel {
  return JSON.parse(readFileSync(path.join(WORKSPACE, MODEL_FILENAME), "utf-8")) as SavedModel;
}

/** 保存されたモデルの、行エディタのブロックの入力への配線 (``src->dst_idx``、整列済み)。 */
function savedWires(): string[] {
  return savedModel()
    .connections.filter((c) => c.dst === BIN_ID)
    .map((c) => `${c.src}->${c.dst_idx}`)
    .sort();
}

/** 保存されたモデルの行。 */
function savedRows(param: string): unknown {
  return savedModel().blocks.find((b) => b.id === BIN_ID)?.params[param];
}

async function shot(page: Page, name: string): Promise<void> {
  if (SHOT_DIR === "") return;
  await page.screenshot({ path: path.join(SHOT_DIR, name) });
}

/**
 * 追加ダイアログで OK できる状態にする。ブロックの form の中身は fixture 次第なので、
 * 既定値のまま OK できなければ、pick の候補の先頭を選び、空の text 欄に名前を入れる。
 */
async function fillAddDialog(dialog: Locator): Promise<void> {
  const ok = dialog.getByTestId("param-row-dialog-ok");
  await expect(dialog.getByTestId("param-row-dialog-loading")).toHaveCount(0, { timeout: 30_000 });
  const settled = async (): Promise<boolean> => {
    try {
      await expect(ok).toBeEnabled({ timeout: 3_000 });
      return true;
    } catch {
      return false;
    }
  };
  if (await settled()) return;
  const queries = dialog.locator("[data-testid^='param-row-pick-'][data-testid$='-query']");
  for (let i = 0; i < (await queries.count()); i += 1) {
    const query = queries.nth(i);
    const testId = (await query.getAttribute("data-testid")) ?? "";
    const rows = dialog.getByTestId(testId.replace(/-query$/, "-table-row"));
    for (const q of QUERY_CANDIDATES) {
      await query.fill(q);
      try {
        await expect(rows.first()).toBeVisible({ timeout: 5_000 });
        await rows.first().click();
        break;
      } catch {
        // 次の検索語
      }
    }
  }
  if (await settled()) return;
  const texts = dialog.locator("input[type='text'][data-testid^='param-row-field-']");
  for (let i = 0; i < (await texts.count()); i += 1) {
    const input = texts.nth(i);
    if ((await input.inputValue()) === "") await input.fill(`e2e${i}`);
  }
  await expect(ok).toBeEnabled({ timeout: 30_000 });
}

test.describe("Parameter row editor (ADR-0086)", () => {
  let typePath = "";
  let param = "";
  let rows: string[] = [];

  test.beforeAll(async ({ playwright }) => {
    // 起動時点の .workspace/ に fixture が無いことがあるので、API で読み込み直してから探す
    const api = await playwright.request.newContext({ baseURL: BACKEND_URL });
    await api.post("/api/v1/blocks/reload", { data: {} });
    const target = await findRowEditorBlock(api);
    expect(target, "e2e_blocks.py must define a dynamic-ports block with block_param_rows").toBeDefined();
    typePath = target!.typePath;
    param = target!.param;
    rows = await initialRows(api, typePath, param, target!.searchable);
    await api.dispose();
    writeFileSync(
      path.join(WORKSPACE, MODEL_FILENAME),
      JSON.stringify(rowsModel(typePath, param, rows), null, 2),
      "utf-8",
    );
  });

  test.afterAll(async ({ playwright }) => {
    rmSync(path.join(WORKSPACE, MODEL_FILENAME), { force: true });
    const api = await playwright.request.newContext({ baseURL: BACKEND_URL });
    await api.post("/api/v1/blocks/reload", { data: {} });
    await api.dispose();
  });

  test("add grows the ports, deleting a wired middle row keeps wires on their rows, undo restores", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/");
    await page.getByText(MODEL_FILENAME).click({ timeout: 15_000 });
    const libraryTab = page.getByTestId("activity-bar-library");
    if ((await libraryTab.getAttribute("aria-selected")) !== "true") {
      await libraryTab.click();
    }
    const refetched = page.waitForResponse(
      (r) => r.request().method() === "GET" && /\/api\/v1\/blocks(\?|$)/.test(r.url()),
    );
    await page.getByTestId("palette-menu-button").click();
    await page.getByTestId("palette-menu-reload").click();
    await refetched;

    const node = page.locator(`.react-flow__node[data-id='${BIN_ID}']`);
    const inputs = node.locator(".react-flow__handle.target");
    await expect(inputs).toHaveCount(SOURCES.length, { timeout: 15_000 });
    await node.click();
    const table = page.getByTestId(`param-rows-${param}-table`);
    await expect(table).toBeVisible({ timeout: 15_000 });
    // 行エディタの引数には「探す…」を出さない
    await expect(page.getByTestId(`param-search-${param}`)).toHaveCount(0);
    const tableRows = page.getByTestId(`param-rows-${param}-table-row`);
    await expect(tableRows).toHaveCount(SOURCES.length);
    await shot(page, "param_rows_table.png");

    // 1. 追加: ダイアログで 1 行組み立てて OK → 入力ポートが 1 つ増え、配線は変わらない
    await page.getByTestId(`param-rows-${param}-add`).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await fillAddDialog(dialog);
    await shot(page, "param_rows_dialog.png");
    await dialog.getByTestId("param-row-dialog-ok").click();
    await expect(dialog).toHaveCount(0);
    await expect(tableRows).toHaveCount(SOURCES.length + 1, { timeout: 15_000 });
    await expect(inputs).toHaveCount(SOURCES.length + 1, { timeout: 15_000 });
    await expect
      .poll(() => (savedRows(param) as unknown[] | undefined)?.length, { timeout: 15_000 })
      .toBe(SOURCES.length + 1);
    expect(savedWires()).toEqual(["s0->0", "s1->1", "s2->2"]);

    // 2. 配線のある途中の行 (1) を削除 → その配線が消え、後ろの行の配線は同じ行に付いたまま
    const addButton = page.getByTestId(`param-rows-${param}-add`);
    await expect(addButton).toBeEnabled({ timeout: 15_000 });
    await tableRows.nth(1).click();
    await page.getByTestId(`param-rows-${param}-delete`).click();
    await expect(tableRows).toHaveCount(SOURCES.length, { timeout: 15_000 });
    await expect(inputs).toHaveCount(SOURCES.length, { timeout: 15_000 });
    await expect.poll(savedWires, { timeout: 15_000 }).toEqual(["s0->0", "s2->1"]);
    const afterDelete = savedRows(param) as string[];
    expect(afterDelete[0]).toBe(rows[0]);
    expect(afterDelete[1]).toBe(rows[2]);
    await shot(page, "param_rows_deleted.png");

    // 3. Undo 1 回で引数と配線が同時に戻る
    await expect(addButton).toBeEnabled({ timeout: 15_000 });
    await page.locator("button[title^='Undo'], button[title^='元に戻す']").click();
    await expect(tableRows).toHaveCount(SOURCES.length + 1, { timeout: 15_000 });
    await expect(inputs).toHaveCount(SOURCES.length + 1, { timeout: 15_000 });
    await expect.poll(savedWires, { timeout: 15_000 }).toEqual(["s0->0", "s1->1", "s2->2"]);
    expect((savedRows(param) as string[]).slice(0, SOURCES.length)).toEqual(rows);
  });
});
