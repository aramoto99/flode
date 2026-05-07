// 線図ビュー (ADR-0012 §(3)、ADR-0019 §(4) で編集機能を追加)。
// Phase 3: ドラッグ&ドロップでブロック追加 / ノード移動 / エッジ作成・削除 /
// 削除キーで対象削除 / port shape validation。

import { useQuery } from "@tanstack/react-query";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  SelectionMode,
  useReactFlow,
  type Connection,
  type EdgeChange,
  type NodeChange,
  type OnConnect,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useEffect, useMemo, useRef, useState } from "react";

import { getModel, listBlockMetadata } from "../api/client";
import { modelToDiagram, type BlockNode } from "../lib/diagramConverter";
import { generateUniqueId } from "../lib/idGenerator";
import { resolveBlocksAtPath } from "../lib/pathResolver";
import {
  indexRegistry,
  validatePortShapeConnection,
} from "../lib/portShapeValidate";
import { BlockNodeView } from "./BlockNodeView";
import {
  addBlockToEditing,
  addConnectionToEditing,
  removeBlockFromEditing,
  removeConnectionFromEditing,
  updateBlockPosition,
  useAppStore,
} from "../store/appStore";
import type { FlwModel } from "../types/api";

interface DiagramCanvasProps {
  modelId: string;
}

// React Flow に渡すカスタムノード type 表 (modelToDiagram で type: "blockNode" を返す)。
// 識別子の object 参照を毎回同じにすることで React Flow の警告を回避する
// (`useMemo` がコンポーネント外で使えないため module-level 定数で代用)。
const NODE_TYPES = { blockNode: BlockNodeView } as const;

// 中ボタン (button=1) と右ボタン (button=2) で pan、左クリック (button=0) は
// 「空エリアドラッグ → 矩形選択 / ノード上ドラッグ → ノード移動」(Simulink + 一般的な
// editor 慣習)。配列参照を毎 render で新しくしないために module-level 定数。
const PAN_BUTTONS = [1, 2];

