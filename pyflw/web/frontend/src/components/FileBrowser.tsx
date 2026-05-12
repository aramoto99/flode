// ADR-0041 §論点 7-A: 自前実装 FileBrowser (= JupyterLab 流儀のワークスペース
// ツリービュー)。
//
// v0.17.0 スコープ:
//   - tree view (1 階層展開、ディレクトリは折りたたみ可)
//   - クリックで `.flw.json` を開く (= selectFilePath + editingModel に load)
//   - Refresh ボタンで再 fetch
//   - 503 (= legacy --model-dir モード) なら「File API 無効」表示
//
// v0.18.0 追加 (本 commit):
//   - 右クリック context menu (Rename / Delete / New file / New folder)
//   - inline rename (F2 + double-click rename via context menu)
//   - 上書き保存
//
// v0.19.0 送り (ADR-0041 §論点 7-A):
//   - drag-drop でフォルダ移動
//   - 全ファイル表示 toggle (現状は全ファイルを tree で列挙)
//   - multi-select (Shift / Ctrl)

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type FileEntry,
  fileTree,
  FileApiUnavailableError,
  deleteFile,
  getFileContent,
  mkdir,
  putFileContent,
  renameFile,
} from "../api/filesApi";
import { useAppStore } from "../store/appStore";
import { DirtyConfirmDialog } from "./Modal";

interface ContextMenuState {
  x: number;
  y: number;
  /** 対象 path (= 操作対象の file/dir、空文字列で root を対象) */
  path: string;
  /** 対象がディレクトリか */
  isDirectory: boolean;
}

/** v0.28.1: drag-drop で workspace 内アイテムを移動する MIME type。
 * 外部 ファイルの drop は受け付けない (= MIME 一致時のみ移動扱い)。 */
const PYFLW_PATH_MIME = "application/x-pyflw-path";

/** 親 path を抽出 (= "a/b/c.flw.json" → "a/b"、トップレベル → "")。 */
function dirnameOf(path: string): string {
  const idx = path.lastIndexOf("/");
  return idx < 0 ? "" : path.slice(0, idx);
}

/** basename を抽出 (= "a/b/c.flw.json" → "c.flw.json")。 */
function basenameOf(path: string): string {
  const idx = path.lastIndexOf("/");
  return idx < 0 ? path : path.slice(idx + 1);
}

/** ``childPath`` が ``ancestorPath`` の子孫 (= 移動禁止条件) か判定。
 * 例: ancestorPath="a/b"、childPath="a/b/c" → true。両者一致は false。 */
function isDescendantOf(childPath: string, ancestorPath: string): boolean {
  if (ancestorPath === "") return childPath.length > 0; // root は全 path の祖先
  return childPath.startsWith(ancestorPath + "/");
}

/**
 * 左サイドバーに置く workspace ツリービュー。React Query で 1 階層分の `tree`
 * 結果をキャッシュし、ディレクトリを開いた時点で個別 fetch する設計
 * (= 起動時に全再帰しない、大規模ワークスペース対応)。
 */
