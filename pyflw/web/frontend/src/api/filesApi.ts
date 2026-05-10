// ADR-0041 §論点 1-A: File API client (= /api/v1/files/*)。
// JupyterLab 互換の 6 endpoint を呼び出すラッパー。Path traversal 防御は backend
// (= pyflw/server/security/paths.py) に集約、frontend は単純に POSIX path を
// encodeURIComponent して送るだけ。

import type { FlwModel } from "../types/api";

const API_BASE = "/api/v1/files";

export type FileEntryType = "file" | "directory";

export interface FileEntry {
  name: string;
  type: FileEntryType;
  size: number | null;
  mtime: string;
}

export interface FileTreeResponse {
  path: string;
  children: FileEntry[];
}

export interface FileContentResponse {
  path: string;
  content: FlwModel;
  mtime: string;
  etag: string;
}

export interface FilePutResponse {
  path: string;
  mtime: string;
  etag: string;
}

/**
 * 503 (= File API not enabled、legacy `--model-dir` モード) を専用エラーで投げる。
 * frontend は `instanceof FileApiUnavailableError` で legacy フローへ fallback
 * できるようにする。
 */
export class FileApiUnavailableError extends Error {
  constructor() {
    super(
      "File API not enabled. The pyflw-server is running in legacy --model-dir mode. " +
        "Restart with --workspace=PATH (see ADR-0041) to enable workspace browsing.",
    );
    this.name = "FileApiUnavailableError";
  }
}

/**
 * etag mismatch (= 409、外部編集による衝突)。frontend は楽観ロックの再取得を促す。
 * `currentEtag` を保持して再 fetch / 確認モーダルを発火する材料にする。
 */
export class EtagMismatchError extends Error {
  readonly currentEtag: string | undefined;
  constructor(currentEtag: string | undefined) {
    super("etag mismatch — file modified externally");
    this.name = "EtagMismatchError";
    this.currentEtag = currentEtag;
  }
}

async function _fetch<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (response.status === 503) {
    throw new FileApiUnavailableError();
  }
  if (!response.ok) {
    let detail: unknown;
    let body: unknown;
    try {
      body = await response.json();
      detail =
        (body as { error?: { message?: string }; detail?: unknown })?.error
          ?.message ??
        (body as { detail?: unknown })?.detail ??
        response.statusText;
    } catch {
      detail = response.statusText;
    }
    if (response.status === 409 && typeof detail === "object" && detail !== null) {
      const obj = detail as { current_etag?: string };
      throw new EtagMismatchError(obj.current_etag);
    }
    throw new Error(`${response.status} ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

function _query(path: string): string {
  // workspace root 相対 POSIX path。空 / "." は workspace root。
  const params = new URLSearchParams({ path });
  return params.toString();
}

/**
 * GET /api/v1/files/tree?path=<rel> — ディレクトリ列挙 (1 階層、再帰しない)。
 * ``path`` は workspace 相対 POSIX (空文字 / "." で root)。
 */
export async function fileTree(path: string): Promise<FileTreeResponse> {
  return _fetch<FileTreeResponse>(`${API_BASE}/tree?${_query(path)}`);
}

/**
 * GET /api/v1/files/content?path=<rel> — ファイル内容を parsed JSON で返す。
 */
export async function getFileContent(path: string): Promise<FileContentResponse> {
  return _fetch<FileContentResponse>(`${API_BASE}/content?${_query(path)}`);
}

/**
 * PUT /api/v1/files/content?path=<rel> — ファイル新規 / 上書き保存。
 * ``expectedEtag`` を渡すと楽観ロック有効化、不一致時は 409 → ``EtagMismatchError``。
 */
export async function putFileContent(
  path: string,
  content: FlwModel,
  expectedEtag?: string,
): Promise<FilePutResponse> {
  const body: { content: FlwModel; expected_etag?: string } = { content };
  if (expectedEtag !== undefined) {
    body.expected_etag = expectedEtag;
  }
  return _fetch<FilePutResponse>(`${API_BASE}/content?${_query(path)}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

/**
 * POST /api/v1/files/rename — リネーム / 移動。``to`` 既存で 409。
 */
export async function renameFile(from: string, to: string): Promise<{ from: string; to: string }> {
  return _fetch<{ from: string; to: string }>(`${API_BASE}/rename`, {
    method: "POST",
    body: JSON.stringify({ from, to }),
  });
}

/**
 * DELETE /api/v1/files?path=<rel> — ファイル / 空ディレクトリ削除 (204)。
 */
export async function deleteFile(path: string): Promise<void> {
  await _fetch<void>(`${API_BASE}?${_query(path)}`, { method: "DELETE" });
}

/**
 * POST /api/v1/files/mkdir?path=<rel> — ディレクトリ作成 (mkdir -p)。
 */
export async function mkdir(path: string): Promise<void> {
  await _fetch<void>(`${API_BASE}/mkdir?${_query(path)}`, { method: "POST" });
}

// ADR-0043 §論点 1-A / §論点 8-A: workspace_info
export interface WorkspaceInfoResponse {
  absolute_path: string;
  hash: string;
}

export async function getWorkspaceInfo(): Promise<WorkspaceInfoResponse> {
  return _fetch<WorkspaceInfoResponse>(`${API_BASE}/workspace_info`);
}

// ADR-0043 §論点 5-A: search
export type SearchKind = "path" | "content";

export interface SearchResultEntry {
  path: string;
  /** kind=path のみ。0-100 の rapidfuzz スコア。 */
  score?: number;
  /** kind=content のみ。1-based 行番号。 */
  line_no?: number;
  /** kind=content のみ。マッチ行 (200 文字 truncated)。 */
  line_content?: string;
}

export interface SearchResponse {
  kind: SearchKind;
  results: SearchResultEntry[];
  truncated: boolean;
}

export async function searchFiles(
  q: string,
  kind: SearchKind = "path",
  limit: number = 100,
): Promise<SearchResponse> {
  const params = new URLSearchParams({
    q,
    kind,
    limit: String(limit),
  });
  return _fetch<SearchResponse>(`${API_BASE}/search?${params.toString()}`);
}

/**
 * Untitled<N>.flw.json の N を採番する (= 既存 tree 内で衝突しない最小 N)。
 * ``path.basename`` レベルで判定するため、サブディレクトリの同名ファイルは無視。
 */
export async function nextUntitledFilePath(): Promise<string> {
  const tree = await fileTree("");
  const taken = new Set(tree.children.map((c) => c.name));
  for (let i = 1; i < 10000; i++) {
    const name = `untitled${i}.flw.json`;
    if (!taken.has(name)) return name;
  }
  throw new Error("Cannot allocate untitled<N>.flw.json: too many files in workspace root");
}
