// v0.20.6: リファレンスツール互換の「既存配線から分岐配線を引く」を実現する Custom Edge。
//
// 既存の React Flow built-in ``"step"`` edge と同じ見た目 (= ステップ折れ線
// + 矢印 head) を維持しつつ、path に invisible で太い overlay path を重ね、
// ``onPointerDown`` で drag 開始を捕捉する。
//
// drag 開始の通知は global subscription pattern (= ``setBranchStartHandler``)
// で DiagramCanvas に届ける (= React Context を edge component に流すと
// 全 edge が再 render するため避ける)。

import { BaseEdge, type EdgeProps, getSmoothStepPath, Position } from "@xyflow/react";

// v0.20.10: edge の起点 / 終点を Handle 中心 (= node 境界の +12 px 外側) では
// なく **node 境界線** に補正するためのオフセット。React Flow Handle width=24
// で Handle center は node 境界の Handle width/2 = 12 px 外側にあるため、
// edge 描画座標を 12 px 内側にずらすと node 境界に edge が直接当たる。
//
// v0.20.12: source / target ともに 12 px 補正で揃える。SVG markerEnd の矢印
// head は path の終端を **矢印先端の anchor** として描画し、矢印 base は
// path 方向の逆側 (= source 方向) に伸びる:
//   - Right pos の出力ポート → path 始点 (= source)、ここに矢印は出ない
//   - Left pos の入力ポート → path 終点 (= target)、矢印先端 = adjustedTargetX、
//     base は外側 (右) に 8 px → 矢印 head 全体が node 外で path 方向を向く
//
// よって target も 12 px 補正 (= adjustedTargetX = node 境界) で、矢印先端
// が node 境界に綺麗に触れ、矢印 head 全体は node 外側に綺麗に描画される。
const PORT_TO_NODE_BORDER_PX = 12;

function adjustToBorder(
  x: number,
  y: number,
  position: Position,
): { x: number; y: number } {
  switch (position) {
    case Position.Right:
      return { x: x - PORT_TO_NODE_BORDER_PX, y };
    case Position.Left:
      return { x: x + PORT_TO_NODE_BORDER_PX, y };
    case Position.Top:
      return { x, y: y + PORT_TO_NODE_BORDER_PX };
    case Position.Bottom:
      return { x, y: y - PORT_TO_NODE_BORDER_PX };
    default:
      return { x, y };
  }
}

export interface BranchStartParams {
  /** 既存 edge の source ノード ID (= 分岐の起点ブロック) */
  src: string;
  /** 既存 edge の source ポート番号 */
  src_idx: number;
  /** mousedown 時の screen 座標 (= ドラッグ追従線の始点) */
  startScreenX: number;
  startScreenY: number;
}

type BranchStartHandler = (params: BranchStartParams) => void;

let _handler: BranchStartHandler | null = null;

/** DiagramCanvas が mount 時に呼び出して branch drag 開始通知を購読する。
 *  unmount 時は ``null`` を渡してクリア。 */
export function setBranchStartHandler(cb: BranchStartHandler | null): void {
  _handler = cb;
}

/**
 * React Flow の ``"step"`` edge と同等のステップ折れ線を描画 + 透明 overlay で
 * mousedown を捕捉する Custom Edge。
 */
export function BranchableEdge(props: EdgeProps): JSX.Element {
  const {
    id,
    source,
    sourceHandleId,
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    style,
    markerEnd,
  } = props;

  // v0.20.10: ユーザー要求「ポート位置は動かさず、ポート接続後はエッジの起点を
  // ポートではなくブロックにしてほしい」への対応。React Flow は sourceX/Y に
  // Handle center 座標 (= node 境界 + 12 px 外側、Handle width=24 のため) を
  // 渡してくる。これを 12 px 内側に補正することで edge の path が node 境界
  // に当たる見た目になる。chevron / Handle 自体は元の位置のまま。
  //
  // v0.20.12: source / target ともに 12 px 補正 (= 両端を node 境界に揃える)。
  // path 終点 = node 境界、矢印先端 = node 境界に綺麗に触れる、矢印 base は
  // path 方向の逆側 (= node 外側、入力ポート Left pos の場合) に伸びる。
  const adjustedSrc = adjustToBorder(sourceX, sourceY, sourcePosition);
  const adjustedTgt = adjustToBorder(targetX, targetY, targetPosition);

  const [edgePath] = getSmoothStepPath({
    sourceX: adjustedSrc.x,
    sourceY: adjustedSrc.y,
    targetX: adjustedTgt.x,
    targetY: adjustedTgt.y,
    sourcePosition,
    targetPosition,
    // リファレンスツール流: 折れ角は直角 (= radius 0)
    borderRadius: 0,
  });

  return (
    <>
      {/* v0.20.11: markerEnd 復活。target 座標を矢印サイズ分外側に置いた
          ことで矢印 head が node 境界に綺麗に当たる位置に描画される。 */}
      <BaseEdge id={id} path={edgePath} style={style} markerEnd={markerEnd} />
      {/* 透明・太いストロークの overlay path で hit area を拡大。
          ``pointerEvents: "stroke"`` でストローク領域のみクリック判定 (= 細い
          描画 path との見た目のズレを最小化)。 */}
      <path
        d={edgePath}
        fill="none"
        stroke="transparent"
        strokeWidth={20}
        style={{ cursor: "crosshair", pointerEvents: "stroke" }}
        onPointerDown={(e) => {
          // 左ボタンのみ反応 (= 右ドラッグはキャンバス pan)
          if (e.button !== 0) return;
          if (_handler === null) return;
          e.stopPropagation();
          const srcIdx =
            sourceHandleId !== null && sourceHandleId !== undefined
              ? parseInt(sourceHandleId, 10) || 0
              : 0;
          _handler({
            src: source,
            src_idx: srcIdx,
            startScreenX: e.clientX,
            startScreenY: e.clientY,
          });
        }}
      />
    </>
  );
}
