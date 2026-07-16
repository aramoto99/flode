// 自前 canvas 描画 (XYGraphView 等) を高 DPI ディスプレイで鮮明に保つための
// バッキングストア サイジング ユーティリティ。
//
// 背景: canvas のバッキングストア (canvas.width/height) を CSS px 等倍で作ると、
// devicePixelRatio > 1 の環境 (Windows のスケーリング 150% 等) ではブラウザが
// 拡大表示するためピンボケする。バッキングストアを CSS px × dpr にし、描画
// コンテキストを dpr 倍スケールすることで、描画コード側は従来どおり CSS px の
// 座標系で描けるまま、表示は物理ピクセル解像度で鮮明になる。
//
// なぜ独立ファイルか: jsdom は canvas 2d コンテキスト非対応で XYGraphView の
// draw() 全体を単体テストできない。このサイジング判定だけを純粋関数として
// 切り出すことで、dpr 倍計算と ctx.scale 呼び出しを mock で検証可能にしている
// (= テスト可能な seam)。HiDPI 対応が必要な他の自前 canvas 描画でも再利用できる。

/** canvas のバッキングストアを HiDPI 対応でサイズし、ctx を dpr 倍スケールする。
 *
 * ``canvas.width`` / ``canvas.height`` への代入は 2D コンテキストの状態
 * (transform 含む) を単位行列にリセットするため、毎フレーム呼んでも
 * ``scale(dpr, dpr)`` が多重適用されることはない。呼び出し後は CSS px 座標で
 * 描画してよい (= 既存の描画ロジックを変更しなくてよい)。
 *
 * @param canvas サイズ対象の canvas。
 * @param ctx ``canvas`` から取得した 2D コンテキスト。
 * @param cssWidth CSS px でのコンテナ幅 (= 表示幅)。
 * @param cssHeight CSS px でのコンテナ高さ (= 表示高さ)。
 * @param dpr デバイスピクセル比。既定は ``window.devicePixelRatio`` (SSR や
 *   未定義環境では本体で 1 に丸められる)。0 以下や非有限値は 1 にフォールバック
 *   する (= フォールバック判定は本体に一本化)。
 */
export function sizeCanvasToDisplay(
  canvas: HTMLCanvasElement,
  ctx: CanvasRenderingContext2D,
  cssWidth: number,
  cssHeight: number,
  dpr: number = typeof window !== "undefined" ? window.devicePixelRatio : 1,
): void {
  const ratio = Number.isFinite(dpr) && dpr > 0 ? dpr : 1;
  canvas.width = Math.round(cssWidth * ratio);
  canvas.height = Math.round(cssHeight * ratio);
  ctx.scale(ratio, ratio);
}
