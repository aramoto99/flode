import { defineConfig } from "vitest/config";

// Vitest 専用設定。Playwright E2E (tests/e2e/**) は ``npm run e2e`` で別ランナーが
// 走らせるため、Vitest からは除外する。これがないと Playwright の ``test.describe``
// 呼び出しを Vitest が拾って "did not expect test.describe()" エラーで失敗する。
export default defineConfig({
  test: {
    // jsdom: ADR-0023 で UPlotChart の mount / unmount テストに DOM 環境が必要。
    // pure-logic テスト (= scopeBuffer 等) も jsdom 上で問題なく動く。
    environment: "jsdom",
    setupFiles: ["./tests/vitest.setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    exclude: ["node_modules", "dist", "tests/e2e/**"],
  },
});