export function FileBrowser(): JSX.Element {
  const { t } = useTranslation();
  const selectedFilePath = useAppStore((s) => s.selectedFilePath);
  const selectFilePath = useAppStore((s) => s.selectFilePath);
  const openFileInTab = useAppStore((s) => s.openFileInTab);
  const closeTab = useAppStore((s) => s.closeTab);
  const renameTabFilePath = useAppStore((s) => s.renameTabFilePath);
  const setEditingModel = useAppStore((s) => s.setEditingModel);
  const setEditingFileMeta = useAppStore((s) => s.setEditingFileMeta);
  const setDirty = useAppStore((s) => s.setDirty);
  const queryClient = useQueryClient();

  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [renamingPath, setRenamingPath] = useState<string | null>(null);
  // v0.20.4: 折りたたみ状態 (localStorage 連動、appStore 経由)
  const collapsed = useAppStore((s) => s.workspaceCollapsed);
  const setCollapsed = useAppStore((s) => s.setWorkspaceCollapsed);
  // ADR-0041 §論点 9-A: dirty 状態で別ファイルを開こうとしたら 3-button モーダル
  // (Discard / Save & Open / Cancel) で確認。``pendingOpenPath`` が non-null の
  // 間は ``DirtyConfirmDialog`` が開く。
  const [pendingOpenPath, setPendingOpenPath] = useState<string | null>(null);

  const performOpen = useCallback(
    async (path: string): Promise<void> => {
      try {
        const resp = await getFileContent(path);
        // ADR-0043 §論点 2: 単一 atomic action で tab 追加 + active 化 + state 同期。
        // 旧 selectFilePath + setEditingModel + setEditingFileMeta + setDirty の
        // 4 連続 set より race / dirty flag 中間状態の問題が起きにくい。
        openFileInTab(path, resp.content, resp.mtime, resp.etag);
        // ADR-0043 §論点 4: Recent Files に move-to-front。
        const hash = useAppStore.getState().workspaceHash;
        if (hash) {
          const { addRecentFile } = await import("../lib/recentFiles");
          addRecentFile(hash, path);
        }
      } catch (e) {
        console.error("Failed to open file:", path, e);
      }
    },
    [openFileInTab],
  );

  const handleOpen = useCallback(
    async (path: string) => {
      // 同ファイル再選択は no-op
      const state = useAppStore.getState();
      if (state.selectedFilePath === path) return;
      // dirty 確認 (ADR-0041 §論点 9-A): モーダル経由で 3-button 選択させる
      if (state.dirty) {
        setPendingOpenPath(path);
        return;
      }
      await performOpen(path);
    },
    [performOpen],
  );

  const refresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ["files-tree"] });
  }, [queryClient]);

  const handleRefresh = useCallback(() => {
    void refresh();
  }, [refresh]);

  // F2 で選択ファイルを inline rename
  useEffect(() => {
    const handler = (e: KeyboardEvent): void => {
      if (e.key === "F2" && selectedFilePath !== null && renamingPath === null) {
        // input フォーカス中は trigger しない (= ブラウザネイティブの編集を妨げない)
        const ae = document.activeElement;
        if (
          ae instanceof HTMLInputElement ||
          ae instanceof HTMLTextAreaElement
        ) {
          return;
        }
        e.preventDefault();
        setRenamingPath(selectedFilePath);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [selectedFilePath, renamingPath]);

  // クリック outside で context menu を閉じる
  useEffect(() => {
    if (!contextMenu) return;
    const handler = (): void => setContextMenu(null);
    window.addEventListener("click", handler);
    window.addEventListener("blur", handler);
    return () => {
      window.removeEventListener("click", handler);
      window.removeEventListener("blur", handler);
    };
  }, [contextMenu]);

  const handleContextMenu = useCallback(
    (e: React.MouseEvent, path: string, isDirectory: boolean) => {
      e.preventDefault();
      e.stopPropagation();
      setContextMenu({ x: e.clientX, y: e.clientY, path, isDirectory });
    },
    [],
  );

  const handleRename = useCallback(
    async (oldPath: string, newName: string) => {
      setRenamingPath(null);
      if (!newName || newName === oldPath.split("/").pop()) return;
      // 同階層に rename (= dirname 維持)
      const parts = oldPath.split("/");
      parts[parts.length - 1] = newName;
      const newPath = parts.join("/");
      try {
        await renameFile(oldPath, newPath);
        await refresh();
        // ADR-0043 §論点 2: rename を tab に追従。複数タブ時に他タブを失わない。
        renameTabFilePath(oldPath, newPath);
        if (selectedFilePath === oldPath) {
          // 新 path で再 fetch して etag/mtime を最新に
          const data = await getFileContent(newPath);
          setEditingModel(data.content);
          setEditingFileMeta(data.mtime, data.etag);
        }
      } catch (e) {
        console.error("Rename failed:", e);
      }
    },
    [
      refresh,
      renameTabFilePath,
      selectedFilePath,
      setEditingFileMeta,
      setEditingModel,
    ],
  );

  /** v0.28.1: drag-drop でファイル / フォルダを別ディレクトリへ移動する。
   *
   * - source = drag された path (file or dir)
   * - targetDir = drop された先のディレクトリ path (root の場合は "")
   *
   * 以下のケースは no-op:
   * - source と targetDir が同じ親ディレクトリ (= 移動先が同じ場所)
   * - source 自身が targetDir (= dir を自分自身に drop)
   * - source が targetDir の祖先 (= 自分のサブツリーに drop)
   *
   * 同名ファイルが targetDir に存在する場合、backend は 409 を返し alert で通知。
   */
  const handleMove = useCallback(
    async (sourcePath: string, targetDir: string): Promise<void> => {
      if (!sourcePath) return;
      const base = basenameOf(sourcePath);
      const parentOfSource = dirnameOf(sourcePath);
      // 同じ親 dir 内 → 移動不要
      if (parentOfSource === targetDir) return;
      // dir を自分自身に drop
      if (sourcePath === targetDir) return;
      // 自分のサブツリーに drop (= 無限再帰防止)
      if (isDescendantOf(targetDir, sourcePath)) {
        window.alert(
          t(
            "filebrowser.move.descendant_forbidden",
            "Cannot move into own subdirectory",
          ),
        );
        return;
      }
      const newPath = targetDir ? `${targetDir}/${base}` : base;
      try {
        await renameFile(sourcePath, newPath);
        await refresh();
        // 移動した item が現在開いている tab の path と一致するか、その祖先なら
        // tab path も追従させる (= rename と同じ semantics)
        const state = useAppStore.getState();
        for (const tab of state.tabs) {
          if (tab.filePath === sourcePath) {
            renameTabFilePath(sourcePath, newPath);
          } else if (isDescendantOf(tab.filePath, sourcePath)) {
            // dir 移動で配下 file の path も変わる
            const suffix = tab.filePath.slice(sourcePath.length); // "/foo.flw.json"
            const newTabPath = newPath + suffix;
            renameTabFilePath(tab.filePath, newTabPath);
          }
        }
        // 開いてるモデル本体も etag/mtime 再 fetch
        const stillActive = useAppStore.getState().selectedFilePath;
        if (stillActive) {
          const data = await getFileContent(stillActive);
          setEditingModel(data.content);
          setEditingFileMeta(data.mtime, data.etag);
        }
      } catch (e) {
        console.error("Move failed:", sourcePath, "->", targetDir, e);
        window.alert(`Move failed: ${(e as Error).message}`);
      }
    },
    [refresh, renameTabFilePath, setEditingFileMeta, setEditingModel, t],
  );

  const handleDelete = useCallback(
    async (path: string) => {
      // confirm dialog (= browser native、SaveAsModal の作りと同じ自前 modal は
      // v0.19.0 で実装)
      const ok = window.confirm(
        t("filebrowser.confirm_delete", "Delete {{path}}?", { path }),
      );
      if (!ok) return;
      try {
        await deleteFile(path);
        await refresh();
        // ADR-0043 §論点 2: 開いていた tab があれば閉じる (= 隣接 tab に切替 or 全閉じ)
        const state = useAppStore.getState();
        if (state.tabs.some((t) => t.filePath === path)) {
          closeTab(path);
        } else if (selectedFilePath === path) {
          // 後方互換: tabs に未登録だが active な path (= legacy load パス)
          selectFilePath(null);
          setEditingModel(null);
          setDirty(false);
        }
      } catch (e) {
        console.error("Delete failed:", e);
        window.alert(`Delete failed: ${(e as Error).message}`);
      }
    },
    [
      closeTab,
      refresh,
      selectFilePath,
      selectedFilePath,
      setDirty,
      setEditingModel,
      t,
    ],
  );

  const handleNewFile = useCallback(
    async (parentPath: string) => {
      const name = window.prompt(
        t("filebrowser.prompt_new_file", "New file name (.flw.json):"),
        "untitled.flw.json",
      );
      if (!name) return;
      const fullPath = parentPath ? `${parentPath}/${name}` : name;
      try {
        // 空モデル (= legacy emptyModel と同じ scaffold) を書き込む
        await putFileContent(fullPath, {
          schema_version: "0.8",
          metadata: { name: name.replace(/\.flw\.json$/, ""), tool: "pyflw GUI" },
          simulator: {
            t_end: 10.0,
            dt: 0.01,
            solver: "RK45",
            rtol: 1e-3,
            atol: 1e-6,
            dt_base: null,
          },
          blocks: [],
          connections: [],
          layout: {},
        });
        await refresh();
      } catch (e) {
        console.error("New file failed:", e);
        window.alert(`Create failed: ${(e as Error).message}`);
      }
    },
    [refresh, t],
  );

  const handleNewFolder = useCallback(
    async (parentPath: string) => {
      const name = window.prompt(
        t("filebrowser.prompt_new_folder", "New folder name:"),
        "subdir",
      );
      if (!name) return;
      const fullPath = parentPath ? `${parentPath}/${name}` : name;
      try {
        await mkdir(fullPath);
        await refresh();
      } catch (e) {
        console.error("Mkdir failed:", e);
        window.alert(`Mkdir failed: ${(e as Error).message}`);
      }
    },
    [refresh, t],
  );

  return (
    <div className="flex min-h-0 flex-col bg-white text-[12px]">
      <div className="flex h-6 items-center justify-between border-b border-slate-200 bg-slate-100 px-2">
        {/* v0.20.4: header 全体クリックで折りたたみ。Refresh ボタンは右側に分離。 */}
        <button
          type="button"
          onClick={() => setCollapsed(!collapsed)}
          className="flex flex-1 items-center gap-1 text-left hover:text-slate-700"
          title={
            collapsed
              ? t("filebrowser.expand", "Expand workspace")
              : t("filebrowser.collapse", "Collapse workspace")
          }
          aria-expanded={!collapsed}
        >
          <span
            className="w-3 text-[10px] text-slate-500"
            aria-hidden
          >
            {collapsed ? "▸" : "▾"}
          </span>
          <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            {t("filebrowser.title", "Workspace")}
          </span>
        </button>
        {!collapsed && (
          <button
            type="button"
            onClick={handleRefresh}
            className="rounded px-1.5 py-0.5 text-[10px] text-slate-500 hover:bg-slate-200"
            title={t("filebrowser.refresh", "Refresh")}
            aria-label={t("filebrowser.refresh", "Refresh")}
          >
            ⟳
          </button>
        )}
      </div>
      {!collapsed && (
        <div
          className="min-h-0 flex-1 overflow-y-auto py-1"
          onContextMenu={(e) => handleContextMenu(e, "", true)}
          // v0.28.1: container 全体を drop target にし、root への移動を許可
          onDragOver={(e) => {
            if (e.dataTransfer.types.includes(PYFLW_PATH_MIME)) {
              e.preventDefault();
              e.dataTransfer.dropEffect = "move";
            }
          }}
          onDrop={(e) => {
            const source = e.dataTransfer.getData(PYFLW_PATH_MIME);
            if (!source) return;
            e.preventDefault();
            void handleMove(source, "");
          }}
        >
          <DirectoryNode
            path=""
            name="(root)"
            depth={0}
            defaultExpanded
            onFileClick={handleOpen}
            onContextMenu={handleContextMenu}
            onMove={handleMove}
            renamingPath={renamingPath}
            onSubmitRename={handleRename}
            onCancelRename={() => setRenamingPath(null)}
            selectedFilePath={selectedFilePath}
          />
        </div>
      )}
      {pendingOpenPath !== null && (
        <DirtyConfirmDialog
          currentName={selectedFilePath ?? "(untitled)"}
          nextName={pendingOpenPath}
          onDiscard={() => {
            const target = pendingOpenPath;
            setPendingOpenPath(null);
            void performOpen(target);
          }}
          onSaveAndOpen={async () => {
            // 現在の編集を File API で保存してから開く (v0.21.0 で legacy
            // ``selectedModelId`` 経路は削除済、selectedFilePath 一本化)。
            const target = pendingOpenPath;
            const state = useAppStore.getState();
            const path = state.selectedFilePath;
            const model = state.editingModel;
            if (path !== null && model !== null) {
              try {
                const saved = await putFileContent(
                  path,
                  model,
                  state.editingFileEtag ?? undefined,
                );
                setEditingFileMeta(saved.mtime, saved.etag);
                setDirty(false);
              } catch (e) {
                console.error("Save before switch failed:", e);
                window.alert(`Save failed: ${(e as Error).message}`);
                return;
              }
            }
            setPendingOpenPath(null);
            void performOpen(target);
          }}
          onClose={() => setPendingOpenPath(null)}
        />
      )}
      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          path={contextMenu.path}
          isDirectory={contextMenu.isDirectory}
          onRename={() => {
            if (contextMenu.path !== "") setRenamingPath(contextMenu.path);
            setContextMenu(null);
          }}
          onDelete={() => {
            if (contextMenu.path !== "") void handleDelete(contextMenu.path);
            setContextMenu(null);
          }}
          onNewFile={() => {
            const parent = contextMenu.isDirectory ? contextMenu.path : "";
            void handleNewFile(parent);
            setContextMenu(null);
          }}
          onNewFolder={() => {
            const parent = contextMenu.isDirectory ? contextMenu.path : "";
            void handleNewFolder(parent);
            setContextMenu(null);
          }}
          onClose={() => setContextMenu(null)}
        />
      )}
    </div>
  );
}

