// ADR-0045 §(1) §(2) §(6): Workspace JupyterLab Stage 1 = multi-pane split。
// 上位の SplitTree (= ``useAppStore.workspaceLayout``) を再帰的に
// ``<PanelGroup>`` + ``<Panel>`` に展開し、各葉ノード paneId に応じて
// Diagram slot / Scope / scopes-stack を描画する。
//
// **viewport 保持**: Diagram pane は本コンポーネント内では「空の div + ref」のみ
// 描画し、実際の ``<DiagramCanvas>`` は App.tsx で常時 mount された portal が
// この div に投影する (= ADR-0045 §(6) "React Portal" 実装方式)。
//
// **永続化**: drag resize の最終 ratio は ``<PanelGroup onLayout>`` で受け取り、
// `store.setWorkspaceSplitRatio` で localStorage に書き出す (ADR §(1))。

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Group as PanelGroup,
  type Layout,
  Panel,
  Separator as PanelResizeHandle,
} from "react-resizable-panels";

import {
  type ScopeBuffer,
  useAppStore,
} from "../store/appStore";
import {
  computeDropZone,
  type DropZone,
  dropZoneToSplit,
  PYFLW_TAB_REF_MIME,
} from "../lib/dnd";
import {
  findLeaf,
  getLeafPaneIds,
  makeSplitId,
  type SplitNode,
  type SplitTree,
} from "../lib/splitTree";
import { PaneTitleBar } from "./PaneTitleBar";
import { ParameterPanel } from "./ParameterPanel";
import { ScopeView } from "./ScopeView";
import { XYGraphView } from "./XYGraphView";

interface WorkspaceSplitProps {
  /** Diagram slot ``<div>`` の DOM ノードを受け取る ref callback。
   * SplitTree 再構造で slot div が再生成された時に新しい el が渡される。
   * App.tsx でこれを使って ``<DiagramCanvas portalTarget={el} />`` を切替。 */
  setDiagramSlot: (el: HTMLDivElement | null) => void;
  /** Display 以外で実体のある Scope / XYGraph の entries (= ADR-0044 と同じ判定)。 */
  visibleScopeEntries: Array<[string, ScopeBuffer]>;
  /** scope_id → block.type マップ (= ``XYGraph`` 判別用)。 */
  blockTypeById: Map<string, string>;
  /** v0.27.1: モデルが構造的に Scope/XYGraph ブロックを持つか (= sim 未実行でも true)。
   * 空 ``scopes-stack`` pane の表示文言を「sim 未実行」と「全分離済」で出し分ける。 */
  hasScopeBlocks: boolean;
}

export function WorkspaceSplit({
  setDiagramSlot,
  visibleScopeEntries,
  blockTypeById,
  hasScopeBlocks,
}: WorkspaceSplitProps): JSX.Element {
  const { t } = useTranslation();
  const layout = useAppStore((s) => s.workspaceLayout);
  const splitPane = useAppStore((s) => s.splitPane);
  const unsplitPane = useAppStore((s) => s.unsplitPane);
  const setRatio = useAppStore((s) => s.setWorkspaceSplitRatio);
  // ADR-0052 §(3): Scope detach (= Rnd float に切替) で再利用
  const openScopePanel = useAppStore((s) => s.openScopePanel);
  const selectedFilePath = useAppStore((s) => s.selectedFilePath);

  // SplitTree 内で独立分離されている scope:<id> 葉の集合
  const splitOutScopeIds = useMemo(() => {
    const ids = new Set<string>();
    for (const pid of getLeafPaneIds(layout)) {
      if (pid.startsWith("scope:")) ids.add(pid.slice("scope:".length));
    }
    return ids;
  }, [layout]);

  // scopes-stack pane に表示する entries (= 独立分離されていないもの)
  const stackEntries = useMemo(
    () => visibleScopeEntries.filter(([id]) => !splitOutScopeIds.has(id)),
    [visibleScopeEntries, splitOutScopeIds],
  );

  // 葉単位で scope_id → buffer を引けるマップ
  const allScopes = useMemo(
    () => new Map<string, ScopeBuffer>(visibleScopeEntries),
    [visibleScopeEntries],
  );

  const leafCount = getLeafPaneIds(layout).length;
  const hasScopesStackLeaf = findLeaf(layout, "scopes-stack");

  // v0.27.1 UX-1: 空 scopes-stack pane の表示文言を出し分けるための判定情報。
  // - splitOutAnyScope=true → 「全分離済」(= 個別 pane に分離 + stack は空)
  // - splitOutAnyScope=false → 「sim 未実行」or 「Scope 無し」
  // hasScopeBlocks (= モデル内に Scope/XYGraph ブロックが存在) が true で
  // visibleScopeEntries が empty なら sim 未実行、false なら Scope 無し。
  const splitOutAnyScope = splitOutScopeIds.size > 0;

  const ctx: RenderContext = {
    layout,
    leafCount,
    hasScopesStackLeaf,
    stackEntries,
    allScopes,
    blockTypeById,
    setDiagramSlot,
    splitPane,
    unsplitPane,
    splitOutAnyScope,
    hasScopeBlocks,
    t_scopeLeafCannotSplit: t("workspace.split.disabled.scope_leaf"),
    t_runSimulationToSplit: t("workspace.split.disabled.run_simulation"),
    t_allScopesSeparated: t("workspace.split.disabled.all_separated"),
    openScopePanel,
    InspectorBody: () => (
      <ParameterPanel modelId={selectedFilePath ?? ""} />
    ),
  };

  return (
    <div className="h-full w-full">
      {renderTree(layout, ctx, setRatio)}
    </div>
  );
}

