// Blob をファイルとしてブラウザに保存させる共通処理 (ライブラリの書き出し、
// グラフ画像の保存 fallback)。

/** object URL を解放するまでの猶予 (ms)。``click()`` 直後に解放すると、ブラウザに
 *  よってはダウンロードが始まる前に URL が無効になる。 */
const REVOKE_DELAY_MS = 1000;

/**
 * ``blob`` を ``filename`` という名前でダウンロードさせる。
 *
 * アンカーは一時的に ``document.body`` に付けてから click する (document に属さない
 * アンカーの click を無視するブラウザがあるため)。
 *
 * @param blob 保存する内容。
 * @param filename 保存時のファイル名。
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS);
}
