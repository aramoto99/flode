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
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type FileEntry,
  type FileTreeResponse,
  fileTree,
  FileApiUnavailableError,
  copyFile,
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
 * 外部 ファイルの drop は受け付けない (= MIME 一致時のみ移動扱い)。
 * v0.28.2: 値は JSON 配列 ``["path1", "path2", ...]`` (= multi-select 対応、
 * 1 個でも配列で統一)。 */
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

/** v0.28.2: drag MIME に格納された JSON 配列を解析。失敗時は単一文字列として
 * 解釈 (= 1 個の path として後方互換)。 */
function parsePathsMime(raw: string): string[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      return parsed.filter((x): x is string => typeof x === "string");
    }
    if (typeof parsed === "string") return [parsed];
  } catch {
    // 旧形式 (= JSON でない単純な path 文字列) もサポート
    return [raw];
  }
  return [];
}

/** v0.28.2: drag MIME に格納するための JSON シリアライズ。 */
function serializePathsMime(paths: string[]): string {
  return JSON.stringify(paths);
}

/** v0.31.9: copy/paste で衝突しない複製名を生成する。
 *
 * 例:
 * - "model.flw.json" + existing={"model.flw.json"} → "model (copy).flw.json"
 * - 上記がさらに衝突 → "model (copy 2).flw.json"
 * - "no_ext" + existing={"no_ext"} → "no_ext (copy)"
 *
 * 拡張子は **最初の `.` 以降** 全体を「拡張子」とみなす (= ".flw.json" の
 * 二重拡張子を 1 つの ext として保つ)。
 */