interface DirectoryNodeProps {
  path: string;
  name: string;
  depth: number;
  defaultExpanded?: boolean;
  onFileClick: (path: string) => void;
  onContextMenu: (e: React.MouseEvent, path: string, isDirectory: boolean) => void;
  /** v0.28.1: drag-drop で移動する handler (sourcePath, targetDir) */
  onMove: (sourcePath: string, targetDir: string) => Promise<void>;
  renamingPath: string | null;
  onSubmitRename: (oldPath: string, newName: string) => Promise<void>;
  onCancelRename: () => void;
  selectedFilePath: string | null;
}

function DirectoryNode({
  path,
  name,
  depth,
  defaultExpanded = false,
  onFileClick,
  onContextMenu,
  onMove,
  renamingPath,
  onSubmitRename,
  onCancelRename,
  selectedFilePath,
}: DirectoryNodeProps): JSX.Element {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(defaultExpanded);
  // v0.28.1: drag-over 中のハイライト state
  const [isDragOver, setIsDragOver] = useState(false);

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
            onContextMenu={onContextMenu}
            onMove={onMove}
            renamingPath={renamingPath}
            onSubmitRename={onSubmitRename}
            onCancelRename={onCancelRename}
            selectedFilePath={selectedFilePath}
          />
        ))}
      </ul>
    );
  }

  // v0.28.1: directory は **drop target + drag source** 両対応。
  // drop target: 自分の path を targetDir として move
  // drag source: 自分の path を source として外に出す (= 別 dir へ移動可能)
  const onDragStart = (e: React.DragEvent<HTMLButtonElement>): void => {
    e.dataTransfer.setData(PYFLW_PATH_MIME, path);
    e.dataTransfer.effectAllowed = "move";
    e.stopPropagation();
  };
  const onDragOver = (e: React.DragEvent<HTMLLIElement>): void => {
    if (!e.dataTransfer.types.includes(PYFLW_PATH_MIME)) return;
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = "move";
    setIsDragOver(true);
  };
  const onDragLeave = (): void => setIsDragOver(false);
  const onDrop = (e: React.DragEvent<HTMLLIElement>): void => {
    setIsDragOver(false);
    const source = e.dataTransfer.getData(PYFLW_PATH_MIME);
    if (!source) return;
    e.preventDefault();
    e.stopPropagation();
    void onMove(source, path);
  };

  // 子ディレクトリの場合: 行 + 折りたたみ children
  return (
    <li
      role="treeitem"
      aria-expanded={expanded}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <button
        type="button"
        draggable
        onDragStart={onDragStart}
        onClick={() => setExpanded(!expanded)}
        onContextMenu={(e) => onContextMenu(e, path, true)}
        className={`flex w-full items-center gap-1 py-0.5 text-left ${
          isDragOver ? "bg-blue-100" : "hover:bg-slate-100"
        }`}
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
              parentPath={path}
              depth={depth + 1}
              onFileClick={onFileClick}
              onContextMenu={onContextMenu}
              onMove={onMove}
              renamingPath={renamingPath}
              onSubmitRename={onSubmitRename}
              onCancelRename={onCancelRename}
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
  onContextMenu: (e: React.MouseEvent, path: string, isDirectory: boolean) => void;
  /** v0.28.1: drag-drop で移動する handler */
  onMove: (sourcePath: string, targetDir: string) => Promise<void>;
  renamingPath: string | null;
  onSubmitRename: (oldPath: string, newName: string) => Promise<void>;
  onCancelRename: () => void;
  selectedFilePath: string | null;
}

