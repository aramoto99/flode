// ADR-0041 §論点 7-A: 自前実装 FileBrowser (= JupyterLab 流儀のワークスペース
// ツリービュー)。
//
// v0.17.0 スコープ:
//   - tree view (1 階層展開、ディレクトリは折りたたみ可)
//   - クリックで `.flw.json` を開く (= selectFilePath + editingModel に load)
//   - Refresh ボタンで再 fetch
//   - 503 (= legacy --model-dir モード) なら「File API 無効」表示
//
// v0.18.0 送り (ADR-0041 §論点 7-A):
//   - 右クリック context menu (Rename / Duplicate / Delete / New file / New folder)
//   - inline rename (F2)
//   - drag-drop でフォルダ移動
//   - 全ファイル表示 toggle (現状は `.flw.json` のみ)

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type FileEntry,
  fileTree,
  FileApiUnavailableError,
  getFileContent,
} from "../api/filesApi";
import { useAppStore } from "../store/appStore";

/**
 * 左サイドバーに置く workspace ツリービュー。React Query で 1 階層分の `tree`
 * 結果をキャッシュし、ディレクトリを開いた時点で個別 fetch する設計
 * (= 起動時に全再帰しない、大規模ワークスペース対応)。
 */
export function FileBrowser(): JSX.Element {
  const { t } = useTranslation();
  const selectedFilePath = useAppStore((s) => s.selectedFilePath);
  const selectFilePath = useAppStore((s) => s.selectFilePath);
  const setEditingModel = useAppStore((s) => s.setEditingModel);
  const setEditingFileMeta = useAppStore((s) => s.setEditingFileMeta);
  const setDirty = useAppStore((s) => s.setDirty);
  const queryClient = useQueryClient();

  const handleOpen = useCallback(
    async (path: string) => {
      try {
        const resp = await getFileContent(path);
        selectFilePath(path);
        setEditingModel(resp.content);
        setEditingFileMeta(resp.mtime, resp.etag);
        setDirty(false);
      } catch (e) {
        console.error("Failed to open file:", path, e);
      }
    },
    [selectFilePath, setEditingModel, setEditingFileMeta, setDirty],
  );

  const handleRefresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ["files-tree"] });
  }, [queryClient]);

  return (
    <div className="flex min-h-0 flex-col bg-white text-[12px]">
      <div className="flex h-6 items-center justify-between border-b border-slate-200 bg-slate-100 px-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          {t("filebrowser.title", "Workspace")}
        </span>
        <button
          type="button"
          onClick={handleRefresh}
          className="rounded px-1.5 py-0.5 text-[10px] text-slate-500 hover:bg-slate-200"
          title={t("filebrowser.refresh", "Refresh")}
          aria-label={t("filebrowser.refresh", "Refresh")}
        >
          ⟳
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto py-1">
        <DirectoryNode
          path=""
          name="(root)"
          depth={0}
          defaultExpanded
          onFileClick={handleOpen}
          selectedFilePath={selectedFilePath}
        />
      </div>
    </div>
  );
}

interface DirectoryNodeProps {
  path: string;
  name: string;
  depth: number;
  defaultExpanded?: boolean;
  onFileClick: (path: string) => void;
  selectedFilePath: string | null;
}

