import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { readPortEnv } from "./tests/e2e/ports";

// ADR-0019 code-reviewer SHOULD: package.json から version を読み込んで
// `__APP_VERSION__` として注入する (フロント側のハードコードを排除)。
const __dirname = dirname(fileURLToPath(import.meta.url));
const pkg = JSON.parse(
  readFileSync(resolve(__dirname, "package.json"), "utf-8"),
) as { version: string };

// ADR-0012 §(7): dev server (port 5173) → backend (port 8770) を proxy で接続。
// production build は FastAPI が静的配信するため同一オリジン。
// E2E_BACKEND_PORT / E2E_FRONTEND_PORT (playwright.config.ts と共通) で上書き可 —
// 開発用サーバーが 8770 を占有していてもローカル E2E を別ポートで回せる。
const backendPort = readPortEnv("E2E_BACKEND_PORT", 8770);
const frontendPort = readPortEnv("E2E_FRONTEND_PORT", 5173);

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  server: {
    port: frontendPort,
    proxy: {
      "/api": {
        target: `http://localhost:${backendPort}`,
        // changeOrigin は付けない: Host を backend 側に書き換えると、backend の
        // CSRF guard (flode/server/security/origin.py) がブラウザの Origin
        // (dev server 側) と Host の不一致を cross-origin とみなし、書き込み系
        // API を 403 で拒否する。Host をそのまま転送すれば Origin == Host の
        // same-origin (loopback = unspoofable) として許可される。
        // 注意 1: string 省略記法 (`"/api": "http://..."`) は Vite が
        // changeOrigin: true を暗黙付与するため使用禁止 (403 全滅が再発する)。
        // 注意 2: dev server は loopback bind 前提。`--host` で LAN 公開すると
        // 同一 LAN からの書き込みが Origin == Host (IP リテラル) で許可される
        // ため使わないこと。
        ws: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
