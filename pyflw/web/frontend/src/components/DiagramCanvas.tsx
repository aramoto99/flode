// 線図ビュー (ADR-0012 §(3)、ADR-0019 §(4) で編集機能を追加)。
// Phase 3: ドラッグ&ドロップでブロック追加 / ノード移動 / エッジ作成・削除 /
// 削除キーで対象削除 / port shape validation。

import { useQuery } from "@tanstack/react-query";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
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
import {
  indexRegistry,
  validatePortShapeConnection,
} from "../lib/portShapeValidate";
import {
  addBlockToEditing,
  addConnectionToEditing,
  removeBlockFromEditing,
  removeConnectionFromEditing,
  updateBlockPosition,
  useAppStore,
} from "../store/appStore";

interface DiagramCanvasProps {
  modelId: string;
}

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
  const selectedNodeId = useAppStore((s) => s.selectedNodeId);
  const selectNode = useAppStore((s) => s.selectNode);
  const selectedModelId = useAppStore((s) => s.selectedModelId);

  const [toast, setToast] = useState<string | null>(null);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const reactFlow = useReactFlow();

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
  const { nodes: baseNodes, edges } = modelToDiagram(model);
  const decoratedNodes = baseNodes.map((n) => ({
    ...n,
    selected: n.id === selectedNodeId,
  }));

  // ---------- ハンドラ ----------

  const onNodesChange = (changes: NodeChange[]): void => {
    for (const ch of changes) {
      if (ch.type === "position" && ch.position && !ch.dragging) {
        // ドラッグ終了時 (`dragging === false`) に layout を更新
        updateBlockPosition(ch.id, { x: ch.position.x, y: ch.position.y });
      } else if (ch.type === "remove") {
        removeBlockFromEditing(ch.id);
      }
    }
  };

  const onEdgesChange = (changes: EdgeChange[]): void => {
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
      }
    }
  };

  const onConnect: OnConnect = (connection: Connection): void => {
    if (!editingModel) return;
    const srcBlock = editingModel.blocks.find((b) => b.id === connection.source);
    const dstBlock = editingModel.blocks.find((b) => b.id === connection.target);
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
    const existingIds = new Set(editingModel.blocks.map((b) => b.id));
    const newId = generateUniqueId(typePath, existingIds);
    addBlockToEditing(
      { id: newId, type: typePath, params: defaultParams },
      position,
    );
  };

  return (
    <div className="relative h-full w-full" ref={reactFlowWrapper}>
      <ReactFlow
        nodes={decoratedNodes}
        edges={edges}
        fitView
        nodesDraggable
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={(_event, node: BlockNode) => selectNode(node.id)}
        onPaneClick={() => selectNode(null)}
        onDragOver={onDragOver}
        onDrop={onDrop}
        deleteKeyCode={["Backspace", "Delete"]}
      >
        <Background />
        <MiniMap pannable zoomable />
        <Controls />
      </ReactFlow>
      {toast && (
        <div
          className="absolute bottom-4 left-1/2 z-10 -translate-x-1/2 rounded bg-red-600 px-4 py-2 text-sm text-white shadow-lg"
          role="alert"
        >
          {toast}
        </div>
      )}
    </div>
  );
}
