// 線図ビュー (ADR-0012 §(3))。
// Phase 2 は読み取り専用 (Phase 3 でドラッグ&ドロップ編集を追加)。
// Phase 3 で ``useReactFlow()`` 等のフックを外部コンポーネントから使う場合は、
// ``<ReactFlowProvider>`` を ``App`` 側に昇格させる必要がある (現状は ``ReactFlow``
// が内部で provider を持つため省略している)。

import { useQuery } from "@tanstack/react-query";
import { Background, Controls, MiniMap, ReactFlow } from "@xyflow/react";
// React Flow 独自スタイル。Tailwind preflight 後に評価されるよう、index.css の
// `@tailwind` 群より後で import する (DiagramCanvas.tsx に置くことで保証)。
import "@xyflow/react/dist/style.css";

import { getModel } from "../api/client";
import { modelToDiagram } from "../lib/diagramConverter";
import { useAppStore } from "../store/appStore";

interface DiagramCanvasProps {
  modelId: string;
}

export function DiagramCanvas({ modelId }: DiagramCanvasProps): JSX.Element {
  const { data, isLoading, error } = useQuery({
    queryKey: ["model", modelId],
    queryFn: () => getModel(modelId),
  });

  const selectedNodeId = useAppStore((s) => s.selectedNodeId);
  const selectNode = useAppStore((s) => s.selectNode);

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
  if (!data) {
    return <div className="p-4 text-sm text-gray-500">No model</div>;
  }
  const { nodes, edges } = modelToDiagram(data);
  // 選択状態を React Flow node の selected フィールドに反映 (UI ハイライト用)
  const decoratedNodes = nodes.map((n) => ({
    ...n,
    selected: n.id === selectedNodeId,
  }));
  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={decoratedNodes}
        edges={edges}
        fitView
        nodesDraggable={false}
        onNodeClick={(_event, node) => selectNode(node.id)}
        onPaneClick={() => selectNode(null)}
      >
        <Background />
        <MiniMap pannable zoomable />
        <Controls />
      </ReactFlow>
    </div>
  );
}
