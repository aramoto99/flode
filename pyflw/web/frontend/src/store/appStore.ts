// アプリ状態 store (ADR-0012 §(5)、ADR-0019 §(5) で編集状態 + auto-save 拡張)。

import { create } from "zustand";

import {
  ENABLE_TYPE,
  getNumberParam,
  INPORT_TYPE,
  OUTPORT_TYPE,
  TRIGGER_TYPE,
} from "../lib/blockTypes";
import { resolvePortCounts } from "../lib/dynamicPorts";
import { findBlockPath } from "../lib/findBlockPath";
import {
  applyAtPath,
  applyBranchWaypointsAtPath,
  pruneBranchWaypoints,
  resolveBlocksAtPath,
  resolveBranchWaypointsAtPath,
} from "../lib/pathResolver";
import {
  appendBatch as appendScopeBatchSoA,
  createBuffer as createScopeBuffer,
  type ScopeBuffer,
} from "../lib/scopeBuffer";
import {
  chooseInitialTree,
  DEFAULT_TREE,
  DEFAULT_TREE_WITH_SCOPES,
  findLeaf,
  insertSplit,
  removeLeaf,
  renameLeaf as splitTreeRenameLeaf,
  serializeTree,
  setSplitRatio as splitTreeSetRatio,
  toggleSplitOrientation as splitTreeToggleOrientation,
  type SplitTree,
} from "../lib/splitTree";
import { makeWorkspaceLayoutKey } from "../lib/storageKeys";
import type {
  BlockEntry,
  BlockMetadata,
  BranchWaypoint,
  BranchWaypointDict,
  ConnectionEntry,
  FailurePayload,
  FlwModel,
  LayoutDict,
  MaskValuesDict,
  SimulationStatus,
  SimulatorConfig,
  StreamMessage,
  TEnd,
} from "../types/api";

// ADR-0058 §論点 10: ファイルロード時の schema migration toast 通知用。
// toastStore は appStore に依存しない (= 循環依存なし、静的 import で OK)。
import { pushToast } from "./toastStore";

// ADR-0023 §Decision §(3): ScopeBuffer は ``../lib/scopeBuffer`` に SoA 実装を抽出。
// ここでは re-export して既存 import (= ScopeView / XYGraphView / BlockNodeView 経由) を
// 壊さないように維持する。
export type { ScopeBuffer };

/** v0.20.0: undo/redo の最大履歴サイズ (= 過去 N 状態まで保持)。
 *
 * 1 モデル = 数 KB〜数 MB の dict (= deep-clone コスト前提)、50 件 × 平均
 * 100 KB ≒ 5 MB に収まる想定。利用者の編集回数 50 を超えたら一番古い履歴
 * から drop。 */
export const HISTORY_MAX = 50;

function deepCloneModel(m: FlwModel): FlwModel {
  return JSON.parse(JSON.stringify(m)) as FlwModel;
}

const WORKSPACE_COLLAPSE_STORAGE_KEY = "pyflw.workspace_collapsed";
const INSPECTOR_COLLAPSE_STORAGE_KEY = "pyflw.inspector_collapsed";
const SIDEBAR_MODE_STORAGE_KEY = "pyflw.sidebar_mode";
const INSPECTOR_DOCK_MODE_STORAGE_KEY = "pyflw.inspector_dock_mode";

type SidebarMode = "file" | "library" | "search";
type InspectorDockMode = "sidebar" | "pane" | "float";

function readSidebarMode(): SidebarMode {
  try {
    const v = window.localStorage.getItem(SIDEBAR_MODE_STORAGE_KEY);
    if (v === "library" || v === "search") return v;
    return "file"; // default
  } catch {
    return "file";
  }
}

function writeSidebarMode(mode: SidebarMode): void {
  try {
    window.localStorage.setItem(SIDEBAR_MODE_STORAGE_KEY, mode);
  } catch {
    // quota / private mode は黙って失敗
  }
}

// ADR-0052 §(2) Stage 3: Inspector dock mode の localStorage 永続化。
function readInspectorDockMode(): InspectorDockMode {
  try {
    const v = window.localStorage.getItem(INSPECTOR_DOCK_MODE_STORAGE_KEY);
    if (v === "pane" || v === "float") return v;
    return "sidebar"; // default (= 現状温存、利用者の慣行)
  } catch {
    return "sidebar";
  }
}

function writeInspectorDockMode(mode: InspectorDockMode): void {
  try {
    window.localStorage.setItem(INSPECTOR_DOCK_MODE_STORAGE_KEY, mode);
  } catch {
    // 同上
  }
}

/** ADR-0045 §(3-B): Workspace SplitTree を localStorage に永続化する。
 * ``workspaceHash`` / ``activeTabFilePath`` のいずれかが未確定なら no-op
 * (= 起動直後 / タブ未選択時)。 */
function persistWorkspaceLayoutFor(
  workspaceHash: string | null,
  activeTabFilePath: string | null,
  layout: SplitTree,
): void {
  if (workspaceHash === null || activeTabFilePath === null) return;
  const key = makeWorkspaceLayoutKey(workspaceHash, activeTabFilePath);
  try {
    window.localStorage.setItem(key, serializeTree(layout));
  } catch {
    // localStorage 不可環境 (= quota / private mode) は session 内のみ反映
  }
}