interface RenderContext {
  layout: SplitTree;
  leafCount: number;
  hasScopesStackLeaf: boolean;
  stackEntries: Array<[string, ScopeBuffer]>;
  allScopes: Map<string, ScopeBuffer>;
  blockTypeById: Map<string, string>;
  setDiagramSlot: (el: HTMLDivElement | null) => void;
  splitPane: (
    paneId: string,
    orientation: "horizontal" | "vertical",
    newPaneId: string,
    position?: "after" | "before",
  ) => void;
  unsplitPane: (paneId: string) => void;
  /** v0.27.1 UX-1: scopes-stack 空表示の文言出し分け用。 */
  splitOutAnyScope: boolean;
  hasScopeBlocks: boolean;
  /** v0.27.1 UX-3: split 無効時の tooltip 文言 (= pre-resolved i18n)。 */
  t_scopeLeafCannotSplit: string;
  t_runSimulationToSplit: string;
  t_allScopesSeparated: string;
  /** ADR-0052 §(3) Stage 3: Scope detach (= float に切替) action。 */
  openScopePanel: (scopeId: string) => void;
  /** ADR-0052 §(2) Stage 3: Inspector pane 葉の body component (= ParameterPanel)。 */
  InspectorBody: () => JSX.Element;
}

function renderTree(
  tree: SplitTree,
  ctx: RenderContext,
  setRatio: (splitId: string, ratio: number) => void,
): JSX.Element {
  if (tree.kind === "leaf") return renderLeaf(tree.paneId, ctx);
  return renderSplit(tree, ctx, setRatio);
}

function renderSplit(
  node: SplitNode,
  ctx: RenderContext,
  setRatio: (splitId: string, ratio: number) => void,
): JSX.Element {
  const splitId = makeSplitId(node);
  const direction = node.orientation;
  const aPercent = Math.round(node.ratio * 100);
  const bPercent = 100 - aPercent;
  const handleOrientation: "horizontal" | "vertical" =
    direction === "horizontal" ? "vertical" : "horizontal";
  const aPanelId = `${splitId}/a`;
  const bPanelId = `${splitId}/b`;

  // react-resizable-panels v4: ``onLayoutChanged`` は **drag 終了時のみ** 呼ばれる
  // (= 永続化に最適、``onLayoutChange`` は drag 中も呼ばれるので避ける)。
  // Layout は ``{ <panelId>: flexGrow }`` のマップで、ratio は a / (a + b) で計算。
  // ネスト PanelGroup の場合、outer group の callback には outer Panel id のみ
  // 含まれる想定 (= inner panel id は inner group の callback に届く)。
  const onLayoutChanged = (layout: Layout): void => {
    const a = layout[aPanelId];
    const b = layout[bPanelId];
    if (typeof a !== "number" || typeof b !== "number") {
      // 該当 group の Panel id が layout map に無い ⇒ library 仕様変更や id 衝突
      // などの異常。本来発火しないルートだが、発火したら追跡できるよう warn。
      if (typeof console !== "undefined" && console.warn) {
        console.warn(
          "[pyflw] onLayoutChanged: Panel ids not in Layout map",
          { aPanelId, bPanelId, layoutKeys: Object.keys(layout) },
        );
      }
      return;
    }
    const sum = a + b;
    if (sum <= 0) return;
    const newRatio = a / sum;
    if (Math.abs(newRatio - node.ratio) < 0.001) return;
    setRatio(splitId, newRatio);
  };

  return (
    <PanelGroup
      orientation={direction}
      className="h-full w-full"
      onLayoutChanged={onLayoutChanged}
    >
      <Panel id={aPanelId} defaultSize={aPercent} minSize={10}>
        <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
          {renderTree(node.a, ctx, setRatio)}
        </div>
      </Panel>
      <PanelResizeHandleStyled orientation={handleOrientation} />
      <Panel id={bPanelId} defaultSize={bPercent} minSize={10}>
        <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
          {renderTree(node.b, ctx, setRatio)}
        </div>
      </Panel>
    </PanelGroup>
  );
}

