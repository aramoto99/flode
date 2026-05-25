// ブロック線図の慣例「分岐点 (junction / branch point) に ● を打つ」を描画する
// オーバーレイ + 手動 waypoint routing (ADR-0057) の canvas 直接操作 UI。
//
// このツールの分岐は「同一出力ポートから複数の独立 edge を引く」方式
// (``BranchableEdge``) のため、線が重なって途中で分かれる分岐点にマーカーが
// 出ていなかった。本コンポーネントは React Flow store からライブの nodes /
// edges を購読し、同一 (source, sourceHandle) グループの edge polyline が実際に
// 分かれる座標 (= mid-wire の分岐点) を ``findJunctionPoints`` で求めて ● を描く。
//
// ADR-0057: ● は表示専用ではなくドラッグで任意位置に固定できる (= 手動 waypoint
// routing)。手動位置を持つグループ (= ``waypoints[groupKey]`` が存在) は自動算出を
// **スキップ**し、waypoint 座標を ● 位置として使う (= 描画 via と ● 座標が同一値に
// なり幾何整合が定義上保証される、二重表示も防止)。ダブルクリック / 右クリック
// メニューで手動位置を破棄して自動計算に戻す。
//
// 座標は flow 座標系なので ``ViewportPortal`` 内に置いて pan / zoom に追従させる。
// nodes を store から取ることで、controlled mode のドラッグ中 (= ``onNodesChange``
// が毎フレーム store へ position を反映) も ● が配線に追従する。

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import {
  useReactFlow,
  useStore,
  ViewportPortal,
  type Edge,
} from "@xyflow/react";

import {
  blockNodeToEndpoint,
  DIAGRAM_EDGE_STROKE,
  type BlockNode,
} from "../lib/diagramConverter";
import { computeStepEdgePolyline, type Point } from "../lib/edgeRectIntersect";
import { findJunctionPoints } from "../lib/junctionDots";
import {
  resetBranchWaypoint,
  setBranchWaypoint,
} from "../store/appStore";
import type { BranchWaypointDict } from "../types/api";

/** 分岐点 ● の描画半径 (flow px)。配線 strokeWidth=1.5 に対し視認できる太さ。 */
const JUNCTION_DOT_RADIUS = 3;

/** ● のドラッグ hit-target 直径 (flow px)。描画半径より広く取りつつ、配線の
 *  hit area (strokeWidth=20) を不当に食わないサイズ (= ADR-0057 §Q3、半径 9px)。 */
const JUNCTION_DOT_HIT_DIAMETER = 18;

/** waypoints prop 欠落時の安定参照 (= useMemo の依存で毎レンダー新規 {} を作らない)。 */
const EMPTY_WAYPOINTS: BranchWaypointDict = {};

/** 分岐点 ● 1 個分の算出結果。 */
export interface JunctionDot {
  /** flow 絶対座標。 */
  x: number;
  y: number;
  /** 合成キー ``"<source block id>:<sourceHandle index>"`` (= 永続キーと同形)。 */
  groupKey: string;
  /** ``true`` で手動固定 (= waypoint 由来)。``false`` は自動計算。 */
  manual: boolean;
}

/**
 * nodes / edges / 手動 waypoint から全分岐点の座標を算出する。
 *
 * edge を ``(source, sourceHandle)`` でグルーピングし、2 本以上のグループのみ:
 * - 手動 waypoint があれば waypoint 座標を ● として 1 個だけ返す (自動算出を抑制)
 * - 無ければ各 edge の step polyline を ``computeStepEdgePolyline`` (= 描画と同一
 *   幾何) で作って ``findJunctionPoints`` に渡し、自動 ● を返す
 */
