import { cpSync, mkdirSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

// E2E global setup: git 管理の fixtures を使い捨ての作業コピー (.workspace/,
// gitignore 済み) へ複製する。backend はこのコピーを --workspace として配信する。
//
// 背景: GUI は legacy schema のモデルを開いただけで migration 済み内容を
// auto-save (PUT) するため、fixtures を直接 workspace にすると spec が編集を
// しなくても git 管理ファイルが書き換わってしまう。テストは作業コピーだけを
// 汚し、毎回の実行開始時にここで作り直す。
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIXTURES_DIR = path.join(__dirname, "fixtures");
export const E2E_WORKSPACE_DIR = path.join(__dirname, ".workspace");

export default function globalSetup(): () => void {
  rmSync(E2E_WORKSPACE_DIR, { recursive: true, force: true });
  mkdirSync(E2E_WORKSPACE_DIR, { recursive: true });
  cpSync(FIXTURES_DIR, E2E_WORKSPACE_DIR, { recursive: true });
  // teardown: playwright.config.ts が作った実行ごとの一時ディレクトリ (backend の
  // config.toml とユーザーライブラリの置き場、ADR-0080) を片付ける。消せなくても
  // (backend がまだファイルを掴んでいる等) OS の一時領域なのでテストは失敗させない。
  return () => {
    const stateDir = process.env.FLODE_E2E_STATE_DIR;
    if (!stateDir) return;
    // 再帰削除するのは、playwright.config.ts が作る形 (OS の一時ディレクトリ直下の
    // ``flode-e2e-*``) のときだけ。環境変数が外から別の場所に向けられていても消さない
    const resolved = path.resolve(stateDir);
    const insideTmp = path.dirname(resolved) === path.resolve(os.tmpdir());
    if (!insideTmp || !path.basename(resolved).startsWith("flode-e2e-")) return;
    try {
      rmSync(resolved, { recursive: true, force: true });
    } catch {
      // 残っても無害 (OS の一時ディレクトリ)
    }
  };
}
