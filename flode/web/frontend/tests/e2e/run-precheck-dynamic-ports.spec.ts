import { rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type Page, type Request, type Route } from "@playwright/test";

import { readPortEnv } from "./ports";

// 回帰テスト (bug-report 2026-11-19-run-precheck-unresolved-dynamic-ports):
// 引数でポート数が変わるユーザーブロック (block_dynamic_ports) を含むモデルを開いた直後、
// ポートの解決 (POST /api/v1/blocks/resolve-port-shapes) の応答前に実行すると、registry の
// 既定のポート数と比べて「ブロックに無いポートへの配線があります」と誤って起動失敗にしていた。
// - 解決前は配線を超過 (赤) と描かず、Inspector にも警告を出さない
// - 実行は解決を待ってから実行前チェックする (本当に超過していれば、解決後にその配線で止まる)
// - 解決が通信失敗なら判定を飛ばして backend に任せる (backend は ModelLoadError で拒否する)
//
// 題材は fixtures/blocks/e2e_blocks.py の E2ePartsBin (``parts`` の行ごとに入力ポート、既定は 0 本)。

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WORKSPACE = path.join(__dirname, ".workspace");
const BACKEND_URL = `http://127.0.0.1:${readPortEnv("E2E_BACKEND_PORT", 8770)}`;
const BIN_TYPE = "flode_ws.e2e_blocks.E2ePartsBin";
const VALID_MODEL = "precheck_dynamic_valid.flw.json";
const EXCESS_MODEL = "precheck_dynamic_excess.flw.json";
const RESOLVE_URL = "**/api/v1/blocks/resolve-port-shapes";
/** 超過ポートの配線のエラー色 (``EXCESS_PORT_STROKE`` = #e11d48、style 属性では rgb 表記)。 */
const EXCESS_STROKE = "rgb(225, 29, 72)";

/** 2 つの定数 → bin の in[0] / in[1] → Scope。``parts`` の行数が bin の入力ポート数。 */
function model(parts: string[]): Record<string, unknown> {
  return {
    schema_version: "0.15",
    metadata: { tool: "flode e2e (run precheck with unresolved dynamic ports)" },
    simulator: { t_end: 0.1, dt: 0.01, solver: "RK45", rtol: 1e-6, atol: 1e-9, dt_base: null },
    blocks: [
      { id: "c0", type: "flode.blocks.sources.Constant", params: { value: 1.0 } },
      { id: "c1", type: "flode.blocks.sources.Constant", params: { value: 2.0 } },
      { id: "bin", type: BIN_TYPE, params: { parts } },
      { id: "sc", type: "flode.blocks.sinks.Scope", params: { n_inputs: 1 } },
    ],
    connections: [
      { src: "c0", src_idx: 0, dst: "bin", dst_idx: 0 },
      { src: "c1", src_idx: 0, dst: "bin", dst_idx: 1 },
      { src: "bin", src_idx: 0, dst: "sc", dst_idx: 0 },
    ],
    layout: {
      c0: { x: 60, y: 60 },
      c1: { x: 60, y: 160 },
      bin: { x: 240, y: 90 },
      sc: { x: 420, y: 100 },
    },
  };
}

const isResolveRequest = (r: Request): boolean =>
  r.url().includes("/api/v1/blocks/resolve-port-shapes");
const isStartRequest = (r: Request): boolean =>
  r.method() === "POST" && /\/api\/v1\/simulations(\?|\/start|$)/.test(r.url());

/** モデルを開き、ポートの問い合わせが出るまで待つ (どちらかの失敗を取りこぼさないよう Promise.all)。 */
async function openModelAndWaitForPortRequest(page: Page, filename: string): Promise<void> {
  await page.setViewportSize({ width: 1280, height: 860 });
  await page.goto("/");
  await Promise.all([
    page.waitForRequest(isResolveRequest, { timeout: 15_000 }),
    (async () => {
      await page.getByRole("button", { name: filename, exact: true }).click({ timeout: 15_000 });
      await expect(
        page.locator(".react-flow__node[data-id='bin'] [data-user-block]"),
      ).toHaveAttribute("data-user-block", "user", { timeout: 15_000 });
    })(),
  ]);
}

async function runSimulation(page: Page): Promise<void> {
  await page
    .locator("button[title^='Run Simulation'], button[title^='シミュレーション実行']")
    .click();
}

/** ポートの問い合わせを保留する (応答が遅いサーバ)。``release`` で通す。 */
async function holdPortRequests(page: Page): Promise<{ held: Route[]; release: () => void }> {
  let release: () => void = () => {};
  const gate = new Promise<void>((r) => {
    release = r;
  });
  const held: Route[] = [];
  await page.route(RESOLVE_URL, async (route) => {
    held.push(route);
    await gate;
    await route.continue().catch(() => {});
  });
  return { held, release };
}

