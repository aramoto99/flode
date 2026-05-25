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

/** 連続する重複頂点 (= 長さ 0 セグメント) を除去する。
 *  via 経由 polyline で via が trunk 上に乗る等の退化ケースで生じる。 */
function dedupeConsecutive(points: readonly Point[]): Point[] {
  const out: Point[] = [];
  for (const p of points) {
    const last = out[out.length - 1];
    if (last && last.x === p.x && last.y === p.y) continue;
    out.push({ x: p.x, y: p.y });
  }
  return out;
}

/**
 * リファレンスツール流 step edge (90° 折れ線、``borderRadius=0``) の polyline を返す。
 *
 * **典型ケース** (= 出力ポート Right → 入力ポート Left、``sx < tx``) を 3-segment
 * polyline で近似する: ``(sx, sy) → (midX, sy) → (midX, ty) → (tx, ty)``
 * (``midX = (sx + tx) / 2``)。
 *
 * ADR-0057: 手動分岐点 ``via`` が与えられた場合、``via`` を**必ず通る** Z 折れ
 * ``(sx,sy) → (via.x,sy) → (via.x,via.y) → (via.x,ty) → (tx,ty)`` を返す。
 * 同一 ``(source, sourceHandle)`` グループの全枝は ``sy`` / ``via`` が共通なので
 * ``(sx,sy) → (via.x,sy) → via`` の trunk を共有し ``via`` で分岐する。これにより
 * **● 位置 (= via) が定義上ワイヤ上に乗る** (描画と ● 算出の幾何 SSOT)。連続する
 * 退化頂点は ``dedupeConsecutive`` で除去する。
 *
 * 既知の制限 (``via`` 無し時のみ): ``tx < sx`` (= 逆向き接続 / 帰還ループ) は
 * React Flow が ``offset=20px`` を加えた 5-point U-turn path で描画するため、本
 * 近似だと ``sx ± 20px`` / ``tx ± 20px`` 付近の折り返し領域だけを横切る選択矩形
 * では **偽陰性** (= 本来選択されるべき edge が選ばれない) が生じうる。pyflw の
 * 典型モデルは左→右の信号フローのため実害は限定的。U-turn 多発モデルで顕在化
 * したら ``getSmoothStepPath`` の path 文字列を parse する実装に差し替える。
 * ``via`` 経由時は折れ線が ``via`` で確定するため U-turn でも破綻しにくい。
 *
 * ``computeStepEdgePolyline`` 経由でのみ呼ばれる (= module 内 helper)。
 *
 * @param via optional な手動分岐点 (flow 絶対座標)。指定時は必ずこの点を通る。
 */
export function getStepEdgePolyline(
  sx: number,
  sy: number,
  tx: number,
  ty: number,
  via?: Point,
): Point[] {
  if (via) {
    return dedupeConsecutive([
      { x: sx, y: sy },
      { x: via.x, y: sy },
      { x: via.x, y: via.y },
      { x: via.x, y: ty },
      { x: tx, y: ty },
    ]);
  }
  const midX = (sx + tx) / 2;
  return [
    { x: sx, y: sy },
    { x: midX, y: sy },
    { x: midX, y: ty },
    { x: tx, y: ty },
  ];
}

/**
 * 折れ線を SVG path 文字列 (``M x,y L x,y ...``) に変換する。
 *
 * ADR-0057: via 経由 edge を ``BranchableEdge`` が ``getSmoothStepPath`` を使わず
 * 自前 path で描画する際に使う (= 描画と ● 算出が同一 polyline を共有する SSOT)。
 * 角は直角のまま (= ``borderRadius=0`` 相当)。``points.length < 2`` は空文字を返す。
 */
export function polylineToSvgPath(points: readonly Point[]): string {
  if (points.length < 2) return "";
  const [head, ...rest] = points;
  return (
    `M${head.x},${head.y}` + rest.map((p) => `L${p.x},${p.y}`).join("")
  );
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
  via?: Point,
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
  // ADR-0057: 手動分岐点 (via) があれば必ず経由する Z 折れを返す (= 描画と ● 算出
  // の幾何 SSOT)。via 無しは従来の midX 近似 (後方互換)。
  return getStepEdgePolyline(sx, sy, tx, ty, via);
}
