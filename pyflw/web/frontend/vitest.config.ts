import { defineConfig } from "vitest/config";

// Vitest 専用設定。Playwright E2E (tests/e2e/**) は ``npm run e2e`` で別ランナーが
// 走らせるため、Vitest からは除外する。これがないと Playwright の ``test.describe``
// 呼び出しを Vitest が拾って "did not expect test.describe()" エラーで失敗する。
export default defineConfig({
  test: {
    include: ["tests/**/*.test.{ts,tsx}"],
    exclude: ["node_modules", "dist", "tests/e2e/**"],
  },
});
