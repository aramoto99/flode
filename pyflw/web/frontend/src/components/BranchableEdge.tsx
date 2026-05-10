// v0.20.6: Simulink 互換の「既存配線から分岐配線を引く」を実現する Custom Edge。
//
// 既存の React Flow built-in ``"step"`` edge と同じ見た目 (= ステップ折れ線
// + 矢印 head) を維持しつつ、path に invisible で太い overlay path を重ね、
// ``onPointerDown`` で drag 開始を捕捉する。
//
// drag 開始の通知は global subscription pattern (= ``setBranchStartHandler``)
// で DiagramCanvas に届ける (= React Context を edge component に流すと
// 全 edge が再 render するため避ける)。

import { BaseEdge, type EdgeProps, getSmoothStepPath } from "@xyflow/react";

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
  } = props;

  const [edgePath] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    // Simulink 流: 折れ角は直角 (= radius 0)
    borderRadius: 0,
  });

  return (
    <>
      {/* v0.20.7: markerEnd を渡さない (= 矢印 head なし)。React Flow は markerEnd
          を node 境界の外側に描画するため隙間が生じる。Simulink でも接続済み
          配線は純粋な線で、信号方向は node 配置で把握する慣習。 */}
      <BaseEdge id={id} path={edgePath} style={style} />
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