function DirectoryNode({
  path,
  name,
  depth,
  defaultExpanded = false,
  onFileClick,
  selectedFilePath,
}: DirectoryNodeProps): JSX.Element {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(defaultExpanded);

  // root (depth=0) は強制展開、子ディレクトリは expanded=true 時のみ fetch
  const shouldFetch = depth === 0 || expanded;
  const { data, error, isLoading } = useQuery({
    queryKey: ["files-tree", path],
    queryFn: () => fileTree(path),
    enabled: shouldFetch,
  });

  if (depth === 0) {
    // root は label を出さずに children だけレンダリング
    if (error instanceof FileApiUnavailableError) {
      return (
        <div className="px-3 py-2 text-[11px] text-amber-600">
          {t(
            "filebrowser.disabled",
            "File API not enabled. Restart pyflw-server with --workspace=PATH.",
          )}
        </div>
      );
    }
    if (isLoading) {
      return (
        <div className="px-3 py-2 text-[11px] text-slate-400">
          {t("filebrowser.loading", "Loading…")}
        </div>
      );
    }
    if (error) {
      return (
        <div className="px-3 py-2 text-[11px] text-rose-600">
          {String((error as Error).message)}
        </div>
      );
    }
    if (!data || data.children.length === 0) {
      return (
        <div className="px-3 py-2 text-[11px] text-slate-400">
          {t("filebrowser.empty", "(empty workspace)")}
        </div>
      );
    }
    return (
      <ul role="tree" className="select-none">
        {data.children.map((child) => (
          <TreeEntry
            key={child.name}
            entry={child}
            parentPath=""
            depth={1}
            onFileClick={onFileClick}
            selectedFilePath={selectedFilePath}
          />
        ))}
      </ul>
    );
  }

  // 子ディレクトリの場合: 行 + 折りたたみ children
  const childPath = path; // already includes parent prefix
  return (
    <li role="treeitem" aria-expanded={expanded}>
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className={`flex w-full items-center gap-1 py-0.5 text-left hover:bg-slate-100`}
        style={{ paddingLeft: `${depth * 12 + 4}px`, paddingRight: 8 }}
      >
        <span className="w-3 text-[10px] text-slate-400">
          {expanded ? "▾" : "▸"}
        </span>
        <FolderIcon />
        <span className="truncate text-slate-700">{name}</span>
      </button>
      {expanded && data && (
        <ul role="group">
          {data.children.map((child) => (
            <TreeEntry
              key={child.name}
              entry={child}
              parentPath={childPath}
              depth={depth + 1}
              onFileClick={onFileClick}
              selectedFilePath={selectedFilePath}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

interface TreeEntryProps {
  entry: FileEntry;
  parentPath: string;
  depth: number;
  onFileClick: (path: string) => void;
  selectedFilePath: string | null;
}

function TreeEntry({
  entry,
  parentPath,
  depth,
  onFileClick,
  selectedFilePath,
}: TreeEntryProps): JSX.Element {
  const fullPath = parentPath ? `${parentPath}/${entry.name}` : entry.name;

  if (entry.type === "directory") {
    return (
      <DirectoryNode
        path={fullPath}
        name={entry.name}
        depth={depth}
        onFileClick={onFileClick}
        selectedFilePath={selectedFilePath}
      />
    );
  }

  const isSelected = selectedFilePath === fullPath;
  const isFlw = entry.name.endsWith(".flw.json");
  return (
    <li role="treeitem">
      <button
        type="button"
        onClick={() => isFlw && onFileClick(fullPath)}
        disabled={!isFlw}
        className={`flex w-full items-center gap-1 py-0.5 text-left ${
          isSelected
            ? "bg-blue-100 text-blue-800"
            : isFlw
              ? "text-slate-700 hover:bg-slate-100"
              : "text-slate-400"
        }`}
        style={{ paddingLeft: `${depth * 12 + 4}px`, paddingRight: 8 }}
        title={fullPath}
      >
        <span className="w-3" />
        <FileIcon flw={isFlw} />
        <span className="truncate">{entry.name}</span>
      </button>
    </li>
  );
}

function FolderIcon(): JSX.Element {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-3.5 w-3.5 shrink-0 text-amber-500"
      fill="currentColor"
      aria-hidden
    >
      <path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6Z" />
    </svg>
  );
}

function FileIcon({ flw }: { flw: boolean }): JSX.Element {
  return (
    <svg
      viewBox="0 0 24 24"
      className={`h-3.5 w-3.5 shrink-0 ${flw ? "text-blue-600" : "text-slate-400"}`}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  );
}
