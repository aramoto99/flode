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
  useStoreApi,
  type Connection,
  type Edge,
  type EdgeChange,
  type NodeChange,
  type OnConnect,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import { getLibraryEntry, listBlockMetadata } from "../api/client";
import { pushToast } from "../store/toastStore";
import {
  modelToDiagram,
  blockNodeToEndpoint,
  DIAGRAM_EDGE_STYLE,
  DIAGRAM_EDGE_TYPE,
  DIAGRAM_MARKER_END,
  type BlockNode,
} from "../lib/diagramConverter";
import { collectPythonCodes, ensurePythonSpecs } from "../lib/pythonFunctionSpec";
import { useDtypeResolutionFetcher } from "../lib/dtypeResolution";
import { usePythonSpecVersion } from "../lib/usePythonSpecVersion";
import { generateUniqueId } from "../lib/idGenerator";
import {
  resolveBlocksAtPath,
  resolveBranchWaypointsAtPath,
} from "../lib/pathResolver";
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
import { JunctionDots } from "./JunctionDots";
import { resolveJunctions } from "../lib/branchJunctions";
import { QuickAdd } from "./QuickAdd";
import {
  addBlockToEditing,
  addConnectionToEditing,
  removeBlockFromEditing,
  removeConnectionFromEditing,
  spliceEdgeWithBlock,
  updateBlockPosition,
  updateBlockPositions,
  useAppStore,
} from "../store/appStore";
import type { BranchWaypointDict, FlwModel } from "../types/api";
import {
  type BlockGeom,
  type EdgeGeom,
  findSpliceCandidate,
} from "../lib/autoSplice";
import {
  computeStepEdgePolyline,
  polylineIntersectsRect,
  type Point,
  type Rect,
} from "../lib/edgeRectIntersect";

// React Flow に渡すカスタムノード type 表 (modelToDiagram で type: "blockNode" を返す)。
// 識別子の object 参照を毎回同じにすることで React Flow の警告を回避する
// (`useMemo` がコンポーネント外で使えないため module-level 定数で代用)。
const NODE_TYPES = { blockNode: BlockNodeView } as const;

// v0.20.6: edge type "branchable" は BranchableEdge を使う。リファレンスツールの「既存
// 配線から分岐」drag を edge mousedown で発火できるようにする。
const EDGE_TYPES = { branchable: BranchableEdge } as const;

// 中ボタン (button=1) と右ボタン (button=2) で pan、左クリック (button=0) は
// 「空エリアドラッグ → 矩形選択 / ノード上ドラッグ → ノード移動」(リファレンスツール + 一般的な
// editor 慣習)。配列参照を毎 render で新しくしないために module-level 定数。
const PAN_BUTTONS = [1, 2];

/**
 * v0.21.0: legacy ``modelId`` prop を撤去し、``editingModel`` を store から
 * 直接読む形に変更 (= FileBrowser onClick が ``editingModel`` を populate 済の
 * 前提、ADR-0041 §論点 8-A)。
 *
 * ADR-0045 §(6) Stage 1: ``portalTarget`` が指定された場合、本コンポーネントの
 * DOM 出力を React Portal で当該要素に移動する。React tree 上の親
 * (= ``<ReactFlowProvider>`` 直下) は不変なので、SplitTree 構造の変更で
 * ``portalTarget`` が別の DOM ノードに切り替わっても ReactFlow / DiagramCanvas
 * の内部 state (= viewport / nodes / edges) は維持される。
 *
 * @param portalTarget undefined: 親に直接 render (= legacy 挙動)。
 *                     null: 何も render しない (= portal target 未確定の起動直後)。
 *                     HTMLElement: そのノードに portal で投影。
 */
