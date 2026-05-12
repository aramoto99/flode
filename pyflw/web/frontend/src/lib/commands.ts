// v0.29.0: コマンドパレット (Ctrl+Shift+P) 用の command registry。
//
// pyflw 内の主要操作を 1 ヶ所に集約し、ユーザーが名前検索で発火できるように
// する (= JupyterLab / VSCode 流)。
//
// **実装方針**: 各 command の ``action`` は **store action 直接呼出し** か
// **synthetic keyboard event dispatch** で既存 shortcut path を再利用する。
// ``useSimulation`` などの hook を CommandPalette 内部で重複 instance 化
// しないため、Ctrl+T (= sim.run) / Ctrl+S (= file.save) / Ctrl+N (= file.new)
// 等は KeyboardEvent を window.dispatchEvent で投げて、既存 ``useShortcuts``
// / ``useAutoSave`` / ``MenuBar`` の listener に処理させる。

import { getFileContent } from "../api/filesApi";
import { addRecentFile, readRecentFiles } from "./recentFiles";
import { useAppStore } from "../store/appStore";

/** category 別の並び順 (= UI 上の表示順、関係ない category は末尾)。 */
export type CommandCategory =
  | "file"
  | "edit"
  | "simulation"
  | "view"
  | "workspace";

export interface Command {
  /** 一意 ID (= "file.new" 等の dot 区切り)、i18n key にも流用。 */
  id: string;
  /** category (= UI で grouping、検索フィルタには使わない)。 */
  category: CommandCategory;
  /** 表示ラベルの i18n key (= ``t(labelKey)`` で取得)。 */
  labelKey: string;
  /** v0.29.1: 表示用 suffix (= ``t(labelKey)`` の後ろに ": <suffix>" 形式で
   * 連結される)。動的 command (= Recent Files のように同じ labelKey で複数
   * 行を出す) で path / 引数を表示するために使う。 */
  dynamicSuffix?: string;
  /** キーボードショートカット表示 (= 任意、UI 右端に表示)。 */
  shortcut?: string;
  /** 検索対象キーワード (= label に加えて検索される、英日混在 OK)。 */
  keywords?: string[];
  /** 発火時の動作。close は呼出し側 (CommandPalette) が paletteClose する。 */
  action: () => void | Promise<void>;
  /** 実行可能か (= disable 表示する判定)。デフォルト = 常に有効。 */
  enabled?: () => boolean;
}

/** category の表示順序 (= ローカル UI 用、enum 列順を使う)。 */
const CATEGORY_ORDER: CommandCategory[] = [
  "file",
  "edit",
  "simulation",
  "view",
  "workspace",
];

/** category を比較 (= sort 用)。 */
export function compareCategory(a: CommandCategory, b: CommandCategory): number {
  return CATEGORY_ORDER.indexOf(a) - CATEGORY_ORDER.indexOf(b);
}

/** コマンド検索の substring match (= 大文字小文字無視、簡易実装)。
 * label + keywords を 1 つの target string に連結して match。 */
export function commandMatches(cmd: Command, label: string, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (q.length === 0) return true;
  const target = [label, ...(cmd.keywords ?? [])].join(" ").toLowerCase();
  return target.includes(q);
}

// ---------------------------------------------------------------------------
// Command actions (= helper closures、循環参照を避けるため hook 化せず
// store.getState() で直接 store 操作 / API 呼出し / window dispatch を行う)
// ---------------------------------------------------------------------------

function dispatchOpenSearch(kind: "path" | "content"): void {
  const state = useAppStore.getState();
  state.setSidebarMode("search");
  if (state.workspaceCollapsed) state.setWorkspaceCollapsed(false);
  window.dispatchEvent(
    new CustomEvent("pyflw:open-search", { detail: { kind } }),
  );
}

/** v0.29.0: 既存 shortcut path を再利用するために synthetic keyboard event を
 * 発火するヘルパー。CommandPalette が close されてから setTimeout 0 で投げる
 * (= input から focus が外れ、useShortcuts の isTextEditing チェックを通過
 * できる状態にする)。 */
function dispatchShortcut(opts: {
  key: string;
  ctrl?: boolean;
  shift?: boolean;
}): void {
  setTimeout(() => {
    window.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: opts.key,
        ctrlKey: opts.ctrl ?? false,
        shiftKey: opts.shift ?? false,
        bubbles: true,
        cancelable: true,
      }),
    );
  }, 0);
}