function PanelResizeHandleStyled({
  orientation,
}: {
  orientation: "horizontal" | "vertical";
}): JSX.Element {
  const { t } = useTranslation();
  return (
    <PanelResizeHandle
      aria-orientation={orientation}
      aria-label={
        orientation === "horizontal"
          ? t("workspace.split.handle.horizontal")
          : t("workspace.split.handle.vertical")
      }
      className={
        orientation === "vertical"
          ? "group relative z-10 w-0.5 cursor-col-resize bg-slate-300 transition-colors hover:bg-blue-400 data-[resize-handle-state=drag]:bg-blue-500"
          : "group relative z-10 h-0.5 cursor-row-resize bg-slate-300 transition-colors hover:bg-blue-400 data-[resize-handle-state=drag]:bg-blue-500"
      }
    >
      <div
        className={
          orientation === "vertical"
            ? "absolute inset-y-0 -left-1 -right-1"
            : "absolute inset-x-0 -top-1 -bottom-1"
        }
      />
    </PanelResizeHandle>
  );
}

function renderLeaf(paneId: string, ctx: RenderContext): JSX.Element {
  const isDiagram = paneId === "diagram";
  const isStack = paneId === "scopes-stack";

  // 次の split で新葉に置く paneId を決める。
  // - Diagram: scopes-stack 未登場なら先に "scopes-stack" を、登場済なら stack 内の最初の scope を分離
  // - scopes-stack: stack 内の最初の scope を分離
  // - scope:<id>: 更なる split は Stage 1 では無効 (= scope 葉は終端)
  const nextNewLeaf = ((): string | null => {
    if (isDiagram) {
      if (!ctx.hasScopesStackLeaf) return "scopes-stack";
      const first = ctx.stackEntries[0];
      return first ? `scope:${first[0]}` : null;
    }
    if (isStack) {
      const first = ctx.stackEntries[0];
      return first ? `scope:${first[0]}` : null;
    }
    return null;
  })();

  // v0.30.2: Diagram pane (= isDiagram) からの split は禁止 (ユーザー要望: 6)。
  // Diagram は常に 1 pane で運用、Scope との分割は scopes-stack タイトルバーで操作。
  const onSplitRight =
    !isDiagram && nextNewLeaf !== null
      ? () => ctx.splitPane(paneId, "horizontal", nextNewLeaf)
      : null;
  const onSplitDown =
    !isDiagram && nextNewLeaf !== null
      ? () => ctx.splitPane(paneId, "vertical", nextNewLeaf)
      : null;

  // unsplit:
  // - Diagram: 必ず存在すべき pane なので不許可
  // - 残葉数が 1 のときは不許可 (= unsplit すると tree 全消滅)
  const onUnsplit =
    !isDiagram && ctx.leafCount > 1
      ? () => ctx.unsplitPane(paneId)
      : null;

  // v0.27.1 UX-3 + v0.30.2: split が無効のとき disabled で表示。
  // ただし Diagram pane (v0.30.2 で split 禁止) は **完全 hide** とする
  // (= ユーザー要望「ダイアグラムの分割表示はいらない」)。
  const disabledSplitReason = ((): string | null => {
    if (nextNewLeaf !== null) return null;
    if (isDiagram) return null; // v0.30.2: Diagram は disabled 表示も hide
    if (!isStack) {
      return ctx.t_scopeLeafCannotSplit;
    }
    return ctx.splitOutAnyScope
      ? ctx.t_allScopesSeparated
      : ctx.t_runSimulationToSplit;
  })();

  // 本体描画 + paneId 種別判定 (= ADR-0052 §(1)(2)(3) 新葉対応)
  const isScopeLeaf = !isDiagram && !isStack && paneId.startsWith("scope:");
  const isTabLeaf = paneId.startsWith("tab:");
  const isInspectorLeaf = paneId === "inspector";

  let body: JSX.Element;
  let titleKey: PaneTitleKey;
  let titleRaw: string | null = null;
  if (isDiagram) {
    body = <DiagramSlot setDiagramSlot={ctx.setDiagramSlot} />;
    titleKey = "workspace.pane.title.diagram";
  } else if (isStack) {
    body = (
      <ScopesStack
        entries={ctx.stackEntries}
        blockTypeById={ctx.blockTypeById}
        splitOutAnyScope={ctx.splitOutAnyScope}
        hasScopeBlocks={ctx.hasScopeBlocks}
        onSplitOutScope={(scopeId) =>
          ctx.splitPane("scopes-stack", "vertical", `scope:${scopeId}`)
        }
      />
    );
    titleKey = "workspace.pane.title.scopes_stack";
  } else if (isInspectorLeaf) {
    // ADR-0052 §(2): inspector 葉は ParameterPanel を描画
    body = <ctx.InspectorBody />;
    titleKey = "workspace.pane.title.inspector";
  } else if (isTabLeaf) {
    // ADR-0052 §(1): tab:<filePath> 葉は別タブのモデル view (= 別 file の
    // 読み取り専用 viewport)。Stage 3 MVP では「タブ名表示 + open ボタン」の
    // 軽量プレースホルダーで開始 (= 本格的 multi-edit は Stage 4+)。
    const filePath = paneId.slice("tab:".length);
    body = <TabLeafBody filePath={filePath} />;
    titleKey = "";
    titleRaw = filePath.split("/").pop() ?? filePath;
  } else if (isScopeLeaf) {
    const scopeId = paneId.slice("scope:".length);
    const buffer = ctx.allScopes.get(scopeId);
    const blockType = ctx.blockTypeById.get(scopeId) ?? "";
    body = (
      <ScopeLeafBody
        scopeId={scopeId}
        buffer={buffer}
        blockType={blockType}
      />
    );
    titleKey = "";
    titleRaw = scopeId;
  } else {
    // 未知 paneId: empty fallback
    body = <div className="h-full w-full bg-white" />;
    titleKey = "";
    titleRaw = paneId;
  }

  // ADR-0052 §(3): Scope 葉に「detach」アクション (= Rnd float に切替)
  const onDetach = isScopeLeaf
    ? () => {
        const scopeId = paneId.slice("scope:".length);
        ctx.unsplitPane(paneId);
        ctx.openScopePanel(scopeId);
      }
    : null;

  // v0.30.3: Diagram pane で scopes-stack 葉が tree に無く、かつ Scope ブロックを
  // 持つモデルのとき「Scope エリアを表示」ボタンを提供 (= × で閉じた後の復活
  // 経路、ユーザー要望)
  const onShowScopes =
    isDiagram && !ctx.hasScopesStackLeaf && ctx.hasScopeBlocks
      ? () => ctx.splitPane("diagram", "vertical", "scopes-stack", "after")
      : null;

  return (
    <PaneLeafShell
      titleKey={titleKey}
      titleRaw={titleRaw}
      onSplitRight={onSplitRight}
      onSplitDown={onSplitDown}
      onUnsplit={onUnsplit}
      onDetach={onDetach}
      onShowScopes={onShowScopes}
      disabledSplitReason={disabledSplitReason}
      paneId={paneId}
      onTabDrop={(zone, filePath) => handleTabDrop(ctx, paneId, zone, filePath)}
    >
      {body}
    </PaneLeafShell>
  );
}

