/**
 * E2E 用ポート環境変数の共通解決 (vite.config.ts / playwright.config.ts で共有)。
 *
 * 未設定・空文字は既定値に落とし、それ以外は有効なポート番号 (1-65535) で
 * あることを検証する。誤設定 (typo 等) を `http://localhost:NaN` のような
 * 原因不明の E2E 失敗にせず、config 評価時に即座に fail させるのが目的。
 *
 * @param name - 環境変数名 (例: "E2E_BACKEND_PORT")
 * @param fallback - 未設定・空文字時の既定ポート
 * @returns 解決されたポート番号
 * @throws Error 値がポート番号として不正な場合
 */
export function readPortEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (raw === undefined || raw === "") {
    return fallback;
  }
  const port = Number(raw);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`${name} must be a port number (1-65535), got: ${raw}`);
  }
  return port;
}