export function computeJunctionDots(
  nodes: BlockNode[],
  edges: Edge[],
  waypoints: BranchWaypointDict,
): JunctionDot[] {
  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  const groups = new Map<string, Edge[]>();
  for (const e of edges) {
    const srcIdx = Number(e.sourceHandle ?? 0);
    // 永続キーと同形の合成キー (= ADR-0004 で block id に `:` は出ないため曖昧なし)。
    const key = `${e.source}:${srcIdx}`;
    const arr = groups.get(key);
    if (arr) arr.push(e);
    else groups.set(key, [e]);
  }

  const dots: JunctionDot[] = [];
  for (const [groupKey, group] of groups) {
    if (group.length < 2) continue;
    const via = waypoints[groupKey];
    if (via) {
      // 手動上書き: 自動算出をスキップし waypoint 座標に ● を 1 個だけ打つ。
      if (Number.isFinite(via.x) && Number.isFinite(via.y)) {
        dots.push({ x: via.x, y: via.y, groupKey, manual: true });
      }
      continue;
    }
    const polylines: Point[][] = [];
    for (const e of group) {
      const src = nodeById.get(e.source);
      const dst = nodeById.get(e.target);
      if (!src || !dst) continue;
      const srcEp = blockNodeToEndpoint(src);
      const dstEp = blockNodeToEndpoint(dst);
      if (!srcEp || !dstEp) continue;
      const srcIdx = Number(e.sourceHandle ?? 0);
      const dstIdx = Number(e.targetHandle ?? 0);
      polylines.push(computeStepEdgePolyline(srcEp, srcIdx, dstEp, dstIdx));
    }
    for (const p of findJunctionPoints(polylines)) {
      dots.push({ x: p.x, y: p.y, groupKey, manual: false });
    }
  }
  return dots;
}

/** ドラッグ中の状態 (= 掴んだ ● のグループキー + grab オフセット)。 */
interface DragState {
  groupKey: string;
  /** ドラッグ開始時の (● 座標 − カーソル flow 座標)。掴んだ位置のズレを保つ。 */
  offsetX: number;
  offsetY: number;
}

/** 右クリックメニューの state (screen 座標 + 対象グループ)。 */
interface MenuState {
  x: number;
  y: number;
  groupKey: string;
}

/**
 * 分岐点 ● を描画 + ドラッグ移動するオーバーレイ。``<ReactFlow>`` の子として配置
 * する (``ViewportPortal`` / ``useStore`` / ``useReactFlow`` が React Flow context を
 * 要求するため)。
 *
 * @param waypoints 現在の編集スコープの ``branch_waypoints`` (= ``DiagramCanvas`` が
 *   ``resolveBranchWaypointsAtPath`` で解決して渡す)。欠落時は全自動計算。
 */