/** ADR-0052 §(1): drop event → SplitTree 操作 dispatch helper。
 *
 * - zone="center" → no-op (= タブ追加 semantics は Stage 4+、Stage 3 では skip)
 * - zone=top/right/bottom/left → splitPane(target, orientation, "tab:<filePath>", position)
 *
 * filePath が既に SplitTree 内に `tab:<filePath>` 葉として存在する場合、
 * insertSplit は no-op (= 重複検出、splitTree.ts §insertSplit の規約)。 */
function handleTabDrop(
  ctx: RenderContext,
  targetPaneId: string,
  zone: "center" | "top" | "right" | "bottom" | "left",
  filePath: string,
): void {
  // v0.30.2: Diagram pane への drop は no-op (= 「Diagram の分割表示はいらない」
  // 要望、ボタンと semantics 統一)
  if (targetPaneId === "diagram") return;
  const op = dropZoneToSplit(zone);
  if (op === null) {
    // center drop: Stage 3 MVP では no-op、Stage 4+ で「タブ追加」semantics
    return;
  }
  ctx.splitPane(
    targetPaneId,
    op.orientation,
    `tab:${filePath}`,
    op.position,
  );
}

/** v0.30.0 ADR-0052: tab:<filePath> 葉の本体 (Stage 3 MVP、軽量プレースホルダー)。
 *
 * 別タブのモデルを別 pane で簡易表示。「このファイルを active 編集に切替」
 * ボタンを提示するだけ (= 真の multi-edit viewport は Stage 4 候補)。 */
