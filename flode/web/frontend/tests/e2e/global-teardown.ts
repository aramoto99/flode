import { removeTempConfigDir } from "./tempConfig";

/**
 * E2E global teardown: playwright.config.ts が作った一時 config ディレクトリを消す
 * (OS の一時ディレクトリ直下かつ決まった接頭辞のときだけ、tempConfig.ts 参照)。
 */
export default function globalTeardown(): void {
  removeTempConfigDir();
}