function TreeEntry({
  entry,
  parentPath,
  depth,
  onFileClick,
  onContextMenu,
  onMove,
  renamingPath,
  onSubmitRename,
  onCancelRename,
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
        onContextMenu={onContextMenu}
        onMove={onMove}
        renamingPath={renamingPath}
        onSubmitRename={onSubmitRename}
        onCancelRename={onCancelRename}
        selectedFilePath={selectedFilePath}
      />
    );
  }

  const isSelected = selectedFilePath === fullPath;
  const isFlw = entry.name.endsWith(".flw.json");
  const isRenaming = renamingPath === fullPath;

  // v0.28.1: file は drag source として扱う (= drop target にはしない、
  // file の上に file を drop する semantics は未定義)。
  const onDragStart = (e: React.DragEvent<HTMLButtonElement>): void => {
    e.dataTransfer.setData(PYFLW_PATH_MIME, fullPath);
    e.dataTransfer.effectAllowed = "move";
  };

  return (
    <li role="treeitem">
      {isRenaming ? (
        <InlineRename
          initialValue={entry.name}
          depth={depth}
          onSubmit={(newName) => void onSubmitRename(fullPath, newName)}
          onCancel={onCancelRename}
        />
      ) : (
        <button
          type="button"
          draggable
          onDragStart={onDragStart}
          onClick={() => isFlw && onFileClick(fullPath)}
          onContextMenu={(e) => onContextMenu(e, fullPath, false)}
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
      )}
    </li>
  );
}

