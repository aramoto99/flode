// Scope グラフ (uPlot canvas) + 凡例を 1 枚の PNG に合成し、クリップボードへ
// コピー (失敗時はダウンロードへ fallback) するユーティリティ。
//
// uPlot の凡例は canvas ではなく DOM (table) なので、canvas をそのまま toBlob
// すると凡例が欠ける。html2canvas 等の依存を増やさない方針 (ADR-0023) に沿って、
// plot canvas を描画したうえで凡例を手描きで合成する。

import { resolveSignalColor } from "./scopeSettings";
import type { SignalSettings } from "../types/api";

export interface LegendEntry {
  label: string;
  color: string;
}

/** scope の凡例 (label + color) を導出する。
 *
 * ``buildOptions`` の series 構築と同じ規約: 単一信号は ``scopeId``、複数は
 * ``scopeId[i]``。色は per-signal 設定 → 8 色 fallback。
 */
export function deriveLegend(
  scopeId: string,
  nSignals: number,
  resolvedSignals: Record<string, SignalSettings> | undefined,
): LegendEntry[] {
  return Array.from({ length: nSignals }, (_, i) => ({
    label: nSignals === 1 ? scopeId : `${scopeId}[${i}]`,
    color: resolveSignalColor(resolvedSignals, i),
  }));
}

/** uPlot plot canvas の下に凡例行を合成した新しい canvas を返す (白背景)。 */
export function compositeScopeImage(
  plotCanvas: HTMLCanvasElement,
  legend: LegendEntry[],
): HTMLCanvasElement {
  const dpr = window.devicePixelRatio || 1;
  const w = plotCanvas.width; // device px (uPlot は dpr 込みで canvas を作る)
  const h = plotCanvas.height;
  const legendH = legend.length > 0 ? Math.round(26 * dpr) : 0;

  const out = document.createElement("canvas");
  out.width = w;
  out.height = h + legendH;
  const ctx = out.getContext("2d");
  if (!ctx) return out;

  // 白背景 (uPlot canvas は透過のことがあるため)
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, out.width, out.height);
  ctx.drawImage(plotCanvas, 0, 0);

  if (legend.length > 0) {
    const fontPx = Math.round(11 * dpr);
    const sq = Math.round(10 * dpr);
    const gap = Math.round(6 * dpr);
    const padX = Math.round(8 * dpr);
    ctx.font = `${fontPx}px system-ui, "Segoe UI", sans-serif`;
    ctx.textBaseline = "middle";
    let x = padX;
    const y = h + legendH / 2;
    for (const { label, color } of legend) {
      ctx.fillStyle = color;
      ctx.fillRect(x, y - sq / 2, sq, sq);
      x += sq + gap;
      ctx.fillStyle = "#1e293b"; // slate-800
      ctx.fillText(label, x, y);
      x += ctx.measureText(label).width + gap * 3;
    }
  }
  return out;
}

/** canvas を PNG にして clipboard へコピー。非対応 / 失敗時は download に fallback。
 *
 * @returns 実際に行った操作 (``"copied"`` / ``"downloaded"``)。
 * @throws toBlob が null を返した場合 (= 描画不能)。
 */
export async function copyOrDownloadCanvas(
  canvas: HTMLCanvasElement,
  filename: string,
): Promise<"copied" | "downloaded"> {
  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, "image/png"),
  );
  if (!blob) throw new Error("canvas.toBlob returned null");

  // クリップボード優先 (= ユーザー選択)。ClipboardItem 非対応ブラウザや
  // 権限拒否時は download に fallback して必ず保存手段を確保する。
  try {
    if (
      typeof ClipboardItem !== "undefined" &&
      navigator.clipboard?.write !== undefined
    ) {
      await navigator.clipboard.write([
        new ClipboardItem({ "image/png": blob }),
      ]);
      return "copied";
    }
  } catch {
    // fall through to download
  }

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
  return "downloaded";
}

/** plot canvas + 凡例を合成して clipboard / download する一括ヘルパ。 */
export async function exportScopeImage(
  plotCanvas: HTMLCanvasElement,
  legend: LegendEntry[],
  filename: string,
): Promise<"copied" | "downloaded"> {
  const composed = compositeScopeImage(plotCanvas, legend);
  return copyOrDownloadCanvas(composed, filename);
}
