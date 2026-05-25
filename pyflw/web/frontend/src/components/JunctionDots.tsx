// ブロック線図の慣例「分岐点 (junction / branch point) に ● を打つ」を描画する
// オーバーレイ + 手動 waypoint routing (ADR-0057 改訂) の canvas 直接操作 UI。
//
// 分岐点の算出 (自動 + 手動の幹線上再構成) は ``resolveJunctions`` (= 幾何 SSOT) が
// 担い、本コンポーネントは受け取った ``junctions`` を描画 + ドラッグ/リセットする
// だけの presentation + interaction 層。これにより DiagramCanvas (edge 描画) と
// ● が**同一の正規化済 via** を共有する。
//
// ADR-0057 改訂 (R1): ● は幹線 (source 出力高さ) 上の **1 軸スライド**に拘束される。
// ドラッグは幹線方向 (現状は水平 = X) のみ動き、`[source 端, 最も近い target 端]` に
// クランプされる。これにより ● は常に「線が実際に分かれる点」であり続ける。
// ダブルクリック / 右クリックメニューで手動位置を破棄し自動計算に戻す。
//
// 座標は flow 座標系なので ``ViewportPortal`` 内に置いて pan / zoom に追従させる。

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { useReactFlow, ViewportPortal } from "@xyflow/react";

import { DIAGRAM_EDGE_STROKE } from "../lib/diagramConverter";
import {
  along,
  type ResolvedJunctionDot,
  type TrunkAxis,
} from "../lib/branchJunctions";
import { resetBranchWaypoint, setBranchWaypoint } from "../store/appStore";

/** 分岐点 ● の描画半径 (flow px)。配線 strokeWidth=1.5 に対し視認できる太さ。 */
const JUNCTION_DOT_RADIUS = 3;

/** ● のドラッグ hit-target 直径 (flow px)。描画半径より広く取りつつ、配線の
 *  hit area (strokeWidth=20) を不当に食わないサイズ (= ADR-0057 §Q3、半径 9px)。 */
const JUNCTION_DOT_HIT_DIAMETER = 18;

/** ドラッグ中の状態 (= 掴んだ ● のグループ + 幹線軸 + 可動範囲 + grab オフセット)。 */
interface DragState {
  groupKey: string;
  axis: TrunkAxis;
  lo: number;
  hi: number;
  /** ドラッグ開始時の (● 幹線方向座標 − カーソル幹線方向座標)。掴んだズレを保つ。 */
  offsetAlong: number;
}

/** 右クリックメニューの state (screen 座標 + 対象グループ)。 */
interface MenuState {
  x: number;
  y: number;
  groupKey: string;
}

/**
 * 分岐点 ● を描画 + 幹線上 1 軸ドラッグするオーバーレイ。``<ReactFlow>`` の子として
 * 配置する (``ViewportPortal`` / ``useReactFlow`` が React Flow context を要求するため)。
 *
 * @param junctions ``resolveJunctions`` が返した現スコープの ● 一覧 (描画 + ドラッグ
 *   拘束幾何を同梱)。DiagramCanvas が render 毎に算出して渡す (= ドラッグ中もライブ追従)。
 */
export function JunctionDots({
  junctions,
}: {
  junctions: readonly ResolvedJunctionDot[];
}): JSX.Element | null {
  const { t } = useTranslation();
  const reactFlow = useReactFlow();
  // ドラッグ effect の deps を ``drag`` のみに保つため最新 instance を ref に逃がす。
  const reactFlowRef = useRef(reactFlow);
  reactFlowRef.current = reactFlow;

  const [drag, setDrag] = useState<DragState | null>(null);
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);
  const [menu, setMenu] = useState<MenuState | null>(null);
  const [menuHover, setMenuHover] = useState(false);

  // ドラッグ中は window で pointermove / pointerup を捕捉し、幹線方向に射影 +
  // クランプした位置を毎フレーム waypoint へ書く (= mergeKey で 1 履歴に集約)。
  useEffect(() => {
    if (!drag) return;
    const onMove = (e: PointerEvent): void => {
      const flow = reactFlowRef.current.screenToFlowPosition({
        x: e.clientX,
        y: e.clientY,
      });
      const raw = along(drag.axis, flow) + drag.offsetAlong;
      const pos = Math.min(drag.hi, Math.max(drag.lo, raw));
      setBranchWaypoint(drag.groupKey, { axis: drag.axis, pos }, { merge: true });
    };
    const onUp = (): void => setDrag(null);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    // pointercancel (touch のスクロール割り込み / OS タスクスイッチ等) でも終了し、
    // drag state がリークして以降の pointermove で誤更新が続くのを防ぐ。
    window.addEventListener("pointercancel", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, [drag]);

  // 右クリックメニューは外側クリック / Esc で閉じる。
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

  if (junctions.length === 0 && menu === null) return null;

  return (
    <>
      <ViewportPortal>
        {junctions.map((dot) => {
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
                // 幹線軸方向のリサイズカーソルで「動かせる方向」を示す。
                cursor: isDragging
                  ? "grabbing"
                  : dot.axis === "x"
                    ? "ew-resize"
                    : "ns-resize",
                // ● 上の pointerdown = ● 移動。配線 (BranchableEdge) の新規分岐
                // drag は dot 外の wire で従来どおり発火する (= ADR-0057 §Q3)。
                pointerEvents: "auto",
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
                  axis: dot.axis,
                  lo: dot.lo,
                  hi: dot.hi,
                  offsetAlong: along(dot.axis, dot) - along(dot.axis, flow),
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