interface InlineRenameProps {
  initialValue: string;
  depth: number;
  onSubmit: (newName: string) => void;
  onCancel: () => void;
}

function InlineRename({
  initialValue,
  depth,
  onSubmit,
  onCancel,
}: InlineRenameProps): JSX.Element {
  const [value, setValue] = useState(initialValue);
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    // mount 時に focus + 拡張子を除く部分を選択 (= JupyterLab 流儀)
    const input = ref.current;
    if (!input) return;
    input.focus();
    const ext = initialValue.lastIndexOf(".flw.json");
    const stemEnd = ext > 0 ? ext : initialValue.length;
    input.setSelectionRange(0, stemEnd);
  }, [initialValue]);

  return (
    <div
      className="flex w-full items-center gap-1 py-0.5"
      style={{ paddingLeft: `${depth * 12 + 4}px`, paddingRight: 8 }}
    >
      <span className="w-3" />
      <FileIcon flw={initialValue.endsWith(".flw.json")} />
      <input
        ref={ref}
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            onSubmit(value);
          } else if (e.key === "Escape") {
            e.preventDefault();
            onCancel();
          }
        }}
        onBlur={() => {
          // blur で確定 (= JupyterLab と同じ、Esc で cancel 経由のみ取消)
          onSubmit(value);
        }}
        className="flex-1 border border-blue-500 bg-white px-1 text-[12px] outline-none"
      />
    </div>
  );
}

