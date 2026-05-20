// XYGraph の可視化: 入力 0 = x, 入力 1 = y のパラメトリック散布線プロット。
// ADR-0023 §Decision §(2): uPlot は単調 X 前提のためパラメトリック軌跡には
// 不向き。XYGraphView は引き続き canvas 自前で描画する。
// ADR-0023 で SoA 化した ScopeBuffer (列指向 Float64Array) から x = values[0],
// y = values[1] を index ベースで読む。

import { useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { exportScopeImage } from "../lib/scopeImageExport";
import type { ScopeBuffer } from "../store/appStore";
import { pushToast } from "../store/toastStore";

interface XYGraphViewProps {
  scopeId: string;
  buffer: ScopeBuffer;
  xLabel?: string;
  yLabel?: string;
}

export function XYGraphView({
  scopeId,
  buffer,
  xLabel = "x",
  yLabel = "y",
}: XYGraphViewProps): JSX.Element {
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // 描画本体。data 変更時と resize 時の両方から呼ぶため useCallback で安定化。
  const draw = useCallback((): void => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const { width, height } = canvas.getBoundingClientRect();
    if (width === 0 || height === 0) return;
    canvas.width = width;
    canvas.height = height;
    ctx.clearRect(0, 0, width, height);

    // SoA: values[0] = x 列、values[1] = y 列。両方揃っていない / サンプル <2 ならスキップ。
    const xCol = buffer.values[0];
    const yCol = buffer.values[1];
    if (!xCol || !yCol || buffer.length < 2) {
      ctx.fillStyle = "#64748b";
      ctx.font = "12px sans-serif";
      ctx.fillText(t("xygraph.no_data"), 8, 16);
      return;
    }

    const padding = 28;
    const plotW = width - padding * 2;
    const plotH = height - padding * 2;

    let xMin = Infinity;
    let xMax = -Infinity;
    let yMin = Infinity;
    let yMax = -Infinity;
    for (let i = 0; i < buffer.length; i += 1) {
      const x = xCol[i]!;
      const y = yCol[i]!;
      if (x < xMin) xMin = x;
      if (x > xMax) xMax = x;
      if (y < yMin) yMin = y;
      if (y > yMax) yMax = y;
    }
    if (
      !Number.isFinite(xMin) ||
      !Number.isFinite(xMax) ||
      !Number.isFinite(yMin) ||
      !Number.isFinite(yMax)
    ) {
      return;
    }
    const xRange = xMax - xMin || 1;
    const yRange = yMax - yMin || 1;

    // 軸 (X=0, Y=0 を含むなら描画)
    ctx.strokeStyle = "#cbd5e1";
    ctx.lineWidth = 0.6;
    if (xMin <= 0 && xMax >= 0) {
      const x0 = padding + ((0 - xMin) / xRange) * plotW;
      ctx.beginPath();
      ctx.moveTo(x0, padding);
      ctx.lineTo(x0, padding + plotH);
      ctx.stroke();
    }
    if (yMin <= 0 && yMax >= 0) {
      const y0 = padding + plotH - ((0 - yMin) / yRange) * plotH;
      ctx.beginPath();
      ctx.moveTo(padding, y0);
      ctx.lineTo(padding + plotW, y0);
      ctx.stroke();
    }

    // 枠
    ctx.strokeStyle = "#e2e8f0";
    ctx.lineWidth = 1;
    ctx.strokeRect(padding, padding, plotW, plotH);

    // パラメトリック折れ線
    ctx.beginPath();
    ctx.strokeStyle = "#2563eb";
    ctx.lineWidth = 1.5;
    for (let i = 0; i < buffer.length; i += 1) {
      const x = xCol[i]!;
      const y = yCol[i]!;
      const px = padding + ((x - xMin) / xRange) * plotW;
      const py = padding + plotH - ((y - yMin) / yRange) * plotH;
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.stroke();

    // 最新点をマーカー
    const lastX = xCol[buffer.length - 1]!;
    const lastY = yCol[buffer.length - 1]!;
    if (Number.isFinite(lastX) && Number.isFinite(lastY)) {
      const px = padding + ((lastX - xMin) / xRange) * plotW;
      const py = padding + plotH - ((lastY - yMin) / yRange) * plotH;
      ctx.beginPath();
      ctx.fillStyle = "#dc2626";
      ctx.arc(px, py, 3, 0, Math.PI * 2);
      ctx.fill();
    }

    // ラベル
    ctx.fillStyle = "#64748b";
    ctx.font = "10px sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(scopeId, 8, 12);
    ctx.textAlign = "center";
    ctx.fillText(xLabel, padding + plotW / 2, height - 4);
    ctx.save();
    ctx.translate(10, padding + plotH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText(yLabel, 0, 0);
    ctx.restore();
    ctx.textAlign = "right";
    ctx.fillText(
      `[${xMin.toFixed(2)}, ${xMax.toFixed(2)}] × [${yMin.toFixed(2)}, ${yMax.toFixed(2)}]`,
      width - 8,
      12,
    );
  }, [scopeId, buffer, xLabel, yLabel, t]);

  // data 変更時の再描画
  useEffect(() => {
    draw();
  }, [draw]);

  // 親サイズ追従 (= 出力ペインのリサイズ/最大化で再描画、Scope と同じ挙動)。
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ro = new ResizeObserver(() => draw());
    ro.observe(canvas);
    return () => ro.disconnect();
  }, [draw]);

  // グラフ画像をクリップボードへコピー (失敗時 download)。XYGraph は全要素を
  // canvas に直接描画しているため凡例合成は不要 (= 空 legend で白背景のみ付与)。
  const handleCopyImage = async (): Promise<void> => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    try {
      const result = await exportScopeImage(canvas, [], `${scopeId}.png`);
      pushToast({
        severity: "info",
        message: t(
          result === "copied"
            ? "scope.copy_image.copied"
            : "scope.copy_image.downloaded",
        ),
      });
    } catch {
      pushToast({ severity: "error", message: t("scope.copy_image.error") });
    }
  };

  return (
    <div className="flex h-full w-full flex-col border border-slate-200 bg-white">
      {/* 薄いヘッダー (= 画像コピーボタンの置き場、Scope と統一)。 */}
      <div className="flex h-6 shrink-0 items-center gap-1 border-b border-slate-200 bg-slate-50 px-2 text-[11px] text-slate-700">
        <div className="flex-1" />
        {buffer.length > 0 && (
          <button
            type="button"
            title={t("scope.button.copy_image", "Copy image")}
            onClick={() => void handleCopyImage()}
            className="flex h-4 w-4 items-center justify-center rounded text-slate-500 hover:bg-slate-200 hover:text-slate-800"
          >
            <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <circle cx="8.5" cy="8.5" r="1.5" />
              <path d="M21 15l-5-5L5 21" />
            </svg>
          </button>
        )}
      </div>
      <div className="relative flex-1">
        <canvas ref={canvasRef} className="absolute inset-0" />
      </div>
    </div>
  );
}
