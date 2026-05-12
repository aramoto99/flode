// ADR-0052 §(4) Stage 3: HTML5 drag-drop の共通ヘルパー (= タブを別 pane に
// drag するための MIME + drop 位置判定)。
//
// **採用方針**: HTML5 native drag-drop API、`@dnd-kit` 不採用 (= ADR-0019
// `BlockPalette` / v0.28.1 `FileBrowser` で確立した path を踏襲)。
//
// **MIME**:
// - `application/x-pyflw-tab-ref`: タブ (= 1 ファイル) の drag を表す、
//   値は `filePath` 文字列
//
// **drop 位置判定**: pane の矩形を 5 領域 (center 50% + 4 端 25%) に分割。
// drop 位置に応じて挙動を変える (= ADR-0052 §(1) 仕様):
// - center → タブ追加 (= 既存 pane 内、Stage 3 で「タブ群」化は未実装、
//   現状は paneId 変更なしで no-op、Stage 4 候補)
// - top / right / bottom / left → split で新 pane 化

/** タブ drag 用 MIME type。値は filePath 文字列。 */
export const PYFLW_TAB_REF_MIME = "application/x-pyflw-tab-ref";

/** drop 位置を表す enum (= pane 矩形内の領域)。 */
export type DropZone = "center" | "top" | "right" | "bottom" | "left";

/** pane 矩形内のマウス座標から drop zone を計算。
 *
 * 5 領域 (= center 50% × 50% + 4 端 25% 各) に分割。
 * 四隅 (= top-left 等) は近い端を採用する菱形ルール:
 *   - rect 内座標を (rx, ry) で 0〜1 正規化
 *   - 中央領域 = 0.25 ≤ rx ≤ 0.75 かつ 0.25 ≤ ry ≤ 0.75
 *   - 中央外: max(|rx - 0.5|, |ry - 0.5|) で支配軸を判定
 *
 * @param rect pane の DOMRect (`getBoundingClientRect()`)
 * @param clientX マウス clientX
 * @param clientY マウス clientY
 * @returns DropZone
 */
export function computeDropZone(
  rect: DOMRect,
  clientX: number,
  clientY: number,
): DropZone {
  if (rect.width <= 0 || rect.height <= 0) return "center";
  const rx = (clientX - rect.left) / rect.width;
  const ry = (clientY - rect.top) / rect.height;
  // 中央 50% × 50%
  if (rx >= 0.25 && rx <= 0.75 && ry >= 0.25 && ry <= 0.75) return "center";
  // 中央外: x / y のいずれが端に近いかで判定
  const dx = rx < 0.5 ? rx : 1 - rx;
  const dy = ry < 0.5 ? ry : 1 - ry;
  if (dx < dy) {
    return rx < 0.5 ? "left" : "right";
  }
  return ry < 0.5 ? "top" : "bottom";
}

/** drop zone を `splitTree.insertSplit` の (orientation, position) に変換。
 *
 * - top   → orientation=vertical, position=before (= 新葉を上に)
 * - bottom → orientation=vertical, position=after  (= 新葉を下に)
 * - left  → orientation=horizontal, position=before (= 新葉を左に)
 * - right → orientation=horizontal, position=after  (= 新葉を右に)
 * - center → null (= split しない、タブ追加扱い、Stage 3 では no-op)
 */
export function dropZoneToSplit(
  zone: DropZone,
): { orientation: "horizontal" | "vertical"; position: "before" | "after" } | null {
  switch (zone) {
    case "top":
      return { orientation: "vertical", position: "before" };
    case "bottom":
      return { orientation: "vertical", position: "after" };
    case "left":
      return { orientation: "horizontal", position: "before" };
    case "right":
      return { orientation: "horizontal", position: "after" };
    case "center":
      return null;
  }
}

/** drop zone に対応する overlay 矩形を計算 (= visual feedback 用)。
 * 中央 / 4 端それぞれで pane 矩形の対応する半分 (or 中央 50%) を返す。
 */
export function dropZoneOverlayRect(
  rect: DOMRect,
  zone: DropZone,
): { left: number; top: number; width: number; height: number } {
  const { left, top, width, height } = rect;
  switch (zone) {
    case "center":
      return {
        left: left + width * 0.25,
        top: top + height * 0.25,
        width: width * 0.5,
        height: height * 0.5,
      };
    case "top":
      return { left, top, width, height: height * 0.5 };
    case "bottom":
      return { left, top: top + height * 0.5, width, height: height * 0.5 };
    case "left":
      return { left, top, width: width * 0.5, height };
    case "right":
      return { left: left + width * 0.5, top, width: width * 0.5, height };
  }
}
