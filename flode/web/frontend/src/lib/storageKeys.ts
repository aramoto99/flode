// ADR-0045 §(3) localStorage 永続化キーの共通ヘルパー。
//
// 複数の永続化機能 (= ADR-0044 floating Scope panel / ADR-0045 multi-pane
// workspace layout) が **同じ key prefix 規約** で動くよう、b64url エンコード +
// key 生成関数をここに集約する。
//
// 慣例 (= `flode.<feature>.<workspace_hash>.<base64url(model_path)>[.<...>]`):
// - prefix `flode.` は ADR-0024 (i18n localStorage) と同じ dot 区切り
// - `<workspace_hash>` は ADR-0043 `getWorkspaceInfo()` から得るワークスペース
//   絶対パスの SHA hash (= 別ワークスペースで key 衝突を防ぐ)
// - `<base64url(model_path)>` はワークスペース root からの相対パスを base64url
//   エンコード (= `/` や `.` を含む path をキーに使うため)

/** ASCII 範囲外 (= 多バイト UTF-8) を許容する base64url エンコード。
 * - 通常の ``btoa`` は Latin-1 (= 0-255) しか受け付けないので、UTF-8 を経由する
 * - 出力は ``+`` → ``-``、``/`` → ``_``、末尾 ``=`` 削除 (= URL-safe Base64) */
export function b64urlEncode(input: string): string {
  // TextEncoder で UTF-8 byte stream に変換 → Latin-1 文字列 → btoa
  const bytes = new TextEncoder().encode(input);
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/** ADR-0045 §(3-B): Workspace layout (= SplitTree) 永続化キー。
 *
 * フォーマット: ``flode.workspace_layout.<workspaceHash>.<b64url(modelPath)>``
 *
 * @param workspaceHash 現在のワークスペース hash (= ``store.workspaceHash``、
 *                      ADR-0043 §論点 1-A で workspace 絶対パス由来の SHA hash)
 * @param modelPath     現在開いているモデルのワークスペース root からの相対パス
 *                      (= ``store.activeTabFilePath``、ADR-0041 §論点 4-A)
 */
export function makeWorkspaceLayoutKey(
  workspaceHash: string,
  modelPath: string,
): string {
  return `flode.workspace_layout.${workspaceHash}.${b64urlEncode(modelPath)}`;
}

/** ADR-0044 §論点 6-A: 旧 ``ScopePanelContainer.tsx`` から共通化した floating
 * Scope panel の geometry 永続化キー。
 *
 * フォーマット: ``flode.scope_panel.<workspaceHash>.<b64url(modelPath)>.<scopeId>``
 *
 * @param workspaceHash 現在のワークスペース hash (= ``store.workspaceHash``)
 * @param modelPath     現在開いているモデルのワークスペース root からの相対パス
 *                      (= ``store.activeTabFilePath``)
 * @param scopeId       Scope ブロックの id
 */
export function makeScopePanelKey(
  workspaceHash: string,
  modelPath: string,
  scopeId: string,
): string {
  return `flode.scope_panel.${workspaceHash}.${b64urlEncode(modelPath)}.${scopeId}`;
}