function TabLeafBody({ filePath }: { filePath: string }): JSX.Element {
  const { t } = useTranslation();
  const switchTab = useAppStore((s) => s.switchTab);
  const tabs = useAppStore((s) => s.tabs);
  const exists = tabs.some((tab) => tab.filePath === filePath);
  return (
    <div className="flex h-full flex-col items-center justify-center bg-slate-50 p-4 text-center text-[11px] text-slate-500">
      <div className="font-mono">{filePath}</div>
      {exists ? (
        <button
          type="button"
          onClick={() => switchTab(filePath)}
          className="mt-2 border border-slate-400 bg-white px-3 py-0.5 text-[11px] hover:bg-slate-100"
        >
          {t("workspace.tab_leaf.switch_to")}
        </button>
      ) : (
        <div className="mt-2 text-[10px] text-slate-400">
          {t("workspace.tab_leaf.not_open")}
        </div>
      )}
    </div>
  );
}

type PaneTitleKey =
  | "workspace.pane.title.diagram"
  | "workspace.pane.title.scopes_stack"
  | "workspace.pane.title.inspector"
  | "";

function PaneLeafShell({
  titleKey,
  titleRaw,
  onSplitRight,
  onSplitDown,
  onUnsplit,
  onDetach,
  onShowScopes,
  disabledSplitReason,
  paneId,
  onTabDrop,
  children,
}: {
  /** i18n キー (= 翻訳して title に使う)。``""`` ならスキップ。
   * Stage 3 で diagram / scopes_stack / inspector の 3 値に拡張。 */
  titleKey: PaneTitleKey;
  /** raw 表示用 (= scope_id / filePath 等、翻訳しない)。``null`` なら titleKey 経由。 */
  titleRaw: string | null;
  onSplitRight: (() => void) | null;
  onSplitDown: (() => void) | null;
  onUnsplit: (() => void) | null;
  /** ADR-0052 §(3) Stage 3: Scope detach action (= float に切替)。null で hide。 */
  onDetach: (() => void) | null;
  /** v0.30.3: Diagram pane 専用「Scope エリアを表示」action。null で hide。 */
  onShowScopes: (() => void) | null;
  /** v0.27.1 UX-3: split 無効時の tooltip 文言。 */
  disabledSplitReason: string | null;
  /** ADR-0052 §(1) Stage 3: drop target identification。 */
  paneId: string;
  /** ADR-0052 §(1) Stage 3: drop event handler (zone, filePath)。 */
  onTabDrop: (zone: DropZone, filePath: string) => void;
  children: React.ReactNode;
}): JSX.Element {
  const { t } = useTranslation();
  // ADR-0052 §(1) Stage 3: drag over 中の hover zone (= 5 領域 visual feedback)
  const [hoverZone, setHoverZone] = useState<DropZone | null>(null);
  // titleKey が limited union なので t() の strict-typed signature を満たす
  const title =
    titleRaw ??
    (titleKey === "workspace.pane.title.diagram"
      ? t("workspace.pane.title.diagram")
      : titleKey === "workspace.pane.title.scopes_stack"
        ? t("workspace.pane.title.scopes_stack")
        : titleKey === "workspace.pane.title.inspector"
          ? t("workspace.pane.title.inspector")
          : "");

  // ADR-0052 §(1) §(3): drop event handlers。Scope pane / Diagram pane / Inspector
  // pane / scopes-stack に drop 可能、tab:<filePath> 葉自身への drop も可。
  const onDragOver = (e: React.DragEvent<HTMLDivElement>): void => {
    if (!e.dataTransfer.types.includes(PYFLW_TAB_REF_MIME)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    const rect = e.currentTarget.getBoundingClientRect();
    setHoverZone(computeDropZone(rect, e.clientX, e.clientY));
  };
  const onDragLeave = (e: React.DragEvent<HTMLDivElement>): void => {
    // ADR-0052 code-reviewer §SHOULD #3: HTML5 drag event は子要素への移動
    // でも dragleave を発火する。relatedTarget が自要素の内側なら無視 (=
    // hover zone overlay のチラつき防止)。
    if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
    setHoverZone(null);
  };
  const onDrop = (e: React.DragEvent<HTMLDivElement>): void => {
    const filePath = e.dataTransfer.getData(PYFLW_TAB_REF_MIME);
    setHoverZone(null);
    if (!filePath) return;
    e.preventDefault();
    e.stopPropagation();
    // tab:<filePath> 葉自身を自分自身に drop は no-op
    if (paneId === `tab:${filePath}`) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const zone = computeDropZone(rect, e.clientX, e.clientY);
    onTabDrop(zone, filePath);
  };

  return (
    <div
      className="relative flex h-full min-h-0 flex-col overflow-hidden bg-white"
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <PaneTitleBar
        title={title}
        onSplitRight={onSplitRight}
        onSplitDown={onSplitDown}
        onUnsplit={onUnsplit}
        onDetach={onDetach}
        onShowScopes={onShowScopes}
        disabledSplitReason={disabledSplitReason}
      />
      <div className="min-h-0 flex-1 overflow-hidden">{children}</div>
      {/* ADR-0052 §(1) Stage 3: drag-over 中の drop zone overlay (= 5 領域
          visual feedback、`pointer-events: none` で drop event を阻害しない) */}
      {hoverZone !== null && (
        <DropZoneOverlay zone={hoverZone} />
      )}
    </div>
  );
}

/** ADR-0052 §(1): drop zone overlay。pane 内 absolute 配置、bg-blue-200/40。 */
function DropZoneOverlay({ zone }: { zone: DropZone }): JSX.Element {
  // pane 内相対比率で 5 領域を描画 (= dropZoneOverlayRect は absolute 座標版、
  // ここでは parent relative + Tailwind class で簡素化)
  const cls = ((): string => {
    switch (zone) {
      case "center":
        return "absolute inset-1/4 bg-blue-200/50";
      case "top":
        return "absolute inset-x-0 top-0 h-1/2 bg-blue-200/50";
      case "bottom":
        return "absolute inset-x-0 bottom-0 h-1/2 bg-blue-200/50";
      case "left":
        return "absolute inset-y-0 left-0 w-1/2 bg-blue-200/50";
      case "right":
        return "absolute inset-y-0 right-0 w-1/2 bg-blue-200/50";
    }
  })();
  return (
    <div
      aria-hidden="true"
      className={`pointer-events-none ${cls} border-2 border-blue-500/60`}
    />
  );
}

/** Diagram の slot div を描画 + ref callback で App.tsx に DOM ノードを伝達。
 *
 * React の ref callback は cleanup の null 呼び出しが新規 attach より先に発火
 * するため、SplitTree 再構造で diagram leaf の DOM 位置が変わる際に App.tsx
 * の portal target が一瞬 null に落ちる可能性がある。これは ReactFlow の
 * 再 mount を引き起こさない (= ``<DiagramCanvas>`` 自体は React tree 上で同じ
 * 親に居続ける) ため viewport は保持される。 */
function DiagramSlot({
  setDiagramSlot,
}: {
  setDiagramSlot: (el: HTMLDivElement | null) => void;
}): JSX.Element {
  // ref callback を inline で書くと毎 render で identity が変わり、その都度
  // ref(null) → ref(newEl) が発火する。``useRef`` で stable な ref callback を
  // 作るのではなく、stable な setter (= state setter) を使うのが本パターンの
  // 正規。本コンポーネントは setDiagramSlot をそのまま callback ref に渡す
  // (= App.tsx 側で useCallback or useState で安定化済の前提)。
  return (
    <div
      ref={setDiagramSlot}
      className="h-full w-full"
      data-testid="workspace-pane-diagram-slot"
    />
  );
}

function ScopesStack({
  entries,
  blockTypeById,
  splitOutAnyScope,
  hasScopeBlocks,
  onSplitOutScope,
}: {
  entries: Array<[string, ScopeBuffer]>;
  blockTypeById: Map<string, string>;
  splitOutAnyScope: boolean;
  hasScopeBlocks: boolean;
  /** v0.27.2 UX-4 → v0.30.2: タブ切替化のため未使用、interface は維持。 */
  onSplitOutScope: (scopeId: string) => void;
}): JSX.Element {
  const { t } = useTranslation();
  // v0.30.2: タブ切替で 1 個ずつ表示 (= Simulink Scope 風)。
  // 現 active scope_id は local state、entries の最初を default。
  const [activeId, setActiveId] = useState<string | null>(null);
  // entries 変化で active が消えたら自動切替
  const validActiveId =
    activeId !== null && entries.some(([id]) => id === activeId)
      ? activeId
      : (entries[0]?.[0] ?? null);
  // 未使用 prop warning suppression (= interface 維持のため)
  void onSplitOutScope;
  if (entries.length === 0) {
    // v0.27.1 UX-1: 空 stack の理由を出し分ける:
    // - 個別 pane に分離済 (= splitOutAnyScope=true) → "all separated"
    // - それ以外 (= sim 未実行 or Scope ブロック無し) → "no data, run sim"
    // 後者の 2 ケースは現状同じ文言なので 1 つに統合 (= v0.30.0 code-reviewer
    // §NITS #4 で dead 三項演算子を解消)。
    // 将来 Scope ブロック無しの状態を別文言にする場合は別 i18n キー化する。
    void hasScopeBlocks; // 将来分岐用に keep
    const message = splitOutAnyScope
      ? t("workspace.scopes_stack.empty")
      : t("workspace.scopes_stack.no_data");
    return (
      <div className="flex h-full items-center justify-center bg-white p-3 text-center text-[11px] text-slate-400">
        {message}
      </div>
    );
  }
  // v0.30.2: タブ切替で 1 Scope を表示 (Simulink Scope 風)。
  const activeEntry =
    entries.find(([id]) => id === validActiveId) ?? entries[0]!;
  const [activeScopeId, activeBuffer] = activeEntry;
  const activeBlockType = blockTypeById.get(activeScopeId) ?? "";
  const isXY = activeBlockType.endsWith(".XYGraph");
  return (
    <div className="flex h-full flex-col overflow-hidden bg-white">
      {/* タブヘッダー: 各 Scope の scope_id ボタンを横並べ。
          幅が足りない場合は overflow-x-auto で横スクロール。 */}
      <div
        role="tablist"
        aria-label={t("workspace.scopes_stack.tablist")}
        className="flex h-6 shrink-0 items-center gap-0 overflow-x-auto border-b border-slate-200 bg-slate-50"
      >
        {entries.map(([scopeId]) => {
          const isActive = scopeId === validActiveId;
          return (
            <button
              key={scopeId}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => setActiveId(scopeId)}
              className={`shrink-0 border-r border-slate-200 px-2 py-0.5 font-mono text-[10px] ${
                isActive
                  ? "bg-white text-slate-800"
                  : "text-slate-500 hover:bg-slate-100 hover:text-slate-800"
              }`}
              title={scopeId}
            >
              {scopeId}
            </button>
          );
        })}
      </div>
      {/* active scope の uPlot 描画 */}
      <div className="min-h-0 flex-1 overflow-hidden p-1">
        {isXY ? (
          <XYGraphView scopeId={activeScopeId} buffer={activeBuffer} />
        ) : (
          <ScopeView scopeId={activeScopeId} buffer={activeBuffer} />
        )}
      </div>
    </div>
  );
}

function ScopeLeafBody({
  scopeId,
  buffer,
  blockType,
}: {
  scopeId: string;
  buffer: ScopeBuffer | undefined;
  blockType: string;
}): JSX.Element {
  if (buffer === undefined) {
    return (
      <div className="flex h-full items-center justify-center bg-white p-2 text-[11px] text-slate-400" />
    );
  }
  if (blockType.endsWith(".XYGraph")) {
    return (
      <div className="h-full overflow-hidden p-2">
        <XYGraphView scopeId={scopeId} buffer={buffer} />
      </div>
    );
  }
  return (
    <div className="h-full overflow-hidden p-2">
      <ScopeView scopeId={scopeId} buffer={buffer} />
    </div>
  );
}

