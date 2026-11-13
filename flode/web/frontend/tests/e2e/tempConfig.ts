/**
 * E2E 用の backend 設定ファイル (実行ごとの一時ディレクトリ)。
 *
 * backend は `--config` を省略すると開発者の `~/.flode/config.toml` を読む
 * (SPEC-0004)。そこに `[blocks]` (ADR-0081) や `[server]` の設定があると E2E の結果が
 * 開発者の環境に左右されるため、実行ごとに OS の一時ディレクトリへ空の
 * `config.toml` を作り、`--config` で渡す。実ホームの `~/.flode` は読みも書きもしない。
 *
 * playwright.config.ts は main プロセスと各 worker で評価されるため、作ったディレクトリは
 * 環境変数で受け渡して 1 実行 1 つにする (worker は main の環境変数を引き継ぐ)。
 */
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";

/** 一時ディレクトリの basename 接頭辞。削除はこの接頭辞のものだけに限る。 */
export const TEMP_CONFIG_PREFIX = "flode-e2e-config-";
/** main → worker へ一時ディレクトリを渡す環境変数。 */
const TEMP_CONFIG_ENV = "FLODE_E2E_CONFIG_DIR";
const CONFIG_FILENAME = "config.toml";
const CONFIG_CONTENT =
  "# flode E2E: empty config so that the developer's ~/.flode/config.toml is not read.\n";

/**
 * `dir` が「OS の一時ディレクトリ直下」かつ「basename が決まった接頭辞」か。
 *
 * @param dir - 判定するパス。
 * @returns 両方を満たすときだけ true (それ以外は作成・削除の対象にしない)。
 */
export function isOwnTempConfigDir(dir: string): boolean {
  const resolved = path.resolve(dir);
  return (
    path.dirname(resolved) === path.resolve(os.tmpdir()) &&
    path.basename(resolved).startsWith(TEMP_CONFIG_PREFIX)
  );
}

/**
 * 一時 config ファイルを用意してパスを返す (同じ実行の 2 回目以降は同じファイル)。
 *
 * @returns `config.toml` の絶対パス。
 */
export function ensureTempConfigFile(): string {
  const inherited = process.env[TEMP_CONFIG_ENV];
  const dir =
    inherited !== undefined && inherited !== "" && isOwnTempConfigDir(inherited)
      ? inherited
      : mkdtempSync(path.join(os.tmpdir(), TEMP_CONFIG_PREFIX));
  process.env[TEMP_CONFIG_ENV] = dir;
  mkdirSync(dir, { recursive: true });
  const file = path.join(dir, CONFIG_FILENAME);
  writeFileSync(file, CONFIG_CONTENT, "utf-8");
  return file;
}

/** 一時 config ディレクトリを削除する (`isOwnTempConfigDir` を満たすときだけ)。 */
export function removeTempConfigDir(): void {
  const dir = process.env[TEMP_CONFIG_ENV];
  if (dir === undefined || dir === "" || !isOwnTempConfigDir(dir)) return;
  rmSync(dir, { recursive: true, force: true });
}
