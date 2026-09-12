import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";

import { readPortEnv } from "./tests/e2e/ports";

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
// backend に渡す workspace は git 管理の fixtures/ そのものではなく、
// globalSetup (tests/e2e/global-setup.ts) が毎回作り直す使い捨てコピー
// .workspace/ (gitignore 済み)。GUI が legacy モデルを開くと migration 済み
// 内容を auto-save するため、直接 fixtures/ を配信すると git が汚れる。
const WORKSPACE_DIR = path.join(
  "flode", "web", "frontend", "tests", "e2e", ".workspace",
);
// Playwright は webServer を globalSetup より先に起動するため、backend の
// --workspace 検証が通るようディレクトリ自体はここで確保しておく
// (mkdirSync recursive は既存なら no-op なので worker の config 再評価でも安全)。
// fixtures の複製・入れ替えは globalSetup が行う (テスト開始前に完了する)。
mkdirSync(path.join(REPO_ROOT, WORKSPACE_DIR), { recursive: true });

// 環境変数で上書き可 (vite.config.ts の proxy 先と連動)。開発用サーバーが
// 8770 を占有していてもローカル E2E を別ポートで実行できる
const E2E_BACKEND_PORT = readPortEnv("E2E_BACKEND_PORT", 8770);
const E2E_FRONTEND_PORT = readPortEnv("E2E_FRONTEND_PORT", 5173);

export default defineConfig({
  testDir: "./tests/e2e",
  globalSetup: "./tests/e2e/global-setup.ts",
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
      command: `python -m flode.server.cli --workspace ${WORKSPACE_DIR} --port ${E2E_BACKEND_PORT}`,
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
