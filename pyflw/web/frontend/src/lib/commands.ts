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

import { deleteFile, fileTree, getFileContent } from "../api/filesApi";
import { queryClient } from "./queryClient";
import { addRecentFile, readRecentFiles } from "./recentFiles";
import {
  localizedDisplayName,
  searchableDisplayNames,
} from "./blockI18n";
import {
  addBlockToEditing,
  addConnectionToEditing,
  useAppStore,
} from "../store/appStore";
import { resolveBlocksAtPath } from "./pathResolver";
import { buildDefaultParams, generateUniqueId } from "./idGenerator";
import type { BlockMetadata } from "../types/api";

/** category 別の並び順 (= UI 上の表示順、関係ない category は末尾)。 */
export type CommandCategory =
  | "file"
  | "edit"
  | "simulation"
  | "view"
  | "workspace"
  | "block";

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

/** category の表示順序 (= ローカル UI 用、enum 列順を使う)。
 * "block" は数 30+ で多いため最後にして、初期表示で他 category を見つけやすく。 */
const CATEGORY_ORDER: CommandCategory[] = [
  "file",
  "edit",
  "simulation",
  "view",
  "workspace",
  "block",
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

    // v0.31.1: 不要な untitled* を一括削除 (= ADR-0041 副作用バグの後始末)
    {
      id: "workspace.cleanup_untitled",
      category: "workspace",
      labelKey: "command.workspace.cleanup_untitled",
      keywords: ["cleanup", "untitled", "整理", "削除", "クリーンアップ"],
      action: async () => {
        await cleanupUntitled();
      },
    },
  ];
}

/** v0.31.1: workspace 直下の `untitled*.flw.json` のうち、現在のタブ群に
 * 開かれていないもの **すべて** を順次削除する。confirm dialog で個数を確認。
 *
 * 安全策:
 * - 現在 active な tab の path は除外
 * - 開いている tabs[] の path も除外
 * - workspace root の **直下のみ** 対象 (= サブフォルダの untitled は対象外、
 *   サブフォルダ内の作業データを誤削除しないため)
 */