const status = (page: Page) => page.getByTestId("simulation-status");
const excessEdges = (page: Page) =>
  page.locator(`.react-flow__edge-path[style*='${EXCESS_STROKE}']`);

test.describe("Run precheck with unresolved dynamic ports", () => {
  test.beforeAll(async ({ playwright }) => {
    writeFileSync(
      path.join(WORKSPACE, VALID_MODEL),
      JSON.stringify(model(["a: resistor", "b: capacitor"]), null, 2),
    );
    writeFileSync(path.join(WORKSPACE, EXCESS_MODEL), JSON.stringify(model(["a: resistor"]), null, 2));
    // 起動時点の .workspace/ に fixture の blocks/ が無いことがあるので、読み込み直す
    const api = await playwright.request.newContext({ baseURL: BACKEND_URL });
    await api.post("/api/v1/blocks/reload", { data: {} });
    await api.dispose();
  });

  test.afterAll(() => {
    for (const f of [VALID_MODEL, EXCESS_MODEL]) rmSync(path.join(WORKSPACE, f), { force: true });
  });

  test("running before the ports are resolved waits for them, then runs", async ({ page }) => {
    const { held, release } = await holdPortRequests(page);
    const starts: Request[] = [];
    page.on("request", (r) => {
      if (isStartRequest(r)) starts.push(r);
    });
    try {
      await openModelAndWaitForPortRequest(page, VALID_MODEL);
      await expect.poll(() => held.length).toBeGreaterThan(0);

      // 未解決の間は配線を超過 (赤) と描かず、Inspector にも警告を出さない
      await expect(excessEdges(page)).toHaveCount(0);
      await page.locator(".react-flow__node[data-id='bin']").click();
      await expect(page.getByTestId("parameter-panel")).toBeVisible();
      await expect(page.getByTestId("param-excess-ports")).toHaveCount(0);

      // 応答前に押すと、実行は応答を待つ (止めない・まだ開始要求を送らない)。「起きないこと」の
      // 確認なので、しばらく見続ける (待機中は idle = 状態表示が出ない)
      await runSimulation(page);
      for (let i = 0; i < 5; i++) {
        await expect(status(page)).toHaveCount(0);
        expect(starts).toHaveLength(0);
        await page.evaluate(() => new Promise((r) => setTimeout(r, 100)));
      }

      // 応答が届くと実行前チェックを通って実行される
      release();
      await expect(status(page)).toHaveAttribute("data-status", "completed", { timeout: 30_000 });
      expect(starts.length).toBeGreaterThan(0);
    } finally {
      release();
    }
  });

  test("a really-excess model pressed before the response stops with the port once resolved", async ({
    page,
  }) => {
    const { held, release } = await holdPortRequests(page);
    try {
      await openModelAndWaitForPortRequest(page, EXCESS_MODEL);
      await expect.poll(() => held.length).toBeGreaterThan(0);
      await expect(excessEdges(page)).toHaveCount(0);
      await runSimulation(page);
      release();
      // 解決後 (入力 1 本) に実行前チェックで止まる: 整形メッセージに配線のポート
      await expect(status(page)).toHaveAttribute("data-status", "failed", { timeout: 15_000 });
      await expect(page.getByRole("alert").filter({ hasText: "bin.in[1]" }).first()).toBeVisible();
      await expect(excessEdges(page)).toHaveCount(1);
    } finally {
      release();
    }
  });

  test("ports that really are fewer stop the run after they are resolved", async ({ page }) => {
    await openModelAndWaitForPortRequest(page, EXCESS_MODEL);
    // 解決後 (入力 1 本) は in[1] の配線を超過として赤く描く
    await expect(excessEdges(page)).toHaveCount(1, { timeout: 15_000 });
    await runSimulation(page);
    await expect(status(page)).toHaveAttribute("data-status", "failed", { timeout: 15_000 });
    await expect(page.getByRole("alert").filter({ hasText: "bin.in[1]" }).first()).toBeVisible();
  });

  test("a failed port request does not fail the precheck (the backend checks the model)", async ({
    page,
  }) => {
    await page.route(RESOLVE_URL, (route) => route.abort("failed"));
    await openModelAndWaitForPortRequest(page, VALID_MODEL);
    await expect(excessEdges(page)).toHaveCount(0);
    await runSimulation(page);
    await expect(status(page)).toHaveAttribute("data-status", "completed", { timeout: 30_000 });
  });

  test("a failed port request leaves a really-excess model to the backend's check", async ({ page }) => {
    await page.route(RESOLVE_URL, (route) => route.abort("failed"));
    await openModelAndWaitForPortRequest(page, EXCESS_MODEL);
    await runSimulation(page);
    // 実行前チェックでは止めないが、backend がモデルの読み込みで拒否する
    await expect(status(page)).toHaveAttribute("data-status", "failed", { timeout: 30_000 });
  });
});
