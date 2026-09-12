import { cpSync, mkdirSync, rmSync } from "node:fs";
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

export default function globalSetup(): void {
  rmSync(E2E_WORKSPACE_DIR, { recursive: true, force: true });
  mkdirSync(E2E_WORKSPACE_DIR, { recursive: true });
  cpSync(FIXTURES_DIR, E2E_WORKSPACE_DIR, { recursive: true });
}