async function cleanupUntitled(): Promise<void> {
  const state = useAppStore.getState();
  const openPaths = new Set(state.tabs.map((tab) => tab.filePath));
  if (state.activeTabFilePath) openPaths.add(state.activeTabFilePath);
  let listing;
  try {
    listing = await fileTree("");
  } catch (e) {
    window.alert(`Cleanup failed: ${(e as Error).message}`);
    return;
  }
  const targets = listing.children
    .filter(
      (entry) =>
        entry.type === "file" &&
        /^untitled\d*\.flw\.json$/.test(entry.name) &&
        !openPaths.has(entry.name),
    )
    .map((entry) => entry.name);
  if (targets.length === 0) {
    window.alert(
      "No unused untitled files found at workspace root.\n" +
        "(現在 tab で開かれていない untitled*.flw.json は見つかりませんでした)",
    );
    return;
  }
  const ok = window.confirm(
    `Delete ${targets.length} unused untitled file(s) at workspace root?\n\n` +
      targets.slice(0, 20).join("\n") +
      (targets.length > 20 ? `\n... and ${targets.length - 20} more` : ""),
  );
  if (!ok) return;
  let success = 0;
  const failures: string[] = [];
  for (const path of targets) {
    try {
      await deleteFile(path);
      success++;
    } catch (e) {
      failures.push(`${path}: ${(e as Error).message}`);
    }
  }
  // v0.31.2: 削除後に FileBrowser の React Query cache を invalidate
  // (= 自動 refresh、ユーザーが手動で 🔄 を押さなくて済む)
  await queryClient.invalidateQueries({ queryKey: ["files-tree"] });
  if (failures.length > 0) {
    window.alert(
      `Cleaned ${success} / ${targets.length}.\nFailed:\n${failures.slice(0, 10).join("\n")}`,
    );
  } else {
    window.alert(`Cleaned ${success} untitled files.`);
  }
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

/** v0.29.2: block-registry を動的 command として展開。
 *
 * 各 block_metadata に対し ``block.add:<type_path>`` command を生成、
 * Ctrl+Shift+P → 「Gain」「constant」「ブロック」等で検索 → Enter で canvas に
 * デフォルト位置で追加。実装は BlockPalette の drag-drop と同じ路線
 * (= ``addBlockToEditing(block, position)``)。
 *
 * **位置決定**: 既存 block の bounding box の右下 + 140 px offset、無ければ
 * (100, 100)。React Flow の viewport center 取得は CommandPalette modal が
 * focus を握っているため複雑なので、上記 heuristics で十分。
 *
 * **enabled**: ``editingModel !== null`` (= ファイル未開時は灰色表示)
 *
 * @param blocks backend ``listBlockMetadata()`` の結果配列
 */
export function buildBlockAddCommands(blocks: BlockMetadata[]): Command[] {
  return blocks.map((meta) => ({
    id: `block.add:${meta.type_path}`,
    category: "block" as const,
    labelKey: "command.block.add",
    // v0.29.4: ADR-0028 display_name_i18n 経由で現在 locale の表示名を使用。
    // 言語切替時は CommandPalette の useMemo deps (i18n.language) で再構築。
    dynamicSuffix: localizedDisplayName(meta),
    // v0.29.4: searchableDisplayNames は両言語 (ja/en) + type_path 末尾を返す
    // ため、ja 環境でも英語名 "Sum" で検索可能 (= Simulink 経験者向けセーフネット、
    // ADR-0028 §(4))。type_path / category / tags は補助検索用に併用。
    keywords: [
      ...searchableDisplayNames(meta),
      meta.type_path,
      meta.type_path.toLowerCase(),
      meta.category,
      ...(meta.tags ?? []),
    ],
    enabled: () => useAppStore.getState().editingModel !== null,
    action: () => {
      const state = useAppStore.getState();
      const model = state.editingModel;
      if (!model) return;
      let view;
      try {
        view = resolveBlocksAtPath(model, state.editingPath);
      } catch {
        return;
      }
      // 既存 ID 集合 + 一意 ID 採番
      const existingIds = new Set(view.blocks.map((b) => b.id));
      const newId = generateUniqueId(meta.type_path, existingIds);

      // v0.29.3: Quick Insert (= Simulink 流)。selectedNodeIds が 1 個なら
      // **その block の右側 (+140 px) に配置 + auto-connect** (= src.out[0]
      // → new.in[0])。複数選択 / 未選択時は従来の bounding box heuristics。
      const selectedIds = state.selectedNodeIds;
      const singleSelected =
        selectedIds.length === 1
          ? view.blocks.find((b) => b.id === selectedIds[0])
          : undefined;

      let x = 100;
      let y = 100;
      if (singleSelected) {
        // single selection: 右隣に並べる
        const pos = view.layout[singleSelected.id];
        if (pos) {
          x = pos.x + 140;
          y = pos.y;
        }
      } else {
        // 通常: 既存 block の bounding box の右下 + offset
        const positions = view.blocks
          .map((b) => view.layout[b.id])
          .filter((p): p is { x: number; y: number } => p != null);
        if (positions.length > 0) {
          x = Math.max(...positions.map((p) => p.x)) + 140;
          y = Math.min(...positions.map((p) => p.y));
        }
      }

      const newBlock = {
        id: newId,
        type: meta.type_path,
        params: buildDefaultParams(meta.params_spec, {
          isContainer: meta.is_container,
        }),
      };
      addBlockToEditing(newBlock, { x, y });

      // v0.29.3 Quick Insert: 新 block が入力を持ち、かつ singleSelected が
      // 出力を持つなら auto-connect (= source.out[0] → new.in[0])
      if (
        singleSelected !== undefined &&
        meta.default_n_inputs > 0 &&
        !meta.is_container // Subsystem は内部接続が複雑なので skip
      ) {
        // ADR-0039 派生 property: Subsystem の n_outputs は registry の
        // default_n_outputs ではなく内部 Outport 数で決まるが、Quick Insert
        // 元の selectedSource は通常ブロック想定 (= subsystem を source に
        // 選んでいる場合も view.blocks に居るので connect 自体は OK)
        addConnectionToEditing({
          src: singleSelected.id,
          src_idx: 0,
          dst: newId,
          dst_idx: 0,
        });
        // selection を新 block に移す (= 連続 Quick Insert で「→ Gain →
        // Scope」のように直列追加できる、Simulink 流儀)
        state.selectNode(newId);
      }
    },
  }));
}
