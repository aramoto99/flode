// ADR-0043 §論点 4: Recent Files の localStorage 永続化。
//
// localStorage キー: ``flode.recent.<workspace_root_hash>`` (= workspace ごとに別 entry)。
// hash は backend ``GET /api/v1/files/workspace_info`` の ``hash`` をそのまま使う
// (= sha256 16 文字)。値は file path の文字列配列、最新 (= 最後にアクセス) が
// 配列 index 0、古い順に index N-1。上限 10 件で打ち切り。

const KEY_PREFIX = "flode.recent.";
const MAX_RECENT = 10;

/**
 * localStorage から workspace の Recent Files 配列を読む。stale prune は
 * 別途 ``pruneRecentFiles`` で実施 (= startup タイミング)。
 *
 * @param workspaceHash backend ``workspace_info.hash``
 * @returns 最新が先頭、古い順の配列。読めなければ空配列。
 */
export function readRecentFiles(workspaceHash: string): string[] {
  if (!workspaceHash) return [];
  try {
    const raw = window.localStorage.getItem(KEY_PREFIX + workspaceHash);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    // 防御的: 文字列以外を除外、上限で truncate
    return parsed
      .filter((x): x is string => typeof x === "string")
      .slice(0, MAX_RECENT);
  } catch {
    return [];
  }
}

/**
 * 配列を localStorage に書き戻す。配列長は ``MAX_RECENT`` で truncate。
 */
function writeRecentFiles(workspaceHash: string, paths: string[]): void {
  if (!workspaceHash) return;
  try {
    const truncated = paths.slice(0, MAX_RECENT);
    window.localStorage.setItem(
      KEY_PREFIX + workspaceHash,
      JSON.stringify(truncated),
    );
  } catch {
    // localStorage quota / private mode 等は黙って失敗
  }
}

/**
 * Recent Files に path を追加 (= 既存なら先頭に move-to-front、なければ先頭追加)。
 * 上限を超えた古い entry は drop。
 */
export function addRecentFile(workspaceHash: string, path: string): void {
  if (!workspaceHash || !path) return;
  const current = readRecentFiles(workspaceHash);
  const filtered = current.filter((p) => p !== path);
  filtered.unshift(path);
  writeRecentFiles(workspaceHash, filtered);
}

/**
 * 単一 entry を削除。
 */
export function removeRecentFile(workspaceHash: string, path: string): void {
  if (!workspaceHash) return;
  const current = readRecentFiles(workspaceHash);
  writeRecentFiles(
    workspaceHash,
    current.filter((p) => p !== path),
  );
}

/**
 * Recent Files を全削除。
 */
export function clearRecentFiles(workspaceHash: string): void {
  if (!workspaceHash) return;
  try {
    window.localStorage.removeItem(KEY_PREFIX + workspaceHash);
  } catch {
    // 黙って失敗
  }
}

/**
 * ADR-0043 §論点 4-A: stale (= 削除済 / rename 済) entry を prune する。
 * ``existsCheck(path)`` を各 path に対して実行し、false を返した entry を除外。
 * Promise.all で並列 fetch。
 *
 * 通常 startup 時に呼ばれる。
 */
export async function pruneRecentFiles(
  workspaceHash: string,
  existsCheck: (path: string) => Promise<boolean>,
): Promise<void> {
  const current = readRecentFiles(workspaceHash);
  if (current.length === 0) return;
  const results = await Promise.all(current.map(existsCheck));
  const survived = current.filter((_, i) => results[i] === true);
  if (survived.length !== current.length) {
    writeRecentFiles(workspaceHash, survived);
  }
}
