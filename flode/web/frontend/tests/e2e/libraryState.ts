import path from "node:path";

/**
 * E2E 用ユーザーライブラリの置き場に置く「目印ライブラリ」の名前
 * (playwright.config.ts が書き、spec が backend の一覧で確かめる)。
 *
 * 一時ディレクトリ名 (実行ごとに一意) から決めるので、別の実行・別設定で起動した
 * backend を掴んだ場合は一致しない。
 *
 * @param stateDir - 実行ごとの一時ディレクトリ (環境変数 FLODE_E2E_STATE_DIR)
 * @returns ライブラリ名 (英小文字・数字・ハイフンのみ)
 */
export function e2eMarkerLibraryName(stateDir: string): string {
  const slug = path
    .basename(stateDir)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-");
  return `e2e-marker-${slug}`;
}