interface ContextMenuProps {
  x: number;
  y: number;
  path: string;
  isDirectory: boolean;
  onRename: () => void;
  onDelete: () => void;
  onNewFile: () => void;
  onNewFolder: () => void;
  onClose: () => void;
}

function ContextMenu({
  x,
  y,
  path,
  isDirectory,
  onRename,
  onDelete,
  onNewFile,
  onNewFolder,
}: ContextMenuProps): JSX.Element {
  const { t } = useTranslation();
  const isRoot = path === "";
  return (
    <div
      role="menu"
      onClick={(e) => e.stopPropagation()}
      onContextMenu={(e) => e.preventDefault()}
      className="fixed z-50 min-w-[160px] border border-slate-300 bg-white py-0.5 shadow-md"
      style={{ left: x, top: y }}
    >
      <MenuItem
        label={t("filebrowser.menu.new_file", "New file")}
        onClick={onNewFile}
      />
      <MenuItem
        label={t("filebrowser.menu.new_folder", "New folder")}
        onClick={onNewFolder}
      />
      {!isRoot && (
        <>
          <div className="my-0.5 border-t border-slate-200" />
          <MenuItem
            label={t("filebrowser.menu.rename", "Rename (F2)")}
            onClick={onRename}
            disabled={isDirectory}
          />
          <MenuItem
            label={t("filebrowser.menu.delete", "Delete")}
            onClick={onDelete}
            destructive
          />
        </>
      )}
    </div>
  );
}

interface MenuItemProps {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  destructive?: boolean;
}

function MenuItem({
  label,
  onClick,
  disabled = false,
  destructive = false,
}: MenuItemProps): JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`flex w-full items-center gap-2 px-3 py-1 text-left text-[12px] ${
        disabled
          ? "text-slate-400"
          : destructive
            ? "text-rose-600 hover:bg-rose-50"
            : "text-slate-700 hover:bg-blue-600 hover:text-white"
      }`}
    >
      {label}
    </button>
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