export function DiagramCanvas({
  portalTarget,
}: { portalTarget?: HTMLElement | null } = {}): JSX.Element {
  const { t } = useTranslation();
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
  const selectedNodeIds = useAppStore((s) => s.selectedNodeIds);
  const selectNode = useAppStore((s) => s.selectNode);
  const setSelectedNodeIds = useAppStore((s) => s.setSelectedNodeIds);
  const selectedEdgeIds = useAppStore((s) => s.selectedEdgeIds);
  const setSelectedEdgeIds = useAppStore((s) => s.setSelectedEdgeIds);
  const editingPath = useAppStore((s) => s.editingPath);
  const drilldownInto = useAppStore((s) => s.drilldownInto);
  // ADR-0056 follow-up: Log tab のエラーからジャンプ要求を受けて canvas を pan する。
  const focusBlockRequest = useAppStore((s) => s.focusBlockRequest);

  // SPEC-0023 / ADR-0073 §論点 1: PythonFunction のポート数はコードの静的解析
  // (introspect) で決まる。モデル変更時に未解析コードをまとめて要求し、解析完了
  // (= cache 世代の更新) で再描画してポート数を確定値に置き換える。それまでの
  // 1 往復は registry default (1 in / 1 out) で描かれる (結線は壊れない、V10)。
  usePythonSpecVersion();
  // SM-D Stage 1 (SPEC-0028 §5.5): dtype 解決結果のモデルレベル fetch。
  // Inspector (SignalDtypeSection) と Display の表示整形が同じ store を読む
  useDtypeResolutionFetcher();
  useEffect(() => {
    const codes = collectPythonCodes(editingModel);
    if (codes.length > 0) void ensurePythonSpecs(codes);
  }, [editingModel]);

  // リファレンスツール互換 (v2.1.x ユーザー指摘): ``Ctrl + 左クリック`` 2-step auto-connect の
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

  // v0.20.6: リファレンスツール互換 「既存配線 mousedown → drag → ブロック drop で分岐
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
  const storeApi = useStoreApi();

  // v3.x: ドラッグ範囲選択 (rubber-band) で「両端ノードのどちらも矩形外で、
  // 中間の path だけが矩形を横切るエッジ」が選択されないバグの補完。
  // React Flow v12 の UserSelection は ``getNodesInside`` で選んだ node に
  // 接続している edge しか拾わない (= edge geometry × rect 判定なし)。本 hook
  // で ``userSelectionRect`` が null に戻った瞬間 (= drag 終了) を捕まえ、
  // edge polyline × flow 座標 rect で追加判定する。
  //
  // ref 経由で最新 edges/nodes/selection を読むことで store subscription を
  // 1 回だけに抑える (= drag 中の高頻度更新で DiagramCanvas が再 render しない)。
  const rubberBandRefs = useRef<{
    edges: Edge[];
    nodes: BlockNode[];
    selectedEdgeIds: readonly string[];
  }>({ edges: [], nodes: [], selectedEdgeIds: [] });

  // リファレンスツール風: ノード上で右クリックドラッグ = そのノードをコピーしてカーソルに追従。
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
      // リファレンスツール仕様 (= ユーザー指摘):
      // - ``Ctrl + 右クリックドラッグ``: ノード複製
      // - 単純な右クリック (Ctrl なし) ドラッグ: 同様にノード複製 (= alternative
      //   shortcut、リファレンスツールでも両方使える)
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
      document.body.classList.add("flode-copying");

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
      document.body.classList.remove("flode-copying");
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
      document.body.classList.remove("flode-copying");
    };
  }, [reactFlow]);

  // v0.21.0: legacy ``serverModel`` 初期化 effect を削除。``editingModel`` は
  // FileBrowser onClick が File API 経由で populate するため、ここでの初期化
  // は不要。

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

  // ADR-0056 follow-up: Log tab のエラーからのジャンプ要求を受けて canvas を pan。
  // ``focusBlock`` action が editingPath / 選択 / focusBlockRequest を同一 set で
  // 更新するため、この effect 発火時には新パスの nodes が React Flow に描画済。
  useEffect(() => {
    if (!focusBlockRequest) return;
    const node = reactFlow.getNode(focusBlockRequest.blockId);
    if (!node) return; // 別 path / 未描画なら no-op (= drilldown 不能ケース)
    const w = node.measured?.width ?? node.width ?? 0;
    const h = node.measured?.height ?? node.height ?? 0;
    reactFlow.setCenter(node.position.x + w / 2, node.position.y + h / 2, {
      zoom: reactFlow.getZoom(),
      duration: 400,
    });
  }, [focusBlockRequest, reactFlow]);

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
      // flode GUI 既定挙動)。
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

  // userSelectionRect が非 null → null に切り替わった瞬間 (= 範囲選択完了)
  // を捕まえ、矩形を横切る edge を追加で選択する (= React Flow v12 default では
  // 拾われない edge の補完)。
  useEffect(() => {
    let prevRect:
      | { x: number; y: number; width: number; height: number }
      | null = null;
    const unsubscribe = storeApi.subscribe((state) => {
      const cur = state.userSelectionRect;
      if (cur !== null) {
        // dragging 中: 最新 rect を保持しておく (= pointerup 時に store から
        // 消されるため、直前の値を自前で記録する)
        prevRect = { x: cur.x, y: cur.y, width: cur.width, height: cur.height };
        return;
      }
      if (prevRect === null) return;
      const screenRect = prevRect;
      prevRect = null;
      const [tx, ty, zoom] = state.transform;
      if (zoom <= 0) return;
      // screen (container-relative px) → flow 座標
      const flowRect: Rect = {
        x: (screenRect.x - tx) / zoom,
        y: (screenRect.y - ty) / zoom,
        w: screenRect.width / zoom,
        h: screenRect.height / zoom,
      };
      const { edges: curEdges, nodes: curNodes, selectedEdgeIds: curSelected } =
        rubberBandRefs.current;
      const nodeById = new Map(curNodes.map((n) => [n.id, n]));
      const additional: string[] = [];
      for (const edge of curEdges) {
        const src = nodeById.get(edge.source);
        const dst = nodeById.get(edge.target);
        if (!src || !dst) continue;
        const srcEp = blockNodeToEndpoint(src);
        const dstEp = blockNodeToEndpoint(dst);
        if (!srcEp || !dstEp) continue;
        const srcIdx = Number(edge.sourceHandle ?? 0);
        const dstIdx = Number(edge.targetHandle ?? 0);
        // ADR-0057: 手動分岐点 (via) があれば描画と同一の via 経由 polyline で
        // 交差判定する (= 幾何 SSOT)。via は decoratedEdges の data に入っている。
        const via = (edge.data as { via?: Point } | undefined)?.via;
        const polyline = computeStepEdgePolyline(
          srcEp,
          srcIdx,
          dstEp,
          dstIdx,
          via,
        );
        if (polylineIntersectsRect(polyline, flowRect)) {
          additional.push(edge.id);
        }
      }
      if (additional.length === 0) return;
      const merged = new Set<string>(curSelected);
      let changed = false;
      for (const id of additional) {
        if (!merged.has(id)) {
          merged.add(id);
          changed = true;
        }
      }
      if (changed) setSelectedEdgeIds(Array.from(merged));
    });
    return unsubscribe;
  }, [storeApi, setSelectedEdgeIds]);

  // v0.21.0: legacy loading/error 判定削除 (= editingModel は FileBrowser
  // onClick で populate される、loading 表示は FileBrowser 側 / no_model
  // 表示で対応)。
  const model = editingModel;
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
  // ADR-0057: 現スコープの手動分岐点 (branch_waypoints)。pathView 解決が成功して
  // いるので通常 throw しないが、editingPath の非同期変化等のコーナーケースで例外が
  // 出てもレンダーをクラッシュさせず楽観無視する (= ADR-0057 §(5) load 時方針)。
  let scopeWaypoints: BranchWaypointDict = {};
  try {
    scopeWaypoints = resolveBranchWaypointsAtPath(model, editingPath);
  } catch {
    scopeWaypoints = {};
  }
  const selectedSet = new Set(selectedNodeIds);
  const decoratedNodes = baseNodes.map((n) => ({
    ...n,
    selected: selectedSet.has(n.id),
  }));
  // ADR-0057 (改訂): 分岐点 ● の算出 (自動 + 手動の幹線上再構成 + クランプ) を
  // resolveJunctions に一本化する (= 幾何 SSOT)。返り値の vias (= 手動グループの
  // 正規化済 via {x,y}) を edge / rubber-band へ、junctionDots を <JunctionDots> へ
  // 渡し、描画・● 算出・rubber-band の 3 系統が同一 via を共有する。枝が 2 本未満の
  // 孤児グループは resolveJunctions が除外する (= 楽観的無視)。
  const { dots: junctionDots, vias } = resolveJunctions(
    decoratedNodes,
    edges,
    scopeWaypoints,
  );
  const decoratedEdges = edges.map((e) => {
    const gkey = `${e.source}:${Number(e.sourceHandle ?? 0)}`;
    const via = vias.get(gkey);
    return {
      ...e,
      // diagramConverter で設定した type ("branchable") を尊重 (= リファレンスツール風 90°
      // 折れ線)。``smoothstep`` で上書きしていた v0.x 時代の挙動を撤廃。
      animated: false,
      // controlled mode では ``selected`` を prop に流し込まないと .selected
      // クラスが付かず、CSS のハイライトが効かない (= ユーザーから選択不可に見える)。
      selected: selectedEdgeIds.includes(e.id),
      data: via ? { ...(e.data ?? {}), via } : e.data,
    };
  });
  // rubber-band 補完 hook の subscription callback が常に最新の edges/nodes/
  // selection を参照できるよう、render 毎に ref を更新する。
  rubberBandRefs.current = {
    edges: decoratedEdges,
    nodes: decoratedNodes,
    selectedEdgeIds,
  };

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
    // ADR-0029: Library entry の drop は別 MIME (`application/flode-library-entry-ref`)
    // で運ばれる。先にそちらを check してから通常 block drop に fallback する。
    const libraryRefRaw = event.dataTransfer.getData(
      "application/flode-library-entry-ref",
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
      // SHOULD: 非同期完了時にユーザーが別ファイルへ切り替えていたら drop は無視する
      // (= 古い座標で別モデルにブロックが追加されるのを防ぐ)。v0.21.0:
      // ``selectedFilePath`` を snapshot して比較。
      const dropFilePath = useAppStore.getState().selectedFilePath;
      void getLibraryEntry(ref.library, ref.entry)
        .then((detail) => {
          const state = useAppStore.getState();
          if (state.selectedFilePath !== dropFilePath) {
            // ユーザーが drop 中に別ファイルに切り替えた → drop を破棄
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
    const typePath = event.dataTransfer.getData("application/flode-block-type");
    if (!typePath) return;
    const defaultParamsRaw = event.dataTransfer.getData(
      "application/flode-default-params",
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
    // v0.26.0 リファレンスツールの auto-connect-on-edge: drop 直後に block が edge 上に
    // 載ったら自動接続。store は同期 set なので getState で最新を読める。
    tryAutoSplice(newId);
  };

  /**
   * v0.26.0: ``blockId`` の現在位置で auto-connect-on-edge の判定を行い、
   * 該当 edge が **正確に 1 件** なら splice する (= 元 edge を 2 本に置換)。
   *
   * 適用条件:
   *   - block が SISO (n_inputs=1, n_outputs=1)
   *   - block 入力 0 と出力 0 が edge path 上にある (= helper 判定)
   *   - block 自身に既存 connection が無い (= 動的な auto-splice での既存接続
   *     破壊を防ぐ、新規 drop と「孤立ブロック移動」だけ対象)
   */
  function tryAutoSplice(blockId: string): void {
    const state = useAppStore.getState();
    const model = state.editingModel;
    if (!model) return;
    let view;
    try {
      view = resolveBlocksAtPath(model, state.editingPath);
    } catch {
      return;
    }
    // block 自身に既存 connection があれば skip (= 利用者が明示的に接続済)
    const hasOwnConnection = view.connections.some(
      (c) => c.src === blockId || c.dst === blockId,
    );
    if (hasOwnConnection) return;
    const target = view.blocks.find((b) => b.id === blockId);
    if (!target) return;
    const targetLayout = view.layout[blockId];
    if (!targetLayout) return;

    // block → BlockGeom 変換 (= autoSplice helper が期待する形)
    const toGeom = (b: typeof target): BlockGeom => {
      const l = view.layout[b.id];
      return {
        id: b.id,
        type: b.type,
        params: b.params,
        x: l?.x ?? 0,
        y: l?.y ?? 0,
        w: typeof l?.w === "number" ? l.w : undefined,
        h: typeof l?.h === "number" ? l.h : undefined,
      };
    };
    const blockGeom = toGeom(target);
    const allGeoms = view.blocks.map(toGeom);
    const edgeGeoms: EdgeGeom[] = view.connections.map((c) => ({
      src: c.src,
      src_idx: c.src_idx,
      dst: c.dst,
      dst_idx: c.dst_idx,
    }));
    const candidate = findSpliceCandidate(
      blockGeom,
      allGeoms,
      edgeGeoms,
      registryMap,
    );
    if (candidate) {
      spliceEdgeWithBlock(candidate.edge, blockId);
    }
  }

  // ADR-0021 §(4): is_container=true なノード (= Subsystem サブクラス) を
  // ダブルクリックでドリルダウンする。registry の `is_container` を参照。
  // ADR-0044 §論点 8-A: Scope / XYGraph をダブルクリックで floating panel を開く。
  // v0.30.0 で docked split 昇格に semantics 変更したが、v0.30.2 でユーザー要望
  // により revert (= ADR-0044 当初挙動に戻す)。
  const openScopePanel = useAppStore((s) => s.openScopePanel);
  const onNodeDoubleClick = (
    _event: React.MouseEvent,
    node: BlockNode,
  ): void => {
    const meta = registryMap.get(node.data.blockType);
    if (meta?.is_container) {
      drilldownInto(node.id);
      return;
    }
    const t = node.data.blockType;
    if (t.endsWith(".Scope") || t.endsWith(".XYGraph")) {
      openScopePanel(node.id);
    }
  };

  // 空ペーン (どのノードにも乗っていない領域) をダブルクリックで Quick Insert を開く。
  // リファレンスツールのクイック挿入機能と同等の操作。React Flow v12 には ``onPaneDoubleClick``
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

  // ADR-0045 §(6): portalTarget が指定されていれば、出力 DOM を React Portal で
  // 移動する (= React tree 上の親は ``<ReactFlowProvider>`` 直下のまま不変、
  // viewport / nodes / edges 等の internal state が SplitTree 構造変更でも維持)。
  const content = (
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
        // ADR-0057: via 注入済の decoratedEdges を渡す (rubber-band 判定と SSOT)。
        // 注意: ここでインライン ``style`` を当てると CSS の
        // ``.react-flow__edge.selected`` / ``:hover`` ルールが specificity 負けする
        // ので入れない。色 / 太さは index.css で集中管理。
        edges={decoratedEdges}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        fitView
        // v0.32.3: fitView は既定で zoom 上限なしのため、ノードが少ないモデルで
        // 過度に拡大されていた (= ユーザー指摘「デフォルトの拡大率が少し大きい」)。
        // maxZoom=1.0 で 100% を超えないように制限、padding は描画余白
        fitViewOptions={{ maxZoom: 1.0, padding: 0.2 }}
        nodesDraggable
        defaultEdgeOptions={{
          // 業界標準ブロック線図ツール準拠: 90° 折れ線 (step) + 黒系細線 + 終点矢印 head。
          // v0.20.11: markerEnd 復活。BranchableEdge が target 座標を矢印
          // サイズ分外側に置く補正をするため、矢印 head が node 境界に綺麗に
          // 当たる位置に描画される (= 矢印先端が node 境界 + 8 px、base が
          // node 境界)。
          type: DIAGRAM_EDGE_TYPE,
          style: DIAGRAM_EDGE_STYLE,
          markerEnd: DIAGRAM_MARKER_END,
        }}
        proOptions={{ hideAttribution: true }}
        // 左クリックドラッグ = 空エリアで矩形選択 / ノード上でそのノード移動
        // (リファレンスツール + 一般的な editor 慣習)。``panOnDrag = [1, 2]`` で中 / 右ボタン
        // ドラッグだけ pan に。OS の右クリックメニューは onPaneContextMenu / onNodeContextMenu
        // で preventDefault する。
        panOnDrag={PAN_BUTTONS}
        selectionOnDrag
        selectionMode={SelectionMode.Partial}
        // リファレンスツール仕様: ``Shift`` で multi-select、``Ctrl/Meta`` は auto-connect
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
        // リファレンスツール互換 (= 信号線から複数ブロックへ分岐) パターンの実装。
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
        // リファレンスツール流: Shift を押しながらノードドラッグを始めると、対象 (= 選択中の)
        // ノードに繋がっているエッジをすべて切り離す。これによりブロックを「リンク
        // から外して動かす」操作が 1 ストロークで完結する。
        // また v0.16.0: ドラッグ中は body に ``flode-dragging`` を付け、CSS で全
        // ノードの transition を切る (= 複数選択ドラッグでも追従遅延が起きない)。
        onNodeDragStart={(event, node) => {
          document.body.classList.add("flode-dragging");
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
        onNodeDragStop={(_event, node) => {
          document.body.classList.remove("flode-dragging");
          // v0.26.0: 移動後の位置で auto-connect-on-edge を試行
          // (= 孤立ブロックを wire の上に置いたケース)
          tryAutoSplice(node.id);
        }}
        onSelectionDragStart={() => {
          document.body.classList.add("flode-dragging");
        }}
        onSelectionDragStop={() => {
          document.body.classList.remove("flode-dragging");
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
        {/* 分岐点 (junction) に ● を描く。同一出力ポートから複数 edge が分かれる
            mid-wire 位置に打つ (= ブロック線図の慣例)。ADR-0057 改訂: ● は幹線上を
            1 軸スライドで固定でき、resolveJunctions が算出した junctionDots を渡す。 */}
        <JunctionDots junctions={junctionDots} />
      </ReactFlow>
      {/* v0.20.6: ブランチドラッグ中のカーソル追従線 (= 全画面 fixed SVG)。
          start から current への直線で十分 (= リファレンスツールでも drag 中は仮の
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

  if (portalTarget === undefined) return content;
  if (portalTarget === null) return <></>;
  return <>{createPortal(content, portalTarget)}</>;
}