/** 全 command を返す (= registry の static エクスポート)。 */
export function buildCommandRegistry(): Command[] {
  return [
    // File (= MenuBar / useAutoSave の Ctrl+N / Ctrl+S listener に dispatch)
    {
      id: "file.new",
      category: "file",
      labelKey: "command.file.new",
      shortcut: "Ctrl+N",
      keywords: ["new", "新規", "作成"],
      action: () => dispatchShortcut({ key: "n", ctrl: true }),
    },
    {
      id: "file.save",
      category: "file",
      labelKey: "command.file.save",
      shortcut: "Ctrl+S",
      keywords: ["save", "保存"],
      action: () => dispatchShortcut({ key: "s", ctrl: true }),
    },

    // Edit (= store action 直接呼出し)
    {
      id: "edit.undo",
      category: "edit",
      labelKey: "command.edit.undo",
      shortcut: "Ctrl+Z",
      keywords: ["undo", "元に戻す"],
      action: () => useAppStore.getState().undo(),
      enabled: () => useAppStore.getState().canUndo(),
    },
    {
      id: "edit.redo",
      category: "edit",
      labelKey: "command.edit.redo",
      shortcut: "Ctrl+Y",
      keywords: ["redo", "やり直し"],
      action: () => useAppStore.getState().redo(),
      enabled: () => useAppStore.getState().canRedo(),
    },

    // Simulation (= useShortcuts の Ctrl+T / Ctrl+Shift+T listener に dispatch)
    {
      id: "simulation.run",
      category: "simulation",
      labelKey: "command.simulation.run",
      shortcut: "Ctrl+T",
      keywords: ["run", "start", "実行", "開始"],
      action: () => dispatchShortcut({ key: "t", ctrl: true }),
    },
    {
      id: "simulation.stop",
      category: "simulation",
      labelKey: "command.simulation.stop",
      shortcut: "Ctrl+Shift+T",
      keywords: ["stop", "停止"],
      action: () => dispatchShortcut({ key: "t", ctrl: true, shift: true }),
    },

    // View (= store action 直接呼出し)
    {
      id: "view.toggle_sidebar",
      category: "view",
      labelKey: "command.view.toggle_sidebar",
      shortcut: "Ctrl+B",
      keywords: ["sidebar", "toggle", "サイドバー", "切替"],
      action: () => {
        const s = useAppStore.getState();
        s.setWorkspaceCollapsed(!s.workspaceCollapsed);
      },
    },
    {
      id: "view.sidebar_file",
      category: "view",
      labelKey: "command.view.sidebar_file",
      shortcut: "Ctrl+Shift+E",
      keywords: ["file", "explorer", "ファイル", "エクスプローラ"],
      action: () => {
        const s = useAppStore.getState();
        s.setSidebarMode("file");
        if (s.workspaceCollapsed) s.setWorkspaceCollapsed(false);
      },
    },
    {
      id: "view.sidebar_library",
      category: "view",
      labelKey: "command.view.sidebar_library",
      keywords: ["library", "palette", "ライブラリ", "パレット"],
      action: () => {
        const s = useAppStore.getState();
        s.setSidebarMode("library");
        if (s.workspaceCollapsed) s.setWorkspaceCollapsed(false);
      },
    },
    {
      id: "view.sidebar_search_path",
      category: "view",
      labelKey: "command.view.sidebar_search_path",
      shortcut: "Ctrl+P",
      keywords: ["search", "path", "検索", "パス"],
      action: () => dispatchOpenSearch("path"),
    },
    {
      id: "view.sidebar_search_content",
      category: "view",
      labelKey: "command.view.sidebar_search_content",
      shortcut: "Ctrl+Shift+F",
      keywords: ["search", "content", "find", "検索", "内容"],
      action: () => dispatchOpenSearch("content"),
    },
    {
      id: "view.toggle_inspector",
      category: "view",
      labelKey: "command.view.toggle_inspector",
      keywords: ["inspector", "panel", "インスペクタ"],
      action: () => {
        const s = useAppStore.getState();
        s.setInspectorCollapsed(!s.inspectorCollapsed);
      },
    },
  ];
}

/** v0.29.1: 現在のワークスペースの Recent Files を動的 command として展開。
 *
 * Launcher の Recent list と同じデータソース (= ``readRecentFiles(workspaceHash)``)
 * から最大 ``limit`` 件 (= 既定 10) を生成。各 command は **直接 REST 呼出し**
 * (= getFileContent + openFileInTab) で synthetic keyboard event を経由しない。
 *
 * 検索 query 例:
 * - ja: 「最近 spring」 → 「最近: models/spring_mass_damper.flw.json」が match
 * - en: "recent pid"   → "Recent: models/pid_controller.flw.json" が match
 *
 * @param workspaceHash 現在のワークスペース hash (= ``store.workspaceHash``)
 * @param limit         最大件数 (= 既定 10、コマンドパレット視認性のため抑制)
 */
export function buildRecentFileCommands(
  workspaceHash: string | null,
  limit: number = 10,
): Command[] {
  if (!workspaceHash) return [];
  const recent = readRecentFiles(workspaceHash).slice(0, limit);
  return recent.map((path) => ({
    id: `file.open_recent:${path}`,
    category: "file" as const,
    // 共通 labelKey で "最近のファイル" / "Recent file" を表示、suffix で path を連結
    labelKey: "command.file.open_recent",
    dynamicSuffix: path,
    keywords: ["recent", "open", "最近", "開く", path, path.toLowerCase()],
    action: async () => {
      try {
        const data = await getFileContent(path);
        const state = useAppStore.getState();
        state.openFileInTab(path, data.content, data.mtime, data.etag);
        addRecentFile(workspaceHash, path);
      } catch (e) {
        console.error("CommandPalette: open recent failed:", path, e);
        window.alert(`Open failed: ${(e as Error).message}`);
      }
    },
  }));
}
