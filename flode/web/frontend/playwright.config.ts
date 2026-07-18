import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";

// E2E テスト構成 (ADR-0012 §(7) Vite dev server + ADR-0011 FastAPI backend)。
// Backend (flode) と Vite dev server を webServer で並列に起動する。
//
// ローカル実行:
//   npm run e2e:install   # 初回のみ Playwright ブラウザを取得
//   npm run e2e
//
// CI 実行は ci-frontend.yml の e2e job で行う。

// 本ファイルからリポジトリルートへの絶対パスを計算する。Playwright の
// `webServer.cwd` はプロセスの cwd 相対で解釈されるため、`npm run e2e` 以外の
// 経路 (例: repo root から `npx playwright test flode/web/frontend/...`) で
// 起動された場合でも壊れないように絶対パスで指定する。
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "../../..");
const FIXTURES_DIR = path.join("flode", "web", "frontend", "tests", "e2e", "fixtures");

const E2E_BACKEND_PORT = 8770;
const E2E_FRONTEND_PORT = 5173;

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: /.*\.spec\.ts$/,
  // E2E は per-spec で隔離するため並列度を抑える (1 backend instance を共有)
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: process.env.CI ? "github" : [["list"]],

  use: {
    baseURL: `http://127.0.0.1:${E2E_FRONTEND_PORT}`,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },

  // Backend と Frontend dev server を並列起動
  // Playwright が両方の port を待ってから spec を流し込む
  webServer: [
    {
      // flode FastAPI backend (port 8770)。Python 環境に flode がインストール済み
      // (例: `pip install -e .`、v0.44.0 で GUI サーバー依存は core に統合) であること。
      // ``flode`` console script が PATH に通っていない環境でも動くよう
      // ``python -m flode.server.cli`` で起動する。``cwd`` は本ファイルからの
      // 絶対パスでリポジトリルートに固定 (process cwd 依存をなくす)。
      // v0.21.0 (ADR-0041 §論点 4-A): ``--model-dir`` 廃止 → ``--workspace``。
      // health check URL も legacy ``/api/v1/models`` から
      // ``/api/v1/files/workspace_info`` (= ADR-0043 §論点 1-A) に切替。
      command: `python -m flode.server.cli --workspace ${FIXTURES_DIR} --port ${E2E_BACKEND_PORT}`,
      cwd: REPO_ROOT,
      url: `http://127.0.0.1:${E2E_BACKEND_PORT}/api/v1/files/workspace_info`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      // Vite dev server (5173)。`/api/*` と WebSocket を 8770 にプロキシ (vite.config.ts)。
      // ``--host 127.0.0.1`` で IPv4 にバインドさせる: Vite default の `localhost` は
      // Windows で IPv6 (`[::1]`) のみになるケースがあり、Playwright の IPv4 health
      // check が通らないため。
      command: `npm run dev -- --host 127.0.0.1 --port ${E2E_FRONTEND_PORT}`,
      url: `http://127.0.0.1:${E2E_FRONTEND_PORT}`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
