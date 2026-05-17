// Drag 範囲選択 (rubber-band) でエッジが選ばれない問題の補完用 geometry。
//
// React Flow v12 の UserSelection は「選択ノードに接続している edge」だけ
// 選択する (= ノードに片端も触らずに edge 中央を矩形で囲っても無視される)。
// pyflw 側で onSelectionEnd の最終 userSelectionRect を取り、edge の step
// polyline と矩形の交差判定を自前で行うために本モジュールを使う。

export interface Point {
  x: number;
  y: number;
}

/** 左上 ``(x, y)`` + width / height で表現された axis-aligned 矩形 (flow 座標)。 */
export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

function isPointInsideRect(p: Point, r: Rect): boolean {
  return p.x >= r.x && p.x <= r.x + r.w && p.y >= r.y && p.y <= r.y + r.h;
}

/**
 * 線分 ``p1 - p2`` が axis-aligned 矩形と交差するか判定する。
 *
 * 真偽判定のみ (= 交点座標は不要)。判定アルゴリズムは Liang-Barsky 風で、
 * 線分を ``p1 + t * (p2 - p1)`` (``t ∈ [0,1]``) と書き、矩形の各辺で ``t`` の
 * 上下限を絞り込む。
 *
 * 軸並行な線分 (= ``p1.x === p2.x`` 等) も特殊扱いせず汎用ロジックで処理する
 * (= 分母ゼロが出るが、その軸では矩形範囲内かどうかだけで判定できる)。
 */
export function segmentIntersectsRect(p1: Point, p2: Point, r: Rect): boolean {
  // 端点が矩形内なら即 true (高速 path)
  if (isPointInsideRect(p1, r) || isPointInsideRect(p2, r)) return true;

  const dx = p2.x - p1.x;
  const dy = p2.y - p1.y;
  const xMin = r.x;
  const xMax = r.x + r.w;
  const yMin = r.y;
  const yMax = r.y + r.h;

  // Liang-Barsky: 線分パラメータ t ∈ [tEnter, tExit] を矩形 4 辺で絞り込む
  let tEnter = 0;
  let tExit = 1;

  const clip = (p: number, q: number): boolean => {
    // p * t <= q を満たす範囲に t を制約する
    if (p === 0) {
      // 線分が当該辺と平行: q < 0 なら矩形外
      return q >= 0;
    }
    const t = q / p;
    if (p < 0) {
      if (t > tExit) return false;
      if (t > tEnter) tEnter = t;
    } else {
      if (t < tEnter) return false;
      if (t < tExit) tExit = t;
    }
    return true;
  };

  // 4 つの不等式: p1.x + t*dx >= xMin, <= xMax, p1.y + t*dy >= yMin, <= yMax
  if (!clip(-dx, p1.x - xMin)) return false;
  if (!clip(dx, xMax - p1.x)) return false;
  if (!clip(-dy, p1.y - yMin)) return false;
  if (!clip(dy, yMax - p1.y)) return false;

  return tEnter <= tExit;
}

/**
 * 折れ線 (polyline = 連続した線分) が矩形と交差するか判定する。
 *
 * 1 つでも segment が交差すれば ``true``。``points.length < 2`` は ``false``
 * (= 単点や空配列は線分を持たない)。
 */
export function polylineIntersectsRect(points: readonly Point[], r: Rect): boolean {
  if (points.length < 2) return false;
  for (let i = 0; i < points.length - 1; i++) {
    if (segmentIntersectsRect(points[i], points[i + 1], r)) return true;
  }
  return false;
}

/**
 * リファレンスツール流 step edge (90° 折れ線、``borderRadius=0``) の polyline を返す。
 *
 * **典型ケース** (= 出力ポート Right → 入力ポート Left、``sx < tx``) を 3-segment
 * polyline で近似する: ``(sx, sy) → (midX, sy) → (midX, ty) → (tx, ty)``
 * (``midX = (sx + tx) / 2``)。
 *
 * 既知の制限: ``tx < sx`` (= 逆向き接続 / 帰還ループ) は React Flow が
 * ``offset=20px`` を加えた 5-point U-turn path で描画するため、本近似だと
 * ``sx ± 20px`` / ``tx ± 20px`` 付近の折り返し領域だけを横切る選択矩形では
 * **偽陰性** (= 本来選択されるべき edge が選ばれない) が生じうる。pyflw の
 * 典型モデルは左→右の信号フローのため実害は限定的。U-turn 多発モデルで
 * 顕在化したら ``getSmoothStepPath`` の path 文字列を parse する実装に
 * 差し替える。
 *
 * ``computeStepEdgePolyline`` 経由でのみ呼ばれる (= module 内 helper)。
 */
function getStepEdgePolyline(
  sx: number,
  sy: number,
  tx: number,
  ty: number,
): Point[] {
  const midX = (sx + tx) / 2;
  return [
    { x: sx, y: sy },
    { x: midX, y: sy },
    { x: midX, y: ty },
    { x: tx, y: ty },
  ];
}

/** ``computeStepEdgePolyline`` が必要とする端点ノードの最小情報。 */
export interface EdgeEndpointNode {
  position: { x: number; y: number };
  width: number;
  height: number;
  nInputs: number;
  nOutputs: number;
  /** ``true`` で左右反転 (出力が左辺・入力が右辺) */
  flipped?: boolean;
}

/**
 * 2 ノードと port index から、レンダリング済みの step edge と同じ polyline
 * (4 点 = 3 セグメント) を flow 座標で計算する。
 *
 * Handle Y は ``BlockNodeView`` の uniform 配置式 ``(idx+1)*h/(n+1)`` に合わせる
 * (= triangle-r / circle shape は nOut=1 なので同式で ``h/2`` を返し、結果一致)。
 * Handle X はブロックの左右辺 (= ``BranchableEdge`` の ``adjustToBorder`` 後の
 * 描画端点) と一致させる。
 */
export function computeStepEdgePolyline(
  src: EdgeEndpointNode,
  srcHandleIdx: number,
  dst: EdgeEndpointNode,
  dstHandleIdx: number,
): Point[] {
  const srcFlipped = src.flipped ?? false;
  const dstFlipped = dst.flipped ?? false;
  // 非反転: output = 右辺、input = 左辺。反転: output = 左辺、input = 右辺。
  const sx = src.position.x + (srcFlipped ? 0 : src.width);
  const tx = dst.position.x + (dstFlipped ? dst.width : 0);
  const sy =
    src.position.y +
    ((srcHandleIdx + 1) * src.height) / (src.nOutputs + 1);
  const ty =
    dst.position.y +
    ((dstHandleIdx + 1) * dst.height) / (dst.nInputs + 1);
  return getStepEdgePolyline(sx, sy, tx, ty);
}