export function DiagramCanvas({ modelId }: DiagramCanvasProps): JSX.Element {
  // サーバ最新モデルを fetch (= editingModel の初期値)
  const { data: serverModel, isLoading, error } = useQuery({
    queryKey: ["model", modelId],
    queryFn: () => getModel(modelId),
  });
  const { data: registry } = useQuery({
    queryKey: ["blocks-registry"],
    queryFn: listBlockMetadata,
    staleTime: 60 * 60 * 1000,
  });
  const registryMap = useMemo(
    () => indexRegistry(registry?.blocks ?? []),
    [registry],
  );

  const editingModel = useAppStore((s) => s.editingModel);
  const setEditingModel = useAppStore((s) => s.setEditingModel);
  const selectedNodeIds = useAppStore((s) => s.selectedNodeIds);
  const selectNode = useAppStore((s) => s.selectNode);
  const setSelectedNodeIds = useAppStore((s) => s.setSelectedNodeIds);
  const selectedEdgeIds = useAppStore((s) => s.selectedEdgeIds);
  const setSelectedEdgeIds = useAppStore((s) => s.setSelectedEdgeIds);
  const selectedModelId = useAppStore((s) => s.selectedModelId);
  const editingPath = useAppStore((s) => s.editingPath);
  const drilldownInto = useAppStore((s) => s.drilldownInto);

  const [toast, setToast] = useState<string | null>(null);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const reactFlow = useReactFlow();

  // Simulink 風: ノード上で右クリックドラッグ = そのノードをコピーしてカーソルに追従。
  // 空エリアで右クリックドラッグの場合は ``panOnDrag = [1, 2]`` 経由で React Flow が
  // pan を担当するので、ここではターゲットが ``.react-flow__node`` に閉じている時のみ
  // 介入する。OS のコンテキストメニュー抑制は ``onPaneContextMenu`` /
  // ``onNodeContextMenu`` ですでに preventDefault されている。
  useEffect(() => {
    const wrapper = reactFlowWrapper.current;
    if (!wrapper) return;
    let dragState: {
      newId: string;
      startClientX: number;
      startClientY: number;
      origX: number;
      origY: number;
    } | null = null;

    const onMouseDown = (e: MouseEvent): void => {
      if (e.button !== 2) return; // right click のみ
      const target = e.target as HTMLElement | null;
      const nodeEl = target?.closest(".react-flow__node") as HTMLElement | null;
      if (!nodeEl) return;
      const origId = nodeEl.getAttribute("data-id");
      const state = useAppStore.getState();
      const model = state.editingModel;
      if (!origId || !model) return;
      const path = state.editingPath;
      let view;
      try {
        view = resolveBlocksAtPath(model, path);
      } catch {
        return;
      }
      const origBlock = view.blocks.find((b) => b.id === origId);
      if (!origBlock) return;
      const origPos = view.layout[origId] ?? { x: 0, y: 0 };

      // ID 衝突しない新 ID を採番 + パラメータをディープコピー (= 同じ参照だと
      // 後の編集が双方に反映されてしまう)
      const existingIds = new Set(view.blocks.map((b) => b.id));
      const newId = generateUniqueId(origBlock.type, existingIds);
      const clonedParams = JSON.parse(JSON.stringify(origBlock.params)) as Record<
        string,
        unknown
      >;
      addBlockToEditing(
        { id: newId, type: origBlock.type, params: clonedParams },
        origPos,
      );

      // React Flow / OS のデフォルト挙動 (pan / context menu) を抑制
      e.preventDefault();
      e.stopPropagation();

      // ドラッグ中はノードの CSS transition を切って、マウスにピッタリ追従させる
      // (= ヌルッと遅れて見える symptom の抑制)。body 全体に class を付ける。
      document.body.classList.add("pyflw-copying");

      dragState = {
        newId,
        startClientX: e.clientX,
        startClientY: e.clientY,
        origX: origPos.x,
        origY: origPos.y,
      };
    };

    const onMouseMove = (e: MouseEvent): void => {
      if (!dragState) return;
      const zoom = reactFlow.getZoom() || 1;
      const dx = (e.clientX - dragState.startClientX) / zoom;
      const dy = (e.clientY - dragState.startClientY) / zoom;
      updateBlockPosition(dragState.newId, {
        x: dragState.origX + dx,
        y: dragState.origY + dy,
      });
    };

    const onMouseUp = (): void => {
      if (!dragState) return;
      // 複製を選択状態にして、そのまま左クリックで微調整できるようにする
      const newId = dragState.newId;
      dragState = null;
      document.body.classList.remove("pyflw-copying");
      useAppStore.getState().selectNode(newId);
    };

    // contextmenu (= 右クリック) の OS メニュー抑制 (mousedown だけでは漏れることがある)
    const onContextMenu = (e: MouseEvent): void => {
      const target = e.target as HTMLElement | null;
      if (target?.closest(".react-flow__node")) {
        e.preventDefault();
      }
    };

    wrapper.addEventListener("mousedown", onMouseDown, true);
    wrapper.addEventListener("contextmenu", onContextMenu);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      wrapper.removeEventListener("mousedown", onMouseDown, true);
      wrapper.removeEventListener("contextmenu", onContextMenu);
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      // unmount 中にドラッグが続いていた場合の保険
      document.body.classList.remove("pyflw-copying");
    };
  }, [reactFlow]);

  // モデル切替 / 初期 fetch 完了で editingModel を初期化
  useEffect(() => {
    if (serverModel && selectedModelId === modelId) {
      // 既に同 model を編集中ならサーバ更新を上書きしない (auto-save 中の race
      // 対策: PUT 直後に再 fetch されると編集が消える)
      const current = useAppStore.getState().editingModel;
      if (!current || useAppStore.getState().selectedModelId !== modelId) {
        setEditingModel(serverModel);
        useAppStore.getState().setDirty(false);
      }
    }
  }, [serverModel, modelId, selectedModelId, setEditingModel]);

  const showToast = (msg: string): void => {
    setToast(msg);
    setTimeout(() => setToast(null), 3000);
  };

  if (isLoading) {
    return <div className="p-4 text-sm text-gray-500">Loading model...</div>;
  }
  if (error) {
    return (
      <div className="p-4 text-sm text-red-600">
        Failed to load model: {(error as Error).message}
      </div>
    );
  }
  const model = editingModel ?? serverModel;
  if (!model) {
    return <div className="p-4 text-sm text-gray-500">No model</div>;
  }
  // ADR-0021 §(2): editingPath を辿って現スコープの blocks/connections/layout を取得
  let pathView;
  try {
    pathView = resolveBlocksAtPath(model, editingPath);
  } catch (e) {
    return (
      <div className="p-4 text-sm text-red-600">
        Path resolution failed: {(e as Error).message}
      </div>
    );
  }
  const scopeModel: FlwModel = {
    ...model,
    blocks: pathView.blocks,
    connections: pathView.connections,
    layout: pathView.layout,
  };
  const { nodes: baseNodes, edges } = modelToDiagram(scopeModel, registryMap);
  const selectedSet = new Set(selectedNodeIds);
  const decoratedNodes = baseNodes.map((n) => ({
    ...n,
    selected: selectedSet.has(n.id),
  }));

  // ---------- ハンドラ ----------

  const onNodesChange = (changes: NodeChange[]): void => {
    // 選択変更はバッチで反映 (= 1 ドラッグ中の rubber-band で多数の select イベントが
    // 来るので、最後の状態をまとめて store に書く)。
    let nextSelected: string[] | null = null;
    const flushSelection = (): void => {
      if (nextSelected !== null) {
        setSelectedNodeIds(nextSelected);
      }
    };
    const ensureSelectedDraft = (): string[] => {
      if (nextSelected === null) nextSelected = [...selectedNodeIds];
      return nextSelected;
    };

    for (const ch of changes) {
      // React Flow controlled mode (= nodes prop 駆動) では、ドラッグ中の position も
      // props に書き戻さないと、parent の他の理由で起きた再 render で props の元位置に
      // スナップバックされ、カーソルから逃げて見える。``ch.dragging`` の真偽を問わず
      // position 変更は即 store に反映する (auto-save は 500ms debounce で 1 回に
      // まとめられるのでサーバ負荷は変わらない)。
      if (ch.type === "position" && ch.position) {
        updateBlockPosition(ch.id, { x: ch.position.x, y: ch.position.y });
      } else if (ch.type === "remove") {
        removeBlockFromEditing(ch.id);
      } else if (ch.type === "select") {
        const draft = ensureSelectedDraft();
        if (ch.selected) {
          if (!draft.includes(ch.id)) draft.push(ch.id);
        } else {
          const idx = draft.indexOf(ch.id);
          if (idx >= 0) draft.splice(idx, 1);
        }
      }
    }
    flushSelection();
  };

  const onEdgesChange = (changes: EdgeChange[]): void => {
    // ノード側と同様、エッジの select 変更もバッチで store に反映する (rubber-band で
    // 多数のイベントが瞬時に飛んでくるため、最後の状態をまとめて書き込む)。
    let nextSelected: string[] | null = null;
    const ensureDraft = (): string[] => {
      if (nextSelected === null) nextSelected = [...selectedEdgeIds];
      return nextSelected;
    };
    for (const ch of changes) {
      if (ch.type === "remove") {
        // edge id "e{idx}-{src}-{dst}" 形式から復元するのは脆い。
        // 代わりに React Flow の現エッジを参照して src/dst/handle を取り出す。
        const edge = edges.find((e) => e.id === ch.id);
        if (edge) {
          removeConnectionFromEditing(
            edge.source,
            Number(edge.sourceHandle ?? 0),
            edge.target,
            Number(edge.targetHandle ?? 0),
          );
        }
      } else if (ch.type === "select") {
        const draft = ensureDraft();
        if (ch.selected) {
          if (!draft.includes(ch.id)) draft.push(ch.id);
        } else {
          const idx = draft.indexOf(ch.id);
          if (idx >= 0) draft.splice(idx, 1);
        }
      }
    }
    if (nextSelected !== null) setSelectedEdgeIds(nextSelected);
  };

  const onConnect: OnConnect = (connection: Connection): void => {
    if (!editingModel) return;
    const srcBlock = pathView.blocks.find((b) => b.id === connection.source);
    const dstBlock = pathView.blocks.find((b) => b.id === connection.target);
    if (!srcBlock || !dstBlock) {
      showToast("Connection refused: source or target block not found.");
      return;
    }
    const srcIdx = Number(connection.sourceHandle ?? 0);
    const dstIdx = Number(connection.targetHandle ?? 0);
    const check = validatePortShapeConnection(
      srcBlock,
      srcIdx,
      dstBlock,
      dstIdx,
      registryMap,
    );
    if (!check.ok) {
      showToast(check.reason ?? "Port shape mismatch.");
      return;
    }
    addConnectionToEditing({
      src: srcBlock.id,
      src_idx: srcIdx,
      dst: dstBlock.id,
      dst_idx: dstIdx,
    });
  };

  const onDragOver = (event: React.DragEvent): void => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  };

  const onDrop = (event: React.DragEvent): void => {
    event.preventDefault();
    if (!editingModel) return;
    const typePath = event.dataTransfer.getData("application/pyflw-block-type");
    if (!typePath) return;
    const defaultParamsRaw = event.dataTransfer.getData(
      "application/pyflw-default-params",
    );
    let defaultParams: Record<string, unknown> = {};
    try {
      defaultParams = JSON.parse(defaultParamsRaw || "{}");
    } catch {
      defaultParams = {};
    }
    const position = reactFlow.screenToFlowPosition({
      x: event.clientX,
      y: event.clientY,
    });
    // ADR-0021 §(4): 現在 path の scope 内の id だけと衝突しないようにする
    const existingIds = new Set(pathView.blocks.map((b) => b.id));
    const newId = generateUniqueId(typePath, existingIds);
    addBlockToEditing(
      { id: newId, type: typePath, params: defaultParams },
      position,
    );
  };

  // ADR-0021 §(4): is_container=true なノード (= Subsystem サブクラス) を
  // ダブルクリックでドリルダウンする。registry の `is_container` を参照。
  const onNodeDoubleClick = (
    _event: React.MouseEvent,
    node: BlockNode,
  ): void => {
    const meta = registryMap.get(node.data.blockType);
    if (meta?.is_container) {
      drilldownInto(node.id);
    }
  };

  return (
    // ADR-0019 §(4.1): React Flow v12 では ``onDragOver`` / ``onDrop`` を
    // ``<ReactFlow>`` の props ではなく **wrapper div** に付けるのが公式推奨パターン。
    // wrapper に貼ることでイベントが内部 pane の pointer-event 処理に消費されずに
    // 確実に届く (= Palette からの drop が無視される問題を防ぐ)。
    <div
      className="relative h-full w-full"
      ref={reactFlowWrapper}
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      <ReactFlow
        nodes={decoratedNodes}
        edges={edges.map((e) => ({
          ...e,
          type: "smoothstep",
          animated: false,
          // controlled mode では ``selected`` を prop に流し込まないと .selected
          // クラスが付かず、CSS のハイライトが効かない (= ユーザーから選択不可に見える)。
          selected: selectedEdgeIds.includes(e.id),
          // 注意: ここでインライン ``style`` を当てると CSS の
          // ``.react-flow__edge.selected`` / ``:hover`` ルールが specificity 負けする
          // ので入れない。色 / 太さは index.css で集中管理。
        }))}
        nodeTypes={NODE_TYPES}
        fitView
        nodesDraggable
        defaultEdgeOptions={{ type: "smoothstep" }}
        proOptions={{ hideAttribution: true }}
        // 左クリックドラッグ = 空エリアで矩形選択 / ノード上でそのノード移動
        // (Simulink + 一般的な editor 慣習)。``panOnDrag = [1, 2]`` で中 / 右ボタン
        // ドラッグだけ pan に。OS の右クリックメニューは onPaneContextMenu / onNodeContextMenu
        // で preventDefault する。
        panOnDrag={PAN_BUTTONS}
        selectionOnDrag
        selectionMode={SelectionMode.Partial}
        multiSelectionKeyCode={["Shift", "Meta", "Control"]}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={(_event, node: BlockNode) => selectNode(node.id)}
        onNodeDoubleClick={onNodeDoubleClick}
        // Simulink 流: Shift を押しながらノードドラッグを始めると、対象 (= 選択中の)
        // ノードに繋がっているエッジをすべて切り離す。これによりブロックを「リンク
        // から外して動かす」操作が 1 ストロークで完結する。
        onNodeDragStart={(event, node) => {
          if (!event.shiftKey || !editingModel) return;
          const ids = new Set(
            useAppStore.getState().selectedNodeIds.length > 0
              ? useAppStore.getState().selectedNodeIds
              : [node.id],
          );
          for (const c of pathView.connections) {
            if (ids.has(c.src) || ids.has(c.dst)) {
              removeConnectionFromEditing(c.src, c.src_idx, c.dst, c.dst_idx);
            }
          }
        }}
        onPaneClick={() => selectNode(null)}
        onPaneContextMenu={(e) => e.preventDefault()}
        onNodeContextMenu={(e) => e.preventDefault()}
        deleteKeyCode={["Backspace", "Delete"]}
      >
        <Background gap={18} size={1} color="#cbd5e1" />
        <MiniMap
          pannable
          zoomable
          className="!bg-white !shadow-md"
          maskColor="rgb(241 245 249 / 0.7)"
          nodeColor={(n) => (n.data?.color as string) ?? "#94a3b8"}
        />
        <Controls className="!shadow-md" />
      </ReactFlow>
      {toast && (
        <div
          className="absolute bottom-5 left-1/2 z-10 flex -translate-x-1/2 items-center gap-2 rounded-md bg-rose-600 px-3.5 py-2 text-xs font-medium text-white shadow-lg ring-1 ring-rose-400"
          role="alert"
        >
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          {toast}
        </div>
      )}
    </div>
  );
}
