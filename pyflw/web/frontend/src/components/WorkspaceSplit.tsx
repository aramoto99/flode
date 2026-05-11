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

import { useMemo } from "react";
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
  findLeaf,
  getLeafPaneIds,
  makeSplitId,
  type SplitNode,
  type SplitTree,
} from "../lib/splitTree";
import { PaneTitleBar } from "./PaneTitleBar";
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
}

export function WorkspaceSplit({
  setDiagramSlot,
  visibleScopeEntries,
  blockTypeById,
}: WorkspaceSplitProps): JSX.Element {
  const layout = useAppStore((s) => s.workspaceLayout);
  const splitPane = useAppStore((s) => s.splitPane);
  const unsplitPane = useAppStore((s) => s.unsplitPane);
  const setRatio = useAppStore((s) => s.setWorkspaceSplitRatio);

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
  ) => void;
  unsplitPane: (paneId: string) => void;
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

  const onSplitRight =
    nextNewLeaf !== null
      ? () => ctx.splitPane(paneId, "horizontal", nextNewLeaf)
      : null;
  const onSplitDown =
    nextNewLeaf !== null
      ? () => ctx.splitPane(paneId, "vertical", nextNewLeaf)
      : null;

  // unsplit:
  // - Diagram: 必ず存在すべき pane なので不許可
  // - 残葉数が 1 のときは不許可 (= unsplit すると tree 全消滅)
  const onUnsplit =
    !isDiagram && ctx.leafCount > 1
      ? () => ctx.unsplitPane(paneId)
      : null;

  // 本体描画
  let body: JSX.Element;
  let titleKey: PaneTitleKey;
  if (isDiagram) {
    body = <DiagramSlot setDiagramSlot={ctx.setDiagramSlot} />;
    titleKey = "workspace.pane.title.diagram";
  } else if (isStack) {
    body = (
      <ScopesStack
        entries={ctx.stackEntries}
        blockTypeById={ctx.blockTypeById}
      />
    );
    titleKey = "workspace.pane.title.scopes_stack";
  } else {
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
    titleKey = ""; // scope leaf はタイトル = scope_id を直接表示
  }

  return (
    <PaneLeafShell
      titleKey={titleKey}
      titleRaw={isDiagram || isStack ? null : paneId.slice("scope:".length)}
      onSplitRight={onSplitRight}
      onSplitDown={onSplitDown}
      onUnsplit={onUnsplit}
    >
      {body}
    </PaneLeafShell>
  );
}

type PaneTitleKey =
  | "workspace.pane.title.diagram"
  | "workspace.pane.title.scopes_stack"
  | "";

function PaneLeafShell({
  titleKey,
  titleRaw,
  onSplitRight,
  onSplitDown,
  onUnsplit,
  children,
}: {
  /** i18n キー (= 翻訳して title に使う)。``""`` ならスキップ。
   * Stage 1 では diagram / scopes_stack の 2 値のみ。 */
  titleKey: PaneTitleKey;
  /** raw 表示用 (= scope_id 等、翻訳しない)。``null`` なら titleKey 経由。 */
  titleRaw: string | null;
  onSplitRight: (() => void) | null;
  onSplitDown: (() => void) | null;
  onUnsplit: (() => void) | null;
  children: React.ReactNode;
}): JSX.Element {
  const { t } = useTranslation();
  // titleKey が limited union なので t() の strict-typed signature を満たす
  const title =
    titleRaw ??
    (titleKey === "workspace.pane.title.diagram"
      ? t("workspace.pane.title.diagram")
      : titleKey === "workspace.pane.title.scopes_stack"
        ? t("workspace.pane.title.scopes_stack")
        : "");
  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-white">
      <PaneTitleBar
        title={title}
        onSplitRight={onSplitRight}
        onSplitDown={onSplitDown}
        onUnsplit={onUnsplit}
      />
      <div className="min-h-0 flex-1 overflow-hidden">{children}</div>
    </div>
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
}: {
  entries: Array<[string, ScopeBuffer]>;
  blockTypeById: Map<string, string>;
}): JSX.Element {
  const { t } = useTranslation();
  if (entries.length === 0) {
    // stack 内のすべての Scope が個別 pane に分離されている / そもそも Scope が
    // 無い場合: ユーザーに状態を明示する notice を表示 (code-reviewer §SHOULD #5)。
    return (
      <div className="flex h-full items-center justify-center bg-white p-3 text-center text-[11px] text-slate-400">
        {t("workspace.scopes_stack.empty")}
      </div>
    );
  }
  return (
    <div className="flex h-full flex-col gap-2 overflow-y-auto bg-white p-2">
      {entries.map(([scopeId, buffer]) => {
        const blockType = blockTypeById.get(scopeId) ?? "";
        if (blockType.endsWith(".XYGraph")) {
          return (
            <XYGraphView key={scopeId} scopeId={scopeId} buffer={buffer} />
          );
        }
        return <ScopeView key={scopeId} scopeId={scopeId} buffer={buffer} />;
      })}
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