export function JunctionDots({
  waypoints,
}: {
  waypoints?: BranchWaypointDict;
}): JSX.Element | null {
  const { t } = useTranslation();
  const reactFlow = useReactFlow();
  // ドラッグ effect の deps を ``drag`` のみに保つため最新 instance を ref に逃がす
  // (= useReactFlow が render ごとに参照変化しても listener を貼り直さず、ドラッグ中
  // の pointermove を取りこぼさない)。
  const reactFlowRef = useRef(reactFlow);
  reactFlowRef.current = reactFlow;
  // controlled mode では store.nodes = 渡している nodes prop。ドラッグ中も
  // ライブ更新されるため ● が配線に追従する。
  const nodes = useStore((s) => s.nodes as BlockNode[]);
  const edges = useStore((s) => s.edges);

  const [drag, setDrag] = useState<DragState | null>(null);
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);
  const [menu, setMenu] = useState<MenuState | null>(null);
  const [menuHover, setMenuHover] = useState(false);

  const wp = waypoints ?? EMPTY_WAYPOINTS;
  const dots = useMemo(
    () => computeJunctionDots(nodes, edges, wp),
    [nodes, edges, wp],
  );

  // ドラッグ中は window で pointermove / pointerup を捕捉し、毎フレーム waypoint を
  // 更新する (= mergeKey で 1 履歴エントリに集約、ノード移動と同方針)。
  useEffect(() => {
    if (!drag) return;
    const onMove = (e: PointerEvent): void => {
      const flow = reactFlowRef.current.screenToFlowPosition({
        x: e.clientX,
        y: e.clientY,
      });
      setBranchWaypoint(
        drag.groupKey,
        { x: flow.x + drag.offsetX, y: flow.y + drag.offsetY },
        { merge: true },
      );
    };
    const onUp = (): void => setDrag(null);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [drag]);

  // 右クリックメニューは外側クリック / Esc で閉じる。メニュー内 pointerdown は
  // stopPropagation するため window listener には届かない (= 自身では閉じない)。
  useEffect(() => {
    if (!menu) return;
    const close = (): void => {
      setMenu(null);
      setMenuHover(false);
    };
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("pointerdown", close);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("keydown", onKey);
    };
  }, [menu]);

  if (dots.length === 0 && menu === null) return null;

  return (
    <>
      <ViewportPortal>
        {dots.map((dot) => {
          const isDragging = drag?.groupKey === dot.groupKey;
          const isHovered = hoveredKey === dot.groupKey || isDragging;
          return (
            <div
              // 手動 ● は groupKey で一意 (ドラッグ中も remount せず滑らかに追従)。
              // 自動 ● は同一グループに複数あり得るため座標も key に含める。
              key={
                dot.manual
                  ? `m:${dot.groupKey}`
                  : `a:${dot.groupKey}:${dot.x},${dot.y}`
              }
              style={{
                position: "absolute",
                left: dot.x,
                top: dot.y,
                width: JUNCTION_DOT_HIT_DIAMETER,
                height: JUNCTION_DOT_HIT_DIAMETER,
                transform: "translate(-50%, -50%)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                cursor: isDragging ? "grabbing" : "grab",
                // ● 上の pointerdown = ● 移動。配線 (BranchableEdge) の新規分岐
                // drag は dot 外の wire で従来どおり発火する (= ADR-0057 §Q3)。
                pointerEvents: "auto",
                // touch でのスクロール抑制 + ドラッグ中のテキスト選択抑制。
                // (preventDefault は使わず CSS で済ませる = click/focus を阻害しない)
                touchAction: "none",
                userSelect: "none",
              }}
              onPointerDown={(e) => {
                if (e.button !== 0) return; // 左ボタンのみ (右は context menu)
                e.stopPropagation();
                const flow = reactFlow.screenToFlowPosition({
                  x: e.clientX,
                  y: e.clientY,
                });
                setDrag({
                  groupKey: dot.groupKey,
                  offsetX: dot.x - flow.x,
                  offsetY: dot.y - flow.y,
                });
              }}
              onDoubleClick={(e) => {
                // 手動 ● のみリセット可 (自動 ● は破棄対象が無い)。
                if (!dot.manual) return;
                e.stopPropagation();
                resetBranchWaypoint(dot.groupKey);
              }}
              onContextMenu={(e) => {
                e.preventDefault();
                e.stopPropagation();
                if (!dot.manual) return;
                setMenu({ x: e.clientX, y: e.clientY, groupKey: dot.groupKey });
              }}
              onPointerEnter={() => setHoveredKey(dot.groupKey)}
              onPointerLeave={() =>
                setHoveredKey((k) => (k === dot.groupKey ? null : k))
              }
            >
              <div
                style={{
                  width: JUNCTION_DOT_RADIUS * 2,
                  height: JUNCTION_DOT_RADIUS * 2,
                  borderRadius: "50%",
                  background: DIAGRAM_EDGE_STROKE,
                  // ホバー / ドラッグ中はわずかに拡大して「掴める点」を示す。
                  transform: isHovered ? "scale(1.5)" : "scale(1)",
                  transition: "transform 80ms ease-out",
                }}
              />
            </div>
          );
        })}
      </ViewportPortal>
      {menu !== null &&
        createPortal(
          <div
            style={{
              position: "fixed",
              left: menu.x,
              top: menu.y,
              zIndex: 1000,
              background: "#ffffff",
              border: "1px solid #cbd5e1", // slate-300
              borderRadius: 2,
              boxShadow: "0 2px 6px rgba(0,0,0,0.15)",
              padding: "2px 0",
              fontSize: 12,
              minWidth: 160,
            }}
            // メニュー内 pointerdown は外側クリック判定 (window) に伝播させない。
            onPointerDown={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                padding: "4px 12px",
                background: menuHover ? "#f1f5f9" : "transparent", // slate-100 / -
                border: "none",
                cursor: "pointer",
                color: "#1e293b", // slate-800
              }}
              onMouseEnter={() => setMenuHover(true)}
              onMouseLeave={() => setMenuHover(false)}
              onClick={() => {
                resetBranchWaypoint(menu.groupKey);
                setMenu(null);
                setMenuHover(false);
              }}
            >
              {t("diagram.reset_branch_waypoint")}
            </button>
          </div>,
          document.body,
        )}
    </>
  );
}