/** localStorage から FileBrowser 折りたたみ状態を復元 (= 起動時 default)。 */
function readWorkspaceCollapsed(): boolean {
  try {
    return window.localStorage.getItem(WORKSPACE_COLLAPSE_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function writeWorkspaceCollapsed(collapsed: boolean): void {
  try {
    if (collapsed) {
      window.localStorage.setItem(WORKSPACE_COLLAPSE_STORAGE_KEY, "1");
    } else {
      window.localStorage.removeItem(WORKSPACE_COLLAPSE_STORAGE_KEY);
    }
  } catch {
    // localStorage 不可環境では session 内のみ反映
  }
}

/** localStorage から Inspector 折りたたみ状態を復元 (= 起動時 default)。 */
function readInspectorCollapsed(): boolean {
  try {
    return window.localStorage.getItem(INSPECTOR_COLLAPSE_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function writeInspectorCollapsed(collapsed: boolean): void {
  try {
    if (collapsed) {
      window.localStorage.setItem(INSPECTOR_COLLAPSE_STORAGE_KEY, "1");
    } else {
      window.localStorage.removeItem(INSPECTOR_COLLAPSE_STORAGE_KEY);
    }
  } catch {
    // localStorage 不可環境では session 内のみ反映
  }
}

const LEFT_SIDEBAR_WIDTH_STORAGE_KEY = "pyflw.left_sidebar_width";
const LEFT_SIDEBAR_DEFAULT_PX = 240;
const LEFT_SIDEBAR_MIN_PX = 160;
const LEFT_SIDEBAR_MAX_PX = 600;

// v0.30.4: Inspector 横幅永続化 + clamp 値。
const INSPECTOR_WIDTH_STORAGE_KEY = "pyflw.inspector_width";
const INSPECTOR_DEFAULT_PX = 280;
const INSPECTOR_MIN_PX = 200;
const INSPECTOR_MAX_PX = 600;

function readLeftSidebarWidth(): number {
  try {
    const raw = window.localStorage.getItem(LEFT_SIDEBAR_WIDTH_STORAGE_KEY);
    if (!raw) return LEFT_SIDEBAR_DEFAULT_PX;
    const n = Number(raw);
    if (!Number.isFinite(n)) return LEFT_SIDEBAR_DEFAULT_PX;
    return Math.max(LEFT_SIDEBAR_MIN_PX, Math.min(LEFT_SIDEBAR_MAX_PX, n));
  } catch {
    return LEFT_SIDEBAR_DEFAULT_PX;
  }
}

function writeLeftSidebarWidth(px: number): void {
  try {
    window.localStorage.setItem(
      LEFT_SIDEBAR_WIDTH_STORAGE_KEY,
      String(Math.round(px)),
    );
  } catch {
    // 同上
  }
}

// v0.30.4: Inspector 横幅 localStorage helper。
function readInspectorWidth(): number {
  try {
    const raw = window.localStorage.getItem(INSPECTOR_WIDTH_STORAGE_KEY);
    if (!raw) return INSPECTOR_DEFAULT_PX;
    const n = Number(raw);
    if (!Number.isFinite(n)) return INSPECTOR_DEFAULT_PX;
    return Math.max(INSPECTOR_MIN_PX, Math.min(INSPECTOR_MAX_PX, n));
  } catch {
    return INSPECTOR_DEFAULT_PX;
  }
}

function writeInspectorWidth(px: number): void {
  try {
    window.localStorage.setItem(
      INSPECTOR_WIDTH_STORAGE_KEY,
      String(Math.round(px)),
    );
  } catch {
    // quota / private mode は session のみ反映
  }
}

/** Ctrl+C で蓄えるブロック群のコピー (Ctrl+V でオフセット位置に貼り付け)。 */
export interface ClipboardPayload {
  blocks: BlockEntry[];
  connections: ConnectionEntry[];
  layout: LayoutDict; // 元 id → 元位置 (paste 時に位相平均から bbox 中心を計算する基準)
}

/**
 * ADR-0043 §論点 2: タブごとの完全なスナップショット。
 *
 * ``activeTabFilePath`` で指される tab が「現在編集中」(= 上位 ``selectedFilePath``
 * / ``editingModel`` 等が live で同期)。それ以外の tab は本 snapshot 内に
 * 「凍結」されており、switchTab で active になると上位 fields に restore される。
 *
 * tabs[] は active tab も含む順序付き配列。同一 ``filePath`` は重複しない (=
 * VSCode 流儀、既存 tab があればそれを active 化)。
 */
export interface TabSnapshot {
  filePath: string;
  editingModel: FlwModel | null;
  editingFileMtime: string | null;
  editingFileEtag: string | null;
  dirty: boolean;
  history: { past: FlwModel[]; future: FlwModel[] };
  lastMergeKey: string | null;
  editingPath: string[];
}

interface AppState {
  // v0.21.0: legacy ``selectedModelId`` を完全削除済 (ADR-0041 §論点 4-A)。
  // ``selectedFilePath`` のみが「選択中の編集対象」を表す。
  selectedFilePath: string | null;
  /** file path ベースで開く。``null`` で閉じる。
   *
   * v0.23.0 (ADR-0043 §論点 2): 内部的にも tabs[] と activeTabFilePath を更新
   * する。既存の callsite は変更不要 — 「path を渡す = その path を active に
   * する」セマンティクスは維持。 */
  selectFilePath: (path: string | null) => void;

  // ADR-0043 §論点 2: 複数タブ管理。tabs は active も含む全タブ順序付きリスト。
  // tabs.find(t => t.filePath === activeTabFilePath) が現在 active な snapshot。
  // 上位 ``selectedFilePath`` / ``editingModel`` 等は active tab と常に同期される。
  tabs: TabSnapshot[];
  activeTabFilePath: string | null;
  // ADR-0043 §論点 1-A / §論点 8-A: workspace 情報 (= startup で fetch)。
  // hash は localStorage キーの suffix に使う (= workspace 単位 scope)。
  workspaceHash: string | null;
  workspaceAbsolutePath: string | null;
  setWorkspaceInfo: (hash: string | null, absolutePath: string | null) => void;

  // ADR-0044 §論点 6 / §論点 11: 開いている floating Scope panel (scope_id の集合)。
  // モデル切替 / closeTab で全 panel を閉じる。
  scopePanels: string[];
  openScopePanel: (scopeId: string) => void;
  closeScopePanel: (scopeId: string) => void;
  closeAllScopePanels: () => void;

  // ADR-0045 §(1) Workspace convergence Stage 1: Diagram + Scope の multi-pane split。
  // モデル別 (= ``workspaceHash`` + ``activeTabFilePath`` 単位) に
  // ``pyflw.workspace_layout.<hash>.<b64url(path)>`` で永続化。
  workspaceLayout: SplitTree;
  /** モデル切替 / 起動時に localStorage から SplitTree を復元 (= 旧 ``pyflw.
   * scope_split`` 片方向 migration を含む)。``loadWorkspaceLayout`` 内では
   * 永続化を呼ばない (= 読み込みは write 不要)。 */
  loadWorkspaceLayout: (
    storedRaw: string | null,
    legacyRaw: string | null,
    hasVisibleScopes: boolean,
  ) => void;
  /** v0.42.x: 出力エリア (scopes-stack) の presence を hasScopeBlocks に
   * 揃える正規化。**意図的に永続化しない**: boot 時は子 (WorkspaceSplit) の
   * effect が親 (App) の layout 復元 effect より先に走るため、ここで persist
   * すると復元前の DEFAULT_TREE ベースの木が保存値を clobber する。正規化は
   * 復元後にも再適用されるので、保存はユーザー操作由来の mutator に任せる。 */
  normalizeScopesStackPresence: (hasScopeBlocks: boolean) => void;
  /** 既存 pane を split。v0.30.0 (ADR-0052): position で新葉の挿入位置を制御
   * (= "after" = 右/下、"before" = 左/上)、既定 "after" で従来挙動。 */
  splitPane: (
    paneId: string,
    orientation: "horizontal" | "vertical",
    newPaneId: string,
    position?: "after" | "before",
  ) => void;
  /** 既存 pane を tree から除去 (= 兄弟が親位置に昇格)。
   * tree 全体が 1 葉のみのとき呼ぶと ``DEFAULT_TREE`` (= ``diagram`` 単独) に戻る。 */
  unsplitPane: (paneId: string) => void;
  /** split node ごとの ratio を更新 (= drag resize 確定時)。``splitId`` は
   * ``makeSplitId(node)`` で計算した一意 ID。 */
  setWorkspaceSplitRatio: (splitId: string, ratio: number) => void;
  /** split node の orientation を反転 (= 縦 ↔ 横 切替、Stage 1 未使用予定)。 */
  toggleWorkspaceSplitOrientation: (splitId: string) => void;
  /** SplitTree を強制リセット (= DEFAULT_TREE_WITH_SCOPES or DEFAULT_TREE)。 */
  resetWorkspaceLayout: (hasVisibleScopes: boolean) => void;

  // ADR-0044 §論点 4 / §論点 10: scope 設定編集中の scope_id (= ScopeSettingsDialog 制御)。
  editingScopeSettingsId: string | null;
  setEditingScopeSettingsId: (id: string | null) => void;

  /**
   * ADR-0044 §論点 4 / §論点 10: editingModel.scope_settings の partial 更新。
   * モデル単位で永続化されるため applyEditingModel 経由で書き込む (= dirty 化、auto-save 対象)。
   */
  updateScopeSettings: (
    scopeId: string,
    partial: import("../types/api").ScopeSettings,
  ) => void;
  /** ADR-0044 §論点 9: 当該 scope の全 settings をクリアして既定値に戻す。 */
  resetScopeSettings: (scopeId: string) => void;
  /**
   * ファイルを新規 tab として開く、または既存 tab を active 化する。
   * @param path file path
   * @param model load 済みの FlwModel (= filesApi.getFileContent の戻り値)
   * @param mtime 楽観ロック用 mtime
   * @param etag 楽観ロック用 etag
   */
  openFileInTab: (
    path: string,
    model: FlwModel,
    mtime: string | null,
    etag: string | null,
  ) => void;
  /** 指定 tab を閉じる。active を閉じた場合は隣接 tab に切替、最後の tab なら全閉じ。 */
  closeTab: (path: string) => void;
  /** 指定 tab を active 化 (= tabs[] にあれば snapshot から復元)。 */
  switchTab: (path: string) => void;
  /** rename されたファイルの tab path を追従更新 (= 開いている tab の filePath を変更)。 */
  renameTabFilePath: (oldPath: string, newPath: string) => void;
  // ADR-0041 §論点 11-A: 楽観ロック / 外部変更検知に使う state。`selectFilePath`
  // で `editingModel` がロードされたタイミングで一緒にセットされる。
  editingFileMtime: string | null;
  editingFileEtag: string | null;
  setEditingFileMeta: (mtime: string | null, etag: string | null) => void;

  // ノード選択 (パラメータ編集 + 一括操作用)。複数選択対応。
  // ParameterPanel は ``selectedNodeIds.length === 1`` の時だけ表示する設計。
  selectedNodeIds: string[];
  selectedNodeId: string | null; // 互換性: selectedNodeIds.length === 1 のとき先頭、それ以外 null
  selectNode: (nodeId: string | null) => void;
  setSelectedNodeIds: (ids: readonly string[]) => void;
  toggleNodeSelection: (nodeId: string) => void;

  // エッジ選択 (= 矩形選択 / クリック選択 で React Flow が select イベントを発火する。
  // controlled mode では prop 経由で ``selected`` を渡し直さないと視覚反映されない)。
  selectedEdgeIds: string[];
  setSelectedEdgeIds: (ids: readonly string[]) => void;

  // クリップボード (Ctrl+C / Ctrl+V のための in-memory バッファ、cross-window 永続化なし)。
  clipboard: ClipboardPayload | null;
  setClipboard: (cb: ClipboardPayload | null) => void;

  // ADR-0019 §(5): 編集中モデル (=PUT する前の最新) を保持。
  // null のときは「読み取りモード」(従来の Phase 2 と同じ TanStack Query キャッシュ)。
  editingModel: FlwModel | null;
  setEditingModel: (model: FlwModel | null) => void;
  /**
   * editingModel を更新する。
   *
   * @param fn 現在の model から次の model を返す純粋関数。``current`` を返すと
   *   no-op (= history に push しない)。
   * @param options.mergeKey 連続操作を 1 履歴エントリに集約するための key。
   *   v0.20.1: ブロックドラッグの ``onNodesChange`` のように 1 操作で多数の
   *   ``applyEditingModel`` 呼び出しが発生する場合、同じ ``mergeKey`` の連続
   *   呼び出しは history に追加 push しない (= 直前 push の上書き効果)。
   *   別 ``mergeKey`` または ``undefined`` で新しい操作と判定。例:
   *   ``move:{id}`` (1 ブロック移動)、``resize:{id}`` (リサイズ)。
   */
  applyEditingModel: (
    fn: (current: FlwModel) => FlwModel,
    options?: { mergeKey?: string },
  ) => void;

  // v0.20.0: Undo / Redo 履歴 (= editingModel の past / future スタック)。
  // ``applyEditingModel`` で変更前の model を ``past`` に push、``future`` を
  // クリアする。``setEditingModel`` (= ファイル load) で完全クリア。
  // 最大 ``HISTORY_MAX`` 件、それを超える古い履歴は drop。
  history: { past: FlwModel[]; future: FlwModel[] };
  /** v0.20.1: 直前の applyEditingModel で指定された mergeKey (= 連続操作集約用)。
   *  別 key または undefined で「新しい操作」と判定して新規 push する。 */
  lastMergeKey: string | null;
  undo: () => void;
  redo: () => void;
  canUndo: () => boolean;
  canRedo: () => boolean;

  // v0.20.4: 左サイドバー上部 ``FileBrowser`` パネルの折りたたみ状態。
  // localStorage ("pyflw.workspace_collapsed") に永続化。``true`` で header
  // のみ表示、``false`` で tree 展開。
  workspaceCollapsed: boolean;
  setWorkspaceCollapsed: (collapsed: boolean) => void;

  // ADR-0051 §(1) §(2): activity bar (列 0) で切替される sidebar mode。
  // 列 1 (left sidebar) の中身を mode に応じて切替: file = FileBrowser /
  // library = BlockPalette / search = SearchPanel inline 描画。
  // localStorage "pyflw.sidebar_mode" に永続化。
  sidebarMode: "file" | "library" | "search";
  setSidebarMode: (mode: "file" | "library" | "search") => void;

  // v0.29.0: コマンドパレット (Ctrl+Shift+P) modal の open / closed state。
  // 永続化なし (= セッション内のみ)、Ctrl+Shift+P で open、Esc / 行クリックで close。
  commandPaletteOpen: boolean;
  setCommandPaletteOpen: (open: boolean) => void;

  // ADR-0052 §(2) Stage 3: Inspector の dock mode (= "sidebar" | "pane" | "float")。
  // localStorage `pyflw.inspector_dock_mode` に永続化、workspace 横断 (= モデル
  // 切替で変更しない)。
  inspectorDockMode: "sidebar" | "pane" | "float";
  setInspectorDockMode: (mode: "sidebar" | "pane" | "float") => void;
  // v0.26.5: 右サイドバー (Inspector) の折りたたみ。Canvas を広げて使う用途。
  inspectorCollapsed: boolean;
  setInspectorCollapsed: (collapsed: boolean) => void;
  // v0.26.10: 左サイドバー横幅 (px、drag で変更)。localStorage 永続。
  leftSidebarWidth: number;
  setLeftSidebarWidth: (px: number) => void;
  // v0.30.4: Inspector (= 列 4) 横幅 (px、drag で変更)。localStorage 永続。
  // collapsed 時は無視され、grid template columns で 24 px に潰す。
  inspectorWidth: number;
  setInspectorWidth: (px: number) => void;

  // v0.31.0: FileBrowser の cwd (= 現在表示中のフォルダ相対パス、リファレンス Web IDE
  // 流儀)。``""`` で root。permanent 永続化なし (= session 内のみ、起動時は
  // root) — workspace 切替で root reset したいため localStorage 不適。
  fileBrowserCwd: string;
  setFileBrowserCwd: (path: string) => void;

  // ADR-0019 §(5): dirty flag と debounce 用 timer
  dirty: boolean;
  setDirty: (dirty: boolean) => void;

  // ADR-0021 §(1): Subsystem ドリルダウン path
  editingPath: string[];
  setEditingPath: (path: string[]) => void;
  drilldownInto: (subsystemId: string) => void;
  drillUp: (depth?: number) => void;

  // シミュレーション関連
  simulationId: string | null;
  status: SimulationStatus | "idle";
  // ADR-0042 §論点 3-A: ``t_end`` は ``number | "inf"`` Union (= unbounded run)。
  progress: { current_t: number; t_end: TEnd } | null;
  startedSimulation: (simId: string) => void;
  setStatus: (status: SimulationStatus | "idle") => void;
  setProgress: (current_t: number, t_end: TEnd) => void;
  resetSimulation: () => void;
  // ADR-0056: 直近 1 件の失敗詳細 (= Scope tab strip の Error tab に表示)。
  // 起動失敗時は ``setLastFailure(payload, source="start")``、実行中エラー時は
  // ``handleStreamMessage`` で ``failed + category`` 受信時にセット。
  lastFailure: FailurePayload | null;
  /** 直近失敗が start API 由来 (= 「起動失敗:」プレフィックス) か runtime 由来か。 */
  lastFailureSource: "start" | "runtime" | null;
  /** Scope tab strip の Error tab がアクティブか (= 失敗時自動 focus トリガー)。 */
  activeErrorTab: boolean;
  setLastFailure: (payload: FailurePayload | null, source: "start" | "runtime") => void;
  setActiveErrorTab: (value: boolean) => void;
  // ADR-0056 follow-up: Log tab のエラーから対象ブロックへジャンプ。
  // ``focusBlock`` が path 解決 + drilldown + 選択 + center 要求 (= focusBlockRequest)
  // をまとめてセットし、DiagramCanvas の effect が canvas を pan する。
  focusBlockRequest: { blockId: string; nonce: number } | null;
  focusBlock: (blockId: string) => void;

  // Scope データ (scope_id -> 時系列)
  scopes: Record<string, ScopeBuffer>;
  resetScopes: () => void;
  // 終端後の一括結果 (`GET /results`) で scope バッファを丸ごと置き換える。
  // WS の queue 満杯 drop による波形のサイレント欠損を補完する (ADR-0011 §(2))。
  replaceScopes: (
    scopes: Record<string, { times: number[]; values: number[][] }>,
  ) => void;

  // 受信ハンドラ (WebSocket メッセージから状態に反映)
  handleStreamMessage: (msg: StreamMessage) => void;
}

/**
 * ADR-0043 §論点 2: 現在の上位 state から TabSnapshot を組み立てる helper。
 * switchTab / openFileInTab / closeTab で active 切替前に呼ぶ。
 */
function makeTabSnapshot(state: AppState): TabSnapshot | null {
  if (state.activeTabFilePath === null) return null;
  return {
    filePath: state.activeTabFilePath,
    editingModel: state.editingModel,
    editingFileMtime: state.editingFileMtime,
    editingFileEtag: state.editingFileEtag,
    dirty: state.dirty,
    history: state.history,
    lastMergeKey: state.lastMergeKey,
    editingPath: state.editingPath,
  };
}

export const useAppStore = create<AppState>((set, get) => ({
  selectedFilePath: null,
  tabs: [],
  activeTabFilePath: null,
  workspaceHash: null,
  workspaceAbsolutePath: null,
  setWorkspaceInfo: (hash, absolutePath) =>
    set({ workspaceHash: hash, workspaceAbsolutePath: absolutePath }),

  // ADR-0044 §論点 6 / §論点 11
  scopePanels: [],
  openScopePanel: (scopeId) =>
    set((state) => {
      if (state.scopePanels.includes(scopeId)) {
        // 既に開いていれば末尾に move (= bring to front)
        return {
          scopePanels: [
            ...state.scopePanels.filter((id) => id !== scopeId),
            scopeId,
          ],
        };
      }
      return { scopePanels: [...state.scopePanels, scopeId] };
    }),
  closeScopePanel: (scopeId) =>
    set((state) => ({
      scopePanels: state.scopePanels.filter((id) => id !== scopeId),
    })),
  closeAllScopePanels: () => set({ scopePanels: [] }),

  // ADR-0045 §(1) Workspace convergence Stage 1: multi-pane split state + actions。
  // 永続化は各 mutator action 内で同期的に行う (= setLeftSidebarWidth と同じ慣例)。
  workspaceLayout: DEFAULT_TREE,
  loadWorkspaceLayout: (storedRaw, legacyRaw, hasVisibleScopes) =>
    set({
      workspaceLayout: chooseInitialTree(
        storedRaw,
        legacyRaw,
        hasVisibleScopes,
      ),
    }),
  normalizeScopesStackPresence: (hasScopeBlocks) =>
    set((state) => {
      const has = findLeaf(state.workspaceLayout, "scopes-stack");
      if (hasScopeBlocks && !has) {
        const next = insertSplit(
          state.workspaceLayout,
          "diagram",
          "vertical",
          "scopes-stack",
          "after",
        );
        if (next === state.workspaceLayout) return state;
        return { workspaceLayout: next };
      }
      if (!hasScopeBlocks && has) {
        const removed = removeLeaf(state.workspaceLayout, "scopes-stack");
        if (removed === null || removed === state.workspaceLayout) return state;
        return { workspaceLayout: removed };
      }
      return state;
    }),
  splitPane: (paneId, orientation, newPaneId, position = "after") =>
    set((state) => {
      const next = insertSplit(
        state.workspaceLayout,
        paneId,
        orientation,
        newPaneId,
        position,
      );
      if (next === state.workspaceLayout) return state;
      persistWorkspaceLayoutFor(
        state.workspaceHash,
        state.activeTabFilePath,
        next,
      );
      return { workspaceLayout: next };
    }),
  unsplitPane: (paneId) =>
    set((state) => {
      const removed = removeLeaf(state.workspaceLayout, paneId);
      if (removed === null) {
        // 残葉数 1 で唯一の葉を unsplit しようとした (UI 上到達不能、防御的処理)。
        // 既に DEFAULT_TREE 相当 (= diagram 単独) なら no-op、それ以外は
        // DEFAULT_TREE に差し戻す + 永続化。
        if (
          state.workspaceLayout.kind === "leaf" &&
          state.workspaceLayout.paneId === "diagram"
        ) {
          return state;
        }
        persistWorkspaceLayoutFor(
          state.workspaceHash,
          state.activeTabFilePath,
          DEFAULT_TREE,
        );
        return { workspaceLayout: DEFAULT_TREE };
      }
      if (removed === state.workspaceLayout) return state;
      persistWorkspaceLayoutFor(
        state.workspaceHash,
        state.activeTabFilePath,
        removed,
      );
      return { workspaceLayout: removed };
    }),
  setWorkspaceSplitRatio: (splitId, ratio) =>
    set((state) => {
      const next = splitTreeSetRatio(state.workspaceLayout, splitId, ratio);
      if (next === state.workspaceLayout) return state;
      persistWorkspaceLayoutFor(
        state.workspaceHash,
        state.activeTabFilePath,
        next,
      );
      return { workspaceLayout: next };
    }),
  toggleWorkspaceSplitOrientation: (splitId) =>
    set((state) => {
      const next = splitTreeToggleOrientation(state.workspaceLayout, splitId);
      if (next === state.workspaceLayout) return state;
      persistWorkspaceLayoutFor(
        state.workspaceHash,
        state.activeTabFilePath,
        next,
      );
      return { workspaceLayout: next };
    }),
  resetWorkspaceLayout: (hasVisibleScopes) =>
    set((state) => {
      const next = hasVisibleScopes ? DEFAULT_TREE_WITH_SCOPES : DEFAULT_TREE;
      persistWorkspaceLayoutFor(
        state.workspaceHash,
        state.activeTabFilePath,
        next,
      );
      return { workspaceLayout: next };
    }),

  editingScopeSettingsId: null,
  setEditingScopeSettingsId: (id) => set({ editingScopeSettingsId: id }),

  updateScopeSettings: (scopeId, partial) => {
    const current = get().editingModel;
    if (!current) return;
    const next = {
      ...current,
      scope_settings: {
        ...(current.scope_settings ?? {}),
        [scopeId]: {
          ...(current.scope_settings?.[scopeId] ?? {}),
          ...partial,
        },
      },
    };
    set((state) => ({
      editingModel: next,
      dirty: true,
      history: {
        past: [...state.history.past, JSON.parse(JSON.stringify(current))],
        future: [],
      },
      lastMergeKey: `scope-settings:${scopeId}`,
    }));
  },
  resetScopeSettings: (scopeId) => {
    const current = get().editingModel;
    if (!current) return;
    // 既に default 状態 (= entry 不在) なら no-op
    if (!current.scope_settings || !(scopeId in current.scope_settings)) {
      return;
    }
    // shallow copy して当該 scope を削除
    const newSettings = { ...current.scope_settings };
    delete newSettings[scopeId];
    // 新 editingModel: 空 dict になったら ``scope_settings`` キーごと削除する
    // (= JSON 出力をクリーンに保つ)。
    // v0.24.6 fix: 旧実装は ``{ ...current, ...rest }`` で spread していたが、
    // spread はキーを「持たない」ことを表現できないため scope_settings が残って
    // しまっていた。明示的に ``delete next.scope_settings`` する必要がある。
    const next = { ...current };
    if (Object.keys(newSettings).length > 0) {
      next.scope_settings = newSettings;
    } else {
      delete next.scope_settings;
    }
    set((state) => ({
      editingModel: next,
      dirty: true,
      history: {
        past: [...state.history.past, JSON.parse(JSON.stringify(current))],
        future: [],
      },
      lastMergeKey: null,
    }));
  },
  selectFilePath: (path) =>
    set((state) => {
      // tabs[] への反映: path === null は全閉じ、それ以外は **既存 tab があれば
      // 維持、なければ tabs[] には追加しない** (= 後で openFileInTab で content
      // 同梱で追加する想定)。FileBrowser 等から path だけで selectFilePath を
      // 呼ぶ既存挙動は legacy として維持し、tab メタは別 hook が管理する。
      const newTabs = path === null ? [] : state.tabs;
      return {
        selectedFilePath: path,
        activeTabFilePath: path,
        tabs: newTabs,
        editingFileMtime: null,
        editingFileEtag: null,
        selectedNodeIds: [],
        selectedNodeId: null,
        selectedEdgeIds: [],
        clipboard: null,
        simulationId: null,
        status: "idle",
        scopes: {},
        editingModel: null,
        dirty: false,
        editingPath: [],
        history: { past: [], future: [] },
        lastMergeKey: null,
      };
    }),

  // ADR-0043 §論点 2: 複数タブ操作 actions
  openFileInTab: (path, model, mtime, etag) => {
    // ADR-0058 §論点 10: backend persistence.migrate_to_current() が 1 段以上
    // migration を適用したファイルには ``_migrated_from`` メタが付く。ロード直後に
    // toast 通知 + dirty flag で「保存すると新 schema になる」とユーザーに伝え、
    // store にはメタを保存しない (= save 時に二重記録しない、ADR-0058 §論点 10
    // 確定)。
    let initialDirty = false;
    let storedModel: FlwModel = model;
    const migratedFrom = model._migrated_from;
    if (migratedFrom) {
      initialDirty = true;
      pushToast({
        severity: "info",
        message: `モデルを schema ${migratedFrom} → ${model.schema_version} に自動更新しました。保存すると新スキーマになります。`,
        durationMs: 8000,
      });
      // 引数の model object を mutate せず、メタ除去版を spread で複製する
      // (= 呼び出し側 filesApi の cache が壊れない、関数 contract 上の安全)。
      const { _migrated_from: _omit, ...rest } = model;
      storedModel = rest as FlwModel;
    }
    // 以降は storedModel (メタ除去済 or 元のまま) を保存する
    const m = storedModel;
    set((state) => {
      // 同一 path の tab が既存ならそれを active 化 (= 重複オープン不可、VSCode 流儀)
      const existing = state.tabs.find((t) => t.filePath === path);
      if (existing) {
        // 現 active を snapshot 化 + 既存 tab restore
        const currentSnap = makeTabSnapshot(state);
        const updatedTabs = state.tabs.map((t) =>
          currentSnap && t.filePath === currentSnap.filePath ? currentSnap : t,
        );
        return {
          tabs: updatedTabs,
          activeTabFilePath: existing.filePath,
          selectedFilePath: existing.filePath,
          editingModel: existing.editingModel,
          editingFileMtime: existing.editingFileMtime,
          editingFileEtag: existing.editingFileEtag,
          dirty: existing.dirty,
          history: existing.history,
          lastMergeKey: existing.lastMergeKey,
          editingPath: existing.editingPath,
          // 切替時にはノード選択 / Scope を reset
          selectedNodeIds: [],
          selectedNodeId: null,
          selectedEdgeIds: [],
          simulationId: null,
          status: "idle",
          scopes: {},
        };
      }
      // 新規 tab。現 active を snapshot 化して tabs[] に反映、新 tab を末尾に追加。
      const currentSnap = makeTabSnapshot(state);
      const otherTabs = currentSnap
        ? state.tabs.map((t) =>
            t.filePath === currentSnap.filePath ? currentSnap : t,
          )
        : state.tabs;
      const newTab: TabSnapshot = {
        filePath: path,
        editingModel: m,
        editingFileMtime: mtime,
        editingFileEtag: etag,
        // ADR-0058 §論点 10: migrated_from があれば dirty 開始 (= 「保存すると
        // 新スキーマ」を伝える)。
        dirty: initialDirty,
        history: { past: [], future: [] },
        lastMergeKey: null,
        editingPath: [],
      };
      return {
        tabs: [...otherTabs, newTab],
        activeTabFilePath: path,
        selectedFilePath: path,
        editingModel: m,
        editingFileMtime: mtime,
        editingFileEtag: etag,
        dirty: initialDirty,
        history: { past: [], future: [] },
        lastMergeKey: null,
        editingPath: [],
        selectedNodeIds: [],
        selectedNodeId: null,
        selectedEdgeIds: [],
        simulationId: null,
        status: "idle",
        scopes: {},
      };
    });
  },
  closeTab: (path) =>
    set((state) => {
      const idx = state.tabs.findIndex((t) => t.filePath === path);
      if (idx < 0) return {};
      const remaining = state.tabs.filter((_, i) => i !== idx);
      const wasActive = state.activeTabFilePath === path;
      // ADR-0052 §(1): タブ閉じで SplitTree から `tab:<filePath>` 葉も除去
      // (= drag-to-split-tab で pane 化していた場合の cleanup)
      const tabPaneId = `tab:${path}`;
      let updatedLayout = state.workspaceLayout;
      if (findLeaf(state.workspaceLayout, tabPaneId)) {
        const removed = removeLeaf(state.workspaceLayout, tabPaneId);
        updatedLayout = removed ?? DEFAULT_TREE;
        persistWorkspaceLayoutFor(
          state.workspaceHash,
          state.activeTabFilePath,
          updatedLayout,
        );
      }
      if (!wasActive) {
        return { tabs: remaining, workspaceLayout: updatedLayout };
      }
      // active を閉じた: 隣接 tab に switchTab。なければ全 clear。
      if (remaining.length === 0) {
        return {
          tabs: [],
          activeTabFilePath: null,
          selectedFilePath: null,
          editingFileMtime: null,
          editingFileEtag: null,
          editingModel: null,
          dirty: false,
          editingPath: [],
          history: { past: [], future: [] },
          lastMergeKey: null,
          selectedNodeIds: [],
          selectedNodeId: null,
          selectedEdgeIds: [],
          simulationId: null,
          status: "idle",
          scopes: {},
          workspaceLayout: updatedLayout,
        };
      }
      // 右側の tab を優先、無ければ左側
      const nextIdx = idx < remaining.length ? idx : remaining.length - 1;
      const nextTab = remaining[nextIdx]!;
      return {
        tabs: remaining,
        activeTabFilePath: nextTab.filePath,
        selectedFilePath: nextTab.filePath,
        editingModel: nextTab.editingModel,
        editingFileMtime: nextTab.editingFileMtime,
        editingFileEtag: nextTab.editingFileEtag,
        dirty: nextTab.dirty,
        history: nextTab.history,
        lastMergeKey: nextTab.lastMergeKey,
        editingPath: nextTab.editingPath,
        selectedNodeIds: [],
        selectedNodeId: null,
        selectedEdgeIds: [],
        simulationId: null,
        status: "idle",
        scopes: {},
        workspaceLayout: updatedLayout,
      };
    }),
  switchTab: (path) =>
    set((state) => {
      if (state.activeTabFilePath === path) return {};
      const target = state.tabs.find((t) => t.filePath === path);
      if (!target) return {};
      const currentSnap = makeTabSnapshot(state);
      const updatedTabs = currentSnap
        ? state.tabs.map((t) =>
            t.filePath === currentSnap.filePath ? currentSnap : t,
          )
        : state.tabs;
      return {
        tabs: updatedTabs,
        activeTabFilePath: target.filePath,
        selectedFilePath: target.filePath,
        editingModel: target.editingModel,
        editingFileMtime: target.editingFileMtime,
        editingFileEtag: target.editingFileEtag,
        dirty: target.dirty,
        history: target.history,
        lastMergeKey: target.lastMergeKey,
        editingPath: target.editingPath,
        selectedNodeIds: [],
        selectedNodeId: null,
        selectedEdgeIds: [],
        simulationId: null,
        status: "idle",
        scopes: {},
      };
    }),
  renameTabFilePath: (oldPath, newPath) =>
    set((state) => {
      // ADR-0052 code-reviewer §SHOULD #2: SplitTree 内の tab:<oldPath> 葉も
      // 追従させる (= rename 後に「このタブは閉じられています」表示を防ぐ)
      const oldTabLeafId = `tab:${oldPath}`;
      const newTabLeafId = `tab:${newPath}`;
      let updatedLayout = state.workspaceLayout;
      if (findLeaf(state.workspaceLayout, oldTabLeafId)) {
        const renamed = splitTreeRenameLeaf(
          state.workspaceLayout,
          oldTabLeafId,
          newTabLeafId,
        );
        if (renamed !== state.workspaceLayout) {
          updatedLayout = renamed;
          persistWorkspaceLayoutFor(
            state.workspaceHash,
            state.activeTabFilePath,
            updatedLayout,
          );
        }
      }

      const idx = state.tabs.findIndex((t) => t.filePath === oldPath);
      if (idx < 0) {
        // active path が rename された場合だけ反映
        if (state.activeTabFilePath === oldPath) {
          return {
            activeTabFilePath: newPath,
            selectedFilePath: newPath,
            workspaceLayout: updatedLayout,
          };
        }
        return { workspaceLayout: updatedLayout };
      }
      const updated = state.tabs.map((t, i) =>
        i === idx ? { ...t, filePath: newPath } : t,
      );
      const newActive =
        state.activeTabFilePath === oldPath ? newPath : state.activeTabFilePath;
      return {
        tabs: updated,
        activeTabFilePath: newActive,
        selectedFilePath:
          state.selectedFilePath === oldPath ? newPath : state.selectedFilePath,
        workspaceLayout: updatedLayout,
      };
    }),

  editingFileMtime: null,
  editingFileEtag: null,
  setEditingFileMeta: (mtime, etag) =>
    set({ editingFileMtime: mtime, editingFileEtag: etag }),

  selectedNodeIds: [],
  selectedNodeId: null,
  selectNode: (nodeId) =>
    set({
      selectedNodeIds: nodeId === null ? [] : [nodeId],
      selectedNodeId: nodeId,
      // ノード選択を切り替えたらエッジ選択も解除 (= ParameterPanel の整合性)
      ...(nodeId === null ? { selectedEdgeIds: [] } : {}),
    }),
  setSelectedNodeIds: (ids) => {
    const arr = Array.from(new Set(ids));
    set({
      selectedNodeIds: arr,
      // ParameterPanel 表示用の単一 id (= 1 件選択時のみ)
      selectedNodeId: arr.length === 1 ? arr[0]! : null,
    });
  },
  toggleNodeSelection: (nodeId) =>
    set((state) => {
      const has = state.selectedNodeIds.includes(nodeId);
      const next = has
        ? state.selectedNodeIds.filter((id) => id !== nodeId)
        : [...state.selectedNodeIds, nodeId];
      return {
        selectedNodeIds: next,
        selectedNodeId: next.length === 1 ? next[0]! : null,
      };
    }),

  selectedEdgeIds: [],
  setSelectedEdgeIds: (ids) =>
    set({ selectedEdgeIds: Array.from(new Set(ids)) }),

  // Phase 3: in-app クリップボード (= cross-window で persist する必要は今のところ
  // ない、シンプルな in-memory の単一バッファ)。
  clipboard: null,
  setClipboard: (cb) => set({ clipboard: cb }),

  editingModel: null,
  // ファイル load 時に呼ばれる (= history を完全クリア、別履歴と混ぜない)
  setEditingModel: (model) =>
    set({
      editingModel: model,
      history: { past: [], future: [] },
      lastMergeKey: null,
    }),
  applyEditingModel: (fn, options) => {
    const current = get().editingModel;
    if (!current) return;
    const next = fn(current);
    if (next === current) return; // no-op (= history を膨らませない)
    set((state) => {
      const mergeKey = options?.mergeKey;
      // v0.20.1: 直前と同じ ``mergeKey`` なら history に追加 push しない。
      // 例: 1 ブロックを連続ドラッグすると 1px ごとに本関数が呼ばれるが、
      // mergeKey="move:{id}" を毎回指定すると history は最初の 1 エントリだけ
      // 残り、Ctrl+Z 1 回でドラッグ前の位置に戻る。
      const shouldMerge =
        mergeKey !== undefined &&
        state.lastMergeKey === mergeKey &&
        state.history.past.length > 0;
      let past: FlwModel[];
      if (shouldMerge) {
        past = state.history.past; // 既存を維持 (= 上書きしない、最古を保持)
      } else {
        past = [...state.history.past, deepCloneModel(current)];
        // 上限超えたら古い履歴を drop
        if (past.length > HISTORY_MAX) {
          past = past.slice(past.length - HISTORY_MAX);
        }
      }
      return {
        editingModel: next,
        dirty: true,
        // 新しい変更が入った時点で future (= redo 候補) は破棄
        history: { past, future: [] },
        lastMergeKey: mergeKey ?? null,
      };
    });
  },

  // v0.20.0: undo / redo
  history: { past: [], future: [] },
  lastMergeKey: null,

  // v0.20.4: FileBrowser 折りたたみ (localStorage 連動)
  inspectorCollapsed: readInspectorCollapsed(),
  setInspectorCollapsed: (collapsed) => {
    writeInspectorCollapsed(collapsed);
    set({ inspectorCollapsed: collapsed });
  },
  leftSidebarWidth: readLeftSidebarWidth(),
  setLeftSidebarWidth: (px) => {
    const clamped = Math.max(
      LEFT_SIDEBAR_MIN_PX,
      Math.min(LEFT_SIDEBAR_MAX_PX, px),
    );
    writeLeftSidebarWidth(clamped);
    set({ leftSidebarWidth: clamped });
  },
  // v0.30.4: Inspector 横幅 (drag で変更、localStorage 永続)
  inspectorWidth: readInspectorWidth(),
  setInspectorWidth: (px) => {
    const clamped = Math.max(
      INSPECTOR_MIN_PX,
      Math.min(INSPECTOR_MAX_PX, px),
    );
    writeInspectorWidth(clamped);
    set({ inspectorWidth: clamped });
  },
  // v0.31.0: FileBrowser cwd (= リファレンス Web IDE 流儀の「中に入る」ナビゲーション)
  fileBrowserCwd: "",
  setFileBrowserCwd: (path) => set({ fileBrowserCwd: path }),
  workspaceCollapsed: readWorkspaceCollapsed(),
  setWorkspaceCollapsed: (collapsed) => {
    writeWorkspaceCollapsed(collapsed);
    set({ workspaceCollapsed: collapsed });
  },
  // ADR-0051 §(1) §(2): activity bar sidebar mode (= file / library / search)
  sidebarMode: readSidebarMode(),
  setSidebarMode: (mode) => {
    writeSidebarMode(mode);
    set({ sidebarMode: mode });
  },
  // v0.29.0: コマンドパレット modal state
  commandPaletteOpen: false,
  setCommandPaletteOpen: (open) => set({ commandPaletteOpen: open }),

  // ADR-0052 §(2) Stage 3: Inspector dock mode
  inspectorDockMode: readInspectorDockMode(),
  setInspectorDockMode: (mode) => {
    writeInspectorDockMode(mode);
    // Stage 3 §(2): mode 切替時の SplitTree side-effect
    // - sidebar → pane: SplitTree に "inspector" 葉を split 挿入
    // - pane → sidebar: SplitTree から "inspector" 葉を removeLeaf
    // - * → float / float → *: SplitTree 操作なし (Rnd で独立描画)
    const state = get();
    const prev = state.inspectorDockMode;
    set({ inspectorDockMode: mode });
    if (prev !== "pane" && mode === "pane") {
      // sidebar/float → pane: SplitTree に inspector 葉を split 挿入
      const layout = state.workspaceLayout;
      if (!findLeaf(layout, "inspector")) {
        // diagram 葉を horizontal split で右に inspector を追加
        const next = insertSplit(
          layout,
          "diagram",
          "horizontal",
          "inspector",
          "after",
        );
        if (next !== layout) {
          persistWorkspaceLayoutFor(
            state.workspaceHash,
            state.activeTabFilePath,
            next,
          );
          set({ workspaceLayout: next });
        }
      }
    } else if (prev === "pane" && mode !== "pane") {
      // pane → sidebar/float: SplitTree から inspector 葉を除去
      const removed = removeLeaf(state.workspaceLayout, "inspector");
      if (removed !== state.workspaceLayout) {
        const next = removed ?? DEFAULT_TREE;
        persistWorkspaceLayoutFor(
          state.workspaceHash,
          state.activeTabFilePath,
          next,
        );
        set({ workspaceLayout: next });
      }
    }
  },
  canUndo: () => get().history.past.length > 0,
  canRedo: () => get().history.future.length > 0,
  undo: () => {
    const state = get();
    const past = state.history.past;
    if (past.length === 0 || state.editingModel === null) return;
    const previous = past[past.length - 1]!;
    set({
      editingModel: previous,
      history: {
        past: past.slice(0, -1),
        future: [deepCloneModel(state.editingModel), ...state.history.future],
      },
      // undo 自体は編集アクションなので dirty 化 (= 次の auto-save で書き出す)
      dirty: true,
      // undo / redo 後は merge を継続させない (= 直後の編集は新規 entry)
      lastMergeKey: null,
    });
  },
  redo: () => {
    const state = get();
    const future = state.history.future;
    if (future.length === 0 || state.editingModel === null) return;
    const next = future[0]!;
    set({
      editingModel: next,
      history: {
        past: [...state.history.past, deepCloneModel(state.editingModel)],
        future: future.slice(1),
      },
      dirty: true,
      lastMergeKey: null,
    });
  },

  dirty: false,
  setDirty: (dirty) => set({ dirty }),

  editingPath: [],
  setEditingPath: (path) => set({ editingPath: path, selectedNodeId: null }),
  drilldownInto: (subsystemId) =>
    set((state) => ({
      editingPath: [...state.editingPath, subsystemId],
      selectedNodeId: null,
      selectedNodeIds: [],
    })),
  drillUp: (depth) =>
    set((state) => ({
      editingPath:
        depth === undefined
          ? state.editingPath.slice(0, -1)
          : state.editingPath.slice(0, depth),
      selectedNodeId: null,
      selectedNodeIds: [],
    })),

  simulationId: null,
  status: "idle",
  progress: null,
  startedSimulation: (simId) => {
    // 前 run の未 flush pending (scope_batch / progress) が新 run に漏れ込まない
    // よう、予約済み rAF を解除して pending を破棄してから開始する。
    cancelPendingStream();
    set({
      simulationId: simId,
      status: "running",
      progress: null,
      scopes: {},
      // ADR-0056 §F3: 次の Run 開始時に直近 failure をクリア + Error tab focus 解除。
      lastFailure: null,
      lastFailureSource: null,
      activeErrorTab: false,
    });
  },
  setStatus: (status) => set({ status }),
  setProgress: (current_t, t_end) => set({ progress: { current_t, t_end } }),
  resetSimulation: () =>
    set({ simulationId: null, status: "idle", progress: null }),
  // ADR-0056 §F2: 失敗詳細セット + Error tab を自動 focus。
  lastFailure: null,
  lastFailureSource: null,
  activeErrorTab: false,
  setLastFailure: (payload, source) =>
    // code-reviewer MUST-1: null クリア時は status を触らない (= failed 遷移のみ責務)。
    // クリアパスで status="idle" に上書きすると、実行中エラーをクリアしようとした際に
    // running→idle の意図しない遷移を引き起こす。
    set(
      payload === null
        ? {
            lastFailure: null,
            lastFailureSource: null,
            activeErrorTab: false,
          }
        : {
            lastFailure: payload,
            lastFailureSource: source,
            activeErrorTab: true,
            status: "failed",
          },
    ),
  setActiveErrorTab: (value) => set({ activeErrorTab: value }),
  focusBlockRequest: null,
  focusBlock: (blockId) => {
    const model = get().editingModel;
    if (!model) return;
    const path = findBlockPath(model, blockId);
    // 別モデルに切替後など、現モデルに存在しない block は no-op。
    if (path === null) return;
    const prevNonce = get().focusBlockRequest?.nonce ?? 0;
    set({
      editingPath: path,
      selectedNodeIds: [blockId],
      selectedNodeId: blockId,
      // nonce 単調増加で同一ブロック連打でも DiagramCanvas の effect を再発火させる。
      focusBlockRequest: { blockId, nonce: prevNonce + 1 },
    });
  },

  scopes: {},
  resetScopes: () => {
    cancelPendingStream();
    set({ scopes: {} });
  },

  replaceScopes: (results) => {
    // 終端後の呼び出し前提だが、念のため未 flush の pending を先に破棄する
    // (= 置き換え後に古い batch が追記されて再び欠損状態に戻るのを防ぐ)。
    cancelPendingStream();
    const rebuilt: Record<string, ScopeBuffer> = {};
    for (const [scopeId, data] of Object.entries(results)) {
      // appendBatch は空バッファへの一括追記で全件を SoA 転置し、
      // MAX_SAMPLES 超過時は WS 経路と同じ ring drop 規則を適用する。
      rebuilt[scopeId] = appendScopeBatchSoA(
        createScopeBuffer(),
        data.times,
        data.values,
      );
    }
    set({ scopes: rebuilt });
  },

  handleStreamMessage: (msg) => {
    switch (msg.type) {
      case "progress":
        // rAF coalescing: 最新 progress のみ保持し 1 フレーム後に反映する
        // (= 毎ステップ届く progress で React 再レンダを煽らない)。
        pendingProgress = { current_t: msg.current_t, t_end: msg.t_end };
        scheduleScopeFlush();
        break;
      case "scope_batch":
        // rAF coalescing: pending に積み、1 フレーム 1 回だけ flush する。
        // 1 frame 内に複数バッチが届いても uPlot 再描画は 1 回に畳む
        // (= カクつき/CPU 浪費の解消)。append ロジック自体は flush 側で
        // ``appendScopeBatchSoA`` を直接呼び、整合性管理を 1 か所に集約する。
        pendingScopeBatches.push({
          scope_id: msg.scope_id,
          times: msg.times,
          values: msg.values,
        });
        scheduleScopeFlush();
        break;
      case "completed":
      case "stopped":
        // 終端: 予約済み pending を同期 drain してからステータス確定する
        // (= バックエンドの最終バッチの取りこぼし・順序逆転を防ぐ)。
        flushPendingStream();
        cancelPendingStream();
        set({ status: msg.type });
        break;
      case "failed": {
        // 終端: progress / scope_batch の pending を同期 drain してから失敗確定。
        flushPendingStream();
        cancelPendingStream();
        // ADR-0056 §F2: ``failed`` に ``category`` フィールドが付いていれば構造化
        // エラーとして lastFailure に保存し Error tab を自動 focus。``category``
        // 無し (= 旧フォーマット or 想定外) なら詳細無しで status だけ立てる。
        if (typeof msg.category === "string") {
          // FailurePayload 9 fields を msg (= Partial<FailurePayload>) から抽出。
          const payload: FailurePayload = {
            category: msg.category,
            template_key: msg.template_key ?? "error.unknown",
            template_args: msg.template_args ?? {},
            block_id: msg.block_id ?? null,
            block_ids: msg.block_ids ?? [],
            block_type: msg.block_type ?? null,
            block_label: msg.block_label ?? null,
            t: msg.t ?? null,
            raw_message: msg.raw_message ?? "",
            raw_traceback: msg.raw_traceback ?? null,
          };
          set({
            status: "failed",
            lastFailure: payload,
            lastFailureSource: "runtime",
            activeErrorTab: true,
          });
        } else {
          set({ status: "failed" });
        }
        break;
      }
    }
  },
}));

// ---------------------------------------------------------------------------
// Scope ストリームの rAF coalescing (描画 cadence を最大 60fps に間引く性能最適化)。
//
// 背景: WebSocket の ``scope_batch`` / ``progress`` は、実時間非同期で最速計算する
// バックエンドから 1 フレーム (16ms) 内に何本も届きうる。受信ごとに同期 ``set()``
// すると 1 フレームで複数回の React 再レンダ + uPlot canvas 再描画が走り、カクつき
// / CPU 浪費の原因になる。届いたメッセージを pending に溜め、
// ``requestAnimationFrame`` で 1 フレーム 1 回だけまとめて 1 ``set()`` に畳む。
//
// 観測挙動 (= 最終的に描かれるグラフ) は不変で、描画頻度のみを整える。終端メッセージ
// (completed / stopped / failed) は ``flushPendingStream()`` で同期 drain してから
// ステータスを確定し、最終バッチの取りこぼし・順序逆転を防ぐ。
// ---------------------------------------------------------------------------

interface PendingScopeBatch {
  scope_id: string;
  times: readonly number[];
  values: readonly (readonly number[])[];
}

let pendingScopeBatches: PendingScopeBatch[] = [];
let pendingProgress: { current_t: number; t_end: TEnd } | null = null;
let scopeFlushHandle: number | null = null;

/** rAF 非対応環境 (SSR 等) での setTimeout fallback 間隔 (≒ 60fps = 1000/60 ms)。 */
const RAF_FALLBACK_MS = 16;

// request / cancel はともに「呼び出し時点」で rAF の有無を判定する。モジュール
// 評価時に固定しないことで、環境差・テストの global stub・dev HMR の差し替えに
// 追従する (= request したら同系統で cancel される保証を実行時に取り直す)。
function requestFrame(cb: () => void): number {
  if (typeof requestAnimationFrame === "function") {
    return requestAnimationFrame(cb);
  }
  return setTimeout(cb, RAF_FALLBACK_MS) as unknown as number;
}
function cancelFrame(handle: number): void {
  if (typeof cancelAnimationFrame === "function") {
    cancelAnimationFrame(handle);
  } else {
    clearTimeout(handle);
  }
}

/** pending を 1 フレーム後に flush するよう予約する (二重予約はしない)。 */
function scheduleScopeFlush(): void {
  if (scopeFlushHandle !== null) return;
  scopeFlushHandle = requestFrame(() => {
    scopeFlushHandle = null;
    flushPendingStream();
  });
}

/** 溜まった scope_batch / progress を 1 回の ``set()`` にまとめて反映する。
 *  pending が空なら no-op。終端メッセージ処理から同期呼び出しもされる。 */
function flushPendingStream(): void {
  if (pendingScopeBatches.length === 0 && pendingProgress === null) return;
  const batches = pendingScopeBatches;
  const progress = pendingProgress;
  pendingScopeBatches = [];
  pendingProgress = null;
  useAppStore.setState((state) => {
    const patch: Partial<AppState> = {};
    if (batches.length > 0) {
      // scopes の shallow copy は 1 フレームにつき 1 回だけ (= 旧実装はバッチ毎)。
      const scopes = { ...state.scopes };
      for (const b of batches) {
        const current = scopes[b.scope_id] ?? createScopeBuffer();
        scopes[b.scope_id] = appendScopeBatchSoA(current, b.times, b.values);
      }
      patch.scopes = scopes;
    }
    if (progress !== null) patch.progress = progress;
    return patch;
  });
}

/** 予約済み flush を解除し pending を破棄する (run 開始 / scope リセット時)。 */
function cancelPendingStream(): void {
  if (scopeFlushHandle !== null) {
    cancelFrame(scopeFlushHandle);
    scopeFlushHandle = null;
  }
  pendingScopeBatches = [];
  pendingProgress = null;
}

// ---------------------------------------------------------------------------
// ADR-0019 §(5) / ADR-0021 §(2) helper functions:
// editingModel の編集 API (現在 path 配下を更新する)
// ---------------------------------------------------------------------------

function currentPath(): readonly string[] {
  return useAppStore.getState().editingPath;
}

/**
 * ADR-0057 §(5) 孤児掃除: ``path`` 先 scope の branch_waypoint のうち、枝が 2 本
 * 未満になったグループのものを drop した model を返す。waypoint が無い / 変化が
 * 無ければ identity を保つ (= 余計な書き込みを避ける)。connection 削除・block
 * 削除の applyEditingModel 内で同 fn として呼び、操作と同一履歴に畳む。
 */
function pruneOrphanWaypointsAtScope(
  model: FlwModel,
  path: readonly string[],
): FlwModel {
  let waypoints: BranchWaypointDict;
  try {
    waypoints = resolveBranchWaypointsAtPath(model, path);
  } catch {
    return model; // path 不整合は no-op (= remove 系の race と同じ握り潰し方針)
  }
  if (Object.keys(waypoints).length === 0) return model;
  let connections: ConnectionEntry[];
  try {
    connections = resolveBlocksAtPath(model, path).connections;
  } catch {
    return model;
  }
  const pruned = pruneBranchWaypoints(connections, waypoints);
  // 変化なし判定はキー集合の一致で行う (pruneBranchWaypoints は subset しか返さない
  // ため現状は件数比較でも十分だが、将来の仕様変更に対し堅牢にする)。
  const prunedKeys = Object.keys(pruned);
  const originalKeys = Object.keys(waypoints);
  if (
    prunedKeys.length === originalKeys.length &&
    prunedKeys.every((k) => k in waypoints)
  ) {
    return model; // 孤児が出なかった (= identity 不変)
  }
  return applyBranchWaypointsAtPath(model, path, () => pruned);
}

export function addBlockToEditing(
  block: BlockEntry,
  position: { x: number; y: number },
): void {
  const path = currentPath();
  const isInport = block.type === INPORT_TYPE;
  const isOutport = block.type === OUTPORT_TYPE;
  const isPort = isInport || isOutport;

  useAppStore.getState().applyEditingModel((m) => {
    let updated = m;

    // (1) path 配下に block を追加。Inport / Outport なら port_idx を内部の
    //     既存同種 count に上書き (= 連番採番、_build 検証と整合)。
    //     ADR-0039: 親 Subsystem の n_inputs / n_outputs は派生 property のため、
    //     ここで明示的に +1 する処理は不要 (= 内部 Inport を追加するだけで
    //     `dynamicPorts.resolvePortCounts` が自動派生する)。
    updated = applyAtPath(updated, path, (view) => {
      let inserted = block;
      if (isPort) {
        const sameTypeCount = view.blocks.filter(
          (b) => b.type === block.type,
        ).length;
        inserted = {
          ...block,
          params: { ...block.params, port_idx: sameTypeCount },
        };
      }
      return {
        blocks: [...view.blocks, inserted],
        connections: view.connections,
        layout: { ...view.layout, [inserted.id]: position },
      };
    });

    // (2) ADR-0058 §論点 4: Subsystem 内部に Trigger / Enable control block が
    //     ある場合、それらの slot index は [data_inports..., enable, trigger]
    //     順なので、新 Inport を追加すると enable / trigger の dst_idx が +1
    //     シフトする。旧 ADR-0036 の TriggeredSubsystem 専用 shift ロジックを
    //     filter ベースで一般化したもの。
    if (isInport && path.length > 0) {
      const parentPath = path.slice(0, -1);
      const parentSubId = path[path.length - 1]!;
      updated = applyAtPath(updated, parentPath, (view) => {
        const parentBlock = view.blocks.find((b) => b.id === parentSubId);
        if (!parentBlock) {
          console.warn(
            `[appStore] addBlockToEditing: parent subsystem "${parentSubId}" not found at path`,
            path,
          );
          return view;
        }
        if (!parentBlock.type.endsWith(".Subsystem")) {
          return view; // Subsystem 以外は対象外
        }
        const innerBlocks =
          (parentBlock.params as { blocks?: BlockEntry[] }).blocks ?? [];
        const hasEnable = innerBlocks.some((b) => b.type === ENABLE_TYPE);
        const hasTrigger = innerBlocks.some((b) => b.type === TRIGGER_TYPE);
        if (!hasEnable && !hasTrigger) {
          return view; // 制御ブロックなし → シフト不要
        }
        // 旧 (= 新 Inport 追加前) の slot index を計算。追加後の innerBlocks には
        // 新 Inport が含まれるため、Inport count から 1 引いて旧 inport count を
        // 得る。slot 順は [data_inports..., enable, trigger]。
        const oldInportCount =
          innerBlocks.filter((b) => b.type === INPORT_TYPE).length - 1;
        const oldEnableIdx = hasEnable ? oldInportCount : -1;
        const oldTriggerIdx = hasTrigger
          ? oldInportCount + (hasEnable ? 1 : 0)
          : -1;
        const newConnections = view.connections.map((c) => {
          if (c.dst !== parentSubId) return c;
          if (oldEnableIdx >= 0 && c.dst_idx === oldEnableIdx) {
            return { ...c, dst_idx: c.dst_idx + 1 };
          }
          if (oldTriggerIdx >= 0 && c.dst_idx === oldTriggerIdx) {
            return { ...c, dst_idx: c.dst_idx + 1 };
          }
          return c;
        });
        return {
          blocks: view.blocks,
          connections: newConnections,
          layout: view.layout,
        };
      });
    }

    return updated;
  });
}

export function removeBlockFromEditing(blockId: string): void {
  const path = currentPath();

  useAppStore.getState().applyEditingModel((m) => {
    // 削除対象 block の type / port_idx を先に特定 (= path 配下 view を覗いて
    // Inport / Outport なら親同期が必要かどうかを決める)
    let target: BlockEntry | undefined;
    try {
      const view = resolveBlocksAtPath(m, path);
      target = view.blocks.find((b) => b.id === blockId);
    } catch (err) {
      // path 不整合は通常 onNodesChange の race で発生し得る。エラーを握り潰さず
      // 警告を残して no-op で返す (= code-reviewer SHOULD-3)。
      console.error(
        "[appStore] removeBlockFromEditing: failed to resolve path",
        path,
        err,
      );
      target = undefined;
    }
    if (!target) return m;
    const targetType = target.type;

    const isInport = targetType === INPORT_TYPE;
    const isOutport = targetType === OUTPORT_TYPE;
    const isPort = isInport || isOutport;
    const targetParams = target.params as Record<string, unknown>;
    const rawPortIdx = targetParams.port_idx;
    const removedPortIdx =
      isPort && typeof rawPortIdx === "number" && Number.isFinite(rawPortIdx)
        ? rawPortIdx
        : undefined;

    let updated = m;

    // (1) path 配下から block 削除 + 関連 connection 削除 + 残った同種 port の
    //     port_idx 連番再割り当 (削除した port_idx より大きいものを -1)
    updated = applyAtPath(updated, path, (view) => {
      const blocks = view.blocks
        .filter((b) => b.id !== blockId)
        .map((b) => {
          if (removedPortIdx === undefined || b.type !== targetType) return b;
          const idx = getNumberParam(
            b.params as Record<string, unknown>,
            "port_idx",
            -1,
          );
          if (idx > removedPortIdx) {
            return { ...b, params: { ...b.params, port_idx: idx - 1 } };
          }
          return b;
        });
      const connections = view.connections.filter(
        (c) => c.src !== blockId && c.dst !== blockId,
      );
      const layout = { ...view.layout };
      delete layout[blockId];
      return { blocks, connections, layout };
    });

    // (2) 親階層 connections のシフト/削除のみ実行 (= ADR-0039: 親
    //     n_inputs / n_outputs は派生 property のため明示的な -1 は不要)。
    //     port_idx 連番再割り当てに伴って親階層の dst_idx (Inport) / src_idx
    //     (Outport) を追従させる。Subsystem 内部 Trigger / Enable 接続も
    //     `dst_idx > removedPortIdx` のシフトで自動的に末尾を保つ
    //     (ADR-0058 §論点 4)。
    if (isPort && path.length > 0 && removedPortIdx !== undefined) {
      const parentPath = path.slice(0, -1);
      const parentSubId = path[path.length - 1]!;
      updated = applyAtPath(updated, parentPath, (view) => {
        const parentBlock = view.blocks.find((b) => b.id === parentSubId);
        if (!parentBlock) {
          console.warn(
            `[appStore] removeBlockFromEditing: parent subsystem "${parentSubId}" not found at path`,
            path,
          );
          return view;
        }
        const newConnections = view.connections
          .filter((c) => {
            if (
              isInport &&
              c.dst === parentSubId &&
              c.dst_idx === removedPortIdx
            )
              return false;
            if (
              isOutport &&
              c.src === parentSubId &&
              c.src_idx === removedPortIdx
            )
              return false;
            return true;
          })
          .map((c) => {
            if (
              isInport &&
              c.dst === parentSubId &&
              c.dst_idx > removedPortIdx
            ) {
              return { ...c, dst_idx: c.dst_idx - 1 };
            }
            if (
              isOutport &&
              c.src === parentSubId &&
              c.src_idx > removedPortIdx
            ) {
              return { ...c, src_idx: c.src_idx - 1 };
            }
            return c;
          });
        return {
          blocks: view.blocks,
          connections: newConnections,
          layout: view.layout,
        };
      });
    }

    // ADR-0057 §(5): block 削除で枝が消えた分岐の手動 waypoint を drop。block 自身
    // の scope (= path) と、Inport/Outport 削除で親 connection が変わった場合は親
    // scope の両方を掃除する (port_idx シフトで孤児化したキーも 2 本未満なら drop)。
    updated = pruneOrphanWaypointsAtScope(updated, path);
    if (isPort && path.length > 0 && removedPortIdx !== undefined) {
      updated = pruneOrphanWaypointsAtScope(updated, path.slice(0, -1));
    }

    return updated;
  });
}

export function updateBlockPosition(
  blockId: string,
  position: { x: number; y: number },
): void {
  const path = currentPath();
  useAppStore.getState().applyEditingModel(
    (m) =>
      applyAtPath(m, path, (view) => {
        // 既存 entry の w/h を保持しつつ x/y のみ更新
        const prev = view.layout[blockId];
        const next = {
          ...view.layout,
          [blockId]: { ...prev, x: position.x, y: position.y },
        };
        return {
          blocks: view.blocks,
          connections: view.connections,
          layout: next,
        };
      }),
    // v0.20.1: 連続ドラッグの 1px ごとの呼び出しを 1 履歴エントリに集約
    { mergeKey: `move:${blockId}` },
  );
}

/**
 * v0.16.0: 複数 block の position 更新をまとめて 1 回の ``applyEditingModel`` で
 * 適用する batch 版。複数選択ドラッグで React Flow が 1 frame に渡してくる
 * 複数の position changes を、個別 set による中間 re-render 連発で処理すると、
 * edge 計算が「一部 node は新座標 / 一部は旧座標」の中間状態で走り、edge が
 * ブロックに追随しないように見える (= 追従の連動ズレ)。本関数は 1 回の set で
 * 全 position を更新し、edge 計算も 1 回の整合した状態で行わせる。
 *
 * @param updates 各 block の id と新しい position の配列。空配列なら no-op。
 */
export function updateBlockPositions(
  updates: readonly { id: string; x: number; y: number }[],
): void {
  if (updates.length === 0) return;
  const path = currentPath();
  // v0.20.1: 同じ block 群の連続ドラッグを 1 履歴に集約。merge key は ids を
  // ソートして連結 (= 同じ集合を選択して動かしている間はずっと同じ key)。
  const ids = updates.map((u) => u.id).slice().sort();
  const mergeKey = `move-multi:${ids.join(",")}`;
  useAppStore.getState().applyEditingModel(
    (m) =>
      applyAtPath(m, path, (view) => {
        const next: LayoutDict = { ...view.layout };
        for (const u of updates) {
          const prev = next[u.id];
          next[u.id] = { ...prev, x: u.x, y: u.y };
        }
        return {
          blocks: view.blocks,
          connections: view.connections,
          layout: next,
        };
      }),
    { mergeKey },
  );
}

/**
 * v0.16.0: モデル全体の simulator config (= t_end / dt / solver / rtol / atol /
 * dt_base) を patch する。Subsystem 内部のドリルダウンに関わらず、トップレベル
 * モデルの ``simulator`` フィールドを更新する (= simulator は単一スコープ)。
 *
 * autosave に乗せるため ``applyEditingModel`` 経由で書き込む。
 */
export function updateSimulatorConfig(patch: Partial<SimulatorConfig>): void {
  // v0.20.1: 同じフィールドの連続入力 (= number input の typing) を 1 履歴に集約。
  // 異なるフィールドの編集は別 entry になる (= mergeKey が変わる)。
  const fieldKeys = Object.keys(patch).slice().sort().join(",");
  useAppStore.getState().applyEditingModel(
    (m) => ({
      ...m,
      simulator: { ...m.simulator, ...patch },
    }),
    { mergeKey: `sim-config:${fieldKeys}` },
  );
}

export function updateBlockSize(
  blockId: string,
  size: { w: number; h: number },
): void {
  const path = currentPath();
  useAppStore.getState().applyEditingModel(
    (m) =>
      applyAtPath(m, path, (view) => {
        const prev = view.layout[blockId];
        // 位置情報がまだ無い場合は (0,0) で fallback (= NodeResizer 作動時に必ず position は
        // 別途 onNodesChange でも書かれているので、ほぼ起きないケース)
        const next = {
          ...view.layout,
          [blockId]: {
            x: prev?.x ?? 0,
            y: prev?.y ?? 0,
            w: size.w,
            h: size.h,
          },
        };
        return {
          blocks: view.blocks,
          connections: view.connections,
          layout: next,
        };
      }),
    // v0.20.1: 連続リサイズドラッグを 1 履歴に集約
    { mergeKey: `resize:${blockId}` },
  );
}

/**
 * v0.15.0: ブロックの左右反転フラグをトグルする (リファレンスツールの "Flip Block" 相当)。
 * ``layout[blockId].flipped`` を反転、純粋な GUI metadata で backend 計算には
 * 影響しない。``layout`` entry が無ければ作る。
 */
export function toggleBlockFlipped(blockId: string): void {
  const path = currentPath();
  useAppStore.getState().applyEditingModel((m) =>
    applyAtPath(m, path, (view) => {
      const prev = view.layout[blockId];
      const newFlipped = !(prev?.flipped ?? false);
      const next = {
        ...view.layout,
        [blockId]: {
          x: prev?.x ?? 0,
          y: prev?.y ?? 0,
          ...(prev?.w !== undefined ? { w: prev.w } : {}),
          ...(prev?.h !== undefined ? { h: prev.h } : {}),
          // ``true`` のときだけ書き込む = false に戻したら field を消す (= JSON
          // byte-identical 維持、normalize_layout も同じ方針)。
          ...(newFlipped ? { flipped: true } : {}),
        },
      };
      return {
        blocks: view.blocks,
        connections: view.connections,
        layout: next,
      };
    }),
  );
}

export function updateBlocksLayout(layout: LayoutDict): void {
  const path = currentPath();
  useAppStore.getState().applyEditingModel((m) =>
    applyAtPath(m, path, (view) => ({
      blocks: view.blocks,
      connections: view.connections,
      layout,
    })),
  );
}

export function addConnectionToEditing(conn: ConnectionEntry): void {
  const path = currentPath();
  useAppStore.getState().applyEditingModel((m) =>
    applyAtPath(m, path, (view) => {
      const filtered = view.connections.filter(
        (c) => !(c.dst === conn.dst && c.dst_idx === conn.dst_idx),
      );
      return {
        blocks: view.blocks,
        connections: [...filtered, conn],
        layout: view.layout,
      };
    }),
  );
}

export function removeConnectionFromEditing(
  src: string,
  src_idx: number,
  dst: string,
  dst_idx: number,
): void {
  const path = currentPath();
  useAppStore.getState().applyEditingModel((m) => {
    const afterConn = applyAtPath(m, path, (view) => ({
      blocks: view.blocks,
      connections: view.connections.filter(
        (c) =>
          !(
            c.src === src &&
            c.src_idx === src_idx &&
            c.dst === dst &&
            c.dst_idx === dst_idx
          ),
      ),
      layout: view.layout,
    }));
    // ADR-0057 §(5): 枝が 2 本未満になった分岐の手動 waypoint を同一履歴で drop。
    return pruneOrphanWaypointsAtScope(afterConn, path);
  });
}

/**
 * ADR-0057 (改訂): 手動分岐点 (● のドラッグ固定位置) を現 scope の branch_waypoints
 * に書き込む。``key`` は合成キー ``"<source block id>:<sourceHandle index>"``。値は
 * 幹線方向の 1 次元位置 ``{ axis, pos }`` (直交成分は保存しない = SSOT、R3)。
 * ``connections`` には一切触らない (= トポロジ不変、シミュレーション意味論不変)。
 *
 * @param key 合成キー ``"<src>:<src_idx>"``。
 * @param value 幹線方向位置 (``axis`` = 幹線軸、``pos`` = 幹線方向の絶対座標スカラ)。
 *   ``pos`` が NaN / Infinity の場合は無視する (DOM / 保存に渡さない)。
 * @param opts.merge ``true`` でドラッグ連続更新を 1 履歴エントリに集約する
 *   (= ノード移動の ``mergeKey`` と同方針)。
 */
export function setBranchWaypoint(
  key: string,
  value: BranchWaypoint,
  opts?: { merge?: boolean },
): void {
  // 退化座標ガード (junctionDots.ts の finite ガードと同方針)。
  if (!Number.isFinite(value.pos)) return;
  const path = currentPath();
  useAppStore.getState().applyEditingModel(
    (m) =>
      applyBranchWaypointsAtPath(m, path, (wp) => ({
        ...wp,
        [key]: { axis: value.axis, pos: value.pos },
      })),
    opts?.merge
      ? { mergeKey: `branch-waypoint:${path.join("/")}:${key}` }
      : undefined,
  );
}

/**
 * ADR-0057 §(6): 手動分岐点をリセットして自動計算 ● に戻す (= 該当合成キーを
 * 現 scope の branch_waypoints から削除)。キーが無ければ no-op (= 履歴を汚さない)。
 */
export function resetBranchWaypoint(key: string): void {
  const path = currentPath();
  useAppStore.getState().applyEditingModel((m) => {
    let cur: BranchWaypointDict;
    try {
      cur = resolveBranchWaypointsAtPath(m, path);
    } catch {
      return m;
    }
    if (!(key in cur)) return m; // no-op
    return applyBranchWaypointsAtPath(m, path, (wp) => {
      const next = { ...wp };
      delete next[key];
      return next;
    });
  });
}

/**
 * v0.26.0 (リファレンスツールの auto-connect-on-edge): エッジを 1 件削除し、source → block →
 * target の 2 本を atomic に追加する (= 履歴 1 entry にまとめる、undo で 1 回で元に戻る)。
 * 同 dst_idx に既存接続があれば置換 (= ``addConnectionToEditing`` と同じ規約)。
 */
export function spliceEdgeWithBlock(
  oldEdge: { src: string; src_idx: number; dst: string; dst_idx: number },
  blockId: string,
  blockInputIdx: number = 0,
  blockOutputIdx: number = 0,
): void {
  const path = currentPath();
  useAppStore.getState().applyEditingModel((m) =>
    applyAtPath(m, path, (view) => {
      // 旧 edge を除外
      const withoutOld = view.connections.filter(
        (c) =>
          !(
            c.src === oldEdge.src &&
            c.src_idx === oldEdge.src_idx &&
            c.dst === oldEdge.dst &&
            c.dst_idx === oldEdge.dst_idx
          ),
      );
      // 新 2 本 (= 同 dst_idx と衝突する既存接続も置換するため filter 適用)
      const upstream = {
        src: oldEdge.src,
        src_idx: oldEdge.src_idx,
        dst: blockId,
        dst_idx: blockInputIdx,
      };
      const downstream = {
        src: blockId,
        src_idx: blockOutputIdx,
        dst: oldEdge.dst,
        dst_idx: oldEdge.dst_idx,
      };
      const dedup = withoutOld.filter(
        (c) =>
          !(c.dst === upstream.dst && c.dst_idx === upstream.dst_idx) &&
          !(c.dst === downstream.dst && c.dst_idx === downstream.dst_idx),
      );
      return {
        blocks: view.blocks,
        connections: [...dedup, upstream, downstream],
        layout: view.layout,
      };
    }),
  );
}

export function updateBlockParams(
  blockId: string,
  params: Record<string, unknown>,
  registry?: ReadonlyMap<string, BlockMetadata>,
): void {
  const path = currentPath();
  useAppStore.getState().applyEditingModel(
    (m) =>
      applyAtPath(m, path, (view) => {
        const target = view.blocks.find((b) => b.id === blockId);
        if (!target) return view;
        const newBlocks = view.blocks.map((b) =>
          b.id === blockId ? { ...b, params } : b,
        );
        // param 変更により port 数が減った場合、index out-of-range の edge を剪定する。
        const meta = registry?.get(target.type);
        const before = resolvePortCounts(target.type, target.params, meta);
        const after = resolvePortCounts(target.type, params, meta);
        let newConnections = view.connections;
        if (after.nInputs < before.nInputs || after.nOutputs < before.nOutputs) {
          newConnections = view.connections.filter((c) => {
            if (c.dst === blockId && c.dst_idx >= after.nInputs) return false;
            if (c.src === blockId && c.src_idx >= after.nOutputs) return false;
            return true;
          });
        }
        return {
          blocks: newBlocks,
          connections: newConnections,
          layout: view.layout,
        };
      }),
    // v0.20.1: 同じブロックの param 連続編集 (= ParameterPanel の number input
    // を typing する間) を 1 履歴に集約。別ブロック / 別アクションで分離。
    { mergeKey: `params:${blockId}` },
  );
}

// ---------------------------------------------------------------------------
// 全選択 / コピー / 貼り付け (リファレンスツール準拠 Ctrl+A / Ctrl+C / Ctrl+V)
// ---------------------------------------------------------------------------

/**
 * 現在 path 配下のすべての node + edge を選択状態にする。
 * 入力フォーカス中は呼び出し側で抑制する想定 (= テキスト編集中の Ctrl+A は
 * テキスト全選択として OS / ブラウザが扱うべき)。
 */
export function selectAllInScope(): void {
  const state = useAppStore.getState();
  const model = state.editingModel;
  if (!model) return;
  let view;
  try {
    view = resolveBlocksAtPath(model, state.editingPath);
  } catch {
    return;
  }
  state.setSelectedNodeIds(view.blocks.map((b) => b.id));
  // edge id 規則 = modelToDiagram の "e{idx}-{src}-{dst}" と一致させる
  state.setSelectedEdgeIds(
    view.connections.map((c, idx) => `e${idx}-${c.src}-${c.dst}`),
  );
}

/**
 * 選択中の block + そのブロック間に閉じる connection を clipboard に保存する。
 * 既存 layout も込みで保存し、paste 時にレイアウトを忠実に再現する。
 */
export function copySelectionToClipboard(): void {
  const state = useAppStore.getState();
  const model = state.editingModel;
  if (!model || state.selectedNodeIds.length === 0) return;
  let view;
  try {
    view = resolveBlocksAtPath(model, state.editingPath);
  } catch {
    return;
  }
  const selectedSet = new Set(state.selectedNodeIds);
  const blocks = view.blocks
    .filter((b) => selectedSet.has(b.id))
    .map((b) => ({ ...b, params: deepClone(b.params) }));
  // 選択ブロック同士の connection だけコピー (= 切れた配線の貼り付けは不自然)
  const connections = view.connections.filter(
    (c) => selectedSet.has(c.src) && selectedSet.has(c.dst),
  );
  const layout: LayoutDict = {};
  for (const id of selectedSet) {
    const e = view.layout[id];
    if (e) layout[id] = { ...e };
  }
  state.setClipboard({ blocks, connections, layout });
}

/**
 * Clipboard の中身を現在 path / オフセットで貼り付け。新しい block id を生成し、
 * connection の src/dst を新 id にリマップする。貼り付け後、貼り付けた block 群を
 * 選択状態にする。
 */
export function pasteClipboard(offset = { x: 20, y: 20 }): void {
  const state = useAppStore.getState();
  const cb = state.clipboard;
  if (!cb || cb.blocks.length === 0) return;
  const path = state.editingPath;

  const idMap = new Map<string, string>();
  let pastedIds: string[] = [];

  state.applyEditingModel((m) =>
    applyAtPath(m, path, (view) => {
      const existingIds = new Set(view.blocks.map((b) => b.id));
      // ID 採番: generateUniqueId と同じく "{typeName}_{i}" を空きまでスキャン。
      // store の独立性のため inline 実装。
      const allocateId = (orig: string): string => {
        const typeName = orig.split("_")[0] ?? orig;
        for (let i = 0; i < 10000; i++) {
          const candidate = `${typeName}_${i}`;
          if (!existingIds.has(candidate)) {
            existingIds.add(candidate);
            return candidate;
          }
        }
        throw new Error(`Cannot allocate id for paste from ${orig}`);
      };

      const newBlocks: BlockEntry[] = [];
      for (const b of cb.blocks) {
        const newId = allocateId(b.id);
        idMap.set(b.id, newId);
        newBlocks.push({ ...b, id: newId, params: deepClone(b.params) });
      }
      pastedIds = newBlocks.map((b) => b.id);

      const newConnections = cb.connections
        .map((c) => {
          const src = idMap.get(c.src);
          const dst = idMap.get(c.dst);
          if (!src || !dst) return null;
          return { ...c, src, dst };
        })
        .filter((c): c is ConnectionEntry => c !== null);

      const newLayout: LayoutDict = { ...view.layout };
      for (const [oldId, entry] of Object.entries(cb.layout)) {
        const newId = idMap.get(oldId);
        if (!newId) continue;
        newLayout[newId] = {
          ...entry,
          x: entry.x + offset.x,
          y: entry.y + offset.y,
        };
      }

      return {
        blocks: [...view.blocks, ...newBlocks],
        connections: [...view.connections, ...newConnections],
        layout: newLayout,
      };
    }),
  );

  // 貼り付けた block 群を選択 (リファレンスツールでも Ctrl+V 直後は新規分が選択される)
  if (pastedIds.length > 0) {
    state.setSelectedNodeIds(pastedIds);
  }
}

function deepClone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T;
}

// ADR-0021 §(9): Subsystem の mask_values 更新 (= ParameterPanel mask edit からの呼び出し)
export function updateSubsystemMaskValues(
  subsystemId: string,
  maskValues: MaskValuesDict,
): void {
  const path = currentPath();
  useAppStore.getState().applyEditingModel(
    (m) =>
      applyAtPath(m, path, (view) => ({
        blocks: view.blocks.map((b) => {
          if (b.id !== subsystemId) return b;
          return {
            ...b,
            params: { ...b.params, mask_values: maskValues },
          };
        }),
        connections: view.connections,
        layout: view.layout,
      })),
    // v0.20.1: 同じ subsystem の mask 連続編集を 1 履歴に集約
    { mergeKey: `mask:${subsystemId}` },
  );
}
