// 線図ビュー (ADR-0012 §(3)、ADR-0019 §(4) で編集機能を追加)。
// Phase 3: ドラッグ&ドロップでブロック追加 / ノード移動 / エッジ作成・削除 /
// 削除キーで対象削除 / port shape validation。

import { useQuery } from "@tanstack/react-query";
import {
  Background,
  Controls,
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
import { useTranslation } from "react-i18next";

import { getLibraryEntry, getModel, listBlockMetadata } from "../api/client";
import { pushToast } from "../store/toastStore";
import {
  modelToDiagram,
  SIMULINK_EDGE_STYLE,
  SIMULINK_EDGE_TYPE,
  SIMULINK_MARKER_END,
  type BlockNode,
} from "../lib/diagramConverter";
import { generateUniqueId } from "../lib/idGenerator";
import { resolveBlocksAtPath } from "../lib/pathResolver";
import {
  indexRegistry,
  validatePortShapeConnection,
} from "../lib/portShapeValidate";
import { BlockNodeView } from "./BlockNodeView";
import {
  BranchableEdge,
  type BranchStartParams,
  setBranchStartHandler,
} from "./BranchableEdge";
import { QuickAdd } from "./QuickAdd";
import {
  addBlockToEditing,
  addConnectionToEditing,
  removeBlockFromEditing,
  removeConnectionFromEditing,
  updateBlockPosition,
  updateBlockPositions,
  useAppStore,
} from "../store/appStore";
import type { FlwModel } from "../types/api";

interface DiagramCanvasProps {
  /** legacy ``selectedModelId`` 経路の model id。``selectedFilePath`` (= File API
   *  経路、ADR-0041 §論点 8-A) では null を渡し、内部で legacy query を skip。
   *  editingModel は FileBrowser onClick が事前にセット済前提。 */
  modelId: string | null;
}

// React Flow に渡すカスタムノード type 表 (modelToDiagram で type: "blockNode" を返す)。
// 識別子の object 参照を毎回同じにすることで React Flow の警告を回避する
// (`useMemo` がコンポーネント外で使えないため module-level 定数で代用)。
const NODE_TYPES = { blockNode: BlockNodeView } as const;

// v0.20.6: edge type "branchable" は BranchableEdge を使う。Simulink の「既存
// 配線から分岐」drag を edge mousedown で発火できるようにする。
const EDGE_TYPES = { branchable: BranchableEdge } as const;

// 中ボタン (button=1) と右ボタン (button=2) で pan、左クリック (button=0) は
// 「空エリアドラッグ → 矩形選択 / ノード上ドラッグ → ノード移動」(Simulink + 一般的な
// editor 慣習)。配列参照を毎 render で新しくしないために module-level 定数。
const PAN_BUTTONS = [1, 2];

export function DiagramCanvas({ modelId }: DiagramCanvasProps): JSX.Element {
  const { t } = useTranslation();
  // サーバ最新モデルを fetch (= editingModel の初期値)。
  // ``modelId == null`` (= File API モード) では legacy query を skip。FileBrowser
  // onClick が editingModel を直接セット済 (ADR-0041 §論点 8-A)。
  const { data: serverModel, isLoading, error } = useQuery({
    queryKey: ["model", modelId ?? "__none__"],
    queryFn: () => getModel(modelId!),
    enabled: modelId !== null,
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

  // Simulink 互換 (v2.1.x ユーザー指摘): ``Ctrl + 左クリック`` 2-step auto-connect の
  // 1 回目クリック時の source を保持。2 回目の別ノード Ctrl+click で edge を作成、
  // null にリセット。
  //
  // v0.20.5: edge を起点にする「分岐配線」をサポート。``string`` の場合は従来通り
  // ノード ID + src_idx=0、``{src, src_idx}`` オブジェクトの場合は既存 edge を
  // Ctrl+クリックして得た source 情報 (= 既存配線から枝分かれ、Display 等
  // シンク系ブロックへの典型的接続パターン)。
  type AutoConnectSrc = string | { src: string; src_idx: number };
  const [autoConnectSource, setAutoConnectSource] =
    useState<AutoConnectSrc | null>(null);

  // v0.20.6: Simulink 互換 「既存配線 mousedown → drag → ブロック drop で分岐
  // 配線」を実装する state。``BranchableEdge`` の overlay path で pointerdown
  // が発火すると ``setBranchDrag`` が呼ばれ、以降 window mousemove で current
  // 位置を追跡、mouseup で hit testing して接続成立 or cancel。
  interface BranchDragState {
    src: string;
    src_idx: number;
    /** mousedown 時の screen 座標 (= 線の始点) */
    startScreenX: number;
    startScreenY: number;
    /** 現在のカーソル screen 座標 (= 線の終点、drag に追従) */
    currentScreenX: number;
    currentScreenY: number;
  }
  const [branchDrag, setBranchDrag] = useState<BranchDragState | null>(null);
  const [quickAdd, setQuickAdd] = useState<{
    screenX: number;
    screenY: number;
    flowX: number;
    flowY: number;
  } | null>(null);
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
      // Simulink 仕様 (= ユーザー指摘):
      // - ``Ctrl + 右クリックドラッグ``: ノード複製
      // - 単純な右クリック (Ctrl なし) ドラッグ: 同様にノード複製 (= alternative
      //   shortcut、Simulink でも両方使える)
      // - ``Ctrl + 左クリック`` (= ドラッグでなく単発クリック): 2 ノード間の
      //   auto-connect (= 別経路 ``onCanvasClick`` 等で処理、本ハンドラの対象外)
      const isRightDrag = e.button === 2;
      if (!isRightDrag) return;
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

  // モデル切替 / 初期 fetch 完了で editingModel を初期化 (legacy 経路のみ)
  useEffect(() => {
    if (modelId !== null && serverModel && selectedModelId === modelId) {
      // 既に同 model を編集中ならサーバ更新を上書きしない (auto-save 中の race
      // 対策: PUT 直後に再 fetch されると編集が消える)
      const current = useAppStore.getState().editingModel;
      if (!current || useAppStore.getState().selectedModelId !== modelId) {
        setEditingModel(serverModel);
        useAppStore.getState().setDirty(false);
      }
    }
  }, [serverModel, modelId, selectedModelId, setEditingModel]);

  // ADR-0030: 旧ローカル toast (`useState<string|null>` + `setTimeout`) はグローバル
  // `<ToastContainer>` (App ルート mount) に置き換え済み。port 形状エラー / connect 失敗 /
  // library drop 失敗はユーザー操作で訂正可能なので severity=warning で 5 秒表示。
  const showToast = (msg: string): void => {
    pushToast({ severity: "warning", message: msg });
  };

  // v0.20.6: BranchableEdge の onPointerDown 通知を購読 + window レベルで
  // mousemove / mouseup / Esc を捕捉して分岐配線を成立させる。
  useEffect(() => {
    const handleStart = (params: BranchStartParams): void => {
      setBranchDrag({
        src: params.src,
        src_idx: params.src_idx,
        startScreenX: params.startScreenX,
        startScreenY: params.startScreenY,
        currentScreenX: params.startScreenX,
        currentScreenY: params.startScreenY,
      });
    };
    setBranchStartHandler(handleStart);
    return () => setBranchStartHandler(null);
  }, []);

  useEffect(() => {
    if (!branchDrag) return;

    const handleMove = (e: PointerEvent): void => {
      setBranchDrag((prev) =>
        prev === null
          ? null
          : { ...prev, currentScreenX: e.clientX, currentScreenY: e.clientY },
      );
    };

    const handleUp = (e: PointerEvent): void => {
      // hit testing: ドロップ位置の DOM から最も近い `data-id` (= ノード ID)
      // を持つ React Flow node 要素を辿る。input port[0] (= dst_idx=0) に接続
      // するセマンティクスは Ctrl+ 接続と同じ (= ADR-0041 §論点 5-A 範囲外、
      // pyflw GUI 既定挙動)。
      const dropElem = document.elementFromPoint(e.clientX, e.clientY);
      let cursor: HTMLElement | null = dropElem as HTMLElement | null;
      let dropNodeId: string | null = null;
      while (cursor !== null) {
        const id = cursor.getAttribute?.("data-id");
        if (id !== null && id !== undefined && cursor.classList?.contains("react-flow__node")) {
          dropNodeId = id;
          break;
        }
        cursor = cursor.parentElement;
      }

      if (dropNodeId !== null && dropNodeId !== branchDrag.src) {
        addConnectionToEditing({
          src: branchDrag.src,
          src_idx: branchDrag.src_idx,
          dst: dropNodeId,
          dst_idx: 0,
        });
      }
      setBranchDrag(null);
    };

    const handleKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") {
        setBranchDrag(null);
      }
    };

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
    window.addEventListener("keydown", handleKey);
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
      window.removeEventListener("keydown", handleKey);
    };
  }, [branchDrag]);

  // legacy mode の loading / error 判定 (modelId が null の File API mode では skip)
  if (modelId !== null) {
    if (isLoading) {
      return <div className="p-4 text-sm text-gray-500">{t("diagram.loading")}</div>;
    }
    if (error) {
      return (
        <div className="p-4 text-sm text-red-600">
          {t("diagram.load_failed", { message: (error as Error).message })}
        </div>
      );
    }
  }
  const model = editingModel ?? serverModel ?? null;
  if (!model) {
    return <div className="p-4 text-sm text-gray-500">{t("diagram.no_model")}</div>;
  }
  // ADR-0021 §(2): editingPath を辿って現スコープの blocks/connections/layout を取得
  let pathView;
  try {
    pathView = resolveBlocksAtPath(model, editingPath);
  } catch (e) {
    return (
      <div className="p-4 text-sm text-red-600">
        {t("diagram.path_failed", { message: (e as Error).message })}
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
    // 選択変更 + position 変更ともに **バッチで 1 回の store 書き込み** に集約する。
    // 個別 set だと複数選択ドラッグ中に「一部 node は新座標 / 一部は旧座標」の中間
    // re-render が発生し、その間に再計算された edge path が古い座標で描画されて
    // ブロックとエッジの追従が連動しないように見える (v0.16.0 ユーザー指摘)。
    let nextSelected: string[] | null = null;
    const positionUpdates: { id: string; x: number; y: number }[] = [];
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
      if (ch.type === "position" && ch.position) {
        // controlled mode では ``ch.dragging`` の真偽を問わず position を即 store に
        // 書き戻さないと、props の元位置にスナップバックする。auto-save の debounce
        // (500ms) でサーバ負荷は変わらない。複数 nodes の更新は positionUpdates に
        // 集約し、ループ後に 1 回の applyEditingModel で書き込む。
        positionUpdates.push({
          id: ch.id,
          x: ch.position.x,
          y: ch.position.y,
        });
      } else if (ch.type === "remove") {
        removeBlockFromEditing(ch.id);
        // 削除されたブロックが selection に残っていると ParameterPanel が
        // 「not found」状態になる → 同期して selection からも除く
        const state = useAppStore.getState();
        if (state.selectedNodeId === ch.id) state.selectNode(null);
        if (autoConnectSource === ch.id) setAutoConnectSource(null);
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
    if (positionUpdates.length > 0) updateBlockPositions(positionUpdates);
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
      showToast(t("diagram.connect_no_block"));
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
      showToast(check.reason ?? t("diagram.port_shape_mismatch"));
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
    // ADR-0029: Library entry の drop は別 MIME (`application/pyflw-library-entry-ref`)
    // で運ばれる。先にそちらを check してから通常 block drop に fallback する。
    const libraryRefRaw = event.dataTransfer.getData(
      "application/pyflw-library-entry-ref",
    );
    if (libraryRefRaw) {
      let ref: { library: string; entry: string } | null = null;
      try {
        ref = JSON.parse(libraryRefRaw);
      } catch {
        ref = null;
      }
      if (!ref || !ref.library || !ref.entry) {
        showToast(t("diagram.library_drop_invalid_ref"));
        return;
      }
      const position = reactFlow.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });
      // 非同期 fetch → 解決後に inline 展開 (= drop 瞬間に subsystem 定義をモデル
      // にコピー、ADR-0029 §PLACE-A)。fetch 中は何も配置しない (= drag 操作と認識的
      // 親和)。失敗時は toast。
      // SHOULD: 非同期完了時にユーザーが別モデルへ切り替えていたら drop は無視する
      // (= 古い座標で別モデルにブロックが追加されるのを防ぐ)。
      const dropModelId = modelId;
      void getLibraryEntry(ref.library, ref.entry)
        .then((detail) => {
          const state = useAppStore.getState();
          if (state.selectedModelId !== dropModelId) {
            // ユーザーが drop 中に別モデルに切り替えた → drop を破棄
            return;
          }
          const m = state.editingModel;
          if (!m) return;
          let existingIds: Set<string>;
          try {
            const view = resolveBlocksAtPath(m, state.editingPath);
            existingIds = new Set(view.blocks.map((b) => b.id));
          } catch {
            return;
          }
          const subType = detail.subsystem.type;
          const newId = generateUniqueId(subType, existingIds);
          // params は ``Subsystem.to_dict()`` の出力をそのまま使う (= byte-identical)。
          addBlockToEditing(
            { id: newId, type: subType, params: detail.subsystem.params },
            position,
          );
          useAppStore.getState().selectNode(newId);
        })
        .catch((err: Error) => {
          // ADR-0030 SHOULD: API / fetch 失敗はシステムエラー → severity=error
          // (port 形状エラー等のユーザー操作で訂正可能なものは warning)。
          pushToast({
            severity: "error",
            message: t("diagram.library_drop_failed", { message: err.message }),
          });
        });
      return;
    }
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

  // 空ペーン (どのノードにも乗っていない領域) をダブルクリックで Quick Insert を開く。
  // Simulink R2014b〜のクイック挿入と同等の操作。React Flow v12 には ``onPaneDoubleClick``
  // prop が無いので、wrapper の ``onDoubleClick`` で受けて、target が ``.react-flow__pane``
  // (= 空エリア) または背景 SVG の時だけ反応する。
  const onWrapperDoubleClick = (event: React.MouseEvent): void => {
    if (!editingModel) return;
    const target = event.target as HTMLElement | null;
    if (!target) return;
    // ノード / ハンドル / エッジ / コントロールの上では発火させない。
    if (
      target.closest(".react-flow__node") ||
      target.closest(".react-flow__handle") ||
      target.closest(".react-flow__edge") ||
      target.closest(".react-flow__controls") ||
      target.closest(".react-flow__minimap")
    ) {
      return;
    }
    const flow = reactFlow.screenToFlowPosition({
      x: event.clientX,
      y: event.clientY,
    });
    setQuickAdd({
      screenX: event.clientX,
      screenY: event.clientY,
      flowX: flow.x,
      flowY: flow.y,
    });
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
      onDoubleClick={onWrapperDoubleClick}
    >
      <ReactFlow
        nodes={decoratedNodes}
        edges={edges.map((e) => ({
          ...e,
          // diagramConverter で設定した type ("step") を尊重 (= Simulink 風 90°
          // 折れ線)。``smoothstep`` で上書きしていた v0.x 時代の挙動を撤廃。
          animated: false,
          // controlled mode では ``selected`` を prop に流し込まないと .selected
          // クラスが付かず、CSS のハイライトが効かない (= ユーザーから選択不可に見える)。
          selected: selectedEdgeIds.includes(e.id),
          // 注意: ここでインライン ``style`` を当てると CSS の
          // ``.react-flow__edge.selected`` / ``:hover`` ルールが specificity 負けする
          // ので入れない。色 / 太さは index.css で集中管理。
        }))}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        fitView
        nodesDraggable
        defaultEdgeOptions={{
          // Simulink 風: 90° 折れ線 (step) + 黒系細線 + 終点矢印 head。
          // v0.20.11: markerEnd 復活。BranchableEdge が target 座標を矢印
          // サイズ分外側に置く補正をするため、矢印 head が node 境界に綺麗に
          // 当たる位置に描画される (= 矢印先端が node 境界 + 8 px、base が
          // node 境界)。
          type: SIMULINK_EDGE_TYPE,
          style: SIMULINK_EDGE_STYLE,
          markerEnd: SIMULINK_MARKER_END,
        }}
        proOptions={{ hideAttribution: true }}
        // 左クリックドラッグ = 空エリアで矩形選択 / ノード上でそのノード移動
        // (Simulink + 一般的な editor 慣習)。``panOnDrag = [1, 2]`` で中 / 右ボタン
        // ドラッグだけ pan に。OS の右クリックメニューは onPaneContextMenu / onNodeContextMenu
        // で preventDefault する。
        panOnDrag={PAN_BUTTONS}
        selectionOnDrag
        selectionMode={SelectionMode.Partial}
        // Simulink 仕様: ``Shift`` で multi-select、``Ctrl/Meta`` は auto-connect
        // (= 2 ノード間に edge を引く 2-step 操作) に振る。
        multiSelectionKeyCode={["Shift"]}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={(event, node: BlockNode) => {
          // Ctrl / Meta + 左クリック: 2-step auto-connect
          // - 1 回目: ノードを source として記録
          // - 2 回目 (別ノード): A.out[0] -> B.in[0] に edge を作成
          // v0.20.5: source が edge 由来 (= {src, src_idx} オブジェクト) の
          //   場合も対応。既存配線から分岐して B.in[0] へ接続。
          if (event.ctrlKey || event.metaKey) {
            if (autoConnectSource === null) {
              setAutoConnectSource(node.id);
              selectNode(node.id);
              return;
            }
            // 同じノード自身を 2 回 Ctrl+ click: cancel
            const srcId =
              typeof autoConnectSource === "string"
                ? autoConnectSource
                : autoConnectSource.src;
            if (srcId === node.id) {
              setAutoConnectSource(null);
              return;
            }
            const srcIdx =
              typeof autoConnectSource === "string"
                ? 0
                : autoConnectSource.src_idx;
            addConnectionToEditing({
              src: srcId,
              src_idx: srcIdx,
              dst: node.id,
              dst_idx: 0,
            });
            setAutoConnectSource(null);
            selectNode(node.id);
            return;
          }
          // 通常: 選択 + auto-connect 中断
          setAutoConnectSource(null);
          selectNode(node.id);
        }}
        // v0.20.5: Edge を Ctrl+クリック → 「分岐配線」モード開始。
        // 既存 edge の src + src_idx を auto-connect source に記録、次に Ctrl+
        // クリックされたブロックの input port[0] へ枝分かれする edge を追加。
        // Simulink 互換 (= 信号線から複数ブロックへ分岐) パターンの実装。
        onEdgeClick={(event, edge) => {
          if (event.ctrlKey || event.metaKey) {
            event.stopPropagation();
            const srcIdx =
              edge.sourceHandle !== null && edge.sourceHandle !== undefined
                ? parseInt(edge.sourceHandle, 10) || 0
                : 0;
            setAutoConnectSource({ src: edge.source, src_idx: srcIdx });
            // 視覚フィードバックとして edge を選択状態に
            setSelectedEdgeIds([edge.id]);
            return;
          }
          // 通常クリック: 選択 + auto-connect 中断
          setAutoConnectSource(null);
        }}
        onNodeDoubleClick={onNodeDoubleClick}
        // Simulink 流: Shift を押しながらノードドラッグを始めると、対象 (= 選択中の)
        // ノードに繋がっているエッジをすべて切り離す。これによりブロックを「リンク
        // から外して動かす」操作が 1 ストロークで完結する。
        // また v0.16.0: ドラッグ中は body に ``pyflw-dragging`` を付け、CSS で全
        // ノードの transition を切る (= 複数選択ドラッグでも追従遅延が起きない)。
        onNodeDragStart={(event, node) => {
          document.body.classList.add("pyflw-dragging");
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
        onNodeDragStop={() => {
          document.body.classList.remove("pyflw-dragging");
        }}
        onSelectionDragStart={() => {
          document.body.classList.add("pyflw-dragging");
        }}
        onSelectionDragStop={() => {
          document.body.classList.remove("pyflw-dragging");
        }}
        onPaneClick={() => {
          // pane クリックは選択解除 + auto-connect 中断
          setAutoConnectSource(null);
          selectNode(null);
        }}
        onPaneContextMenu={(e) => e.preventDefault()}
        onNodeContextMenu={(e) => e.preventDefault()}
        deleteKeyCode={["Backspace", "Delete"]}
      >
        <Background gap={18} size={1} color="#cbd5e1" />
        <Controls className="!shadow-md" />
      </ReactFlow>
      {/* v0.20.6: ブランチドラッグ中のカーソル追従線 (= 全画面 fixed SVG)。
          start から current への直線で十分 (= Simulink でも drag 中は仮の
          直線のみ、確定後に React Flow が step edge を描画)。 */}
      {branchDrag && (
        <svg
          className="pointer-events-none fixed inset-0 z-50"
          width="100%"
          height="100%"
        >
          <line
            x1={branchDrag.startScreenX}
            y1={branchDrag.startScreenY}
            x2={branchDrag.currentScreenX}
            y2={branchDrag.currentScreenY}
            stroke="#1e293b"
            strokeWidth={1.5}
            strokeDasharray="4 3"
          />
        </svg>
      )}
      {quickAdd && (
        <QuickAdd
          screenX={quickAdd.screenX}
          screenY={quickAdd.screenY}
          flowX={quickAdd.flowX}
          flowY={quickAdd.flowY}
          onClose={() => setQuickAdd(null)}
        />
      )}
    </div>
  );
}