function generateCopyName(originalName: string, existing: Set<string>): string {
  if (!existing.has(originalName)) return originalName;
  const dotIdx = originalName.indexOf(".");
  const base = dotIdx >= 0 ? originalName.slice(0, dotIdx) : originalName;
  const ext = dotIdx >= 0 ? originalName.slice(dotIdx) : "";
  for (let i = 1; i < 1000; i++) {
    const candidate = i === 1
      ? `${base} (copy)${ext}`
      : `${base} (copy ${i})${ext}`;
    if (!existing.has(candidate)) return candidate;
  }
  // フォールバック: タイムスタンプで一意性を確保
  return `${base} (copy ${Date.now()})${ext}`;
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
  // v0.31.3: ヘッダーの「新規ファイル」「新規フォルダ」アイコンボタンが現在の
  // cwd 直下に作成するため、FileBrowser 本体でも cwd を購読する。
  const fileBrowserCwd = useAppStore((s) => s.fileBrowserCwd);
  const queryClient = useQueryClient();

  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [renamingPath, setRenamingPath] = useState<string | null>(null);
  // v0.31.9: copy/paste クリップボード。Ctrl+C で selectedPaths (空なら
  // selectedFilePath) をセット、Ctrl+V で現在の cwd 直下に順次複製 (= API
  // copyFile)。OS clipboard とは独立 (= preventDefault で誤介入を抑止)。
  const [clipboard, setClipboard] = useState<string[]>([]);
  // v0.28.2: multi-select state (= Ctrl+クリックで追加選択、drag-drop で複数移動)
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
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

  // v0.31.6: ルート div のショートカット handler。
  // 旧 v0.31.5 まで: F2 のみグローバル `window.addEventListener("keydown")` で
  // 拾っていた → Diagram canvas など FileBrowser 外でも誤発火するリスク。
  // 新 v0.31.6: FileBrowser ルート div を tabIndex={-1} で focusable にし、
  // onKeyDown で F2 / Delete (Backspace) / Enter / Escape を処理する。
  // CwdView 内の click 時に root div へ focus を移す (= onMouseDown で focus()
  // 呼出し)。これで JupyterLab 流の「アイテム選択中はファイル操作ショートカットが
  // 有効」UX が成立する。
  const rootRef = useRef<HTMLDivElement>(null);
  const focusRoot = useCallback(() => {
    rootRef.current?.focus({ preventScroll: true });
  }, []);
  // handleKeyDown 本体は handleDelete / handleNewFolder の宣言後 (= 下方) で
  // 定義する (= TDZ 回避)。

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

  /** v0.28.1 + v0.28.2: drag-drop でファイル / フォルダを別ディレクトリへ移動。
   *
   * - sources = drag された path (1 個または複数、v0.28.2 から配列形式)
   * - targetDir = drop された先のディレクトリ path (root の場合は "")
   *
   * 各 source ごとに以下のケースは no-op:
   * - source と targetDir が同じ親ディレクトリ (= 移動先が同じ場所)
   * - source 自身が targetDir (= dir を自分自身に drop)
   * - source が targetDir の祖先 (= 自分のサブツリーに drop、禁止 alert)
   *
   * 同名ファイルが targetDir に存在する場合、backend は 409 を返し alert で通知
   * (= 各 source を順次処理、いずれかで失敗しても残りを処理)。
   */
  const handleMove = useCallback(
    async (sources: string[], targetDir: string): Promise<void> => {
      if (sources.length === 0) return;

      // v0.28.2: 禁止条件チェックを最初に集める (= 1 つでも禁止条件があれば
      // user に明示してから処理続行)
      const forbiddenForOwnSubtree: string[] = [];
      const moveTargets: string[] = [];
      for (const sourcePath of sources) {
        if (!sourcePath) continue;
        const parentOfSource = dirnameOf(sourcePath);
        if (parentOfSource === targetDir) continue;
        if (sourcePath === targetDir) continue;
        if (isDescendantOf(targetDir, sourcePath)) {
          forbiddenForOwnSubtree.push(sourcePath);
          continue;
        }
        moveTargets.push(sourcePath);
      }
      if (forbiddenForOwnSubtree.length > 0) {
        window.alert(
          t(
            "filebrowser.move.descendant_forbidden",
            "Cannot move into own subdirectory",
          ),
        );
      }
      if (moveTargets.length === 0) return;

      const failures: Array<{ path: string; error: string }> = [];
      for (const sourcePath of moveTargets) {
        const base = basenameOf(sourcePath);
        const newPath = targetDir ? `${targetDir}/${base}` : base;
        try {
          await renameFile(sourcePath, newPath);
          // tabs[] の path 追従 (= 1 件ずつ、tree 全体 refresh は後でまとめて)
          const state = useAppStore.getState();
          for (const tab of state.tabs) {
            if (tab.filePath === sourcePath) {
              renameTabFilePath(sourcePath, newPath);
            } else if (isDescendantOf(tab.filePath, sourcePath)) {
              const suffix = tab.filePath.slice(sourcePath.length);
              renameTabFilePath(tab.filePath, newPath + suffix);
            }
          }
        } catch (e) {
          failures.push({ path: sourcePath, error: (e as Error).message });
          console.error("Move failed:", sourcePath, "->", targetDir, e);
        }
      }
      await refresh();
      // 開いてるモデルの etag/mtime を再 fetch (= tab path 更新後の最新)
      const stillActive = useAppStore.getState().selectedFilePath;
      if (stillActive) {
        try {
          const data = await getFileContent(stillActive);
          setEditingModel(data.content);
          setEditingFileMeta(data.mtime, data.etag);
        } catch {
          // 移動失敗 + active path 無効化のケース、refresh で UI 復元される
        }
      }
      // 移動完了で選択クリア (= multi-select した state を引きずらない)
      setSelectedPaths(new Set());

      if (failures.length > 0) {
        const summary = failures
          .map((f) => `  - ${f.path}: ${f.error}`)
          .join("\n");
        window.alert(`Move failed for ${failures.length} item(s):\n${summary}`);
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
      // v0.31.5: prompt のデフォルト値 "subdir" を削除 (= ユーザー要望、
      // 何も書かれていない空欄から入力させる)
      const name = window.prompt(
        t("filebrowser.prompt_new_folder", "New folder name:"),
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

  // v0.31.7: multi-select 削除 (= Ctrl+クリックや Ctrl+A で集めた selectedPaths
  // を一括で削除する)。confirm dialog は **1 回だけ** 個数を提示して、OK なら
  // 順次 deleteFile。途中失敗は summary alert で報告。
  const handleDeleteMany = useCallback(
    async (paths: string[]) => {
      if (paths.length === 0) return;
      const ok = window.confirm(
        t("filebrowser.confirm_delete_many", "Delete {{count}} item(s)?", {
          count: paths.length,
        }),
      );
      if (!ok) return;
      const failures: { path: string; error: string }[] = [];
      for (const p of paths) {
        try {
          await deleteFile(p);
          // 開いていた tab を閉じる (= 単一 handleDelete と同じセマンティクス)
          const state = useAppStore.getState();
          if (state.tabs.some((tab) => tab.filePath === p)) {
            closeTab(p);
          } else if (selectedFilePath === p) {
            selectFilePath(null);
            setEditingModel(null);
            setDirty(false);
          }
        } catch (e) {
          failures.push({ path: p, error: (e as Error).message });
        }
      }
      await refresh();
      setSelectedPaths(new Set());
      if (failures.length > 0) {
        const summary = failures
          .map((f) => `  - ${f.path}: ${f.error}`)
          .join("\n");
        window.alert(
          `Delete failed for ${failures.length} / ${paths.length}:\n${summary}`,
        );
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

  // v0.31.9: Ctrl+V 貼り付け。クリップボードの各 path を現在の cwd 配下に
  // copyFile で複製。target name は basename 衝突を回避するため "(copy)" suffix を
  // 動的に付与 (= JupyterLab 流の "Duplicate" と同じ挙動)。
  const handlePaste = useCallback(async () => {
    if (clipboard.length === 0) return;
    const treeData = queryClient.getQueryData<FileTreeResponse>([
      "files-tree",
      fileBrowserCwd,
    ]);
    if (!treeData) {
      window.alert("Paste failed: file listing not loaded yet");
      return;
    }
    const existing = new Set(treeData.children.map((e) => e.name));
    const failures: { from: string; error: string }[] = [];
    const createdPaths: string[] = [];
    for (const src of clipboard) {
      const base = src.split("/").pop() ?? src;
      const newName = generateCopyName(base, existing);
      existing.add(newName);
      const dst = fileBrowserCwd ? `${fileBrowserCwd}/${newName}` : newName;
      try {
        await copyFile(src, dst);
        createdPaths.push(dst);
      } catch (e) {
        failures.push({ from: src, error: (e as Error).message });
      }
    }
    await refresh();
    if (failures.length > 0) {
      const summary = failures
        .map((f) => `  - ${f.from}: ${f.error}`)
        .join("\n");
      window.alert(
        `Paste failed for ${failures.length} / ${clipboard.length}:\n${summary}`,
      );
    }
  }, [clipboard, fileBrowserCwd, queryClient, refresh]);

  // v0.31.6: ファイル操作ショートカット handler (= focus が FileBrowser 内に
  // ある時のみ発火)。F2 = rename / Delete・Backspace = 削除 / Enter = 開く /
  // Escape = 選択クリア。
  // v0.31.7: Ctrl+A 全選択 + multi-delete (= selectedPaths.size > 0 なら一括削除)
  // を追加。
  // v0.31.9: Ctrl+C コピー / Ctrl+V 貼り付け。
  const handleKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLDivElement>) => {
      // rename 用 input にフォーカスがあるときは何もしない (= ブラウザネイティブの
      // 編集を妨げない)
      const ae = document.activeElement;
      if (
        ae instanceof HTMLInputElement ||
        ae instanceof HTMLTextAreaElement
      ) {
        return;
      }
      if (renamingPath !== null) return;

      // Ctrl+A / Cmd+A: 現在の cwd 内の全 entry を selectedPaths に追加
      // (= React Query cache から entries を取得、再 fetch せず即時)
      if ((e.ctrlKey || e.metaKey) && e.key === "a") {
        const data = queryClient.getQueryData<FileTreeResponse>([
          "files-tree",
          fileBrowserCwd,
        ]);
        if (!data) return;
        e.preventDefault();
        const allPaths = data.children.map((entry) =>
          fileBrowserCwd ? `${fileBrowserCwd}/${entry.name}` : entry.name,
        );
        setSelectedPaths(new Set(allPaths));
        return;
      }

      // v0.31.9: Ctrl+C / Cmd+C: 選択中アイテムをクリップボードに保存。
      // selectedPaths が非空ならそれを、空なら selectedFilePath 単独を保存。
      if ((e.ctrlKey || e.metaKey) && e.key === "c") {
        const targets =
          selectedPaths.size > 0
            ? Array.from(selectedPaths)
            : selectedFilePath !== null
              ? [selectedFilePath]
              : [];
        if (targets.length === 0) return;
        e.preventDefault();
        setClipboard(targets);
        return;
      }

      // v0.31.9: Ctrl+V / Cmd+V: クリップボードの各 path を現在の cwd 配下に複製
      if ((e.ctrlKey || e.metaKey) && e.key === "v") {
        if (clipboard.length === 0) return;
        e.preventDefault();
        void handlePaste();
        return;
      }

      switch (e.key) {
        case "F2":
          if (selectedFilePath !== null) {
            e.preventDefault();
            setRenamingPath(selectedFilePath);
          }
          return;
        case "Delete":
        case "Backspace":
          // ※ Backspace = 親ディレクトリ移動とする UI もあるが、pyflw では
          // breadcrumb の ↑ ボタンを別途用意しているため Backspace も削除に bind。
          // selectedPaths が非空なら一括削除、空なら selectedFilePath を単一削除
          if (selectedPaths.size > 0) {
            e.preventDefault();
            void handleDeleteMany(Array.from(selectedPaths));
          } else if (selectedFilePath !== null) {
            e.preventDefault();
            void handleDelete(selectedFilePath);
          }
          return;
        case "Enter":
          if (selectedFilePath !== null) {
            e.preventDefault();
            void handleOpen(selectedFilePath);
          }
          return;
        case "Escape":
          if (selectedFilePath !== null || selectedPaths.size > 0) {
            e.preventDefault();
            selectFilePath(null);
            setSelectedPaths(new Set());
          }
          return;
        default:
          return;
      }
    },
    [
      selectedFilePath,
      renamingPath,
      selectedPaths,
      selectFilePath,
      handleDelete,
      handleDeleteMany,
      handleOpen,
      handlePaste,
      clipboard,
      queryClient,
      fileBrowserCwd,
    ],
  );

  return (
    <div
      ref={rootRef}
      tabIndex={-1}
      className="flex min-h-0 flex-col bg-white text-[12px] outline-none"
      // v0.31.3: ヘッダー / 余白で右クリックしてもブラウザ context menu を
      // 抑止して、現在の cwd を対象にカスタム context menu を出す。
      onContextMenu={(e) => handleContextMenu(e, fileBrowserCwd, true)}
      // v0.31.6: クリックで root div に focus を移し、F2/Delete/Enter/Escape の
      // ショートカットを有効化する (= JupyterLab 流 "アイテム選択中はキーが有効")。
      // tabIndex=-1 にしているため Tab navigation には現れず、mousedown 経由のみで
      // フォーカスが当たる。
      onMouseDown={focusRoot}
      onKeyDown={handleKeyDown}
    >
      <div className="flex h-6 items-center justify-between border-b border-slate-200 bg-slate-100 px-2">
        {/* v0.20.4: header 全体クリックで折りたたみ。アクション ボタン群は右側。 */}
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
          <span className="w-3 text-[10px] text-slate-500" aria-hidden>
            {collapsed ? "▸" : "▾"}
          </span>
          <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            {t("filebrowser.title", "Workspace")}
          </span>
        </button>
        {!collapsed && (
          <div className="flex shrink-0 items-center gap-0.5">
            {/* v0.31.3: 新規ファイル / 新規フォルダ アイコンボタン (= JupyterLab 流) */}
            <button
              type="button"
              onClick={() => void handleNewFile(fileBrowserCwd)}
              className="flex h-5 w-5 items-center justify-center rounded text-slate-500 hover:bg-slate-200 hover:text-slate-800"
              title={t("filebrowser.action.new_file", "New file")}
              aria-label={t("filebrowser.action.new_file", "New file")}
            >
              <NewFileIcon />
            </button>
            <button
              type="button"
              onClick={() => void handleNewFolder(fileBrowserCwd)}
              className="flex h-5 w-5 items-center justify-center rounded text-slate-500 hover:bg-slate-200 hover:text-slate-800"
              title={t("filebrowser.action.new_folder", "New folder")}
              aria-label={t("filebrowser.action.new_folder", "New folder")}
            >
              <NewFolderIcon />
            </button>
            <button
              type="button"
              onClick={handleRefresh}
              className="flex h-5 w-5 items-center justify-center rounded text-slate-500 hover:bg-slate-200 hover:text-slate-800"
              title={t("filebrowser.refresh", "Refresh")}
              aria-label={t("filebrowser.refresh", "Refresh")}
            >
              <RefreshIcon />
            </button>
          </div>
        )}
      </div>
      {!collapsed && (
        <CwdView
          onFileClick={handleOpen}
          onContextMenu={handleContextMenu}
          onMove={handleMove}
          renamingPath={renamingPath}
          onSubmitRename={handleRename}
          onCancelRename={() => setRenamingPath(null)}
          selectedFilePath={selectedFilePath}
          selectedPaths={selectedPaths}
          onToggleSelection={(path) =>
            setSelectedPaths((prev) => {
              const next = new Set(prev);
              if (next.has(path)) next.delete(path);
              else next.add(path);
              return next;
            })
          }
          onReplaceSelection={(paths) => setSelectedPaths(new Set(paths))}
        />
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
  /** v0.28.1 + v0.28.2: drag-drop で移動する handler (sources, targetDir) */
  onMove: (sources: string[], targetDir: string) => Promise<void>;
  renamingPath: string | null;
  onSubmitRename: (oldPath: string, newName: string) => Promise<void>;
  onCancelRename: () => void;
  selectedFilePath: string | null;
  /** v0.28.2: multi-select 集合 (Ctrl+クリックで追加) */
  selectedPaths: Set<string>;
  onToggleSelection: (path: string) => void;
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
  selectedPaths,
  onToggleSelection,
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
            selectedPaths={selectedPaths}
            onToggleSelection={onToggleSelection}
          />
        ))}
      </ul>
    );
  }

  // v0.28.1 + v0.28.2: directory は **drop target + drag source** 両対応。
  // drag source: selectedPaths.has(自分) なら集合全体、それ以外は自分単体
  const onDragStart = (e: React.DragEvent<HTMLButtonElement>): void => {
    const sources = selectedPaths.has(path) ? Array.from(selectedPaths) : [path];
    e.dataTransfer.setData(PYFLW_PATH_MIME, serializePathsMime(sources));
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
    const raw = e.dataTransfer.getData(PYFLW_PATH_MIME);
    if (!raw) return;
    e.preventDefault();
    e.stopPropagation();
    const sources = parsePathsMime(raw);
    void onMove(sources, path);
  };

  // v0.28.2: Ctrl+クリックで selection toggle (= 既存の click =
  // expand/collapse は通常クリックのまま)
  const onClick = (e: React.MouseEvent<HTMLButtonElement>): void => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      onToggleSelection(path);
      return;
    }
    setExpanded(!expanded);
  };

  const isMultiSelected = selectedPaths.has(path);

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
        onClick={onClick}
        onContextMenu={(e) => onContextMenu(e, path, true)}
        aria-selected={isMultiSelected || undefined}
        className={`flex w-full items-center gap-1 py-0.5 text-left ${
          isDragOver
            ? "bg-blue-200"
            : isMultiSelected
              ? "bg-blue-100"
              : "hover:bg-slate-100"
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
              selectedPaths={selectedPaths}
              onToggleSelection={onToggleSelection}
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
  /** v0.28.1 + v0.28.2: drag-drop で移動する handler (sources, targetDir) */
  onMove: (sources: string[], targetDir: string) => Promise<void>;
  renamingPath: string | null;
  onSubmitRename: (oldPath: string, newName: string) => Promise<void>;
  onCancelRename: () => void;
  selectedFilePath: string | null;
  selectedPaths: Set<string>;
  onToggleSelection: (path: string) => void;
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
  selectedPaths,
  onToggleSelection,
}: TreeEntryProps): JSX.Element {
  const fullPath = parentPath ? `${parentPath}/${entry.name}` : entry.name;

  if (entry.type === "directory") {
    return (
      <DirectoryNode
        path={fullPath}
        name={entry.name}
        depth={depth}
        // v0.30.2: 起動時 depth 1 (= root 直下) まで自動展開 (= 階層が見えない
        // 印象を改善、深い階層はユーザークリックで expand)
        defaultExpanded={depth <= 1}
        onFileClick={onFileClick}
        onContextMenu={onContextMenu}
        onMove={onMove}
        renamingPath={renamingPath}
        onSubmitRename={onSubmitRename}
        onCancelRename={onCancelRename}
        selectedFilePath={selectedFilePath}
        selectedPaths={selectedPaths}
        onToggleSelection={onToggleSelection}
      />
    );
  }

  const isActive = selectedFilePath === fullPath;
  const isFlw = entry.name.endsWith(".flw.json");
  const isRenaming = renamingPath === fullPath;
  const isMultiSelected = selectedPaths.has(fullPath);

  // v0.28.1 + v0.28.2: file は drag source (drop target にはしない)。
  // selectedPaths.has(自分) なら集合全体を MIME に乗せる。
  const onDragStart = (e: React.DragEvent<HTMLButtonElement>): void => {
    const sources = selectedPaths.has(fullPath)
      ? Array.from(selectedPaths)
      : [fullPath];
    e.dataTransfer.setData(PYFLW_PATH_MIME, serializePathsMime(sources));
    e.dataTransfer.effectAllowed = "move";
  };

  // v0.28.2: Ctrl+クリック = 選択 toggle + ファイル開かない、通常クリック =
  // open + multi-select クリア (= 暗黙的に selectedPaths を空にしない、Ctrl で
  // 明示的に組み立てる)
  const onClick = (e: React.MouseEvent<HTMLButtonElement>): void => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      onToggleSelection(fullPath);
      return;
    }
    if (isFlw) onFileClick(fullPath);
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
          onClick={onClick}
          onContextMenu={(e) => onContextMenu(e, fullPath, false)}
          // file 自体は disable しない (Ctrl+click で .flw.json 以外も multi-select 候補)
          aria-selected={isMultiSelected || undefined}
          className={`flex w-full items-center gap-1 py-0.5 text-left ${
            isMultiSelected
              ? "bg-blue-100 text-blue-800"
              : isActive
                ? "bg-blue-100 text-blue-800"
                : isFlw
                  ? "text-slate-700 hover:bg-slate-100"
                  : "text-slate-400 hover:bg-slate-100"
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

// v0.31.3: FileBrowser ヘッダーのアクション アイコン (= JupyterLab toolbar 風)
function NewFileIcon(): JSX.Element {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-3.5 w-3.5"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-9" />
      <polyline points="14 3 14 9 20 9" />
      <line x1="17" y1="14" x2="17" y2="20" />
      <line x1="14" y1="17" x2="20" y2="17" />
    </svg>
  );
}

function NewFolderIcon(): JSX.Element {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-3.5 w-3.5"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />
      <line x1="12" y1="11" x2="12" y2="17" />
      <line x1="9" y1="14" x2="15" y2="14" />
    </svg>
  );
}

function RefreshIcon(): JSX.Element {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-3.5 w-3.5"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <polyline points="20 6 20 11 15 11" />
      <path d="M20 11A8 8 0 1 0 18 18" />
    </svg>
  );
}

// v0.31.0: JupyterLab 流の cwd フォーカス型 FileBrowser。
// 旧 v3.9.x まで: 階層ツリー展開 (DirectoryNode で再帰)
// 新 v0.31.0: 1 階層 flat list + breadcrumb + フォルダクリックで cd
// 既存 DirectoryNode / TreeEntry は dead code (= 削除せず温存、ロールバック用)。

interface CwdViewProps {
  onFileClick: (path: string) => void;
  onContextMenu: (
    e: React.MouseEvent,
    path: string,
    isDirectory: boolean,
  ) => void;
  onMove: (sources: string[], targetDir: string) => Promise<void>;
  renamingPath: string | null;
  onSubmitRename: (oldPath: string, newName: string) => Promise<void>;
  onCancelRename: () => void;
  selectedFilePath: string | null;
  selectedPaths: Set<string>;
  onToggleSelection: (path: string) => void;
  /** v0.31.8: marquee (矩形ドラッグ) 選択完了時に呼ばれる。引数は新しい選択集合。 */
  onReplaceSelection: (paths: string[]) => void;
}

function CwdView({
  onFileClick,
  onContextMenu,
  onMove,
  renamingPath,
  onSubmitRename,
  onCancelRename,
  selectedFilePath,
  selectedPaths,
  onToggleSelection,
  onReplaceSelection,
}: CwdViewProps): JSX.Element {
  const { t } = useTranslation();
  const cwd = useAppStore((s) => s.fileBrowserCwd);
  const setCwd = useAppStore((s) => s.setFileBrowserCwd);

  const { data, error, isLoading } = useQuery({
    queryKey: ["files-tree", cwd],
    queryFn: () => fileTree(cwd),
    enabled: true,
  });

  // breadcrumb 用に cwd を segments に分解
  const segments: Array<{ name: string; path: string }> = [];
  if (cwd) {
    const parts = cwd.split("/");
    for (let i = 0; i < parts.length; i++) {
      segments.push({
        name: parts[i]!,
        path: parts.slice(0, i + 1).join("/"),
      });
    }
  }

  const onCwdDragOver = (e: React.DragEvent<HTMLDivElement>): void => {
    if (e.dataTransfer.types.includes(PYFLW_PATH_MIME)) {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
    }
  };
  const onCwdDrop = (e: React.DragEvent<HTMLDivElement>): void => {
    const raw = e.dataTransfer.getData(PYFLW_PATH_MIME);
    if (!raw) return;
    e.preventDefault();
    const sources = parsePathsMime(raw);
    void onMove(sources, cwd);
  };

  // v0.31.8: marquee (矩形ドラッグ) 選択。空白部分から mouseDown → ドラッグ →
  // mouseUp で、矩形と各 row の bounding box が重なる行を `onReplaceSelection`
  // に通知。row 上 (= li 要素内) で開始した場合は HTML5 drag-drop に譲るため
  // marquee 起動しない (= 既存の「ファイル間移動」drag-drop と非干渉)。
  const listBodyRef = useRef<HTMLDivElement>(null);
  const [marqueeStart, setMarqueeStart] = useState<{ x: number; y: number } | null>(
    null,
  );
  const [marqueeCurrent, setMarqueeCurrent] = useState<{
    x: number;
    y: number;
  } | null>(null);

  const onListBodyMouseDown = (e: React.MouseEvent<HTMLDivElement>): void => {
    if (e.button !== 0) return; // 左クリックのみ
    const target = e.target as HTMLElement;
    if (target.closest('li[data-pyflw-path]')) return; // row の上は drag-drop に譲る
    setMarqueeStart({ x: e.clientX, y: e.clientY });
    setMarqueeCurrent({ x: e.clientX, y: e.clientY });
  };

  useEffect(() => {
    if (!marqueeStart) return;
    const onMove = (e: MouseEvent): void => {
      setMarqueeCurrent({ x: e.clientX, y: e.clientY });
    };
    const onUp = (_e: MouseEvent): void => {
      const list = listBodyRef.current;
      if (list && marqueeStart && marqueeCurrent) {
        const x1 = Math.min(marqueeStart.x, marqueeCurrent.x);
        const y1 = Math.min(marqueeStart.y, marqueeCurrent.y);
        const x2 = Math.max(marqueeStart.x, marqueeCurrent.x);
        const y2 = Math.max(marqueeStart.y, marqueeCurrent.y);
        const distance = Math.hypot(x2 - x1, y2 - y1);
        if (distance < 4) {
          // 移動距離が極小 = 単なる空白クリックとして扱い、選択をクリア
          onReplaceSelection([]);
        } else {
          const rows = list.querySelectorAll<HTMLElement>("li[data-pyflw-path]");
          const hits: string[] = [];
          rows.forEach((row) => {
            const r = row.getBoundingClientRect();
            if (r.left < x2 && r.right > x1 && r.top < y2 && r.bottom > y1) {
              const p = row.dataset.pyflwPath;
              if (p) hits.push(p);
            }
          });
          onReplaceSelection(hits);
        }
      }
      setMarqueeStart(null);
      setMarqueeCurrent(null);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
  }, [marqueeStart, marqueeCurrent, onReplaceSelection]);

  // marquee overlay の `position: absolute` 値 (= list body 相対座標)
  const marqueeRect = ((): {
    left: number;
    top: number;
    width: number;
    height: number;
  } | null => {
    if (!marqueeStart || !marqueeCurrent || !listBodyRef.current) return null;
    const listRect = listBodyRef.current.getBoundingClientRect();
    const x1 = Math.min(marqueeStart.x, marqueeCurrent.x) - listRect.left;
    const y1 = Math.min(marqueeStart.y, marqueeCurrent.y) - listRect.top;
    const x2 = Math.max(marqueeStart.x, marqueeCurrent.x) - listRect.left;
    const y2 = Math.max(marqueeStart.y, marqueeCurrent.y) - listRect.top;
    if (x2 - x1 < 2 && y2 - y1 < 2) return null; // 描画閾値
    return { left: x1, top: y1, width: x2 - x1, height: y2 - y1 };
  })();

  return (
    <div
      className="flex min-h-0 flex-1 flex-col overflow-hidden"
      onContextMenu={(e) => onContextMenu(e, cwd, true)}
    >
      {/* Breadcrumb 行 (JupyterLab 風) */}
      <div className="flex h-6 shrink-0 items-center gap-0.5 overflow-x-auto border-b border-slate-200 bg-slate-50 px-1 text-[11px] text-slate-600">
        <button
          type="button"
          onClick={() => setCwd("")}
          title={t("filebrowser.breadcrumb.root")}
          aria-label={t("filebrowser.breadcrumb.root")}
          className="flex h-5 w-5 shrink-0 items-center justify-center text-slate-500 hover:bg-slate-200 hover:text-slate-800"
        >
          {/* home icon */}
          <svg
            viewBox="0 0 24 24"
            className="h-3.5 w-3.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M3 12 12 3l9 9" />
            <path d="M5 10v10h14V10" />
          </svg>
        </button>
        {cwd && (
          <button
            type="button"
            onClick={() => {
              const idx = cwd.lastIndexOf("/");
              setCwd(idx < 0 ? "" : cwd.slice(0, idx));
            }}
            title={t("filebrowser.breadcrumb.up")}
            aria-label={t("filebrowser.breadcrumb.up")}
            className="flex h-5 w-5 shrink-0 items-center justify-center text-slate-500 hover:bg-slate-200 hover:text-slate-800"
          >
            {/* up arrow */}
            <svg
              viewBox="0 0 24 24"
              className="h-3.5 w-3.5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polyline points="6 12 12 6 18 12" />
              <line x1="12" y1="6" x2="12" y2="20" />
            </svg>
          </button>
        )}
        {segments.map((seg, i) => (
          <span key={seg.path} className="flex shrink-0 items-center gap-0.5">
            <span className="text-slate-400" aria-hidden>
              /
            </span>
            <button
              type="button"
              onClick={() => setCwd(seg.path)}
              className={`shrink-0 px-1 ${
                i === segments.length - 1
                  ? "font-semibold text-slate-700"
                  : "text-slate-500 hover:text-slate-800 hover:underline"
              }`}
              title={seg.path}
            >
              {seg.name}
            </button>
          </span>
        ))}
      </div>
      {/* flat list 本体 (= marquee overlay の anchor として relative にする) */}
      <div
        ref={listBodyRef}
        className="relative min-h-0 flex-1 overflow-y-auto py-1"
        onDragOver={onCwdDragOver}
        onDrop={onCwdDrop}
        onMouseDown={onListBodyMouseDown}
      >
        {error instanceof FileApiUnavailableError && (
          <div className="px-3 py-2 text-[11px] text-amber-600">
            {t(
              "filebrowser.disabled",
              "File API not enabled. Restart pyflw-server with --workspace=PATH.",
            )}
          </div>
        )}
        {isLoading && (
          <div className="px-3 py-2 text-[11px] text-slate-400">
            {t("filebrowser.loading", "Loading…")}
          </div>
        )}
        {error && !(error instanceof FileApiUnavailableError) && (
          <div className="px-3 py-2 text-[11px] text-rose-600">
            {String((error as Error).message)}
          </div>
        )}
        {data && data.children.length === 0 && (
          <div className="px-3 py-2 text-[11px] text-slate-400">
            {t("filebrowser.empty_folder", "(empty folder)")}
          </div>
        )}
        {data && data.children.length > 0 && (
          <ul role="list" className="select-none">
            {/* directory を先頭、file を後ろにソート (= 一般的なファイラー慣習) */}
            {[...data.children]
              .sort((a, b) => {
                if (a.type !== b.type) return a.type === "directory" ? -1 : 1;
                return a.name.localeCompare(b.name);
              })
              .map((entry) => (
                <CwdEntryRow
                  key={entry.name}
                  entry={entry}
                  parentPath={cwd}
                  onFileClick={onFileClick}
                  onFolderClick={(path) => setCwd(path)}
                  onContextMenu={onContextMenu}
                  onMove={onMove}
                  renamingPath={renamingPath}
                  onSubmitRename={onSubmitRename}
                  onCancelRename={onCancelRename}
                  selectedFilePath={selectedFilePath}
                  selectedPaths={selectedPaths}
                  onToggleSelection={onToggleSelection}
                />
              ))}
          </ul>
        )}
        {/* v0.31.8: marquee overlay。pointer-events-none で配下 row のクリックを
            妨げない (= mousemove は document に attach 済) */}
        {marqueeRect && (
          <div
            className="pointer-events-none absolute border border-blue-500/60 bg-blue-300/20"
            style={{
              left: marqueeRect.left,
              top: marqueeRect.top,
              width: marqueeRect.width,
              height: marqueeRect.height,
            }}
            aria-hidden
          />
        )}
      </div>
    </div>
  );
}

interface CwdEntryRowProps {
  entry: FileEntry;
  parentPath: string;
  onFileClick: (path: string) => void;
  onFolderClick: (path: string) => void;
  onContextMenu: (
    e: React.MouseEvent,
    path: string,
    isDirectory: boolean,
  ) => void;
  onMove: (sources: string[], targetDir: string) => Promise<void>;
  renamingPath: string | null;
  onSubmitRename: (oldPath: string, newName: string) => Promise<void>;
  onCancelRename: () => void;
  selectedFilePath: string | null;
  selectedPaths: Set<string>;
  onToggleSelection: (path: string) => void;
}

function CwdEntryRow({
  entry,
  parentPath,
  onFileClick,
  onFolderClick,
  onContextMenu,
  onMove,
  renamingPath,
  onSubmitRename,
  onCancelRename,
  selectedFilePath,
  selectedPaths,
  onToggleSelection,
}: CwdEntryRowProps): JSX.Element {
  const fullPath = parentPath ? `${parentPath}/${entry.name}` : entry.name;
  const isDir = entry.type === "directory";
  const isFlw = !isDir && entry.name.endsWith(".flw.json");
  const isRenaming = renamingPath === fullPath;
  const isActive = !isDir && selectedFilePath === fullPath;
  const isMultiSelected = selectedPaths.has(fullPath);
  const [isDragOver, setIsDragOver] = useState(false);

  const onDragStart = (e: React.DragEvent<HTMLLIElement>): void => {
    const sources = selectedPaths.has(fullPath)
      ? Array.from(selectedPaths)
      : [fullPath];
    e.dataTransfer.setData(PYFLW_PATH_MIME, serializePathsMime(sources));
    e.dataTransfer.effectAllowed = "move";
  };
  const onDragOver = (e: React.DragEvent<HTMLLIElement>): void => {
    if (!isDir) return;
    if (!e.dataTransfer.types.includes(PYFLW_PATH_MIME)) return;
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = "move";
    setIsDragOver(true);
  };
  const onDragLeave = (e: React.DragEvent<HTMLLIElement>): void => {
    if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
    setIsDragOver(false);
  };
  const onDrop = (e: React.DragEvent<HTMLLIElement>): void => {
    if (!isDir) return;
    setIsDragOver(false);
    const raw = e.dataTransfer.getData(PYFLW_PATH_MIME);
    if (!raw) return;
    e.preventDefault();
    e.stopPropagation();
    const sources = parsePathsMime(raw);
    void onMove(sources, fullPath);
  };

  const onClick = (e: React.MouseEvent): void => {
    // v0.31.10: Shift+click も Ctrl+click と同じ toggle 動作にする
    // (= ユーザー要望「Shift で個別選択を複数選択状態にする」)
    if (e.ctrlKey || e.metaKey || e.shiftKey) {
      e.preventDefault();
      onToggleSelection(fullPath);
      return;
    }
    if (isDir) {
      onFolderClick(fullPath);
    } else if (isFlw) {
      onFileClick(fullPath);
    }
  };

  return (
    <li
      role="listitem"
      // v0.31.8: data attribute で marquee 衝突判定の対象を識別
      data-pyflw-path={fullPath}
      draggable={!isRenaming}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      onContextMenu={(e) => onContextMenu(e, fullPath, isDir)}
    >
      {isRenaming ? (
        <InlineRename
          initialValue={entry.name}
          depth={0}
          onSubmit={(newName) => void onSubmitRename(fullPath, newName)}
          onCancel={onCancelRename}
        />
      ) : (
        <button
          type="button"
          onClick={onClick}
          disabled={!isDir && !isFlw}
          className={`flex w-full items-center gap-1.5 px-2 py-0.5 text-left text-[12px] ${
            isDragOver
              ? "bg-blue-200"
              : isMultiSelected
                ? "bg-blue-100 text-blue-800"
                : isActive
                  ? "bg-blue-100 text-blue-800"
                  : isDir
                    ? "text-slate-700 hover:bg-slate-100"
                    : isFlw
                      ? "text-slate-700 hover:bg-slate-100"
                      : "text-slate-400 hover:bg-slate-100"
          }`}
          title={fullPath}
          aria-selected={isMultiSelected || undefined}
        >
          {isDir ? <FolderIcon /> : <FileIcon flw={isFlw} />}
          <span className="truncate">{entry.name}</span>
        </button>
      )}
    </li>
  );
}
